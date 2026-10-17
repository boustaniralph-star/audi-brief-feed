#!/usr/bin/env python3
"""Audi Capital Daily Brief - extras for build_brief_v2.py (added 10 Oct 2026, approved by Ralph).

New hero chart types (hero_data.json "type"):
  valuewiped  value gained/lost across the company and its peers + ripple chart
  intraday    the session in half-hours (gap, drift, volume) + volume vs 2-week average
  range       price vs 52-week range, analyst targets/ratings, EPS surprise record
New page-1 extras (content_v2.json p1.extras_right / p1.extras_left): loop, gulf, levels, alumni, weekmap
Overlap guards: install_overlap_guard() checks every matplotlib chart for overlapping or clipped text
before it is saved; check_pdf_overlap(pdf) checks the final PDF for overlapping words.
Nothing here estimates data: every number comes from the JSON the routine writes.
"""
import html, itertools, re, subprocess, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.text import Text

NAVY, STEEL, SILVER = "#1B2A4A", "#4A6FA5", "#8A9BB0"
UP, DN, GRID, MUTE, MONO = "#2F8F6B", "#C0453A", "#E3E8EF", "#6B7A90", "IBM Plex Mono"
WARN = []


# ------------------------------------------------------------------ overlap guards
def _boxes(fig):
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    out = []
    for t in fig.findobj(Text):
        s = t.get_text()
        if not s or not s.strip() or not t.get_visible():
            continue
        try:
            bb = Text.get_window_extent(t, r)
        except Exception:
            continue
        if bb.width < 1 or bb.height < 1:
            continue
        out.append((s.replace("\n", " ")[:28], bb))
    return fig.bbox, out


def check_figure(fig, name):
    fb, items = _boxes(fig)
    bad = 0
    for (a, ba), (b, bb) in itertools.combinations(items, 2):
        w = min(ba.x1, bb.x1) - max(ba.x0, bb.x0)
        h = min(ba.y1, bb.y1) - max(ba.y0, bb.y0)
        if w > 1.5 and h > 1.5:
            WARN.append(f"{name}: text overlap '{a}' / '{b}'")
            bad += 1
    import numpy as np
    from matplotlib.lines import Line2D
    r = fig.canvas.get_renderer()
    for ax in fig.axes:
        for ln in ax.findobj(Line2D):
            if ln.axes is not ax:
                continue
            xd, yd = ln.get_xdata(), ln.get_ydata()
            if len(xd) < 3 or not ln.get_visible():
                continue
            try:
                pts = ax.transData.transform(np.column_stack([np.asarray(xd, float), np.asarray(yd, float)]))
            except Exception:
                continue
            samp = []
            for p0, p1 in zip(pts[:-1], pts[1:]):
                for t in np.linspace(0, 1, 24):
                    samp.append(p0 + (p1 - p0) * t)
            samp = np.array(samp)
            for t in ax.texts:
                if not t.get_text().strip():
                    continue
                bb = Text.get_window_extent(t, r)
                inside = (samp[:, 0] > bb.x0 + 1) & (samp[:, 0] < bb.x1 - 1) & (samp[:, 1] > bb.y0 + 1) & (samp[:, 1] < bb.y1 - 1)
                if inside.any():
                    WARN.append(f"{name}: text sits on a line '{t.get_text()[:28]}'")
                    bad += 1
    for s, bb in items:
        if bb.x1 < fb.x0 or bb.x0 > fb.x1 or bb.y1 < fb.y0 or bb.y0 > fb.y1:
            continue  # fully outside the canvas = a hidden tick label, not visible text
        if bb.x0 < fb.x0 - 1 or bb.x1 > fb.x1 + 1 or bb.y0 < fb.y0 - 1 or bb.y1 > fb.y1 + 1:
            WARN.append(f"{name}: text clipped at the edge '{s}'")
            bad += 1
    return bad


def install_overlap_guard():
    orig = plt.savefig

    def guarded(fname, *a, **k):
        try:
            check_figure(plt.gcf(), str(fname))
        except Exception as e:  # never block the build on the checker itself
            WARN.append(f"{fname}: checker error {e}")
        return orig(fname, *a, **k)
    plt.savefig = guarded


