#!/usr/bin/env python3
"""Build series.json (close history per instrument, keyed by asOf date) from the dated
snapshots in market_data/. Run in the brief folder:  python3 make_series.py
Used by the rotating chart types in build_brief_v2.py (small multiples, heatmap, rebased lines, curve comparison)."""
import json, glob, os, collections
S = collections.defaultdict(dict)
for f in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_data", "*.json"))):
    try:
        d = json.load(open(f, encoding="utf-8-sig"))
    except Exception:
        continue
    for i in d.get("items", []):
        if i.get("close") is not None and i.get("asOf"):
            S[i["name"]][i["asOf"]] = i["close"]
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "series.json")
json.dump(S, open(out, "w"))
print("series.json:", len(S), "instruments;", min(len(v) for v in S.values()), "to", max(len(v) for v in S.values()), "points each")
