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

import rubric

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

# Bound to scanner/rubric.json rather than written here: what counts as
# Critical, and where the emission bar sits, is judgement a practitioner should
# be able to change without editing Python. See scanner/rubric.py.
_SEV_RANK = rubric.SEVERITY_RANK
_CONF_RANK = rubric.CONFIDENCE_RANK

# PRD §4.6: severity >= Medium AND confidence >= Medium
_GATE_SEV = _SEV_RANK[rubric.MIN_SEVERITY]
_GATE_CONF = _CONF_RANK[rubric.MIN_CONFIDENCE]


def emits_to_backlog(finding) -> bool:
    """True if the finding clears the §4.6 emission gate."""
    return (_SEV_RANK.get(finding.severity, 0) >= _GATE_SEV
            and _CONF_RANK.get(finding.confidence, 0) >= _GATE_CONF)


# Dimension code -> its name. The ticket header used to say "Grounding Quality"
# for every dimension, which was true when only D1 existed and has been wrong
# since D2–D5 landed; an ingested Code Analyzer violation filed under "Grounding
# Quality" would be actively misleading about what the finding is.
_DIM_NAME = rubric.DIMENSION_NAMES

# severity -> Jira priority
_PRIORITY = rubric.JIRA_PRIORITY

# ------------------------------------------------ per-rule playbook
#
# One entry per rule_id: `epic` groups tickets, `points` is the PROVISIONAL
# effort estimate, `remediation` is the ordered fix, `acceptance` is how you
# verify it. It lives in scanner/rubric.json, not here — the whole point is that
# it is reviewable and tunable by someone who does not write Python, and a
# thirty-five-entry table of English prose embedded in a module is neither.

_UNKNOWN = rubric.UNKNOWN_RULE

_PLAYBOOK = rubric.PLAYBOOK


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
    "Owner Role",        # which team does it — an unassigned backlog is a list
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
        "Owner Role": rubric.owner_role(f.rule_id, f.dimension),
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
        "Owner Role": (lambda rs: rs.pop() if len(rs) == 1 else "Mixed")({rubric.owner_role(c.rule_id, c.dimension) for c in children}),
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
