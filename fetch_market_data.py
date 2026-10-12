#!/usr/bin/env python3
"""Audi Capital - market data feed (Python port of fetch_market_data.ps1, for GitHub Actions).
No API keys, standard library only. Writes market_data.json and market_data/<date>.json in the same
schema as the PowerShell script (items: name, symbol, source, asOf, close, chgDay, chgYtd, unit, partial).
Index moves are percent; yields are basis points. A bar from a session still in progress is dropped,
so every row is a settled close."""
import csv, datetime as dt, io, json, os, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
RIYADH = dt.timezone(dt.timedelta(hours=3))

YAHOO = [("S&P 500", "^GSPC"), ("Nasdaq Composite", "^IXIC"), ("Dow Jones", "^DJI"), ("STOXX 600", "^STOXX"),
         ("DAX", "^GDAXI"), ("CAC 40", "^FCHI"), ("FTSE 100", "^FTSE"), ("Nikkei 225", "^N225"),
         ("Hang Seng", "^HSI"), ("Sensex", "^BSESN"), ("Brent", "BZ=F"), ("WTI", "CL=F"),
         ("Gold", "GC=F"), ("Dollar Index", "DX-Y.NYB")]
TENORS = [("US 2Y yield", "2 Yr"), ("US 10Y yield", "10 Yr"), ("US 30Y yield", "30 Yr")]


def get(url, timeout=30, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8-sig")
        except Exception as e:
            last = e
            time.sleep(2 + 3 * i)
    raise last


def row(name, symbol, source, date, last, prev, base, is_yield=False):
    ytd = None
    if base is not None:
        ytd = round((last - base) * 100, 1) if is_yield else round((last / base - 1) * 100, 2)
    chg = round((last - prev) * 100, 1) if is_yield else round((last / prev - 1) * 100, 2)
    return {"name": name, "symbol": symbol, "source": source, "asOf": date, "close": round(last, 4),
            "chgDay": chg, "chgYtd": ytd, "unit": "bps" if is_yield else "pct", "partial": False}


def yahoo(name, symbol, now=None):
    now = now or int(time.time())
    res = None
    for rng in ("2y", "1y", "6mo", "3mo", "1mo", "5d"):
        try:
            j = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol, safe="") + f"?range={rng}&interval=1d", tries=2))
            r = j["chart"]["result"][0]
            if len(r.get("timestamp") or []) >= 3:
                res = r
                break
        except Exception:
            pass
        time.sleep(0.5)
    if not res:
        return None
    meta = res["meta"]
    gmt = int(meta.get("gmtoffset") or 0)
    pts = [(int(t), float(c)) for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]
    if len(pts) < 3:
        return None
    day = lambda t: dt.datetime.fromtimestamp(t + gmt, dt.timezone.utc).date()
    exch_today = day(now)
    session_over = False
    try:
        end = int(meta["currentTradingPeriod"]["regular"]["end"])
        if day(end) == exch_today and now >= end:
            session_over = True
    except Exception:
        pass
    partial = day(pts[-1][0]) == exch_today and not session_over
    if partial and len(pts) >= 4:
        pts = pts[:-1]
    last, prev = pts[-1], pts[-2]
    ld = day(last[0])
    prior = [c for t, c in pts if day(t).year < ld.year]
    return row(name, symbol, "yahoo", ld.isoformat(), last[1], prev[1], prior[-1] if prior else None)


def eastmoney_csi300():
    u = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&klt=101&fqt=0&beg=20251201&end=20500101"
         "&fields1=f1,f2,f3&fields2=f51,f52,f53")
    kl = json.loads(get(u))["data"]["klines"]
    pts = sorted((dt.date.fromisoformat(k.split(",")[0]), float(k.split(",")[2])) for k in kl)
    if len(pts) < 3:
        return None
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).date()
    if pts[-1][0] == today and len(pts) >= 4:
        pts = pts[:-1]
    last, prev = pts[-1], pts[-2]
    prior = [c for d, c in pts if d.year < last[0].year]
    return row("CSI 300", "1.000300", "eastmoney", last[0].isoformat(), last[1], prev[1], prior[-1] if prior else None)


