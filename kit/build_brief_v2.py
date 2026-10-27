#!/usr/bin/env python3
"""Audi Capital Daily Brief v2 builder (two-page A4, WeasyPrint + matplotlib SVG).

Usage:  python3 build_brief_v2.py content_v2.json market_data.json hero_data.json OUT.pdf
Run from a folder that also holds wordmark.png and circles.png (transparent logos).
The content file carries the words; every chart is drawn from market_data.json,
hero_data.json or numbers inside the content file. Nothing is estimated.
"""
import json, os, re, sys, datetime as dt, html
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.dates as md
from matplotlib import font_manager as fm

F = os.path.expanduser("~/.fonts/")
for f in os.listdir(F):
    fm.fontManager.addfont(F + f)
import extras_v2 as X

# ------------------------------------------------------------------ labels never sit on a line or a bar
# Every chart (here and in extras_v2) is saved through plt.savefig, so this pass runs on all of them: a label whose
# box crosses a data line or a bar is moved up or down (offset labels) to the nearest clear spot, and if no spot is
# clear it gets a white backing so it stays readable. Gridlines are ignored (faint by design).
from matplotlib.path import Path as _Path
from matplotlib.text import Annotation as _Ann
DECLUTTER = {"moved": 0, "backed": 0}
WINDOWS = {}  # trend charts: how many sessions each one actually shows (its heading must not claim another window)

def _on_grid(ax, bb):
    """True when a label box crosses a gridline (labels are not moved for these, only backed in white)."""
    for ln in ax.get_xgridlines() + ax.get_ygridlines():
        if ln.get_visible() and _Path(ln.get_transform().transform(ln.get_xydata())).intersects_bbox(bb, filled=False):
            return True
    return False

def _hits(ax, bb, r):
    for ln in ax.get_lines():
        if not ln.get_visible() or ln in ax.get_xgridlines() or ln in ax.get_ygridlines() or ln.get_linewidth() < .5:
            continue
        xy = ln.get_transform().transform(ln.get_xydata())
        if len(xy) == 1:
            if bb.contains(*xy[0]): return True
        elif _Path(xy).intersects_bbox(bb, filled=False):
            return True
    for cont in ax.containers:
        for p in getattr(cont, "patches", []):
            if p.get_visible() and bb.overlaps(p.get_window_extent(r)): return True
    return False

def _declutter(fig):
    from matplotlib.transforms import Bbox
    fig.canvas.draw(); r = fig.canvas.get_renderer()
    for ax in fig.axes:
        others = lambda me: [o.get_window_extent(r) for o in ax.texts if o is not me and o.get_visible() and o.get_text().strip()]
        for t in list(ax.texts):
            if not t.get_visible() or not t.get_text().strip() or t.get_bbox_patch() is not None:
                continue
            shrink = lambda b: Bbox.from_extents(b.x0 + 1, b.y0 + 1, b.x1 - 1, b.y1 - 1)
            if not _hits(ax, shrink(t.get_window_extent(r)), r):
                if ax.yaxis._major_tick_kw.get("gridOn") or ax.xaxis._major_tick_kw.get("gridOn") or ax.get_ygridlines():
                    if _on_grid(ax, shrink(t.get_window_extent(r))):
                        t.set_bbox(dict(facecolor="white", edgecolor="none", pad=.8, alpha=.92)); t.set_zorder(max(t.get_zorder(), 6))
                        DECLUTTER["backed"] += 1
                continue
            fixed = False
            if isinstance(t, _Ann) and t.anncoords == "offset points":
                x0, y0 = t.xyann
                for dy in (6, -6, 9, -9, 12, -12, 16, -16, 20, -20):
                    t.xyann = (x0, y0 + dy)
                    bb = shrink(t.get_window_extent(r))
                    if not _hits(ax, bb, r) and not any(bb.overlaps(o) for o in others(t)) and fig.bbox.contains(bb.x1, bb.y1) and fig.bbox.contains(bb.x0, bb.y0):
                        fixed = True; DECLUTTER["moved"] += 1; break
                if not fixed:
                    t.xyann = (x0, y0)
            if not fixed:
                t.set_bbox(dict(facecolor="white", edgecolor="none", pad=.8, alpha=.92)); t.set_zorder(max(t.get_zorder(), 6))
                DECLUTTER["backed"] += 1

_savefig = plt.savefig
def _savefig_clear(*a, **k):
    try:
        _declutter(plt.gcf())
    except Exception as e:
        print("declutter skipped:", type(e).__name__, e)
    return _savefig(*a, **k)
plt.savefig = X.plt.savefig = _savefig_clear
X.install_overlap_guard()
NAVY, STEEL, SILVER = "#1B2A4A", "#4A6FA5", "#8A9BB0"
UP, DN, GRID, MUTE, MONO = "#2F8F6B", "#C0453A", "#E3E8EF", "#6B7A90", "IBM Plex Mono"
UP_M, DN_M, NAVY_M = "#B9D8CB", "#E8BDB8", "#B4BDCC"  # muted tints: bars that are context, not the story
plt.rcParams.update({"font.family": "Inter", "font.size": 8, "axes.edgecolor": GRID,
                     "xtick.color": MUTE, "ytick.color": MUTE, "svg.fonttype": "none",
                     "axes.spines.top": False, "axes.spines.right": False})


def clean(ax):
    for s in ["left", "bottom"]:
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)


def safe_yticks(ax, bottom=.12, top=.06):
    """Keep y tick labels off the plot's edges: one at the very top is clipped by the canvas, and one at the bottom
    collides with the first x label in the corner."""
    lo, hi = ax.get_ylim(); span = hi - lo
    ax.set_yticks([t for t in ax.get_yticks() if lo + span * bottom <= t <= hi - span * top])
    ax.set_ylim(lo, hi)


def mono_ticks(ax, axis="y"):
    for t in (ax.get_yticklabels() if axis == "y" else ax.get_xticklabels()):
        t.set_family(MONO)


