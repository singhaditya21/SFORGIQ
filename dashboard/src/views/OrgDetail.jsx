import { useMemo, useState } from 'react'
import {
  familyOf, componentRollup, backlogCsv, downloadCsv, ownerBreakdown,
  EMPTY_ORG_FILTER, orgFilterActive, applyOrgFilter,
} from '../lib/data.js'
import PersonaPanel from '../components/PersonaPanel.jsx'
import OwnerSplit from '../components/OwnerSplit.jsx'
import ReadinessHero from '../components/ReadinessHero.jsx'
import DimensionGrid from '../components/DimensionGrid.jsx'
import BacklogSummary from '../components/BacklogSummary.jsx'
import FindingsTable from '../components/FindingsTable.jsx'
import TrendChart from '../components/TrendChart.jsx'
import ComponentRollup from '../components/ComponentRollup.jsx'

export default function OrgDetail({ data, scan }) {
  const s = scan.scan
  const all = scan.findings
  const family = familyOf(data.scans, s)

  // This page used to be a set of static pictures: seven of its eight cards had
  // nothing to click, and `.sevrow` carried a pointer cursor with no handler
  // behind it. Every widget now writes to one filter and the findings table
  // reads it — the same arrangement the portfolio page has had all along.
  const [filter, setFilter] = useState(EMPTY_ORG_FILTER)
  const toggle = (key, value) =>
    setFilter((f) => ({ ...f, [key]: f[key] === value ? null : value }))
  const clear = () => setFilter(EMPTY_ORG_FILTER)

  const findings = useMemo(() => applyOrgFilter(all, filter), [all, filter])
  // The summaries stay whole. A backlog card that recomputed itself from its own
  // filtered output would show one epic at 100% and hide the rest, so clicking
  // an epic would destroy the comparison that made it worth clicking.
  const rollup = useMemo(() => componentRollup(all), [all])
  const owners = useMemo(() => ownerBreakdown(all), [all])
  const active = orgFilterActive(filter)
  const go = (id) => { window.location.hash = `#/org/${encodeURIComponent(id)}` }

  const scanDate = new Date(s.timestamp)
  const dateLabel = isNaN(scanDate) ? s.timestamp
    : scanDate.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

  // Grounding cost (PRD §5.3). Deterministic estimates from the scanner, so
  // every number here is labelled as one. A scan exported before these fields
  // existed shows nothing rather than a zero that would read as measured.
  const density = s.semanticDensity          // 0-1 share, not a percent
  const curTokens = s.estGroundingTokens
  const remTokens = s.estRemediatedTokens
  const hasTokens = curTokens != null && remTokens != null && curTokens > 0
  const savedTokens = hasTokens ? Math.max(0, curTokens - remTokens) : 0
  const savedPct = hasTokens ? Math.round((savedTokens / curTokens) * 100) : 0
  // Each play is a rule, so the number and the findings behind it are one click
  // apart. Zero-value plays are dropped rather than shown at 0 — a play that
  // saves nothing here is not a lever on this org.
  const rem = s.estRemovableTokens || {}
  const removable = [
    { key: 'restating_descriptions', rule: 'D1.LOW_INFO_DESCRIPTION', label: 'Restating descriptions' },
    { key: 'duplicate_clusters', rule: 'D1.SEMANTIC_DUPLICATE', label: 'Duplicate clusters' },
    { key: 'unreferenced_fields', rule: 'D1.UNREFERENCED_FIELD', label: 'Unreferenced fields' },
  ].map((p) => ({ ...p, tokens: rem[p.key] || 0 })).filter((p) => p.tokens > 0)

  // Exports what is on screen, like the portfolio page's button does — a filter
  // you can see but cannot act on is only half a drill.
  const onDownload = () => {
    const gated = findings.filter((f) => f.emitsToBacklog)
    const safe = s.externalId.replace(/[^A-Za-z0-9_-]+/g, '_')
    downloadCsv(`${safe}-backlog.csv`, backlogCsv(s, gated))
  }

  return (
    <>
      <div className="crumbs">
        <a href="#/">← All orgs</a>
        <span className="crumbs__sep">/</span>
        <span>{s.targetOrg}</span>
      </div>

      <div className="pagehead">
        <div>
          <h1 className="pagehead__title">{s.targetOrg}</h1>
          <p className="pagehead__sub">
            {s.name} · {s.scanMode} mode · {s.componentsScanned} components ·
            rubric {s.rubricVersion} · {dateLabel}
          </p>
        </div>
        <button className="btn" onClick={onDownload}>⬇ Download backlog CSV</button>
      </div>

      {active && (
        // Visible and reversible. A filter you cannot see is a page that has
        // silently stopped showing you everything.
        <div className="orgfilter">
          <span className="orgfilter__label">Showing</span>
          {Object.entries(filter).filter(([, v]) => v).map(([k, v]) => (
            <button key={k} className="chip chip--filter" onClick={() => toggle(k, v)}>
              {v}<span className="chip__x">✕</span>
            </button>
          ))}
          <span className="orgfilter__count">
            {findings.length.toLocaleString()} of {all.length.toLocaleString()} findings
          </span>
          <button className="orgfilter__clear" onClick={clear}>Clear</button>
        </div>
      )}

      <main className="grid">
        <ReadinessHero onGate={() => toggle('severity', 'Critical')} scan={{
          compositeScore: s.compositeScore,
          readinessBand: s.readinessBand,
          gateApplied: s.gateApplied,
          gateReason: s.gateReason,
        }} />

        {family
          ? (
            <section className="card">
              <div className="card__head">
                <h2 className="card__title">Remediation trend</h2>
                <span className="card__hint">{family.base} · composite over time</span>
              </div>
              <TrendChart family={family} currentId={s.externalId} onSelect={go} />
            </section>
          )
          : (
            <section className="card">
              <div className="card__head">
                <h2 className="card__title">Debt by object</h2>
                <span className="card__hint">findings per object</span>
              </div>
              <ComponentRollup rollup={rollup} active={filter.object}
                             onSelect={(o) => toggle('object', o)} />
            </section>
          )}

        <DimensionGrid dimensions={scan.dimensions} active={filter.dimension}
                       onSelect={(d) => toggle('dimension', d)} />
        <BacklogSummary findings={all} filter={filter} onSelect={toggle} />
        {family && (
          <section className="card">
            <div className="card__head">
              <h2 className="card__title">Debt by object</h2>
              <span className="card__hint">findings per object</span>
            </div>
            <ComponentRollup rollup={rollup} active={filter.object}
                             onSelect={(o) => toggle('object', o)} />
          </section>
        )}
        {(hasTokens || density != null) && (
          // Spans the hole the "Debt by object" card leaves when there is no
          // family trend, so the row still fills exactly (see .grid in index.css).
          <section className={family ? 'card' : 'card card--wide'}>
            <div className="card__head">
              <h2 className="card__title">Grounding cost</h2>
              <span className="card__hint">deterministic estimates · not a model tokenizer</span>
            </div>

            <div className="backlog__stats">
              {density != null && (
                <div className="stat"
                     title="Share of description text that adds information beyond the label and API name.">
                  <div className="stat__num">{(density * 100).toFixed(1)}%</div>
                  <div className="stat__label">
                    semantic density<span className="stat__prov"> · est.</span>
                  </div>
                </div>
              )}
              {hasTokens && (
                <>
                  <div className="stat"
                       title="Tokens an agent retrieves for these fields today (API name + label + description).">
                    <div className="stat__num">{curTokens.toLocaleString()}</div>
                    <div className="stat__label">
                      tokens retrieved today<span className="stat__prov"> · est.</span>
                    </div>
                  </div>
                  <div className="stat"
                       title="Same fields once low-information descriptions are dropped and duplicates collapse.">
                    <div className="stat__num">{remTokens.toLocaleString()}</div>
                    <div className="stat__label">
                      tokens after remediation<span className="stat__prov"> · est.</span>
                    </div>
                  </div>
                </>
              )}
            </div>

            {hasTokens && removable.length > 0 && (
              <div className="gplays">
                <div className="backlog__epicshead">Where the reduction comes from</div>
                {removable.map((r) => (
                  <button key={r.rule}
                          className={`gplay${filter.rule === r.rule ? ' is-active' : ''}`}
                          onClick={() => toggle('rule', r.rule)}
                          title={`Show the ${r.label.toLowerCase()} findings`}>
                    <span className="gplay__name">{r.label}</span>
                    <span className="gplay__num">
                      −{r.tokens.toLocaleString()}<span className="stat__prov"> est.</span>
                    </span>
                  </button>
                ))}
              </div>
            )}

            {hasTokens && (
              <div className="epic">
                <div className="epic__top">
                  <span className="epic__name">Estimated reduction</span>
                  <span className="epic__nums">
                    −{savedTokens.toLocaleString()} tokens · {savedPct}%
                  </span>
                </div>
                <div className="epic__bar">
                  <div className="epic__fill" style={{ width: `${Math.min(100, savedPct)}%` }} />
                </div>
              </div>
            )}
          </section>
        )}

        {(scan.personas || []).length > 0 && (
          <section className="card card--wide">
            <div className="card__head">
              <h2 className="card__title">What each identity can actually do</h2>
              <span className="card__hint">
                {scan.personas.length} personas in this org · click a row to expand
              </span>
            </div>
            {/* No org column: every row here is this org. */}
            <PersonaPanel rows={scan.personas.map((p) => ({ ...p, scanId: s.externalId }))}
                          showOrg={false} />
          </section>
        )}

        {owners.length > 0 && (
          <section className="card">
            <div className="card__head">
              <h2 className="card__title">Who does the work</h2>
              <span className="card__hint">by effort · click a team</span>
            </div>
            <OwnerSplit rows={owners} active={filter.role}
                        onSelect={(r) => toggle('role', r)} />
          </section>
        )}

        <FindingsTable findings={findings} />
      </main>
    </>
  )
}
