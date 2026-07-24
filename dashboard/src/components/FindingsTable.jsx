import { Fragment, useMemo, useState } from 'react'
import { SEVERITY_ORDER, ruleLabel } from '../lib/data.js'

const SEV_RANK = { Critical: 0, High: 1, Medium: 2, Low: 3 }

export default function FindingsTable({ findings }) {
  const [severity, setSeverity] = useState('All')
  const [rule, setRule] = useState('All')
  const [backlogOnly, setBacklogOnly] = useState(false)
  const [q, setQ] = useState('')
  const [open, setOpen] = useState(null)

  const rules = useMemo(
    () => Array.from(new Set(findings.map((f) => f.ruleId))).sort(),
    [findings],
  )

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return findings
      .filter((f) => severity === 'All' || f.severity === severity)
      .filter((f) => rule === 'All' || f.ruleId === rule)
      .filter((f) => !backlogOnly || f.emitsToBacklog)
      .filter((f) =>
        !needle ||
        f.component.toLowerCase().includes(needle) ||
        f.evidence.toLowerCase().includes(needle))
      .sort((a, b) =>
        (SEV_RANK[a.severity] - SEV_RANK[b.severity]) ||
        a.ruleId.localeCompare(b.ruleId) ||
        a.component.localeCompare(b.component))
  }, [findings, severity, rule, backlogOnly, q])

  return (
    <section className="card findings">
      <div className="card__head">
        <h2 className="card__title">Findings</h2>
        <span className="card__hint">{rows.length} of {findings.length} shown</span>
      </div>

      <div className="filters">
        <input
          className="filters__search"
          type="search"
          placeholder="Search component or evidence…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="All">All severities</option>
          {SEVERITY_ORDER.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={rule} onChange={(e) => setRule(e.target.value)}>
          <option value="All">All rules</option>
          {rules.map((r) => <option key={r} value={r}>{ruleLabel(r)}</option>)}
        </select>
        <label className="filters__toggle">
          <input type="checkbox" checked={backlogOnly}
                 onChange={(e) => setBacklogOnly(e.target.checked)} />
          Backlog only
        </label>
      </div>

      <div className="table__wrap">
        <table className="table">
          <thead>
            <tr>
              <th className="c-sev">Severity</th>
              <th className="c-conf">Conf.</th>
              <th>Rule</th>
              <th>Component</th>
              <th>Evidence</th>
              <th className="c-num">Pts</th>
              <th className="c-flag">Backlog</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((f) => {
              const isOpen = open === f.externalId
              return (
                <Fragment key={f.externalId}>
                  <tr
                      className={`row ${isOpen ? 'row--open' : ''}`}
                      onClick={() => setOpen(isOpen ? null : f.externalId)}>
                    <td className="c-sev">
                      <span className={`tag tag--${f.severity.toLowerCase()}`}>{f.severity}</span>
                    </td>
                    <td className="c-conf">{f.confidence}</td>
                    <td className="c-rule">{ruleLabel(f.ruleId)}</td>
                    <td className="c-comp"><code>{f.component}</code></td>
                    <td className="c-ev">{f.evidence}</td>
                    <td className="c-num">{f.effortPoints}</td>
                    <td className="c-flag">
                      {f.emitsToBacklog
                        ? <span className="check" title="Emits to backlog">●</span>
                        : <span className="dash" title="Held back as observation">—</span>}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="detail">
                      <td colSpan={7}>
                        <div className="detail__grid">
                          <div>
                            <div className="detail__h">Remediation</div>
                            <pre className="detail__pre">{f.remediation}</pre>
                          </div>
                          <div className="detail__side">
                            <div><span className="detail__k">Rule</span> {f.ruleId}</div>
                            <div><span className="detail__k">Dimension</span> {f.dimension}</div>
                            <div><span className="detail__k">Maturity</span> {f.ruleMaturity}</div>
                            <div><span className="detail__k">Blast radius</span> {f.blastRadius} <span className="detail__muted">(source mode)</span></div>
                            <div><span className="detail__k">Status</span> {f.status}</div>
                            <div><span className="detail__k">ID</span> <code>{f.externalId}</code></div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
            {rows.length === 0 && (
              <tr><td colSpan={7} className="table__empty">No findings match these filters.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}