# ----------------------------------------------------------------- charts
def hero(h, out="hero.svg"):
    rows, names = h["rows"], h["names"]
    xs = [dt.date.fromisoformat(r[0]) for r in rows]
    day_color = UP if h.get("day_color", "up") == "up" else DN
    fig, ax = plt.subplots(figsize=(7.3, h.get("height", 1.6)), dpi=200)
    styles = [(NAVY, 2.0), (STEEL, 1.2), (SILVER, 1.2)]
    rb_all, ends = [], []
    for i, (n, (c, w)) in enumerate(zip(names, styles), 1):
        v = [r[i] for r in rows]
        rb = [x / v[0] * 100 for x in v]
        rb_all.append(rb)
    lo = min(min(r) for r in rb_all) - 6
    hi = max(max(r) for r in rb_all) + 6
    hi_pt = None
    if h.get("high_close") and h.get("high_price"):
        hi_pt = h["high_price"] / rows[0][1] * 100
        hi = max(hi, hi_pt + 4)
    ax.set_ylim(lo, hi)
    # fixed y ticks kept clear of the top and bottom edge (a label at the limit is clipped by the canvas)
    edge = (hi - lo) * 0.05
    ax.set_yticks([t for t in ax.get_yticks() if lo + edge <= t <= hi - edge])
    for i, (n, (c, w)) in enumerate(zip(names, styles), 1):
        rb = rb_all[i - 1]
        ax.plot(xs, rb, color=c, lw=w, zorder=3 if i == 1 else 2)
        if i == 1:
            ax.fill_between(xs, rb, lo, color=NAVY, alpha=.06, zorder=1)
            ax.plot(xs[-2:], rb[-2:], color=day_color, lw=2.4, zorder=4)
            ax.scatter([xs[-1]], [rb[-1]], s=24, color=day_color, edgecolor="white", linewidth=1, zorder=5)
        ends.append([rb[-1], n, c, i == 1, rb[-1] - 100])
    # story events on the subject line: a ringed dot and a short label above it (what happened, not just the price)
    for ev in h.get("events", [])[:3]:
        d = dt.date.fromisoformat(ev["date"])
        k = min(range(len(xs)), key=lambda j: abs((xs[j] - d).days))
        yv = rb_all[0][k]
        ax.scatter([xs[k]], [yv], s=30, facecolor="white", edgecolor=NAVY, linewidth=1.3, zorder=6)
        up = ev.get("pos", "above") == "above"
        ax.annotate(ev["label"], (xs[k], yv), xytext=(0, 14 if up else -14), textcoords="offset points",
                    ha=ev.get("ha", "center"), va="bottom" if up else "top", fontsize=6.8, color=NAVY, fontweight="bold",
                    arrowprops=dict(arrowstyle="-", color=NAVY, lw=.6, shrinkA=0, shrinkB=3), zorder=6)
    if hi_pt:
        ax.plot([xs[-1], xs[-1]], [rb_all[0][-1], hi_pt], color=NAVY, lw=.8, ls=(0, (1, 1.5)), zorder=4)
        ax.scatter([xs[-1]], [hi_pt], s=20, facecolor="white", edgecolor=NAVY, linewidth=1, zorder=5)
    # nudge end labels so none overlap
    span = hi - lo
    thr = span * 0.115
    order = sorted(range(len(ends)), key=lambda k: ends[k][0])
    pos = [e[0] for e in ends]
    for a, b in zip(order, order[1:]):
        if pos[b] - pos[a] < thr:
            pos[b] = pos[a] + thr
    for k, e in enumerate(ends):
        ax.annotate(f"{e[1]}  {e[4]:+.0f}%", (xs[-1], e[0]), xytext=(9, (pos[k] - e[0]) / span * h.get("height", 1.6) * 72 * .8),
                    textcoords="offset points", va="center", fontsize=7.4, color=e[2],
                    fontweight="bold" if e[3] else "normal")
    ax.axhline(100, color=SILVER, lw=.6, ls=(0, (2, 2)), zorder=0)
    ax.set_xlim(xs[0], xs[-1] + dt.timedelta(days=64))
    ax.yaxis.grid(True, color=GRID, lw=.6)
    ax.set_axisbelow(True)
    clean(ax)
    ax.xaxis.set_major_formatter(md.DateFormatter("%b %y"))
    tk = [d for d in (dt.date(2025, 12, 1), dt.date(2026, 2, 1), dt.date(2026, 4, 1), dt.date(2026, 6, 1), dt.date(2026, 8, 1), dt.date(2026, 10, 1)) if xs[0] < d <= xs[-1]]
    ax.set_xticks(tk)
    ax.tick_params(labelsize=7)
    mono_ticks(ax)
    if h.get("note"):
        ax.text(0.01, 0.06, h["note"], transform=ax.transAxes, fontsize=6.8, color=MUTE, va="bottom")
    plt.tight_layout(pad=.2)
    plt.savefig(out, transparent=True)
    plt.close()


INDEX_ORDER = ["S&P 500", "Nasdaq Composite", "Dow Jones", "STOXX 600", "DAX", "CAC 40", "FTSE 100",
               "Nikkei 225", "Hang Seng", "CSI 300", "Sensex", "Tadawul TASI"]
SHORT = {"Nasdaq Composite": "Nasdaq", "Nikkei 225": "Nikkei", "Tadawul TASI": "TASI", "Dow Jones": "Dow"}


def bars(md_items, key, out, w=3.45, h=2.2, day_col=False, highlight=None, col_key="chgDay", col_label="DAY"):
    rows = [(SHORT.get(i["name"], i["name"]), i[key], i.get(col_key) if i.get(col_key) is not None else 0.0, i["name"] == "Tadawul TASI")
            for i in md_items if i["name"] in INDEX_ORDER and i.get(key) is not None]
    rows.sort(key=lambda r: r[1])
    h = max(h, 0.15 * len(rows))  # keep row labels from overlapping (min 0.15 in per row)
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    ys = range(len(rows))
    hl = set(highlight or [])
    on = lambda r: not hl or r[0] in hl
    cols = [(NAVY if r[3] else (UP if r[1] >= 0 else DN)) if on(r) else (NAVY_M if r[3] else (UP_M if r[1] >= 0 else DN_M)) for r in rows]
    ax.barh(list(ys), [r[1] for r in rows], color=cols, height=.62, zorder=3)
    ax.set_yticks(list(ys))
    ax.set_yticklabels([r[0] for r in rows], fontsize=7.2, color=NAVY)
    for t, r in zip(ax.get_yticklabels(), rows):
        if hl and r[0] in hl: t.set_fontweight("bold")
        elif hl: t.set_color(MUTE)
    vmax = max(abs(r[1]) for r in rows)
    ax.set_xlim(-vmax * 1.45 if min(r[1] for r in rows) < 0 else 0, vmax * (2.0 if day_col else 1.45))
    for y, r in zip(ys, rows):
        off = vmax * .04
        ax.text(r[1] + (off if r[1] >= 0 else -off), y, f"{r[1]:+.2f}%", va="center",
                ha="left" if r[1] >= 0 else "right", fontsize=6.6, family=MONO, color=NAVY if on(r) else MUTE,
                fontweight="bold" if hl and r[0] in hl else "normal")
        if day_col:
            ax.text(1.0, y, f"{r[2]:+.2f}%", transform=ax.get_yaxis_transform(), va="center", ha="right",
                    fontsize=6.6, family=MONO, color=UP if r[2] >= 0 else DN)
    if day_col:
        ax.text(1.0, len(rows) - .35, col_label, transform=ax.get_yaxis_transform(), ha="right", fontsize=6,
                color=MUTE, family=MONO)
    ax.axvline(0, color=SILVER, lw=.6, zorder=2)
    ax.set_xticks([])
    clean(ax)
    ax.spines["bottom"].set_visible(False)
    plt.tight_layout(pad=.2)
    plt.savefig(out, transparent=True)
    plt.close()


