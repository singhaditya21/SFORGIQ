#!/usr/bin/env python3
"""
How often each rule is right.

The maturity ladder — experimental, validated, field-proven — has been in the
schema since the first commit, and every finding this scanner has ever produced
shipped as `experimental`, hardcoded. Not because the rules are bad, but because
nothing measured them: there was no way for anyone to say "this finding was
wrong" and no arithmetic waiting for them to say it.

That is the same shape as the effort model's problem, and it has the same answer.
The data does not exist because there is nowhere for it to land.

**Precision is not the only question, and is deliberately not asked as if it
were.** Two things can be true of a finding and they live in different fields:

    Verdict__c   was it correct?          True Positive / False Positive
    Status__c    will anyone act on it?   Open / Resolved / Suppressed

A rule can be perfectly precise and still not worth shipping, if every correct
finding it raises is one the org has no intention of fixing. Both numbers are
reported here. Only precision moves the ladder — whether work is worth doing is
the org's judgement, not evidence about the rule.

One rule at a time, never pooled. A pack that is 90% precise on average can be
40% precise on the rule that fires most often, and the average is what hides it.
"""

from __future__ import annotations

from dataclasses import dataclass

import rubric

TRUE_POSITIVE = "True Positive"
FALSE_POSITIVE = "False Positive"
VERDICTS = (TRUE_POSITIVE, FALSE_POSITIVE)


@dataclass
class RuleScore:
    rule_id: str
    verdicts: int = 0
    true_positives: int = 0
    false_positives: int = 0
    precision: float = None        # None until there is anything to divide
    suppressed: int = 0            # correct, and the org will not act
    maturity: str = rubric.DEFAULT_MATURITY
    verdict_status: str = "unmeasured"   # unmeasured | provisional | measured

    @property
    def actionability(self):
        """Of the findings this rule got right, the share the org intends to
        act on. Low is not a defect in the rule — it is a rule finding real
        things nobody has decided are worth fixing, which is a product question
        rather than a correctness one."""
        if not self.true_positives:
            return None
        return round((self.true_positives - self.suppressed) / self.true_positives, 2)

    @property
    def withdraw_candidate(self) -> bool:
        """Named for withdrawal only on evidence that could also have promoted
        it. The sample floor cuts both ways: one verdict is not enough to make a
        rule validated, and it is not enough to take one out of the pack either.
        Without that symmetry the first reviewer to disagree with a rule retires
        it."""
        return (self.verdict_status == "measured"
                and self.precision is not None
                and self.precision < rubric.WITHDRAW_BELOW)


def maturity_for(precision, verdicts: int) -> str:
    """The highest tier this evidence clears.

    Both a precision floor and a sample floor, because either alone is gameable:
    three findings at 100% is not a validated rule, and fifty findings at 50% is
    not one either.
    """
    if precision is None:
        return rubric.DEFAULT_MATURITY
    for tier in rubric.MATURITY_LADDER:
        if precision >= tier["min_precision"] and verdicts >= tier["min_verdicts"]:
            return tier["maturity"]
    return rubric.DEFAULT_MATURITY


def score_rule(rule_id: str, records) -> RuleScore:
    """`records` are dicts with `verdict` and, optionally, `status`.

    A finding with no verdict is skipped rather than counted as correct. That
    distinction is the whole point: silence is not agreement, and a rule with
    nothing scored has an unmeasured precision, not a perfect one.
    """
    scored = [r for r in records if (r.get("verdict") or "") in VERDICTS]
    out = RuleScore(rule_id=rule_id, verdicts=len(scored))
    if not scored:
        return out

    out.true_positives = sum(1 for r in scored if r["verdict"] == TRUE_POSITIVE)
    out.false_positives = out.verdicts - out.true_positives
    out.precision = round(out.true_positives / out.verdicts, 3)
    out.suppressed = sum(1 for r in scored
                         if r["verdict"] == TRUE_POSITIVE
                         and (r.get("status") or "") == "Suppressed")
    # Under the floor the number is arithmetic on anecdote: reported, so the
    # gap is visible, but not allowed to move the rule.
    if out.verdicts < rubric.MIN_VERDICTS:
        out.verdict_status = "provisional"
        out.maturity = rubric.DEFAULT_MATURITY
    else:
        out.verdict_status = "measured"
        out.maturity = maturity_for(out.precision, out.verdicts)
    return out


def measure(records) -> list:
    """One RuleScore per rule, least precise first — the order someone reading
    this wants, because the top of the list is what to fix."""
    by_rule = {}
    for r in records:
        by_rule.setdefault(r.get("rule_id", "?"), []).append(r)

    scores = [score_rule(rule, rows) for rule, rows in by_rule.items()]
    return sorted(scores, key=lambda s: (s.precision if s.precision is not None else 2,
                                         -s.verdicts, s.rule_id))


def rubric_patch(scores) -> dict:
    """The `validation.measured` block to write back into rubric.json.

    Only rules that cleared the sample floor are written. A provisional number
    in the rubric would be indistinguishable from a real one the next time
    anybody read it.
    """
    return {s.rule_id: {"precision": s.precision, "verdicts": s.verdicts,
                        "maturity": s.maturity}
            for s in scores if s.verdict_status == "measured"}


def summary(scores) -> str:
    measured = [s for s in scores if s.verdict_status == "measured"]
    if not measured:
        scored = sum(s.verdicts for s in scores)
        return (f"no rule has reached {rubric.MIN_VERDICTS} verdicts "
                f"({scored} finding(s) scored so far)")
    worst = measured[0]
    ranked = sorted(s.precision for s in measured)
    median = ranked[len(ranked) // 2]
    return (f"{len(measured)} rule(s) measured · median precision {median:.2f} · "
            f"worst {worst.rule_id} at {worst.precision:.2f}")
