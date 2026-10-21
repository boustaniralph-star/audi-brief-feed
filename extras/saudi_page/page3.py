#!/usr/bin/env python3
"""Preview of a Saudi Market Intelligence page (page 3). Standalone: not part of the brief pipeline.
Usage: python3 page3.py data.json out.pdf   (run in a folder with brief_v2.css, wordmark.png)"""
import html, json, sys
e = html.escape
D = json.load(open(sys.argv[1], encoding="utf-8"))
CSS = open("brief_v2.css", encoding="utf-8").read()

def sgn(v, d=2):
    return f"{v:+.{d}f}%"

def heat(v, span=3.0):
    """diverging fill: green up, red down, neutral grey near zero; intensity by size, capped at span"""
    a = min(abs(v) / span, 1.0)
    if abs(v) < 0.05: return "#EEF1F5"
    base = (47, 143, 107) if v > 0 else (192, 69, 58)
    mix = lambda c: int(255 + (c - 255) * (0.18 + 0.67 * a))
    return "#%02X%02X%02X" % tuple(mix(c) for c in base)

def ink(v, span=3.0):
    return "#fff" if abs(v) / span > 0.62 else "#1B2A4A"

P = D["pulse"]; B = P["breadth"]
tot = B["up"] + B["down"] + B["flat"]
bar = (f'<div class="brbar"><i class="u" style="width:{B["up"]/tot*100:.1f}%"></i><i class="f" style="width:{B["flat"]/tot*100:.1f}%"></i>'
       f'<i class="d" style="width:{B["down"]/tot*100:.1f}%"></i></div>')
tiles = f'''<div class="p3tiles">
 <div><div class="l">TASI</div><div class="v">{P["tasi"]["c"]:,.2f}</div><div class="c"><span class="{'up' if P['tasi']['d']>=0 else 'dn'}">{sgn(P["tasi"]["d"])}</span> day · <span class="{'up' if P['tasi']['y']>=0 else 'dn'}">{sgn(P["tasi"]["y"])}</span> YTD</div></div>
 <div><div class="l">Breadth</div><div class="v"><span class="up">{B["up"]}</span> / <span class="dn">{B["down"]}</span></div>{bar}<div class="c">up / down, {B["flat"]} unchanged, of {tot}</div></div>
 <div><div class="l">52-week extremes</div><div class="v"><span class="up">{B["hi"]}</span> / <span class="dn">{B["lo"]}</span></div><div class="c">new highs / new lows</div></div>
 <div><div class="l">Turnover</div><div class="v">SAR {P["turnover"]["v"]/1000:.2f} bn</div><div class="c">{sgn(P["turnover"]["vs20"],0)} vs 20-day average</div></div>
</div>'''

rows = "".join(
    f'<tr><td class="sn">{e(s["name"])}</td>' + "".join(
        f'<td class="hm" style="background:{heat(s[k], sp)};color:{ink(s[k], sp)}">{s[k]:+.1f}</td>' for k, sp in (("d", 2.5), ("w", 5), ("y", 15))) + "</tr>"
    for s in P["sectors"])
heatmap = f'''<div class="p3box"><div class="xt">Sectors, % change</div>
<table class="hmt"><tr><th></th><th>Day</th><th>Week</th><th>YTD</th></tr>{rows}</table><div class="xs">Day: official sector index. Week and YTD: median stock in the sector. *Insurance: median stock (no index feed).</div></div>'''

def mv(title, rs, key="d"):
    body = "".join(f'<tr><td class="nm">{e(r["n"])}</td><td class="px">{r["px"]:,.2f}</td>'
                   + (f'<td class="g {"up" if r["d"]>=0 else "dn"}">{r["d"]:+.1f}%</td>' if key == "d" else f'<td class="g">{r["val"]:,.0f}</td>') + '</tr>' for r in rs)
    return f'<div class="mvh">{title}</div><table class="mv3">{body}</table>'
movers = (f'<div class="p3box"><div class="xt">Movers, latest session</div>{mv("Top gainers", P["gainers"])}{mv("Top decliners", P["losers"])}'
          f'{mv("Most traded, SAR mn", P["active"], "val")}</div>')

E = D["events"]
res = "".join(f'<tr><td class="nm">{e(r["co"])}</td><td class="px">{e(r["np"])}</td><td class="px pv">{e(r["prev"])}</td>'
              f'<td class="g {"up" if r["chg"]>=0 else "dn"}">{r["chg"]:+.1f}%</td></tr>' for r in E["results"])
results = (f'<div class="p3box"><div class="xt">Results scorecard: Q3 net profit</div><table class="rs"><tr><th>Company</th><th>Q3 2026</th>'
           f'<th>Q3 2025</th><th>Change</th></tr>{res}</table><div class="xs">{e(E.get("results_note",""))}</div></div>')
