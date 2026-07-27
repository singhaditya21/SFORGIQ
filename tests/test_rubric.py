"""The rubric as data.

Two different things live in this scanner: the engine, which finds defects, and
the rubric, which says what they are worth. These tests defend the separation —
that the rubric really is data, that the engine reads it rather than shadowing
it, and that the split did not quietly lose an entry.
"""

import json
import pathlib
import re

import backlog
import effort
import rubric
import scan_result


# ------------------------------------------------------- it is really data

def test_the_rubric_is_a_file_a_non_engineer_can_edit():
    """The whole point. A thirty-five-entry table of English remediation prose
    embedded in a Python module is not reviewable by the practitioner whose
    judgement it encodes."""
    doc = json.loads(rubric.RUBRIC_PATH.read_text(encoding="utf-8"))
    assert doc["playbook"]
    assert all("remediation" in v and "acceptance" in v
               for v in doc["playbook"].values())


def test_the_engine_reads_the_rubric_rather_than_holding_its_own_copy():
    """A shadow copy is worse than no separation at all: editing the file would
    appear to work and change nothing."""
    assert backlog._PLAYBOOK is rubric.PLAYBOOK
    assert scan_result._PENALTY is rubric.PENALTY
    assert effort.SCALE is rubric.EFFORT_SCALE
    assert backlog._SEV_RANK is rubric.SEVERITY_RANK


# --------------------------------------------------------- no lost entries

def test_every_rule_the_scanner_can_emit_has_a_playbook_entry():
    """A rule with no entry ships a heuristic nobody wrote a fix for. It still
    produces a ticket — with generic text — so the gap is invisible unless it is
    asserted here."""
    import drift
    import external
    import orgiq_spike
    import persona
    import rules_ext

    # Scraped from the sources rather than from a list someone maintains: a
    # hand-kept list is the thing that goes stale the day a rule is added, which
    # is exactly the day this test needs to fail.
    #
    # A dimension code alone ("D1.") is not a rule id — the tail must be an
    # UPPER_SNAKE name, or every sentence ending in "D5." reads as a rule.
    pattern = re.compile(r"\bD[1-5]\.[A-Z][A-Z0-9_]{2,}\b")
    found = set()
    for mod in (orgiq_spike, rules_ext, external, persona, drift):
        found.update(pattern.findall(
            pathlib.Path(mod.__file__).read_text(encoding="utf-8")))
    assert len(found) > 20, "the scraper found almost nothing — it has broken"
    missing = rubric.missing_playbook_entries(found)
    assert missing == [], f"rules with no remediation playbook: {missing}"


def test_an_unknown_rule_falls_back_to_something_deliberately_vague():
    """The fallback must not read like a real fix. A plausible-sounding generic
    remediation is how a missing entry stays missing."""
    play = rubric.play("D9.NOT_A_RULE")
    assert play is rubric.UNKNOWN_RULE
    assert "Investigate" in play["remediation"]


# ----------------------------------------------------- the values survived

def test_the_bands_still_cover_every_score_exactly_once():
    for score in range(0, 101):
        matches = [n for lo, hi, n in rubric.BANDS if lo <= score <= hi]
        assert len(matches) == 1, f"{score} matched {matches}"


def test_the_emission_gate_still_sits_at_medium_and_medium():
    """PRD §4.6. Moving it is a decision, not a side effect of a refactor."""
    assert rubric.MIN_SEVERITY == "Medium" and rubric.MIN_CONFIDENCE == "Medium"
    assert backlog._GATE_SEV == rubric.SEVERITY_RANK["Medium"]


def test_a_gate_cap_the_engine_cannot_evaluate_is_ignored_not_assumed():
    """Which caps exist is rubric; when each fires is engine. A rubric edit must
    not be able to invent a cap that silently applies to every scan."""
    original = rubric.GATE_CAPS
    try:
        rubric.GATE_CAPS = original + [{"cap": 10, "when": "no_such_condition",
                                        "reason": "invented"}]
        composite, applied, reason = scan_result._composite(
            [{"score": 90, "in_composite": True}], [])
        assert composite == 90 and applied is False and "invented" not in reason
    finally:
        rubric.GATE_CAPS = original


def test_the_effort_model_version_is_the_one_the_rubric_declares():
    """An actual recorded against one model must never be compared with
    another, so the two cannot be allowed to drift apart."""
    assert effort.MODEL_VERSION == rubric.EFFORT_MODEL_VERSION
    assert rubric.EFFORT_MODEL_VERSION in effort.estimate("D1.X", 3).basis
