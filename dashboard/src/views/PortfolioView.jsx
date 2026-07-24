import { useMemo, useState } from 'react'
import {
  portfolioStats, bandBreakdown, portfolioFindingBreakdown, dimensionAverages,
  orgRows, heatmapRows, flattenFindings, applyFindingFilter,
  EMPTY_FILTER, findingFilterActive, ruleLabel, BAND_META,
  backlogCsv, downloadCsv,
} from '../lib/data.js'
import KpiRow from '../components/KpiRow.jsx'
import FilterBar from '../components/FilterBar.jsx'
import BandBar from '../components/BandBar.jsx'
import Quadrant from '../components/Quadrant.jsx'
import FindingAnalytics from '../components/FindingAnalytics.jsx'
import DimensionAverages from '../components/DimensionAverages.jsx'
import Heatmap from '../components/Heatmap.jsx'
import OrgGrid from '../components/OrgGrid.jsx'
import OrgsTable from '../components/OrgsTable.jsx'
import PortfolioFindings from '../components/PortfolioFindings.jsx'

export default function PortfolioView({ data }) {
  const scans = data.scans
  const [filter, setFilter] = useState(EMPTY_FILTER)

  // Every widget both reads and writes this one filter — clicking the same
  // value twice clears it.
  const toggle = (key, value) =>
    setFilter((f) => ({ ...f, [key]: f[key] === value ? null : value }))
  const drop = (key) => setFilter((f) => ({ ...f, [key]: null }))
  const clear = () => setFilter(EMPTY_FILTER)

  const stats = portfolioStats(scans)
  const bands = bandBreakdown(scans)
  const dimAvgs = dimensionAverages(scans)
  const findingMix = portfolioFindingBreakdown(scans)
  const rows = useMemo(() => orgRows(scans), [scans])
  const allFindings = useMemo(() => flattenFindings(scans), [scans])

  const bandOrgIds = useMemo(
    () => new Set(rows.filter((r) => !filter.band || r.band === filter.band).map((r) => r.externalId)),
    [rows, filter.band])
  const matching = useMemo(
    () => applyFindingFilter(allFindings, filter).filter((f) => bandOrgIds.has(f.orgId)),
    [allFindings, filter, bandOrgIds])
  const matchOrgIds = useMemo(() => new Set(matching.map((f) => f.orgId)), [matching])

  const shownOrgs = rows
    .filter((r) => bandOrgIds.has(r.externalId))
    .filter((r) => !findingFilterActive(filter) || matchOrgIds.has(r.externalId))
  const shownIds = new Set(shownOrgs.map((r) => r.externalId))
  const heat = heatmapRows(scans).filter((h) => shownIds.has(h.externalId))

  // One import file for everything on screen. The gate is re-applied by
  // backlogCsv, but count it here so the button can say what it will hand over
  // and stay dead when the current filter has no tickets in it.
  const gated = useMemo(() => matching.filter((f) => f.emitsToBacklog), [matching])

  const onDownload = () => {
    const scanById = new Map(scans.map((s) => [s.scan.externalId, s.scan]))
    const byOrg = new Map()
    for (const f of gated) {
      if (!byOrg.has(f.orgId)) byOrg.set(f.orgId, [])
      byOrg.get(f.orgId).push(f)
    }
    // backlogCsv needs one scan for the description block, so build it per org
    // and concatenate in the table's order: severity-sorted within an org, orgs
    // in the order the page shows them. Every header but the first is dropped —
    // the header line has no quoted newlines, so the first CRLF ends it.
    const parts = shownOrgs
      .filter((r) => byOrg.has(r.externalId))
      .map((r) => backlogCsv(scanById.get(r.externalId), byOrg.get(r.externalId)))
    const csv = parts.map((p, i) => (i === 0 ? p : p.slice(p.indexOf('\r\n') + 2))).join('')
    downloadCsv('orgiq-portfolio-backlog.csv', csv)
  }

  const drillLabel = filter.rule ? ruleLabel(filter.rule)
    : filter.dimension ? `${filter.dimension} findings`
      : filter.severity ? `${filter.severity}-severity findings` : ''

  return (
    <>
      <div className="pagehead">
        <div>
          <h1 className="pagehead__title">Readiness portfolio</h1>
          <p className="pagehead__sub">
            {stats.orgCount} client orgs assessed. Click any metric, bar, cell or row to drill in.
          </p>
        </div>
        <button className="btn" onClick={onDownload} disabled={!gated.length}
                title={`Threshold-gated findings for the ${shownOrgs.length} orgs shown, `
                  + 'in the scanner’s backlog column order'}>
          ⬇ Download backlog CSV · {gated.length.toLocaleString()} tickets
        </button>
      </div>

      <KpiRow stats={stats} filter={filter} onFilter={toggle} />

      <FilterBar filter={filter} onClear={clear} onDrop={drop}
                 matchCount={findingFilterActive(filter) ? matching.length : null}
                 orgCount={shownOrgs.length} />

      <div className="grid grid--portfolio">
        <section className="card">
          <div className="card__head">
            <h2 className="card__title">Readiness distribution</h2>
            <span className="card__hint">click a band</span>
          </div>
          <BandBar breakdown={bands} active={filter.band} onSelect={(b) => toggle('band', b)} />
        </section>

        <section className="card">
          <div className="card__head">
            <h2 className="card__title">Average by dimension</h2>
            <span className="card__hint">click to filter</span>
          </div>
          <DimensionAverages averages={dimAvgs} dimension={filter.dimension}
                             onDimension={(d) => toggle('dimension', d)} />
        </section>

        {/* Sits in row 1 with the two short cards so all three are a similar
            height — a tall card here stretched its neighbours into ~900px of
            dead white space. */}
        <section className="card card--flex">
          <div className="card__head">
            <h2 className="card__title">Where to spend</h2>
            <span className="card__hint">readiness vs effort · click a dot</span>
          </div>
          <Quadrant rows={rows} activeBand={filter.band} />
        </section>

        {/* Full width, bars laid out in columns: 21 rules stacked in a third of
            the screen is what made this card 1,100px tall. */}
        <section className="card card--full">
          <div className="card__head">
            <h2 className="card__title">Most common problems</h2>
            <span className="card__hint">findings by type · click a bar to filter</span>
          </div>
          <FindingAnalytics breakdown={findingMix} rule={filter.rule} severity={filter.severity}
                            onRule={(r) => toggle('rule', r)}
                            onSeverity={(s) => toggle('severity', s)} />
        </section>

        <section className="card card--full">
          <div className="card__head">
            <h2 className="card__title">Every org against every dimension</h2>
            <span className="card__hint">{heat.length} orgs · darker is worse · click a row or a column</span>
          </div>
          <Heatmap rows={heat} dimension={filter.dimension}
                   onDimension={(d) => toggle('dimension', d)} />
        </section>

        <section className="card card--full">
          <div className="card__head">
            <h2 className="card__title">
              All orgs
              {filter.band && (
                <span className={`chip chip--${BAND_META[filter.band].key}`}>
                  {BAND_META[filter.band].short}
                  <button className="chip__x" onClick={() => drop('band')}>✕</button>
                </span>
              )}
            </h2>
            <span className="card__hint">{shownOrgs.length} shown</span>
          </div>
          <OrgGrid rows={shownOrgs} />
        </section>

        {findingFilterActive(filter) && (
          <section className="card card--full">
            <div className="card__head">
              <h2 className="card__title">{drillLabel} — across the portfolio</h2>
              <span className="card__hint">
                {matching.length.toLocaleString()} findings in {matchOrgIds.size} orgs · click a row to open the org
              </span>
            </div>
            <PortfolioFindings findings={matching} />
          </section>
        )}

        <section className="card card--full">
          <div className="card__head">
            <h2 className="card__title">Orgs — detail</h2>
            <span className="card__hint">sort by any column · click a row to open</span>
          </div>
          <OrgsTable rows={rows} band={filter.band} onBand={(b) => setFilter((f) => ({ ...f, band: b }))} />
        </section>
      </div>
    </>
  )
}
