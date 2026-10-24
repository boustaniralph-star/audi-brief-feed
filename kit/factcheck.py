#!/usr/bin/env python3
"""Audi Capital Daily Brief - independent fact audit (Ralph, 24.10.2026: no room for hallucinated facts once the brief
goes to clients). Runs on GitHub, outside the writer: for every facts.txt line that cites a web page, it opens the page
and checks that the key figure is actually printed there. Market prices ('market_data.json' / 'official close') are
checked against the market feed by pulse_check instead.
Usage: python3 factcheck.py facts.txt  -> prints one line per fact and a summary; exit 0 always (it reports, the
mailer decides). Statuses: CONFIRMED (a key figure is on the cited page), NOT FOUND (page opened, figure absent),
PARTIAL (fewer than half of its figures found), UNREACHABLE (paywall, block or error: cannot be audited), MARKET (market price, checked elsewhere), NO SOURCE."""
import html, re, sys, urllib.parse, urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def unwrap(u):
    """The real address behind a Google redirect, without tracking parameters."""
    u = u.strip().rstrip(".,;)")
    if "google.com/url" in u:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(u).query).get("q")
        if q:
            u = q[0]
    return u


def page_text(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*", "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(4_000_000).decode(r.headers.get_content_charset() or "utf-8", "ignore")
    raw = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", raw)
    t = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", t)


def figures(key):
    """Significant numbers in a key-figure field: years, DD.MM dates and single digits are skipped."""
    out = []
    for raw in re.findall(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?", key):
        v = raw.replace(",", "")
        if re.fullmatch(r"20[0-3]\d", v) or re.fullmatch(r"\d", v):
            continue
        if re.fullmatch(r"\d{1,2}\.\d{2}", raw) and 1 <= int(raw.split(".")[1]) <= 12 and not re.search(re.escape(raw) + r"\s*%", key):
            continue
        out.append(v)
    return out


def on_page(v, text):
    """True when the number appears on the page, in any common formatting (7.1 / 7.10, 4060.4 / 4,060.40)."""
    f = float(v)
    cands = {v}
    if "." in v:
        cands |= {v.rstrip("0").rstrip("."), f"{f:,.2f}", f"{f:,.1f}", f"{f:.2f}", f"{f:.1f}"}
    else:
        cands |= {f"{int(f):,}"}
    return any(re.search(r"(?<![\d.,])" + re.escape(c) + r"(?![\d])", text) for c in cands if c)


COMMON = set("""that this with from into over after before their about against while will would could also more most less
than said says year years week month today friday thursday monday tuesday wednesday saturday sunday percent profit revenue
shares stock stocks market markets index billion million quarter results rose fell gained lost close closed higher lower
""".split())


def is_section_page(u):
    """A homepage or section page ('argaam.com/en', 'zawya.com/en/capital-markets') shows whatever is new today, so a
    figure on it proves nothing about the story: such a citation counts as no source."""
    path = re.sub(r"^https?://[^/]+", "", u).split("?")[0].strip("/")
    segs = [s for s in path.split("/") if s]
    return len(segs) < 3 and not re.search(r"\d{4,}|[a-z0-9]+-[a-z0-9]+-[a-z0-9]+-[a-z0-9]+", path)


def keywords(text):
    """Distinctive words (names, places) in a key-figure field, for facts that carry no number."""
    return [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]{3,}", text) if w.lower() not in COMMON][:6]


def audit(lines, fetch=page_text):
    res = []
    cache = {}
    for l in lines:
        f = [x.strip() for x in l.split("|")]
        if len(f) < 3 or not f[0]:
            continue
        lead, key, src = f[0], f[1], f[2]
        urls = [unwrap(u) for u in re.findall(r"https?://[^\s;,|]+", src)]
        sections = [u for u in urls if is_section_page(u)]
        urls = [u for u in urls if not is_section_page(u)]
        nums = figures(key)
        if not urls and sections:
            res.append((lead, "NO SOURCE", "section page only: " + sections[0], nums))
            continue
        if not urls:
            res.append((lead, "MARKET" if re.search(r"market_data\.json|official close", src, re.I) else "NO SOURCE", "", nums))
            continue
        texts, where = [], urls[0]
        for u in urls:
            try:
                if u not in cache:
                    cache[u] = page_text(u) if fetch is page_text else fetch(u)
            except Exception:
                cache[u] = None
            if cache[u] is not None:
                texts.append(cache[u]); where = u
        if not texts:
            status = "UNREACHABLE"
        elif not nums:
            kw = keywords(key) or keywords(lead)
            hit = sum(1 for w in kw if any(re.search(r"\b" + re.escape(w) + r"\b", x, re.I) for x in texts))
            status = "CONFIRMED" if kw and hit >= max(1, (len(kw) + 1) // 2) else ("PARTIAL" if hit else "NOT FOUND")
        else:
            found = sum(1 for v in nums if any(on_page(v, x) for x in texts))
            # at least half of the logged figures (and at least one) must be printed on the cited pages
            status = "CONFIRMED" if found >= max(1, (len(nums) + 1) // 2) else ("PARTIAL" if found else "NOT FOUND")
        res.append((lead, status, where, nums))
    return res


def summary(res):
    c = {k: sum(1 for r in res if r[1] == k) for k in ("CONFIRMED", "PARTIAL", "NOT FOUND", "UNREACHABLE", "MARKET", "NO SOURCE")}
    return (f"fact audit: {c['CONFIRMED']} confirmed on the cited page, {c['PARTIAL']} partly confirmed, {c['NOT FOUND']} figure not on the page, "
            f"{c['UNREACHABLE']} page unreachable, {c['NO SOURCE']} without a source, {c['MARKET']} market prices")


if __name__ == "__main__":
    R = audit(open(sys.argv[1], encoding="utf-8").read().splitlines())
    for lead, st, u, n in R:
        print(f"{st:<12} {lead[:48]:<48} {', '.join(n[:3]):<24} {u[:90]}")
    print(summary(R))
