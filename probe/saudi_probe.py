#!/usr/bin/env python3
"""One-off feasibility probe for a Saudi market page (not part of the brief). Prints what each source returns."""
import datetime as dt, html, json, re, sys, time, urllib.request, concurrent.futures as cf

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

print("=== 1. Tadawul universe (Wikipedia) ===")
st, h = get("https://en.wikipedia.org/w/index.php?title=List_of_companies_listed_on_the_Saudi_Exchange&action=raw")
rows = []
if st == 200:
    sector = ""
    for line in h.splitlines():
        m = re.match(r"^=+\s*(.*?)\s*=+$", line)
        if m: sector = m.group(1)
        for c in re.findall(r"\b(\d{4})\b", line) if line.startswith("|") else []:
            pass
    # table rows: | name || ticker || ...
    for blk in re.split(r"\n\|-", h):
        cells = [re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", c).strip() for c in re.split(r"\|\||\n\|", blk)]
        code = next((c for c in cells if re.fullmatch(r"\d{4}", c)), None)
        if code:
            name = next((c for c in cells if c and not re.fullmatch(r"[\d.,%\s-]*", c) and "style" not in c and not c.startswith("{")), "")
            rows.append({"code": code, "name": name[:40]})
print("wikipedia status", st, "rows with a 4-digit code:", len(rows), "sample", rows[:3])

print("=== 2. Yahoo daily closes for .SR stocks ===")
codes = sorted({r["code"] for r in rows}) or [str(c) for c in range(1010, 1012)]
def yh(code):
    st, b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.SR?range=1y&interval=1d", 20)
    if st != 200: return code, None
    try:
        r = json.loads(b)["chart"]["result"][0]
        q = r["indicators"]["quote"][0]; ts = r["timestamp"]
        pts = [(dt.datetime.utcfromtimestamp(t).date().isoformat(), c, v) for t, c, v in zip(ts, q["close"], q["volume"]) if c]
        return code, {"name": r["meta"].get("shortName") or r["meta"].get("longName"), "pts": pts}
    except Exception:
        return code, None
t0 = time.time(); data = {}
with cf.ThreadPoolExecutor(8) as ex:
    for code, d in ex.map(yh, codes):
        if d and len(d["pts"]) > 30: data[code] = d
print(f"yahoo: {len(data)} of {len(codes)} tickers with a year of closes, {time.time()-t0:.0f}s")
last = max((d["pts"][-1][0] for d in data.values()), default=None)
print("latest session in data:", last)

out = []
for code, d in data.items():
    p = d["pts"]
    if p[-1][0] != last or len(p) < 2: continue
    c, pc = p[-1][1], p[-2][1]
    y0 = next((x[1] for x in p if x[0] >= f"{last[:4]}-01-01"), p[0][1])
    hi = max(x[1] for x in p); lo = min(x[1] for x in p)
    out.append({"c": code, "n": (d["name"] or "")[:28], "px": round(c, 2), "d": round((c/pc-1)*100, 2), "y": round((c/y0-1)*100, 2),
                "hi": c >= hi * 0.999, "lo": c <= lo * 1.001, "val": round(c * (p[-1][2] or 0) / 1e6, 1)})
up = sum(1 for r in out if r["d"] > 0); dn = sum(1 for r in out if r["d"] < 0)
print(f"breadth {last}: up {up}, down {dn}, flat {len(out)-up-dn}, 52w highs {sum(r['hi'] for r in out)}, lows {sum(r['lo'] for r in out)}")
print("PREVIEW_STOCKS " + json.dumps(out, separators=(",", ":")))

print("=== 3. Sector indices on Yahoo ===")
for s in ["^TASI.SR", "^TBNI.SR", "^TENI.SR", "^TMTI.SR", "^TFBI.SR", "^TRLI.SR"]:
    st, b = get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}?range=5d&interval=1d", 15)
    print(s, st, len(b))

print("=== 4. Event sources ===")
probes = {
  "saudiexchange home": "https://www.saudiexchange.sa/wps/portal/saudiexchange/home?locale=en",
  "saudiexchange dividends": "https://www.saudiexchange.sa/wps/portal/saudiexchange/newsandreports/issuer-financial-calendars/dividends?locale=en",
  "saudiexchange issuer news": "https://www.saudiexchange.sa/wps/portal/saudiexchange/newsandreports/issuer-news?locale=en",
  "saudiexchange foreign ownership": "https://www.saudiexchange.sa/wps/portal/saudiexchange/newsandreports/reports-publications/trading-and-ownership-by-nationality?locale=en",
  "argaam home": "https://www.argaam.com/en",
  "argaam latest": "https://www.argaam.com/en/article/latest-news",
  "argaam dividends": "https://www.argaam.com/en/company/dividends-calendar",
  "argaam results": "https://www.argaam.com/en/company/financial-results",
  "cma news": "https://cma.org.sa/en/MediaCenter/PR/Pages/default.aspx",
  "mubasher saudi": "https://english.mubasher.info/countries/sa",
  "marketscreener tasi": "https://www.marketscreener.com/quote/index/TADAWUL-ALL-SHARE-INDEX-8389389/",
}
for k, u in probes.items():
    st, b = get(u)
    t = text(b)
    kw = [w for w in ("dividend", "Dividend", "eligib", "result", "profit", "IPO", "foreign", "net", "AGM", "General Assembly") if w in t]
    print(f"{k:34s} status {st} chars {len(t):7d} keywords {kw[:6]} | {t[:160]!r}")
