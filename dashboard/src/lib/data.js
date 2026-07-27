// Data loading + domain metadata + derivations for the OrgIQ dashboard.

// Demo mode reads the bundled portfolio exported from the OrgIQ Salesforce org.
// (A future live mode would swap this for an OAuth'd Salesforce REST query.)
export async function loadPortfolio() {
  const res = await fetch(`${import.meta.env.BASE_URL}portfolio.json`)
  if (!res.ok) throw new Error(`could not load portfolio (${res.status})`)
  return res.json()
}

// Readiness bands (PRD §4.3).
export const BAND_ORDER = [
  'Not Ready',
  'Foundational Work Required',
  'Conditionally Ready',
  'Ready',
]
export const BAND_META = {
  'Not Ready': { key: 'not-ready', short: 'Not Ready', blurb: 'Agent deployment will fail. Foundational remediation required first.' },
  'Foundational Work Required': { key: 'foundational', short: 'Foundational', blurb: 'Narrow, low-risk agents feasible. Broad deployment is not.' },
  'Conditionally Ready': { key: 'conditional', short: 'Conditional', blurb: 'Deploy with named mitigations and a monitoring plan.' },
  Ready: { key: 'ready', short: 'Ready', blurb: 'No structural blockers identified.' },
}
export function bandKey(band) { return BAND_META[band]?.key ?? 'not-ready' }

export const SEVERITY_ORDER = ['Critical', 'High', 'Medium', 'Low']

// Rule display metadata.
//
// `label` is dashboard-only. `epic` and `acceptance` are a MIRROR of
// scanner/backlog.py `_PLAYBOOK` — that file is the source of truth, this is a
// cache for findings exported before the org carried Epic__c /
// Acceptance_Criteria__c. When a rule is added or its playbook wording changes
// in backlog.py, update it here too, verbatim: a silent drift here shows up as
// two different epic names for the same rule in the same backlog.
export const RULE_META = {
  'D1.MISSING_DESCRIPTION': {
    label: 'Missing description',
    epic: 'Add missing field descriptions',
    acceptance: 'Field has a non-empty description that states its business meaning '
      + '(not just a restatement of the label). Re-scan reports no '
      + 'D1.MISSING_DESCRIPTION for this field.',
  },
  'D1.LOW_INFO_DESCRIPTION': {
    label: 'Label-restating description',
    epic: 'Replace label-restating field descriptions',
    acceptance: 'Description carries information beyond the label. Re-scan reports no '
      + 'D1.LOW_INFO_DESCRIPTION for this field.',
  },
  'D1.CRYPTIC_API_NAME': {
    label: 'Cryptic field name',
    epic: 'Clarify cryptic field names',
    acceptance: 'Field is unambiguous to a reader with no tribal knowledge — via a clear '
      + 'description and/or a readable API name. Re-scan reports no '
      + 'D1.CRYPTIC_API_NAME for this field.',
  },
  'D1.NUMBERED_FAMILY': {
    label: 'Numbered field family',
    epic: 'Resolve numbered field families',
    acceptance: 'Either the group is modelled as a related list, or each member carries a '
      + 'distinct, disambiguating description. Re-scan reports no '
      + 'D1.NUMBERED_FAMILY for this object, or a smaller family.',
  },
  'D1.SEMANTIC_DUPLICATE': {
    label: 'Duplicate field',
    epic: 'Consolidate duplicate fields',
    acceptance: 'One canonical field remains; duplicates are deprecated with data and '
      + 'references migrated. Re-scan reports no D1.SEMANTIC_DUPLICATE for this cluster.',
  },
  'D1.UNREFERENCED_FIELD': {
    label: 'Unreferenced field',
    epic: 'Retire unreferenced fields',
    acceptance: "Field is deleted, or retained with a documented reason and hidden from the "
      + "agent's layouts and permissions. Absence of references was verified against "
      + 'integrations and managed packages, not just the committed report metadata. '
      + 'Re-scan reports no D1.UNREFERENCED_FIELD for this field.',
  },
  'DRIFT.BEHIND_REFERENCE': {
    label: 'Behind production',
    epic: 'Realign environments with production',
    acceptance: 'This org carries the production components an agent is validated against.',
  },
  'DRIFT.AHEAD_OF_REFERENCE': {
    label: 'Ahead of production',
    epic: 'Promote or retire unreleased components',
    acceptance: 'Every component here is released, in an open change, or documented as org-local.',
  },
  'DRIFT.AUTOMATION_DIVERGED': {
    label: 'Automation diverged',
    epic: 'Realign automation across environments',
    acceptance: 'An identical agent write triggers the same automation in this org and the reference.',
  },
  'DRIFT.PERMISSION_DIVERGED': {
    label: 'Permissions diverged',
    epic: 'Realign agent permissions across environments',
    acceptance: 'The agent identity holds the same permissions here as in the reference org.',
  },
  'D2.LOW_FILL_RATE': {
    label: 'Low fill rate',
    epic: 'Backfill under-populated fields',
    acceptance: 'Fill rate on the field exceeds the grounding threshold; re-scan clears the finding.',
  },
  'D2.STALE_DATA': {
    label: 'Stale data',
    epic: 'Refresh stale data',
    acceptance: 'Stale-record ratio falls below threshold; re-scan clears the finding.',
  },
  'D2.DUPLICATE_RECORDS': {
    label: 'Duplicate records',
    epic: 'De-duplicate records',
    acceptance: 'Duplicate rate below threshold; re-scan clears the finding.',
  },
  'D3.NO_SAFE_ACTIONS': {
    label: 'No safe actions',
    epic: 'Build a safe action surface',
    acceptance: 'At least one bulk-safe invocable action exists per intended task; re-scan clears the finding.',
  },
  'D3.UNDOCUMENTED_ACTION': {
    label: 'Undocumented action',
    epic: 'Document invocable actions',
    acceptance: 'Action carries a planner-usable description; re-scan clears the finding.',
  },
  'D3.APEX_NO_TESTS': {
    label: 'Untested Apex',
    epic: 'Cover agent-invoked Apex with tests',
    acceptance: 'Class has meaningful test coverage; re-scan clears the finding.',
  },
  'D3.INACTIVE_ACTION': {
    label: 'Inactive flow',
    epic: 'Activate or retire dormant flows',
    acceptance: 'No Draft/Obsolete flow is exposed as an agent action; re-scan clears it.',
  },
  'D4.PERSONA_UNBOUNDED': {
    label: 'Persona unbounded',
    epic: "Bound the agent persona's reach",
    acceptance: 'The persona grants no Modify All Data or View All Data and the agent still completes its tasks.',
  },
  'D4.PERSONA_BEYOND_PROCESS': {
    label: 'Access without a process',
    epic: 'Align persona access with its process',
    acceptance: 'Every object the persona can edit is one it has a process for.',
  },
  'D4.PERSONA_CAN_DELETE': {
    label: 'Persona can delete',
    epic: 'Remove unnecessary delete rights',
    acceptance: 'Delete is granted only where a task requires it.',
  },
  'D4.MODIFY_ALL_DATA': {
    label: 'Modify All Data',
    epic: 'Remove Modify All Data from the agent',
    acceptance: 'Agent permission set no longer grants Modify All Data; re-scan clears the finding.',
  },
  'D4.VIEW_ALL_DATA': {
    label: 'View All Data',
    epic: 'Remove View All Data from the agent',
    acceptance: 'Agent permission set no longer grants View All Data; re-scan clears the finding.',
  },
  'D4.WIDE_OBJECT_ACCESS': {
    label: 'Over-broad access',
    epic: 'Tighten over-broad object access',
    acceptance: 'Object access matches task scope; re-scan clears the finding.',
  },
  'D4.DELETE_GRANTED': {
    label: 'Delete granted',
    epic: 'Remove unnecessary delete rights',
    acceptance: 'Delete is granted only where a task requires it; re-scan clears it.',
  },
  'D5.DML_IN_LOOP': {
    label: 'DML in loop',
    epic: 'Bulkify automation',
    acceptance: 'No DML in loops on the automation path; bulk tests pass; re-scan clears the finding.',
  },
  'D5.SOQL_IN_LOOP': {
    label: 'SOQL in loop',
    epic: 'Bulkify automation',
    acceptance: 'No SOQL inside loops on the automation path; re-scan clears it.',
  },
  'D5.MULTIPLE_TRIGGERS': {
    label: 'Multiple triggers',
    epic: 'Consolidate triggers per object',
    acceptance: 'One trigger per object with defined order; re-scan clears the finding.',
  },
  'D5.NO_RECURSION_GUARD': {
    label: 'No recursion guard',
    epic: 'Add recursion guards',
    acceptance: 'Automation is recursion-safe; re-scan clears the finding.',
  },
  'D5.TRIGGER_AND_FLOW': {
    label: 'Trigger + flow collision',
    epic: 'Resolve trigger/flow ordering collisions',
    acceptance: 'One deterministic automation path per object; re-scan clears it.',
  },
}
// Mirrors backlog._UNKNOWN — a rule the dashboard build predates still needs an
// epic and an acceptance line, or its ticket imports without either.
const UNKNOWN_RULE = {
  epic: 'Grounding quality findings',
  acceptance: 'Re-scan no longer reports this finding for the component.',
}
export function ruleLabel(ruleId) { return RULE_META[ruleId]?.label ?? ruleId }