def rates_curve(md_items, extra, out, w=3.45, h=1.55):
    g = {i["name"]: i for i in md_items}
    labs = ["SOFR", "2Y", "10Y", "30Y"]
    vals = [g["SOFR"]["close"], g["US 2Y yield"]["close"], g["US 10Y yield"]["close"], g["US 30Y yield"]["close"]]
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    x = list(range(4))
    ax.plot(x, vals, color=NAVY, lw=1.8, zorder=3)
    ax.scatter(x, vals, s=26, facecolor="white", edgecolor=NAVY, linewidth=1.3, zorder=4)
    for xi, v in zip(x, vals):
        # the first label goes left of its point: above it, a steep rise to the next point runs through the text
        first = xi == 0
        ax.annotate(f"{v:.2f}%", (xi, v), xytext=(-6, 0) if first else (0, 6), textcoords="offset points",
                    ha="right" if first else "center", va="center" if first else "baseline",
                    fontsize=6.6, family=MONO, color=NAVY)
    for e in extra or []:
        xi = labs.index(e["x"])
        ax.scatter([xi + .12], [e["y"]], s=22, color=STEEL if e.get("c") != "dn" else DN, zorder=5)
        ax.annotate(f'{e["label"]} {e["y"]:.2f}%', (xi + .12, e["y"]), xytext=(6, -2), textcoords="offset points",
                    fontsize=6.4, family=MONO, color=STEEL, va="top")
    ax.set_xticks(x)
    ax.set_xticklabels(labs, fontsize=7.2, color=NAVY)
    lo = min(vals + [e["y"] for e in extra or []]) - .5
    ax.set_ylim(lo, max(vals) + .55)
    ax.set_xlim(-.9, 3.5)
    ax.yaxis.grid(True, color=GRID, lw=.6)
    ax.set_axisbelow(True)
    from matplotlib.ticker import MultipleLocator, FormatStrFormatter
    ax.yaxis.set_major_locator(MultipleLocator(.5))
    ax.yaxis.set_major_formatter(FormatStrFormatter("%.1f"))
    safe_yticks(ax, bottom=.05, top=.05)
    clean(ax)
    fig.canvas.draw()
    mono_ticks(ax)
    ax.tick_params(axis="y", labelsize=6.6)
    plt.tight_layout(pad=.2)
    plt.savefig(out, transparent=True)
    plt.close()


def commodities(md_items, out, w=3.45, h=1.1):
    g = {i["name"]: i for i in md_items}
    rows = [(n, g[n]["chgYtd"], g[n]["chgDay"]) for n in ["Brent", "WTI", "Gold"]]
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    ys = list(range(len(rows)))[::-1]
    vmax = max(abs(r[1]) for r in rows)
    ax.barh(ys, [r[1] for r in rows], color=[UP if r[1] >= 0 else DN for r in rows], height=.55, zorder=3)
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows], fontsize=7.2, color=NAVY)
    ax.set_xlim(-vmax * .4, vmax * 1.5)
    for y, r in zip(ys, rows):
        ax.text(r[1] + (vmax * .03 if r[1] >= 0 else -vmax * .03), y, f"{r[1]:+.1f}%", va="center", ha="left" if r[1] >= 0 else "right",
                fontsize=6.6, family=MONO, color=NAVY)
        ax.text(1.0, y, f"{r[2]:+.2f}%", transform=ax.get_yaxis_transform(), va="center", ha="right",
                fontsize=6.6, family=MONO, color=UP if r[2] >= 0 else DN)
    ax.text(1.0, len(rows) - .45, "DAY", transform=ax.get_yaxis_transform(), ha="right", fontsize=6, color=MUTE,
            family=MONO)
    ax.axvline(0, color=SILVER, lw=.6)
    ax.set_xticks([])
    clean(ax)
    plt.tight_layout(pad=.2)
    plt.savefig(out, transparent=True)
    plt.close()


def movers(rows, out, w=3.45, h=1.7, highlight=None):
    """rows: [{"name","close","high"(optional)}] -> diverging bars, ghost bar for the intraday high."""
    rows = sorted(rows, key=lambda r: r["close"])
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    ys = list(range(len(rows)))
    vmax = max(max(abs(r["close"]), abs(r.get("high", 0))) for r in rows)
    for y, r in zip(ys, rows):
        on = not highlight or r["name"] in highlight
        c = (UP if r["close"] >= 0 else DN) if on else (UP_M if r["close"] >= 0 else DN_M)
        if r.get("high") is not None:
            ax.barh(y, r["high"], color=c, alpha=.18, height=.62, zorder=2)
        ax.barh(y, r["close"], color=c, height=.62, zorder=3)
        lab = f'{r["close"]:+.1f}%' + (f'  (high {r["high"]:+.1f}%)' if r.get("high") is not None else "")
        edge = max(r["close"], r.get("high") or 0) if r["close"] >= 0 else r["close"]
        ax.text(edge + (vmax * .03 if r["close"] >= 0 else -vmax * .03), y, lab, va="center",
                ha="left" if r["close"] >= 0 else "right", fontsize=6.6, family=MONO, color=NAVY)
        ax.text(-vmax * .03 if r["close"] >= 0 else vmax * .03, y, r["name"], va="center",
                ha="right" if r["close"] >= 0 else "left", fontsize=7.2, color=NAVY if on else MUTE,
                fontweight="bold" if highlight and on else "normal")
    ax.set_xlim(-vmax * 1.0, vmax * 2.1)
    ax.axvline(0, color=SILVER, lw=.6, zorder=2)
    ax.set_yticks([])
    ax.set_xticks([])
    clean(ax)
    plt.tight_layout(pad=.2)
    plt.savefig(out, transparent=True)
    plt.close()


# ----------------------------------------------------------------- html helpers
NUM = re.compile(r'(?<![\w#.])([+-]?\d[\d,]*(?:\.\d+)?(?:%|bps|k)?)(?![A-Za-z\d])')  # whole number incl. a k suffix (no '30' + '0k' splits)
PROT = re.compile(r'(S&P 500|STOXX 600|CAC 40|FTSE 100|CSI 300|Nikkei 225|Q[1-4]|[0-9]+Y\b)')


def nums(text):
    parts = PROT.split(html.escape(text, quote=False).replace("&lt;br&gt;", "\x00"))
    return "".join(p if (i % 2) else _nums(p) for i, p in enumerate(parts)).replace("\x00", "<br>")


def _nums(text):

    def rep(m):
        s = m.group(1)
        cls = "n"
        if s[0] in "+-" and (s.endswith("%") or s.endswith("bps")):
            cls += " up" if s[0] == "+" else " dn"
        return f'<span class="{cls}">{s}</span>'
    return NUM.sub(rep, text)


def lis(items):
    return "<ul>" + "".join(f"<li><b>{html.escape(a)}</b> {nums(b)}</li>" for a, b in items) + "</ul>"


