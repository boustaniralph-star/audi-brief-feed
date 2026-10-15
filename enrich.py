#!/usr/bin/env python3
"""Audi Capital Daily Brief - bring a cloud package up to the desktop standard before the PDF is built.
Deterministic, no AI. Used by mailer.py; every step is optional and the caller falls back to the original files.
  ytd(content, txt, md)      add ", +x.xx% YTD" to index closes quoted as "<index> <level> (<day %>)" when the level
                             matches market_data.json; never touches a figure, only appends the verified YTD.
  auto_hero(content, md)     when the writer sent no hero for a listed company, build the classic "line" hero:
                             12 months of weekly closes plus the last daily closes, the company against two benchmarks,
                             rebased to 100 (Yahoo Finance daily closes; settled sessions only)."""
import copy, datetime as dt, json, re, time, urllib.parse

ALIAS = [("S&P 500", "S&P 500"), ("Nasdaq Composite", "Nasdaq Composite"), ("Nasdaq", "Nasdaq Composite"),
         ("Dow Jones", "Dow Jones"), ("Dow", "Dow Jones"), ("STOXX 600", "STOXX 600"), ("Stoxx 600", "STOXX 600"),
         ("DAX", "DAX"), ("CAC 40", "CAC 40"), ("FTSE 100", "FTSE 100"), ("Nikkei 225", "Nikkei 225"), ("Nikkei", "Nikkei 225"),
         ("Hang Seng", "Hang Seng"), ("CSI 300", "CSI 300"), ("Sensex", "Sensex"), ("TASI", "Tadawul TASI")]
CLOSE = re.compile(r"(?P<name>" + "|".join(re.escape(a) for a, _ in ALIAS) + r")(?P<mid>\s+(?P<lvl>\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*)"
                   r"\((?P<day>[+-]?\d+(?:\.\d+)?%)\)")


def _ytd_text(s, items):
    def rep(m):
        it = items.get(dict(ALIAS)[m["name"]])
        if not it or it.get("chgYtd") is None:
            return m[0]
        lvl = float(m["lvl"].replace(",", ""))
        if abs(lvl / it["close"] - 1) > 0.005:          # a different reference (intraday, other date): leave it
            return m[0]
        return f'{m["name"]}{m["mid"]}({m["day"]}, {it["chgYtd"]:+.2f}% YTD)'
    return CLOSE.sub(rep, s)


def ytd(content, txt, md):
    """Returns (content, txt, n_changed). txt is left as is if the edit would push it over 900 words."""
    items = {i["name"]: i for i in md.get("items", []) if i.get("unit") == "pct"}
    C = copy.deepcopy(content)
    n = 0
    for page in ("p1", "p2"):
        for side in ("left", "right"):
            for sec in C.get(page, {}).get(side, []) or []:
                for b in sec[1]:
                    new = _ytd_text(b[1], items)
                    n += new != b[1]
                    b[1] = new
    t2 = _ytd_text(txt, items)
    if len(t2.split()) > 900:
        t2 = txt
    return C, t2, n


# ---------------------------------------------------------------- auto hero
US = re.compile(r"\b(?:NYSE(?: American)?|Nasdaq|NASDAQ)\s*:\s*([A-Z][A-Z.\-]{0,6})")
VENUES = [(r"Tadawul\s*:\s*(\d{4})", "{}.SR", "^TASI.SR", "TASI"), (r"Tokyo\s*:\s*(\d{4})", "{}.T", "^N225", "Nikkei"),
          (r"(?:HKEX|Hong Kong)\s*:\s*(\d{1,5})", "{:0>4}.HK", "^HSI", "Hang Seng"),
          (r"Euronext Amsterdam\s*:\s*([A-Z]{2,6})", "{}.AS", "^STOXX", "STOXX 600"),
          (r"Euronext Paris\s*:\s*([A-Z]{2,6})", "{}.PA", "^FCHI", "CAC 40"),
          (r"(?:Xetra|Frankfurt)\s*:\s*([A-Z0-9]{2,6})", "{}.DE", "^GDAXI", "DAX"),
          (r"(?:LSE|London)\s*:\s*([A-Z]{2,5})", "{}.L", "^FTSE", "FTSE 100")]


def resolve(ticker):
    """Yahoo symbol, benchmarks [(symbol, label), (symbol, label)] for a COTD ticker string, or None."""
    t = (ticker or "").strip()
    m = US.search(t) or (re.fullmatch(r"([A-Z][A-Z.\-]{0,5})", t))
    if m:
        return m.group(1).replace(".", "-"), [("^IXIC", "Nasdaq"), ("^GSPC", "S&P 500")]
    for pat, fmt, idx, lab in VENUES:
        m = re.search(pat, t)
        if m:
            return fmt.format(m.group(1)), [(idx, lab), ("^GSPC", "S&P 500")]
    return None


