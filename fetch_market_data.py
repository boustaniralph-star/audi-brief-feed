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


def _csi_from_points(source, pts):
    pts = sorted(pts)
    if len(pts) < 3:
        return None
    today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).date()
    if pts[-1][0] == today and len(pts) >= 4:
        pts = pts[:-1]
    last, prev = pts[-1], pts[-2]
    prior = [c for d, c in pts if d.year < last[0].year]
    base = prior[-1] if prior else None
    if base is None:
        try:
            base = json.load(open(os.path.join(HERE, "ytd_baselines.json"), encoding="utf-8-sig"))["closes"].get("CSI 300")
        except Exception:
            base = None
    return row("CSI 300", "1.000300", source, last[0].isoformat(), last[1], prev[1], base)


def eastmoney_csi300():
    hdrs = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/", "Accept": "application/json,text/plain,*/*"}
    for host in ("push2his.eastmoney.com", "push2.eastmoney.com"):
        u = (f"https://{host}/api/qt/stock/kline/get?secid=1.000300&klt=101&fqt=0&beg=20251201&end=20500101"
             "&fields1=f1,f2,f3&fields2=f51,f52,f53")
        for i in range(3):
            try:
                req = urllib.request.Request(u, headers=hdrs)
                with urllib.request.urlopen(req, timeout=30) as r:
                    kl = json.loads(r.read().decode("utf-8-sig"))["data"]["klines"]
                res = _csi_from_points("eastmoney", [(dt.date.fromisoformat(k.split(",")[0]), float(k.split(",")[2])) for k in kl])
                if res:
                    return res
            except Exception:
                time.sleep(2 + 2 * i)
    return None


def tencent_csi300():
    j = json.loads(get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000300,day,2025-12-01,,400,qfq"))
    d = j["data"]["sh000300"]
    kl = d.get("day") or d.get("qfqday")
    return _csi_from_points("tencent", [(dt.date.fromisoformat(k[0]), float(k[2])) for k in kl])


def csi300():
    err = []
    for fn in (eastmoney_csi300, tencent_csi300):
        try:
            r = fn()
            if r:
                return r
        except Exception as e:
            err.append(f"{fn.__name__}: {e}")
    raise RuntimeError("; ".join(err) or "no data")


def _series_prev(name, before):
    """Last close in series.json dated before `before` (ISO date), or None."""
    try:
        hist = json.load(open(os.path.join(HERE, "series.json"), encoding="utf-8-sig")).get(name, {})
        older = [d for d in hist if d < before]
        return float(hist[max(older)]) if older else None
    except Exception:
        return None


def yahoo_snapshot(name, symbol, now=None):
    # Day change is computed from the bar series (last settled close vs the close before it), never from
    # meta.previousClose / chartPreviousClose: once the new session is listed those equal the last settled
    # close, which produced chgDay -0.0 for TASI.
    now = now or int(time.time())
    r = None
    for rng in ("1mo", "5d"):
        try:
            r = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol, safe="") + f"?range={rng}&interval=1d"))["chart"]["result"][0]
            break
        except Exception:
            r = None
    if not r:
        return None
    meta = r["meta"]
    gmt = int(meta.get("gmtoffset") or 0)
    day = lambda t: dt.datetime.fromtimestamp(t + gmt, dt.timezone.utc).date()
    bars = {}
    for t, c in zip(r.get("timestamp") or [], r["indicators"]["quote"][0]["close"]):
        if c is not None:
            bars[day(int(t))] = float(c)   # one close per exchange date; a later entry for the same date wins
    pts = sorted(bars.items())
    exch_today = day(now)
    session_over = False
    try:
        end = int(meta["currentTradingPeriod"]["regular"]["end"])
        session_over = day(end) == exch_today and now >= end
    except Exception:
        pass
    if pts and pts[-1][0] == exch_today and not session_over:
        pts = pts[:-1]   # drop the in-progress session
    if not pts:
        return None
    d, last = pts[-1]
    prev = pts[-2][1] if len(pts) >= 2 else _series_prev(name, d.isoformat())
    if prev is None:
        return None
    base = None
    try:
        base = json.load(open(os.path.join(HERE, "ytd_baselines.json"), encoding="utf-8-sig"))["closes"].get(name)
    except Exception:
        pass
    return row(name, symbol, "yahoo-meta", d.isoformat(), last, prev, base)


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


MAJOR = {"S&P 500", "Nasdaq Composite", "Dow Jones", "STOXX 600", "DAX", "CAC 40", "FTSE 100", "Nikkei 225",
         "Hang Seng", "Sensex", "CSI 300", "Tadawul TASI"}


def already_today():
    try:
        gen = json.load(open(os.path.join(HERE, "market_data.json"), encoding="utf-8-sig")).get("generatedAt", "")
    except Exception:
        return False
    return gen[:10] == dt.datetime.now(RIYADH).strftime("%Y-%m-%d")


def main():
    if already_today() and os.environ.get("FORCE", "").lower() not in ("1", "true", "yes"):
        print("market_data.json already has generatedAt for today; skipping fetch")
        return
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
    for label, fn in (("CSI 300", csi300),
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
    for r in rows:
        if r["name"] in MAJOR and r["chgDay"] == 0:
            print(f"::warning::{r['name']} shows an exact 0.0 day change (close {r['close']}, asOf {r['asOf']}); check the baseline")
    if len(rows) < 17:
        sys.exit(f"only {len(rows)} of 20 instruments resolved")


if __name__ == "__main__":
    main()
