"""The procurement scenario from a typical ERP rollout: discovery -> config check -> change request impact."""
import copy

from implcheck.check import check, impact
from implcheck.reqs import parse

DISCOVERY = ["Every request needs a cost center.",
             "Requests of $10,000 and above need a finance approval.",
             "For UK requests over £25,000, add a finance director review before the ERP handoff.",
             "Approval depends on amount and region."]
CFG = {"regions": ["US", "UK", "DE"], "aliases": {"GB": "UK"}, "fx": {"USD": 1.0, "GBP": 1.27, "EUR": 1.08},
       "fields": {"cost_center": {"form": True, "import": False, "api": True}, "legal_entity": {"form": True, "import": True, "api": True},
                  "requester": {"form": True, "import": True, "api": True}, "amount": {"form": True, "import": True, "api": True}},
       "rules": [{"id": "T1", "regions": ["*"], "op": "<", "amount": 10000, "currency": "USD", "approvers": ["line_manager"], "tier": True},
                 {"id": "T2", "regions": ["*"], "op": ">", "amount": 10000, "currency": "USD", "approvers": ["line_manager", "finance"], "tier": True}],
       "mapping": [{"src": "cost_center", "dest": "Dimension.Code", "dest_required": True},
                   {"src": "legal_entity", "dest": "Company.Code", "dest_required": True, "src_maxlen": 40, "dest_maxlen": 12},
                   {"src": "amount", "dest": "Line.Amount", "dest_required": True},
                   {"src": "requester", "dest": "Approval.Owner", "dest_required": True}],
       "erp_required": ["Dimension.Code", "Company.Code", "Line.Amount", "Approval.Owner"]}

reqs, unparsed = parse(DISCOVERY)
print("REQUIREMENTS")
for r in reqs:
    print(f"  {r['id']} {r['type']:17} <- \"{r['quote']}\"")
for u in unparsed:
    print(f"  NOT CHECKED       <- \"{u}\"")
print("\nFINDINGS (current config)")
for f in check(CFG, reqs):
    print(f"  {f.kind:15} {f.target:28} {f.detail}\n  {'':15} witness: {f.witness}")

new = copy.deepcopy(CFG)
new["rules"][1]["op"] = ">="
new["fields"]["cost_center"]["import"] = True
new["mapping"][1]["src_maxlen"] = 12
new["rules"].append({"id": "CR-0248", "regions": ["GB"], "op": ">", "amount": 25000, "currency": "GBP", "approvers": ["finance_director"]})
print(f"\nAFTER FIXES + CR-0248: {len(check(new, reqs))} findings")
cells, tests, regions = impact(CFG, new)
print(f"impact: {len(cells)} (region, amount) cells change approvers in {sorted(regions)}; boundary tests:")
for t in tests:
    print(f"  {t['region']} ${t['amount_usd']:,.2f} -> expect {t['expect']}")
