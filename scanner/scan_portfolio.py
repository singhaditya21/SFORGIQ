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

The generated SIGNALS respect the scan mode each org is labelled with, which is
the difference between a demo corpus and a demo lie. A Source-mode org gets no
record-level statistics, because no directory on disk carries rows — so D2 comes
out Not Assessed for those orgs, exactly as it does for a real source-mode scan.
A couple of the Org-mode orgs get a partial D2 (the duplicate probe has nothing
to group on, which is what an auto-number Name field does to a real org): those
land under the 70% coverage bar and are reported Partially Assessed and kept out
of the composite. Coverage in this file is never asserted, only generated —
every percentage the portfolio shows is computed by the same signal registry the
real scanner uses.

    python3 scanner/scan_portfolio.py --out portfolio.json
    python3 scanner/scan_portfolio.py --out portfolio.json --backlog backlog.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import random

import backlog                         # gate + row shaping for the Jira CSV
import drift as drift_mod
import lifecycle
import persona as persona_mod
import density                         # REMOVABLE_KEYS — the payload breakdown buckets
import enterprises
import metadata as md                  # Flow / Apex / trigger / permission-set model
import orgiq_spike as scanner          # Field, RULES, ABBREV
import rules_ext                       # the real D2–D5 rule packs
import scan_result
from datetime import datetime, timezone

_NOW = datetime.now(timezone.utc)

Field = scanner.Field
ABBREV = scanner.ABBREV
FULL_TO_ABBR = {v: k for k, v in ABBREV.items()}   # e.g. "amount" -> "amt"

# --------------------------------------------------------- record budget
#
# Everything this script emits lands in a Developer Edition org, which allows
# ~5 MB of data and charges 2 KB per custom-object record whatever the row
# actually weighs. Records = scans + dimension scores + findings, so a rule that
# fires once per field (D1.UNREFERENCED_FIELD does) moves the total fast. The
# budget is deliberately below the ceiling: a bulk load that half-fits is worse
# than a smaller corpus.
RECORD_KB = 2
RECORD_BUDGET = 2300               # ≈4.5 MB of the org's ~5 MB allocation

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


