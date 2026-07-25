#!/usr/bin/env python3
"""
Cross-org drift: where an enterprise's orgs disagree with each other.

Every other rule pack answers "what is wrong with this org". This one answers a
question no single-org scan can even ask — **do these orgs still match?** — and
it only became askable once a scan belonged to an org and an org to an estate.

Why it belongs in a readiness tool. An agent is validated in one org and run in
another. If the org it was tested in has forty fields the production org does
not, the test proved nothing about production: the retriever saw a different
corpus, the planner saw a different action surface, and the permissions the
agent ran under were a different set. Drift is not untidiness — it is the reason
a passing UAT test can be followed by a failing production agent.

**Production is the reference**, because it is the org the agent will actually
run in; everything else is measured against it. Where an estate has no
production org, the largest is used and the finding says so.

**Direction matters, and severity is not symmetric.** A developer sandbox that
runs ahead of production is a sandbox doing its job — that is where unreleased
work lives. A UAT org that has fallen behind production is a broken control: it
is the org sign-off is given in. So the same raw difference is reported very
differently depending on which org carries it.

Findings are grouped, not itemised: "UAT is missing 12 fields present in
production" is one ticket with the twelve named, not twelve tickets. The remedy
is a single refresh or a single release, so twelve rows would be twelve copies
of one decision.

Drift findings carry `Drift` as their dimension rather than D1–D5. They are real
work and they reach the backlog, but they are a property of a *pair* of orgs, so
letting them penalise this org's grounding or automation score would be scoring
one org for another org's state.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field

from orgiq_spike import Finding

DIMENSION = "Drift"

# How much it matters that this org disagrees with production.
#
# The release path is what sign-off rests on: UAT and Staging are where an agent
# is proven, so a gap there invalidates the proof. Developer sandboxes are meant
# to differ. Orgs off the path entirely — an acquisition, a frozen legacy
# instance — are not pretending to match, and reporting them as broken would
# bury the ones that are.
_RELEASE_PATH = {"UAT": "High", "Staging": "High", "QA": "Medium", "Training": "Low"}
_OFF_PATH = {"Developer", "Other", "Production"}

# Below this, a difference is noise: an org is always a few fields out of step.
_MIN_FIELDS = 3


@dataclass
class OrgSnapshot:
    """What one org looked like at scan time — enough to compare, no more."""
    name: str
    org_type: str = "Other"
    fields: tuple = ()            # api names, qualified "Object.Field"
    triggers: tuple = ()
    flows: tuple = ()
    perm_sets: tuple = ()


def _sev_for(org_type: str, count: int, behind: bool) -> str:
    """Severity of a gap, from where the org sits and how big the gap is.

    Only orgs on the release path escalate, and only when they are *behind* —
    an org missing what production has is an org whose test does not cover
    production. Running ahead is normal everywhere and never rated above Medium.
    """
    if not behind:
        return "Medium" if count >= 12 else "Low"
    base = _RELEASE_PATH.get(org_type, "Low" if org_type in _OFF_PATH else "Medium")
    if base == "High" and count >= 20:
        return "Critical"
    if base == "Medium" and count >= 25:
        return "High"
    return base


def _names(items, limit: int = 8) -> str:
    shown = sorted(items)[:limit]
    extra = len(items) - len(shown)
    return " | ".join(shown) + (f" | +{extra} more" if extra > 0 else "")


def pick_reference(snapshots):
    """The org everything else is measured against."""
    for s in snapshots:
        if s.org_type == "Production":
            return s, ""
    if not snapshots:
        return None, ""
    biggest = max(snapshots, key=lambda s: len(s.fields))
    return biggest, (" (no production org in this estate — compared against "
                     f"{biggest.name}, its largest)")


def compare_estate(snapshots) -> dict:
    """Findings per org name. The reference org gets none: it is the baseline,
    not a deviation from itself."""
    ref, caveat = pick_reference(snapshots)
    if ref is None or len(snapshots) < 2:
        return {}

    ref_fields, ref_auto = set(ref.fields), set(ref.triggers) | set(ref.flows)
    ref_perms = set(ref.perm_sets)
    out = {}

    for s in snapshots:
        if s.name == ref.name:
            continue
        found = []

        missing = ref_fields - set(s.fields)
        if len(missing) >= _MIN_FIELDS:
            found.append(Finding(
                "DRIFT.BEHIND_REFERENCE", DIMENSION,
                _sev_for(s.org_type, len(missing), behind=True), "High", s.name,
                f"{len(missing)} field(s) exist in {ref.name} but not here — an agent "
                f"validated against this org was not validated against that schema{caveat}",
                _names(missing)))

        extra = set(s.fields) - ref_fields
        if len(extra) >= _MIN_FIELDS:
            found.append(Finding(
                "DRIFT.AHEAD_OF_REFERENCE", DIMENSION,
                _sev_for(s.org_type, len(extra), behind=False), "High", s.name,
                f"{len(extra)} field(s) exist here but not in {ref.name} — unreleased, "
                f"or local and never promoted{caveat}",
                _names(extra)))

        auto = (set(s.triggers) | set(s.flows)) ^ ref_auto
        if auto:
            found.append(Finding(
                "DRIFT.AUTOMATION_DIVERGED", DIMENSION,
                "High" if s.org_type in _RELEASE_PATH else "Medium", "High", s.name,
                f"{len(auto)} automation component(s) differ from {ref.name} — the agent's "
                f"writes will not trigger the same chain in both orgs{caveat}",
                _names(auto)))

        perms = set(s.perm_sets) ^ ref_perms
        if perms:
            found.append(Finding(
                "DRIFT.PERMISSION_DIVERGED", DIMENSION,
                "High" if s.org_type in _RELEASE_PATH else "Medium", "Medium", s.name,
                f"{len(perms)} permission set(s) differ from {ref.name} — the agent will "
                f"run with different reach in each{caveat}",
                _names(perms)))

        if found:
            out[s.name] = found
    return out


def snapshot_from(name, org_type, fields, meta) -> OrgSnapshot:
    """Build a snapshot from what a scan already parsed."""
    return OrgSnapshot(
        name=name,
        org_type=org_type,
        fields=tuple(f"{f.object_name}.{f.api_name}" for f in fields),
        triggers=tuple(t.api_name for t in getattr(meta, "triggers", ())),
        flows=tuple(f.api_name for f in getattr(meta, "flows", ())),
        perm_sets=tuple(p.api_name for p in getattr(meta, "permission_sets", ())),
    )
