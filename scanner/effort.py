#!/usr/bin/env python3
"""
Effort estimation, and the loop that would calibrate it.

The problem this addresses is stated plainly in the PRD's own risk register:
effort estimates are uncalibrated, and they carry the whole value claim, because
a backlog beats a dashboard only when the work can be costed. Twenty-five
hardcoded integers were doing that job, and every finding of a given rule got
the same number whatever its circumstances.

Two things can be fixed honestly without engagement data, and one cannot.

**Fixable: make the estimate responsive to measured evidence.** Retiring a field
forty reports depend on is not the same job as retiring one nobody reads — you
have to find and clear every consumer first. Consolidating a two-field duplicate
cluster is not the same as an eight-field one. Changing production is not the
same as changing a developer sandbox. All three of those are things this scanner
now measures, so the estimate should move with them instead of ignoring them.

**Fixable: build the feedback loop.** OrgIQ_Finding__c carries an actual-effort
field, `calibrate()` compares estimates against whatever actuals have been
recorded, and the report says how many engagements are behind the model. With no
actuals it says zero — which is the current, true answer.

**Not fixable here: the base numbers.** They remain judgement, and no amount of
multiplying makes them measured. So every estimate is stamped with its basis,
`MODEL_VERSION` moves when the model changes, and nothing in this file claims a
number is calibrated until `calibrate()` has been fed real outcomes. An estimate
that says "uncalibrated" is worth more than one that quietly implies otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass

import rubric

# Bumped whenever a multiplier or the scale changes, so an actual recorded
# against an old estimate is never silently compared with a new model.
MODEL_VERSION = rubric.EFFORT_MODEL_VERSION

# The scale the playbook already speaks. Estimates snap to it: a model that
# emits 4.7 implies a precision none of this has.
SCALE = rubric.EFFORT_SCALE

# How many dependants make a fix meaningfully harder. Coarse on purpose — the
# evidence supports "more consumers means more coordination", not a curve.
_BLAST_BANDS = rubric.BLAST_BANDS

# Changing the org of record costs more than changing a sandbox: a release
# window, change control, and the rollback plan someone will actually ask for.
#
# The numbers are bounded below by the scale, not only by judgement. Successive
# stops are ~1.6x apart, so any factor under about 1.4 can never move an estimate
# on its own — it would sit in the code looking like it did something. So either
# a factor is big enough to matter alone, or it is here only to compound with
# others, and 1.1 is exactly that: a shared environment adds a little, and shows
# up only when something else has already pushed the estimate to a boundary.
_ORG_TYPE = rubric.ORG_TYPE_FACTOR


@dataclass
class Estimate:
    points: int
    basis: str                  # human-readable derivation
    model: str = MODEL_VERSION
    calibrated: bool = False    # True only once actuals have fitted the model


def _snap(value: float) -> int:
    """Nearest point on the scale, never below its first stop."""
    return min(SCALE, key=lambda s: (abs(s - value), s))


def _blast_factor(blast: int):
    for floor, factor, why in _BLAST_BANDS:
        if blast >= floor:
            return factor, why
    return 1.0, "no dependency data"


def _group_factor(size: int):
    """A cluster is one decision and N executions.

    Neither 1x (the members still have to be migrated one by one) nor Nx (you
    decide once). Grows sub-linearly and stops: past a point the work is a
    migration script, not N conversations.
    """
    if size <= 1:
        return 1.0, ""
    g = rubric.GROUP_FACTOR
    factor = min(g["cap"], 1.0 + g["per_extra_member"] * (size - 1))
    return factor, f"{size}-member cluster"


def estimate(rule_id: str, base_points: int, blast: int = 0,
             group_size: int = 1, org_type: str = "") -> Estimate:
    """Effort for one finding, from its own measured circumstances.

    `base_points` is the playbook's judgement for the rule; everything else is
    something this scan actually measured. Passing none of it returns the base
    unchanged, so a caller with no evidence gets exactly the old behaviour rather
    than an invented adjustment.
    """
    reasons = []
    factor = 1.0

    bf, why = _blast_factor(blast)
    if bf != 1.0:
        factor *= bf
        reasons.append(why)

    gf, why = _group_factor(group_size)
    if gf != 1.0:
        factor *= gf
        reasons.append(why)

    of, why = _ORG_TYPE.get(org_type, (1.0, ""))
    if of != 1.0:
        factor *= of
        reasons.append(why)

    points = _snap(base_points * factor)
    # Only report an adjustment that actually moved the number. At the bottom of
    # the scale a 1.5x on a base of 1 rounds back to 1, and saying "consumers
    # must be checked" next to an unchanged estimate reads as a factor that was
    # applied when nothing was.
    if points == base_points:
        reasons = [r + " (below the scale's resolution)" for r in reasons[:1]] if reasons else []
    basis = (f"base {base_points}" +
             ("; " + "; ".join(reasons) if reasons else "") +
             f" ({MODEL_VERSION})")
    return Estimate(points=points, basis=basis)


# ------------------------------------------------------------ calibration

@dataclass
class Calibration:
    """What the actuals say about the model. Every field is 'so far' — this is a
    report on the evidence available, not a verdict on the model."""
    samples: int = 0
    mean_ratio: float = 0.0        # actual / estimated
    median_ratio: float = 0.0
    within_half_band: float = 0.0  # share landing within one scale stop
    by_rule: dict = None
    verdict: str = "uncalibrated — no recorded actuals"

    @property
    def is_calibrated(self) -> bool:
        return self.samples >= MIN_SAMPLES


# Below this the ratios are anecdote. Chosen so a single unusual engagement
# cannot move the model, and stated rather than buried.
MIN_SAMPLES = rubric.EFFORT_MIN_SAMPLES


def calibrate(records) -> Calibration:
    """Compare estimates against recorded actuals.

    `records` are dicts with `rule_id`, `effort_points` and `actual_effort` —
    exactly what a finding carries once someone has closed the ticket and written
    down what it took. Findings with no actual are skipped, not counted as
    agreeing.
    """
    pairs = [(r.get("rule_id", "?"), float(r["effort_points"]), float(r["actual_effort"]))
             for r in (records or [])
             if r.get("effort_points") and r.get("actual_effort")]
    if not pairs:
        return Calibration(by_rule={})

    ratios = sorted(a / e for _, e, a in pairs)
    n = len(ratios)
    mean = sum(ratios) / n
    median = ratios[n // 2] if n % 2 else (ratios[n // 2 - 1] + ratios[n // 2]) / 2
    within = sum(1 for _, e, a in pairs if abs(a - e) <= max(1, e * 0.5)) / n

    by_rule = {}
    for rule, e, a in pairs:
        acc = by_rule.setdefault(rule, {"n": 0, "ratio": 0.0})
        acc["n"] += 1
        acc["ratio"] += a / e
    for acc in by_rule.values():
        acc["ratio"] = round(acc["ratio"] / acc["n"], 2)

    if n < MIN_SAMPLES:
        verdict = (f"{n} actual(s) recorded — under the {MIN_SAMPLES} needed before "
                   f"the model should be moved on this evidence")
    elif 0.8 <= median <= 1.25:
        verdict = f"calibrated on {n} actual(s); median actual/estimate {median:.2f}"
    else:
        direction = "under" if median > 1 else "over"
        verdict = (f"{n} actual(s) say the model {direction}-estimates by "
                   f"{abs(1 - median) * 100:.0f}% — base points should move")

    return Calibration(samples=n, mean_ratio=round(mean, 2),
                       median_ratio=round(median, 2),
                       within_half_band=round(within, 2),
                       by_rule=by_rule, verdict=verdict)