def check_pdf_overlap(pdf, band_words=None):
    """Words whose boxes overlap in the final PDF (text hidden under the Watch band, collisions)."""
    try:
        x = subprocess.run(["pdftotext", "-bbox", pdf, "-"], capture_output=True, text=True, timeout=60).stdout
    except Exception as e:
        WARN.append(f"pdf check skipped: {e}")
        return
    n = len(x.split("<page ")) - 1
    if n != 2:
        WARN.append(f"PDF has {n} pages, must be exactly 2 (overflow: trim wording or chart heights)")
    pages = x.split("<page ")[1:]
    for pi, pg in enumerate(pages, 1):
        words = [(float(a), float(b), float(c), float(d), html.unescape(w)) for a, b, c, d, w in
                 re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', pg)]
        if band_words and pi == 2:
            keys = {w[4].lower().strip(".,;:") for w in words if w[4].lower().strip(".,;:") in band_words}
            tops = [w[1] for w in words if w[4].upper() == "WATCH"]
            if tops:
                top = min(tops) - 10
                bottom = max(w[3] for w in words if w[4].lower().strip(".,;:") in band_words and w[1] >= top) + 4
                for w_ in words:
                    if w_[1] >= top and w_[3] <= bottom and w_[4].lower().strip(".,;:") not in band_words:
                        WARN.append(f"PDF page 2: text hidden under the Watch band: '{w_[4]}' near y={w_[1]:.0f}")
        for (a, b) in itertools.combinations(words, 2):
            w = min(a[2], b[2]) - max(a[0], b[0])
            h = min(a[3], b[3]) - max(a[1], b[1])
            if w > 1.2 and h > 1.8:
                WARN.append(f"PDF page {pi}: words overlap '{a[4]}' / '{b[4]}' near y={a[1]:.0f}")


# ------------------------------------------------------------------ hero: value wiped + ripple
def _hbars(ax, names, vals, title, hi=None, fmt="{:+.1f}", unit=""):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ys = list(range(len(order)))
    cols = []
    for i in order:
        cols.append(NAVY if (hi is not None and i == hi) else (UP if vals[i] >= 0 else DN))
    ax.barh(ys, [vals[i] for i in order], color=cols, height=.6, zorder=3)
    ax.set_yticks(ys)
    ax.set_yticklabels([names[i] for i in order], fontsize=7.6, color=NAVY)
    vm = max(abs(v) for v in vals) or 1
    for y, i in zip(ys, order):
        v = vals[i]
        ax.text(v + (vm * .04 if v >= 0 else -vm * .04), y, fmt.format(v) + unit, va="center",
                ha="left" if v >= 0 else "right", fontsize=7.4, family=MONO, color=UP if v >= 0 else DN)
    lo = min(0, min(vals)); hi_ = max(0, max(vals))
    ax.set_xlim(lo * 1.55 - (vm * .15 if lo < 0 else 0), hi_ * 1.55 + (vm * .15 if hi_ > 0 else 0))
    ax.set_xticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)
    ax.axvline(0, color=SILVER, lw=.6)
    ax.set_title(title, fontsize=8, color=NAVY, loc="left", fontweight="bold")


def hero_valuewiped(h, out="hero.svg"):
    fig, axs = plt.subplots(1, 2, figsize=(7.3, h.get("height", 1.8)), dpi=200,
                            gridspec_kw={"width_ratios": [1, 1.15]})
    w, r = h["wiped"], h["ripple"]
    _hbars(axs[0], w["names"], w["usd_bn"], w.get("title", "Market value change, USD bn"), hi=w.get("highlight", 0), fmt="{:+.1f}", unit=" bn")
    _hbars(axs[1], r["names"], r["pct"], r.get("title", "Who else moved, % on the day"), hi=r.get("highlight", 0), fmt="{:+.1f}", unit="%")
    plt.tight_layout(pad=.3, w_pad=1.6)
    plt.savefig(out, transparent=True); plt.close()


