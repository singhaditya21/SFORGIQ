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

  - **Findings cluster into epics before emission** (PRD §4.6). Each playbook
    epic ("Retire unreferenced fields") is emitted as a real Epic row, followed
    immediately by its child Task rows, so the file reads as a structure rather
    than a flat list. Jira's CSV importer takes `Epic Name` on the epic only and
    links the children through `Epic Link` — a child that also carries an Epic
    Name is read as a second epic, so children leave it blank. Without this,
    a 24-org portfolio imports as ~1,900 unparented tickets: the same
    "four-thousand-ticket dump nobody imports" the §4.6 gate exists to prevent.

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


# Dimension code -> its name. The ticket header used to say "Grounding Quality"
# for every dimension, which was true when only D1 existed and has been wrong
# since D2–D5 landed; an ingested Code Analyzer violation filed under "Grounding
# Quality" would be actively misleading about what the finding is.
_DIM_NAME = {
    "D1": "Grounding Quality",
    "D2": "Data Foundation",
    "D3": "Action Surface",
    "D4": "Permission Blast Radius",
    "D5": "Automation Collision",
}

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

    # --- ingested from Salesforce's free tools (scanner/external.py) ---
    #
    # Two things differ from the native entries above, and both are honesty
    # requirements rather than style:
    #
    #   * Acceptance says re-run THE TOOL THAT RAISED IT. An OrgIQ re-scan
    #     cannot clear a Code Analyzer violation — OrgIQ has no Apex parser —
    #     so "re-scan clears the finding" would be an acceptance criterion
    #     nobody can actually satisfy.
    #   * Where an ingested finding shares an epic with a native rule
    #     (bulkification, Apex tests, unreferenced fields) it KEEPS that epic
    #     name, so one fix is one epic no matter which engine found it.

    "D5.EXT_BULK_SAFETY": {
        "epic": "Bulkify automation", "points": 5,
        "remediation": "1. Open the flagged file at the reported line and confirm the "
                       "violation — Code Analyzer parses Apex, so treat it as a finding, "
                       "not a hint.\n"
                       "2. Hoist the query or DML out of the loop and act on collections; "
                       "where the caller is agent-invoked, check the whole call path, not "
                       "just this method.\n"
                       "3. Add a bulk test (200+ records) that fails before the fix.",
        "acceptance": "Re-running Code Analyzer over the same workspace reports no "
                      "bulk-safety violation for this file, and a 200-record test passes.",
    },
    "D4.EXT_SECURITY_VIOLATION": {
        "epic": "Close code-level security violations", "points": 5,
        "remediation": "1. Read the rule's documentation link on the finding; CRUD/FLS, "
                       "sharing and injection rules each have a specific safe form.\n"
                       "2. Apply it — enforce sharing, check accessibility before the "
                       "query or DML, bind variables instead of concatenating SOQL.\n"
                       "3. Re-run Code Analyzer with the same rule selector to confirm "
                       "the path is clear, including any Graph Engine path rules.",
        "acceptance": "Re-running Code Analyzer reports no security violation for this "
                      "file. Note this is Code Analyzer's verdict, not OrgIQ's: OrgIQ "
                      "does not analyse Apex data flow and cannot confirm the fix.",
    },
    "D3.EXT_TEST_QUALITY": {
        "epic": "Cover agent-invoked Apex with tests", "points": 3,
        "remediation": "1. Add assertions that check outcomes — a test that runs code "
                       "without asserting anything proves only that it did not throw.\n"
                       "2. Remove SeeAllData=true and build the data the test needs.\n"
                       "3. Exercise the bulk and error paths an agent will hit.",
        "acceptance": "Re-running Code Analyzer reports no test-quality violation for "
                      "this class, and the tests assert on outcomes rather than coverage.",
    },
    "D4.HEALTH_CHECK_RISK": {
        "epic": "Raise the org to the Health Check baseline", "points": 2,
        "remediation": "1. Open Setup > Security > Health Check and find the setting "
                       "named on this finding; the page fixes most settings in place.\n"
                       "2. Confirm the change is safe for existing integrations and "
                       "logins before applying it — several of these settings can lock "
                       "out a working integration.\n"
                       "3. Apply it, or record a documented exception with an owner if "
                       "the org deliberately runs below the baseline.",
        "acceptance": "Health Check no longer lists this setting as a risk, or the "
                      "deviation is recorded as an accepted exception with an owner. "
                      "This is org security posture, not agent blast radius: it is "
                      "reported and ticketed but does not move the D4 score.",
    },
    "D1.OPTIMIZER_UNUSED_FIELD": {
        "epic": "Retire unreferenced fields", "points": 3,
        "remediation": "1. Confirm against Optimizer's own report which records and "
                       "components it checked — it sees the whole org, including layouts "
                       "and dependencies OrgIQ cannot read from source.\n"
                       "2. Deprecate before deleting: remove the field from page layouts "
                       "and permission sets and let a full business cycle pass.\n"
                       "3. Delete it, or keep it and describe what it is for so it stops "
                       "competing with live fields for retrieval.",
        "acceptance": "Field is deleted, or retained with a documented reason and hidden "
                      "from the agent's layouts and permissions. A re-run of Optimizer no "
                      "longer lists it as unused.",
    },
    "D4.OPTIMIZER_PERMISSION_RISK": {
        "epic": "Reduce profile and permission-set sprawl", "points": 5,
        "remediation": "1. Review the profile or permission set Optimizer flagged and "
                       "list who actually holds it.\n"
                       "2. Consolidate overlapping grants and remove the ones no live "
                       "user or integration needs.\n"
                       "3. Re-test the agent's own permission set against the tightened "
                       "model.",
        "acceptance": "A re-run of Optimizer no longer flags this profile or permission "
                      "set, and the agent's own access is unchanged or narrower.",
    },
}


