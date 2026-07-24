import { bandKey, BAND_META } from '../lib/data.js'

// Segmented bar of how many orgs sit in each readiness band.
export default function BandBar({ breakdown }) {
  const total = breakdown.reduce((s, b) => s + b.count, 0) || 1
  return (
    <div className="bandbar">
      <div className="bandbar__track">
        {breakdown.map((b) => b.count > 0 && (
          <div
            key={b.band}
            className={`bandbar__seg bandbar__seg--${bandKey(b.band)}`}
            style={{ width: `${(b.count / total) * 100}%` }}
            title={`${b.band}: ${b.count}`}
          >
            {b.count}
          </div>
        ))}
      </div>
      <div className="bandbar__legend">
        {breakdown.map((b) => (
          <span key={b.band} className="bandbar__key">
            <span className={`dot dot--band-${bandKey(b.band)}`} />
            {BAND_META[b.band].short} <b>{b.count}</b>
          </span>
        ))}
      </div>
    </div>
  )
}
