#!/usr/bin/env python3
"""Build series.json (close history per instrument, keyed by asOf date).
Merges the existing series.json (history carried forward) with every dated snapshot in market_data/."""
import json, glob, os, collections
HERE = os.path.dirname(os.path.abspath(__file__))
S = collections.defaultdict(dict)
out = os.path.join(HERE, "series.json")
try:
    for k, v in json.load(open(out, encoding="utf-8-sig")).items():
        S[k].update(v)
except Exception:
    pass
for f in sorted(glob.glob(os.path.join(HERE, "market_data", "*.json"))):
    try:
        d = json.load(open(f, encoding="utf-8-sig"))
    except Exception:
        continue
    for i in d.get("items", []):
        if i.get("close") is not None and i.get("asOf"):
            S[i["name"]][i["asOf"]] = i["close"]
S = {k: dict(sorted(v.items())) for k, v in S.items()}
json.dump(S, open(out, "w"))
print("series.json:", len(S), "instruments;", min(len(v) for v in S.values()), "to", max(len(v) for v in S.values()), "points each")