def _play(rule_id: str) -> dict:
    return _PLAYBOOK.get(rule_id, _UNKNOWN)


# ---------------------------------------------------------- row shaping

def _component_type(finding) -> str:
    # Ingested findings know exactly what they are about — an Apex class, a
    # security setting — and say so on the finding. Read that first; the
    # heuristic below cannot tell an Apex class from a field and would label a
    # Code Analyzer violation "CustomField".
    explicit = getattr(finding, "component_type", "")
    if explicit:
        return explicit
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


def _epic_external_id(epic: str, source: str) -> str:
    """Idempotent id for an epic row. Hashes only (epic, source): the epic must
    survive its children changing — findings come and go between re-scans, and
    an epic that re-minted its id whenever one child cleared would orphan the
    parent everyone is tracking the burn-down on."""
    raw = f"{epic}|{source}"
    return "OIQ-EPIC-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _epic_name(epic: str, source: str) -> str:
    """The Jira Epic Name. Org-qualified, because a merged portfolio CSV puts 24
    orgs in one file and Jira keys epics by name — unqualified, every org's
    "Retire unreferenced fields" would collapse into one epic."""
    return f"{epic} — {source}"


def _summary(finding) -> str:
    return f"[{finding.rule_id}] {finding.component}: {finding.evidence}"[:200]


# ------------------------------------------------------- epic roll-up
#
# What a triager wants off an epic row, before opening a single child: what the
# work is, how big it is, and where in the org it lands.

# How many objects to name in an epic summary before collapsing to "+N more".
# Four fits the width of a Jira summary column; twenty does not, and a summary
# nobody can read is a summary nobody triages from.
_SCOPE_CAP = 4


def _scope_of(finding) -> str:
    """The object (or, for components that are not object-scoped, the artefact)
    a finding lands on. Components arrive in several shapes across the rule
    packs and all of them have to reduce to something a reader recognises:

        Account.Region__c      -> Account          (field)
        Account [12 fields]    -> Account          (aggregate)
        Agent_PS:Case          -> Case             (perm set on an object)
        BillingService.cls     -> BillingService   (Apex class)
        Opportunity            -> Opportunity      (object / trigger / flow)
    """
    head = (finding.component or "").split(" [", 1)[0].strip()
    if ":" in head:                       # perm set : object — the object is the news
        head = head.split(":", 1)[-1].strip()
    if head.endswith(".cls"):             # the class IS the subject, keep it
        return head[:-len(".cls")]
    if "." in head:
        return head.split(".", 1)[0]
    return head


