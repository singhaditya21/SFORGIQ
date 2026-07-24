#!/usr/bin/env python3
"""
Generate a whole *portfolio* of synthetic client-org scans and emit them as one
JSON, ready to bulk-load into the OrgIQ Salesforce org.

This exists to fill the org with realistic, high-variety data: many fictional
client orgs spanning the full readiness spectrum (Not Ready -> Ready), every D1
rule / severity / confidence, plus a few multi-quarter time series so the data
shows a remediation burn-down.

Fields are generated in memory and run through the real D1 rules — findings are
genuine rule output, not fabricated. Deterministic (seeded), stdlib only.

    python3 scanner/scan_portfolio.py --out portfolio.json
"""

from __future__ import annotations

import argparse
import json
import random

import orgiq_spike as scanner          # Field, RULES, ABBREV
import scan_result

Field = scanner.Field
ABBREV = scanner.ABBREV
FULL_TO_ABBR = {v: k for k, v in ABBREV.items()}   # e.g. "amount" -> "amt"

# ------------------------------------------------------------ vocabulary

ENTITIES = [
    "Account", "Customer", "Contract", "Invoice", "Shipment", "Policy", "Claim",
    "Patient", "Order", "Payment", "Subscription", "Ticket", "Asset", "Vendor",
    "Employee", "Product", "Campaign", "Lead", "Case", "Booking", "Loan",
    "Deposit", "Route", "Meter", "Device", "Enrollment", "Provider", "Member",
    "Session", "Warehouse", "Reservation", "Prescription", "Portfolio",
]
ATTRS = [
    "Balance", "Amount", "Category", "Priority", "Region", "Segment", "Owner",
    "Source", "Channel", "Tier", "Score", "Reason", "Method", "Frequency",
    "Rating", "Currency", "Country", "Duration", "Discount", "Quantity",
    "Revenue", "Margin", "Weight", "Volume", "Origin", "Destination",
    "Severity", "Outcome", "Stage", "Version", "Batch", "Reference",
    "Threshold", "Interval", "Percentage", "Limit", "Address", "Manager",
]
QUALIFIERS = ["Primary", "Secondary", "Initial", "Final", "Current", "Prior",
              "Net", "Gross", "Total", "Average", "Expected", "Actual",
              "Preferred", "Estimated", "Adjusted"]
TYPES = ["Text", "Number", "Currency", "Date", "Checkbox", "Picklist", "Percent"]

# Attributes that have a known abbreviation in the scanner's map — used to build
# guaranteed cryptic names and guaranteed semantic-duplicate pairs.
ABBREVIABLE = [a for a in ATTRS if a.lower() in FULL_TO_ABBR]


def _drop_vowels(word: str) -> str:
    out = word[0] + "".join(c for c in word[1:] if c.lower() not in "aeiou")
    return out or word


def _label(api: str) -> str:
    return api[:-3].replace("_", " ") if api.endswith("__c") else api


class FieldFactory:
    """Builds one object's worth of fields with a controlled defect mix."""

    def __init__(self, obj: str, rnd: random.Random):
        self.obj = obj
        self.rnd = rnd
        self.used = set()

    def _name(self, *parts) -> str | None:
        api = "_".join(parts) + "__c"
        if api in self.used:
            return None
        self.used.add(api)
        return api

    def clean(self):
        for _ in range(6):
            q = self.rnd.choice(QUALIFIERS)
            a = self.rnd.choice(ATTRS)
            api = self._name(q, a)
            if api:
                lbl = _label(api)
                desc = (f"The {q.lower()} {a.lower()} recorded for each "
                        f"{self.obj.replace('__c','').lower()} during processing.")
                return Field(self.obj, api, lbl, self.rnd.choice(TYPES), desc, "", "")
        return None

    def missing(self):
        for _ in range(6):
            api = self._name(self.rnd.choice(QUALIFIERS), self.rnd.choice(ATTRS))
            if api:
                return Field(self.obj, api, _label(api), self.rnd.choice(TYPES), "", "", "")
        return None

    def low_info(self):
        for _ in range(6):
            api = self._name(self.rnd.choice(ATTRS))
            if api:
                lbl = _label(api)
                return Field(self.obj, api, lbl, "Text", lbl, "", "")   # desc == label
        return None

    def cryptic(self):
        a = self.rnd.choice(ATTRS)
        token = FULL_TO_ABBR.get(a.lower(), _drop_vowels(a))
        for _ in range(6):
            api = self._name(self.rnd.choice(["Cust", "Acct", "Cd", "Ref"]),
                             token.capitalize())
            if api:
                return Field(self.obj, api, _label(api), "Text", "", "", "")  # no desc
        return None

    def duplicate_pair(self):
        if not ABBREVIABLE:
            return []
        a = self.rnd.choice(ABBREVIABLE)
        abbr = FULL_TO_ABBR[a.lower()].capitalize()
        ent = self.rnd.choice(ENTITIES)
        full = self._name(ent, a)
        short = self._name(ent, abbr)
        out = []
        if full:
            out.append(Field(self.obj, full, _label(full), "Text",
                             f"The {a.lower()} associated with the {ent.lower()}.", "", ""))
        if short:
            out.append(Field(self.obj, short, _label(short), "Text", "", "", ""))
        return out

    def family(self, k: int):
        base = self.rnd.choice(["Contact", "Tech", "Acct", "Line", "Note", "Ref"])
        attr = self.rnd.choice(["Email", "Ref", "Id", "Name", "Code"])
        out = []
        for i in range(1, k + 1):
            api = self._name(f"{base}{i}", attr)
            if api:
                out.append(Field(self.obj, api, _label(api), "Text", "", "", ""))
        return out


