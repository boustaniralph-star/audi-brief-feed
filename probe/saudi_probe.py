#!/usr/bin/env python3
"""One-off feasibility probe for a Saudi market page (not part of the brief), round 3."""
import datetime as dt, html, json, re, time, urllib.request, concurrent.futures as cf
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
AST = dt.timezone(dt.timedelta(hours=3))
def get(url, t=25):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t)
        return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", type(e).__name__), ""
def text(h):
    h = re.sub(r"(?is)<(script|style|nav|header|footer).*?</\1>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()
def raw(sym, rng):
    st, b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d", 20)
    try: return json.loads(b)["chart"]["result"][0]
    except Exception: return None
def day(t): return dt.datetime.fromtimestamp(t, AST).date().isoformat()

print("=== A. Sector indices: meta (latest) ===")
SECT = ["TASI", "TENI", "TMTI", "TCGI", "TCSI", "TTNI", "TCDI", "TCPI", "TMDI", "TRLI", "TFSI", "TFBI", "THEI", "TPBI", "TBNI",
        "TDFI", "TINI", "TTSI", "TUTI", "TRTI", "TREI", "TSSI", "TDAI", "THCI", "TFRI", "TMSI", "TCSS", "TPHI", "TRMI", "TSWI"]
sec = {}
for s in SECT:
    r = raw(f"^{s}.SR", "5d")
    if not r: continue
    m = r["meta"]; px = m.get("regularMarketPrice"); pc = m.get("chartPreviousClose") or m.get("previousClose")
    nb = sum(1 for c in r["indicators"]["quote"][0].get("close") or [] if c)
    if px and pc:
        sec[s] = {"name": m.get("longName") or m.get("shortName"), "px": px, "pc": pc, "d": round((px/pc-1)*100, 2),
                  "t": day(m.get("regularMarketTime", 0)), "bars5d": nb}
print("PREVIEW_SECTORS " + json.dumps(sec, separators=(",", ":")))

print("=== B. Stocks: 1y bars + latest meta ===")
codes = [c for a, b in ((1010, 1835), (2001, 2390), (3001, 3100), (4001, 4350), (5110, 5111), (6001, 6100), (7010, 7210), (8010, 8320)) for c in range(a, b)]
def stock(c):
    r = raw(f"{c}.SR", "1y")
    if not r or not r.get("timestamp"): return c, None
    m = r["meta"]; q = r["indicators"]["quote"][0]
    bars = {}
    for t, cl, v in zip(r["timestamp"], q["close"], q["volume"]):
        if cl: bars[day(t)] = (cl, v or 0)
    px, mt = m.get("regularMarketPrice"), m.get("regularMarketTime")
    if px and mt: bars[day(mt)] = (px, m.get("regularMarketVolume") or bars.get(day(mt), (0, 0))[1])
    return c, {"n": m.get("longName") or m.get("shortName"), "bars": sorted(bars.items())}
t0 = time.time(); S = {}
with cf.ThreadPoolExecutor(12) as ex:
    for c, d in ex.map(stock, codes):
        if d and len(d["bars"]) > 5: S[c] = d
last = max(d["bars"][-1][0] for d in S.values())
print(f"{len(S)} stocks in {time.time()-t0:.0f}s; latest session {last}; on it: {sum(1 for d in S.values() if d['bars'][-1][0] == last)}")
out = []
for c, d in S.items():
    b = d["bars"]
    if b[-1][0] != last: continue
    px = b[-1][1][0]; pc = b[-2][1][0]; w0 = b[-6][1][0] if len(b) > 6 else b[0][1][0]
    y0 = next((x[1][0] for x in b if x[0] >= last[:4] + "-01-01"), b[0][1][0])
    hi = max(x[1][0] for x in b[-250:-1]); lo = min(x[1][0] for x in b[-250:-1])
    v20 = sum(x[1][0] * x[1][1] for x in b[-21:-1]) / max(1, len(b[-21:-1]))
    out.append({"c": c, "n": (d["n"] or "")[:30], "px": round(px, 2), "d": round((px/pc-1)*100, 2), "w": round((px/w0-1)*100, 2),
                "y": round((px/y0-1)*100, 2), "hi": int(px > hi), "lo": int(px < lo), "val": round(px * b[-1][1][1] / 1e6, 1), "v20": round(v20 / 1e6, 1)})
up = sum(1 for r in out if r["d"] > 0); dn = sum(1 for r in out if r["d"] < 0)
print(f"breadth {last}: up {up}, down {dn}, flat {len(out)-up-dn}; 52w highs {sum(r['hi'] for r in out)}, lows {sum(r['lo'] for r in out)}; "
      f"turnover SAR {sum(r['val'] for r in out):.0f} mn vs 20d avg {sum(r['v20'] for r in out):.0f} mn")
print("PREVIEW_STOCKS " + json.dumps(out, separators=(",", ":")))

print("=== C. Sector membership from Argaam's menu ===")
st, h = get("https://www.argaam.com/en")
t = text(re.sub(r"(?is)<(script|style).*?</\1>", " ", h))
names = ["Energy", "Materials", "Capital Goods", "Commercial & Professional Svc", "Transportation", "Consumer Durables & Apparel",
         "Consumer Services", "Media and Entertainment", "Consumer Discretionary Distribution & Retail", "Consumer Staples Distribution & Retail",
         "Food & Beverages", "Household & Personal Products", "Health Care Equipment & Svc", "Pharma, Biotech & Life Science", "Banks",
         "Financial Services", "Insurance", "Software & Services", "Telecommunication Services", "Utilities", "Real Estate Mgmt & Dev't", "REITs"]
raw_menu = re.sub(r"<[^>]+>", "\n", re.sub(r"(?is)<(script|style).*?</\1>", " ", h))
lines = [html.unescape(l).strip() for l in raw_menu.splitlines() if l.strip()]
mem, cur = {}, None
for l in lines:
    m = re.match(r"^(\d{4}) - (.+)$", l)
    if m and cur: mem.setdefault(cur, []).append(int(m.group(1)))
    elif not m and 2 < len(l) < 60 and not re.search(r"\d", l): cur = l
mem = {k: v for k, v in mem.items() if len(v) >= 2}
print("PREVIEW_MEMBERS " + json.dumps(mem, separators=(",", ":")))

print("=== D. Argaam event pages (table text) ===")
for p in ["/en/company/calendar/details/marketid/3", "/en/company/financial-result/market/3/fptype/3/2026/4", "/en/disclosures/ipo",
          "/en/disclosures/dividends/previous-year", "/en/disclosures/dividends", "/en/company/financial-result/market/3"]:
    st, b = get("https://www.argaam.com" + p)
    rowsx = []
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", b):
        cells = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", td))).strip() for td in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
        if any(cells): rowsx.append(" | ".join(cells)[:200])
    print(f"--- {p} status {st}, {len(rowsx)} table rows")
    for r in rowsx[:14]: print("   ", r)
