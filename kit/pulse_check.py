#!/usr/bin/env python3
"""Audi Capital Daily Brief - pulse check (added 11 Oct 2026, approved by Ralph).
Sanity-checks a brief before it is committed: fresh data, figures consistent with market_data.json,
extras make sense, rotation rules respected, no banned characters, 2 pages.
Usage: python3 pulse_check.py content_v2.json market_data.json hero_data.json [brief.pdf] [--ledger FILE] [--txt FILE] [--today YYYY-MM-DD] [--sources FILE] [--facts FILE]
Exit 0 = pass (warnings may print), exit 5 = at least one FAIL. Never edits anything."""
import json, re, subprocess, sys, datetime as dt

args = [a for a in sys.argv[1:]]
def opt(name, default=None):
    if name in args:
        i = args.index(name); v = args[i + 1]; del args[i:i + 2]; return v
    return default
ledger = opt("--ledger"); txt = opt("--txt"); today = opt("--today"); sources = opt("--sources"); facts = opt("--facts")
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

# THEME DAYS (promised to Ralph; enforced from 20.10.2026, Monday's map from 19.10): each weekday has its chart
THEMES = {0: "Monday: week-ahead map (weekmap)", 1: "Tuesday: earnings scorecard (movers or topmovers)",
          2: "Wednesday: rates day (rates or rates_trend in card B)", 3: "Thursday: Gulf deep dive (a TASI or Gulf-bourse chart)",
          4: "Friday: weekly scorecard (a scorecard chart: week bars with a YTD column, in card A)", 5: "Saturday: where are they now (alumni) and month bars",
          6: "Sunday: ytd bars"}
def theme_types():
    """chart types today's theme requires; the rotation check lets these repeat"""
    return {0: {"weekmap"}, 1: {"movers", "topmovers"}, 2: {"rates", "rates_trend"}, 3: set(),
            4: {"scorecard", "week", "ytd"}, 5: {"alumni", "month"}, 6: {"ytd"}}[today_d.weekday()]

# 6. rotation ledger
if ledger:
    try:
        L = [l for l in open(ledger, encoding="utf-8-sig").read().splitlines() if re.match(r"\d\d-\d\d-\d{4}:", l)]
        L = [l for l in L if not l.startswith(today_d.strftime("%d-%m-%Y"))][-3:]
        cur_hero = ht
        prev = [re.search(r"hero=([a-z_]+)", l) for l in L]
        RS = "ROTATION (fix, do not justify): "
        if cur_hero == "line" and len(prev) >= 2 and all(p and p.group(1) == "line" for p in prev[-2:]):
            warn(RS + "third line hero in a row; pick a story-driven hero (drawdown, valuewiped, range, intraday, guidance)")
        if any(p and p.group(1) == cur_hero and cur_hero not in ("none", "line") for p in prev):
            warn(RS + f"hero type {cur_hero} was used in the last 3 editions; pick another story-driven type or the line hero")
        # page-2 cards: no chart type in the same slot as in the previous 2 editions, never yesterday's exact combination
        def slot_types(line, slot):
            m = re.search(slot + r"=([^;]*)", line)
            return [re.sub(r"\(.*", "", t).strip() for t in m.group(1).split("+")] if m else []
        for ci, c in enumerate(C["p2"]["cards"][:2]):
            slot = "AB"[ci]
            now = [x["type"] for x in c["charts"]] + (["tiles"] if c.get("tiles") else [])
            charts_now = [t for t in now if t != "tiles"]
            recent = [t for l in L[-2:] for t in slot_types(l, slot)]
            rep = [t for t in charts_now if t in recent and t not in theme_types()]
            if rep: warn(RS + f"card {slot} repeats {', '.join(rep)} from the last 2 editions; rotate to another type on the menu")
            if L and sorted(now) == sorted(slot_types(L[-1], slot)) and not set(charts_now) <= theme_types():
                warn(RS + f"card {slot} is the same combination as yesterday")
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