// ---- per-org rollups ----------------------------------------------------
export function orgEffort(findings) {
  return findings.filter((f) => f.emitsToBacklog).reduce((s, f) => s + (f.effortPoints || 0), 0)
}
export function orgBacklogCount(findings) {
  return findings.filter((f) => f.emitsToBacklog).length
}
export function topIssue(findings) {
  const c = {}
  for (const f of findings) c[f.ruleId] = (c[f.ruleId] || 0) + 1
  const best = Object.entries(c).sort((a, b) => b[1] - a[1])[0]
  return best ? ruleLabel(best[0]) : '—'
}

// Flatten to a per-org summary row used by the portfolio table + quadrant.
export function orgRows(scans) {
  return scans.map((s) => ({
    externalId: s.scan.externalId,
    name: s.scan.targetOrg,
    mode: s.scan.scanMode,
    composite: s.scan.compositeScore,
    band: s.scan.readinessBand,
    findings: s.findings.length,
    backlog: orgBacklogCount(s.findings),
    effort: orgEffort(s.findings),
    topIssue: topIssue(s.findings),
  }))
}

// ---- portfolio aggregates ----------------------------------------------
export function portfolioStats(scans) {
  const rows = orgRows(scans)
  const n = rows.length || 1
  const allFindings = scans.flatMap((s) => s.findings)
  const sev = severityCounts(allFindings)
  const totalFindings = rows.reduce((s, r) => s + r.findings, 0)
  const totalComponents = scans.reduce((s, x) => s + (x.scan.componentsScanned || 0), 0)
  return {
    orgCount: rows.length,
    avgComposite: Math.round(rows.reduce((s, r) => s + r.composite, 0) / n),
    notReady: rows.filter((r) => r.band === 'Not Ready').length,
    foundational: rows.filter((r) => r.band === 'Foundational Work Required').length,
    conditional: rows.filter((r) => r.band === 'Conditionally Ready').length,
    ready: rows.filter((r) => r.band === 'Ready').length,
    totalFindings,
    critical: sev.Critical,
    high: sev.High,
    avgFindings: Math.round(totalFindings / n),
    totalComponents,
    totalBacklog: rows.reduce((s, r) => s + r.backlog, 0),
    totalEffort: rows.reduce((s, r) => s + r.effort, 0),
    gated: scans.filter((s) => s.scan.gateApplied).length,
  }
}

