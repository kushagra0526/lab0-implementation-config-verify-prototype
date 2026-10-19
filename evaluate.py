"""Score the config verifier vs a 30-request UAT sample run.

usage: python evaluate.py dev|heldout
heldout = new seeds + different discovery phrasings (frozen in git before the first run).
"""

import json
import sys
from collections import Counter
from pathlib import Path

from implcheck.check import check
from implcheck.projects import make, sample_uat
from implcheck.reqs import parse

SPLITS = {"dev": (range(1, 81), "dev"), "heldout": (range(4001, 4201), "heldout")}


def norm(f):
    kind, target = f
    return (kind, "*") if kind in ("TIER_GAP", "TIER_OVERLAP") else (kind, target)


def run(split):
    seeds, phr = SPLITS[split]
    res = {m: Counter() for m in ("verifier", "uat30")}
    unparsed_total, sentences, planted, miss_ex = 0, 0, 0, []
    for s in seeds:
        P = make(s, phr)
        reqs, unparsed = parse(P["sentences"])
        unparsed_total += len(unparsed)
        sentences += len(P["sentences"])
        T = set(P["truth"])
        planted += len(T)
        V = {norm((f.kind, f.target)) for f in check(P["cfg"], reqs)}
        U = sample_uat(P["cfg"], reqs, s)
        for m, F in (("verifier", V), ("uat30", U)):
            res[m]["caught"] += len(F & T)
            res[m]["false"] += len(F - T)
            for k, _ in T - F:
                res[m]["miss_" + k] += 1
        if T - V and len(miss_ex) < 5:
            miss_ex.append({"seed": s, "missed": sorted(T - V), "false": sorted(V - T), "unparsed": unparsed})
    return {"split": split, "projects": len(seeds), "planted": planted, "sentences": sentences, "unparsed": unparsed_total,
            "results": {m: dict(c) for m, c in res.items()}, "verifier_miss_examples": miss_ex}


if __name__ == "__main__":
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    o = run(split)
    Path("out").mkdir(exist_ok=True)
    Path(f"out/{split}.json").write_text(json.dumps(o, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{split}: {o['projects']} projects, {o['planted']} planted defects, {o['unparsed']}/{o['sentences']} discovery sentences NOT CHECKED (listed)\n")
    for m, r in o["results"].items():
        misses = {k[5:]: v for k, v in r.items() if k.startswith("miss_")}
        print(f"  {m:9} caught {r.get('caught', 0):4}/{o['planted']}  false flags {r.get('false', 0):3}  missed: {misses}")
    for e in o["verifier_miss_examples"]:
        print("   miss:", e)
