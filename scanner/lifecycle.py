#!/usr/bin/env python3
"""
How long a finding has been there, from the scans already held.

Of the three ways a number can get into the effort model, this is the one that
needs nobody's cooperation. Actuals arrive when a practitioner records what a
fix took; expert estimates arrive when someone sits down with a worksheet. Both
depend on a person. **Survival does not** — an org with a scan history already
contains the answer, and nothing but arithmetic stands between the data and the
finding record.

What it says is not effort, and this module never pretends otherwise. A finding
on its sixth consecutive scan is one nobody is fixing. That could mean it is
hard, or that it is not worth doing, or that no one has looked — survival cannot
tell those apart, and reading it as "hard" would be exactly the unearned
inference the effort model is being kept honest about. What it *can* say is
which findings the backlog has stopped moving on, and that is worth publishing
on its own terms:

    Survived_Scans__c    consecutive scans reporting this defect, incl. this one
    Resolved_In_Scan__c  the scan by which it had stopped being reported

Identity across scans is (rule_id, component), plus `detail` for the handful of
rules where detail says *which* finding this is rather than describing its
current state. That is deliberately the same identity `backlog._external_id`
uses minus the scan, because a survival count that disagreed with the ticket's
idempotency would be counting a different thing than the ticket tracks.
"""

from __future__ import annotations

import backlog


def _key(row) -> tuple:
    """What makes two findings in different scans the same finding."""
    detail = ""
    if row["rule_id"] in backlog._IDENTITY_DETAIL_RULES:
        # finding_rows folds detail into evidence as "evidence — detail"; the
        # detail is the discriminating half.
        evidence = row.get("evidence") or ""
        detail = evidence.split(" — ", 1)[1] if " — " in evidence else ""
    return (row["rule_id"], row["component_api_name"], detail)


def _sorted_scans(scans) -> list:
    return sorted(scans, key=lambda s: s["scan"]["scan_timestamp"])


def annotate(scans) -> dict:
    """Add survival to every finding row, in place.

    `scans` are scan_result.build() results for **one org**, in any order. Each
    finding gains `survived_scans`, and the last scan that still reported a
    defect gains `resolved_in_scan` naming the scan by which it was gone.

    A gap re-starts the count rather than adding to it. A defect that was fixed,
    regressed, and is now back has been present for one scan, not five — the
    other reading would let a burn-down that went backwards look like steady
    neglect, which is a different problem with a different owner.
    """
    ordered = _sorted_scans(scans)
    seen = {}          # key -> (consecutive count, index of last scan seen in)
    resolved = 0

    for idx, s in enumerate(ordered):
        present = set()
        for row in s["findings"]:
            k = _key(row)
            present.add(k)
            count, last = seen.get(k, (0, None))
            run = count + 1 if last == idx - 1 else 1
            seen[k] = (run, idx)
            row["survived_scans"] = run

        # Anything carried into this scan but not reported by it has gone. The
        # record that gets stamped is the last one that still reported it — the
        # scan it was resolved *in* has no row for it, by definition.
        for k, (count, last) in list(seen.items()):
            if last == idx - 1 and k not in present:
                for row in ordered[last]["findings"]:
                    if _key(row) == k:
                        row["resolved_in_scan"] = s["scan"]["external_scan_id"]
                        resolved += 1
                del seen[k]

    return {"scans": len(ordered), "tracked": len(seen), "resolved": resolved}


def annotate_portfolio(scans) -> dict:
    """Same, for a portfolio spanning several orgs.

    Grouped by org first, because survival is a statement about one org's
    history. Two orgs with the same badly-named field are two defects, and
    letting them share a run would report a survival no scan ever observed.
    """
    by_org = {}
    for s in scans:
        by_org.setdefault(s["scan"]["target_org"], []).append(s)

    totals = {"orgs": len(by_org), "scans": 0, "resolved": 0}
    for org_scans in by_org.values():
        stats = annotate(org_scans)
        totals["scans"] += stats["scans"]
        totals["resolved"] += stats["resolved"]
    return totals


def survival_summary(scans) -> dict:
    """What the survival data says, for a scan report.

    Reported over the findings that survived at all, and over the backlog-emitting
    ones separately: an observation the §4.6 gate never ticketed has survived
    because nobody was ever asked to fix it, and averaging it in with the tickets
    would understate how stuck the real backlog is.
    """
    runs, ticketed = [], []
    for s in scans:
        for row in s["findings"]:
            n = row.get("survived_scans")
            if not n:
                continue
            runs.append(n)
            if row.get("emits_to_backlog"):
                ticketed.append(n)

    def stats(values):
        if not values:
            return {"n": 0, "max": 0, "stuck": 0}
        return {"n": len(values), "max": max(values),
                # Three consecutive scans is two quarters of not being fixed on
                # this portfolio's cadence — long enough to mean something,
                # short enough not to require a year of history to ever fire.
                "stuck": sum(1 for v in values if v >= 3)}

    return {"all": stats(runs), "ticketed": stats(ticketed)}