def _settled(get, symbol, now):
    """[(date, close)] daily, 1 year, without a session still in progress."""
    j = json.loads(get("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(symbol, safe="") + "?range=1y&interval=1d"))
    r = j["chart"]["result"][0]
    gmt = int(r["meta"].get("gmtoffset") or 0)
    day = lambda ts: dt.datetime.fromtimestamp(ts + gmt, dt.timezone.utc).date()
    bars = {}
    for ts, c in zip(r.get("timestamp") or [], r["indicators"]["quote"][0].get("close") or []):
        if c is not None:
            bars[day(int(ts))] = float(c)
    pts = sorted(bars.items())
    try:
        end = int(r["meta"]["currentTradingPeriod"]["regular"]["end"])
        if pts and pts[-1][0] == day(now) and now < end:
            pts = pts[:-1]
    except Exception:
        pass
    return pts


def _pick_rows(pts, daily_tail=8):
    """Last close of each ISO week for 12 months, then every session of the last `daily_tail`."""
    tail = pts[-daily_tail:]
    head = pts[:-daily_tail]
    weekly = {}
    for d, c in head:
        weekly[d.isocalendar()[:2]] = (d, c)
    return sorted(weekly.values()) + tail


def auto_hero(content, md, get, now=None):
    """Returns (hero, content) with a line hero and its caption, or (None, None)."""
    cot = content.get("cotd", {})
    res = resolve(cot.get("ticker"))
    if not res:
        return None, None
    sym, peers = res
    now = now or int(time.time())
    subj = _settled(get, sym, now)
    if len(subj) < 120:
        return None, None
    series = []
    for psym, _ in peers:
        p = dict(_settled(get, psym, now))
        if len(p) < 120:
            return None, None
        series.append(p)
    rows, last = [], [None] * len(series)
    keys = [sorted(s) for s in series]
    for d, c in _pick_rows(subj):
        vals = []
        for k, s in enumerate(series):
            past = [x for x in keys[k] if x <= d]
            if not past:
                break
            vals.append(round(s[past[-1]], 4))
        else:
            rows.append([d.isoformat(), round(c, 4)] + vals)
    if len(rows) < 30:
        return None, None
    name = cot.get("name") or sym
    names = [name] + [lab for _, lab in peers]
    chg = [(rows[-1][i] / rows[0][i] - 1) * 100 for i in range(1, 4)]
    first = dt.date.fromisoformat(rows[0][0])
    lastd = dt.date.fromisoformat(rows[-1][0])
    fmt = lambda d: d.strftime("%b %-d, %Y")
    w = ["ahead of" if chg[0] >= b else "behind" for b in chg[1:]]
    if w[0] == w[1]:
        cmp = f"{w[0]} both the {names[1]} ({chg[1]:+.1f}%) and the {names[2]} ({chg[2]:+.1f}%)"
    else:
        cmp = f"{w[0]} the {names[1]} ({chg[1]:+.1f}%) and {w[1]} the {names[2]} ({chg[2]:+.1f}%)"
    title = f"Since {fmt(first)} {name} is {chg[0]:+.1f}%, {cmp}"
    method = f"Weekly closes from {fmt(first)}, then daily closes to {fmt(lastd)} (official), rebased to 100."
    day_up = rows[-1][1] >= rows[-2][1]
    hero = {"names": names, "rows": rows, "height": 1.6, "day_color": "up" if day_up else "dn"}
    C = copy.deepcopy(content)
    C["cotd"]["chart_title"], C["cotd"]["chart_method"] = title, method
    return hero, C


def relayouts(content):
    """Layouts to try when a hero does not fit: the content as is, then one page-1 section moved to the end of page 2
    (Emerging Markets first, the desktop placement; then the last section of each page-1 column), to the shorter page-2
    column first. Each item is (label, content)."""
    out = [("layout as sent", content)]
    p1, p2 = content.get("p1", {}), content.get("p2", {})
    words = lambda col: sum(len(b[1].split()) for s in col for b in s[1])
    targets = sorted(("left", "right"), key=lambda s: words(p2.get(s, []) or []))
    cands = []
    for side in ("left", "right"):
        for i, s in enumerate(p1.get(side, []) or []):
            if "EMERGING" in s[0].upper():
                cands.insert(0, (side, i))
    for side in ("left", "right"):
        col = p1.get(side, []) or []
        if len(col) > 1 and (side, len(col) - 1) not in cands:
            cands.append((side, len(col) - 1))
    for side, i in cands:
        for tgt in targets:
            C = copy.deepcopy(content)
            sec = C["p1"][side].pop(i)
            C["p2"].setdefault(tgt, []).append(sec)
            out.append((f"{sec[0].title()} moved to page 2 {tgt}", C))
    return out[:5]
