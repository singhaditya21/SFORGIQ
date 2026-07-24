import {
  portfolioStats, bandBreakdown, portfolioFindingBreakdown, orgRows,
} from '../lib/data.js'
import KpiRow from '../components/KpiRow.jsx'
import BandBar from '../components/BandBar.jsx'
import Quadrant from '../components/Quadrant.jsx'
import FindingAnalytics from '../components/FindingAnalytics.jsx'
import OrgsTable from '../components/OrgsTable.jsx'

export default function PortfolioView({ data }) {
  const scans = data.scans
  const stats = portfolioStats(scans)
  const bands = bandBreakdown(scans)
  const findingMix = portfolioFindingBreakdown(scans)
  const rows = orgRows(scans)

  return (
    <>
      <div className="pagehead">
        <div>
          <h1 className="pagehead__title">Readiness portfolio</h1>
          <p className="pagehead__sub">
            {stats.orgCount} client orgs assessed for Agentforce readiness. Select an org to drill in.
          </p>
        </div>
      </div>

      <KpiRow stats={stats} />

      <div className="grid grid--portfolio">
        <section className="card">
          <div className="card__head">
            <h2 className="card__title">Readiness distribution</h2>
            <span className="card__hint">orgs per band</span>
          </div>
          <BandBar breakdown={bands} />
        </section>

        <section className="card">
          <div className="card__head">
            <h2 className="card__title">Most common problems</h2>
            <span className="card__hint">findings by type, all orgs</span>
          </div>
          <FindingAnalytics breakdown={findingMix} />
        </section>

        <section className="card card--wide">
          <div className="card__head">
            <h2 className="card__title">Where to spend</h2>
            <span className="card__hint">readiness vs remediation effort · click a dot</span>
          </div>
          <Quadrant rows={rows} />
        </section>

        <section className="card card--wide">
          <div className="card__head">
            <h2 className="card__title">Orgs</h2>
            <span className="card__hint">sort by any column · click a row to open</span>
          </div>
          <OrgsTable rows={rows} />
        </section>
      </div>
    </>
  )
}
