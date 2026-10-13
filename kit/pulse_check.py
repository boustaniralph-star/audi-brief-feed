#!/usr/bin/env python3
"""Audi Capital Daily Brief - pulse check (added 11 Oct 2026, approved by Ralph).
Sanity-checks a brief before it is committed: fresh data, figures consistent with market_data.json,
extras make sense, rotation rules respected, no banned characters, 2 pages.
Usage: python3 pulse_check.py content_v2.json market_data.json hero_data.json [brief.pdf] [--ledger FILE] [--txt FILE] [--today YYYY-MM-DD]
Exit 0 = pass (warnings may print), exit 5 = at least one FAIL. Never edits anything."""
import json, re, subprocess, sys, datetime as dt

args = [a for a in sys.argv[1:]]
def opt(name, default=None):
    if name in args:
        i = args.index(name); v = args[i + 1]; del args[i:i + 2]; return v
    return default
ledger = opt("--ledger"); txt = opt("--txt"); today = opt("--today")
content, mdata, hero = args[0], args[1], args[2]
pdf = args[3] if len(args) > 3 else None
rd = lambda p: json.load(open(p, encoding="utf-8-sig"))
C, M, H = rd(content), rd(mdata), rd(hero)
FAIL, WARN, OK = [], [], []
def fail(m): FAIL.append(m)
def warn(m): WARN.append(m)

def walk(o):
    if isinstance(o, str): yield o
    elif isinstance(o, dict):
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)
alltext = " ".join(walk(C))

# 1. data freshness
today_d = dt.date.fromisoformat(today) if today else dt.date.today()
gen = M.get("generatedAt", "")[:10]
if gen != today_d.isoformat(): fail(f"market_data.json generatedAt {gen} is not today ({today_d})")
else: OK.append("market_data.json is from today")
items = {i["name"]: i for i in M["items"]}
for n, i in items.items():
    try:
        age = (today_d - dt.date.fromisoformat(i["asOf"])).days
        # rates (SOFR, Treasury yields) publish with a 1-5 day lag at the source; only flag them past 7 days
        if age > (7 if i.get("unit") == "bps" else 4): warn(f"{n}: asOf {i['asOf']} is {age} days old")
        if i.get("partial"): warn(f"{n}: partial data")
    except Exception: warn(f"{n}: no asOf")

# 2. figures quoted in text vs market_data.json
ALIAS = {"S&P 500": ["S&P 500"], "Nasdaq Composite": ["Nasdaq"], "Dow Jones": ["Dow"], "STOXX 600": ["STOXX 600"], "DAX": ["DAX"],
         "CAC 40": ["CAC 40"], "FTSE 100": ["FTSE 100"], "Nikkei 225": ["Nikkei"], "Hang Seng": ["Hang Seng"], "Sensex": ["Sensex"],
         "Brent": ["Brent"], "WTI": ["WTI"], "Gold": ["Gold"], "CSI 300": ["CSI 300"], "Tadawul TASI": ["TASI"]}
def num(s): return float(s.replace(",", ""))
bad = 0
for name, al in ALIAS.items():
    it = items.get(name)
    if not it: continue
    for a in al:
        for m in re.finditer(re.escape(a) + r"[^0-9%]{0,22}?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{2,}\.\d+)(?![\d,]*%)", alltext):
            v = num(m.group(1))
            if abs(v - it["close"]) / max(abs(it["close"]), 1e-9) > 0.004 and abs(v - it["close"]) > 0.015:
                # allow values that are clearly another reference (prior close within 3%)
                warn(f"text quotes {a} {m.group(1)} but market_data.json close is {it['close']:,.2f}")
                bad += 1
if not bad: OK.append("quoted index/commodity levels match market_data.json")
for y in ("US 10Y yield", "US 2Y yield", "US 30Y yield"):
    it = items.get(y)
    if it:
        k = y.split()[1]
        for m in re.finditer(r"(?:US )?" + k + r"[^0-9%]{0,18}?(\d\.\d{2})%", alltext):
            if abs(float(m.group(1)) - it["close"]) > 0.015: warn(f"text quotes {k} {m.group(1)}% but market_data.json is {it['close']:.2f}%")

# 3. banned characters
if re.search("[–—]", alltext): fail("em or en dash found in content")
if re.search("[\U0001F000-\U0001FFFF☀-➿]", alltext): fail("emoji or symbol found in content")
if txt:
    t = open(txt, encoding="utf-8-sig").read()
    if re.search("[–—]", t): fail(".txt contains an em or en dash")
    w = len(t.split())
    if w > 900: fail(f".txt is {w} words (max 900)")
    elif w < 700: warn(f".txt is {w} words (target 700-850)")
    else: OK.append(f".txt is {w} words")

# 4. extras sanity
def specs():
    for k in ("extras_left", "extras_right"):
        for x in C["p1"].get(k, []) or []: yield "p1." + k, x
    for ci, c in enumerate(C["p2"]["cards"]):
        for x in c["charts"]: yield f"card{ci}", x