def gen_report_refs(fields, r, rnd) -> md.ReportRefs:
    """Synthetic report/dashboard consumption for one org.

    Same shape `metadata.parse_reports` returns, so D1.UNREFERENCED_FIELD and the
    blast-radius weighting run on the demo portfolio exactly as they do on a real
    SFDX tree. Driven by the org's defect ratio like everything else here: a
    neglected org keeps building fields and stops building reports, so the share
    of fields no document touches climbs with the ratio.

    The dark share stays modest on purpose. Real legacy orgs are far darker than
    this, but every unreferenced field is a record in a 2 KB-per-row org — see
    RECORD_BUDGET.
    """
    refs = md.ReportRefs()
    if not fields:
        return refs

    # Reporting estate: about one document per ten fields, thinner where the org
    # stopped investing — the same neglect the defect ratio already encodes.
    n_docs = max(3, int(round(len(fields) * 0.10 * (1.2 - 0.6 * r))))
    refs.report_count = n_docs
    refs.dashboard_count = max(1, n_docs // 4)

    # Share of fields nothing reports on. Sampled to an exact count rather than
    # rolled per field: at ~85 fields an independent roll per field varies by
    # several points either way, which was enough to make the Helios quarters
    # tick *up* mid-remediation. The burn-down has to be monotonic to be read.
    dark_n = int(round(len(fields) * (0.02 + 0.13 * r)))
    dark = set(rnd.sample(range(len(fields)), dark_n))

    for i, f in enumerate(fields):
        if i in dark:
            continue
        # Most live fields sit on one or two documents; a small core is on enough
        # of them to cross the blast-radius threshold and weight its findings up.
        roll = rnd.random()
        hits = 1 if roll < 0.62 else (2 if roll < 0.88 else rnd.randint(3, min(8, n_docs)))
        refs.refs[f"{f.object_name}.{f.api_name}"] = hits
    return refs


def gen_personas(industry, objects, fields, r, rnd, flows):
    """Profiles, the screens they are given, and the rules and processes that
    constrain them.

    The estate used to carry one blanket permission set and nothing else, so the
    persona model — which reads profiles, layouts, flows, approvals and
    validation rules — was being fed a fifth of its inputs and every surface it
    produced came out the same shape.

    Degradation is the same principle the schema generator uses: start from the
    access a job actually needs, then let a messy org accumulate. A high defect
    ratio widens a persona's edit rights onto objects nobody built it a screen
    for, and narrows the share of each object its layout actually surfaces.
    Both are what fifteen years of "just give them access" looks like, and
    neither is a defect planted directly — the D4 rules have to find it.
    """
    present = set(objects)
    layouts, profiles, vrules, approvals = [], [], [], []

    by_object = {}
    for f in fields:
        by_object.setdefault(f.object_name, []).append(f.api_name)

    # A layout surfaces a share of the object, and the share falls as the org
    # gets messier: fields kept being added, the screen did not keep up. This is
    # the gap that makes "sees 34 of 61 fields" a sentence worth reading.
    share = max(0.25, 0.8 - 0.45 * r)
    for obj in objects:
        own = by_object.get(obj, [])
        if not own:
            continue
        shown = own[:max(1, int(len(own) * share))]
        layouts.append(md.LayoutMeta(
            api_name=f"{obj}-{obj} Layout", object_name=obj,
            fields=tuple(shown),
            actions=("Edit", "Clone") + (("Submit for Approval",)
                                         if rnd.random() > r else ())))
    layout_of = {l.object_name: l.api_name for l in layouts}
    flow_names = [f.api_name for f in flows]

    # An acquired instance runs on its own schema, so none of the parent's roles
    # match its objects — and skipping them all left it with a single blanket
    # integration permission set and no profiles at all, which reads as a broken
    # parse rather than as a separate business. It had its own people; they are
    # generated from its own objects.
    specs = enterprises.PERSONAS.get(industry, [])
    if not any(o in present for s in specs for o in s["edits"] + s["reads"]):
        own = [o for o in objects if o.endswith("__c")]
        specs = [{"api": "Legacy_Administrator", "label": "Legacy Administrator",
                  "edits": own, "reads": [], "laid_out": own[:1],
                  "deletes": own[:1]},
                 {"api": "Legacy_Operations", "label": "Legacy Operations",
                  "edits": own[:1], "reads": own[1:], "laid_out": own[:1]}]

    for spec in specs:
        edits = [o for o in spec["edits"] if o in present]
        reads = [o for o in spec["reads"] if o in present]
        if not edits and not reads:
            # An acquired instance on an unrelated schema never had the parent's
            # profiles. Emitting them anyway produced surfaces that edit nothing
            # and see nothing — four rows of noise per divergent org, and a
            # reviewer would rightly read them as a broken parse.
            continue
        laid_out = [o for o in spec.get("laid_out", spec["edits"]) if o in layout_of]

        # Accumulated access: rights on objects this role has no screen for.
        # Drawn from what the org actually has, so a small org cannot sprout
        # access to objects that do not exist in it.
        spare = [o for o in objects if o not in edits and o not in reads]
        rnd.shuffle(spare)
        edits = edits + spare[:int(len(spare) * r)]

        obj_perms = [md.ObjectPerm(object_name=o, allow_edit=True,
                                   allow_delete=o in spec.get("deletes", []))
                     for o in edits]
        obj_perms += [md.ObjectPerm(object_name=o) for o in reads if o not in edits]

        profiles.append(md.ProfileMeta(
            api_name=spec["api"], label=spec["label"],
            object_perms=obj_perms,
            layout_assignments=tuple(layout_of[o] for o in laid_out),
            # A role runs the automation its own job depends on, not all of it.
            flow_access=tuple(flow_names[:rnd.randint(0, min(3, len(flow_names)))]),
        ))

    for obj, rules in enterprises.VALIDATION_RULES.get(industry, {}).items():
        if obj not in present:
            continue
        for api, message in rules:
            vrules.append(md.ValidationRuleMeta(
                api_name=api, object_name=obj,
                # A deactivated rule still ships in the metadata and constrains
                # nobody. Messier orgs have more of them, and the persona model
                # already refuses to count them.
                active=rnd.random() > r * 0.3,
                error_message=message))

    for api, obj in enterprises.APPROVALS.get(industry, []):
        if obj in present:
            approvals.append(md.ApprovalProcessMeta(
                api_name=api, object_name=obj, label=api.replace("_", " "),
                active=True))

    return layouts, profiles, vrules, approvals


def gen_org_metadata(objects, fields, r, rnd, mode="Org",
                     dup_signal=True, report_metadata=True,
                     industry="") -> md.OrgMetadata:
    """Build the Flow / Apex / trigger / permission-set / report material for one org.

    These are the *same structures* the SFDX parsers produce, and the *same*
    real rule packs run over them — only the inputs are synthesised, scaled by
    the org's defect ratio. Bodies are real Apex text, so the DML-in-loop and
    recursion-guard heuristics genuinely fire, and the report references are real
    ReportRefs, so D1.UNREFERENCED_FIELD and the blast-radius weighting do too.

    `mode` and `dup_signal` decide what EVIDENCE this org has, not what score it
    gets. A Source-mode org gets no RecordStats at all — a directory carries no
    rows — so its D2 is Not Assessed. `dup_signal=False` models the org whose
    Name field is an auto-number: fill rate and staleness are measured, the
    duplicate probe has nothing groupable to run on, and D2 lands at 2/3
    coverage. `report_metadata=False` models the very common repo that simply
    does not commit its reports and dashboards: D1.UNREFERENCED_FIELD cannot run
    without them, so D1 comes out assessed at 5/6 — 83.3%, still over the bar
    and still in the composite, but no longer the flat 100% every dimension used
    to claim. None of the three is a fudge factor; all are conditions the real
    collector reports every day, and the coverage arithmetic is left to draw its
    own conclusion from them.
    """
    flows, apex, triggers, perms, stats = [], [], [], [], []

    # --- Flows: messier orgs document fewer of them and leave drafts around
    for i in range(rnd.randint(2, 4)):
        documented = rnd.random() > r
        flows.append(md.FlowMeta(
            api_name=f"{objects[0][:-3]}_Action{i + 1}",
            label=f"Action {i + 1}",
            description="Automates a step in the service process." if documented else "",
            process_type="AutoLaunchedFlow",
            status="Draft" if rnd.random() < r * 0.4 else "Active",
        ))
    if rnd.random() < r:                      # record-triggered flow -> collision risk
        flows.append(md.FlowMeta(
            api_name=f"{objects[0][:-3]}_AfterSave", label="After Save",
            description="Recalculates roll-ups after save.",
            process_type="AutoLaunchedFlow", status="Active",
            trigger_object=objects[0], record_trigger_type="CreateAndUpdate"))

    # --- Apex: invocable classes; clean orgs also ship tests
    for i in range(rnd.randint(1, 3)):
        # The index is part of the name, not just the object: with fewer objects
        # than iterations the clamp hands back the same object twice, and two
        # classes sharing a name means two identical findings — which collide on
        # one external id at load time.
        obj_for_cls = objects[min(i, len(objects) - 1)][:-3]
        cls = f"{obj_for_cls}Service" if i == 0 else f"{obj_for_cls}Service{i + 1}"
        labelled = rnd.random() > r
        label_part = '(label="Run ' + cls + '")' if labelled else ''
        apex.append(md.ApexClassMeta(api_name=cls, sharing="with sharing", body=(
            f"public with sharing class {cls} {{\n"
            f"    @InvocableMethod{label_part}\n"
            f"    public static void run(List<Id> ids) {{ }}\n}}\n")))
        if rnd.random() > r:                  # a test exists
            apex.append(md.ApexClassMeta(api_name=f"{cls}Test", body=(
                f"@isTest\nprivate class {cls}Test {{\n"
                f"    @isTest static void t() {{ {cls}.run(new List<Id>()); }}\n}}\n")))

    # --- Triggers: messy orgs get loops without guards, and doubled triggers
    for obj in objects[:max(1, int(len(objects) * min(1.0, r + 0.3)))]:
        base = obj[:-3]
        if rnd.random() < r:                  # unbulkified, unguarded
            body = (f"trigger {base}Trigger on {obj} (after insert, after update) {{\n"
                    f"    for ({obj} o : Trigger.new) {{\n"
                    f"        List<{obj}> rel = [SELECT Id FROM {obj} WHERE Id = :o.Id];\n"
                    f"        {obj} n = new {obj}();\n        insert n;\n    }}\n}}\n")
        else:                                 # guarded, delegates to a handler
            body = (f"trigger {base}Trigger on {obj} (after insert) {{\n"
                    f"    if ({base}Handler.hasRun) return;\n"
                    f"    {base}Handler.handle(Trigger.new);\n}}\n")
        triggers.append(md.ApexTriggerMeta(api_name=f"{base}Trigger", object_name=obj,
                                           events=["after insert"], body=body))
        if rnd.random() < r * 0.5:            # a second trigger on the same object
            triggers.append(md.ApexTriggerMeta(
                api_name=f"{base}AuditTrigger", object_name=obj, events=["before update"],
                body=f"trigger {base}AuditTrigger on {obj} (before update) {{\n"
                     f"    if ({base}Handler.hasRun) return;\n}}\n"))

    # --- Permission set for the agent identity
    user_perms = []
    if r > 0.55 and rnd.random() < 0.7:
        user_perms.append("ModifyAllData")
    if r > 0.3 and rnd.random() < 0.7:
        user_perms.append("ViewAllData")
    obj_perms = []
    for obj in objects[:max(1, int(len(objects) * r))]:
        obj_perms.append(md.ObjectPerm(object_name=obj, allow_edit=True,
                                       allow_delete=rnd.random() < r,
                                       modify_all=rnd.random() < r * 0.5,
                                       view_all=rnd.random() < r * 0.5))
    perms.append(md.PermissionSetMeta(api_name="Agent_Integration", label="Agent Integration",
                                      user_permissions=user_perms, object_perms=obj_perms))

    # --- Record-level signal. It exists only where the scan actually reached an
    # org: a Source-mode scan has no rows to measure, and inventing them here
    # would score D2 off evidence the mode cannot produce.
    if mode != "Source":
        for obj in objects[:3]:
            stats.append(md.RecordStats(
                object_name=obj,
                fill_rate=max(0.05, 1 - r * rnd.uniform(0.5, 1.25)),
                stale_ratio=min(0.95, r * rnd.uniform(0.4, 1.1)),
                # Left at the benign default when unmeasurable, and named in
                # `unavailable` so nothing downstream reads 0.0 as "no
                # duplicates" — the trap RecordStats documents.
                duplicate_rate=(min(0.5, r * rnd.uniform(0.05, 0.35))
                                if dup_signal else 0.0),
                record_count=rnd.randint(2_000, 40_000),
                sampled_fields=tuple(f.api_name for f in fields[:4]
                                     if f.object_name == obj),
                duplicate_key="Name" if dup_signal else "",
                unavailable=() if dup_signal else ("duplicate_rate",),
                notes=() if dup_signal else (
                    "the Name field is an auto-number, so no duplicate probe "
                    "could group on it",),
            ))

    # Last, so adding it left every draw above unchanged and the D2–D5 findings
    # this portfolio already ships stayed byte-identical.
    refs = gen_report_refs(fields, r, rnd) if report_metadata else md.ReportRefs()

    # After every draw above, so adding personas left the existing D1-D5 corpus
    # byte-identical — the same discipline the report references were added under.
    layouts, profiles, vrules, approvals = gen_personas(
        industry, objects, fields, r, rnd, flows)

    meta = md.OrgMetadata(flows=flows, apex=apex, triggers=triggers,
                          permission_sets=perms, record_stats=stats,
                          report_refs=refs, layouts=layouts, profiles=profiles,
                          validation_rules=vrules, approval_processes=approvals)
    if stats and not dup_signal:
        # The explicit verdict an org collector would have logged. Inference
        # would reach the same answer from `unavailable`; the log is what carries
        # the REASON into the dimension record, so the dashboard can say why D2
        # is only partly assessed instead of just that it is.
        meta.record_signal(md.SIGNAL_DUPLICATES, md.UNAVAILABLE,
                           "the Name field is an auto-number on every measured "
                           "object, so this org offers no duplicate signal")
    return meta


# --------------------------------------------------- enterprise generation

def _fld(obj, api, ftype, desc):
    return Field(object_name=obj, api_name=api, label=_label(api),
                 type=ftype, description=desc, help_text="", path="")


# The last two fields of each object stand for "added recently". `behind` orgs
# were refreshed before they landed, so this is what they are missing.
_RECENT_PER_OBJECT = 2


def base_schema(ent) -> list:
    """The enterprise's schema as designed — before the years happen to it."""
    out = []
    for obj, fields in ent["objects"].items():
        for api, ftype, desc in fields:
            out.append(_fld(obj, api, ftype, desc))
    for api, ftype in enterprises.MANAGED_FIELDS[ent["industry"]]:
        # Hung off the first object; not ours to fix, and the rules know it.
        out.append(_fld(list(ent["objects"])[0], api, ftype, ""))
    return out


def apply_drift(fields, drift, ent, rnd) -> list:
    """Make an org differ from its estate the way a real sandbox does.

    This is the point of the whole fixture: two orgs that differ for a
    *reason* — unreleased work, a stale refresh, a hotfix that never went back —
    are what makes a difference between them worth reporting.
    """
    fields = list(fields)
    if drift == "behind":
        recent = set()
        for obj in {f.object_name for f in fields}:
            of = [f for f in fields if f.object_name == obj]
            recent.update(f.api_name for f in of[-_RECENT_PER_OBJECT:])
        return [f for f in fields if f.api_name not in recent]
    if drift == "ahead":
        obj = rnd.choice(sorted({f.object_name for f in fields}))
        for i in range(rnd.randint(3, 6)):
            fields.append(_fld(obj, f"Rework_Stage_{i+1}__c", "Text",
                               "Added by the in-flight rework; not yet released."))
        return fields
    if drift == "hotfix":
        obj = rnd.choice(sorted({f.object_name for f in fields}))
        for i in range(rnd.randint(2, 4)):
            fields.append(_fld(obj, f"Hotfix_Override_{i+1}__c", "Text", ""))
        return fields
    if drift == "divergent":
        # An acquisition: the same business, on a data model nobody reconciled.
        #
        # What diverges is the model — different objects, holding the same
        # concepts. The fields keep their own names and their own descriptions,
        # because the acquired company documented its system as well or as badly
        # as anyone else, and `degrade` is what decides how badly.
        #
        # This used to rename every field to `*_Old__c` and drop every
        # description. Both were wrong in the same way: they described the org
        # from the parent's point of view. No company names its own fields
        # "Old", and an org with literally zero descriptions produced a semantic
        # density of exactly 0.0 — a number that reads as "not measured" rather
        # than as a fact about the org.
        out = []
        for obj, defs in list(ent["objects"].items())[:2]:
            lobj = f"Legacy_{obj}"
            for api, ftype, desc in defs:
                out.append(_fld(lobj, api, ftype, desc))
        return out
    return fields


def _unique(name, used):
    """An org cannot hold two fields with the same API name — and if the
    generator emits one, the rules fire twice on it and two findings collapse
    onto one external id at load time. Suffix until it is genuinely new."""
    if name not in used:
        used.add(name)
        return name
    for n in range(2, 40):
        alt = name.replace("__c", f"_{n}__c")
        if alt not in used:
            used.add(alt)
            return alt
    return None


def degrade(fields, ratio, rnd) -> list:
    """Fifteen years of unreviewed change, applied to a sensible schema.

    Generating defects directly produces noise; degrading a considered schema
    produces debt — which is what the rules are meant to find.
    """
    out, by_obj = [], {}
    for f in fields:
        by_obj.setdefault(f.object_name, []).append(f)
    used = {(f.object_name, f.api_name) for f in fields}

    for obj, fs in by_obj.items():
        for f in fs:
            if f.api_name.count("__") > 1 or "__" in f.api_name.split("__c")[0][:12] and "_" not in f.api_name[:3]:
                pass
            # The bands are set so the share of descriptions that survive intact
            # is about (1 - ratio): a 0.95 org keeps almost none, a 0.12 one
            # keeps nearly all. The restate band used to be a fixed 0.15 * ratio
            # wide, which left even the worst possible org with 43% of its
            # descriptions pristine — so semantic density could not fall below
            # about 0.67 anywhere in the corpus, and the metric barely moved
            # between an org scoring 21 and one scoring 95.
            roll = rnd.random()
            if roll < ratio * 0.45 and f.description:
                out.append(_fld(obj, f.api_name, f.type, ""))            # description lost
            elif roll < ratio and f.description:
                out.append(_fld(obj, f.api_name, f.type, f.label))       # restates the label
            else:
                out.append(f)
        # Structural debt, sized by how ungoverned the org is.
        n = len(fs)
        for i in range(int(n * ratio * 0.18)):
            src = rnd.choice(fs)
            stem = src.api_name.replace("__c", "")
            name = _unique(f"{stem[:12]}_Cd__c", {n for o, n in used if o == obj})
            if name:
                used.add((obj, name))
                out.append(_fld(obj, name, "Text", ""))                   # cryptic twin
        if rnd.random() < ratio:
            base = rnd.choice(["Contact", "Adjuster", "Signatory", "Reviewer"])
            for i in range(rnd.randint(2, 4)):
                name = _unique(f"{base}{i+1}_Ref__c", {n for o, n in used if o == obj})
                if name:
                    used.add((obj, name))
                    out.append(_fld(obj, name, "Text", ""))               # numbered family
    return out


def rewind(fields, quarters, rnd):
    """The same org, `quarters` quarters ago.

    History used to be generated by re-running the whole generator with a worse
    defect ratio and the same seed. That produces an org that *resembles* this
    one, not this one — the extra draws shift every subsequent draw, so fields
    appeared in one quarter, vanished in the next and came back in the third.
    Seventeen components in one org's newest scan had never existed in the scan
    before it, while its score improved. No one can read that as remediation.

    It also quietly broke the thing built on top of it. Survival counts how many
    consecutive scans reported the same defect; over a re-rolled history a
    finding "surviving" is partly the RNG landing the same way twice, so the
    number measured coincidence as much as neglect.

    So the past is derived from the present instead. Today's schema is the
    floor: every field that exists now existed then, and the past additionally
    carries the debt that has since been fixed —

        descriptions that have since been written  (stripped going back)
        fields that have since been retired        (re-added going back)

    which makes today's field set a subset of every earlier one, the burn-down
    monotonic, and a finding that disappears something that was actually fixed.
    """
    if quarters <= 0:
        return list(fields)

    # The orderings below are drawn ONCE per org and then sliced by `quarters`,
    # so each quarter's debt is a superset of the next one's. Drawing them per
    # quarter instead — the obvious way to write this — leaves a field
    # documented three quarters ago and undocumented two quarters ago, and the
    # finding reappears going forward: the same flicker this function exists to
    # remove, just moved one level down.
    out = list(fields)
    documented = [i for i, f in enumerate(out) if f.description]
    rnd.shuffle(documented)
    for i in documented[:int(len(documented) * 0.09 * quarters)]:
        out[i] = _fld(out[i].object_name, out[i].api_name, out[i].type, "")

    # Fields retired since. Shaped like what the backlog actually tickets for
    # removal, so the fields that used to be there are the ones the playbook
    # would have said to retire.
    by_obj = {}
    for f in fields:
        by_obj.setdefault(f.object_name, []).append(f)
    for obj, fs in sorted(by_obj.items()):
        used = {f.api_name for f in out if f.object_name == obj}
        stems = [f.api_name.replace("__c", "")[:12] for f in fs]
        rnd.shuffle(stems)
        for stem in stems[:int(len(fs) * 0.05 * quarters)]:
            name = _unique(f"{stem}_Old__c", used)
            if name:
                used.add(name)
                out.append(_fld(obj, name, "Text", ""))
    return out


def rewind_metadata(meta, fields, quarters, rnd):
    """Today's org metadata, carrying the debt that has since been paid off.

    The same argument as rewind(): a past quarter generated by re-running the
    generator at a worse ratio is a different org, and the churn shows. D4
    findings went 8, 8, 7, 8 across one org's own history — a persona losing a
    grant and getting it back — and D1.UNREFERENCED_FIELD flickered because the
    reports were re-rolled too, so a field nobody reported on in April was
    reported on in January and unreported again in October.

    Report references are the sharpest case, and they fix themselves once the
    history is derived: they are simply carried over unchanged. Every field that
    exists today existed then, so its references did too — and the fields
    rewind() adds back are the ones that were retired, which have no references
    precisely because that is why they were retired.
    """
    import copy
    past = copy.deepcopy(meta)
    past.field_count = len(fields)
    past.report_refs = meta.report_refs        # carried, not re-rolled

    n = max(1, quarters)

    # Flows documented since, and drafts since cleaned up.
    undocumented = [i for i, f in enumerate(past.flows) if f.description]
    rnd.shuffle(undocumented)
    for i in undocumented[:min(len(undocumented), n)]:
        past.flows[i].description = ""
    for i in range(min(len(past.flows), n)):
        past.flows[i].status = "Draft"

    # Tests written since: a class that has one today did not always.
    tests = {c.api_name for c in past.apex if c.api_name.endswith("Test")}
    droppable = sorted(tests)
    rnd.shuffle(droppable)
    for name in droppable[:min(len(droppable), n)]:
        past.apex = [c for c in past.apex if c.api_name != name]

    # Duplicate triggers since consolidated — the D5 story the playbook tells.
    if past.triggers:
        for k in range(n):
            src = past.triggers[k % len(past.triggers)]
            past.triggers.append(md.ApexTriggerMeta(
                api_name=f"{src.object_name[:-3]}Legacy{k + 1}Trigger",
                object_name=src.object_name, events=["after insert"],
                body=f"trigger {src.object_name[:-3]}Legacy{k + 1}Trigger on "
                     f"{src.object_name} (after insert) {{\n"
                     f"    for ({src.object_name} o : Trigger.new) {{ insert o; }}\n}}\n"))

    # Access narrowed since: a persona edited more objects before someone
    # reviewed it. Widened here, so the D4 count falls forward in time instead
    # of wobbling.
    present = sorted({f.object_name for f in fields})
    for prof in past.profiles:
        held = {op.object_name for op in prof.object_perms}
        spare = [o for o in present if o not in held]
        rnd.shuffle(spare)
        for obj in spare[:n]:
            prof.object_perms.append(md.ObjectPerm(object_name=obj, allow_edit=True))
    return past


def gen_enterprise_org(ent, org_name, org_type, ratio, drift, seed):
    rnd = random.Random(seed)
    fields = apply_drift(base_schema(ent), drift, ent, rnd)
    return degrade(fields, ratio, rnd)


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
# defect_ratio drives the readiness band; sizes drive the finding volume — and
# therefore the record count, so raising them is a RECORD_BUDGET decision. The
# heaviest orgs were trimmed when D1.UNREFERENCED_FIELD started firing; the
# bands are set by the ratios, so trimming volume left every band in place.

SPECS = [
    # Ready / Conditionally Ready — clean, modern orgs
    ("Northwind Robotics",       "Mfg",     50, 0.06, 2, "Source"),
    ("Cobalt Analytics",         "Saas",    52, 0.10, 2, "Source"),
    ("Vireo Health Cloud",       "Health",  58, 0.16, 2, "Org"),
    ("Meridian Wealth",          "Fin",     66, 0.22, 3, "Hybrid"),
    ("Solstice Retail Group",    "Retail",  74, 0.28, 3, "Source"),
    # Foundational Work Required — mid-life orgs carrying real debt
    ("Anchor Freight Systems",   "Logi",    80, 0.42, 3, "Org"),
    ("Bluepeak Telecom",         "Telco",   84, 0.46, 3, "Source"),
    ("Cascade Insurance",        "Ins",     84, 0.50, 3, "Org"),
    ("Harborline Bank",          "Fin",     88, 0.52, 3, "Hybrid"),
    ("Pinnacle Energy",          "Energy",  84, 0.54, 3, "Source"),
    ("Trailhead Education",      "Edu",     80, 0.48, 3, "Org"),
    ("Fathom Media Networks",    "Media",   84, 0.49, 3, "Source"),
    # Not Ready — old, heavily-accreted enterprise orgs
    ("Gateway Health Alliance",  "Health",  84, 0.74, 3, "Org"),
    ("Irongate Manufacturing",   "Mfg",     88, 0.82, 4, "Source"),
    ("Summit Telecom Legacy",    "Telco",   88, 0.86, 4, "Org"),
    ("Delta Logistics Intl",     "Logi",    84, 0.80, 4, "Hybrid"),
    ("Crownpoint Insurance",     "Ins",     88, 0.84, 4, "Org"),
    ("Old Mill Bancorp",         "Fin",     88, 0.88, 4, "Source"),
    ("Redwood Utilities",        "Energy",  84, 0.78, 3, "Org"),
    ("Beacon Public Sector",     "Gov",     88, 0.82, 4, "Source"),
    # Time series — one org remediating over four quarters (burn-down)
    ("Helios Airlines · 2025-Q1", "Travel",  88, 0.84, 4, "Org"),
    ("Helios Airlines · 2025-Q2", "Travel",  88, 0.58, 4, "Org"),
    ("Helios Airlines · 2025-Q3", "Travel",  88, 0.36, 4, "Org"),
    ("Helios Airlines · 2025-Q4", "Travel",  88, 0.18, 4, "Org"),
]


# Orgs whose primary object uses an auto-number Name. The duplicate probe has
# nothing groupable to run on, so D2 is measured for fill rate and staleness and
# not for duplicates — 2 of 3 rules, 66.7%, under the 70% bar. Named here rather
# than rolled at random so a reader can see which orgs the portfolio's two
# Partially Assessed dimensions belong to and check the arithmetic.
AUTONUMBER_NAME_ORGS = frozenset({"Meridian Insurance · gladstone",
                                  "Northgate Bank · legacy-core"})

# Source-mode orgs whose repository does not commit its reports and dashboards —
# the ordinary case, not an exotic one. With no report metadata to check against,
# D1.UNREFERENCED_FIELD cannot run and must not: an unused field and an
# unobserved one look identical from there. D1 is assessed at 83.3%, and the
# dimension record names the signal that cost it the other 16.7%.
NO_REPORT_METADATA_ORGS = frozenset({"Meridian Insurance · dev-core"})


def build_portfolio():
    """Returns (scans, orgs) — the loadable records, and (name, findings) pairs
    kept as raw Findings so the backlog emitter can gate them itself.

    Walks the estates rather than a flat list of companies. An org belongs to an
    enterprise, carries its place in the promotion path, and is derived from that
    estate's base schema — so two orgs differing is a fact about one business
    rather than a coincidence between two unrelated ones.
    """
    scans, orgs = [], []
    i = -1
    # name -> (index into `scans`, index into `orgs`) so drift can be folded back
    # into the right records once the whole estate has been generated.
    pending = {}
    for ent in enterprises.ENTERPRISES:
        snapshots = []
        for spec in ent["orgs"]:
            (org_name, org_type, ratio, drift, refreshed, notes) = spec[:6]
            m, history = (spec[6], spec[7]) if len(spec) > 6 else ("Org", 0)
            i += 1
            name = enterprises.org_display_name(ent["name"], org_name)
            fields = gen_enterprise_org(ent, org_name, org_type, ratio, drift, seed=1000 + i)
            objects = sorted({f.object_name for f in fields})
            # Built before the D1 rules run: the report references gate
            # D1.UNREFERENCED_FIELD and weight every other D1 finding.
            org_meta = gen_org_metadata(objects, fields, ratio, random.Random(5000 + i),
                                        mode=m,
                                        dup_signal=name not in AUTONUMBER_NAME_ORGS,
                                        report_metadata=name not in NO_REPORT_METADATA_ORGS,
                                        industry=ent["industry"])
            # D1's own signal. metadata.py cannot see Field — it is owned by the
            # scanner — so without this the registry reports D1 as having no schema
            # to read and the portfolio's strongest dimension scores nothing.
            org_meta.field_count = len(fields)
            code_tokens = scanner.code_identifiers(org_meta)
            findings = scanner.all_d1_findings(fields, org_meta.report_refs, code_tokens)
            findings.extend(rules_ext.all_findings(org_meta))   # the real D2–D5 packs
            personas = persona_mod.build_personas(org_meta)
            findings.extend(persona_mod.persona_findings(personas))
            blast = persona_mod.blast_index(org_meta, personas)
            # The same withholding a real scan applies: a rule whose signals were
            # never collected does not get to report. On this corpus it is a no-op
            # for every org — the generator only produces evidence the mode can
            # actually carry — and it is here so it stays a no-op, loudly.
            findings, withheld = org_meta.drop_blocked(findings)
            if withheld:
                # Said out loud rather than swallowed: it would mean the generator
                # produced a finding from evidence it also declined to generate.
                print(f"  note: {len(withheld)} finding(s) withheld for {name} — "
                      f"{sorted({f.rule_id for f in withheld})}")
            # The same reference evidence goes to the scan record, so the payload
            # projection retires exactly the fields the backlog tickets for retirement.
            scans.append(scan_result.build(fields, findings, name, scan_mode=m,
                                           assessed_dims=frozenset({"D1"} | org_meta.assessable_dims()),
                                           report_refs=org_meta.report_refs,
                                           code_tokens=code_tokens,
                                           coverage=org_meta.coverage(),
                                           org_type=org_type, blast=blast,
                                           personas=personas,
                                           enterprise=enterprises.enterprise_record(ent),
                                           org_overrides={"last_refreshed": refreshed,
                                                          "notes": notes}))
            orgs.append((name, findings))
            snapshots.append(drift_mod.snapshot_from(name, org_type, fields, org_meta))
            pending[name] = (len(scans) - 1, len(orgs) - 1)

            # Prior quarters for orgs that carry a history. Same org, earlier
            # date, more debt — remediation running backwards from today, which
            # is what makes a burn-down readable rather than a single number.
            for q in range(1, history + 1):
                # Count in months and derive the date, rather than adjusting
                # month and year separately: subtracting three months from a Q1
                # date underflows, and the naive version put the oldest scan in
                # the future, which reversed the whole series.
                total = (_NOW.year * 12 + _NOW.month - 1) - 3 * q
                past = _NOW.replace(year=total // 12, month=total % 12 + 1, day=1)
                worse = min(0.97, ratio + 0.07 * q)
                # Both derived from today, not re-rolled: see rewind() and
                # rewind_metadata(). `worse` still sets the org's overall defect
                # level for anything that reads it, but nothing that a rule sees
                # is generated from a fresh draw any more.
                pf = rewind(fields, q, random.Random(9000 + i))
                pm = rewind_metadata(org_meta, pf, q, random.Random(9000 + i))
                pct = scanner.code_identifiers(pm)
                pfind = scanner.all_d1_findings(pf, pm.report_refs, pct)
                pfind.extend(rules_ext.all_findings(pm))
                # Every rule the current scan runs, or the history is not
                # comparable with it: a past scan missing the persona pack scores
                # better than today for a reason that is not remediation, and the
                # burn-down reads as the org getting worse.
                ppersonas = persona_mod.build_personas(pm)
                pfind.extend(persona_mod.persona_findings(ppersonas))
                pblast = persona_mod.blast_index(pm, ppersonas)
                pfind, _ = pm.drop_blocked(pfind)
                scans.append(scan_result.build(
                    pf, pfind, name, scan_mode=m,
                    assessed_dims=frozenset({"D1"} | pm.assessable_dims()),
                    report_refs=pm.report_refs, code_tokens=pct,
                    coverage=pm.coverage(), now=past, org_type=org_type, blast=pblast,
                    personas=ppersonas,
                    enterprise=enterprises.enterprise_record(ent),
                    org_overrides={"last_refreshed": refreshed, "notes": notes}))
        # Drift is an estate-level question: it needs every org in the estate,
        # so it runs once they all exist rather than per org as they are built.
        for org_name, dfs in drift_mod.compare_estate(snapshots).items():
            si, oi = pending[org_name]
            orgs[oi] = (org_name, orgs[oi][1] + dfs)
            scans[si]["findings"].extend(
                scan_result.finding_rows(dfs, scans[si]["scan"]["external_scan_id"]))
    # Last, and after drift: survival is counted over every finding a scan
    # reported, and a drift finding added afterwards would otherwise be the one
    # kind of defect that could never be seen to persist.
    lifecycle.annotate_portfolio(scans)
    return scans, orgs


# ------------------------------------------------------ portfolio backlog

# The per-org CSV is written by backlog.write_csv and has no org column, because
# a single-org export does not need one. Merged across 24 orgs it does, so this
# export is backlog.BACKLOG_COLUMNS with the org prepended — derived from that
# list, never re-typed, so the two exports cannot drift apart.
ORG_COLUMN = "Target Org"
PORTFOLIO_COLUMNS = [ORG_COLUMN] + backlog.BACKLOG_COLUMNS


def _count_epics(rows) -> int:
    """Epic rows are scaffolding, not work — counted apart from the tickets so
    neither number silently absorbs the other (backlog.count_tickets is the
    matching side of this)."""
    return sum(1 for r in rows if r.get("Issue Type") == "Epic")


def write_portfolio_backlog(orgs, path) -> tuple:
    """Write ONE Jira-importable CSV covering every org in the portfolio.

    Reuses backlog.to_rows verbatim — same §4.6 gate, same columns, same epic
    clustering, same external ids — so a consultant importing the merged file
    gets exactly the rows the per-org exports would have produced, without
    merging 24 files by hand. The file keeps to_rows' structure: within each
    org, every epic is followed immediately by its own children, so the merged
    export reads top-down as org -> epic -> tasks rather than as ~1,900 loose
    tickets.

    Each org is serialised with its own name as the scan source, which is what
    keeps 24 orgs apart in one file:

      - task external ids hash the source, so two orgs' identical findings get
        different ids and cannot collide on upsert;
      - epic external ids hash (epic, source) for the same reason;
      - Epic Name is org-qualified ("Retire unreferenced fields — Old Mill
        Bancorp"). Jira keys epics by name, so unqualified names would collapse
        every org's copy of an epic into one and hang 24 orgs' children off it.

    Returns (epic_count, ticket_count, observations_held_back).
    """
    rows, observations = [], 0
    for name, findings in orgs:
        org_rows, obs = backlog.to_rows(findings, name)
        for row in org_rows:
            row[ORG_COLUMN] = name
        rows.extend(org_rows)
        observations += obs

    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=PORTFOLIO_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return _count_epics(rows), backlog.count_tickets(rows), observations


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--backlog", default=None,
                    help="write ONE portfolio-wide Jira-importable CSV covering "
                         "every org — epics followed by their child tasks, each "
                         "row tagged with the org it came from (threshold-gated: "
                         "severity>=Medium AND confidence>=Medium)")
    a = ap.parse_args()

    scans, orgs = build_portfolio()
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"scans": scans}, fh, indent=2)

    total_f = sum(len(s["findings"]) for s in scans)
    total_d = sum(len(s["dimensions"]) for s in scans)
    records = len(scans) + total_f + total_d
    fields = sum(s["scan"]["components_scanned"] for s in scans)
    unref = sum(1 for s in scans for f in s["findings"]
                if f["rule_id"] == "D1.UNREFERENCED_FIELD")
    bands = {}
    for s in scans:
        b = s["scan"]["readiness_band"]
        bands[b] = bands.get(b, 0) + 1
    print(f"wrote {a.out}")
    print(f"  scans:      {len(scans)}")
    print(f"  fields:     {fields}")
    print(f"  findings:   {total_f}  ({unref} D1.UNREFERENCED_FIELD)")
    print(f"  dimensions: {total_d}")
    # Portfolio-wide grounding payload. Printed because it is the headline the
    # landing page reports, and a silent regression in it is otherwise invisible
    # until someone opens the dashboard. Estimates, not billed tokens.
    cur = sum(s["scan"]["est_grounding_tokens"] for s in scans)
    rem = sum(s["scan"]["est_remediated_tokens"] for s in scans)
    print(f"  payload:    {cur:,} est. grounding tokens -> {rem:,} after the D1 "
          f"plays land — {((1 - rem / cur) * 100) if cur else 0:.1f}% is dead "
          f"weight removable without losing information")
    for key in density.REMOVABLE_KEYS:
        n = sum(s["scan"]["est_removable_tokens"][key] for s in scans)
        print(f"                {n:>6,}  {key}")
    # The load target is a Developer Edition org: 2 KB per record, ~5 MB total.
    print(f"  records:    {records} of {RECORD_BUDGET} budgeted "
          f"— {records * RECORD_KB / 1024:.2f} MB at {RECORD_KB} KB/record")
    print(f"  bands:      {bands}")
    # Coverage is generated, not asserted — printed here so a change in what the
    # synthetic orgs can evidence shows up in the run that produced it, rather
    # than being discovered in the dashboard.
    statuses = {}
    for s in scans:
        for d in s["dimensions"]:
            key = (d["dimension"][:2], d["assessment_status"], d["rule_coverage"])
            statuses[key] = statuses.get(key, 0) + 1
    print("  coverage:")
    for (code, status, pct), n in sorted(statuses.items()):
        print(f"                {code}  {status:<20} {pct:>5.1f}%  {n:>2} org(s)")
    if records > RECORD_BUDGET:
        # Said out loud here rather than discovered halfway through a bulk load,
        # which leaves the org holding a partial portfolio.
        print(f"  WARNING:    over the record budget by {records - RECORD_BUDGET} "
              f"— trim SPECS sizes before loading")

    if a.backlog:
        epics, tickets, observations = write_portfolio_backlog(orgs, a.backlog)
        # Tickets and epics are reported apart: "backlog items" has always meant
        # findings that became work, and folding the epic scaffolding into that
        # number would inflate the size of the engagement on paper.
        print(f"\nwrote {a.backlog} — {tickets} backlog item(s) in {epics} "
              f"epic(s) across {len(orgs)} orgs, {observations} observation(s) "
              f"held back by the §4.6 gate (severity>=Medium AND "
              f"confidence>=Medium)")
        print(f"  {epics + tickets} CSV row(s): within each org, every epic is "
              f"followed by its own children, and Epic Names are org-qualified "
              f"so two orgs' epics cannot merge on import")

    print("\n  per-scan:")
    for s in scans:
        sc = s["scan"]
        print(f"    {sc['composite_score']:>3} {sc['readiness_band']:<26} "
              f"{len(s['findings']):>4} findings  {sc['target_org']}")


if __name__ == "__main__":
    main()
