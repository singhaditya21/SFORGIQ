import { ruleLabel } from '../lib/data.js'

// Where the estate disagrees with itself. This is the reading no single-org scan
// can produce: an agent proven in one org and run in another was only ever
// proven against the schema, automation and permissions of the org it was tested
// in — so a gap here is not untidiness, it is an invalid test.
export default function DriftPanel({ rows }) {
  const go = (id) => { window.location.hash = `#/org/${encodeURIComponent(id)}` }
  if (!rows.length) {
    return <div className="drift__none">No drift detected — every org matches the reference.</div>
  }
  return (
    <div className="drift">
      {rows.map((r) => (
        <button key={r.externalId} className="driftrow" onClick={() => go(r.externalId)}
                title={`Open ${r.org}`}>
          <span className="driftrow__head">
            <span className={`tag tag--${r.worst.toLowerCase()}`}>{r.worst}</span>
            <span className="driftrow__org">{r.org}</span>
          </span>
          <span className="driftrow__items">
            {r.findings.map((f) => (
              <span key={f.externalId} className="driftrow__item">
                <b>{ruleLabel(f.ruleId)}</b> — {f.evidence.split(' — ')[0]}
              </span>
            ))}
          </span>
        </button>
      ))}
    </div>
  )
}
