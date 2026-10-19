#!/usr/bin/env python3
"""Audi Capital Daily Brief - bring a cloud package up to the desktop standard before the PDF is built.
Deterministic, no AI. Used by mailer.py; every step is optional and the caller falls back to the original files.
  ytd(content, txt, md)      add ", +x.xx% YTD" to index closes quoted as "<index> <level> (<day %>)" when the level
                             matches market_data.json; never touches a figure, only appends the verified YTD.
  auto_hero(content, md)     when the writer sent no hero for a listed company, build the classic "line" hero:
                             12 months of weekly closes plus the last daily closes, the company against two benchmarks,
                             rebased to 100 (Yahoo Finance daily closes; settled sessions only)."""
import copy, datetime as dt, json, os, re, sys, time, urllib.parse, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def get(url, timeout=30, tries=3):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"}), timeout=timeout) as r:
                return r.read().decode("utf-8-sig")
        except Exception as e:
            last = e; time.sleep(2 + 3 * i)
    raise last

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


# ---------------------------------------------------------------- data-provider names
PROVIDER = re.compile(r"\b(?:Robinhood|IBKR|Interactive Brokers|Yahoo(?: Finance)?)\b", re.I)


_PROV = r"(?:Interactive Brokers|Yahoo Finance|Robinhood|IBKR|Yahoo)"


def _scrub_s(s):
    if not isinstance(s, str) or not PROVIDER.search(s):
        return s
    s = re.sub(r"\s*\((?:via |from |source:? )?" + _PROV + r"\)", "", s, flags=re.I)              # "(IBKR)"
    s = re.sub(r"[;,]?\s*(?:via|from|per|according to|source:?)\s+" + _PROV + r"\b", "", s, flags=re.I)  # "from Yahoo"
    s = re.sub(r"\b" + _PROV + r"(?:'s)?\s+", "", s, flags=re.I)                                    # "Robinhood official"
    s = re.sub(r"\b" + _PROV + r"\b", "", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s+([,;.)])", r"\1", s).strip(" ;,")
    return s[:1].upper() + s[1:] if s else s


def scrub(content, hero=None):
    """Remove data-provider names from chart captions, card subtitles, chart notes, tiles and panel captions (not from
    news text, where a provider can be the story). Returns (content, hero, n_changed)."""
    C, H, n = copy.deepcopy(content), copy.deepcopy(hero) if hero is not None else None, 0
    def fix(d, keys):
        nonlocal n
        for k in keys:
            if isinstance(d, dict) and isinstance(d.get(k), str):
                new = _scrub_s(d[k]); n += new != d[k]; d[k] = new
    fix(C.get("cotd", {}), ("chart_title", "chart_method"))
    for card in C.get("p2", {}).get("cards", []) or []:
        fix(card, ("title", "sub", "tiles_head"))
        for ch in card.get("charts", []) or []:
            fix(ch, ("title", "note", "sub"))
        for t in card.get("tiles", []) or []:
            fix(t, ("l",))
    for side in ("extras_left", "extras_right"):
        for x in C.get("p1", {}).get(side, []) or []:
            fix(x, ("title", "note"))
    for pnl in C.get("p2", {}).get("gcc_panels", []) or []:
        fix(pnl, ("label", "small", "caption"))
    if isinstance(H, dict):
        fix(H, ("title", "note", "ratings_note", "close_label"))
        for k in ("wiped", "ripple", "volx", "eps"):
            fix(H.get(k), ("title",))
    return C, H, n


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


def auto_hero(content, md, get=get, now=None, closes=None):
    """Returns (hero, content) with a line hero and its caption, or (None, None)."""
    cot = content.get("cotd", {})
    res = resolve(cot.get("ticker"))
    if not res:
        return None, None
    sym, peers = res
    now = now or int(time.time())
    if closes:   # [[date, close], ...] x3 (company, benchmark 1, benchmark 2), e.g. from Robinhood daily historicals
        load = lambda s: sorted((dt.date.fromisoformat(d[:10]), float(c)) for d, c in s)
        subj = load(closes[0])
        series = [dict(load(s)) for s in closes[1:3]]
        if len(series) < 2 or min(len(s) for s in series) < 120:
            return None, None
    else:
        subj = _settled(get, sym, now)
        series = []
        for psym, _ in peers:
            p = dict(_settled(get, psym, now))
            if len(p) < 120:
                return None, None
            series.append(p)
    if len(subj) < 120:
        return None, None
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


