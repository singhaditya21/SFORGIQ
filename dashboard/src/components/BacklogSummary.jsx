import { backlogSummary, severityCounts, SEVERITY_ORDER } from '../lib/data.js'

export default function BacklogSummary({ findings }) {
  const b = backlogSummary(findings)
  const sev = severityCounts(findings)
  const maxEpicEffort = Math.max(1, ...b.epics.map((e) => e.effort))

  return (
    <section className="card backlog">
      <div className="card__head">
        <h2 className="card__title">Remediation backlog</h2>
        <span className="card__hint">threshold-gated · severity ≥ Medium and confidence ≥ Medium</span>
      </div>

      <div className="backlog__stats">
        <div className="stat">
          <div className="stat__num">{b.ticketCount}</div>
          <div className="stat__label">backlog items</div>
        </div>
        <div className="stat">
          <div className="stat__num">{b.totalEffort}</div>
          <div className="stat__label">effort points<span className="stat__prov"> · provisional</span></div>
        </div>
        <div className="stat">
          <div className="stat__num">{b.observationCount}</div>
          <div className="stat__label">observations held back</div>
        </div>
      </div>

      <div className="backlog__sev">
        {SEVERITY_ORDER.map((s) => (
          sev[s] > 0 && (
            <div key={s} className="sevrow">
              <span className={`dot dot--${s.toLowerCase()}`} />
              <span className="sevrow__name">{s}</span>
              <span className="sevrow__count">{sev[s]}</span>
            </div>
          )
        ))}
      </div>

      <div className="backlog__epics">
        <div className="backlog__epicshead">By work stream</div>
        {b.epics.map((e) => (
          <div key={e.epic} className="epic">
            <div className="epic__top">
              <span className="epic__name">{e.epic}</span>
              <span className="epic__nums">{e.count} items · {e.effort} pts</span>
            </div>
            <div className="epic__bar">
              <div className="epic__fill" style={{ width: `${(e.effort / maxEpicEffort) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
