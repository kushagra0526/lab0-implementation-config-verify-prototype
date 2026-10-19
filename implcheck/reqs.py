"""Discovery sentences -> checkable requirements. Anything not parsed is listed as NOT CHECKED."""

from __future__ import annotations

import re

CUR = {"£": "GBP", "$": "USD", "€": "EUR", "gbp": "GBP", "usd": "USD", "eur": "EUR"}
OPS = {"over": ">", "above": ">", "more than": ">", "exceeding": ">", "at least": ">=", "or more": ">=",
       "and above": ">=", "under": "<", "below": "<", "less than": "<", "up to": "<="}
REGION_WORDS = {"uk": "UK", "british": "UK", "us": "US", "american": "US", "german": "DE", "germany": "DE", "de": "DE",
                "french": "FR", "france": "FR", "all": "*", "every": "*", "any": "*"}


def _money(s):
    m = re.search(r"([£$€])\s?([\d,]+(?:\.\d+)?)\s*(k)?|([\d,]+(?:\.\d+)?)\s*(k)?\s*(gbp|usd|eur)", s, re.I)
    if not m:
        return None
    if m.group(1):
        v, cur, k = float(m.group(2).replace(",", "")), CUR[m.group(1)], m.group(3)
    else:
        v, cur, k = float(m.group(4).replace(",", "")), CUR[m.group(6).lower()], m.group(5)
    return v * (1000 if k else 1), cur


def parse(sentences):
    reqs, unparsed = [], []
    for i, s in enumerate(sentences):
        low = s.lower()
        m = re.search(r"(?:every|each|all) (?:purchase )?requests? (?:needs?|must have|requires?) (?:a |an )?([a-z ]+?)[.,]?$", low)
        if m:
            reqs.append({"id": f"R-{100 + i}", "type": "FIELD_REQUIRED", "field": m.group(1).strip().replace(" ", "_"), "quote": s})
            continue
        money = _money(s)
        appr = re.search(r"(?:add|needs?|requires?|must get|with) (?:a |an )?([a-z ]+?) (?:review|approval|sign-?off)", low)
        if money and appr:
            op = next((v for k, v in sorted(OPS.items(), key=lambda kv: -len(kv[0])) if re.search(rf"\b{k}\b", low)), None)
            if op:
                reg = re.search(r"\bfor (\w+) requests\b", low) or re.search(r"\b(uk|us|german|french|british|american) requests\b", low)
                region = REGION_WORDS.get(reg.group(1), reg.group(1).upper()) if reg else "*"
                reqs.append({"id": f"R-{100 + i}", "type": "APPROVER_REQUIRED", "regions": [region], "op": op, "amount": money[0],
                             "currency": money[1], "approver": appr.group(1).strip().replace(" ", "_"), "quote": s})
                continue
        unparsed.append(s)
    return reqs, unparsed