def _scope_phrase(children) -> str:
    """Renders as: Account, Contact, Case, Opportunity +3 more

    In the children's own order, so the most severe object is named first."""
    seen = []
    for f in children:
        scope = _scope_of(f)
        if scope and scope not in seen:
            seen.append(scope)
    if not seen:
        return "components with no object recorded"
    shown = ", ".join(seen[:_SCOPE_CAP])
    extra = len(seen) - _SCOPE_CAP
    return f"{shown} +{extra} more" if extra > 0 else shown


def _distinct(values) -> list:
    out = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out


def _epic_points(children) -> int:
    return sum(_play(f.rule_id)["points"] for f in children)


def _epic_severity(children) -> str:
    """An epic is as urgent as its worst child."""
    return max(children, key=lambda f: _SEV_RANK.get(f.severity, 0)).severity


def _epic_confidence(children) -> str:
    """...and only as trustworthy as its shakiest one. Computed, not read off
    the last child: the children sort by severity first, so the tail is the
    least severe finding, which is not necessarily the least confident."""
    return min(children, key=lambda f: _CONF_RANK.get(f.confidence, 0)).confidence


def _epic_summary(epic: str, children) -> str:
    n = len(children)
    item = "item" if n == 1 else "items"
    return f"{epic} — {n} {item} across {_scope_phrase(children)}"[:200]


def _epic_description(epic: str, children, source: str) -> str:
    """The rollup a reviewer reads before deciding whether to schedule the whole
    epic: what it is, how big, how much provisional effort, and what "done"
    means for its children."""
    n = len(children)
    rules = _distinct(f.rule_id for f in children)
    engines = _distinct(_finding_source(f) for f in children)
    # What actually verifies this epic. An OrgIQ re-scan cannot clear a Code
    # Analyzer violation or a Health Check risk — OrgIQ has no Apex parser and
    # does not evaluate org security settings — so an epic full of ingested
    # findings has to name the engine that can confirm the fix.
    closes = ("a re-scan" if engines == [FINDING_SOURCE]
              else "a re-run of " + " and ".join(engines))
    lines = [
        f"Epic: {epic} ({children[0].dimension})",
        f"Severity: {_epic_severity(children)}   "
        f"Confidence: {_epic_confidence(children)}",
        "",
        f"Items: {n}",
        f"Objects: {_scope_phrase(children)}",
        f"Rules: {', '.join(rules)}",
        f"Provisional effort: {_epic_points(children)} point(s) across {n} child item(s)",
        "",
        "These findings share one fix, so they are imported as one epic rather "
        "than as loose tickets (PRD §4.6). Each child below carries its own "
        "component, evidence and remediation steps; the epic closes when every "
        f"child clears {closes}.",
        "",
        "Acceptance criteria (shared by the children):",
    ]
    for rule_id in rules:
        lines.append(f"- {rule_id}: {_play(rule_id)['acceptance']}")
    lines += [
        "",
        f"Scan source: {source}",
        f"Finding source: {', '.join(_distinct(_finding_source(f) for f in children))}",
        f"Effort points are PROVISIONAL (uncalibrated, PRD §8/§11).",
    ]
    return "\n".join(lines)


def _description(finding, source: str) -> str:
    play = _play(finding.rule_id)
    lines = [
        f"Rule: {finding.rule_id} ({finding.dimension} — {_DIM_NAME.get(finding.dimension, 'OrgIQ')})",
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
    ]
    # Ingested findings: name the tool's own rule and its documentation, so a
    # triager can go back to the engine that made the claim, and record any
    # corroborating engine, so the merge that removed a second ticket is
    # visible on the one that survived rather than silently applied.
    tool_rule = getattr(finding, "tool_rule", "")
    if tool_rule:
        lines.append(f"Tool rule: {tool_rule}")
    reference = getattr(finding, "reference", "")
    if reference:
        lines.append(f"Reference: {reference}")
    corroborated = getattr(finding, "corroborated_by", None)
    if corroborated:
        lines.append(f"Corroborated by: {', '.join(corroborated)} — the same defect "
                     f"reported independently; merged into this one item so it is "
                     f"not worked, or counted, twice.")
    lines.append("Effort points are PROVISIONAL (uncalibrated, PRD §8/§11).")
    return "\n".join(lines)


