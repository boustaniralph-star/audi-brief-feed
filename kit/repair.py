#!/usr/bin/env python3
"""Audi Capital Daily Brief - automatic repairs (Ralph, 26.10.2026: "never hold a brief, resolve it").
GitHub runs these on every package before it builds, so a fixable slip never stops or spoils an edition:
  storylines  a storyline or level chart is redrawn from series.json so it ends on the official close
  currency    a foreign amount in the text gets its USD equivalent; in stat boxes and panels it becomes USD
Each repair returns the changed content and a list of what it changed, for the owner's report."""
import copy, re

try:
    from enrich import usd_text, _repo_json
except ImportError:          # imported from the repo root
    from kit.enrich import usd_text, _repo_json

CODES = ("EUR", "GBP", "JPY", "CNY", "HKD", "INR", "KRW", "SEK", "NOK", "DKK", "CHF", "CAD", "AUD", "SGD", "TWD",
         "BRL", "MXN", "ZAR", "TRY", "EGP", "PKR", "IDR", "AED", "QAR", "BHD", "OMR")
AMOUNT = re.compile(r"\b(" + "|".join(CODES) + r")\s?(-?\d[\d,]*(?:\.\d+)?)(?:\s?(bn|mn|m|k|tn|billion|million|trillion)\b)?")
UNIT = {"billion": "bn", "million": "m", "trillion": "tn", "mn": "m"}
SERIES_NAME = {"10Y": "US 10Y yield", "US 10Y": "US 10Y yield", "2Y": "US 2Y yield", "30Y": "US 30Y yield",
               "TASI": "Tadawul TASI", "Nasdaq": "Nasdaq Composite", "Dow": "Dow Jones", "Nikkei": "Nikkei 225"}


def _usd(code, num, unit):
    """'about USD 373 m' for one amount, or None when the rate is unknown."""
    try:
        t = usd_text(code, float(num.replace(",", "")), UNIT.get(unit or "", unit or ""))
    except Exception:
        return None
    m = re.search(r"\((about USD [^)]+)\)", t)
    return m.group(1) if m else None


def usd_in_text(s):
    """Append '(about USD x)' after every foreign amount that lacks a USD or SAR figure right after it."""
    out, last, changes = [], 0, []
    ms = list(AMOUNT.finditer(s))
    for k, m in enumerate(ms):
        nxt = ms[k + 1].start() if k + 1 < len(ms) else len(s)
        if re.search(r"USD|SAR", s[m.end():min(m.end() + 45, nxt)]):
            continue
        u = _usd(m.group(1), m.group(2), m.group(3))
        if not u:
            continue
        out.append(s[last:m.end()] + f" ({u})"); last = m.end()
        changes.append(f"{m.group(0)} -> {m.group(0)} ({u})")
    out.append(s[last:])
    return "".join(out), changes


def usd_in_box(s):
    """Replace a foreign amount with its USD value (boxes have no room for both)."""
    changes = []
    def sub(m):
        u = _usd(m.group(1), m.group(2), m.group(3))
        if not u:
            return m.group(0)
        changes.append(f"{m.group(0)} -> {u[6:]}")
        return u[6:]          # drop "about "
    return AMOUNT.sub(sub, s), changes


def currency(content, txt):
    c = copy.deepcopy(content); log = []
    def walk(o, box=False):
        if isinstance(o, dict):
            for k, v in o.items():
                in_box = box or k in ("stats", "gcc_panels", "tiles")
                if isinstance(v, str):
                    new, ch = (usd_in_box if in_box else usd_in_text)(v)
                    if ch:
                        o[k] = new; log.extend(ch)
                else:
                    walk(v, in_box)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                if isinstance(v, str):
                    new, ch = (usd_in_box if box else usd_in_text)(v)
                    if ch:
                        o[i] = new; log.extend(ch)
                else:
                    walk(v, box)
    walk(c)
    t, ch = usd_in_text(txt)
    log.extend("text: " + x for x in ch)
    return c, t, log


def storylines(content, series, md):
    """Redraw storyline / level charts from series.json so the last point is the official close."""
    c = copy.deepcopy(content); log = []
    closes = {i["name"]: i for i in md.get("items", [])}
    charts = [ch for card in c.get("p2", {}).get("cards", []) for ch in card.get("charts", [])]
    charts += [x for side in ("extras_left", "extras_right") for x in c.get("p2", {}).get(side, []) or []]
    for ch in charts:
        if ch.get("type") not in ("storyline", "levelchart") or not ch.get("values"):
            continue
        name = SERIES_NAME.get(ch.get("name", ""), ch.get("name", ""))
        hist = series.get(name)
        it = closes.get(name)
        if not hist or not it:
            continue
        v = ch["values"]
        if abs(v[-1] - it["close"]) <= max(0.02, abs(it["close"]) * 0.002):
            continue
        days = sorted(d for d in hist if d <= it["asOf"])[-len(v):]
        if len(days) < 5:
            continue
        old = v[-1]
        ch["values"] = [round(float(hist[d]), 4) for d in days]
        ch["values"][-1] = it["close"]
        ch["dates"] = [days[0], it["asOf"]]
        log.append(f"{ch.get('name')} chart redrawn from the official series (last point {old} -> {it['close']})")
    return c, log


def all_repairs(content, txt, md):
    log = []
    try:
        series = _repo_json("series.json")
        content, l = storylines(content, series, md); log += l
    except Exception as e:
        log.append(f"storyline repair skipped ({type(e).__name__})")
    try:
        content, txt, l = currency(content, txt); log += l
    except Exception as e:
        log.append(f"currency repair skipped ({type(e).__name__})")
    return content, txt, log
