#!/usr/bin/env python3
"""
OrgIQ backlog emitter — turn scanner Findings into a Jira-importable CSV.

Implements EMIT-2 (threshold-gated backlog conversion) and EMIT-3 (Jira CSV
emitter) from the PRD. Standard library only.

Design, straight from PRD §4.6:

  - **Threshold-gated emission.** Every finding is recorded, but only findings
    meeting `severity >= Medium AND confidence >= Medium` auto-emit as backlog
    items. Everything else is an *observation*, reported but not ticketed.
    Without this gate a large org produces a four-thousand-ticket dump nobody
    imports.

  - **Idempotency.** Each row carries a deterministic External ID
    `hash(rule_id + component + source)`. Re-importing updates the same ticket
    instead of duplicating it — this is what turns a one-off audit into a
    trackable burn-down.

  - **Findings cluster into epics before emission** (PRD §4.6). Here each rule
    becomes an epic ("Add missing field descriptions"), and its findings are
    child tasks. Jira picks this up via the `Epic Name` column.

Effort points come from a PROVISIONAL calibration table (PRD §11 EMIT-7,
risk register §8). They are honest guesses until real engagement data exists;
the CSV header and the report both say so.
"""

import csv
import hashlib

# --------------------------------------------------------------- gate

_SEV_RANK = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}
_CONF_RANK = {"High": 3, "Medium": 2, "Low": 1}

# PRD §4.6: severity >= Medium AND confidence >= Medium
_GATE_SEV = _SEV_RANK["Medium"]
_GATE_CONF = _CONF_RANK["Medium"]


def emits_to_backlog(finding) -> bool:
    """True if the finding clears the §4.6 emission gate."""
    return (_SEV_RANK.get(finding.severity, 0) >= _GATE_SEV
            and _CONF_RANK.get(finding.confidence, 0) >= _GATE_CONF)


# severity -> Jira priority
_PRIORITY = {
    "Critical": "Highest",
    "High": "High",
    "Medium": "Medium",
    "Low": "Low",
}

# ------------------------------------------------ per-rule playbook
#
# One entry per rule_id. `epic` groups tickets; `points` is the PROVISIONAL
# effort estimate; `remediation` is the ordered fix; `acceptance` is how you
# verify it. Kept as data, not code, so a non-engineer can review and tune it.

_UNKNOWN = {
    "epic": "Grounding quality findings",
    "points": 3,
    "remediation": "1. Investigate the flagged component.\n"
                   "2. Apply the appropriate grounding fix.\n"
                   "3. Re-scan to confirm the finding clears.",
    "acceptance": "Re-scan no longer reports this finding for the component.",
}

_PLAYBOOK = {
    "D1.MISSING_DESCRIPTION": {
        "epic": "Add missing field descriptions",
        "points": 1,
        "remediation": (
            "1. Determine the field's business meaning from its usage "
            "(page layouts, reports, automation that reads it).\n"
            "2. Add a <description> stating what it holds and when it is set; "
            "add matching inline help text.\n"
            "3. Redeploy the field metadata."
        ),
        "acceptance": (
            "Field has a non-empty description that states its business "
            "meaning (not just a restatement of the label). Re-scan reports "
            "no D1.MISSING_DESCRIPTION for this field."
        ),
    },
    "D1.LOW_INFO_DESCRIPTION": {
        "epic": "Replace label-restating field descriptions",
        "points": 1,
        "remediation": (
            "1. Confirm the field's actual meaning; the current description "
            "only echoes the label and adds no disambiguating information.\n"
            "2. Rewrite it to say what distinguishes this field from similar "
            "ones (unit, source system, when populated, valid values).\n"
            "3. Redeploy."
        ),
        "acceptance": (
            "Description carries information beyond the label. Re-scan reports "
            "no D1.LOW_INFO_DESCRIPTION for this field."
        ),
    },
    "D1.CRYPTIC_API_NAME": {
        "epic": "Clarify cryptic field names",
        "points": 3,
        "remediation": (
            "1. Confirm the field's meaning with an owner; cryptic / "
            "abbreviated names cannot be grounded reliably.\n"
            "2. Cheap win first: add a clear description and inline help text.\n"
            "3. If renaming, use a dependency-safe rename — check formulas, "
            "flows, Apex, reports, and integrations before changing the API "
            "name, and stage the change."
        ),
        "acceptance": (
            "Field is unambiguous to a reader with no tribal knowledge — via a "
            "clear description and/or a readable API name. Re-scan reports no "
            "D1.CRYPTIC_API_NAME for this field."
        ),
    },
    "D1.NUMBERED_FAMILY": {
        "epic": "Resolve numbered field families",
        "points": 5,
        "remediation": (
            "1. Review whether the repeating numbered group should instead be "
            "a child object / related list (N rows, not N columns).\n"
            "2. If the flat design must stay, give each member a distinct "
            "description so a retriever can tell them apart.\n"
            "3. Retire unused members via a dependency-safe deprecation."
        ),
        "acceptance": (
            "Either the group is modelled as a related list, or each member "
            "carries a distinct, disambiguating description. Re-scan reports "
            "no D1.NUMBERED_FAMILY for this object, or a smaller family."
        ),
    },
    "D1.SEMANTIC_DUPLICATE": {
        "epic": "Consolidate duplicate fields",
        "points": 3,
        "remediation": (
            "1. Confirm the fields are true duplicates by comparing data and "
            "usage — near-identical names can still mean different things.\n"
            "2. Choose the canonical field.\n"
            "3. Migrate data and references to it, then deprecate the others "
            "via a dependency-safe removal."
        ),
        "acceptance": (
            "One canonical field remains; duplicates are deprecated with data "
            "and references migrated. Re-scan reports no D1.SEMANTIC_DUPLICATE "
            "for this cluster."
        ),
    },
}


