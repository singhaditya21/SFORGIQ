import { familyOf, componentRollup, backlogCsv, downloadCsv } from '../lib/data.js'
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
        <FindingsTable findings={findings} />
      </main>
    </>
  )
}