// ---- grounding economics (PRD §5.3) ------------------------------------
//
// FRAMING, and it is not decoration: Agentforce grounds through RETRIEVAL, not
// through full-schema injection. So on this surface the cost of a bloated
// metadata corpus is ACCURACY first — a retriever that cannot tell two fields
// apart hands the planner the wrong one — and payload size only second. Nothing
// here is an LLM bill.
//
// Every number below is a deterministic ESTIMATE over normalised words and
// characters (scanner/density.py): stable across re-scans and comparable org to
// org, but never a model tokenizer's count and never a billed cost. Callers must
// say so wherever they render one.

const finite = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

// Per-play split of the removable payload — scan_result's `est_removable_tokens`,
// whose three buckets are density.REMOVABLE_KEYS and sum exactly to
// (current - remediated). The scanner owns it and no Salesforce field maps to it
// yet, so today's portfolio export does NOT carry it; a scan without it returns
// null here and the card shows totals only. There is no way to recover the split
// from the totals, and a guessed one would be indistinguishable on screen from a
// measured one.
//
// The buckets are play names, not rule ids, so the rule each one maps to is
// spelled out here — that mapping is what makes a bar drillable into the
// findings behind it. It mirrors the three plays grounding_payload models; a
// fourth bucket added there shows up as an unlabelled, non-drillable row (its
// tokens still counted) rather than silently vanishing from the total.
const REMOVABLE_LEVERS = {
  unreferenced_fields: 'D1.UNREFERENCED_FIELD',
  restating_descriptions: 'D1.LOW_INFO_DESCRIPTION',
  duplicate_clusters: 'D1.SEMANTIC_DUPLICATE',
}

function removableLevers(scan) {
  const raw = scan.estRemovableTokens ?? scan.est_removable_tokens ?? null
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const kept = Object.entries(raw)
    .map(([key, v]) => [key, finite(v)])
    .filter(([, v]) => v != null && v > 0)
  return kept.length ? kept : null
}

export function groundingEconomics(scans) {
  let current = 0, remediated = 0
  let densityNum = 0, densityDen = 0
  const orgs = []
  const levers = new Map()

  for (const s of scans) {
    const sc = s.scan
    const cur = finite(sc.estGroundingTokens)
    const rem = finite(sc.estRemediatedTokens)
    // A scan that predates these fields is skipped outright rather than folded
    // in as a zero, which would read as "measured, and clean".
    if (cur == null || rem == null || cur <= 0) continue

    current += cur
    remediated += rem
    const removable = Math.max(0, cur - rem)

    // semanticDensity is a 0-1 SHARE, not a percent — the org detail view
    // already trips over this. Weight the portfolio average by the org's own
    // payload, or a tiny clean org counts for as much as a huge messy one.
    const d = finite(sc.semanticDensity)
    if (d != null) { densityNum += d * cur; densityDen += cur }

    orgs.push({
      externalId: sc.externalId,
      name: sc.targetOrg,
      band: sc.readinessBand,
      current: cur,
      remediated: rem,
      removable,
      removablePct: (removable / cur) * 100,
      density: d,
    })

    const split = removableLevers(sc)
    if (split) for (const [key, tokens] of split) levers.set(key, (levers.get(key) || 0) + tokens)
  }

  const removable = Math.max(0, current - remediated)
  const leverTotal = [...levers.values()].reduce((a, b) => a + b, 0)
  const leverRows = levers.size
    ? [...levers.entries()]
      .map(([key, tokens]) => {
        // hasOwn, not a bare lookup: a bucket named "constructor" would
        // otherwise resolve to Object.prototype's and be labelled with it.
        const ruleId = Object.hasOwn(REMOVABLE_LEVERS, key) ? REMOVABLE_LEVERS[key] : null
        return {
          key,
          ruleId,                                    // null => shown, but not drillable
          label: ruleId ? ruleLabel(ruleId) : key.replace(/_/g, ' '),
          tokens,
          // Share of the ATTRIBUTED payload, so the bars read as 100% of what the
          // scanner could account for rather than of a total they may not cover
          // (they do cover it today — the buckets sum to current - remediated —
          // but a portfolio mixing new and old exports would not).
          pct: leverTotal ? (tokens / leverTotal) * 100 : 0,
        }
      })
      .sort((a, b) => b.tokens - a.tokens)
    : null

  return {
    orgCount: orgs.length,
    missingCount: scans.length - orgs.length,
    current,
    remediated,
    removable,
    removablePct: current ? (removable / current) * 100 : 0,
    density: densityDen ? densityNum / densityDen : null,   // 0-1 share
    levers: leverRows,
    leverTotal,
    orgs: orgs.sort((a, b) => b.removable - a.removable || b.current - a.current),
  }
}

// Every finding in the portfolio, tagged with the org it came from — the basis
// for cross-filtering (click a rule/dimension/severity anywhere, see the matches).
export function flattenFindings(scans) {
  const out = []
  for (const s of scans) {
    for (const f of s.findings) {
      out.push({ ...f, org: s.scan.targetOrg, orgId: s.scan.externalId })
    }
  }
  return out
}