def sec(title, items, extra=""):
    return f'<div class="sec"><h2>{html.escape(title).replace("&amp;amp;", "&amp;")}</h2>{extra}{lis(items)}</div>'


CSS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "brief_v2.css"), encoding="utf-8").read()

# Page 3: the Important Notice and Disclaimer approved by Audi Capital Compliance (Ralph, 26.10.2026: "the only thing
# I want there"). Compliance's wording, verbatim, English and Arabic (from Daily_Brief_Disclaimer.docx); change it
# only with a new approved text.
DISCLAIMER_EN = ('Important Notice and Disclaimer', [
    'This Brief is issued by Audi Capital, Riyadh, Kingdom of Saudi Arabia, a capital market institution licensed by the Capital Market Authority (License No. 06017-37), for information purposes only.',
    'It does not constitute investment, legal, tax, or accounting advice, a personal recommendation, or an offer or solicitation to buy or sell any security, and does not take into account the objectives, financial situation, or needs of any recipient.',
    'Information is obtained from sources believed to be reliable, but its accuracy and completeness are not guaranteed. Opinions are as at the date of publication and are subject to change without notice.',
    'Prices, values, or income of investments may fall, and investors may get back less than they invested. Past performance is not necessarily a guide to future performance.',
    'Audi Capital or its affiliates may hold positions in, or provide services to, issuers of securities mentioned in this Brief.',
    'To the fullest extent permitted by applicable law, Audi Capital accepts no liability for any loss arising from the use of or reliance on this Brief.',
    "This Brief may not be reproduced or redistributed without Audi Capital's prior written consent.",
    '© 2026 Audi Capital. All rights reserved.',
])
DISCLAIMER_AR = ('إشعار هام وإخلاء مسؤولية', [
    'صدرت هذه النشرة عن شركة عوده كابيتال ، الرياض – المملكة العربية السعودية ، وهي مؤسسة سوق مالية مرخص لها من هيئة السوق المالية (ترخيص رقم٣٧-٠٦٠١٧)، لأغراض المعلومات فقط.',
    'لا تُعد هذه النشرة نصيحة استثمارية أو قانونية أو ضريبية أو محاسبية، ولا توصية شخصية، ولا عرضاً أو دعوة لشراء أو بيع أي ورقة مالية، ولا تراعي الأهداف أو الوضع المالي أو احتياجات أي متلقٍ.',
    'المعلومات مستمدة من مصادر يُعتقد أنها موثوقة، دون ضمان لدقتها أو اكتمالها. والآراء الواردة بتاريخ النشر وعرضة للتغيير دون إشعار.',
    'قد تنخفض أسعار الاستثمارات أو قيمتها أو دخلها، وقد يسترد المستثمر أقل مما استثمره. والأداء السابق ليس بالضرورة دليلاً على الأداء المستقبلي.',
    'قد تحتفظ الشركة أو الشركات التابعة لها بمراكز في الجهات المصدرة للأوراق المالية المذكورة في هذه النشرة، أو تقدم لها خدمات.',
    'إلى أقصى حد يسمح به النظام، لا تتحمل الشركة أي مسؤولية عن أي خسارة ناتجة عن استخدام هذه النشرة أو الاعتماد عليها.',
    'لا يجوز نسخ هذه النشرة أو إعادة توزيعها دون موافقة كتابية مسبقة من الشركة.',
    '© 2026 شركة عوده كابيتال . جميع الحقوق محفوظة.',
])




# ---------------- rotating chart types (v3) ----------------
# All of these draw from series.json (made by make_series.py from the dated market_data snapshots).
SER = json.load(open("series.json")) if os.path.exists("series.json") else {}

def _latest():
    return max(max(v) for v in SER.values())

def _d(s):
    return dt.date.fromisoformat(s)

def _near(name, target, tol=5):
    """(date, value) of the last close on/before target; None if nothing within tol days."""
    s = SER[name]
    ks = [k for k in s if k <= target]
    if not ks:
        return None
    k = max(ks)
    if (_d(target) - _d(k)).days > tol:
        return None
    return k, s[k]

def _tgt(days):
    return (_d(_latest()) - dt.timedelta(days=days)).isoformat()

def _ser(name, start):
    pts = sorted((d, v) for d, v in SER[name].items() if d >= start)
    if len(pts) < 5:
        raise SystemExit(f"series.json has fewer than 5 points for {name} since {start}; use a classic chart type")
    return [_d(d) for d, _ in pts], [v for _, v in pts]

def _fmt(d):
    return _d(d).strftime("%b %d").replace(" 0", " ")

def multiples(names, out, w=3.45, h=1.5, days=11):
    start = _tgt(days)
    cols = 3
    rowsn = (len(names) + cols - 1) // cols
    fig, axs = plt.subplots(rowsn, cols, figsize=(w, h), dpi=200)
    axs = axs.flatten()
    for ax, n in zip(axs, names):
        xs, v = _ser(n, start)
        rb = [x / v[0] * 100 - 100 for x in v]
        col = UP if rb[-1] >= 0 else DN
        ax.plot(range(len(rb)), rb, color=col, lw=1.4)
        ax.fill_between(range(len(rb)), rb, 0, color=col, alpha=.10)
        ax.axhline(0, color=SILVER, lw=.5, ls=(0, (2, 2)))
        ax.scatter([len(rb) - 1], [rb[-1]], s=10, color=col, zorder=5)
        ax.set_title(SHORT.get(n, n), fontsize=6.8, color=NAVY, loc="left", pad=1, fontweight="bold")
        ax.text(1.0, 1.02, f"{rb[-1]:+.1f}%", transform=ax.transAxes, ha="right", fontsize=6.4, family=MONO, color=col)
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values(): sp.set_visible(False)
    for ax in axs[len(names):]: ax.axis("off")
    plt.tight_layout(pad=.3, h_pad=.9, w_pad=.8)
    plt.savefig(out, transparent=True); plt.close()

