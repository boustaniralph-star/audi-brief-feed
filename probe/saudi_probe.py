#!/usr/bin/env python3
"""One-off feasibility probe for a Saudi market page (not part of the brief), round 2."""
import datetime as dt, html, json, re, time, urllib.request, concurrent.futures as cf

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
def get(url, t=25):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t)
        return r.status, r.read().decode("utf-8", "replace")
    except Exception as e:
        return getattr(e, "code", type(e).__name__), ""
def text(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).strip()
def chart(sym, rng="1y"):
    st, b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range={rng}&interval=1d", 20)
    if st != 200: return None
    try:
        r = json.loads(b)["chart"]["result"][0]; q = r["indicators"]["quote"][0]
        pts = [(dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat(), c, v) for t, c, v in zip(r["timestamp"], q["close"], q["volume"]) if c]
        return {"name": r["meta"].get("longName") or r["meta"].get("shortName"), "pts": pts}
    except Exception:
        return None

print("=== A. Sector indices ===")
SECT = ["TASI", "TENI", "TMTI", "TCGI", "TCSI", "TTNI", "TCDI", "TCPI", "TMDI", "TRLI", "TFSI", "TFBI", "THEI", "TPBI", "TBNI",
        "TDFI", "TINI", "TTSI", "TUTI", "TRTI", "TREI", "TSSI", "TDAI", "THCI", "TCRI", "TCCI", "TFRI", "TDSI", "TPSI", "TSCI", "TMSI"]
sec = {}
for s in SECT:
    d = chart(f"^{s}.SR", "1y")
    if d and len(d["pts"]) > 30:
        p = d["pts"]; y0 = next((x[1] for x in p if x[0] >= p[-1][0][:4] + "-01-01"), p[0][1])
        w0 = p[-6][1] if len(p) > 6 else p[0][1]
        sec[s] = {"name": d["name"], "last": p[-1][0], "c": round(p[-1][1], 2), "d": round((p[-1][1]/p[-2][1]-1)*100, 2),
                  "w": round((p[-1][1]/w0-1)*100, 2), "y": round((p[-1][1]/y0-1)*100, 2)}
print(f"{len(sec)} sector indices found")
print("PREVIEW_SECTORS " + json.dumps(sec, separators=(",", ":")))

print("=== B. Tadawul universe by code scan (5d) ===")
cands = [c for a, b in ((1010, 1835), (2001, 2390), (3001, 3100), (4001, 4350), (5110, 5111), (6001, 6100), (7010, 7210), (8010, 8320)) for c in range(a, b)]
t0 = time.time(); found = {}
with cf.ThreadPoolExecutor(12) as ex:
    for c, d in zip(cands, ex.map(lambda c: chart(f"{c}.SR", "5d"), cands)):
        if d and d["pts"]: found[c] = d
print(f"scan: {len(found)} live tickers out of {len(cands)} codes in {time.time()-t0:.0f}s")
t0 = time.time(); full = {}
with cf.ThreadPoolExecutor(10) as ex:
    for c, d in zip(list(found), ex.map(lambda c: chart(f"{c}.SR", "1y"), list(found))):
        if d and len(d["pts"]) > 5: full[c] = d
print(f"1y history: {len(full)} tickers in {time.time()-t0:.0f}s")
last = max(d["pts"][-1][0] for d in full.values())
print("latest session:", last, "| tickers on it:", sum(1 for d in full.values() if d["pts"][-1][0] == last))
out = []
for c, d in full.items():
    p = d["pts"]
    if p[-1][0] != last or len(p) < 2: continue
    px, pc = p[-1][1], p[-2][1]
    y0 = next((x[1] for x in p if x[0] >= last[:4] + "-01-01"), p[0][1])
    hi = max(x[1] for x in p[-250:]); lo = min(x[1] for x in p[-250:])
    v20 = sum((x[1] * (x[2] or 0)) for x in p[-21:-1]) / max(1, len(p[-21:-1]))
    out.append({"c": c, "n": (d["name"] or "")[:30], "px": round(px, 2), "d": round((px/pc-1)*100, 2), "y": round((px/y0-1)*100, 2),
                "hi": int(px >= hi * 0.999), "lo": int(px <= lo * 1.001), "val": round(px * (p[-1][2] or 0) / 1e6, 1), "v20": round(v20 / 1e6, 1)})
up = sum(1 for r in out if r["d"] > 0); dn = sum(1 for r in out if r["d"] < 0)
print(f"breadth {last}: up {up}, down {dn}, flat {len(out)-up-dn}; 52w highs {sum(r['hi'] for r in out)}, lows {sum(r['lo'] for r in out)}; "
      f"turnover SAR {sum(r['val'] for r in out):.0f} mn vs 20d avg {sum(r['v20'] for r in out):.0f} mn")
print("PREVIEW_STOCKS " + json.dumps(out, separators=(",", ":")))

print("=== C. Argaam link discovery ===")
st, h = get("https://www.argaam.com/en")
links = sorted(set(re.findall(r'href="(/en/[^"#?]+)"', h)))
kw = ("dividend", "result", "calendar", "ipo", "general-assembl", "capital", "financial", "earning", "market-summary", "foreign", "tasi")
hits = [l for l in links if any(k in l.lower() for k in kw)]
print(len(links), "links;", len(hits), "relevant:", hits[:40])
for l in hits[:14]:
    st, b = get("https://www.argaam.com" + l); t = text(b)
    print(f"  {l[:70]:70s} {st} {len(t):6d} | {t[200:380]!r}")
print("=== D. Mubasher market pages ===")
for u in ["https://english.mubasher.info/markets/TDWL", "https://english.mubasher.info/countries/sa/stock-prices",
          "https://english.mubasher.info/countries/sa/companies-financial-results", "https://english.mubasher.info/countries/sa/dividends",
          "https://english.mubasher.info/countries/sa/ipos"]:
    st, b = get(u); t = text(b)
    print(f"  {u[29:]:55s} {st} {len(t):6d} | {t[300:460]!r}")
