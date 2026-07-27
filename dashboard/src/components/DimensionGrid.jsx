import DimensionRadar from './DimensionRadar.jsx'

function Cell({ dim, clickable, active, onSelect, className, children }) {
  const Tag = clickable ? 'button' : 'div'
  return (
    <Tag className={`${className}${clickable ? ' dim--click' : ''}${active ? ' is-active' : ''}`}
         {...(clickable ? { onClick: () => onSelect(dim.code), type: 'button' } : {})}>
      {children}
    </Tag>
  )
}

// The five OrgIQ dimensions. Assessed ones show a score bar; unassessed ones
// state what signal is missing (honest about coverage — PRD §7.2.4).
export default function DimensionGrid({ dimensions, active = null, onSelect = null }) {
  const anyAssessed = dimensions.some((d) => d.status === 'Assessed' && d.score != null)
  return (
    <section className="card dims">
      <div className="card__head">
        <h2 className="card__title">Dimensions</h2>
        <span className="card__hint">D1–D5 · only assessed dimensions feed the composite</span>
      </div>
      <div className="dims__body">
        {anyAssessed && (
          <div className="dims__radar"><DimensionRadar dimensions={dimensions} /></div>
        )}
        <div className="dims__grid">
        {dimensions.map((d) => {
          const assessed = d.status === 'Assessed'
          const scoreKey =
            d.score == null ? 'na'
              : d.score <= 40 ? 'low'
                : d.score <= 60 ? 'mid'
                  : d.score <= 80 ? 'ok' : 'good'
          return (
            // Unassessed dimensions are not clickable: filtering to a
            // dimension whose rules never ran would show an empty table and
            // read as "nothing wrong here", which is the opposite of what an
            // unassessed dimension means.
            <Cell key={d.code} dim={d} clickable={Boolean(onSelect) && assessed}
                  active={active === d.code} onSelect={onSelect}
                  className={`dim ${assessed ? '' : 'dim--muted'}`}>
              <div className="dim__top">
                <span className="dim__code">{d.code}</span>
                {d.inComposite && <span className="dim__badge">in composite</span>}
              </div>
              <div className="dim__name">{d.name}</div>
              {assessed ? (
                <>
                  <div className="dim__score">
                    <span className={`dim__num dim__num--${scoreKey}`}>{d.score}</span>
                    <span className="dim__denom">/100</span>
                  </div>
                  <div className="dim__bar">
                    <div className={`dim__fill dim__fill--${scoreKey}`}
                         style={{ width: `${d.score}%` }} />
                  </div>
                  <div className="dim__meta">coverage {Math.round(d.coverage)}%</div>
                </>
              ) : (
                <>
                  <div className="dim__status">{d.status}</div>
                  <div className="dim__missing">{d.missingSignals}</div>
                </>
              )}
            </Cell>
          )
        })}
        </div>
      </div>
    </section>
  )
}
