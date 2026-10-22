#!/usr/bin/env python3
"""Build series.json (close history per instrument, keyed by asOf date).
Merges the existing series.json (history carried forward) with every dated snapshot in market_data/."""
import json, glob, os, collections
HERE = os.path.dirname(os.path.abspath(__file__))
S = collections.defaultdict(dict)
out = os.path.join(HERE, "series.json")
try:
    for k, v in json.load(open(out, encoding="utf-8-sig")).items():
        S[k].update(v)
except Exception:
    pass
for f in sorted(glob.glob(os.path.join(HERE, "market_data", "*.json"))):
    try:
        d = json.load(open(f, encoding="utf-8-sig"))
    except Exception:
        continue
    for i in d.get("items", []):
        if i.get("close") is not None and i.get("asOf"):
            S[i["name"]][i["asOf"]] = i["close"]
# Backfill: daily snapshots miss days when the feed did not run (16-24.09.2026 is a gap), and a gap of more than five
# days breaks the 1-week and 1-month windows (week, month and heatmap charts). Fill missing dates from each source's
# own daily history, only for dates before the latest snapshot of that instrument (so a session still in progress is
# never written) and never overwriting a snapshot.
def backfill():
    import datetime as dt, io, csv, urllib.parse
    import fetch_market_data as F
    added = collections.Counter()
    def put(name, d, v):
        s = S.get(name)
        if not s or d >= max(s) or d in s or d < (dt.date.today() - dt.timedelta(days=400)).isoformat():
            return
        s[d] = round(float(v), 6); added[name] += 1
    for name, sym in F.YAHOO + [("Tadawul TASI", "^TASI.SR")]:
        try:
            r = json.loads(F.get("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym, safe="") + "?range=1y&interval=1d", tries=2))["chart"]["result"][0]
            gmt = int(r["meta"].get("gmtoffset") or 0)
            for t, c in zip(r.get("timestamp") or [], r["indicators"]["quote"][0].get("close") or []):
                if c is not None:
                    put(name, dt.datetime.fromtimestamp(int(t) + gmt, dt.timezone.utc).date().isoformat(), c)
        except Exception as e:
            print("backfill skipped", name, type(e).__name__)
    try:
        yr = dt.date.today().year
        for y in (yr, yr - 1):
            u = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/%d/all"
                 "?type=daily_treasury_yield_curve&field_tdr_date_value=%d&page&_format=csv" % (y, y))
            for r in csv.DictReader(io.StringIO(F.get(u))):
                d = dt.datetime.strptime(r["Date"], "%m/%d/%Y").date().isoformat()
                for name, col in F.TENORS:
                    if r.get(col) not in (None, "", "N/A"):
                        put(name, d, r[col])
    except Exception as e:
        print("backfill skipped Treasury", type(e).__name__)
    try:
        j = json.loads(F.get("https://markets.newyorkfed.org/api/rates/secured/sofr/last/300.json"))
        for r in j["refRates"]:
            if r.get("percentRate") is not None:
                put("SOFR", r["effectiveDate"], r["percentRate"])
    except Exception as e:
        print("backfill skipped SOFR", type(e).__name__)
    print("backfill added:", dict(added) or "nothing")

if os.environ.get("NO_BACKFILL", "") != "1":
    try:
        backfill()
    except Exception as e:
        print("backfill failed:", type(e).__name__, e)
S = {k: dict(sorted(v.items())) for k, v in S.items()}
json.dump(S, open(out, "w"))
print("series.json:", len(S), "instruments;", min(len(v) for v in S.values()), "to", max(len(v) for v in S.values()), "points each")
