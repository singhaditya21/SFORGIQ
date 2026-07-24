import { bandKey, BAND_META } from '../lib/data.js'

function scoreKey(n) {
  return n <= 40 ? 'low' : n <= 60 ? 'mid' : n <= 80 ? 'ok' : 'good'
}

// All orgs at a glance — every card is a drill target.
export default function OrgGrid({ rows }) {
  const go = (id) => { window.location.hash = `#/org/${encodeURIComponent(id)}` }
  if (rows.length === 0) {
    return <div className="orggrid__empty">No orgs match this filter.</div>
  }
  return (
    <div className="orggrid">
      {rows.map((r) => (
        <button key={r.externalId} className={`orgcard orgcard--${bandKey(r.band)}`}
                onClick={() => go(r.externalId)} title={`Open ${r.name}`}>
          <div className="orgcard__head">
            <span className="orgcard__name">{r.name}</span>
            <span className={`tag tag--band-${bandKey(r.band)}`}>{BAND_META[r.band].short}</span>
          </div>
          <div className="orgcard__score">
            <span className={`orgcard__num dim__num--${scoreKey(r.composite)}`}>{r.composite}</span>
            <span className="orgcard__denom">/100</span>
          </div>
          <div className="orgcard__bar">
            <div className={`orgcard__fill dim__fill--${scoreKey(r.composite)}`}
                 style={{ width: `${r.composite}%` }} />
          </div>
          <div className="orgcard__foot">
            <span>{r.findings} findings</span>
            <span>{r.effort} pts</span>
          </div>
        </button>
      ))}
    </div>
  )
}