export function applyFindingFilter(findings, filter) {
  return findings
    .filter((f) => !filter.dimension || f.dimension === filter.dimension)
    .filter((f) => !filter.rule || f.ruleId === filter.rule)
    .filter((f) => !filter.severity || f.severity === filter.severity)
}

export const EMPTY_FILTER = { band: null, dimension: null, rule: null, severity: null }
export function filterIsActive(f) {
  return !!(f.band || f.dimension || f.rule || f.severity)
}
export function findingFilterActive(f) {
  return !!(f.dimension || f.rule || f.severity)
}

// One row per org with its five dimension scores — feeds the heatmap.
export function heatmapRows(scans) {
  return scans
    .map((s) => {
      const dims = {}
      for (const d of s.dimensions) dims[d.code] = d.score
      return {
        externalId: s.scan.externalId,
        name: s.scan.targetOrg,
        composite: s.scan.compositeScore,
        band: s.scan.readinessBand,
        findings: s.findings.length,
        dims,
      }
    })
    .sort((a, b) => a.composite - b.composite)
}

// Average score per dimension across the orgs that assessed it.
export function dimensionAverages(scans) {
  const acc = {}
  for (const s of scans) {
    for (const d of s.dimensions) {
      if (d.score == null) continue
      const a = (acc[d.code] ||= { code: d.code, name: d.name, sum: 0, n: 0 })
      a.sum += d.score
      a.n += 1
    }
  }
  return Object.values(acc)
    .sort((a, b) => a.code.localeCompare(b.code))
    .map((a) => ({ code: a.code, name: a.name, avg: Math.round(a.sum / a.n), orgs: a.n }))
}

// Count per band, plus what each band actually costs — the counts alone left the
// card mostly empty, and "9 orgs" means little without the work behind it.
export function bandBreakdown(scans) {
  const acc = Object.fromEntries(BAND_ORDER.map((b) => [b, { n: 0, score: 0, findings: 0, effort: 0 }]))
  for (const s of scans) {
    const a = acc[s.scan.readinessBand]
    if (!a) continue
    a.n += 1
    a.score += s.scan.compositeScore
    a.findings += s.findings.length
    a.effort += orgEffort(s.findings)
  }
  return BAND_ORDER.map((band) => {
    const a = acc[band]
    return {
      band,
      count: a.n,
      avgScore: a.n ? Math.round(a.score / a.n) : null,
      findings: a.findings,
      effort: a.effort,
    }
  })
}

// Finding counts across the whole portfolio, by rule and by severity.
export function portfolioFindingBreakdown(scans) {
  const byRule = {}, bySev = Object.fromEntries(SEVERITY_ORDER.map((s) => [s, 0]))
  let total = 0
  for (const s of scans) {
    for (const f of s.findings) {
      byRule[f.ruleId] = (byRule[f.ruleId] || 0) + 1
      bySev[f.severity] = (bySev[f.severity] || 0) + 1
      total += 1
    }
  }
  const rules = Object.entries(byRule)
    .map(([ruleId, count]) => ({ ruleId, label: ruleLabel(ruleId), count }))
    .sort((a, b) => b.count - a.count)
  const severities = SEVERITY_ORDER.filter((s) => bySev[s] > 0).map((s) => ({ severity: s, count: bySev[s] }))
  return { rules, severities, total }
}

// ---- org-detail derivations --------------------------------------------
// Who does the work. The output of this tool is a backlog, and a backlog
// nobody owns is a list — so this is the split that decides whether it can be
// handed over: four teams, or one person who now has a thousand tickets.
export function ownerBreakdown(findings) {
  const by = new Map()
  for (const f of findings) {
    if (!f.emitsToBacklog) continue          // observations are not anyone's work yet
    const role = f.ownerRole || 'Unassigned'
    const row = by.get(role) || { role, tickets: 0, points: 0, critical: 0 }
    row.tickets += 1
    row.points += f.effortPoints || 0
    if (f.severity === 'Critical') row.critical += 1
    by.set(role, row)
  }
  return [...by.values()].sort((a, b) => b.points - a.points)
}

export function severityCounts(findings) {
  const c = Object.fromEntries(SEVERITY_ORDER.map((s) => [s, 0]))
  for (const f of findings) c[f.severity] = (c[f.severity] || 0) + 1
  return c
}

export function backlogSummary(findings) {
  const gated = findings.filter((f) => f.emitsToBacklog)
  const byEpic = {}
  for (const f of gated) {
    // The finding's own epic when the export carries one, so the summary and
    // the downloaded CSV never disagree about which epic a ticket belongs to.
    const epic = f.epic || RULE_META[f.ruleId]?.epic || f.ruleId
    if (!byEpic[epic]) byEpic[epic] = { epic, count: 0, effort: 0 }
    byEpic[epic].count += 1
    byEpic[epic].effort += f.effortPoints || 0
  }
  return {
    ticketCount: gated.length,
    observationCount: findings.length - gated.length,
    totalEffort: gated.reduce((s, f) => s + (f.effortPoints || 0), 0),
    epics: Object.values(byEpic).sort((a, b) => b.effort - a.effort),
  }
}

// Roll findings up to the object they sit on (component is "Obj.Field" or "Obj [N fields]").
export function objectOf(component) {
  return component.split('.')[0].split(' [')[0]
}
export function componentRollup(findings, limit = 8) {
  const by = {}
  for (const f of findings) {
    const o = objectOf(f.component)
    if (!by[o]) by[o] = { object: o, count: 0, effort: 0 }
    by[o].count += 1
    by[o].effort += f.emitsToBacklog ? (f.effortPoints || 0) : 0
  }
  return Object.values(by).sort((a, b) => b.count - a.count).slice(0, limit)
}

