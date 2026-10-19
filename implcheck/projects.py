"""Synthetic implementation projects: discovery sentences + a config with planted defects and look-alikes."""

from __future__ import annotations

import copy
import random

from .check import approvers, region_of, usd

DEFECTS = ["FIELD_BYPASS", "TIER_GAP", "TIER_OVERLAP", "REQ_CURRENCY", "REQ_REGION", "REQ_STAGE", "REQ_BOUNDARY",
           "MAP_NULL_RISK", "MAP_TRUNCATION", "MAP_MISSING"]
LOOKS = ["ALIAS_REGION", "STRICTER_OTHER_CURRENCY", "ADDITIVE_OVERLAP", "OPTIONAL_TO_OPTIONAL", "CLEAN_BOUNDARY"]
SYM = {"GBP": "£", "USD": "$", "EUR": "€"}
REGWORD = {"UK": "UK", "US": "US", "DE": "German", "FR": "French"}


def make(seed: int, phrasing: str = "dev"):
    rng = random.Random(seed)
    fx = {"USD": 1.0, "GBP": round(rng.uniform(1.22, 1.32), 2), "EUR": round(rng.uniform(1.04, 1.12), 2)}
    regions = rng.sample(["US", "UK", "DE", "FR"], rng.randint(2, 4))
    fields = {f: {"form": True, "import": True, "api": True} for f in ["cost_center", "legal_entity", "requester", "amount"]}
    fields["project_code"] = {"form": False, "import": False, "api": False}
    tier_t = rng.choice([5000, 10000, 15000, 25000])
    rules = [{"id": "T1", "regions": ["*"], "op": "<", "amount": tier_t, "currency": "USD", "approvers": ["line_manager"], "tier": True},
             {"id": "T2", "regions": ["*"], "op": ">=", "amount": tier_t, "currency": "USD", "approvers": ["line_manager", "finance"], "tier": True}]
    # one regional extra review requirement
    reg = rng.choice(regions)
    cur = {"UK": "GBP", "US": "USD"}.get(reg, "EUR")
    amt = rng.choice([20000, 25000, 40000, 50000])
    approver = rng.choice(["finance_director", "procurement", "cfo"])
    op_word, op = rng.choice([("over", ">"), ("and above", ">=")])
    amt_phrase = f"over {SYM[cur]}{amt:,}" if op == ">" else f"of {SYM[cur]}{amt:,} and above"
    rules.append({"id": "X1", "regions": [reg], "op": op, "amount": amt, "currency": cur, "approvers": [approver], "stage": "pre_handoff"})
    mapping = [{"src": "cost_center", "dest": "Dimension.Code", "dest_required": True, "src_maxlen": 10, "dest_maxlen": 20},
               {"src": "legal_entity", "dest": "Company.Code", "dest_required": True, "src_maxlen": 8, "dest_maxlen": 12},
               {"src": "amount", "dest": "Line.Amount", "dest_required": True},
               {"src": "requester", "dest": "Approval.Owner", "dest_required": True, "src_maxlen": 60, "dest_maxlen": 80}]
    erp_required = ["Dimension.Code", "Company.Code", "Line.Amount", "Approval.Owner"]
    if phrasing == "dev":
        S = ["Every request needs a cost center.",
             f"For {REGWORD[reg]} requests {amt_phrase}, add a {approver.replace('_', ' ')} review before the ERP handoff.",
             f"Requests of ${tier_t:,} and above need a finance approval.", "Approval depends on amount and region."]
    else:   # held-out phrasings (different sentence shapes)
        amt_txt = rng.choice([f"{SYM[cur]}{amt:,}", f"{amt // 1000}k {cur}"])
        S = ["All purchase requests must have a cost center.",
             f"For {REGWORD[reg]} requests {'exceeding' if op == '>' else 'at least'} {amt_txt}, they need a {approver.replace('_', ' ')} sign-off.",
             f"Anything at least ${tier_t:,} requires a finance approval.", "Managers approve smaller requests in all regions."]
    cfg = {"regions": regions, "aliases": {"GB": "UK"}, "fx": fx, "fields": fields, "rules": rules, "mapping": mapping, "erp_required": erp_required}
    truth, looks = [], []
    plant = rng.sample(DEFECTS, rng.randint(1, 3))
    if "TIER_GAP" in plant and "TIER_OVERLAP" in plant:   # together they cancel into a valid partition
        plant.remove("TIER_OVERLAP")
    for d in plant:
        if d == "FIELD_BYPASS":
            p = rng.choice(["import", "api"])
            cfg["fields"]["cost_center"][p] = False
            truth.append(("FIELD_BYPASS", f"cost_center@{p}"))
            truth.append(("MAP_NULL_RISK", "cost_center->Dimension.Code"))   # same root cause, both are real
        elif d == "TIER_GAP":
            cfg["rules"][1]["op"] = ">"
            truth.append(("TIER_GAP", "*"))
            truth.append(("REQ_UNMET", "R-102"))   # "and above" now misses the exact threshold
        elif d == "TIER_OVERLAP":
            cfg["rules"][0]["op"] = "<="
            truth.append(("TIER_OVERLAP", "*"))
        elif d == "REQ_CURRENCY" and cur != "GBP":
            cfg["rules"][2]["currency"] = "GBP"      # same number, stronger currency: laxer rule
            truth.append(("REQ_UNMET", "R-101"))
        elif d == "REQ_REGION":
            cfg["rules"][2]["regions"] = [rng.choice(["IE", "EN", "UKI"])]
            truth.append(("REQ_UNMET", "R-101"))
        elif d == "REQ_STAGE":
            cfg["rules"][2]["stage"] = "post_handoff"
            truth.append(("REQ_UNMET", "R-101"))
        elif d == "REQ_BOUNDARY" and op == ">=":
            cfg["rules"][2]["op"] = ">"
            truth.append(("REQ_UNMET", "R-101"))
        elif d == "MAP_NULL_RISK":
            cfg["fields"]["legal_entity"]["api"] = False
            truth.append(("MAP_NULL_RISK", "legal_entity->Company.Code"))
        elif d == "MAP_TRUNCATION":
            next(m for m in cfg["mapping"] if m["src"] == "requester")["src_maxlen"] = 120
            truth.append(("MAP_TRUNCATION", "requester->Approval.Owner"))
        elif d == "MAP_MISSING":
            cfg["mapping"] = [m for m in cfg["mapping"] if m["dest"] != "Line.Amount"]
            truth.append(("MAP_MISSING", "Line.Amount"))
    for a in rng.sample(LOOKS, rng.randint(2, 4)):
        x1_touched = any(k == "REQ_UNMET" and t == "R-101" for k, t in truth)
        if a in ("ALIAS_REGION", "STRICTER_OTHER_CURRENCY") and x1_touched:
            continue    # look-alikes only on rules without a planted defect
        if a == "ALIAS_REGION" and reg == "UK" and cfg["rules"][2]["regions"] == ["UK"]:
            cfg["rules"][2]["regions"] = ["GB"]
            looks.append(a)
        elif a == "STRICTER_OTHER_CURRENCY" and cfg["rules"][2]["currency"] == cur and cur != "USD":
            r = cfg["rules"][2]
            r["amount"], r["currency"] = int(amt * fx[cur] * 0.97), "USD"     # a bit below in USD: still covers the requirement
            looks.append(a)
        elif a == "ADDITIVE_OVERLAP":
            cfg["rules"].append({"id": "X2", "regions": ["*"], "op": ">", "amount": 100000, "currency": "USD", "approvers": ["cfo"]})
            looks.append(a)
        elif a == "OPTIONAL_TO_OPTIONAL":
            cfg["mapping"].append({"src": "project_code", "dest": "Line.Project", "dest_required": False})
            looks.append(a)
        elif a == "CLEAN_BOUNDARY":
            looks.append(a)
    return {"sentences": S, "cfg": cfg, "truth": sorted(set(truth)), "lookalikes": looks, "region": reg}


