#!/usr/bin/env python3
"""Audi Capital - market data cross-check (Ralph, 25.10.2026: Brent's 23.10 close read 116.72 on 24.10 and 111.70 on
25.10 from the same feed, and the brief printed the first one).
Two checks on every fresh market_data.json row, run by fetch_market_data.py before it writes the file:
  1. revision: the same instrument and the same session date in the previous download must give the same close;
  2. second source: Brent, WTI and gold are compared with another feed's daily front-month futures closes for the
     same date (CNBC, then Stooq).
A row that fails either gets "check": "<reason>". pulse_check then keeps that price and any chart of it out of the
brief, and the mailer emails the owner. A second source that cannot be reached is reported, never treated as a pass."""
import csv, datetime as dt, glob, io, json, os, urllib.parse, urllib.request

REVISION_TOL = 0.005      # 0.5%: a settled close does not move between downloads
SECOND_TOL = 0.015        # 1.5%: two feeds of the same front-month future settle within this
SECOND = ("Brent", "WTI", "Gold")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def _rel(a, b):
    return abs(a - b) / max(abs(b), 1e-9)


def previous_snapshot(snapdir, today):
    """The latest market_data/<date>.json dated before today, as {name: item}."""
    files = sorted(f for f in glob.glob(os.path.join(snapdir, "*.json")) if os.path.basename(f)[:10] < today)
    if not files:
        return {}, None
    try:
        return {i["name"]: i for i in json.load(open(files[-1], encoding="utf-8-sig"))["items"]}, os.path.basename(files[-1])[:10]
    except Exception:
        return {}, None


def revisions(rows, old):
    out = {}
    for r in rows:
        o = old.get(r["name"])
        if o and o.get("asOf") == r["asOf"] and o.get("unit") == r.get("unit") and _rel(r["close"], o["close"]) > REVISION_TOL:
            out[r["name"]] = (f"{r['name']} close for {r['asOf']} changed from {o['close']} to {r['close']} between downloads")
    return out


def _get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "*/*"}), timeout=30) as f:
        return f.read().decode("utf-8-sig")


def cnbc_closes(name, fetch):
    """{ISO date: close} from CNBC's daily chart bars for the continuous front-month future."""
    sym = {"Brent": "@LCO.1", "WTI": "@CL.1", "Gold": "@GC.1"}[name]
    j = json.loads(fetch("https://ts-api.cnbc.com/harmony/app/charts/1M.json?symbol=" + urllib.parse.quote(sym)))
    out = {}
    for b in (j.get("barData") or {}).get("priceBars") or []:
        t, c = str(b.get("tradeTime") or ""), b.get("close")
        if len(t) >= 8 and c not in (None, ""):
            out[f"{t[:4]}-{t[4:6]}-{t[6:8]}"] = float(c)
    if not out:
        raise ValueError("no bars: " + json.dumps(j)[:120])
    return out


def stooq_closes(name, fetch):
    """{ISO date: close} from Stooq's daily CSV for the front-month future."""
    code = {"Brent": "cb.f", "WTI": "cl.f", "Gold": "gc.f"}[name]
    text = fetch(f"https://stooq.com/q/d/l/?s={code}&i=d")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out[row["Date"]] = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            pass
    if not out:
        raise ValueError("no rows: " + text[:80].replace("\n", " "))
    return out


PROVIDERS = (("CNBC", cnbc_closes), ("Stooq", stooq_closes))


def second_source(rows, fetch=None):
    fetch = fetch or _get
    issues, notes = {}, []
    for r in rows:
        if r["name"] not in SECOND:
            continue
        tried = []
        for label, fn in PROVIDERS:
            try:
                other = fn(r["name"], fetch).get(r["asOf"])
            except Exception as e:
                tried.append(f"{label} {type(e).__name__}: {str(e)[:100]}"); continue
            if other is None:
                tried.append(f"{label} has no close for {r['asOf']}"); continue
            if _rel(r["close"], other) > SECOND_TOL:
                issues[r["name"]] = f"{r['name']} close for {r['asOf']} is {r['close']} here but {other} on {label}"
            else:
                notes.append(f"{r['name']}: {label} agrees ({other} for {r['asOf']})")
            break
        else:
            notes.append(f"{r['name']}: second source unavailable ({'; '.join(tried)})")
    return issues, notes


def apply(rows, snapdir, today, fetch=None):
    """Mark failing rows with "check" and return the printable report lines."""
    old, when = previous_snapshot(snapdir, today)
    found = revisions(rows, old)
    sec, notes = second_source(rows, fetch)
    for n, why in sec.items():
        found[n] = found[n] + "; " + why if n in found else why
    for r in rows:
        r.pop("check", None)
        if r["name"] in found:
            r["check"] = found[r["name"]]
    lines = [f"cross-check against the {when} download: {len(old)} instruments compared" if when else "cross-check: no earlier download"]
    lines += notes + [f"CHECK {why}" for why in found.values()]
    return lines


if __name__ == "__main__":
    # report only: check today's market_data.json against the previous download and the second source, write nothing
    here = os.path.dirname(os.path.abspath(__file__))
    md = json.load(open(os.path.join(here, "market_data.json"), encoding="utf-8-sig"))
    for line in apply(md["items"], os.path.join(here, "market_data"), md["generatedAt"][:10]):
        print(line)
