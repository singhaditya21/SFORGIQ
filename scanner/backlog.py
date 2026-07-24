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
    `hash(rule_id + component + source)`, plus `detail` for the handful of rules
    where detail identifies *which* finding this is rather than describing its
    current state (see `_IDENTITY_DETAIL_RULES`). Re-importing updates the same
    ticket instead of duplicating it — this is what turns a one-off audit into a
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

# ---------------------------------------------------------- provenance

# Where a finding came from. Native rule findings are "OrgIQ"; the same backlog
# will later carry ingested Optimizer / Health Check / Code Analyzer findings
# (PRD §7.3, "ingested, not duplicated"), and a reviewer triaging a ticket needs
# to know which engine made the claim before trusting it.
FINDING_SOURCE = "OrgIQ"


def _finding_source(finding) -> str:
    """Provenance of a single finding. Ingested findings may carry their own
    `source`; anything the scanner rules produce is FINDING_SOURCE."""
    return getattr(finding, "source", "") or FINDING_SOURCE


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

    "D1.UNREFERENCED_FIELD": {
        "epic": "Retire unreferenced fields",
        "points": 3,
        "remediation": (
            "1. Confirm the field is genuinely unused. Source mode only sees "
            "reports and dashboards that are committed to the repo, so check "
            "integrations, managed packages, and anything outside this "
            "repository before treating 'no references' as 'unused'.\n"
            "2. If it is dead, deprecate before deleting: remove it from page "
            "layouts and permission sets and let a full business cycle pass.\n"
            "3. Delete the field. If it must stay, describe what it is for so "
            "it stops competing with live fields for retrieval."
        ),
        "acceptance": (
            "Field is deleted, or retained with a documented reason and hidden "
            "from the agent's layouts and permissions. Absence of references "
            "was verified against integrations and managed packages, not just "
            "the committed report metadata. Re-scan reports no "
            "D1.UNREFERENCED_FIELD for this field."
        ),
    },

    # --- D2 Data Foundation ---
    "D2.LOW_FILL_RATE": {
        "epic": "Backfill under-populated fields", "points": 5,
        "remediation": "1. Identify records missing the field and the system of record.\n"
                       "2. Backfill from source or mark deliberately empty.\n"
                       "3. Add validation/automation to keep it populated going forward.",
        "acceptance": "Fill rate on the field exceeds the grounding threshold; re-scan clears the finding.",
    },
    "D2.STALE_DATA": {
        "epic": "Refresh stale data", "points": 3,
        "remediation": "1. Confirm which records are genuinely stale vs dormant.\n"
                       "2. Refresh from source or archive.\n"
                       "3. Add a freshness SLA / last-verified process.",
        "acceptance": "Stale-record ratio falls below threshold; re-scan clears the finding.",
    },
    "D2.DUPLICATE_RECORDS": {
        "epic": "De-duplicate records", "points": 5,
        "remediation": "1. Run matching rules to cluster duplicates.\n"
                       "2. Merge to a surviving record with the correct field survivorship.\n"
                       "3. Add duplicate rules to prevent recurrence.",
        "acceptance": "Duplicate rate below threshold; re-scan clears the finding.",
    },

    # --- D3 Action Surface ---
    "D3.NO_SAFE_ACTIONS": {
        "epic": "Build a safe action surface", "points": 8,
        "remediation": "1. Identify the tasks the agent must perform.\n"
                       "2. Expose bulk-safe, idempotent invocable actions with typed inputs.\n"
                       "3. Document each so the planner can select it.",
        "acceptance": "At least one bulk-safe invocable action exists per intended task; re-scan clears the finding.",
    },
    "D3.UNDOCUMENTED_ACTION": {
        "epic": "Document invocable actions", "points": 2,
        "remediation": "1. Describe what the action does, its inputs, and when to use it.\n"
                       "2. Keep the description disambiguating, not a restatement of the name.",
        "acceptance": "Action carries a planner-usable description; re-scan clears the finding.",
    },
    "D3.APEX_NO_TESTS": {
        "epic": "Cover agent-invoked Apex with tests", "points": 3,
        "remediation": "1. Add tests exercising the class's bulk and error paths.\n"
                       "2. Assert on outcomes, not just coverage percentage.",
        "acceptance": "Class has meaningful test coverage; re-scan clears the finding.",
    },

    # --- D4 Permission Blast Radius ---
    "D4.MODIFY_ALL_DATA": {
        "epic": "Remove Modify All Data from the agent", "points": 5,
        "remediation": "1. Enumerate what the agent actually needs to write.\n"
                       "2. Replace Modify All Data with scoped object/field permissions.\n"
                       "3. Re-test the agent against the tightened permission set.",
        "acceptance": "Agent permission set no longer grants Modify All Data; re-scan clears the finding.",
    },
    "D4.VIEW_ALL_DATA": {
        "epic": "Remove View All Data from the agent", "points": 3,
        "remediation": "1. Determine the records the agent legitimately reads.\n"
                       "2. Replace View All Data with sharing-based or scoped read access.",
        "acceptance": "Agent permission set no longer grants View All Data; re-scan clears the finding.",
    },
    "D4.WIDE_OBJECT_ACCESS": {
        "epic": "Tighten over-broad object access", "points": 2,
        "remediation": "1. Compare granted object/field access to the agent's task scope.\n"
                       "2. Revoke access beyond what the task requires.",
        "acceptance": "Object access matches task scope; re-scan clears the finding.",
    },

    # --- D5 Automation Collision ---
    "D5.DML_IN_LOOP": {
        "epic": "Bulkify automation", "points": 5,
        "remediation": "1. Move DML out of loops; collect and act on collections.\n"
                       "2. Add bulk tests (200+ records) that would have caught it.",
        "acceptance": "No DML in loops on the automation path; bulk tests pass; re-scan clears the finding.",
    },
    "D5.MULTIPLE_TRIGGERS": {
        "epic": "Consolidate triggers per object", "points": 8,
        "remediation": "1. Consolidate to one trigger per object delegating to a handler.\n"
                       "2. Define a deterministic execution order.",
        "acceptance": "One trigger per object with defined order; re-scan clears the finding.",
    },
    "D5.NO_RECURSION_GUARD": {
        "epic": "Add recursion guards", "points": 3,
        "remediation": "1. Add a static guard so the handler runs once per transaction.\n"
                       "2. Verify an agent-initiated write cannot re-fire the automation.",
        "acceptance": "Automation is recursion-safe; re-scan clears the finding.",
    },
    "D3.INACTIVE_ACTION": {
        "epic": "Activate or retire dormant flows", "points": 2,
        "remediation": "1. Decide whether the flow is still needed.\n"
                       "2. Activate it (after testing) or delete it so it stops appearing "
                       "as a candidate action.",
        "acceptance": "No Draft/Obsolete flow is exposed as an agent action; re-scan clears it.",
    },
    "D4.DELETE_GRANTED": {
        "epic": "Remove unnecessary delete rights", "points": 2,
        "remediation": "1. Confirm the agent's tasks genuinely require deletes.\n"
                       "2. If not, revoke delete on the object; prefer soft-delete or status "
                       "changes for agent-driven flows.",
        "acceptance": "Delete is granted only where a task requires it; re-scan clears it.",
    },
    "D5.SOQL_IN_LOOP": {
        "epic": "Bulkify automation", "points": 5,
        "remediation": "1. Hoist the query out of the loop and map results by key.\n"
                       "2. Add a bulk test (200+ records) that would have caught it.",
        "acceptance": "No SOQL inside loops on the automation path; re-scan clears it.",
    },
    "D5.TRIGGER_AND_FLOW": {
        "epic": "Resolve trigger/flow ordering collisions", "points": 8,
        "remediation": "1. Map what the trigger and the record-triggered flow each do.\n"
                       "2. Consolidate into one automation path, or set explicit flow "
                       "trigger order and document the contract.\n"
                       "3. Add a test that writes the record the way an agent would.",
        "acceptance": "One deterministic automation path per object; re-scan clears it.",
    },
}


