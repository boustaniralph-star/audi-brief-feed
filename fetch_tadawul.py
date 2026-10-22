#!/usr/bin/env python3
"""Audi Capital - Tadawul price feed (approved by Ralph 22.10.2026).
Daily closes for 1 year of the largest Saudi listings, so a Gulf Company of the Day always has a price chart even when
the writer's market-data tools fail. Yahoo .SR history works from GitHub runners. Writes tadawul_series.json:
{"generatedAt", "stocks": {code: {"name", "closes": {date: close}}}, "top30": {date: level}}, where top30 is an equal-
weight average of the listed stocks, rebased to 100 (Yahoo's TASI index history is unreliable, so this is the Saudi
benchmark for charts; it is labeled "Saudi top 30", never "TASI"). History is merged, never overwritten by a gap."""
import datetime as dt, json, os, time, urllib.parse
from fetch_market_data import get

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "tadawul_series.json")
RIYADH = dt.timezone(dt.timedelta(hours=3))
# code, the name Tadawul investors know
STOCKS = [("2222", "Aramco"), ("1120", "Al Rajhi"), ("1180", "SNB"), ("2010", "SABIC"), ("7010", "STC"), ("1211", "Ma'aden"),
          ("2082", "ACWA Power"), ("1150", "Alinma"), ("1010", "Riyad Bank"), ("1060", "SAB"), ("1140", "Bank Albilad"),
          ("1080", "Arab National Bank"), ("1050", "BSF"), ("2280", "Almarai"), ("4013", "Dr. Sulaiman Al Habib"),
          ("5110", "Saudi Electricity"), ("2020", "SABIC Agri-Nutrients"), ("7020", "Mobily"), ("4280", "Kingdom Holding"),
          ("2050", "Savola"), ("4190", "Jarir"), ("2290", "Yansab"), ("4002", "Mouwasat"), ("1111", "Saudi Tadawul Group"),
          ("4300", "Dar Al Arkan"), ("2310", "Sipchem"), ("4200", "Aldrees"), ("2350", "Saudi Kayan"), ("6010", "NADEC"),
          ("4263", "SAL Saudi Logistics"), ("2380", "Petro Rabigh"), ("1030", "SAIB")]


def closes(code):
    """{date: close} of settled sessions: daily bars plus, when the latest session has closed but its bar is not out
    yet (Yahoo's .SR bars lag a session), the closing price from the chart meta."""
    r = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(code + ".SR") + "?range=1y&interval=1d", tries=2))["chart"]["result"][0]
    m = r["meta"]
    gmt = int(m.get("gmtoffset") or 10800)
    day = lambda ts: dt.datetime.fromtimestamp(int(ts) + gmt, dt.timezone.utc).date()
    now = int(time.time())
    out = {}
    for ts, c in zip(r.get("timestamp") or [], r["indicators"]["quote"][0].get("close") or []):
        if c is not None:
            out[day(ts)] = float(c)
    try:
        end = int(m["currentTradingPeriod"]["regular"]["end"])
        session_open = day(end) == day(now) and now < end
    except Exception:
        session_open = False
    if session_open and day(now) in out:
        del out[day(now)]   # a session still in progress is not a close
    mt, mp = m.get("regularMarketTime"), m.get("regularMarketPrice")
    if mt and mp and not (session_open and day(mt) == day(now)):
        out[day(mt)] = float(mp)   # the settled close of the latest session, from meta
    return {d.isoformat(): round(v, 4) for d, v in out.items()}


def main():
    try:
        old = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        old = {"stocks": {}}
    stocks, ok = old.get("stocks", {}), 0
    for code, name in STOCKS:
        try:
            c = closes(code)
            if len(c) < 20:
                raise ValueError(f"only {len(c)} closes")
            s = stocks.setdefault(code, {"name": name, "closes": {}})
            s["name"] = name
            s["closes"].update(c)
            s["closes"] = dict(sorted(s["closes"].items())[-300:])
            ok += 1
        except Exception as e:
            print(f"{code} {name}: skipped ({type(e).__name__}: {e})")
        time.sleep(.4)
    # equal-weight Saudi top 30: each stock rebased to 100 at the first date it has, carried forward over missing days
    dates = sorted({d for s in stocks.values() for d in s["closes"]})
    top, last, first = {}, {}, {}
    for d in dates:
        for code, s in stocks.items():
            if d in s["closes"]:
                last[code] = s["closes"][d]
                first.setdefault(code, s["closes"][d])
        if len(last) >= .8 * len(stocks):
            top[d] = round(sum(last[c] / first[c] for c in last) / len(last) * 100, 4)
    json.dump({"generatedAt": dt.datetime.now(RIYADH).isoformat(timespec="seconds"), "stocks": stocks, "top30": top},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"tadawul_series.json: {ok} of {len(STOCKS)} stocks refreshed; {len(top)} top-30 points")
    return 0 if ok >= len(STOCKS) // 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
