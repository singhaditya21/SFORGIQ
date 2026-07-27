"""Per-rule precision, and the maturity ladder it drives.

The line these defend: an unmeasured rule is reported as unmeasured, never as
correct — and a rule only climbs the ladder on evidence that could have stopped
it climbing.
"""

import precision
import rubric

TP, FP = precision.TRUE_POSITIVE, precision.FALSE_POSITIVE


def rows(rule, tp=0, fp=0, suppressed=0):
    out = [{"rule_id": rule, "verdict": TP} for _ in range(tp)]
    out += [{"rule_id": rule, "verdict": FP} for _ in range(fp)]
    for r in out[:suppressed]:
        r["status"] = "Suppressed"
    return out


# ------------------------------------------------------------- counting

def test_a_rule_nobody_has_scored_is_unmeasured_not_perfect():
    """Silence is not agreement. A rule with nothing scored has an unknown
    precision, and reporting it as 1.0 would promote it on no evidence."""
    s = precision.score_rule("D1.X", [{"rule_id": "D1.X"}] * 40)
    assert s.verdicts == 0
    assert s.precision is None
    assert s.verdict_status == "unmeasured"
    assert s.maturity == rubric.DEFAULT_MATURITY


def test_precision_is_true_positives_over_everything_scored():
    s = precision.score_rule("D1.X", rows("D1.X", tp=8, fp=2))
    assert (s.true_positives, s.false_positives, s.verdicts) == (8, 2, 10)
    assert s.precision == 0.8


def test_findings_without_a_verdict_are_skipped_not_counted():
    """A half-scored sample must not be diluted by the half nobody looked at."""
    mixed = rows("D1.X", tp=5) + [{"rule_id": "D1.X"}] * 20
    assert precision.score_rule("D1.X", mixed).verdicts == 5


# ---------------------------------------------------------- the ladder

def test_a_handful_of_verdicts_cannot_promote_a_rule():
    """Three findings at 100% is not a validated rule."""
    s = precision.score_rule("D1.X", rows("D1.X", tp=3))
    assert s.precision == 1.0
    assert s.verdict_status == "provisional"
    assert s.maturity == rubric.DEFAULT_MATURITY


def test_enough_verdicts_at_a_high_enough_precision_promote_it():
    s = precision.score_rule("D1.X", rows("D1.X", tp=20))
    assert s.verdict_status == "measured"
    assert s.maturity == "validated"


def test_the_top_tier_needs_more_evidence_than_the_one_below():
    """Otherwise the ladder has two names for the same thing."""
    validated = precision.score_rule("A", rows("A", tp=20))
    proven = precision.score_rule("B", rows("B", tp=50))
    assert validated.maturity == "validated"
    assert proven.maturity == "field-proven"


def test_a_large_sample_at_a_poor_precision_promotes_nothing():
    """Fifty findings at 50% is not a validated rule either — both floors have
    to hold, or each one alone is gameable."""
    s = precision.score_rule("D1.X", rows("D1.X", tp=25, fp=25))
    assert s.verdicts == 50 and s.precision == 0.5
    assert s.maturity == rubric.DEFAULT_MATURITY


def test_a_rule_below_the_floor_is_named_for_withdrawal():
    """Below it the rule is not experimental, it is broken — and left unnamed it
    stays in the pack indefinitely."""
    s = precision.score_rule("D1.X", rows("D1.X", tp=4, fp=8))
    assert s.withdraw_candidate is True
    assert precision.score_rule("D1.Y", rows("D1.Y", tp=11, fp=1)).withdraw_candidate is False


def test_an_unmeasured_rule_is_never_a_withdrawal_candidate():
    """Not looking at a rule is not evidence against it."""
    assert precision.score_rule("D1.X", []).withdraw_candidate is False


# ------------------------------------------------- correctness vs usefulness

def test_actionability_is_reported_apart_from_precision():
    """A rule can be perfectly precise and still not worth shipping if every
    correct finding is one nobody intends to fix. That is a product question,
    not evidence about the rule, so it must not move the ladder."""
    s = precision.score_rule("D1.X", rows("D1.X", tp=20, suppressed=15))
    assert s.precision == 1.0
    assert s.maturity == "validated"          # correctness promoted it
    assert s.actionability == 0.25            # and usefulness is said separately


def test_suppressing_a_false_positive_does_not_flatter_the_rule():
    """Suppressed means "correct, we accept it". Counting a wrong finding there
    would let a rule launder its own errors."""
    recs = rows("D1.X", tp=10) + [{"rule_id": "D1.X", "verdict": FP,
                                   "status": "Suppressed"}] * 10
    s = precision.score_rule("D1.X", recs)
    assert s.precision == 0.5
    assert s.suppressed == 0


# -------------------------------------------------------------- reporting

def test_rules_are_scored_separately_and_the_worst_comes_first():
    """A pack that is 90% precise on average can be 40% on the rule that fires
    most, and the average is exactly what hides it."""
    recs = rows("Good", tp=30) + rows("Bad", tp=4, fp=16)
    scores = precision.measure(recs)
    assert scores[0].rule_id == "Bad"
    assert scores[0].precision == 0.2
    assert scores[1].precision == 1.0


def test_only_measured_rules_are_written_back_to_the_rubric():
    """A provisional number in the rubric is indistinguishable from a real one
    the next time anybody reads it."""
    recs = rows("Solid", tp=25) + rows("Thin", tp=2)
    patch = precision.rubric_patch(precision.measure(recs))
    assert set(patch) == {"Solid"}
    assert patch["Solid"]["maturity"] == "validated"


def test_the_summary_says_nothing_is_measured_rather_than_implying_success():
    out = precision.summary(precision.measure(rows("D1.X", tp=3)))
    assert "no rule has reached" in out
    assert "3 finding(s) scored" in out


def test_one_verdict_cannot_retire_a_rule_any_more_than_it_can_promote_one():
    """The sample floor has to cut both ways. Without that symmetry the first
    reviewer to disagree with a rule takes it out of the pack — and the report
    said `← withdraw` next to a rule with a single verdict against it."""
    thin = precision.score_rule("D1.X", rows("D1.X", fp=1))
    assert thin.precision == 0.0
    assert thin.verdict_status == "provisional"
    assert thin.withdraw_candidate is False

    enough = precision.score_rule("D1.X", rows("D1.X", tp=2, fp=10))
    assert enough.verdict_status == "measured"
    assert enough.withdraw_candidate is True