# 8. desktop standards (added 14 Oct 2026): what the desktop editions always had
try:
    tk = (C["cotd"].get("ticker") or "").strip()
    us_listed = bool(re.search(r"\b(NYSE|Nasdaq|NASDAQ)\b", tk)) or bool(re.fullmatch(r"[A-Z][A-Z.]{0,5}", tk))
    if ht == "none" and us_listed:
        warn(f"DESKTOP STANDARD (fix, do not justify): hero is none but {C['cotd'].get('name', 'the COTD')} ({tk}) has a US listing: build one: python3 enrich.py hero content_v2.json hero_data.json (or a story-driven valuewiped, range, drawdown or intraday hero), then make room on page 1")
    for ci, c in enumerate(C["p2"]["cards"]):
        if not c.get("charts"):
            warn(f"DESKTOP STANDARD (fix, do not justify): page 2 card {'AB'[ci] if ci < 2 else ci} has no chart (tiles only): every card needs at least one chart")
    IDX = ("S&P 500", "Nasdaq", "Dow", "STOXX 600", "Stoxx", "DAX", "CAC 40", "FTSE 100", "Nikkei", "Hang Seng", "CSI 300", "Sensex")
    for page in ("p1", "p2"):
        for side in ("left", "right"):
            for _, bullets in C[page].get(side, []) or []:
                for lead, text in bullets:
                    if sum(k in text for k in IDX) >= 2 and "%" in text and "YTD" not in text:
                        warn(f"DESKTOP STANDARD (fix, do not justify): '{lead}' quotes index closes without YTD: run python3 enrich.py ytd content_v2.json market_data.json")
    # data providers are never named in a caption (Ralph, 16.10)
    meta = [C["cotd"].get("chart_title", ""), C["cotd"].get("chart_method", "")]
    for card in C["p2"]["cards"]:
        meta += [card.get("title", ""), card.get("sub", ""), card.get("tiles_head", "")]
        meta += [ch.get(k, "") for ch in card.get("charts", []) for k in ("title", "note") if isinstance(ch.get(k), str)]
    meta += [p.get(k, "") for p in C["p2"].get("gcc_panels", []) for k in ("label", "small", "caption")]
    meta += [v for v in walk(H) if isinstance(v, str)]
    for m in meta:
        if re.search(r"\b(Robinhood|IBKR|Interactive Brokers|Yahoo)\b", m, re.I):
            warn(f"DESKTOP STANDARD (fix, do not justify): caption names a data provider: '{m[:70]}'; say 'official closes' instead (or run python3 enrich.py scrub content_v2.json hero_data.json)")
    # no stale "as of" dates: every dataset in a caption is from the latest sessions
    for m in meta:
        for d, mo, y in re.findall(r"\b(\d{2})[.-](\d{2})[.-](20\d{2})\b", m):
            try:
                age = (today_d - dt.date(int(y), int(mo), int(d))).days
            except ValueError:
                continue
            if age > 3 and not re.search(r"(since|from|high|low|peak|IPO|listing|first)\b[^.;]{0,25}" + d + r"[.-]" + mo, m, re.I):
                warn(f"DESKTOP STANDARD (fix, do not justify): stale data in a caption, '{d}.{mo}.{y}' is {age} days old: refresh it (IBKR or Robinhood) or drop that element: '{m[:60]}'")
    # GCC panels must read cleanly for a non-specialist
    mult = {"k": 1e3, "mn": 1e6, "m": 1e6, "bn": 1e9, "tn": 1e12}
    def qty(t):
        t = re.sub(r"\b(19|20)\d\d\s*:\s*", "", t)  # a year label ("2026: -3.3%") is not the quantity
        q = re.search(r"([\d,]*\.?\d+)\s*(k|mn|bn|tn|m)?\b\s*(%|bbl/d|[A-Za-z$/]+)?", t.replace("SAR ", "").replace("USD ", ""))
        return (float(q.group(1).replace(",", "")) * mult.get((q.group(2) or "").lower(), 1), (q.group(3) or "")) if q else None
    for pnl in C["p2"].get("gcc_panels", []):
        lab = pnl.get("label", "")
        if len(pnl.get("value", "")) + len(pnl.get("small", "")) / 2 > 13.5:
            warn(f"DESKTOP STANDARD (fix, do not justify): panel '{lab}': '{pnl.get('value','')} {pnl.get('small','')}' wraps; keep the figure short and the words after it to 2-4 words (e.g. '70%' + 'of the refinery's crude')")
        for b in pnl.get("bars", []):
            if len(b.get("t", "")) > 22:
                warn(f"DESKTOP STANDARD (fix, do not justify): panel '{lab}': bar label '{b['t']}' is too long (max 22 characters) and squeezes the bar"); break
        if len(pnl.get("value", "")) > 14:
            warn(f"DESKTOP STANDARD (fix, do not justify): panel '{lab}': headline figure '{pnl['value']}' is too long (max 14 characters): one number and unit")
        if len(pnl.get("small", "")) > 26:
            warn(f"DESKTOP STANDARD (fix, do not justify): panel '{lab}': the words after the figure ('{pnl['small']}') are too long (max 26 characters)")
        bars = [(b.get("w", 0), qty(b.get("t", ""))) for b in pnl.get("bars", [])]
        vals = [(w, q) for w, q in bars if q]
        if len(vals) >= 2 and len({q[1] for _, q in vals}) == 1 and max(q[0] for _, q in vals) > 0:
            top = max(q[0] for _, q in vals)
            for w, q in vals:
                if abs(w - q[0] / top * 100) > 10:
                    warn(f"DESKTOP STANDARD (fix, do not justify): panel '{lab}': bar widths do not match their numbers (width {w} for {q[0]:g} of {top:g}); set w = value / largest x 100")
                    break
