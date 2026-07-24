import { useState } from 'react'
import {
  portfolioStats, bandBreakdown, portfolioFindingBreakdown, orgRows, BAND_META,
} from '../lib/data.js'
import KpiRow from '../components/KpiRow.jsx'
import BandBar from '../components/BandBar.jsx'
import Quadrant from '../components/Quadrant.jsx'
import FindingAnalytics from '../components/FindingAnalytics.jsx'
import OrgGrid from '../components/OrgGrid.jsx'
import OrgsTable from '../components/OrgsTable.jsx'

export default function PortfolioView({ data }) {
  const scans = data.scans
  const [band, setBand] = useState(null)          // shared readiness-band filter

  const stats = portfolioStats(scans)
  const bands = bandBreakdown(scans)
  const findingMix = portfolioFindingBreakdown(scans)
  const rows = orgRows(scans)
  const shown = band ? rows.filter((r) => r.band === band) : rows

  return (
    <>
      <div className="pagehead">
        <div>
          <h1 className="pagehead__title">Readiness portfolio</h1>
          <p className="pagehead__sub">
            {stats.orgCount} client orgs assessed for Agentforce readiness. Click any org to drill in.
          </p>
        </div>
      </div>

      <KpiRow stats={stats} />

      <div className="grid grid--portfolio">
        <section className="card">
          <div className="card__head">
            <h2 className="card__title">Readiness distribution</h2>
            <span className="card__hint">click a band to filter</span>
          </div>
          <BandBar breakdown={bands} active={band} onSelect={setBand} />
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
            <h2 className="card__title">
              All orgs
              {band && (
                <span className={`chip chip--${BAND_META[band].key}`}>
                  {BAND_META[band].short}
                  <button className="chip__x" onClick={() => setBand(null)}>✕</button>
                </span>
              )}
            </h2>
            <span className="card__hint">{shown.length} shown · click a card to open</span>
          </div>
          <OrgGrid rows={shown} />
        </section>

        <section className="card card--wide">
          <div className="card__head">
            <h2 className="card__title">Where to spend</h2>
            <span className="card__hint">readiness vs remediation effort · click a dot</span>
          </div>
          <Quadrant rows={rows} activeBand={band} />
        </section>

        <section className="card card--wide">
          <div className="card__head">
            <h2 className="card__title">Orgs — detail</h2>
            <span className="card__hint">sort by any column · click a row to open</span>
          </div>
          <OrgsTable rows={rows} band={band} onBand={setBand} />
        </section>
      </div>
    </>
  )
}
