#!/usr/bin/env python3
"""
Did anything get worse since the last scan?

This is the difference between a report and a product. A readiness assessment
someone runs by hand tells you where an org stood on the day they ran it; one
that runs on a cadence and speaks up when the number moves the wrong way is
something a team can actually be held to. It is also the only way the history
this scanner now depends on ever comes into existence — survival counts
consecutive scans, and nothing accumulates scans unless something schedules
them.

Three things count as a regression, and they are deliberately different kinds:

  **The composite fell.** A tolerance applies, because these scores are
  provisional and a one-point move is noise. The tolerance is a floor on what
  gets reported, not a licence to drift: a slow slide shows up as a run of small
  drops against the same baseline, which is why the comparison is against the
  previous scan rather than a rolling average.

  **A Critical appeared.** No tolerance. A Critical D4 finding caps the
  composite at 60 on its own (PRD §4.2), so an org can acquire one while its
  score barely moves — reporting only on the score would miss exactly the
  finding that matters most.

  **A resolved finding came back.** A defect that was fixed and has returned is
  a different and more serious fact than one that was never fixed: something
  undid the work, and nobody was told.

A first scan is not a regression. Neither is an org with no history — both are
"nothing to compare against", which is reported as such rather than as a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

# A move smaller than this is inside the noise of a provisional rubric. Stated
# here rather than buried in a caller so it is one number to argue with.
DEFAULT_TOLERANCE = 3


@dataclass
class OrgVerdict:
    org: str
    status: str                      # regressed | improved | unchanged | no-history
    score_before: int = None
    score_after: int = None
    reasons: list = dc_field(default_factory=list)

    @property
    def regressed(self) -> bool:
        return self.status == "regressed"

    @property
    def delta(self):
        if self.score_before is None or self.score_after is None:
            return None
        return self.score_after - self.score_before


def _criticals(findings) -> set:
    return {(f["rule_id"], f["component_api_name"]) for f in findings
            if f.get("severity") == "Critical"}


def _keys(findings) -> set:
    return {(f["rule_id"], f["component_api_name"]) for f in findings}


def compare(previous, latest, tolerance: int = DEFAULT_TOLERANCE) -> OrgVerdict:
    """Two scans of one org, oldest first. `previous` may be None."""
    org = latest["scan"]["target_org"]
    if previous is None:
        return OrgVerdict(org=org, status="no-history",
                          score_after=latest["scan"]["composite_score"],
                          reasons=["first scan of this org — nothing to compare against"])

    before = previous["scan"]["composite_score"]
    after = latest["scan"]["composite_score"]
    reasons = []

    if before - after > tolerance:
        reasons.append(f"composite fell {before} to {after}")

    # No tolerance: a Critical caps the composite on its own, so an org can
    # acquire one while the score barely moves.
    new_criticals = _criticals(latest["findings"]) - _criticals(previous["findings"])
    if new_criticals:
        reasons.append(f"{len(new_criticals)} new Critical finding(s): "
                       + ", ".join(sorted(r for r, _ in new_criticals)[:3]))

    # Something undid work that had been done.
    #
    # The stamp lives on the LAST scan that still reported the defect — the scan
    # it was resolved in has no row for it, by definition — so a returning
    # finding is one present now whose earlier record was marked resolved. The
    # obvious phrasing ("in this scan but not the previous one") excludes
    # exactly the case it is meant to catch, because the previous scan does
    # carry the row; what it carries is the stamp.
    resolved_before = {(f["rule_id"], f["component_api_name"])
                       for f in previous["findings"] if f.get("resolved_in_scan")}
    returned = _keys(latest["findings"]) & resolved_before
    if returned:
        reasons.append(f"{len(returned)} previously-resolved finding(s) returned")

    if reasons:
        status = "regressed"
    elif after > before:
        status = "improved"
    else:
        status = "unchanged"
    return OrgVerdict(org=org, status=status, score_before=before,
                      score_after=after, reasons=reasons)


def compare_portfolio(scans, tolerance: int = DEFAULT_TOLERANCE) -> list:
    """One verdict per org, worst first.

    Grouped by org and ordered by scan timestamp — the same discipline the
    survival arithmetic uses, and for the same reason: a comparison that spanned
    two orgs would report a regression neither of them had.
    """
    by_org = {}
    for s in scans:
        by_org.setdefault(s["scan"]["target_org"], []).append(s)

    out = []
    for org, group in by_org.items():
        group.sort(key=lambda s: s["scan"]["scan_timestamp"])
        previous = group[-2] if len(group) > 1 else None
        out.append(compare(previous, group[-1], tolerance))

    rank = {"regressed": 0, "no-history": 1, "unchanged": 2, "improved": 3}
    return sorted(out, key=lambda v: (rank[v.status], v.org))


def summary(verdicts) -> str:
    counts = {}
    for v in verdicts:
        counts[v.status] = counts.get(v.status, 0) + 1
    parts = [f"{n} {status}" for status, n in sorted(counts.items())]
    return ", ".join(parts) if parts else "nothing scanned"