except Exception as e: warn(f"desktop-standard checks skipped: {e}")
# HOOKS (approved by Ralph 17.10.2026, live from 19.10.2026): Today in 3, Gulf line, Number of the day, headline
# lead-ins, the question in the Watch band
try:
    if today_d >= dt.date(2026, 10, 19):
        H3 = "HOOKS (fix, do not justify): "
        t3 = C.get("top3") or []
        if len(t3) != 3: warn(H3 + f"'top3' needs exactly 3 items (has {len(t3)})")
        for x in t3:
            if len(x.get("k", "")) > 30: warn(H3 + f"Today in 3 headline '{x.get('k')}' is too long (max 30 characters)")
            if len(x.get("t", "")) > 110: warn(H3 + f"Today in 3 line under '{x.get('k')}' is too long (max 110 characters)")
            if not re.search(r"\d", x.get("t", "")): warn(H3 + f"Today in 3 line under '{x.get('k')}' has no figure")
        if not C.get("cotd", {}).get("means"): warn(H3 + "cotd.means (For Gulf investors line) is missing")
        nd = [x for side in ("extras_left", "extras_right") for x in C.get("p1", {}).get(side, []) or [] if x.get("type") == "numday"]
        if len(nd) != 1: warn(H3 + f"page 1 needs exactly one numday callout (has {len(nd)})")
        elif len(nd[0].get("value", "")) > 12: warn(H3 + f"Number of the day '{nd[0]['value']}' is too long (max 12 characters)")
        dull = {"close.", "closes.", "friday.", "monday.", "tuesday.", "wednesday.", "thursday.", "saturday.", "sunday.", "week.", "asia.", "rates.", "chips.", "gap.", "india.", "china."}
        leads = [b[0] for pg in ("p1", "p2") for side in ("left", "right") for s in C.get(pg, {}).get(side, []) or [] for b in s[1]]
        flat = [l for l in leads if l.strip().lower() in dull or len(l.split()) < 2]
        if flat: warn(H3 + f"lead-ins must be short headlines that tell the story, not labels: {', '.join(flat[:6])}")
        w = C.get("watch", {})
        if not w.get("text", "").rstrip().endswith("?"): warn(H3 + "the Watch band must end with the question ('The question this week' / 'The question today')")