def yahoo_snapshot(name, symbol):
    j = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol, safe="") + "?range=5d&interval=1d"))
    r = j["chart"]["result"][0]
    meta = r["meta"]
    closes = [c for c in r["indicators"]["quote"][0]["close"] if c is not None]
    last = closes[-1] if closes else meta.get("regularMarketPrice")
    if last is None:
        return None
    prev = meta.get("chartPreviousClose") or meta.get("previousClose") or last
    gmt = int(meta.get("gmtoffset") or 0)
    ts = (r.get("timestamp") or [int(time.time())])[-1]
    d = dt.datetime.fromtimestamp(ts + gmt, dt.timezone.utc).date()
    base = None
    try:
        base = json.load(open(os.path.join(HERE, "ytd_baselines.json"), encoding="utf-8-sig"))["closes"].get(name)
    except Exception:
        pass
    return row(name, symbol, "yahoo-meta", d.isoformat(), float(last), float(prev), base)


def treasury():
    now = dt.date.today()
    out = []
    by = {}
    for yr in (now.year, now.year - 1):
        u = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/%d/all"
             "?type=daily_treasury_yield_curve&field_tdr_date_value=%d&page&_format=csv" % (yr, yr))
        by[yr] = list(csv.DictReader(io.StringIO(get(u))))
    parse = lambda s: dt.datetime.strptime(s, "%m/%d/%Y").date()
    cur = sorted(by[now.year], key=lambda r: parse(r["Date"]))
    prv = sorted(by[now.year - 1], key=lambda r: parse(r["Date"]))
    for name, col in TENORS:
        s = [r for r in cur if r.get(col) not in (None, "", "N/A")]
        if len(s) < 2:
            continue
        b = [r for r in prv if r.get(col) not in (None, "", "N/A")]
        base = float(b[-1][col]) if b else float(s[0][col])
        out.append(row(name, "UST " + col, "ustreasury", parse(s[-1]["Date"]).isoformat(),
                       float(s[-1][col]), float(s[-2][col]), base, True))
    return out


def sofr():
    j = json.loads(get("https://markets.newyorkfed.org/api/rates/secured/sofr/last/300.json"))
    pts = sorted((dt.date.fromisoformat(r["effectiveDate"]), float(r["percentRate"]))
                 for r in j["refRates"] if r.get("percentRate") is not None)
    if len(pts) < 2:
        return None
    last, prev = pts[-1], pts[-2]
    prior = [c for d, c in pts if d.year < last[0].year]
    return row("SOFR", "SOFR", "nyfed", last[0].isoformat(), last[1], prev[1], prior[-1] if prior else pts[0][1], True)


def main():
    rows, missing, pending = [], [], []
    for name, sym in YAHOO:
        try:
            r = yahoo(name, sym)
        except Exception:
            r = None
        (rows.append(r) if r else pending.append((name, sym)))
        time.sleep(0.8)
    if pending:
        print("retrying after cool-down:", [n for n, _ in pending])
        time.sleep(15)
        for name, sym in pending:
            try:
                r = yahoo(name, sym)
            except Exception:
                r = None
            (rows.append(r) if r else missing.append(f"{name} ({sym})"))
            time.sleep(5)
    for label, fn in (("CSI 300 (eastmoney)", eastmoney_csi300),
                      ("Tadawul TASI", lambda: yahoo_snapshot("Tadawul TASI", "^TASI.SR")),
                      ("US Treasury curve", treasury), ("SOFR (NY Fed)", sofr)):
        try:
            r = fn()
            if not r:
                missing.append(label)
            else:
                rows.extend(r if isinstance(r, list) else [r])
        except Exception as e:
            missing.append(f"{label} - {e}")
    if not rows:
        sys.exit("nothing resolved")
    payload = {"generatedAt": dt.datetime.now(RIYADH).strftime("%Y-%m-%d %H:%M:%S +03:00"), "timezone": "Asia/Riyadh",
               "items": rows, "missing": missing}
    text = json.dumps(payload, indent=1)
    os.makedirs(os.path.join(HERE, "market_data"), exist_ok=True)
    open(os.path.join(HERE, "market_data.json"), "w", encoding="utf-8").write(text)
    open(os.path.join(HERE, "market_data", dt.datetime.now(RIYADH).strftime("%Y-%m-%d") + ".json"), "w", encoding="utf-8").write(text)
    for r in rows:
        print(f"{r['name']:<18}{r['asOf']}  {r['close']:>12}  day {r['chgDay']:>7}  ytd {r['chgYtd']}")
    print("MISSING:", missing if missing else "none")
    if len(rows) < 17:
        sys.exit(f"only {len(rows)} of 20 instruments resolved")


if __name__ == "__main__":
    main()