def unhooked(content):
    """Safety net for the hooks: the content without the Number of the day callout, then also without the Today in 3
    strip, so a page that does not fit with them is still sent rather than lost. Each item is (label, content)."""
    out = []
    C = copy.deepcopy(content)
    for side in ("extras_left", "extras_right"):
        C.get("p1", {})[side] = [x for x in C.get("p1", {}).get(side, []) or [] if x.get("type") != "numday"]
    out.append(("without Number of the day", C))
    C2 = copy.deepcopy(C); C2.pop("top3", None)
    out.append(("without Number of the day and Today in 3", C2))
    return out


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


USAGE = """Writer usage (run in /tmp/brief before building):
  python3 enrich.py hero content_v2.json hero_data.json
      builds the 12-month line hero for the Company of the Day from Yahoo daily closes and writes hero_data.json
      plus cotd.chart_title / chart_method into content_v2.json (benchmarks: Nasdaq and S&P 500 for US listings,
      the home index and S&P 500 otherwise). Needs cotd.ticker like "Nasdaq: CRWV", "NYSE: GS", "Tadawul: 2280".
  python3 enrich.py hero content_v2.json hero_data.json --closes company.json bench1.json bench2.json
      same, from daily closes you saved yourself (e.g. Robinhood get_equity_historicals, interval day, span year),
      each file [[\"YYYY-MM-DD\", close], ...]; benchmark names stay Nasdaq / S&P 500 unless you edit them after.
  python3 enrich.py scrub content_v2.json hero_data.json
      removes data-provider names (Robinhood, IBKR, Yahoo) from chart captions, subtitles, notes and panel captions.
  python3 enrich.py ytd content_v2.json market_data.json
      appends ", +x.xx% YTD" to every index close quoted as "<index> <level> (<day %>)"."""


def _cli(a):
    if len(a) >= 3 and a[0] == "hero":
        C = json.load(open(a[1], encoding="utf-8-sig"))
        closes = [json.load(open(f, encoding="utf-8-sig")) for f in a[a.index("--closes") + 1:a.index("--closes") + 4]] if "--closes" in a else None
        h, C2 = auto_hero(C, {}, closes=closes)
        if not h:
            print("no hero: ticker not recognized or fewer than 120 daily closes; set cotd.ticker like 'Nasdaq: CRWV' or pass --closes"); return 2
        json.dump(h, open(a[2], "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(C2, open(a[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("hero:", h["names"], len(h["rows"]), "points |", C2["cotd"]["chart_title"]); return 0
    if len(a) == 3 and a[0] == "scrub":
        C = json.load(open(a[1], encoding="utf-8-sig")); H = json.load(open(a[2], encoding="utf-8-sig"))
        C2, H2, n = scrub(C, H)
        json.dump(C2, open(a[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        json.dump(H2, open(a[2], "w", encoding="utf-8"), ensure_ascii=False)
        print("provider names removed from", n, "caption(s)"); return 0
    if len(a) == 3 and a[0] == "ytd":
        C = json.load(open(a[1], encoding="utf-8-sig")); md = json.load(open(a[2], encoding="utf-8-sig"))
        C2, _, n = ytd(C, "", md)
        json.dump(C2, open(a[1], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("YTD added to", n, "bullet(s)"); return 0
    if a and a[0] == "newsletters":
        print(newsletter_query()); return 0
    print(USAGE); return 1


def newsletters(path=None):
    """[(name, address)] from newsletters.txt next to this file (or path)."""
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "newsletters.txt")
    out = []
    for l in open(path, encoding="utf-8"):
        l = l.strip()
        if l and not l.startswith("#") and "|" in l:
            n, a = [x.strip() for x in l.split("|", 1)]
            out.append((n, a))
    return out


def newsletter_query(days=1, path=None):
    """The Gmail query for every newsletter that arrived since the previous edition."""
    return f"newer_than:{days}d from:(" + " OR ".join(a for _, a in newsletters(path)) + ")"

if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