// ---- time-series families ----------------------------------------------
// "Helios Airlines · 2025-Q1" -> base "Helios Airlines", label "2025-Q1".
export function splitName(name) {
  const i = name.indexOf(' · ')
  return i === -1 ? { base: name, label: '' } : { base: name.slice(0, i), label: name.slice(i + 3) }
}
// The tenant boundary.
//
// This used to recover the enterprise by splitting the org's free-text name on a
// separator, and said so: "nothing here, and nothing in Salesforce, has a
// concept of enterprise". That was a naming convention wearing the shape of a
// boundary — two estates sat in one org distinguished by a prefix, and no query
// could stop one seeing the other. `OrgIQ_Enterprise__c` is now a record, an org
// is a master-detail child of it, and every scan carries its id.
//
// The split is kept for one job only: turning "Meridian Insurance · prod" into
// the short label "prod" for display. It decides nothing.
export function enterprisesOf(scans) {
  const byId = new Map()
  for (const s of scans) {
    const id = s.scan.enterpriseId
    if (id && !byId.has(id)) byId.set(id, splitName(s.scan.targetOrg).base)
  }
  // An export predating the tenant field would otherwise silently show nothing.
  return byId.size ? [...byId.values()] : []
}

export function enterpriseIdOf(scans, name) {
  for (const s of scans) {
    if (splitName(s.scan.targetOrg).base === name) return s.scan.enterpriseId
  }
  return null
}

// Filtered on the id, not the label. A label collision between two tenants would
// merge their estates; an id collision cannot happen, because it is unique on
// the record.
export function scansForEnterprise(scans, name) {
  if (!name) return scans
  const id = enterpriseIdOf(scans, name)
  return id ? scans.filter((s) => s.scan.enterpriseId === id) : scans
}

// An org now holds more than one scan — the estate dates its scan ids, so today's
// scan sits next to last quarter's. Everything that answers "what is the estate
// like" must read the LATEST scan per org, or one remediated org appears four
// times and drags its own average down.
// Cross-org drift, grouped by the org that carries it. Kept separate from the
// dimension rollups on purpose: drift describes a PAIR of orgs, so folding it
// into this org's D1-D5 scores would grade one org for another's state.
export function driftByOrg(scans) {
  const rows = []
  for (const s of scans) {
    const d = s.findings.filter((f) => f.dimension === 'Drift')
    if (d.length) {
      rows.push({
        externalId: s.scan.externalId,
        org: s.scan.targetOrg,
        findings: d,
        worst: ['Critical', 'High', 'Medium', 'Low'].find((sev) => d.some((f) => f.severity === sev)) || 'Low',
      })
    }
  }
  const rank = { Critical: 0, High: 1, Medium: 2, Low: 3 }
  return rows.sort((a, b) => rank[a.worst] - rank[b.worst] || b.findings.length - a.findings.length)
}

// ---- persona surfaces --------------------------------------------------
//
// An agent runs as a persona, so what an agent can reach IS what its persona can
// reach. Findings answer only half of that question — they say which personas
// are wrong. The surface answers the other half, which is the one a reviewer
// signing off an agent actually asks: what can this identity do, and is that the
// job it has?

// Estate-wide, from the newest scan of each org. A persona is per-org: the same
// role can be bounded in production and wide open in a sandbox, and merging them
// would report a reach no org has.
export function personaRows(scans) {
  const rows = []
  for (const s of latestScans(scans)) {
    for (const p of s.personas || []) {
      rows.push({ ...p, org: s.scan.targetOrg, scanId: s.scan.externalId })
    }
  }
  return rows.sort((a, b) => (b.unbounded ? 1 : 0) - (a.unbounded ? 1 : 0)
    || (b.reach ?? 0) - (a.reach ?? 0))
}

// The share of what a persona may read that is actually put in front of it.
// null — not 0 — where the question does not apply: a permission set assigns no
// layouts, so it has no visible-field count, and rendering that as 0% would read
// as a finding about the persona rather than a fact about where layouts live.
export function shownShare(p) {
  if (p.fieldsVisible == null || !p.fieldsAvailable) return null
  return p.fieldsVisible / p.fieldsAvailable
}

export function personaStats(rows) {
  const unbounded = rows.filter((p) => p.unbounded)
  const shares = rows.map(shownShare).filter((v) => v != null)
  return {
    total: rows.length,
    unbounded: unbounded.length,
    canDelete: rows.filter((p) => p.objectsDeletable > 0).length,
    // Median, not mean: one blanket persona that can see everything would drag
    // an average until the typical persona became unreadable.
    medianShown: shares.length
      ? shares.sort((a, b) => a - b)[Math.floor(shares.length / 2)]
      : null,
    withProcess: rows.filter((p) => p.approvals > 0 || p.flows > 0).length,
  }
}

// ---- survival ----------------------------------------------------------
//
// How many consecutive scans a finding has been reported by. It is not effort
// and is never presented as it: what it says is which findings the backlog has
// stopped moving on, which is observable from scans already held and needs
// nobody to record anything.
export const STUCK_SCANS = 3

export function survivalStats(scans) {
  const ticketed = []
  for (const s of latestScans(scans)) {
    for (const f of s.findings) {
      if (f.emitsToBacklog && f.survivedScans) ticketed.push(f)
    }
  }
  const stuck = ticketed.filter((f) => f.survivedScans >= STUCK_SCANS)
  return {
    measured: ticketed.length,
    stuck: stuck.length,
    longest: ticketed.reduce((m, f) => Math.max(m, f.survivedScans), 0),
    stuckEffort: stuck.reduce((n, f) => n + (f.effortPoints || 0), 0),
  }
}

