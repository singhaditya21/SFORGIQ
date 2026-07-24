import { BAND_META, bandKey } from '../lib/data.js'

const DIMS = ['D1', 'D2', 'D3', 'D4', 'D5']

// Worse = darker. Keeps the blue→black language of the rest of the dashboard.
function tone(score) {
  if (score == null) return 'na'
  if (score <= 40) return 's1'
  if (score <= 60) return 's2'
  if (score <= 80) return 's3'
  return 's4'
}

// Every org against every dimension, in one grid. The densest read of the whole
// portfolio: dark columns are systemic weaknesses, dark rows are the worst orgs.
export default function Heatmap({ rows, dimension, onDimension }) {
  const go = (id) => { window.location.hash = `#/org/${encodeURIComponent(id)}` }
  return (
    <div className="heat">
      <div className="heat__head">
        <span className="heat__corner">org</span>
        <button className="heat__col heat__col--score" disabled>score</button>
        {DIMS.map((d) => (
          <button
            key={d}
            className={`heat__col ${dimension === d ? 'heat__col--on' : ''}`}
            title={`Filter the portfolio to ${d} findings`}
            onClick={() => onDimension(d)}
          >
            {d}
          </button>
        ))}
      </div>
      <div className="heat__body">
        {rows.map((r) => (
          <div key={r.externalId} className="heat__row" onClick={() => go(r.externalId)}
               title={`Open ${r.name}`}>
            <span className="heat__name">
              <span className={`heat__band heat__band--${bandKey(r.band)}`} />
              {r.name}
            </span>
            <span className={`heat__cell heat__cell--${tone(r.composite)} heat__cell--score`}>
              {r.composite}
            </span>
            {DIMS.map((d) => (
              <span key={d} className={`heat__cell heat__cell--${tone(r.dims[d])}`}>
                {r.dims[d] == null ? '–' : r.dims[d]}
              </span>
            ))}
          </div>
        ))}
      </div>
      <div className="heat__legend">
        <span>worse</span>
        <span className="heat__swatch heat__cell--s1" />
        <span className="heat__swatch heat__cell--s2" />
        <span className="heat__swatch heat__cell--s3" />
        <span className="heat__swatch heat__cell--s4" />
        <span>better</span>
        <span className="heat__hint">· click a row to open the org, a column to filter that dimension</span>
      </div>
    </div>
  )
}
