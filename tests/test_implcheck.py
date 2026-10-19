import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from implcheck.check import approvers, check, impact
from implcheck.reqs import parse

BASE = {"regions": ["US", "UK"], "aliases": {"GB": "UK"}, "fx": {"USD": 1.0, "GBP": 1.27, "EUR": 1.08},
        "fields": {"cost_center": {"form": True, "import": True, "api": True}},
        "rules": [{"id": "T1", "regions": ["*"], "op": "<", "amount": 10000, "currency": "USD", "approvers": ["manager"], "tier": True},
                  {"id": "T2", "regions": ["*"], "op": ">=", "amount": 10000, "currency": "USD", "approvers": ["manager", "finance"], "tier": True}],
        "mapping": [], "erp_required": []}


def cfg(**kw):
    import copy
    c = copy.deepcopy(BASE)
    c.update(kw)
    return c


def kinds(c, sents):
    return {(f.kind, f.target) for f in check(c, parse(sents)[0])}


class TestParse(unittest.TestCase):
    def test_sentences(self):
        r, u = parse(["Every request needs a cost center.", "For UK requests over £25,000, add a finance review before the ERP handoff.",
                      "Approval depends on amount and region."])
        self.assertEqual(r[0]["field"], "cost_center")
        self.assertEqual((r[1]["regions"], r[1]["op"], r[1]["amount"], r[1]["currency"], r[1]["approver"]), (["UK"], ">", 25000, "GBP", "finance"))
        self.assertEqual(u, ["Approval depends on amount and region."])


class TestChecks(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(kinds(cfg(), ["Every request needs a cost center."]), set())

    def test_import_bypass(self):
        c = cfg(fields={"cost_center": {"form": True, "import": False, "api": True}})
        self.assertIn(("FIELD_BYPASS", "cost_center@import"), kinds(c, ["Every request needs a cost center."]))

    def test_tier_gap_at_exact_threshold(self):
        c = cfg()
        c["rules"][1]["op"] = ">"
        f = [x for x in check(c, []) if x.kind == "TIER_GAP"]
        self.assertTrue(f)
        self.assertEqual(f[0].witness["amount_usd"], 10000)

    def test_currency_and_alias(self):
        uk = "For UK requests over £25,000, add a legal review before the ERP handoff."
        ok = cfg(rules=BASE["rules"] + [{"id": "X", "regions": ["GB"], "op": ">", "amount": 31000, "currency": "USD", "approvers": ["legal"]}])
        self.assertEqual({k for k in kinds(ok, [uk]) if k[0] == "REQ_UNMET"}, set())       # $31,000 < £25,000: stricter, fine
        lax = cfg(rules=BASE["rules"] + [{"id": "X", "regions": ["UK"], "op": ">", "amount": 25000, "currency": "EUR", "approvers": ["legal"]}])
        self.assertEqual(kinds(lax, [uk]), set())                                           # EUR 25k < GBP 25k: also stricter
        bad = cfg(rules=[r for r in BASE["rules"]] + [{"id": "X", "regions": ["UK"], "op": ">", "amount": 40000, "currency": "USD", "approvers": ["legal"]}])
        self.assertIn(("REQ_UNMET", "R-100"), kinds(bad, [uk]))                             # $40,000 > £25,000: misses £25k–£31.5k

    def test_post_handoff_is_too_late(self):
        c = cfg(rules=BASE["rules"] + [{"id": "X", "regions": ["UK"], "op": ">", "amount": 25000, "currency": "GBP", "approvers": ["finance_dir"], "stage": "post_handoff"}])
        f = [x for x in check(c, parse(["For UK requests over £25,000, add a finance dir review before the ERP handoff."])[0]) if x.kind == "REQ_UNMET"]
        self.assertIn("only after", f[0].detail)

    def test_impact(self):
        new = cfg(rules=BASE["rules"] + [{"id": "X", "regions": ["UK"], "op": ">", "amount": 25000, "currency": "GBP", "approvers": ["finance_review"]}])
        cells, tests, regions = impact(cfg(), new)
        self.assertEqual(regions, {"UK"})
        self.assertTrue(all(c["amount_usd"] > 31749 for c in cells))


if __name__ == "__main__":
    unittest.main()
