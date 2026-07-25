"""Effort estimation and calibration.

The line this file defends: the model may adjust an estimate on evidence it
actually measured, and may not imply calibration it does not have.
"""

import effort


def pts(**kw):
    return effort.estimate("D1.X", kw.pop("base", 3), **kw).points


# ------------------------------------------------------------- estimates

def test_with_no_evidence_the_estimate_is_the_playbook_number():
    """A caller that measured nothing gets the base back, not an invented
    adjustment — otherwise every scan would silently inflate its own backlog."""
    e = effort.estimate("D1.X", 3)
    assert e.points == 3
    assert e.basis.startswith("base 3")
    assert e.calibrated is False


def test_more_dependants_costs_more():
    """Retiring a field forty reports read is not the job retiring a dead one is:
    every consumer has to be cleared first."""
    assert pts(base=3, blast=0) < pts(base=3, blast=20)


def test_dependant_bands_are_coarse_rather_than_a_curve():
    """The evidence supports 'more consumers, more coordination'. It does not
    support a smooth function, and pretending otherwise implies precision."""
    assert pts(base=3, blast=6) == pts(base=3, blast=15)


def test_a_bigger_cluster_costs_more_but_not_proportionally():
    """One decision, N executions. Neither 1x nor Nx."""
    two, eight = pts(base=3, group_size=2), pts(base=3, group_size=8)
    assert two < eight < 8 * 3


def test_changing_production_costs_more_than_a_sandbox():
    assert pts(base=5, org_type="Developer") < pts(base=5, org_type="Production")


def test_estimates_stay_on_the_scale():
    """A model that emits 4.7 implies a precision none of this has."""
    for blast in (0, 3, 9, 40):
        for size in (1, 2, 5, 12):
            assert pts(base=3, blast=blast, group_size=size) in effort.SCALE


def test_the_basis_never_claims_an_adjustment_that_changed_nothing():
    """At the bottom of the scale a 1.5x on a base of 1 rounds back to 1. Saying
    'consumers must be checked' next to an unchanged number reads as a factor
    that was applied when none was."""
    e = effort.estimate("D1.X", 1, blast=10)
    if e.points == 1:
        assert "below the scale's resolution" in e.basis


def test_every_estimate_names_the_model_that_produced_it():
    """An actual recorded against one model must never be silently compared with
    another."""
    assert effort.MODEL_VERSION in effort.estimate("D1.X", 3).basis


# ----------------------------------------------------------- calibration

def test_no_actuals_means_uncalibrated_and_says_so():
    cal = effort.calibrate([])
    assert cal.samples == 0
    assert cal.is_calibrated is False
    assert "uncalibrated" in cal.verdict


def test_findings_without_an_actual_are_skipped_not_counted_as_agreeing():
    """Silence is not agreement. Counting unfinished work as a match would show
    a calibrated model built on nothing."""
    cal = effort.calibrate([{"rule_id": "R", "effort_points": 3, "actual_effort": None},
                            {"rule_id": "R", "effort_points": 3}])
    assert cal.samples == 0


def test_a_handful_of_actuals_is_not_enough_to_move_the_model():
    cal = effort.calibrate([{"rule_id": "R", "effort_points": 3, "actual_effort": 6}] * 5)
    assert cal.samples == 5
    assert cal.is_calibrated is False
    assert str(effort.MIN_SAMPLES) in cal.verdict


def test_enough_actuals_that_agree_report_the_model_as_calibrated():
    cal = effort.calibrate([{"rule_id": "R", "effort_points": 3, "actual_effort": 3}]
                           * effort.MIN_SAMPLES)
    assert cal.is_calibrated is True
    assert "calibrated on" in cal.verdict
    assert cal.median_ratio == 1.0


def test_enough_actuals_that_disagree_say_which_way_and_by_how_much():
    cal = effort.calibrate([{"rule_id": "R", "effort_points": 2, "actual_effort": 6}]
                           * effort.MIN_SAMPLES)
    assert "under-estimates" in cal.verdict
    assert cal.median_ratio == 3.0


def test_calibration_is_reported_per_rule_so_a_bad_rule_is_findable():
    """A model can be right on average and badly wrong on one rule. Averaging
    that away is how a broken estimate survives."""
    cal = effort.calibrate(
        [{"rule_id": "Good", "effort_points": 3, "actual_effort": 3}] * 20 +
        [{"rule_id": "Bad", "effort_points": 1, "actual_effort": 8}] * 20)
    assert cal.by_rule["Good"]["ratio"] == 1.0
    assert cal.by_rule["Bad"]["ratio"] == 8.0