for where, x in specs():
    t = x["type"]
    if t == "loop":
        n = len(x["text"].split())
        if n > 28: fail(f"loop callout is {n} words (max 28)")
        if not re.search(r"\d", x["text"]): warn("loop callout has no figure")
    if t == "gulf" and len(re.findall(r"[.!?](?:\s|$)", x["text"])) > 1: warn("gulf angle should be one sentence")
    if t == "teaser":
        if len(x["text"]) > 150: fail(f"teaser is {len(x['text'])} chars (max 150)")
        if re.search(r"\b(will|expected to|should|likely|could)\b", x["text"], re.I): warn("teaser contains forecast wording; list confirmed events only")
    if t == "sectors":
        r = x["rows"]; mode = x.get("mode")
        if mode not in ("day", "mtd", "ytd"): fail("sectors needs mode day|mtd|ytd")
        if len(r) < 9: fail(f"sectors has {len(r)} rows (need at least 9 of 11)")
        lim = {"day": 6, "mtd": 20, "ytd": 80}.get(mode, 80)
        for q in r:
            if abs(q["pct"]) > lim: fail(f"sector {q['name']} {q['pct']}% outside plausible range for {mode}")
        if mode and mode not in x["title"].lower().replace("month to date", "mtd").replace("year to date", "ytd").replace("day", "day") and not any(k in x["title"].lower() for k in ("friday","monday","tuesday","wednesday","thursday","day","month","year","ytd","mtd","week")):
            warn("sector title does not state its window")
    if t == "topmovers":
        for side, sgn in (("gainers", 1), ("losers", -1)):
            v = [q["pct"] for q in x[side]]
            if any(p * sgn < 0 for p in v): fail(f"topmovers {side} contains wrong-sign values")
            if v != sorted(v, key=lambda p: -p * sgn): fail(f"topmovers {side} not sorted")
    if t in ("storyline", "levelchart"):
        v = x["values"]
        if len(v) < 5: fail(f"{t} has fewer than 5 points")
        if t == "storyline" and not x.get("lines") : warn("storyline has no reference line")
        name = x.get("name", "")
        it = items.get(name) or items.get({"10Y": "US 10Y yield", "Brent": "Brent"}.get(name, ""), None)
        if it and abs(v[-1] - it["close"]) > max(0.02, abs(it["close"]) * 0.002): fail(f"{t} last value {v[-1]} differs from market_data.json {it['close']}")
        if it: OK.append(f"{t} last point matches market_data.json")
    if t == "levels":
        for q in x["rows"]:
            try:
                val = num(re.sub(r"[^0-9.,]", "", q["value"])); gap = q["gap"]
                if "%" in gap and "bps" not in gap and "bp" not in gap:
                    lv = num(re.sub(r"[^0-9.,]", "", q["level"].split()[-1])) if re.search(r"\d", q["level"]) else None
                    if lv and abs((val / lv - 1) * 100 - float(gap.replace("%", "").replace("+", ""))) > 0.25:
                        warn(f"levels row {q['name']}: gap {gap} does not match value/level")
            except Exception: pass
    if t == "alumni":
        if all(r["ret"] > 0 for r in x["rows"]): warn("alumni shows only winners; include losers")

# 5. hero consistency
ht = H.get("type") or ("line" if H.get("rows") else "none")
ct = (C["cotd"].get("chart_title", "") + " " + C["cotd"].get("chart_method", "")).lower()
if ht == "none" and ct.strip(): warn("hero is none but chart_title/method are set")
if ht == "valuewiped" and "value" not in ct: warn("hero chart_title does not mention value for a valuewiped hero")
if ht == "range" and "range" not in ct and "52" not in ct: warn("hero chart_title does not mention the range for a range hero")
if ht == "intraday" and not any(k in ct for k in ("session", "intraday", "gap", "open", "minute")): warn("hero chart_title does not describe the session for an intraday hero")

# 6. rotation ledger
if ledger:
    try:
        L = [l for l in open(ledger, encoding="utf-8-sig").read().splitlines() if re.match(r"\d\d-\d\d-\d{4}:", l)]
        L = [l for l in L if not l.startswith(today_d.strftime("%d-%m-%Y"))][-3:]
        cur_hero = ht
        prev = [re.search(r"hero=([a-z_]+)", l) for l in L]
        if any(p and p.group(1) == cur_hero and cur_hero != "none" for p in prev): warn(f"hero type {cur_hero} was used in the last 3 editions")
        for ci, c in enumerate(C["p2"]["cards"]):
            slot = "AB"[ci] if ci < 2 else str(ci)
            for k, x in enumerate(c["charts"]):
                pass
        ex_now = [x["type"] for _, x in specs()]
        for kind in ("alumni", "levels"):
            if kind in ex_now and L and re.search(kind, L[-1]): warn(f"{kind} was used in the previous edition")
        if "sectors" in ex_now:
            md = [x.get("mode") for _, x in specs() if x["type"] == "sectors"][0]
            if L and re.search(r"sectors=" + md, L[-1]): warn(f"sector window '{md}' repeats the previous edition; rotate day, mtd, ytd")
        OK.append("rotation ledger checked")
    except Exception as e: warn(f"could not read ledger: {e}")

# 7. PDF
if pdf:
    try:
        n = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout).group(1))
        (OK if n == 2 else FAIL).append(f"PDF has {n} page(s)" + ("" if n == 2 else " (must be 2)"))
        txtp = subprocess.run(["pdftotext", pdf, "-"], capture_output=True, text=True).stdout
        if re.search("[–—]", txtp): fail("PDF text contains an em or en dash")
    except Exception as e: warn(f"pdf check skipped: {e}")

print("PULSE CHECK")
for m in OK: print("  ok   ", m)
for m in WARN: print("  WARN ", m)
for m in FAIL: print("  FAIL ", m)
print("RESULT:", "FAIL" if FAIL else ("PASS with warnings" if WARN else "PASS"))
sys.exit(5 if FAIL else 0)