cal = "".join(f'<tr><td class="d">{e(c["d"])}</td><td>{e(c["t"])}</td></tr>' for c in E["calendar"])
calendar = f'<div class="p3box"><div class="xt">Coming up, next 10 days</div><table class="wk">{cal}</table></div>'
lines = "".join(f'<li><b>{e(x["k"])}</b> {e(x["t"])}</li>' for x in E["lines"])
radar_lines = f'<div class="p3box"><div class="xt">IPOs, regulators and flows</div><ul class="p3l">{lines}</ul></div>'

page = f'''<div class="page">
 <div class="runhead"><img src="wordmark.png"><div class="r">Daily Brief | {e(D["date"])} | Saudi market intelligence</div></div>
 <h2>Saudi market pulse <span class="h2s">{e(P["session"])}</span></h2>
 {tiles}
 <div class="cols" style="margin-top:2.5mm"><div class="col">{heatmap}</div><div class="col">{movers}</div></div>
 <div class="sowhat"><b>So what</b>{e(P["sowhat"])}</div>
 <h2 style="margin-top:4mm">Event radar <span class="h2s">{e(E["window"])}</span></h2>
 <div class="cols" style="margin-top:0"><div class="col">{results}</div><div class="col">{calendar}{radar_lines}</div></div>
 <div class="sowhat"><b>So what</b>{e(E["sowhat"])}</div>
 <div class="foot"><div><b>Audi Capital</b> | Daily Brief | {e(D["date"])}</div><div class="pg">03 / 03</div></div></div>'''
EXTRA = '''
.h2s{margin-left:auto;font-size:7pt;letter-spacing:.06em;color:var(--mute);font-weight:600;text-transform:none}
.p3tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:2.4mm}
.p3tiles>div{background:var(--mist);border-radius:4pt;padding:2mm 2.8mm}
.p3tiles .l{font-size:6.4pt;letter-spacing:.12em;text-transform:uppercase;color:var(--mute);font-weight:700}
.p3tiles .v{font-family:M;font-weight:600;font-size:13pt;letter-spacing:-.02em;line-height:1.2}
.p3tiles .c{font-size:6.8pt;color:var(--mute)}
.brbar{display:flex;height:4pt;border-radius:2pt;overflow:hidden;margin:.8mm 0 .6mm 0;gap:1.5px;background:#fff}
.brbar i{display:block;height:100%}.brbar .u{background:var(--up)}.brbar .d{background:var(--dn)}.brbar .f{background:#C9D1DC}
.p3box{border:.8pt solid var(--line);border-radius:5pt;padding:2.4mm 3mm;margin-bottom:2.4mm}
.p3box .xt{font-size:6.8pt;letter-spacing:.12em;text-transform:uppercase;color:var(--steel);font-weight:800;margin-bottom:1.2mm}
.hmt{width:100%;border-collapse:separate;border-spacing:1.5px;font-size:6.9pt}
.hmt th{font-size:6pt;color:var(--mute);font-weight:700;text-transform:uppercase;letter-spacing:.08em}
.hmt td.sn{color:var(--navy);font-weight:600;white-space:nowrap;padding-right:1.5mm}
.hmt td.hm{text-align:center;font-family:M;font-weight:600;width:15%;border-radius:2pt;padding:.45mm 0}
.mvh{font-size:6pt;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);font-weight:700;margin:1.2mm 0 .3mm 0}
table.mv3,table.rs{width:100%;border-collapse:collapse;font-size:7pt}
table.mv3 td,table.rs td{padding:.45mm 0;border-bottom:.4pt solid #E3E8EF}
table.mv3 td.nm,table.rs td.nm{font-weight:700;color:var(--navy)}
table.mv3 td.px,table.mv3 td.g,table.rs td.px,table.rs td.g{text-align:right;font-family:M;font-weight:600}
table.rs th{font-size:6pt;color:var(--mute);text-transform:uppercase;letter-spacing:.06em;text-align:right;font-weight:700}
table.rs th:first-child,table.rs th:nth-child(2){text-align:left}
table.wk{width:100%;border-collapse:collapse;font-size:7pt}table.wk td{padding:.5mm 0;border-bottom:.4pt solid #E3E8EF;vertical-align:top}
table.wk td.d{font-family:M;font-weight:600;color:var(--steel);width:15mm}
.p3l{margin:0;padding:0;list-style:none;font-size:7.2pt}.p3l li{margin-bottom:1mm}
.xs{font-size:6.2pt;color:var(--mute);margin-top:.8mm}
table.rs td.pv{color:var(--mute);font-weight:500}
.sowhat{background:var(--mist);border-left:3pt solid var(--steel);border-radius:0 4pt 4pt 0;padding:1.6mm 3mm;font-size:7.8pt}
.sowhat b{font-size:6.6pt;letter-spacing:.14em;text-transform:uppercase;color:var(--steel);margin-right:2mm}
'''
doc = f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}{EXTRA}</style></head><body>{page}</body></html>'
open("page3.html", "w", encoding="utf-8").write(doc)
from weasyprint import HTML
HTML(filename="page3.html", base_url=".").write_pdf(sys.argv[2])
print("wrote", sys.argv[2])