# Column order chosen to map cleanly in Jira's CSV importer.
BACKLOG_COLUMNS = [
    "External ID",      # -> map to a stable text field for idempotent re-import
    "Issue Type",
    "Epic Name",        # epic rows only — Jira reads a named child as a 2nd epic
    "Epic Link",        # child rows only — the parent's Epic Name
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


def _sort_key(f):
    return (-_SEV_RANK.get(f.severity, 0), -_CONF_RANK.get(f.confidence, 0),
            f.rule_id, f.component)


def _task_row(f, source: str, epic_name: str, epic_link: str) -> dict:
    play = _play(f.rule_id)
    return {
        "External ID": _external_id(f, source),
        "Issue Type": "Task",
        "Epic Name": epic_name,
        "Epic Link": epic_link,
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
    }


def _epic_row(epic: str, children, source: str) -> dict:
    """One parent row for a cluster of gated findings. `children` arrives in the
    order it will be written in, most severe first, so the scope list and the
    rule list read top-down the way the file does."""
    rules = _distinct(f.rule_id for f in children)
    dimension = children[0].dimension     # epics never span dimensions by construction
    severity = _epic_severity(children)
    return {
        "External ID": _epic_external_id(epic, source),
        "Issue Type": "Epic",
        "Epic Name": _epic_name(epic, source),
        "Epic Link": "",                  # an epic has no parent
        "Summary": _epic_summary(epic, children),
        "Priority": _PRIORITY.get(severity, "Medium"),
        "Story Points (provisional)": _epic_points(children),
        "Labels": " ".join(["OrgIQ", dimension, "epic"]
                           + [r.replace(".", "_") for r in rules]),
        "Salesforce Component": _scope_phrase(children),
        "Component Type": "Epic",
        "Rule ID": ", ".join(rules),
        "Dimension": dimension,
        "Severity": severity,
        "Confidence": _epic_confidence(children),
        "Rule Maturity": "experimental",
        "Source": ", ".join(_distinct(_finding_source(f) for f in children)),
        "Description": _epic_description(epic, children, source),
    }


def to_rows(findings, source: str, include_epics: bool = True):
    """Split findings into (backlog_rows, observation_count).

    backlog_rows are dicts keyed by BACKLOG_COLUMNS. With `include_epics` the
    file is a structure, not a list: each playbook epic that has at least one
    gated finding emits an Epic row followed immediately by its own children,
    epics ordered by their most severe child and children most-severe-first
    inside the epic. `include_epics=False` gives the flat one-row-per-finding
    export back, for a caller that only wants the findings.
    """
    gated = [f for f in findings if emits_to_backlog(f)]
    observations = len(findings) - len(gated)
    ordered = sorted(gated, key=_sort_key)

    if not include_epics:
        return ([_task_row(f, source, _play(f.rule_id)["epic"], "") for f in ordered],
                observations)

    # dict preserves insertion order, so epics come out ordered by their most
    # severe finding and each epic's children keep the severity order they were
    # sorted into — no second sort, and nothing to drift out of step with it.
    clusters = {}
    for f in ordered:
        clusters.setdefault(_play(f.rule_id)["epic"], []).append(f)

    rows = []
    for epic, children in clusters.items():
        rows.append(_epic_row(epic, children, source))
        epic_link = _epic_name(epic, source)
        for f in children:
            # Epic Name stays empty on children: Jira's importer treats a row
            # carrying one as an epic in its own right, and the parent's name in
            # Epic Link is what actually creates the link.
            rows.append(_task_row(f, source, "", epic_link))
    return rows, observations


def count_tickets(rows) -> int:
    """How many of these rows are actual work items. Epic rows are scaffolding —
    a caller reporting "N backlog items" means findings that became tickets, so
    anything printing a count off to_rows() should count through here rather
    than len(rows)."""
    return sum(1 for r in rows if r.get("Issue Type") == "Task")


def write_csv(findings, source: str, path: str, include_epics: bool = True):
    """Write the gated backlog to a Jira-importable CSV. Returns
    (ticket_count, observations_skipped).

    ticket_count counts CHILD TASKS only — the number the CLI prints has always
    meant "findings that became tickets", and counting the epic scaffolding into
    it would inflate that number for no reader's benefit."""
    rows, observations = to_rows(findings, source, include_epics=include_epics)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=BACKLOG_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return count_tickets(rows), observations
