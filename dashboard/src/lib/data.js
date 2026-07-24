// Data loading + domain metadata for the OrgIQ dashboard.

// Demo mode reads the bundled JSON exported from the OrgIQ Salesforce org.
// (A future live mode would swap this for an OAuth'd Salesforce REST query,
// returning the same shape.)
export async function loadScan() {
  const res = await fetch(`${import.meta.env.BASE_URL}sample-scan.json`)
  if (!res.ok) throw new Error(`could not load scan data (${res.status})`)
  return res.json()
}

// Readiness bands (PRD §4.3) → colour + one-line meaning.
export const BAND_META = {
  'Not Ready': {
    key: 'not-ready',
    blurb: 'Agent deployment will fail. Foundational remediation required first.',
  },
  'Foundational Work Required': {
    key: 'foundational',
    blurb: 'Narrow, low-risk agents feasible. Broad deployment is not.',
  },
  'Conditionally Ready': {
    key: 'conditional',
    blurb: 'Deploy with named mitigations and a monitoring plan.',
  },
  Ready: {
    key: 'ready',
    blurb: 'No structural blockers identified.',
  },
}

export const SEVERITY_ORDER = ['Critical', 'High', 'Medium', 'Low']
export const CONFIDENCE_ORDER = ['High', 'Medium', 'Low']

// Rule catalogue — friendly label + backlog epic (mirrors scanner/backlog.py).
export const RULE_META = {
  'D1.MISSING_DESCRIPTION': { label: 'Missing description', epic: 'Add missing field descriptions' },
  'D1.LOW_INFO_DESCRIPTION': { label: 'Label-restating description', epic: 'Replace label-restating descriptions' },
  'D1.CRYPTIC_API_NAME': { label: 'Cryptic field name', epic: 'Clarify cryptic field names' },
  'D1.NUMBERED_FAMILY': { label: 'Numbered field family', epic: 'Resolve numbered field families' },
  'D1.SEMANTIC_DUPLICATE': { label: 'Duplicate field', epic: 'Consolidate duplicate fields' },
}

export function ruleLabel(ruleId) {
  return RULE_META[ruleId]?.label ?? ruleId
}

// Backlog rollup over the gate-passing findings only (PRD §4.6).
export function backlogSummary(findings) {
  const gated = findings.filter((f) => f.emitsToBacklog)
  const totalEffort = gated.reduce((s, f) => s + (f.effortPoints || 0), 0)
  const byEpic = {}
  for (const f of gated) {
    const epic = RULE_META[f.ruleId]?.epic ?? f.ruleId
    if (!byEpic[epic]) byEpic[epic] = { epic, count: 0, effort: 0 }
    byEpic[epic].count += 1
    byEpic[epic].effort += f.effortPoints || 0
  }
  const epics = Object.values(byEpic).sort((a, b) => b.effort - a.effort)
  return {
    ticketCount: gated.length,
    observationCount: findings.length - gated.length,
    totalEffort,
    epics,
  }
}

export function severityCounts(findings) {
  const c = Object.fromEntries(SEVERITY_ORDER.map((s) => [s, 0]))
  for (const f of findings) c[f.severity] = (c[f.severity] || 0) + 1
  return c
}