def rebased(names, out, w=3.45, h=1.5, days=11):
    start = _tgt(days)
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    cs = [NAVY, STEEL, SILVER]
    ends = []
    for n, c in zip(names, cs):
        xs, v = _ser(n, start)
        rb = [x / v[0] * 100 for x in v]
        ax.plot(range(len(rb)), rb, color=c, lw=1.8 if n == names[0] else 1.3)
        ends.append([rb[-1], n, c])
    xs, _ = _ser(names[0], start)
    ax.set_xticks(range(len(xs))); ax.set_xticklabels([d.strftime("%d %b") if i % 3 == 0 else "" for i, d in enumerate(xs)], fontsize=6.6)
    # end labels are spaced in points (at least 9 pt apart) on the drawn axes, so close finishes never print on top of each other
    plt.tight_layout(pad=.2); fig.canvas.draw()
    y0, y1 = ax.get_ylim(); ax.set_ylim(y0, y1)
    ppu = ax.get_window_extent().height / fig.dpi * 72 / (y1 - y0)
    ends.sort(key=lambda e: e[0]); pos = [e[0] * ppu for e in ends]
    for a in range(1, len(pos)):
        pos[a] = max(pos[a], pos[a-1] + 9)
    shift = (pos[-1] - ends[-1][0] * ppu) / 2
    for e, p in zip(ends, pos):
        ax.annotate(f"{SHORT.get(e[1], e[1])} {e[0]-100:+.1f}%", (len(rb) - 1, e[0]), xytext=(6, p - shift - e[0] * ppu),
                    textcoords="offset points", va="center", fontsize=7, color=e[2], fontweight="bold", zorder=6,
                    bbox=dict(facecolor="white", edgecolor="none", pad=.8))
    ax.plot([0, len(xs) - 1], [100, 100], color=SILVER, lw=.6, ls=(0, (2, 2)), zorder=1)
    ax.set_xlim(-.2, len(xs) + 2.6)
    ax.yaxis.grid(True, color=GRID, lw=.6); ax.set_axisbelow(True); clean(ax)
    mono_ticks(ax); ax.tick_params(axis="y", labelsize=6.6)
    safe_yticks(ax)
    plt.tight_layout(pad=.2); plt.savefig(out, transparent=True); plt.close()

def heatmap(names, out, w=3.45, h=1.9):
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap
    t5, t1m = _tgt(7), _tgt(30)
    rows = []
    for n in names:
        s = SER[n]; ks = sorted(s); last = s[ks[-1]]; prev = s[ks[-2]]
        r = [(last / prev - 1) * 100]
        for t in (t5, t1m):
            nr = _near(n, t)
            r.append((last / nr[1] - 1) * 100 if nr else float("nan"))
        rows.append(r)
    A = np.array(rows)
    cmap = LinearSegmentedColormap.from_list("d", [DN, "#F6F8FB", UP])
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    lim = np.maximum(np.nanmax(np.abs(A), axis=0), 1e-6)
    for i in range(A.shape[0]):
        for j in range(3):
            y = A.shape[0] - 1 - i
            if np.isnan(A[i, j]):
                ax.add_patch(plt.Rectangle((j, y), .96, .9, color="#EEF1F5", lw=0))
                ax.text(j + .48, y + .45, "n/a", ha="center", va="center", fontsize=6.4, family=MONO, color=MUTE)
                continue
            t = .5 + .5 * np.clip(A[i, j] / lim[j], -1, 1)
            ax.add_patch(plt.Rectangle((j, y), .96, .9, color=cmap(t), lw=0))
            ax.text(j + .48, y + .45, f"{A[i, j]:+.1f}%", ha="center", va="center", fontsize=6.4, family=MONO, color=NAVY)
    ax.set_xlim(0, 3); ax.set_ylim(0, A.shape[0])
    ref = names[0]
    l5 = _near(ref, t5); l1 = _near(ref, t1m)
    ax.set_xticks([.48, 1.48, 2.48])
    ax.set_xticklabels(["1 day", f"Since {_fmt(l5[0])}" if l5 else "1 week", f"Since {_fmt(l1[0])}" if l1 else "1 month"], fontsize=6.6, color=MUTE)
    ax.xaxis.tick_top()
    ax.set_yticks([A.shape[0] - 1 - i + .45 for i in range(A.shape[0])]); ax.set_yticklabels([SHORT.get(n, n) for n in names], fontsize=6.8, color=NAVY)
    for sp in ax.spines.values(): sp.set_visible(False)
    ax.tick_params(length=0)
    plt.tight_layout(pad=.2); plt.savefig(out, transparent=True); plt.close()

def curve_compare(out, w=3.45, h=1.55):
    names = ["US 2Y yield", "US 10Y yield", "US 30Y yield"]
    labs = ["2Y", "10Y", "30Y"]
    t1, t2 = _tgt(7), _tgt(30)
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    sets = []
    for t, c, lw, dy in ((t2, SILVER, 1.2, 0), (t1, STEEL, 1.4, -6), (None, NAVY, 2.0, 5)):
        if t is None:
            v = [SER[n][max(SER[n])] for n in names]; lab = _fmt(max(SER[names[0]]))
        else:
            nr = [_near(n, t) for n in names]
            if any(x is None for x in nr): continue
            v = [x[1] for x in nr]; lab = _fmt(nr[0][0])
        ax.plot(range(3), v, color=c, lw=lw, marker="o", ms=3.5)
        ax.annotate(f"{lab}  {v[-1]:.2f}%", (2, v[-1]), xytext=(6, dy), textcoords="offset points", va="center", fontsize=6.8, color=c, fontweight="bold" if t is None else "normal", family=MONO)
    ax.set_xticks(range(3)); ax.set_xticklabels(labs, fontsize=7.2, color=NAVY); ax.set_xlim(-.2, 3.3)
    ax.yaxis.grid(True, color=GRID, lw=.6); ax.set_axisbelow(True); clean(ax)
    mono_ticks(ax); ax.tick_params(axis="y", labelsize=6.6)
    plt.tight_layout(pad=.2); plt.savefig(out, transparent=True); plt.close()

def rates_trend(out, w=3.45, h=1.55, days=11):
    start = _tgt(days)
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    for n, lab, c, lw in (("US 30Y yield", "30Y", SILVER, 1.2), ("US 10Y yield", "10Y", NAVY, 2.0), ("US 2Y yield", "2Y", STEEL, 1.4)):
        xs, v = _ser(n, start)
        ax.plot(range(len(v)), v, color=c, lw=lw)
        ax.annotate(f"{lab} {v[-1]:.2f}%", (len(v) - 1, v[-1]), xytext=(6, 0), textcoords="offset points", va="center", fontsize=6.8, color=c, family=MONO, fontweight="bold" if lab == "10Y" else "normal")
    xs, _ = _ser("US 10Y yield", start)
    ax.set_xticks(range(len(xs))); ax.set_xticklabels([d.strftime("%d %b") if i % 3 == 0 else "" for i, d in enumerate(xs)], fontsize=6.6)
    ax.set_xlim(-.2, len(xs) + 2.4)
    ax.yaxis.grid(True, color=GRID, lw=.6); ax.set_axisbelow(True); clean(ax)
    mono_ticks(ax); ax.tick_params(axis="y", labelsize=6.6)
    safe_yticks(ax)
    plt.tight_layout(pad=.2); plt.savefig(out, transparent=True); plt.close()

def _add_windows(M):
    """Give every market item chg5 (about 1 week) and chgM (about 1 month) in percent, from series.json."""
    for i in M:
        n = i["name"]
        if n not in SER or i.get("close") is None:
            continue
        for key, days in (("chg5", 7), ("chgM", 30)):
            nr = _near(n, _tgt(days))
            if nr:
                i[key] = (i["close"] / nr[1] - 1) * 100

