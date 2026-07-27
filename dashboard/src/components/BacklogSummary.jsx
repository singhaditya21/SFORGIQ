import { backlogSummary, severityCounts, SEVERITY_ORDER } from '../lib/data.js'

function SevRow({ s, n, filter, onSelect }) {
  const Tag = onSelect ? 'button' : 'div'
  return (
    <Tag className={`sevrow${onSelect ? ' sevrow--click' : ''}`
           + (filter.severity === s ? ' is-active' : '')}
         {...(onSelect ? { onClick: () => onSelect('severity', s), type: 'button' } : {})}>
      <span className={`dot dot--${s.toLowerCase()}`} />
      <span className="sevrow__name">{s}</span>
      <span className="sevrow__count">{n}</span>
    </Tag>
  )
}

function EpicRow({ epic, filter, onSelect, children }) {
  const Tag = onSelect ? 'button' : 'div'
  return (
    <Tag className={`epic${onSelect ? ' epic--click' : ''}`
           + (filter.epic === epic ? ' is-active' : '')}
         {...(onSelect ? { onClick: () => onSelect('epic', epic), type: 'button' } : {})}>
      {children}
    </Tag>
  )
}

// `.sevrow` carried `cursor: pointer` in the stylesheet and no handler in the
// component — an affordance that promised a drill and did nothing, which is a
// worse failure than having no affordance at all. Both the severity rows and
// the work streams are real buttons now.
export default function BacklogSummary({ findings, filter = {}, onSelect = null }) {
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
            <SevRow key={s} s={s} n={sev[s]} filter={filter} onSelect={onSelect} />
          )
        ))}
      </div>

      <div className="backlog__epics">
        <div className="backlog__epicshead">By work stream</div>
        {b.epics.map((e) => (
          <EpicRow key={e.epic} epic={e.epic} filter={filter} onSelect={onSelect}>
            <div className="epic__top">
              <span className="epic__name">{e.epic}</span>
              <span className="epic__nums">{e.count} items · {e.effort} pts</span>
            </div>
            <div className="epic__bar">
              <div className="epic__fill" style={{ width: `${(e.effort / maxEpicEffort) * 100}%` }} />
            </div>
          </EpicRow>
        ))}
      </div>
    </section>
  )
}
