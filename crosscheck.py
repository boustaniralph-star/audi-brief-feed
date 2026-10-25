#!/usr/bin/env python3
"""Audi Capital - market data cross-check (Ralph, 25.10.2026: Brent's 23.10 close read 116.72 on 24.10 and 111.70 on
25.10 from the same feed, and the brief printed the first one).
Two checks on every fresh market_data.json row, run by fetch_market_data.py before it writes the file:
  1. revision: the same instrument and the same session date in the previous download must give the same close;
  2. second source: Brent, WTI and gold are compared with Stooq's daily futures closes for the same date.
A row that fails either gets "check": "<reason>". pulse_check then keeps that price and any chart of it out of the
brief, and the mailer emails the owner. A second source that cannot be reached is reported, never treated as a pass."""
import csv, datetime as dt, glob, io, json, os, urllib.request

REVISION_TOL = 0.005      # 0.5%: a settled close does not move between downloads
SECOND_TOL = 0.015        # 1.5%: two feeds of the same front-month future settle within this
SECOND = {"Brent": "cb.f", "WTI": "cl.f", "Gold": "gc.f"}
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


def stooq_closes(code, fetch=None):
    """{ISO date: close} from Stooq's daily CSV for a futures code."""
    if fetch is None:
        def fetch(u):
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30) as f:
                return f.read().decode("utf-8-sig")
    text = fetch(f"https://stooq.com/q/d/l/?s={code}&i=d")
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            out[row["Date"]] = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            pass
    if not out:
        raise ValueError("no rows")
    return out


def second_source(rows, fetch=None):
    issues, notes = {}, []
    for r in rows:
        code = SECOND.get(r["name"])
        if not code:
            continue
        try:
            closes = stooq_closes(code, fetch)
        except Exception as e:
            notes.append(f"{r['name']}: second source unavailable ({type(e).__name__})"); continue
        other = closes.get(r["asOf"])
        if other is None:
            notes.append(f"{r['name']}: second source has no close for {r['asOf']}"); continue
        if _rel(r["close"], other) > SECOND_TOL:
            issues[r["name"]] = f"{r['name']} close for {r['asOf']} is {r['close']} here but {other} on a second source"
        else:
            notes.append(f"{r['name']}: second source agrees ({other} for {r['asOf']})")
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