def hero_guidance(h, out="hero.svg"):
    labs, vals, kinds = h["labels"], h["values"], h["kinds"]
    fig, ax = plt.subplots(figsize=(7.3, h.get("height", 1.6)), dpi=200)
    cols = [NAVY if k == "actual" else (STEEL if k == "target" else SILVER) for k in kinds]
    ys = list(range(len(vals)))[::-1]
    ax.barh(ys, vals, color=cols, height=.58, zorder=3)
    for y, v, l, k in zip(ys, vals, h["notes"], kinds):
        ax.text(v + max(vals) * .012, y, l, va="center", fontsize=7.2, family=MONO, color=NAVY)
    ax.set_yticks(ys); ax.set_yticklabels(labs, fontsize=7.4, color=NAVY)
    ax.set_xlim(0, max(vals) * 1.28); ax.set_xticks([])
    for sp in ax.spines.values(): sp.set_visible(False)
    ax.tick_params(length=0)
    plt.tight_layout(pad=.2); plt.savefig(out, transparent=True); plt.close()

def hero_drawdown(h, out="hero.svg"):
    fig, axs = plt.subplots(1, 2, figsize=(7.3, h.get("height", 1.6)), dpi=200)
    for ax, key, ttl in ((axs[0], "ret", "Return since Oct 10, 2025"), (axs[1], "dd", "Return since Jan 2, 2026")):
        pairs = sorted(zip(h["names"], h[key]), key=lambda p: p[1])
        ys = range(len(pairs))
        ax.barh(list(ys), [p[1] for p in pairs], color=[NAVY if p[0] == h["names"][0] else STEEL for p in pairs], height=.55, zorder=3)
        ax.set_yticks(list(ys)); ax.set_yticklabels([p[0] for p in pairs], fontsize=7.2, color=NAVY)
        vm = max(abs(p[1]) for p in pairs)
        for y, p in zip(ys, pairs):
            ax.text(p[1] + (vm * .03 if p[1] >= 0 else -vm * .03), y, f"{p[1]:+.0f}%", va="center", ha="left" if p[1] >= 0 else "right", fontsize=7, family=MONO, color=NAVY)
        ax.set_xlim(min(0, min(p[1] for p in pairs)) * 1.45, max(0, max(p[1] for p in pairs)) * 1.3 + 1)
        ax.set_xticks([]); ax.set_title(ttl, fontsize=7, color=MUTE, loc="left")
        for sp in ax.spines.values(): sp.set_visible(False)
        ax.axvline(0, color=SILVER, lw=.6); ax.tick_params(length=0)
    plt.tight_layout(pad=.3, w_pad=1.5); plt.savefig(out, transparent=True); plt.close()


