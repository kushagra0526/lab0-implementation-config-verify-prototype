"""Verify an implementation config against discovery requirements, exactly, with witness inputs.

Config (a procurement app being set up for one customer):
  regions:   ["US", "UK", "DE", ...]          aliases: {"GB": "UK"}
  fx:        {"GBP": 1.27, "EUR": 1.08, "USD": 1.0}   (to USD)
  fields:    {name: {"form": bool, "import": bool, "api": bool}}   required per entry path
  rules:     [{id, regions: [...]|["*"], op: "<"|"<="|">"|">=", amount, currency, approvers: [...], tier: bool, stage}]
             tier rules are meant to partition amounts per region (exactly one matches);
             non-tier rules add approvers on top. stage: "pre_handoff" | "post_handoff"
  mapping:   [{src, dest, dest_required, src_maxlen, dest_maxlen}]
Requirements come from discovery sentences (reqs.py) with their source quote.

Amount conditions are thresholds, so checking each region at every threshold and just
either side of it (plus one point between thresholds) covers every possible request.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EPS = 0.01
PATHS = ("form", "import", "api")


@dataclass
class Finding:
    kind: str
    target: str
    detail: str
    witness: dict = field(default_factory=dict)
    source: str = ""


def region_of(cfg, r):
    return cfg.get("aliases", {}).get(r, r)


def usd(cfg, amount, cur):
    return amount * cfg["fx"][cur]


def matches(cfg, rule, region, amt_usd):
    regs = [region_of(cfg, x) for x in rule["regions"]]
    if "*" not in regs and region_of(cfg, region) not in regs:
        return False
    t = usd(cfg, rule["amount"], rule["currency"])
    return {"<": amt_usd < t - 1e-9, "<=": amt_usd <= t + 1e-9, ">": amt_usd > t + 1e-9, ">=": amt_usd >= t - 1e-9}[rule["op"]]


def probe_points(cfg, extra=()):
    """Every threshold in USD and just either side, plus midpoints and a tiny/huge amount."""
    ts = sorted({usd(cfg, r["amount"], r["currency"]) for r in cfg["rules"]} | set(extra))
    pts = {1.0, 10_000_000.0}
    for i, t in enumerate(ts):
        pts |= {t - EPS, t, t + EPS}
        if i + 1 < len(ts):
            pts.add((t + ts[i + 1]) / 2)
    return sorted(p for p in pts if p > 0)


def approvers(cfg, region, amt_usd, stage="pre_handoff"):
    out, tiers = set(), []
    for r in cfg["rules"]:
        if r.get("stage", "pre_handoff") == stage and matches(cfg, r, region, amt_usd):
            out |= set(r["approvers"])
            if r.get("tier"):
                tiers.append(r["id"])
    return out, tiers


def check(cfg, reqs):
    F = []
    regions = [region_of(cfg, r) for r in cfg["regions"]]
    # 1. required fields enforced on every entry path
    for rq in reqs:
        if rq["type"] == "FIELD_REQUIRED":
            f = cfg["fields"].get(rq["field"])
            if f is None:
                F.append(Finding("FIELD_MISSING", rq["field"], "required by discovery but not in the data model", source=rq["quote"]))
                continue
            for p in PATHS:
                if not f.get(p):
                    F.append(Finding("FIELD_BYPASS", f"{rq['field']}@{p}", f"required on {', '.join(q for q in PATHS if f.get(q)) or 'no path'} but not on {p}",
                                     {"path": p, rq["field"]: None, "result": "accepted"}, rq["quote"]))
    # 2. approval tiers: exactly one tier rule per (region, amount)
    pts = probe_points(cfg)
    for reg in regions:
        for a in pts:
            _, tiers = approvers(cfg, reg, a)
            if not tiers:
                F.append(Finding("TIER_GAP", reg, "no approval tier matches", {"region": reg, "amount_usd": round(a, 2)}))
            elif len(tiers) > 1:
                F.append(Finding("TIER_OVERLAP", reg, f"tiers {tiers} both match", {"region": reg, "amount_usd": round(a, 2)}))
    # 3. approval requirements, checked at every relevant point
    for rq in reqs:
        if rq["type"] != "APPROVER_REQUIRED":
            continue
        t = usd(cfg, rq["amount"], rq["currency"])
        for reg in [region_of(cfg, x) for x in rq["regions"]] if rq["regions"] != ["*"] else regions:
            for a in probe_points(cfg, extra=[t]):
                cond = {">": a > t + 1e-9, ">=": a >= t - 1e-9, "<": a < t - 1e-9, "<=": a <= t + 1e-9}[rq["op"]]
                if cond and rq["approver"] not in approvers(cfg, reg, a)[0]:
                    late = rq["approver"] in approvers(cfg, reg, a, "post_handoff")[0]
                    F.append(Finding("REQ_UNMET", rq["id"], f"{rq['approver']} {'only after' if late else 'not'} before the ERP handoff",
                                     {"region": reg, "amount": round(a / cfg["fx"][rq["currency"]], 2), "currency": rq["currency"]}, rq["quote"]))
                    break
    # 4. ERP mapping
    mapped = {m["dest"] for m in cfg["mapping"]}
    for d in cfg.get("erp_required", []):
        if d not in mapped:
            F.append(Finding("MAP_MISSING", d, "ERP requires this field but nothing maps to it"))
    for m in cfg["mapping"]:
        src = cfg["fields"].get(m["src"], {})
        if m.get("dest_required"):
            weak = [p for p in PATHS if not src.get(p)]
            if weak:
                F.append(Finding("MAP_NULL_RISK", f"{m['src']}->{m['dest']}", f"ERP field required, source optional on {', '.join(weak)}",
                                 {"path": weak[0], m["src"]: None, "result": "ERP handoff fails"}))
        if m.get("src_maxlen") and m.get("dest_maxlen") and m["src_maxlen"] > m["dest_maxlen"]:
            F.append(Finding("MAP_TRUNCATION", f"{m['src']}->{m['dest']}", f"source allows {m['src_maxlen']} chars, ERP {m['dest_maxlen']}",
                             {m["src"]: "x" * m["src_maxlen"]}))
    return dedupe(F)


def dedupe(F):
    seen, out = set(), []
    for f in F:
        k = (f.kind, f.target)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def impact(old, new):
    """Which (region, amount range) cells change approvers, plus boundary tests for them."""
    cells, tests = [], []
    pts = sorted(set(probe_points(old)) | set(probe_points(new)))
    for reg in [region_of(new, r) for r in new["regions"]]:
        for a in pts:
            before, after = approvers(old, reg, a)[0], approvers(new, reg, a)[0]
            if before != after:
                cells.append({"region": reg, "amount_usd": round(a, 2), "before": sorted(before), "after": sorted(after)})
    changed = {(c["region"]) for c in cells}
    for c in cells:
        tests.append({"region": c["region"], "amount_usd": c["amount_usd"], "expect": c["after"]})
    return cells, tests, changed