except Exception as e: warn(f"hook checks skipped: {e}")
# STORY CHARTS (approved by Ralph 17.10.2026, live from 19.10.2026): takeaway titles, events on the line hero,
# highlighted bars, names that exist on the chart
try:
    if today_d >= dt.date(2026, 10, 19):
        SC = "STORY CHARTS (fix, do not justify): "
        BARS = ("index_board", "ytd", "week", "month", "movers", "scorecard")
        short = {"Nasdaq Composite": "Nasdaq", "Nikkei 225": "Nikkei", "Tadawul TASI": "TASI", "Dow Jones": "Dow"}
        on_chart = {short.get(i["name"], i["name"]) for i in M["items"]}
        ct = C.get("cotd", {}).get("chart_title", "")
        if ct and not re.search(r"\d", ct): warn(SC + f"hero chart title '{ct}' states no figure; make it the takeaway with its number")
        for ci, c in enumerate(C.get("p2", {}).get("cards", [])):
            if not re.search(r"\d", c.get("title", "")): warn(SC + f"card {'AB'[ci] if ci < 2 else ci} title '{c.get('title')}' states no figure")
            for x in c.get("charts", []):
                if x.get("type") not in BARS: continue
                hl = x.get("highlight") or []
                if not 1 <= len(hl) <= 3: warn(SC + f"card {'AB'[ci] if ci < 2 else ci} {x['type']} needs 1-3 highlighted names (the story), has {len(hl)}")
                names = {r["name"] for r in x.get("rows", [])} if x["type"] == "movers" else on_chart
                bad = [n for n in hl if n not in names]
                if bad: warn(SC + f"highlight names not on the {x['type']} chart: {', '.join(bad)} (use the chart's short names: Nasdaq, Nikkei, TASI, Dow)")
        if (H.get("rows") and not H.get("type")):
            ev = H.get("events") or []
            if not 1 <= len(ev) <= 2: warn(SC + f"line hero needs 1-2 events marked on it (has {len(ev)}): {{'date','label'}}")
            d0, d1 = H["rows"][0][0], H["rows"][-1][0]
            for e in ev:
                if not d0 <= e.get("date", "") <= d1: warn(SC + f"hero event '{e.get('label')}' date {e.get('date')} is outside the chart window")
                if len(e.get("label", "")) > 22: warn(SC + f"hero event label '{e.get('label')}' is too long (max 22 characters)")
except Exception as e: warn(f"story chart checks skipped: {e}")
# panels: a fall, loss or negative figure must be drawn as one (neg: true), whatever the date
try:
    NEGW = re.compile(r"(?<![\w.])-\s?\d|\b(fall|fell|falls|drop|decline|shrink|contract|contraction|loss|deficit|down)\b", re.I)
    for pnl in C.get("p2", {}).get("gcc_panels", []) or []:
        for b_ in pnl.get("bars", []) or []:
            if NEGW.search(b_.get("t", "")) and not b_.get("neg"):
                warn("STORY CHARTS (fix, do not justify): panel '" + pnl.get("label", "") + "': bar '" + b_.get("t", "") + "' is a fall or a negative value drawn as a rise; set \"neg\": true and show the sign (\"2026: -3.3%\")")
except Exception as e: warn(f"panel sign check skipped: {e}")
# THEME DAYS: the check runs below; the definitions sit here so the rotation check can use them
try:
    wd = today_d.weekday()
    if today_d >= dt.date(2026, 10, 20) or (wd == 0 and today_d >= dt.date(2026, 10, 19)):
        cards = C.get("p2", {}).get("cards", [])
        cardA = [x.get("type") for x in (cards[0].get("charts", []) if cards else [])]
        cardB = [x.get("type") for x in (cards[1].get("charts", []) if len(cards) > 1 else [])]
        ext = [x for side in ("extras_left", "extras_right") for x in C.get("p1", {}).get(side, []) or []]
        allc = [x for c in cards for x in c.get("charts", [])] + ext
        types = [x.get("type") for x in allc]
        ok = {0: "weekmap" in types,
              1: any(t in types for t in ("movers", "topmovers")),
              2: any(t in cardB for t in ("rates", "rates_trend")),
              3: any(("TASI" in (x.get("highlight") or [])) or "TASI" in (x.get("name", "") + x.get("title", "")) or
                     (x.get("type") == "heatmap" and "Tadawul TASI" in x.get("names", [])) for x in allc),
              4: "scorecard" in cardA or ("week" in cardA and "ytd" in cardA),
              5: "alumni" in types and "month" in types,
              6: "ytd" in types}[wd]
        if not ok:
            warn(f"THEME (fix, do not justify): today is {THEMES[wd]}; add it (it may repeat a recent chart type, the rotation check allows it)")
