#!/usr/bin/env python3
"""Audi Capital - FX rates for currency conversion (Ralph, 24.10.2026: the brief's readers know USD and SAR, so every
other currency is shown with its USD equivalent). Writes fx_rates.json: {"generatedAt", "asOf", "usd_per": {code: USD
per one unit}} from Yahoo's daily closes. SAR and the Gulf pegs are fixed by their central banks."""
import datetime as dt, json, os, time, urllib.parse
from fetch_market_data import get

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fx_rates.json")
CODES = ["EUR", "GBP", "JPY", "CNY", "HKD", "INR", "KRW", "SEK", "NOK", "DKK", "CHF", "CAD", "AUD", "SGD", "TWD",
         "BRL", "MXN", "ZAR", "TRY", "EGP", "PKR", "IDR"]
PEGS = {"SAR": 1 / 3.75, "AED": 1 / 3.6725, "QAR": 1 / 3.64, "BHD": 1 / 0.376, "OMR": 1 / 0.3845}


def main():
    try:
        old = json.load(open(OUT, encoding="utf-8")).get("usd_per", {})
    except Exception:
        old = {}
    rates, asof, got = dict(old), {}, 0
    for c in CODES:
        try:
            r = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(c + "USD=X") + "?range=5d&interval=1d", tries=2))["chart"]["result"][0]
            closes = [(t, v) for t, v in zip(r.get("timestamp") or [], r["indicators"]["quote"][0].get("close") or []) if v]
            if closes:
                rates[c] = round(closes[-1][1], 8)
                asof[c] = dt.datetime.fromtimestamp(closes[-1][0], dt.timezone.utc).date().isoformat()
                got += 1
        except Exception as e:
            print(c, "skipped:", type(e).__name__)
        time.sleep(.3)
    rates.update({k: round(v, 8) for k, v in PEGS.items()})
    json.dump({"generatedAt": dt.datetime.now(dt.timezone(dt.timedelta(hours=3))).isoformat(timespec="seconds"),
               "asOf": max(asof.values()) if asof else None, "usd_per": rates}, open(OUT, "w", encoding="utf-8"), indent=1)
    print(f"fx_rates.json: {got} of {len(CODES)} currencies refreshed")
    return 0 if got >= len(CODES) // 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