export function latestScans(scans) {
  const best = new Map()
  for (const s of scans) {
    const key = s.scan.targetOrg
    const prev = best.get(key)
    if (!prev || String(s.scan.timestamp) > String(prev.scan.timestamp)) best.set(key, s)
  }
  return [...best.values()]
}

// The same org over time, oldest first — the burn-down.
export function historyOf(scans, targetOrg) {
  return scans
    .filter((s) => s.scan.targetOrg === targetOrg)
    .sort((a, b) => String(a.scan.timestamp).localeCompare(String(b.scan.timestamp)))
}

export function familyOf(scans, scan) {
  const series = historyOf(scans, scan.targetOrg)
  if (series.length > 1) {
    return { base: scan.targetOrg, members: series }
  }
  const base = splitName(scan.targetOrg).base
  const members = scans
    .filter((s) => splitName(s.scan.targetOrg).base === base)
    .sort((a, b) => splitName(a.scan.targetOrg).label.localeCompare(splitName(b.scan.targetOrg).label))
  return members.length > 1 ? { base, members } : null
}

// ---- backlog CSV -------------------------------------------------------
//
// This is the Jira import file a stakeholder downloads from the dashboard, so
// it has to BE the scanner's file, not a lookalike: the same 17 columns in the
// same order, the same header strings, the same row shaping AND the same
// epic-then-children structure as scanner/backlog.py. These two implementations
// drifted once already — the dashboard emitted 9 columns against the scanner's
// 15 and the demo handed out a spreadsheet Jira could not import as tickets.
// backlog.py is the source of truth; keep this block in lockstep with it, down
// to the wording of the epic summary and description.

// Verbatim from backlog.BACKLOG_COLUMNS. "Epic Link" sits immediately after
// "Epic Name" because Jira's importer reads Epic Name off the epic row only and
// links children through Epic Link — a child carrying an Epic Name imports as a
// second epic instead of as that epic's child.
const BACKLOG_COLUMNS = [
  'External ID',
  'Issue Type',
  'Epic Name',
  'Epic Link',
  'Summary',
  'Priority',
  'Story Points (provisional)',
  'Labels',
  'Salesforce Component',
  'Component Type',
  'Rule ID',
  'Dimension',
  'Severity',
  'Confidence',
  'Rule Maturity',
  'Source',
  'Owner Role',
  'Description',
]

// backlog._PRIORITY / _SEV_RANK / _CONF_RANK / FINDING_SOURCE.
const JIRA_PRIORITY = { Critical: 'Highest', High: 'High', Medium: 'Medium', Low: 'Low' }
const SEV_RANK = { Critical: 4, High: 3, Medium: 2, Low: 1 }
const CONF_RANK = { High: 3, Medium: 2, Low: 1 }
const DEFAULT_FINDING_SOURCE = 'OrgIQ'
// backlog._SCOPE_CAP — objects named in an epic summary before "+N more".
const SCOPE_CAP = 4

// Python compares strings by code point; localeCompare does not, and the row
// order is part of matching the scanner's output.
function cmp(a, b) { return a < b ? -1 : a > b ? 1 : 0 }

// backlog._distinct — first occurrence wins, order preserved.
function distinct(values) {
  const out = []
  for (const v of values) if (v && !out.includes(v)) out.push(v)
  return out
}

// The exported finding carries the org's own epic / acceptance / source once the
// scan has been loaded into Salesforce; RULE_META (a cache of backlog._PLAYBOOK)
// covers findings exported before those fields existed.
function epicOf(f) { return f.epic || (RULE_META[f.ruleId] ?? UNKNOWN_RULE).epic }
function acceptanceOf(f) {
  return f.acceptanceCriteria || (RULE_META[f.ruleId] ?? UNKNOWN_RULE).acceptance
}
function findingSourceOf(f) { return f.source || DEFAULT_FINDING_SOURCE }