def sample_uat(cfg, reqs, seed, n=30):
    """Baseline: a tester runs n random purchase requests through the form and checks outcomes."""
    rng = random.Random(seed)
    found = set()
    for _ in range(n):
        reg = rng.choice(cfg["regions"])
        a = 10 ** rng.uniform(2.5, 5.5)
        appr, tiers = approvers(cfg, reg, a)
        if len(tiers) == 0:
            found.add(("TIER_GAP", "*"))
        if len(tiers) > 1:
            found.add(("TIER_OVERLAP", "*"))
        for rq in reqs:
            if rq["type"] == "APPROVER_REQUIRED":
                regs = rq["regions"]
                if regs != ["*"] and region_of(cfg, reg) not in [region_of(cfg, x) for x in regs]:
                    continue
                t = usd(cfg, rq["amount"], rq["currency"])
                cond = {">": a > t, ">=": a >= t, "<": a < t, "<=": a <= t}[rq["op"]]
                if cond and rq["approver"] not in appr:
                    found.add(("REQ_UNMET", rq["id"]))
        if rng.random() < 0.1:                       # occasionally types a long requester name
            for m in cfg["mapping"]:
                if m.get("src_maxlen", 0) > m.get("dest_maxlen", 1e9):
                    found.add(("MAP_TRUNCATION", f"{m['src']}->{m['dest']}"))
    mapped = {m["dest"] for m in cfg["mapping"]}
    for d in cfg["erp_required"]:
        if d not in mapped:
            found.add(("MAP_MISSING", d))           # the first ERP handoff fails loudly
    return found