def _play(rule_id: str) -> dict:
    return _PLAYBOOK.get(rule_id, _UNKNOWN)


# ---------------------------------------------------------- row shaping

def _component_type(finding) -> str:
    # Aggregate findings look like "Object [N fields]"; field findings like
    # "Object.Field__c". Everything the D1 spike emits is about custom fields.
    return "CustomField group" if "[" in finding.component else "CustomField"


def _external_id(finding, source: str) -> str:
    """Deterministic, idempotent id (PRD §4.6). Source stands in for org_id
    in source mode, so re-scanning the same repo yields the same id."""
    raw = f"{finding.rule_id}|{finding.component}|{source}"
    return "OIQ-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _summary(finding) -> str:
    return f"[{finding.rule_id}] {finding.component}: {finding.evidence}"[:200]


def _description(finding, source: str) -> str:
    play = _play(finding.rule_id)
    lines = [
        f"Rule: {finding.rule_id} ({finding.dimension} — Grounding Quality)",
        f"Severity: {finding.severity}   Confidence: {finding.confidence}",
        f"Component: {finding.component}  [{_component_type(finding)}]",
        "",
        f"Evidence: {finding.evidence}",
    ]
    if finding.detail:
        lines.append(f"Detail: {finding.detail}")
    lines += [
        "",
        "Remediation:",
        play["remediation"],
        "",
        f"Acceptance criteria: {play['acceptance']}",
        "",
        f"Blast radius: n/a (source mode — no dependency graph)",
        f"Source: {source}",
        f"Effort points are PROVISIONAL (uncalibrated, PRD §8/§11).",
    ]
    return "\n".join(lines)


# Column order chosen to map cleanly in Jira's CSV importer.
BACKLOG_COLUMNS = [
    "External ID",      # -> map to a stable text field for idempotent re-import
    "Issue Type",
    "Epic Name",
    "Summary",
    "Priority",
    "Story Points (provisional)",
    "Labels",
    "Salesforce Component",
    "Component Type",
    "Rule ID",
    "Dimension",
    "Severity",
    "Confidence",
    "Rule Maturity",
    "Description",
]


def to_rows(findings, source: str):
    """Split findings into (backlog_rows, observation_count).

    backlog_rows are dicts keyed by BACKLOG_COLUMNS, ordered most-severe first.
    """
    gated = [f for f in findings if emits_to_backlog(f)]
    observations = len(findings) - len(gated)

    def sort_key(f):
        return (-_SEV_RANK.get(f.severity, 0), -_CONF_RANK.get(f.confidence, 0),
                f.rule_id, f.component)

    rows = []
    for f in sorted(gated, key=sort_key):
        play = _play(f.rule_id)
        rows.append({
            "External ID": _external_id(f, source),
            "Issue Type": "Task",
            "Epic Name": play["epic"],
            "Summary": _summary(f),
            "Priority": _PRIORITY.get(f.severity, "Medium"),
            "Story Points (provisional)": play["points"],
            "Labels": f"OrgIQ {f.dimension} {f.rule_id.replace('.', '_')}",
            "Salesforce Component": f.component,
            "Component Type": _component_type(f),
            "Rule ID": f.rule_id,
            "Dimension": f.dimension,
            "Severity": f.severity,
            "Confidence": f.confidence,
            "Rule Maturity": "experimental",
            "Description": _description(f, source),
        })
    return rows, observations


def write_csv(findings, source: str, path: str):
    """Write the gated backlog to a Jira-importable CSV. Returns
    (rows_written, observations_skipped)."""
    rows, observations = to_rows(findings, source)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=BACKLOG_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return len(rows), observations