except Exception as e: warn(f"theme check skipped: {e}")
# SOURCES: every newsletter the Gmail query returned is read in full (GitHub re-checks this against the inbox)
if sources:
    try:
        SL = [l for l in open(sources, encoding="utf-8").read().splitlines() if "|" in l]
        # core newsletters are read in full; the rest may be skimmed (Ralph, 20.10), but every one must be accounted for
        unread = [l for l in SL if l.split("|")[1].strip().upper() not in ("READ", "SKIMMED") and not l.split("|")[1].strip().upper().startswith("SKIP: DUPLICATE")]
        if not SL: warn("SOURCES (fix, do not justify): sources.txt lists no newsletters; run the newsletters query and read them")
        for l in unread[:8]:
            warn("SOURCES (fix, do not justify): newsletter neither read nor skimmed: " + " | ".join(x.strip() for x in l.split("|")[1:4])[:110])
        if today_d >= dt.date(2026, 10, 22):
            nou = [l for l in SL if l.split("|")[1].strip().upper() == "READ" and not re.search(r"used\s*=\s*\d+", l)]
            for l in nou[:4]:
                warn("SOURCES (fix, do not justify): READ line has no 'used=N' (stories in this brief that came from it): " + " | ".join(x.strip() for x in l.split("|")[1:3]))
        if SL and not unread: OK.append(f"{len(SL)} newsletters accounted for")
    except Exception as e: warn(f"sources check skipped: {e}")
# FACTS: every bullet's key figure was checked outside the newsletters, on its latest version
if facts:
    try:
        NL = ("enterpriseam", "ground news", "history facts", "skimm", "front office", "interesting facts", "business insider",
              "morning brew", "retail brew", "tech brew", "cfo brew", "brew markets", "investopedia", "sofi", "exec sum",
              "litquidity", "snacks", "rundown", "newsletter", "substack", "cappnotes", "beehiiv")
        FL = [[x.strip() for x in l.split("|")] for l in open(facts, encoding="utf-8").read().splitlines() if l.count("|") >= 3]
        have = {f[0].lower().rstrip(".") for f in FL}
        leads = [b[0] for pg in ("p1", "p2") for side in ("left", "right") for sec_ in C.get(pg, {}).get(side, []) or [] for b in sec_[1]]
        leads += [x.get("k", "") for x in C.get("top3", []) or []]
        miss = [l for l in leads if l and l.lower().rstrip(".") not in have]
        for l in miss[:6]:
            warn("FACTS (fix, do not justify): no facts.txt line for '" + l + "': verify its key figure on the latest source and log it")
        for f in FL:
            src = f[2].lower()
            if not src:
                warn("FACTS (fix, do not justify): '" + f[0] + "' has no verification source")
            elif "google.com/url" in src or "click." in src or "links." in src:
                warn("FACTS (fix, do not justify): '" + f[0] + "' cites a newsletter tracking link; open the source page itself and cite its own address")
            elif any(n in src for n in NL):
                warn("FACTS (fix, do not justify): '" + f[0] + "' is verified partly by a newsletter (" + f[2][:50] + "); confirm every figure and date in it on a primary or wire source, or cut what you cannot")
        if FL and not miss: OK.append(f"{len(FL)} key figures verified")
    except Exception as e: warn(f"facts check skipped: {e}")
# STORY DISCIPLINE (Ralph, 21.10.2026): one story appears once, figures never contradict, the teaser is truly ahead,
# and both pages look full (page 2 included: card A against card B, and the region columns against the question band)
EDITION = dt.datetime.strptime(C["date"], "%d-%m-%Y").date() if re.match(r"\d\d-\d\d-\d{4}$", C.get("date", "")) else today_d
COMMON = set("""saudi arabia arabian gulf gcc mena us usd sar aed the and for with from that this its their after before into over
under than about against while as at by in of on to up down per year years week weeks month months day days today yesterday tomorrow
monday tuesday wednesday thursday friday saturday sunday january february march april may june july august september october
november december q1 q2 q3 q4 h1 h2 fy brent wti tasi dow nasdaq s&p stoxx dax cac ftse nikkei kospi hang seng sensex csi europe
european asia asian china chinese india indian japan japanese uae qatar kuwait bahrain oman egypt iran israel uk britain british
kingdom riyadh dubai abu dhabi adx dfm tadawul wall street ai ipo ceo eps ytd fed ecb treasury dollar oil gold index market markets
shares share stock stocks bn mn billion million trillion percent profit profits revenue sales quarter quarterly results net income
rose fell gained lost jumped dropped closed close closes trading traded price prices points rate rates yield yields bonds bond
company companies group firm government governments bank banks investors investor deal deals said says will would could also more
most less new first last largest biggest record high low highs lows since tons barrel barrels expected
france french germany german italy spain russia russian ukraine korea korean taiwan turkey yemen lebanon syria iraq jordan
pakistan brazil mexico canada indonesia vietnam africa nigeria argentina australia washington beijing tokyo london paris berlin
seoul moscow trump president minister white house congress reuters bloomberg afp xinhua cnbc wsj spa wam argaam zawya
agbi asharq gdp composite cpi inflation pmi"""
.split())
def _stem(w):
    w = w.lower().strip(".,;:()'\"")
    return w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w