def main(content_p, md_p, hero_p, out_pdf):
    C = json.load(open(content_p, encoding="utf-8"))
    M = json.load(open(md_p, encoding="utf-8-sig"))["items"]
    H = json.load(open(hero_p, encoding="utf-8"))
    if SER:
        _add_windows(M)
    D = C["date"]
    cot = C["cotd"]
    # charts
    has_hero = bool(H.get('rows') or H.get('values') or H.get('ret') or H.get('type') in X.HERO_TYPES)
    if has_hero:
        {"guidance": hero_guidance, "drawdown": hero_drawdown, **X.HERO_TYPES}.get(H.get("type"), hero)(H)
    cards = C["p2"]["cards"]
    chart_files = []
    for ci, card in enumerate(cards):
        for k, spec in enumerate(card["charts"]):
            fn = f"c{ci}_{k}.svg"
            t = spec["type"]
            if t in X.HTML_EXTRAS:
                continue
            if t == "index_board":
                bars(M, "chgDay", fn, h=spec.get("h", 2.15), highlight=spec.get("highlight"))
            elif t == "ytd":
                bars(M, "chgYtd", fn, h=spec.get("h", 2.15), day_col=True, highlight=spec.get("highlight"))
            elif t == "rates":
                rates_curve(M, spec.get("extra"), fn, h=spec.get("h", 1.55))
            elif t == "commodities":
                commodities(M, fn)
            elif t == "week":
                bars(M, "chg5", fn, h=spec.get("h", 2.15), day_col=True, highlight=spec.get("highlight"))
            elif t == "scorecard":  # Friday weekly scorecard: week bars with a YTD column
                bars(M, "chg5", fn, h=spec.get("h", 2.15), day_col=True, highlight=spec.get("highlight"), col_key="chgYtd", col_label="YTD")
            elif t == "month":
                bars(M, "chgM", fn, h=spec.get("h", 2.15), day_col=True, highlight=spec.get("highlight"))
            elif t == "rates_trend":
                rates_trend(fn, h=spec.get("h", 1.55), days=spec.get("days", 11))
                WINDOWS[f"c{ci}_{k}"] = (spec, len(_ser("US 10Y yield", _tgt(spec.get("days", 11)))[0]))
            elif t == "multiples":
                multiples(spec["names"], fn, h=spec.get("h", 1.5))
            elif t == "rebased":
                rebased(spec["names"], fn, h=spec.get("h", 1.5), days=spec.get("days", 11))
                WINDOWS[f"c{ci}_{k}"] = (spec, len(_ser(spec["names"][0], _tgt(spec.get("days", 11)))[0]))
            elif t == "heatmap":
                heatmap(spec["names"], fn, h=spec.get("h", 1.9))
            elif t == "curve_compare":
                curve_compare(fn, h=spec.get("h", 1.55))
            elif t == "movers":
                movers(spec["rows"], fn, h=spec.get("h", 1.7), highlight=spec.get("highlight"))
            chart_files.append(fn)

    def card_html(ci, card):
        s = f'<div class="card"><h3>{html.escape(card["title"])}</h3><div class="sub">{nums(card["sub"])}</div>'
        for k, spec in enumerate(card["charts"]):
            if spec["type"] in X.HTML_EXTRAS:
                s += X.render_extra(spec)
                continue
            if spec.get("mini"):
                s += f'<div class="minihead">{html.escape(spec["mini"])}</div>'
            s += f'<img src="c{ci}_{k}.svg">'
        if card.get("tiles"):
            s += f'<div class="minihead">{html.escape(card.get("tiles_head", "Rates and data"))}</div><div class="rt">'
            for t in card["tiles"]:
                s += f'<div><div class="l">{html.escape(t["l"])}</div><div class="v">{html.escape(t["v"])}</div><div class="c">{nums(t["c"])}</div></div>'
            s += "</div>"
        return s + "</div>"

    stats = "".join(
        f'<div class="stat"><div class="v {s.get("cls","")}">{html.escape(s["v"])}</div><div class="l">{html.escape(s["l"]).replace("&lt;br&gt;", "<br>")}</div></div>'
        for s in cot["stats"])
    p1, p2 = C["p1"], C["p2"]
    fis = ""
    for p in p2.get("gcc_panels", []):
        inner = f'<div class="l">{html.escape(p["label"])}</div><div class="v">{html.escape(p["value"])}<small> {html.escape(p.get("small",""))}</small></div>'
        if p.get("bar") is not None:
            inner += f'<div class="bar"><i style="width:{p["bar"]}%"></i></div>'
        if p.get("bars"):
            # a two-column grid per panel: the label column is as wide as the longest label, the bar track takes the
            # rest and is the same for every row, so each bar's length is w% of one track and matches its number
            if any(b.get("neg") for b in p["bars"]):
                # a value below zero grows left from a center line, in red, so a fall never reads as a rise
                trk = lambda b: (f'<div class="trk dv"><div class="h l">' + (f'<div class="b" style="width:{b["w"]}%;background:{b.get("c", DN)}"></div>' if b.get("neg") else "") +
                                 f'</div><div class="h r">' + ("" if b.get("neg") else f'<div class="b" style="width:{b["w"]}%;background:{b.get("c", NAVY)}"></div>') + '</div></div>')
            else:
                trk = lambda b: f'<div class="trk"><div class="b" style="width:{b["w"]}%;background:{b.get("c", NAVY)}"></div></div>'
            inner += '<div class="bars2">' + "".join(
                trk(b) + f'<span class="n" style="font-size:6.8pt;white-space:nowrap">{html.escape(b["t"])}</span>' for b in p["bars"]) + '</div>'
        inner += f'<div class="fcap">{nums(p["caption"])}</div>'
        fis += f'<div class="fbox">{inner}</div>'
    fis = f'<div class="fis">{fis}</div>' if fis else ""
    w = C["watch"]
    # Compliance, 27.10.2026: the CMA licence next to Audi Capital's name at the bottom of every page
    foot2 = FOOT_ADDR
    # hooks (optional fields): a three-line "today in 3" strip under the masthead, and a Gulf "what it means" line
    top3 = ""
    if C.get("top3"):
        # three equal columns under one kicker: number and headline share a baseline, the line below runs the full
        # column width, so the three stories line up however long each one is
        top3 = '<div class="top3"><div class="t3k">Today in 3</div><div class="t3g">' + "".join(
            f'<div class="t3"><div class="t3h"><span class="t3n">{i:02d}</span><b>{html.escape(x["k"])}</b></div>{nums(x["t"])}</div>'
            for i, x in enumerate(C["top3"], 1)) + '</div></div>'
    means = ""  # the "For Gulf investors" line was retired by Ralph on 23.10.2026
    chartblock = (f'<div class="chartcap"><b>{html.escape(cot["chart_title"])}</b><span>{html.escape(cot["chart_method"])}</span></div><img class="ch" src="hero.svg">' if has_hero else '')
    page1 = f'''<div class="page">
 <div class="mast"><div><img class="wm" src="wordmark.png"><div class="kicker">Daily Brief</div><div class="date">{D}</div></div><img class="circ" src="circles.png"></div>
 {top3}
 <div class="hero">
  <div class="herogrid"><div class="herotext"><div class="kicker">Company of the Day</div>
  <h1>{html.escape(cot["name"])} <small>{html.escape(cot["ticker"])}</small></h1><div class="hbody">{nums(cot["body"])}</div></div><div class="stats">{stats}</div></div>
  {chartblock}
  <div class="catalyst"><b>Next catalyst</b>{nums(cot["catalyst"])}</div>{means}</div>
 <div class="cols"><div class="col">{"".join(sec(t, i) for t, i in p1["left"])}{X.render_extras(p1.get("extras_left"))}</div><div class="col">{"".join(sec(t, i) for t, i in p1["right"])}{X.render_extras(p1.get("extras_right"))}</div></div>
 <div class="foot"><div><b>Audi Capital</b> | Licensed by the CMA (License No. 06017-37) | Daily Brief | {D}</div><div class="pg">01 / 03</div></div></div>'''
    left2 = "".join(sec(t, i, fis if t.startswith("GCC") else "") for t, i in p2["left"]) + X.render_extras(p2.get("extras_left"))
    right2 = "".join(sec(t, i) for t, i in p2["right"]) + X.render_extras(p2.get("extras_right"))
    page2 = f'''<div class="page">
 <div class="runhead"><img src="wordmark.png"><div class="r">Daily Brief | {D} | Charts &amp; regions</div></div>
 <div class="cols" style="margin-top:0"><div class="col">{card_html(0, cards[0])}</div><div class="col">{card_html(1, cards[1])}</div></div>
 <div class="cols"><div class="col">{left2}</div><div class="col">{right2}</div></div>
 <div class="watch"><div class="k">{html.escape(w.get("label", "Watch today"))}<span class="clock">{html.escape(w["clock"])}</span></div><p>{nums(w["text"])}</p></div>
 <div class="foot">{foot2}<div class="pg">02 / 03</div></div></div>'''
    page3 = page3_html(D, foot2)
    doc = f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{X.EXTRA_CSS}{P3_CSS}</style></head><body>{page1}{page2}{page3}</body></html>'
    open("brief_v2.html", "w", encoding="utf-8").write(doc)
    from weasyprint import HTML
    rendered = HTML(filename="brief_v2.html", base_url=os.getcwd()).render()
    rendered.write_pdf(out_pdf)
    print("wrote", out_pdf)
    if DECLUTTER["moved"] or DECLUTTER["backed"]:
        print(f"labels cleared off chart lines: {DECLUTTER['moved']} moved, {DECLUTTER['backed']} given a white backing")
    lay = measure(rendered, out_pdf)
    lay["windows"] = {k: {"type": s["type"], "mini": s.get("mini", ""), "sessions": n} for k, (s, n) in WINDOWS.items()}
    json.dump(lay, open("layout.json", "w"))
    if lay.get("p2"):
        q = lay["p2"]
        print(f"layout: page 2 card A {q['cardA']:.0f} pt, card B {q['cardB']:.0f} pt; region columns end {q['left_gap']:.0f} / {q['right_gap']:.0f} pt above the question band")
    X.check_pdf_overlap(out_pdf, {t.lower().strip('.,;:') for t in (C['watch']['text'] + ' ' + C['watch'].get('label', 'Watch today') + ' ' + C['watch']['clock']).split()})
    if X.WARN:
        print("OVERLAP WARNINGS:", len(X.WARN))
        for w_ in X.WARN: print("  -", w_)
        sys.exit(4)
    print("overlap check: clean")