# ------------------------------------------------------------------ hero: the session in half-hours
def hero_intraday(h, out="hero.svg"):
    pts = h["points"]               # [{"l": "Prior", "v": 0.0, "vol": None}, {"l": "16:30", "v": -9.2}, ...]
    vx = h.get("volx")              # {"title":..., "names":[...], "mult":[...]} optional
    ncols = 2 if vx else 1
    fig = plt.figure(figsize=(7.3, h.get("height", 1.9)), dpi=200)
    gs = fig.add_gridspec(2, ncols, height_ratios=[3, 1], width_ratios=[2.3, 1] if vx else [1], hspace=.12, wspace=.28)
    a1 = fig.add_subplot(gs[0, 0]); a2 = fig.add_subplot(gs[1, 0], sharex=a1)
    xs = list(range(len(pts))); ys = [p["v"] for p in pts]
    a1.plot(xs[:2], ys[:2], color=SILVER, lw=1.2, ls=(0, (3, 2)))
    a1.plot(xs[1:], ys[1:], color=NAVY, lw=2)
    a1.scatter([1, xs[-1]], [ys[1], ys[-1]], s=16, color=DN if ys[-1] < 0 else UP, zorder=5)
    a1.axhline(0, color=SILVER, lw=.6, ls=(0, (2, 2)))
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * .35 + .5
    a1.set_ylim(lo - pad, hi + pad * .8)
    a1.yaxis.grid(True, color=GRID, lw=.6); a1.set_axisbelow(True)
    for s in ("left", "bottom"):
        a1.spines[s].set_visible(False)
    a1.tick_params(length=0, labelsize=7)
    plt.setp(a1.get_xticklabels(), visible=False)
    from matplotlib.ticker import FuncFormatter
    a1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    for t in a1.get_yticklabels():
        t.set_family(MONO)
    for an in h.get("notes", []):
        i = an["i"]
        dx = an.get("dx", 14 if i < len(xs) / 2 else -70)
        dy = an.get("dy", 12 if ys[i] <= (lo + hi) / 2 else -12)
        a1.annotate(an["text"], (xs[i], ys[i]), xytext=(dx, dy), textcoords="offset points",
                    fontsize=7.4, color=an.get("color", NAVY), fontweight="bold" if an.get("bold") else "normal",
                    arrowprops=dict(arrowstyle="-", color=SILVER, lw=.6))
    a1.set_title(h.get("title", "Session in half-hours, % vs prior close"), fontsize=8, color=NAVY, loc="left", fontweight="bold")
    vols = [(i, p["vol"]) for i, p in enumerate(pts) if p.get("vol") is not None]
    a2.bar([i for i, _ in vols], [v for _, v in vols], color=STEEL, width=.7)
    a2.set_yticks([])
    for s in ("left", "bottom", "top", "right"):
        a2.spines[s].set_visible(False)
    step = max(1, len(pts) // 7)
    a2.set_xticks(xs[::step]); a2.set_xticklabels([pts[i]["l"] for i in xs[::step]], fontsize=6.6, family=MONO)
    a2.tick_params(length=0)
    if vx:
        bx = fig.add_subplot(gs[:, 1])
        order = sorted(range(len(vx["names"])), key=lambda i: vx["mult"][i])
        yy = list(range(len(order)))
        bx.barh(yy, [vx["mult"][i] for i in order], color=[NAVY if i == vx.get("highlight", 0) else STEEL for i in order], height=.55)
        bx.set_yticks(yy); bx.set_yticklabels([vx["names"][i] for i in order], fontsize=6.8, color=NAVY)
        m = max(vx["mult"])
        for y, i in zip(yy, order):
            bx.text(vx["mult"][i] + m * .04, y, f'{vx["mult"][i]:.1f}x', va="center", fontsize=6.8, family=MONO, color=NAVY)
        bx.set_xlim(0, m * 1.4); bx.set_xticks([])
        for s in bx.spines.values():
            s.set_visible(False)
        bx.tick_params(length=0)
        bx.set_title(vx.get("title", "Volume vs 2-week average"), fontsize=8, color=NAVY, loc="left", fontweight="bold")
    plt.subplots_adjust(left=.07, right=.98, top=.9, bottom=.12)
    plt.savefig(out, transparent=True); plt.close()


# ------------------------------------------------------------------ hero: range, analysts, earnings record
def hero_range(h, out="hero.svg"):
    panels = []
    if h.get("low") is not None:
        panels.append("range")
    if h.get("ratings"):
        panels.append("ratings")
    if h.get("eps"):
        panels.append("eps")
    fig, axs = plt.subplots(1, len(panels), figsize=(7.3, h.get("height", 1.7)), dpi=200,
                            gridspec_kw={"width_ratios": [1.5 if p == "range" else 1 for p in panels]})
    axs = [axs] if len(panels) == 1 else list(axs)
    for ax, p in zip(axs, panels):
        if p == "range":
            lo, hi, px = h["low"], h["high"], h["close"]
            span = hi - lo
            ax.hlines(1, lo, hi, color=GRID, lw=8, zorder=1)
            ax.scatter([px], [1], s=46, color=DN if px < (lo + hi) / 2 else UP, zorder=5)
            ha = "left" if px < lo + span * .3 else ("right" if px > hi - span * .3 else "center")
            ax.text(px, 1.34, h.get("close_label", f"Close {px:,.2f}"), ha=ha, fontsize=7.4, color=NAVY, fontweight="bold")
            ax.text(lo, .62, f"Low {lo:,.2f}", ha="left", fontsize=7, family=MONO, color=MUTE)
            ax.text(hi, .62, f"High {hi:,.2f}", ha="right", fontsize=7, family=MONO, color=MUTE)
            t = h.get("targets")
            if t:
                ax.hlines(0, t["low"], t["high"], color=STEEL, lw=5, zorder=1)
                ax.scatter([t["mean"]], [0], s=26, facecolor="white", edgecolor=NAVY, zorder=5)
                ax.text(t["low"], -.38, f'Target low {t["low"]:,.0f}', ha="left", fontsize=6.8, family=MONO, color=STEEL)
                ax.text(t["high"], -.38, f'high {t["high"]:,.0f}', ha="right", fontsize=6.8, family=MONO, color=STEEL)
                ax.text(t["mean"], .3, f'mean {t["mean"]:,.0f}', ha="center", fontsize=6.8, family=MONO, color=NAVY)
            xs_all = [lo, hi] + ([h["targets"]["low"], h["targets"]["high"]] if t else [])
            ax.set_xlim(min(xs_all) - span * .06, max(xs_all) + span * .06)
            ax.set_ylim(-.75, 1.9); ax.axis("off")
            ax.set_title(h.get("range_title", "Price vs 52-week range"), fontsize=8, color=NAVY, loc="left", fontweight="bold")
        elif p == "ratings":
            r = h["ratings"]; tot = r["buy"] + r["hold"] + r["sell"]
            left = 0
            for k, c in (("buy", UP), ("hold", SILVER), ("sell", DN)):
                n = r[k]
                if n:
                    ax.barh([0], [n], left=[left], color=c, height=.5)
                    ax.text(left + n / 2, 0, str(n), ha="center", va="center", color="white", fontsize=8, fontweight="bold")
                    ax.text(left + n / 2, -.5, k.capitalize(), ha="center", va="top", fontsize=6.8, color=MUTE)
                left += n
            ax.set_xlim(0, tot); ax.set_ylim(-1.1, .9); ax.axis("off")
            ax.set_title("Analyst ratings", fontsize=8, color=NAVY, loc="left", fontweight="bold")
            if h.get("ratings_note"):
                ax.text(0, -.95, h["ratings_note"], fontsize=6.6, color=MUTE, ha="left")
        else:
            e = h["eps"]; v = e["surprise"]
            ax.bar(range(len(v)), v, color=[UP if x >= 0 else DN for x in v], width=.62)
            top = max(max(v), 1)
            for i, x in enumerate(v):
                ax.text(i, x + top * .04 if x >= 0 else x - top * .04, f"{x:+.1f}%", ha="center", va="bottom" if x >= 0 else "top", fontsize=6.4, family=MONO, color=UP if x >= 0 else DN)
            ax.set_xticks(range(len(v))); ax.set_xticklabels(e["labels"], fontsize=6.2, rotation=0)
            ax.set_yticks([]); ax.set_ylim(min(0, min(v)) * 1.5, top * 1.32)
            for s in ("left", "top", "right"):
                ax.spines[s].set_visible(False)
            ax.tick_params(length=0)
            ax.set_title(e.get("title", "EPS vs estimate"), fontsize=8, color=NAVY, loc="left", fontweight="bold")
    plt.tight_layout(pad=.3, w_pad=1.4)
    plt.savefig(out, transparent=True); plt.close()


HTML_EXTRAS = ("loop", "gulf", "levels", "alumni", "weekmap")
HERO_TYPES = {"valuewiped": hero_valuewiped, "intraday": hero_intraday, "range": hero_range}


# ------------------------------------------------------------------ page-1 extras (pure HTML, so nothing can overlap)
EXTRA_CSS = """
.xbox{background:#F2F5FA;border-radius:4pt;padding:2.4mm 3mm;margin:0 0 3mm 0;break-inside:avoid}
.xbox .xt{font-size:6.6pt;letter-spacing:.12em;text-transform:uppercase;color:#6B7A90;font-weight:700;margin-bottom:1.2mm}
.xbox .xs{font-size:6.4pt;color:#6B7A90;margin-top:1mm}
.callout{border-left:2.4pt solid #4A6FA5;background:#F2F5FA;padding:1.4mm 2.6mm;margin:0 0 2mm 0;font-size:7.5pt;line-height:1.32;break-inside:avoid}
.callout b.k{font-size:6.6pt;letter-spacing:.12em;text-transform:uppercase;color:#4A6FA5;display:block;margin-bottom:.5mm}
table.lv{width:100%;border-collapse:collapse;font-size:7.4pt}
table.lv td{padding:.9mm 1mm .9mm 0;border-bottom:.4pt solid #E3E8EF;vertical-align:baseline}
table.lv tr:last-child td{border-bottom:none}
table.lv td.n{font-weight:700;color:#1B2A4A;white-space:nowrap}
table.lv td.v{font-family:'IBM Plex Mono';color:#1B2A4A;white-space:nowrap}
table.lv td.l{color:#6B7A90;font-size:6.9pt}
table.lv td.g{font-family:'IBM Plex Mono';text-align:right;white-space:nowrap;font-weight:600}
.up{color:#2F8F6B}.dn{color:#C0453A}
.al{display:flex;align-items:center;font-size:7.4pt;padding:.7mm 0}
.al .a{width:24%;font-weight:700;color:#1B2A4A;line-height:1.05}
.al .a small{display:block;font-weight:400;color:#6B7A90;font-size:5.8pt}
.al .neg,.al .pos{width:29%;height:3.2mm;position:relative}
.al .neg i{position:absolute;right:0;top:0;bottom:0;background:#C0453A;border-radius:1pt 0 0 1pt}
.al .pos i{position:absolute;left:0;top:0;bottom:0;background:#2F8F6B;border-radius:0 1pt 1pt 0}
.al .neg{border-right:.6pt solid #8A9BB0}
.al .val{width:18%;text-align:right;font-family:'IBM Plex Mono';font-weight:600}
table.wk{width:100%;border-collapse:collapse;font-size:7.3pt}
table.wk td{padding:.9mm 1.4mm .9mm 0;border-bottom:.4pt solid #E3E8EF;vertical-align:top}
table.wk tr:last-child td{border-bottom:none}
table.wk td.d{font-weight:700;color:#1B2A4A;white-space:nowrap;width:15%}
table.wk tr.hl td.d{color:#4A6FA5}
table.wk tr.hl td{background:#E8EEF8}
"""


def _cls(txt):
    t = str(txt).strip()
    return "up" if t.startswith("+") else ("dn" if t.startswith("-") else "")


def render_extra(x):
    t = x["type"]
    e = html.escape
    if t in ("loop", "gulf"):
        k = x.get("label") or ("Closing the loop" if t == "loop" else "Gulf angle")
        return f'<div class="callout"><b class="k">{e(k)}</b>{e(x["text"])}</div>'
    if t == "levels":
        rows = "".join(f'<tr><td class="n">{e(r["name"])}</td><td class="v">{e(r["value"])}</td><td class="l">{e(r["level"])}</td>'
                       f'<td class="g {_cls(r["gap"])}">{e(r["gap"])}</td></tr>' for r in x["rows"])
        return f'<div class="xbox"><div class="xt">{e(x.get("title", "Levels ladder"))}</div><table class="lv">{rows}</table>' + \
               (f'<div class="xs">{e(x["note"])}</div>' if x.get("note") else "") + '</div>'
    if t == "alumni":
        m = max(abs(r["ret"]) for r in x["rows"]) or 1
        out = ""
        for r in x["rows"]:
            v = r["ret"]; wpct = abs(v) / m * 100
            neg = f'<i style="width:{wpct:.0f}%"></i>' if v < 0 else ""
            pos = f'<i style="width:{wpct:.0f}%"></i>' if v >= 0 else ""
            out += (f'<div class="al"><div class="a">{e(r["name"])}<small>{e(r["date"])}</small></div>'
                    f'<div class="neg">{neg}</div><div class="pos">{pos}</div>'
                    f'<div class="val {"up" if v >= 0 else "dn"}">{v:+.1f}%</div></div>')
        return f'<div class="xbox"><div class="xt">{e(x.get("title", "Where are they now?"))}</div>{out}' + \
               (f'<div class="xs">{e(x["note"])}</div>' if x.get("note") else "") + '</div>'
    if t == "weekmap":
        rows = "".join(f'<tr class="{"hl" if d.get("hi") else ""}"><td class="d">{e(d["day"])}</td><td>{e(d["text"])}</td></tr>' for d in x["days"])
        return f'<div class="xbox"><div class="xt">{e(x.get("title", "Week ahead"))}</div><table class="wk">{rows}</table>' + \
               (f'<div class="xs">{e(x["note"])}</div>' if x.get("note") else "") + '</div>'
    raise SystemExit(f"unknown extra type {t}")


def render_extras(lst):
    return "".join(render_extra(x) for x in (lst or []))


# ================================================================ round 2 (11 Oct 2026, approved by Ralph)
# New HTML extras: teaser, storyline, levelchart (Gulf pulse), sectors, topmovers
import itertools as _it, textwrap as _tw
HTML_EXTRAS = HTML_EXTRAS + ("numday", "teaser", "storyline", "levelchart", "sectors", "topmovers")
EXTRA_CSS += """
.tm{border-top:.6pt solid #1B2A4A;margin-top:1.6mm;padding-top:1.2mm;font-size:7.5pt;line-height:1.3}
.tm b{color:#4A6FA5;letter-spacing:.12em;text-transform:uppercase;font-size:6.4pt;margin-right:1.6mm}
.xbox img{width:100%;display:block}
table.mv{width:100%;border-collapse:collapse;font-size:7.3pt}
table.mv td{padding:.7mm 0;border-bottom:.4pt solid #E3E8EF}
table.mv tr:last-child td{border-bottom:none}
table.mv td.n{font-weight:700;color:#1B2A4A}
table.mv td.g{text-align:right;font-family:'IBM Plex Mono';font-weight:600}
.mvgrid{display:flex;gap:3mm}.mvgrid>div{flex:1}
.sr{display:flex;align-items:center;font-size:7pt;padding:.35mm 0}
.sr .a{width:40%;font-weight:700;color:#1B2A4A;white-space:nowrap;overflow:hidden}
.sr .neg,.sr .pos{width:17%;height:2.6mm;position:relative}
.sr .neg i{position:absolute;right:0;top:0;bottom:0;background:#C0453A;border-radius:1pt 0 0 1pt}
.sr .pos i{position:absolute;left:0;top:0;bottom:0;background:#2F8F6B;border-radius:0 1pt 1pt 0}
.sr .neg{border-right:.6pt solid #8A9BB0}
.sr .val{width:26%;text-align:right;font-family:'IBM Plex Mono';font-weight:600;font-size:6.6pt}
.mvh{font-size:6pt;letter-spacing:.1em;text-transform:uppercase;color:#6B7A90;margin-bottom:.6mm}
"""
_XN = [0]


def _dodge(ax, items, fig, gap_px=9):
    """items: [(y_data, text, color, bold)] -> place labels in the right margin without overlapping each other."""
    fig.canvas.draw()
    pts = sorted([(ax.transData.transform((0, y))[1], y, t, c, b) for y, t, c, b in items])
    placed = []
    last = -1e9
    for py, y, t, c, b in pts:
        nlines = t.count("\n") + 1
        h = gap_px * nlines + 2
        py2 = max(py, last + h)
        placed.append((py2, t, c, b)); last = py2
    # if pushed above the axes top, shift the whole stack down
    top = ax.transData.transform((0, ax.get_ylim()[1]))[1]
    over = last - top
    if over > 0:
        placed = [(p - over, t, c, b) for p, t, c, b in placed]
    return placed


def _levelchart_svg(x, fname):
    vals = x["values"]; n = len(vals)
    h = x.get("h", 1.5)
    fig, ax = plt.subplots(figsize=(3.6, h), dpi=200)
    fmt = x.get("fmt", "{:,.2f}")
    allv = list(vals) + [b["lo"] for b in x.get("bands", [])] + [b["hi"] for b in x.get("bands", [])] + [l["v"] for l in x.get("lines", [])]
    lo, hi = min(allv), max(allv); pad = (hi - lo) * 0.08 or 1
    ax.set_ylim(lo - pad, hi + pad)
    ax.set_xlim(-0.3, n - 1 + n * 0.5)          # right margin for labels
    for b in x.get("bands", []):
        ax.axhspan(b["lo"], b["hi"], xmax=(n - 0.3) / (n * 1.5 + 0.0), color=b.get("color", "#DCE6F4"), lw=0)
    for l in x.get("lines", []):
        ax.plot([-0.3, n - 0.7], [l["v"], l["v"]], color=l.get("color", DN), lw=.8, ls=(0, (4, 3)))
    ax.plot(range(n), vals, color=NAVY, lw=1.5)
    ax.scatter([n - 1], [vals[-1]], color=NAVY, s=14, zorder=3)
    items = [(vals[-1], x.get("name", "") + " " + fmt.format(vals[-1]), NAVY, True)]
    for b in x.get("bands", []):
        items.append(((b["lo"] + b["hi"]) / 2, "\n".join(_tw.wrap(b["label"], 18)), STEEL, False))
    for l in x.get("lines", []):
        items.append((l["v"], "\n".join(_tw.wrap(l["label"], 18)), l.get("color", DN), False))
    for py, t, c, b in _dodge(ax, items, fig):
        xd = ax.transData.inverted().transform((0, py))
        xr = n - 1 + max(0.6, n * 0.05)  # clear of the end marker
        ax.text(xr, ax.transData.inverted().transform((0, py))[1], t, fontsize=6.2, color=c, va="center", ha="left",
                fontweight="bold" if b else "normal", family=MONO if b else None, linespacing=1.05, clip_on=False)
    ax.set_xticks([0, n - 1]); ax.set_xticklabels([x["dates"][0], x["dates"][-1]], fontsize=6.2)
    ax.tick_params(axis="y", labelsize=6.2)
    yl = ax.get_ylim(); ax.set_yticks([t for t in ax.get_yticks() if lo + pad * .5 <= t <= hi])
    ax.set_ylim(*yl)
    for s in ("left", "bottom"): ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    plt.tight_layout(pad=.3)
    plt.savefig(fname, facecolor="white"); plt.close(fig)


def _sectors_svg(x, fname):
    items = sorted(x["rows"], key=lambda r: r["pct"])
    h = max(x.get("h", 0), 0.19 * len(items) + 0.1)
    m = max(abs(r["pct"]) for r in items) or 1
    fig, ax = plt.subplots(figsize=(3.6, h), dpi=200)
    ax.barh(range(len(items)), [r["pct"] for r in items], color=[UP if r["pct"] > 0 else DN for r in items], height=.62)
    ax.set_yticks(range(len(items))); ax.set_yticklabels([r["name"] for r in items], fontsize=6.6, color=NAVY)
    for i, r in enumerate(items):
        v = r["pct"]
        ax.text(v + (m * .03 if v >= 0 else -m * .03), i, f"{v:+.2f}%", ha="left" if v >= 0 else "right", va="center",
                fontsize=6.2, family=MONO, color=UP if v > 0 else DN)
    ax.set_xlim(-m * 1.7, m * 1.7); ax.set_xticks([])
    for s in ("left", "bottom"): ax.spines[s].set_visible(False)
    ax.tick_params(length=0); ax.axvline(0, color=SILVER, lw=.6)
    plt.tight_layout(pad=.3); plt.savefig(fname, facecolor="white"); plt.close(fig)


def _mvtable(rows):
    e = html.escape
    return '<table class="mv">' + "".join(
        f'<tr><td class="n">{e(r["name"])}</td><td class="g {"up" if r["pct"] > 0 else "dn"}">{r["pct"]:+.2f}%</td></tr>' for r in rows) + "</table>"


_render_extra_r1 = render_extra


def render_extra(x):
    t = x["type"]; e = html.escape
    _XN[0] += 1
    note = f'<div class="xs">{e(x["note"])}</div>' if x.get("note") else ""
    if t == "numday":
        return (f'<div class="nd"><div class="ndk">{e(x.get("label", "Number of the day"))}</div>'
                f'<div class="ndr"><div class="ndv">{e(x["value"])}</div><div class="ndt">{e(x["text"])}</div></div></div>')
    if t == "teaser":
        return f'<div class="tm"><b>{e(x.get("label", "Tomorrow"))}</b>{e(x["text"])}</div>'
    if t in ("storyline", "levelchart"):
        fn = f"x{_XN[0]}_{t}.svg"; _levelchart_svg(x, fn)
        return f'<div class="xbox"><div class="xt">{e(x["title"])}</div><img src="{fn}">{note}</div>'
    if t == "sectors":
        rows = sorted(x["rows"], key=lambda r: -r["pct"])
        m = max(abs(r["pct"]) for r in rows) or 1
        def side(rs):
            out = ""
            for r in rs:
                v = r["pct"]; w = abs(v) / m * 100
                neg = f'<i style="width:{w:.0f}%"></i>' if v < 0 else ""
                pos = f'<i style="width:{w:.0f}%"></i>' if v >= 0 else ""
                out += (f'<div class="sr"><div class="a">{e(r["name"])}</div><div class="neg">{neg}</div><div class="pos">{pos}</div>'
                        f'<div class="val {"up" if v >= 0 else "dn"}">{v:+.2f}%</div></div>')
            return out
        h = (len(rows) + 1) // 2
        return (f'<div class="xbox"><div class="xt">{e(x["title"])}</div><div class="mvgrid"><div>{side(rows[:h])}</div><div>{side(rows[h:])}</div></div>{note}</div>')
    if t == "topmovers":
        return (f'<div class="xbox"><div class="xt">{e(x["title"])}</div><div class="mvgrid">'
                f'<div><div class="mvh">Gainers</div>{_mvtable(x["gainers"])}</div>'
                f'<div><div class="mvh">Decliners</div>{_mvtable(x["losers"])}</div></div>{note}</div>')
    return _render_extra_r1(x)


def render_extras(lst):
    return "".join(render_extra(x) for x in (lst or []))
