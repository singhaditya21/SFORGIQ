#!/usr/bin/env python3
"""
Personas: what a given identity can actually do, and how far a component reaches.

An agent is not a new kind of actor. It runs as a user, under a profile and a set
of permission sets, and it can therefore do exactly what that persona can do —
no more, and no less. So the question "what can this agent reach?" is the same
question as "what can this persona reach?", and the answer is spread across five
kinds of metadata that no one file holds:

    profile / permission set   which objects and fields, and what rights over them
    layout                     what is actually put in front of them, and which buttons
    flow                       the processes they can start
    approval process           the processes they take part in
    validation rule            what will refuse their save

Read together they reconstruct a **capability surface**. That surface is the
honest answer to a blast-radius question, and it is also the thing a reviewer
recognises: "the Service Agent persona can edit Policy, sees 40 of its 120
fields, can start three flows, approves nothing, and will be blocked by two
validation rules."

Two limits are stated rather than hidden. Effective access is profile plus
permission sets plus permission set groups minus muting, and metadata alone does
not say which users hold which — so a surface built here is the access a persona
*grants*, not the access a named human ended up with. And sharing rules decide
record-level visibility on a different axis entirely; nothing here models them.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field


def _Finding(*args):
    """Late import, for the same reason external.py does it: `Finding` lives in
    the D1 scanner, which imports scan_result, which imports this module — so a
    module-level import closes the cycle and breaks whichever entry point is
    loaded first."""
    from orgiq_spike import Finding
    return Finding(*args)


# Rights that reach every record of an object regardless of sharing, and so make
# a persona's reach unbounded rather than merely wide.
_BLANKET = ("ModifyAllData", "ViewAllData")


@dataclass
class Persona:
    """One identity's capability surface, assembled from everything that grants
    or constrains it."""
    name: str
    kind: str = "PermissionSet"          # Profile | PermissionSet
    objects_editable: tuple = ()
    objects_readable: tuple = ()
    objects_deletable: tuple = ()
    blanket_perms: tuple = ()            # ModifyAllData / ViewAllData
    fields_visible: tuple = ()           # "Object.Field" surfaced by an assigned layout
    actions: tuple = ()                  # buttons / quick actions on those layouts
    flows: tuple = ()                    # processes this persona can start
    approvals: tuple = ()                # approval processes it takes part in
    blocked_by: tuple = ()               # validation rules on objects it can edit

    @property
    def unbounded(self) -> bool:
        return bool(self.blanket_perms)

    @property
    def reach(self) -> int:
        """A single number for how much of the org this persona touches. Blunt on
        purpose — it is for ordering personas against each other, not for
        reporting as a measurement."""
        return (len(self.objects_editable) * 3 + len(self.objects_readable)
                + len(self.fields_visible) + len(self.flows) * 2
                + len(self.actions))


def _obj_names(perms, pred) -> tuple:
    return tuple(sorted({op.object_name for op in perms if pred(op)}))


def build_personas(meta) -> list:
    """Every profile and permission set in the org, as capability surfaces."""
    layouts = {l.api_name: l for l in getattr(meta, "layouts", ())}
    approvals = getattr(meta, "approval_processes", ())
    vrules = getattr(meta, "validation_rules", ())
    flows = {f.api_name: f for f in getattr(meta, "flows", ())}

    out = []
    for src, kind in ([(p, "Profile") for p in getattr(meta, "profiles", ())]
                      + [(p, "PermissionSet") for p in getattr(meta, "permission_sets", ())]):
        perms = getattr(src, "object_perms", []) or []
        editable = _obj_names(perms, lambda o: o.allow_edit or o.modify_all)
        readable = _obj_names(perms, lambda o: True)
        deletable = _obj_names(perms, lambda o: o.allow_delete)

        # Only a profile carries layout assignments and flow access; a permission
        # set's reach is what its object rights say, which is why a persona built
        # from one has no visible-field list rather than an empty-because-none.
        seen_fields, actions = [], []
        for name in getattr(src, "layout_assignments", ()):
            lay = layouts.get(name)
            if not lay:
                continue
            seen_fields += [f"{lay.object_name}.{f}" for f in lay.fields]
            actions += list(lay.actions)

        runnable = tuple(f for f in getattr(src, "flow_access", ()) if f in flows or not flows)

        # An approval process on an object this persona can edit is a process it
        # takes part in — either raising the record or being asked to sign it.
        involved = tuple(a.api_name for a in approvals
                         if a.active and a.object_name in editable)
        blocked = tuple(v.api_name for v in vrules
                        if v.active and v.object_name in editable)

        out.append(Persona(
            name=getattr(src, "label", "") or src.api_name,
            kind=kind,
            objects_editable=editable,
            objects_readable=readable,
            objects_deletable=deletable,
            blanket_perms=tuple(p for p in _BLANKET if src.has_perm(p)),
            fields_visible=tuple(dict.fromkeys(seen_fields)),
            actions=tuple(dict.fromkeys(actions)),
            flows=runnable,
            approvals=involved,
            blocked_by=blocked,
        ))
    return out


# --------------------------------------------------------- blast radius

def blast_index(meta, personas=None) -> dict:
    """How many things depend on each component.

    `blast_radius` on a finding was hardcoded to 0 from the first commit, which
    meant a backlog could be ordered by severity but never by consequence. This
    is the count that fixes it: for a field, how many reports read it, how many
    layouts surface it, and how many personas can see it. Retiring a field forty
    reports depend on is not the same job as retiring one nobody has opened in
    five years, and until now a ticket could not tell you which you had.

    Keyed on both "Object.Field" and the bare field name, because findings name
    components in both shapes.
    """
    personas = personas if personas is not None else build_personas(meta)
    refs = getattr(meta, "report_refs", None)
    counts = {}

    def bump(key, n=1):
        if key:
            counts[key] = counts.get(key, 0) + n

    # reports and dashboards
    if refs is not None:
        for key, n in getattr(refs, "refs", {}).items():
            bump(key, n)

    # layouts that surface the field
    for lay in getattr(meta, "layouts", ()):
        for f in lay.fields:
            bump(f"{lay.object_name}.{f}")
            bump(f)

    # personas that can see it
    for p in personas:
        for qualified in p.fields_visible:
            bump(qualified)
            bump(qualified.split(".", 1)[-1])

    return counts


def radius_for(component: str, index: dict) -> int:
    """Dependants of the component a finding names. Falls back to the bare field
    name, and returns 0 for the group components ("Obj [3 fields]") that name a
    cluster rather than one thing."""
    if not component or "[" in component:
        return 0
    hit = index.get(component)
    if hit:
        return hit
    return index.get(component.split(".", 1)[-1], 0)


# ------------------------------------------------------------- D4 rules

def persona_findings(personas) -> list:
    """What a persona's own shape says about the blast radius of an agent that
    runs as it."""
    out = []
    for p in personas:
        if p.unbounded:
            out.append(_Finding(
                "D4.PERSONA_UNBOUNDED", "D4", "Critical", "High", p.name,
                f"{p.kind} grants {' and '.join(p.blanket_perms)} — an agent running as "
                f"this persona reaches every record of every object, whatever sharing says",
                f"editable objects: {len(p.objects_editable)}"))

        # Editing far more than you are ever shown is the shape of a persona
        # assembled by accumulation rather than designed for a job.
        shown = {f.split(".", 1)[0] for f in p.fields_visible}
        unshown = [o for o in p.objects_editable if o not in shown]
        if p.fields_visible and len(unshown) >= 3:
            out.append(_Finding(
                "D4.PERSONA_BEYOND_PROCESS", "D4", "Medium", "Medium", p.name,
                f"can edit {len(unshown)} object(s) that no layout assigned to it ever "
                f"surfaces — access without a process to justify it",
                " | ".join(sorted(unshown)[:8])))

        if p.objects_deletable and not p.unbounded:
            out.append(_Finding(
                "D4.PERSONA_CAN_DELETE", "D4", "Medium", "Medium", p.name,
                f"can delete records on {len(p.objects_deletable)} object(s) — rarely "
                f"required by an agent, and irreversible when it is wrong",
                " | ".join(p.objects_deletable[:8])))
    return out
