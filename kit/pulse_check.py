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
        RS = "ROTATION (fix, do not justify): "
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
            rep = [t for t in charts_now if t in recent]
            if rep: warn(RS + f"card {slot} repeats {', '.join(rep)} from the last 2 editions; rotate to another type on the menu")
            if L and sorted(now) == sorted(slot_types(L[-1], slot)): warn(RS + f"card {slot} is the same combination as yesterday")
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
        q = re.search(r"([\d,]*\.?\d+)\s*(k|mn|bn|tn|m)?\b\s*(%|bbl/d|[A-Za-z$/]+)?", t.replace("SAR ", "").replace("USD ", ""))
        return (float(q.group(1).replace(",", "")) * mult.get((q.group(2) or "").lower(), 1), (q.group(3) or "")) if q else None
    for pnl in C["p2"].get("gcc_panels", []):
        lab = pnl.get("label", "")
        if len(pnl.get("value", "")) + len(pnl.get("small", "")) / 2 > 16:
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
        BARS = ("index_board", "ytd", "week", "month", "movers")
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
