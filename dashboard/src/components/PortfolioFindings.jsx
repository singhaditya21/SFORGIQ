import { useState } from 'react'
import { ruleLabel } from '../lib/data.js'

const PAGE = 60

// Findings across every org, for whatever is currently filtered. This is what a
// chart click actually drills *into* — and each row drills further, into the org.
export default function PortfolioFindings({ findings }) {
  const [shown, setShown] = useState(PAGE)
  const go = (id) => { window.location.hash = `#/org/${encodeURIComponent(id)}` }
  const rows = findings.slice(0, shown)

  return (
    <>
      <div className="table__wrap">
        <table className="table">
          <thead>
            <tr>
              <th className="c-sev">Severity</th>
              <th>Org</th>
              <th>Rule</th>
              <th>Component</th>
              <th>Evidence</th>
              <th className="c-num">Pts</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => (
              <tr key={`${f.orgId}-${f.externalId}`} className="row" onClick={() => go(f.orgId)}
                  title={`Open ${f.org}`}>
                <td className="c-sev">
                  <span className={`tag tag--${f.severity.toLowerCase()}`}>{f.severity}</span>
                </td>
                <td className="org-name">{f.org}</td>
                <td className="c-rule">{ruleLabel(f.ruleId)}</td>
                <td className="c-comp"><code>{f.component}</code></td>
                <td className="c-ev">{f.evidence}</td>
                <td className="c-num">{f.effortPoints}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={6} className="table__empty">No findings match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {shown < findings.length && (
        <button className="btn btn--sm morebtn" onClick={() => setShown((n) => n + PAGE * 4)}>
          Show more — {(findings.length - shown).toLocaleString()} remaining
        </button>
      )}
    </>
  )
}
