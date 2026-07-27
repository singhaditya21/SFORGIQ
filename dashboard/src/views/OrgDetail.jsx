import { familyOf, componentRollup, backlogCsv, downloadCsv } from '../lib/data.js'
import PersonaPanel from '../components/PersonaPanel.jsx'
import ReadinessHero from '../components/ReadinessHero.jsx'
import DimensionGrid from '../components/DimensionGrid.jsx'
import BacklogSummary from '../components/BacklogSummary.jsx'
import FindingsTable from '../components/FindingsTable.jsx'
import TrendChart from '../components/TrendChart.jsx'
import ComponentRollup from '../components/ComponentRollup.jsx'

export default function OrgDetail({ data, scan }) {
  const s = scan.scan
  const findings = scan.findings
  const family = familyOf(data.scans, s)
  const rollup = componentRollup(findings)

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

      <main className="grid">
        <ReadinessHero scan={{
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
              <TrendChart family={family} currentId={s.externalId} />
            </section>
          )
          : (
            <section className="card">
              <div className="card__head">
                <h2 className="card__title">Debt by object</h2>
                <span className="card__hint">findings per object</span>
              </div>
              <ComponentRollup rollup={rollup} />
            </section>
          )}

        <DimensionGrid dimensions={scan.dimensions} />
        <BacklogSummary findings={findings} />
        {family && (
          <section className="card">
            <div className="card__head">
              <h2 className="card__title">Debt by object</h2>
              <span className="card__hint">findings per object</span>
            </div>
            <ComponentRollup rollup={rollup} />
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

        <FindingsTable findings={findings} />
      </main>
    </>
  )
}