def _words(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return {_stem(w) for w in re.findall(r"[A-Za-z][A-Za-z\-&']{3,}", s)} - COMMON
def _names(s):
    s = re.sub(r"<[^>]+>", " ", s)
    ns = {re.sub(r"'s$", "", w.strip(".,;:()'\"")) for w in re.findall(r"\b[A-Z][A-Za-z0-9\-&']{2,}", s)}
    return {w for w in ns if w.lower() not in COMMON}
QUOTED = {abs(round(float(i.get(k)), 2)) for i in M.get("items", []) for k in ("close", "chgDay", "chgYtd") if isinstance(i.get(k), (int, float))}
def _figs(s):
    """[(value, decimals, strong)] for the figures in s: years and DD.MM dates skipped; 'strong' = 3+ significant digits
    or a percentage of 10 or more (distinctive enough to identify a story)."""
    out = []
    for m in re.finditer(r"(?<![\d.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\d]|[a-zA-Z])(\s?%)?", re.sub(r"<[^>]+>", " ", s)):
        raw, pct = m.group(1), m.group(2)
        v = raw.replace(",", "")
        dm = re.fullmatch(r"(\d{1,2})\.(\d{2})", raw)
        if re.fullmatch(r"20[2-3]\d", v) or (dm and not pct and 1 <= int(dm.group(1)) <= 31 and 1 <= int(dm.group(2)) <= 12):
            continue  # years and DD.MM dates are not story figures
        sig = len(v.replace(".", "").strip("0"))
        if sig < 2 and not pct: continue
        if float(v) in QUOTED: continue  # an official close, day move or YTD is a market quote, not a story figure
        # distinctive: an amount with 3+ significant digits, or a move of 10% or more (small % moves coincide too often)
        out.append((float(v), len(v.split(".")[1]) if "." in v else 0, (float(v) >= 10) if pct else sig >= 3, raw, bool(pct)))
    return out
def _same_fig(A, B):
    """Figures shared by two stories, allowing for rounding (15.73 and 15.7, 34.8 and 35)."""
    hit = []
    for a in A:
        for b in B:
            if not (a[2] and b[2]) or a[4] != b[4]: continue  # both distinctive; a percentage only matches a percentage
            d = min(a[1], b[1])
            if d == 0 and a[0] != b[0] and (a[4] or max(a[0], b[0]) < 20): continue  # whole-number rounding only for large amounts
            if abs(a[0] - b[0]) <= .5 * 10 ** -d + 1e-9: hit.append(a[3] if a[1] >= b[1] else b[3])
    return sorted(set(hit))
try:
    if today_d >= dt.date(2026, 10, 22):
        RP = "REPETITION (fix: one story appears once; give the space to a new story): "
        units = []
        cot = C.get("cotd", {})
        units.append(("Company of the Day", cot.get("name", "") + " " + cot.get("body", "")))
        for pg in ("p1", "p2"):
            for side in ("left", "right"):
                for sec_ in C.get(pg, {}).get(side, []) or []:
                    for b in sec_[1]:
                        units.append((f"{sec_[0]} '{b[0]}'", b[0] + " " + b[1]))
        for x in (C.get("p1", {}).get("extras_left") or []) + (C.get("p1", {}).get("extras_right") or []):
            if x.get("type") == "numday": units.append(("Number of the day", x.get("value", "") + " " + x.get("text", "")))
        for pnl in C.get("p2", {}).get("gcc_panels", []) or []:
            units.append((f"panel '{pnl.get('label')}'", " ".join([pnl.get("label", ""), pnl.get("value", ""), pnl.get("caption", "")] + [b.get("t", "") for b in pnl.get("bars", [])])))
        feats = [(lab, _names(tx), _words(tx), _figs(tx)) for lab, tx in units]
        hits = 0
        for i in range(len(feats)):
            for j in range(i + 1, len(feats)):
                a, b = feats[i], feats[j]
                why = []
                nm = sorted(a[1] & b[1])
                if nm: why.append("both name " + ", ".join(nm[:3]))
                fg = _same_fig(a[3], b[3])
                if fg: why.append("both quote " + ", ".join(fg[:3]))
                wd = sorted(a[2] & b[2])
                if not why and len(wd) >= 3: why.append("same subject (" + ", ".join(wd[:4]) + ")")
                if why:
                    hits += 1
                    if hits <= 8: warn(RP + f"{a[0]} and {b[0]}: {'; '.join(why)}")
        if not hits: OK.append("no story repeated")
        # contradictions: every figure in Today in 3 and in the Company of the Day stats must match the body exactly
        CT = "CONTRADICTION (fix, do not justify): "
        body = " ".join(tx for _, tx in units)
        bnums = [float(x.replace(",", "")) for x in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", re.sub(r"<[^>]+>", " ", body))]
        def _found(raw, pool):
            v = float(raw.replace(",", "")); dec = len(raw.split(".")[1]) if "." in raw else 0
            return any(abs(b - v) <= .5 * 10 ** -dec + 1e-9 for b in pool)
        for x in C.get("top3", []) or []:
            for raw in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", x.get("k", "") + " " + x.get("t", "")):
                if re.fullmatch(r"20[2-3]\d", raw) or raw in ("1", "2", "3"): continue
                if not _found(raw, bnums): warn(CT + f"Today in 3 '{x.get('k')}' quotes {raw}, which the story below does not; use the same figure in both")
        cb = [float(x.replace(",", "")) for x in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", cot.get("body", "") + " " + " ".join(s.get("l", "") for s in cot.get("stats", [])))]
        for s in cot.get("stats", []):
            for raw in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", s.get("v", "")):
                if not _found(raw, cb): warn(CT + f"Company of the Day stat '{s.get('v')}' is not in its text; state the same figure in the body")
        # a panel's bars must show its headline figure on the same basis: a fall cannot be drawn as a rise
        for pnl in C.get("p2", {}).get("gcc_panels", []) or []:
            mv = re.match(r"\s*([+-])\s*\d", pnl.get("value", ""))
            bars_ = pnl.get("bars") or []
            if mv and len(bars_) == 2 and not any(b.get("neg") for b in bars_):
                newer_bigger = bars_[0].get("w", 0) > bars_[1].get("w", 0)
                if (mv.group(1) == "-") == newer_bigger:
                    warn(CT + f"panel '{pnl.get('label')}' headline is {pnl.get('value')} but its two bars show the opposite move "
                         f"('{bars_[0].get('t')}' vs '{bars_[1].get('t')}'); compare the same periods as the headline (year on year for a y/y figure)")
        # the teaser looks ahead: every date in it is after this edition, and 'Tomorrow' means the next calendar day
        TZ = "TEASER (fix, do not justify): "
        WD = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        for x in (C.get("p1", {}).get("extras_left") or []) + (C.get("p1", {}).get("extras_right") or []):
            if x.get("type") != "teaser": continue
            for m in re.finditer(r"(?:\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?\s+)?\b(\d{1,2})\.(\d{1,2})\b", x.get("text", "")):
                try: d = dt.date(EDITION.year + (1 if int(m.group(3)) < EDITION.month - 6 else 0), int(m.group(3)), int(m.group(2)))
                except ValueError: continue
                if d <= EDITION: warn(TZ + f"teaser date {m.group(2)}.{m.group(3)} is not after this {EDITION:%d.%m} edition; a teaser shows what comes next")
                elif x.get("label", "").strip().lower() == "tomorrow" and d != EDITION + dt.timedelta(days=1):
                    warn(TZ + f"teaser says Tomorrow but its date is {d:%a %d.%m}; label it with the day ('Monday', 'Coming up') or use tomorrow's events")
                if m.group(1) and WD[d.weekday()] != m.group(1).lower()[:3]:
                    warn(TZ + f"teaser pairs {m.group(1)} with {d:%d.%m}, which is a {d:%A}")
        # page 2 fill, measured by the builder (charts are images, so the PDF text alone cannot show these gaps)
        try:
            import os as _os
            LY = json.load(open("layout.json")) if _os.path.exists("layout.json") else {}
            q = LY.get("p2") if pdf and LY.get("pdf") == _os.path.basename(pdf) else None
            if q:
                DS = "DESKTOP STANDARD (fix, do not justify): "
                d_ = q["cardB"] - q["cardA"]
                if abs(d_) > 30:
                    sh, lg = ("A", "B") if d_ > 0 else ("B", "A")
                    warn(DS + f"page 2 card {sh} is {abs(d_):.0f} pt shorter than card {lg}, leaving a blank gap under it: give card {sh} "
                         f"a second chart or a taller one (about h {abs(d_) / 72:.1f} in more), a tiles row, or an HTML extra (topmovers, levels, sectors) inside the card")
                for side, g in (("left (GCC & MENA)", q["left_gap"]), ("right (Oil, Tech, Emerging Markets)", q["right_gap"])):
                    if g > 45:
                        warn(DS + f"page 2 {side} column ends {g:.0f} pt above the question band: add a new news bullet (about 35 pt each) "
                             f"or a page-2 callout in p2.extras_{'left' if side.startswith('left') else 'right'} (topmovers, sectors, levels, storyline, gulf)")
                if abs(d_) <= 30 and q["left_gap"] <= 45 and q["right_gap"] <= 45: OK.append("page 2 filled (cards level, columns reach the question band)")
            # a trend chart's heading names the window it really shows ("last 30 sessions" over 7 sessions is wrong)
            for key, w_ in (LY.get("windows") or {}).items() if pdf and LY.get("pdf") == _os.path.basename(pdf) else []:
                m_ = re.search(r"(\d+)\s*(sessions|trading days|days|weeks|months)", w_.get("mini", ""), re.I)
                if m_:
                    n_, unit = int(m_.group(1)), m_.group(2).lower()
                    approx = {"sessions": n_, "trading days": n_, "days": n_ * 5 / 7, "weeks": n_ * 5, "months": n_ * 21}[unit]
                    if abs(approx - w_["sessions"]) > max(2, .25 * w_["sessions"]):
                        warn("STORY CHARTS (fix, do not justify): " + f"{w_['type']} heading '{w_['mini']}' but the chart shows {w_['sessions']} sessions; "
                             "say what it shows, or set the chart's \"days\" (calendar days back) to match")
        except Exception as e: warn(f"page 2 fill check skipped: {e}")
except Exception as e: warn(f"story discipline checks skipped: {e}")
if pdf:
    try:
        bx = subprocess.run(["pdftotext", "-f", "1", "-l", "1", "-bbox", pdf, "-"], capture_output=True, text=True).stdout
        W, H = map(float, re.search(r'<page width="([\d.]+)" height="([\d.]+)"', bx).groups())
        ws = [(float(a), float(b), float(c), float(d), w) for a, b, c, d, w in
              re.findall(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)<', bx)]
        foot = min(b for a, b, c, d, w in ws if w == "Audi" and b > H * 0.9)
        body = [t for t in ws if t[3] < foot - 2]
        short = 0
        for col, sel in (("left", lambda t: t[2] < W / 2), ("right", lambda t: t[0] > W / 2)):
            gap = foot - max(t[3] for t in body if sel(t))
            if gap > 90:
                short += 1; warn(f"DESKTOP STANDARD (fix, do not justify): page 1 {col} column ends {gap:.0f} pt above the footer (desktop editions end within about 75 pt): add a hero, a story or a callout")
        if not short: OK.append("page 1 columns filled")
    except Exception as e: warn(f"page fill check skipped: {e}")

print("PULSE CHECK")
for m in OK: print("  ok   ", m)
for m in WARN: print("  WARN ", m)
for m in FAIL: print("  FAIL ", m)
print("RESULT:", "FAIL" if FAIL else ("PASS with warnings" if WARN else "PASS"))
sys.exit(5 if FAIL else 0)