// Epic external ids are SHA-1, and they must come out byte-identical to the
// scanner's or re-importing a dashboard export next to a CLI export creates a
// second epic for the same work instead of upserting the one everybody is
// tracking. Web Crypto's digest is async while this runs inside a click handler
// that returns a string, so SHA-1 is inlined here rather than awaited.
function sha1Hex(text) {
  const bytes = new TextEncoder().encode(text)      // hash UTF-8 bytes, as Python does
  const padded = bytes.length + 1 + 8
  const total = padded + ((64 - (padded % 64)) % 64)
  const msg = new Uint8Array(total)
  msg.set(bytes)
  msg[bytes.length] = 0x80
  const view = new DataView(msg.buffer)
  const bits = bytes.length * 8
  view.setUint32(total - 8, Math.floor(bits / 4294967296))
  view.setUint32(total - 4, bits >>> 0)

  let h0 = 0x67452301, h1 = 0xEFCDAB89, h2 = 0x98BADCFE, h3 = 0x10325476, h4 = 0xC3D2E1F0
  const w = new Uint32Array(80)
  for (let i = 0; i < total; i += 64) {
    for (let j = 0; j < 16; j += 1) w[j] = view.getUint32(i + j * 4)
    for (let j = 16; j < 80; j += 1) {
      const n = w[j - 3] ^ w[j - 8] ^ w[j - 14] ^ w[j - 16]
      w[j] = ((n << 1) | (n >>> 31)) >>> 0
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4
    for (let j = 0; j < 80; j += 1) {
      let f, k
      if (j < 20) { f = (b & c) | (~b & d); k = 0x5A827999 }
      else if (j < 40) { f = b ^ c ^ d; k = 0x6ED9EBA1 }
      else if (j < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8F1BBCDC }
      else { f = b ^ c ^ d; k = 0xCA62C1D6 }
      const t = (((a << 5) | (a >>> 27)) + f + e + k + w[j]) >>> 0
      e = d; d = c; c = ((b << 30) | (b >>> 2)) >>> 0; b = a; a = t
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0
    h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0
  }
  return [h0, h1, h2, h3, h4].map((x) => x.toString(16).padStart(8, '0')).join('')
}

// backlog._epic_external_id — hashes (epic, source) only, so the epic survives
// its children changing between re-scans.
function epicExternalId(epic, source) {
  return `OIQ-EPIC-${sha1Hex(`${epic}|${source}`).slice(0, 12)}`
}
// backlog._epic_name — org-qualified, because the portfolio download merges
// every org into one file and Jira keys epics by name.
function epicNameOf(epic, source) { return `${epic} — ${source}` }

function componentTypeOf(f) {
  // Prefer the stored value; fall back to backlog._component_type's rule
  // (aggregate findings render as "Object [N fields]").
  return f.componentType || (f.component.includes('[') ? 'CustomField group' : 'CustomField')
}

// backlog._scope_of — reduce a component of any shape to the object (or
// artefact) a reader recognises: Account.Region__c and Account [12 fields] both
// give Account, Agent_PS:Case gives Case, BillingService.cls gives
// BillingService. Not objectOf() above: that one predates the perm-set and Apex
// component shapes the D3–D5 packs emit.
function scopeOf(f) {
  let head = (f.component || '').split(' [')[0].trim()
  const colon = head.indexOf(':')
  if (colon !== -1) head = head.slice(colon + 1).trim()   // perm set : object
  if (head.endsWith('.cls')) return head.slice(0, -'.cls'.length)
  return head.includes('.') ? head.slice(0, head.indexOf('.')) : head
}

// backlog._scope_phrase — "Account, Contact, Case, Opportunity +3 more", in the
// children's own order so the most severe object is named first.
function scopePhrase(children) {
  const seen = distinct(children.map(scopeOf))
  if (!seen.length) return 'components with no object recorded'
  const shown = seen.slice(0, SCOPE_CAP).join(', ')
  const extra = seen.length - SCOPE_CAP
  return extra > 0 ? `${shown} +${extra} more` : shown
}

const epicPoints = (children) => children.reduce((s, f) => s + (f.effortPoints || 0), 0)
// An epic is as urgent as its worst child...
function epicSeverity(children) {
  return children.reduce((a, f) => ((SEV_RANK[f.severity] ?? 0) > (SEV_RANK[a.severity] ?? 0) ? f : a)).severity
}
// ...and only as trustworthy as its shakiest one. Computed, not read off the
// last child: children sort by severity first, so the tail is the least severe
// finding, which is not necessarily the least confident.
function epicConfidence(children) {
  return children.reduce((a, f) => ((CONF_RANK[f.confidence] ?? 0) < (CONF_RANK[a.confidence] ?? 0) ? f : a)).confidence
}

// backlog._epic_description — the rollup a reviewer reads before deciding to
// schedule the whole epic: what it is, how big, how much provisional effort,
// and what "done" means for its children.
function epicDescription(scan, epic, children) {
  const n = children.length
  const rules = distinct(children.map((f) => f.ruleId))
  const acceptanceByRule = new Map()
  for (const f of children) if (!acceptanceByRule.has(f.ruleId)) acceptanceByRule.set(f.ruleId, acceptanceOf(f))
  return [
    `Epic: ${epic} (${children[0].dimension})`,
    `Severity: ${epicSeverity(children)}   Confidence: ${epicConfidence(children)}`,
    '',
    `Items: ${n}`,
    `Objects: ${scopePhrase(children)}`,
    `Rules: ${rules.join(', ')}`,
    `Provisional effort: ${epicPoints(children)} point(s) across ${n} child item(s)`,
    '',
    'These findings share one fix, so they are imported as one epic rather '
      + 'than as loose tickets (PRD §4.6). Each child below carries its own '
      + 'component, evidence and remediation steps; the epic closes when every '
      + 'child clears a re-scan.',
    '',
    'Acceptance criteria (shared by the children):',
    ...rules.map((ruleId) => `- ${ruleId}: ${acceptanceByRule.get(ruleId)}`),
    '',
    `Scan source: ${scan.targetOrg}`,
    `Finding source: ${distinct(children.map(findingSourceOf)).join(', ')}`,
    'Effort points are PROVISIONAL (uncalibrated, PRD §8/§11).',
  ].join('\n')
}

function backlogDescription(scan, f) {
  const acceptance = acceptanceOf(f)
  return [
    `Rule: ${f.ruleId} (${f.dimension} — Grounding Quality)`,
    `Severity: ${f.severity}   Confidence: ${f.confidence}`,
    `Component: ${f.component}  [${componentTypeOf(f)}]`,
    '',
    // backlog.py emits a separate "Detail:" line; by the time a finding reaches
    // the dashboard its detail is already folded into evidence ("ev — detail"),
    // so there is nothing left to break out.
    `Evidence: ${f.evidence}`,
    '',
    'Remediation:',
    f.remediation || '',
    '',
    `Acceptance criteria: ${acceptance}`,
    '',
    'Blast radius: n/a (source mode — no dependency graph)',
    `Scan source: ${scan.targetOrg}`,
    `Finding source: ${findingSourceOf(f)}`,
    'Effort points are PROVISIONAL (uncalibrated, PRD §8/§11).',
  ].join('\n')
}

// Keyed by column name, then emitted in BACKLOG_COLUMNS order — the same
// DictWriter shape backlog.to_rows uses, so a column can never silently drift
// out of position the way a positional array lets it.
//
// backlog._task_row. Epic Name is blank on a child and its parent's name goes in
// Epic Link; only the flat (no-epic) export puts the epic back on the row.
function taskRow(scan, f, epicName, epicLink) {
  return {
    'External ID': f.externalId,
    'Issue Type': 'Task',
    'Epic Name': epicName,
    'Epic Link': epicLink,
    Summary: `[${f.ruleId}] ${f.component}: ${f.evidence}`.slice(0, 200),
    Priority: JIRA_PRIORITY[f.severity] ?? 'Medium',
    'Story Points (provisional)': f.effortPoints,
    Labels: `OrgIQ ${f.dimension} ${f.ruleId.replace(/\./g, '_')}`,
    'Salesforce Component': f.component,
    'Component Type': componentTypeOf(f),
    'Rule ID': f.ruleId,
    Dimension: f.dimension,
    Severity: f.severity,
    Confidence: f.confidence,
    'Rule Maturity': f.ruleMaturity || 'experimental',
    Source: findingSourceOf(f),
    // Comes off the record. The dashboard does not re-derive it: the mapping is
    // rubric, it lives in scanner/rubric.json, and a second copy here would be a
    // second thing to keep in step.
    'Owner Role': f.ownerRole || '',
    Description: backlogDescription(scan, f),
  }
}

// backlog._epic_row. `children` arrives in the order it will be written in, most
// severe first, so the scope list and the rule list read top-down the way the
// file does.
function epicRow(scan, epic, children) {
  const rules = distinct(children.map((f) => f.ruleId))
  const dimension = children[0].dimension   // epics never span dimensions by construction
  const severity = epicSeverity(children)
  const n = children.length
  return {
    'External ID': epicExternalId(epic, scan.targetOrg),
    'Issue Type': 'Epic',
    'Epic Name': epicNameOf(epic, scan.targetOrg),
    'Epic Link': '',                        // an epic has no parent
    Summary: `${epic} — ${n} ${n === 1 ? 'item' : 'items'} across ${scopePhrase(children)}`.slice(0, 200),
    Priority: JIRA_PRIORITY[severity] ?? 'Medium',
    'Story Points (provisional)': epicPoints(children),
    Labels: ['OrgIQ', dimension, 'epic', ...rules.map((r) => r.replace(/\./g, '_'))].join(' '),
    'Salesforce Component': scopePhrase(children),
    'Component Type': 'Epic',
    'Rule ID': rules.join(', '),
    Dimension: dimension,
    Severity: severity,
    Confidence: epicConfidence(children),
    'Rule Maturity': 'experimental',
    Source: distinct(children.map(findingSourceOf)).join(', '),
    'Owner Role': (() => {
      const roles = distinct(children.map((c) => c.ownerRole).filter(Boolean))
      return roles.length === 1 ? roles[0] : roles.length ? 'Mixed' : ''
    })(),
    Description: epicDescription(scan, epic, children),
  }
}

// QUOTE_MINIMAL, matching Python's csv writer.
function csvCell(v) {
  const s = String(v ?? '')
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

// backlog.to_rows. With epics the file is a structure, not a list: each epic
// that has at least one gated finding emits an Epic row followed immediately by
// its own children, epics ordered by their most severe child and children
// most-severe-first inside the epic. `includeEpics: false` gives the flat
// one-row-per-finding export back.
function backlogRows(scan, findings, includeEpics) {
  const ordered = findings
    // The §4.6 gate again, in case a caller hands us everything: an observation
    // that failed the gate must never arrive as a ticket.
    .filter((f) => f.emitsToBacklog)
    .sort((a, b) => (SEV_RANK[b.severity] ?? 0) - (SEV_RANK[a.severity] ?? 0)
      || (CONF_RANK[b.confidence] ?? 0) - (CONF_RANK[a.confidence] ?? 0)
      || cmp(a.ruleId, b.ruleId)
      || cmp(a.component, b.component))

  if (!includeEpics) return ordered.map((f) => taskRow(scan, f, epicOf(f), ''))

  // A Map preserves insertion order, so epics come out ordered by their most
  // severe finding and each epic's children keep the severity order they were
  // sorted into — no second sort, and nothing to drift out of step with it.
  const clusters = new Map()
  for (const f of ordered) {
    const epic = epicOf(f)
    if (!clusters.has(epic)) clusters.set(epic, [])
    clusters.get(epic).push(f)
  }

  const rows = []
  for (const [epic, children] of clusters) {
    rows.push(epicRow(scan, epic, children))
    const epicLink = epicNameOf(epic, scan.targetOrg)
    // Epic Name stays empty on children: Jira's importer treats a row carrying
    // one as an epic in its own right, and the parent's name in Epic Link is
    // what actually creates the link.
    for (const f of children) rows.push(taskRow(scan, f, '', epicLink))
  }
  return rows
}

// Note for callers counting tickets off this file: epic rows are scaffolding,
// so the row count is no longer the ticket count (backlog.count_tickets makes
// the same distinction). The gated-finding count is still the number of tickets.
export function backlogCsv(scan, findings, { includeEpics = true } = {}) {
  const rows = backlogRows(scan, findings, includeEpics)
    .map((row) => BACKLOG_COLUMNS.map((c) => csvCell(row[c])).join(','))
  // CRLF-terminated rows, trailing terminator included (the Description cell
  // keeps its own bare newlines inside the quotes) — RFC 4180, and byte-for-byte
  // what Python's csv writer produces.
  return [BACKLOG_COLUMNS.join(','), ...rows].map((r) => `${r}\r\n`).join('')
}
export function downloadCsv(filename, text) {
  const blob = new Blob([text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