def _play(rule_id: str) -> dict:
    return _PLAYBOOK.get(rule_id, _UNKNOWN)


# ---------------------------------------------------------- row shaping

def _component_type(finding) -> str:
    # Aggregate findings look like "Object [N fields]"; field findings like
    # "Object.Field__c". Everything the D1 spike emits is about custom fields.
    return "CustomField group" if "[" in finding.component else "CustomField"


# Rules whose `detail` is IDENTITY, not state.
#
# For these, detail says *which* finding this is — the members of a duplicate
# cluster or numbered family, or which occurrence on a trigger — and two
# findings on the same component are only distinguishable by it (both render as
# "Obj [2 fields]"). It must be hashed or the ids collide on upsert.
#
# For every other rule detail is a snapshot of mutable state ("label='X'",
# "desc='...'"), and hashing it re-mints the ticket id the moment somebody edits
# the label or description — i.e. the moment they start fixing the finding. The
# tracked ticket orphans, a new one appears, and the burn-down that is the whole
# point of a stable External ID is destroyed.
_IDENTITY_DETAIL_RULES = {
    "D1.NUMBERED_FAMILY",
    "D1.SEMANTIC_DUPLICATE",
    "D5.MULTIPLE_TRIGGERS",
    "D5.DML_IN_LOOP",
    "D5.NO_RECURSION_GUARD",
}


def _external_id(finding, source: str) -> str:
    """Deterministic, idempotent id (PRD §4.6). Source stands in for org_id
    in source mode, so re-scanning the same repo yields the same id. `detail`
    joins the hash only for _IDENTITY_DETAIL_RULES — see the note there."""
    detail = finding.detail if finding.rule_id in _IDENTITY_DETAIL_RULES else ""
    raw = f"{finding.rule_id}|{finding.component}|{detail}|{source}"
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
        # Two different "sources": where the org came from, and which engine
        # raised the finding. Label both so the ticket is not ambiguous.
        f"Scan source: {source}",
        f"Finding source: {_finding_source(finding)}",
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
    "Source",            # which engine raised it — OrgIQ, or an ingested tool
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
            "Source": _finding_source(f),
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