HERE_DIR = os.path.dirname(os.path.abspath(__file__))
P3_CSS = (f"@font-face{{font-family:AR;src:url('file://{HERE_DIR}/NotoSansArabic-Regular.ttf');font-weight:400}}"
          f"@font-face{{font-family:AR;src:url('file://{HERE_DIR}/NotoSansArabic-Bold.ttf');font-weight:700}}"
          ".p3{position:absolute;left:12mm;right:12mm;top:26mm;bottom:20mm;display:flex;flex-direction:column;justify-content:center}"
          ".p3k{font-size:8pt;letter-spacing:.18em;text-transform:uppercase;color:var(--steel);font-weight:700;margin-bottom:5mm}"
          ".p3g{display:grid;grid-template-columns:1fr 1fr;column-gap:10mm;border-top:2.2pt solid var(--navy);padding-top:9mm}"
          ".p3c{display:flex;flex-direction:column}.p3c h3{font-size:14pt;font-weight:800;margin:0 0 6mm 0;color:var(--navy)}"
          ".p3c p{font-size:9.8pt;line-height:1.62;margin:0 0 4.2mm 0;color:#2B3A55}"
          ".p3c p.cr{margin-top:auto;margin-bottom:0;padding-top:3.5mm;border-top:0.8pt solid var(--line);color:var(--mute);font-size:8.4pt}"
          ".p3c.ar{direction:rtl;text-align:right;font-family:AR,I;border-left:0.8pt solid var(--line);padding-left:10mm}"
          ".p3c.ar h3{font-size:15pt;font-weight:700}.p3c.ar p{font-size:10.4pt;line-height:1.72}.p3c.ar p.cr{font-size:9pt}")


FOOT_ADDR = ('<div class="addr"><div><b>Audi Capital</b> | Licensed by the CMA (License No. 06017-37)</div><div>Centria Building - 3rd Floor | '
             'Tahlia Street - Olaya, Riyadh 12241-6055, Kingdom of Saudi Arabia | <a href="https://audicapital.com" '
             'style="color:#fff;text-decoration:none;font-weight:700">audicapital.com</a></div></div>')


def page3_html(D, foot2):
    """The disclaimer page: Compliance's text only, English and Arabic side by side, in the brief's frame."""
    def col(t, cls):
        h, ps = t
        body = "".join(f'<p{" class=cr" if x.startswith(chr(169)) else ""}>{html.escape(x)}</p>' for x in ps)
        return f'<div class="p3c {cls}"><h3>{html.escape(h)}</h3>{body}</div>'
    return (f'<div class="page">\n <div class="runhead"><img src="wordmark.png"><div class="r">Daily Brief | {D} | Important notice</div></div>\n'
            f' <div class="p3"><div class="p3g">{col(DISCLAIMER_EN, "en")}{col(DISCLAIMER_AR, "ar")}</div></div>\n'
            f' <div class="foot">{foot2}<div class="pg">03 / 03</div></div></div>')


def measure(doc, pdf_name):
    """Heights of the page-2 cards and how far each region column ends above the question band, in pt."""
    def cls(b):
        el = getattr(b, "element", None)
        return (el.get("class") or "").split() if el is not None and getattr(b, "element_tag", None) else []
    def walk(b):
        yield b
        for c in getattr(b, "children", []) or []:
            yield from walk(c)
    out = {"pdf": os.path.basename(pdf_name)}
    b1 = list(walk(doc.pages[0]._page_box))
    body = next((b for b in b1 if "hbody" in cls(b)), None)
    sts = next((b for b in b1 if "stats" in cls(b)), None)
    if body is not None and sts is not None:
        lines = [c for c in walk(body) if type(c).__name__ == "LineBox"]
        text_end = max((c.position_y + c.height for c in lines), default=body.position_y + body.height)
        kids = [c for c in sts.children if "stat" in cls(c)]
        need = sum(c.margin_height() for c in kids) if kids else 0   # boxes at their natural height
        out["p1"] = {"cotd_text_short_by": round((sts.position_y + need - text_end) * .75, 1)}
    if len(doc.pages) < 2:
        return out
    boxes = list(walk(doc.pages[1]._page_box))
    cards = [b for b in boxes if "card" in cls(b)]
    watch = next((b for b in boxes if "watch" in cls(b)), None)
    rows = [b for b in boxes if "cols" in cls(b)]
    if len(cards) < 2 or watch is None or len(rows) < 2:
        return out
    # a grid column stretches to the row height, so its content ends where its last child block ends
    bottom = lambda col: max((c.position_y + c.margin_height() for c in col.children), default=col.position_y)
    cols = [c for c in rows[1].children if "col" in cls(c)]
    pt = .75  # CSS px to pt
    out["p2"] = {"cardA": cards[0].border_height() * pt, "cardB": cards[1].border_height() * pt,
                 "left_gap": (watch.position_y - bottom(cols[0])) * pt, "right_gap": (watch.position_y - bottom(cols[1])) * pt}
    return out





def fallback_pdf(txt_p, date, out_pdf):
    """The last line of defence (Ralph, 26.10.2026: "everything should be clockwork"): when no designed layout builds,
    the text brief is set in the house style, with no charts and no market data, followed by the disclaimer page.
    It depends only on the text and the fonts, so it always builds."""
    from weasyprint import HTML
    lines = [l.rstrip() for l in open(txt_p, encoding="utf-8").read().splitlines()]
    body, lst = [], False
    for l in lines:
        if not l.strip():
            continue
        if l.startswith("- "):
            if not lst: body.append("<ul class='fb'>"); lst = True
            body.append(f"<li>{nums(l[2:])}</li>"); continue
        if lst: body.append("</ul>"); lst = False
        head = re.match(r"^([A-Z][A-Z0-9 &,/-]{3,})(?: - (.*))?$", l) or re.match(r"^([A-Z][A-Z0-9 ,&/-]{3,}):\s*(.*)$", l)
        if head and head.group(1).strip() == head.group(1).strip().upper():
            body.append(f"<h2>{html.escape(head.group(1).strip())}</h2>" + (f"<p><b>{nums(head.group(2))}</b></p>" if head.group(2) else ""))
        else:
            body.append(f"<p>{nums(l)}</p>")
    if lst: body.append("</ul>")
    foot = f"Audi Capital | Licensed by the CMA (License No. 06017-37) | Daily Brief | {date}"
    css = (CSS + P3_CSS + "@page fb{size:A4;margin:16mm 14mm 18mm 14mm;"
           f"@bottom-left{{content:'{foot}';font-family:I;font-size:7pt;color:#5E6C82}}"
           "@bottom-right{content:counter(page) ' / ' counter(pages);font-family:I;font-size:7pt;color:#5E6C82}}"
           ".fbw{page:fb;column-count:2;column-gap:8mm}"
           ".fbw h2{break-after:avoid;margin-top:3mm}.fbw p,.fbw li{margin:0 0 1.6mm 0}ul.fb{padding-left:4mm;margin:0 0 2mm 0}"
           ".fbm{page:fb;display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2.2pt solid var(--navy);"
           "padding-bottom:3mm;margin-bottom:5mm}.fbm img{height:9mm}.p3pg{page-break-before:always}")
    doc = (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head><body>'
           f'<div class="fbm"><img src="wordmark.png"><div class="kicker">Daily Brief | {html.escape(date)}</div></div>'
           f'<div class="fbw">{"".join(body)}</div><div class="p3pg">{page3_html(date, FOOT_ADDR)}</div></body></html>')
    HTML(string=doc, base_url=os.getcwd()).write_pdf(out_pdf)
    print("wrote", out_pdf, "(fallback layout)")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--fallback"]:
        fallback_pdf(*sys.argv[2:5])
    else:
        main(*sys.argv[1:5])