def gen_object_fields(obj, n, defect_ratio, rnd) -> list:
    f = FieldFactory(obj, rnd)
    fields, defects = [], int(round(n * defect_ratio))
    clean = n - defects
    for _ in range(clean):
        x = f.clean()
        if x:
            fields.append(x)
    # spend the defect budget across the defect classes
    budget = defects
    while budget > 0:
        r = rnd.random()
        if r < 0.50:
            x = f.missing();  fields += [x] if x else []; budget -= 1
        elif r < 0.70:
            x = f.cryptic();  fields += [x] if x else []; budget -= 1
        elif r < 0.82:
            x = f.low_info(); fields += [x] if x else []; budget -= 1
        elif r < 0.92:
            grp = f.family(rnd.randint(2, 4)); fields += grp; budget -= len(grp) or 1
        else:
            pair = f.duplicate_pair(); fields += pair; budget -= len(pair) or 1
    return fields


def gen_org(name, industry, total_fields, defect_ratio, n_objects, mode, seed):
    rnd = random.Random(seed)
    objs = [f"{industry}_{rnd.choice(ENTITIES)}{i+1}__c" for i in range(n_objects)]
    per = max(4, total_fields // n_objects)
    fields = []
    for obj in objs:
        fields += gen_object_fields(obj, per, defect_ratio, rnd)
    return name, mode, fields


# --------------------------------------------------------- portfolio spec
#
# (name, industry, total_fields, defect_ratio, n_objects, mode)
# defect_ratio drives the readiness band; sizes drive the finding volume.

SPECS = [
    # Ready / Conditionally Ready — clean, modern orgs
    ("Northwind Robotics",       "Mfg",     55, 0.06, 2, "Source"),
    ("Cobalt Analytics",         "Saas",    60, 0.10, 2, "Source"),
    ("Vireo Health Cloud",       "Health",  65, 0.16, 2, "Org"),
    ("Meridian Wealth",          "Fin",     75, 0.22, 3, "Hybrid"),
    ("Solstice Retail Group",    "Retail",  85, 0.28, 3, "Source"),
    # Foundational Work Required — mid-life orgs carrying real debt
    ("Anchor Freight Systems",   "Logi",    95, 0.40, 3, "Org"),
    ("Bluepeak Telecom",         "Telco",  100, 0.44, 3, "Source"),
    ("Cascade Insurance",        "Ins",    100, 0.48, 3, "Org"),
    ("Harborline Bank",          "Fin",    105, 0.50, 3, "Hybrid"),
    ("Pinnacle Energy",          "Energy", 100, 0.52, 3, "Source"),
    ("Trailhead Education",      "Edu",     95, 0.46, 3, "Org"),
    ("Fathom Media Networks",    "Media",  100, 0.47, 3, "Source"),
    # Not Ready — old, heavily-accreted enterprise orgs
    ("Gateway Health Alliance",  "Health", 110, 0.72, 3, "Org"),
    ("Irongate Manufacturing",   "Mfg",    115, 0.80, 4, "Source"),
    ("Summit Telecom Legacy",    "Telco",  115, 0.84, 4, "Org"),
    ("Delta Logistics Intl",     "Logi",   110, 0.78, 4, "Hybrid"),
    ("Crownpoint Insurance",     "Ins",    110, 0.82, 4, "Org"),
    ("Old Mill Bancorp",         "Fin",    115, 0.86, 4, "Source"),
    ("Redwood Utilities",        "Energy", 105, 0.76, 3, "Org"),
    ("Beacon Public Sector",     "Gov",    110, 0.80, 4, "Source"),
    # Time series — one org remediating over four quarters (burn-down)
    ("Helios Airlines · 2025-Q1", "Travel", 115, 0.82, 4, "Org"),
    ("Helios Airlines · 2025-Q2", "Travel", 115, 0.58, 4, "Org"),
    ("Helios Airlines · 2025-Q3", "Travel", 115, 0.36, 4, "Org"),
    ("Helios Airlines · 2025-Q4", "Travel", 115, 0.18, 4, "Org"),
]


def build_portfolio():
    scans = []
    for i, (name, industry, size, ratio, nobj, mode) in enumerate(SPECS):
        _, m, fields = gen_org(name, industry, size, ratio, nobj, mode, seed=1000 + i)
        findings = []
        for _, fn in scanner.RULES:
            findings.extend(fn(fields))
        scans.append(scan_result.build(fields, findings, name, scan_mode=m))
    return scans


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    scans = build_portfolio()
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"scans": scans}, fh, indent=2)

    total_f = sum(len(s["findings"]) for s in scans)
    total_d = sum(len(s["dimensions"]) for s in scans)
    bands = {}
    for s in scans:
        b = s["scan"]["readiness_band"]
        bands[b] = bands.get(b, 0) + 1
    print(f"wrote {a.out}")
    print(f"  scans:      {len(scans)}")
    print(f"  findings:   {total_f}")
    print(f"  dimensions: {total_d}")
    print(f"  records:    {len(scans) + total_f + total_d}")
    print(f"  bands:      {bands}")
    print("\n  per-scan:")
    for s in scans:
        sc = s["scan"]
        print(f"    {sc['composite_score']:>3} {sc['readiness_band']:<26} "
              f"{len(s['findings']):>4} findings  {sc['target_org']}")


if __name__ == "__main__":
    main()
