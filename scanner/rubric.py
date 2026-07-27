#!/usr/bin/env python3
"""
The rubric, loaded from data.

There are two different things in this scanner and they were tangled together.
The **engine** finds defects: it parses metadata, runs heuristics over field
names and Apex bodies, counts references. The **rubric** says what those defects
are worth: which ones are Critical, what a fix costs, how a score is penalised,
what the remediation is. They change for different reasons and by different
people — a practitioner disagreeing that a cryptic field name is worth three
points should not be editing Python — and they have different futures.

That future is the reason this file exists. If OrgIQ is ever installed *inside*
an org as a managed package, the engine has to be ported to Apex. A port that
has to carry thirty-five remediation playbooks, four band boundaries, a penalty
table and an effort model is a much larger and much riskier piece of work than
one that carries the heuristics alone and reads the same rubric.json it reads
today. Nothing about that port is scheduled; separating the two costs almost
nothing now and is nearly impossible to do later, once both halves have been
translated and can drift apart.

Everything is loaded once at import and exposed as plain dicts, so the modules
that used to hold these values as literals bind to them by name and nothing
downstream changed. The values themselves were extracted from those literals
rather than retyped, so this file could not have introduced a difference.
"""

from __future__ import annotations

import json
from pathlib import Path

RUBRIC_PATH = Path(__file__).with_name("rubric.json")

with RUBRIC_PATH.open(encoding="utf-8") as fh:
    _R = json.load(fh)

RUBRIC_VERSION = _R["rubric_version"]

# --- emission gate (PRD §4.6)
_GATE = _R["emission_gate"]
SEVERITY_RANK = _GATE["severity_rank"]
CONFIDENCE_RANK = _GATE["confidence_rank"]
MIN_SEVERITY = _GATE["min_severity"]
MIN_CONFIDENCE = _GATE["min_confidence"]

# --- backlog presentation
JIRA_PRIORITY = _R["jira_priority"]
DIMENSION_NAMES = _R["dimension_names"]
PLAYBOOK = _R["playbook"]
UNKNOWN_RULE = _R["unknown_rule"]

# --- scoring (PRD §4.2–§4.3)
_S = _R["scoring"]
BANDS = [tuple(b) for b in _S["bands"]]
PENALTY = _S["penalty_per_finding"]
GATE_CAPS = _S["gate_caps"]
D1_WEIGHTS = _S["d1_weights"]

# --- effort
_E = _R["effort"]
EFFORT_MODEL_VERSION = _E["model_version"]
EFFORT_SCALE = tuple(_E["scale"])
EFFORT_MIN_SAMPLES = _E["min_samples"]
BLAST_BANDS = tuple(tuple(b) for b in _E["blast_bands"])
ORG_TYPE_FACTOR = {k: tuple(v) for k, v in _E["org_type_factor"].items()}
GROUP_FACTOR = _E["group_factor"]


# --- routing
_R_ROUTE = _R.get("routing", {})
ROLES = _R_ROUTE.get("roles", {})
ROUTE_BY_RULE = _R_ROUTE.get("by_rule", {})
ROUTE_BY_DIMENSION = _R_ROUTE.get("by_dimension", {})
UNROUTED = _R_ROUTE.get("unrouted", "Unassigned")


# --- validation / rule maturity
_R_VAL = _R.get("validation", {})
MIN_VERDICTS = _R_VAL.get("min_verdicts", 10)
MATURITY_LADDER = _R_VAL.get("ladder", [])
DEFAULT_MATURITY = _R_VAL.get("default_maturity", "experimental")
WITHDRAW_BELOW = _R_VAL.get("withdraw_below", 0.6)
MEASURED = _R_VAL.get("measured", {})


def maturity_for(rule_id: str) -> str:
    """What this rule has earned the right to claim.

    Reads the measurement written back by the precision kit. With none — the
    state every rule is in until someone scores real findings — it returns the
    default, which is exactly what the hardcoded value used to say. The
    difference is that it can now change without editing Python, and that the
    ladder in the schema finally means something.
    """
    return (MEASURED.get(rule_id) or {}).get("maturity", DEFAULT_MATURITY)


def owner_role(rule_id: str, dimension: str = "") -> str:
    """The role that does this work.

    Rule first, dimension second. The per-rule overrides exist because a
    dimension groups findings by what they measure, not by who fixes them:
    D1.CRYPTIC_API_NAME sits with the description rules, but renaming a field
    safely means clearing formulas, flows, Apex, reports and integrations first,
    which is a developer's job. Routed to the steward it would simply stall.
    """
    if rule_id in ROUTE_BY_RULE:
        return ROUTE_BY_RULE[rule_id]
    if dimension in ROUTE_BY_DIMENSION:
        return ROUTE_BY_DIMENSION[dimension]
    # Named, not blank. An unrouted finding is a real gap — a rule shipped
    # without anyone deciding who owns it — and blank would hide it among the
    # findings that simply have no owner yet.
    return UNROUTED


def play(rule_id: str) -> dict:
    """The playbook entry for a rule, or the generic one.

    A rule with no entry is a real gap — it means a heuristic ships without
    anyone having written down how to fix what it finds — so the fallback is
    deliberately vague rather than plausible, and `missing_playbook_entries()`
    exists to make the gap countable instead of invisible.
    """
    return PLAYBOOK.get(rule_id, UNKNOWN_RULE)


def missing_playbook_entries(rule_ids) -> list:
    return sorted({r for r in rule_ids if r not in PLAYBOOK})
