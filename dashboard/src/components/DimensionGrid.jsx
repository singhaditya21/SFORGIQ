// The five OrgIQ dimensions. Assessed ones show a score bar; unassessed ones
// state what signal is missing (honest about coverage — PRD §7.2.4).
export default function DimensionGrid({ dimensions }) {
  return (
    <section className="card dims">
      <div className="card__head">
        <h2 className="card__title">Dimensions</h2>
        <span className="card__hint">D1–D5 · only assessed dimensions feed the composite</span>
      </div>
      <div className="dims__grid">
        {dimensions.map((d) => {
          const assessed = d.status === 'Assessed'
          const scoreKey =
            d.score == null ? 'na'
              : d.score <= 40 ? 'low'
                : d.score <= 60 ? 'mid'
                  : d.score <= 80 ? 'ok' : 'good'
          return (
            <div key={d.code} className={`dim ${assessed ? '' : 'dim--muted'}`}>
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
            </div>
          )
        })}
      </div>
    </section>
  )
}
