import { bandKey } from '../lib/data.js'

// Grounding economics for the whole portfolio (PRD §5.3).
//
// The argument this card has to make, in order: Agentforce grounds through
// RETRIEVAL, so the first cost of a bloated metadata corpus is ACCURACY — how
// much of what comes back actually tells two fields apart. Payload size is the
// second story, and it is dead weight competing for retrieval surface, not a
// bill. Every figure is a deterministic estimate over normalised text, so every
// figure is labelled as one.

const fmt = (v) => v.toLocaleString()
// 2.2% stays "2.2%", 18% does not become "18.0%" — and 9.96% rounds to "10%",
// not to the "10.0%" a naive threshold on the raw value produces.
function pct(v) {
  const s = v >= 10 ? String(Math.round(v)) : v.toFixed(1)
  return `${s.endsWith('.0') ? s.slice(0, -2) : s}%`
}

const TOP_ORGS = 6

export default function GroundingEconomics({ econ, rule, onRule }) {
  const go = (id) => { window.location.hash = `#/org/${encodeURIComponent(id)}` }

  if (!econ || econ.current <= 0) {
    return (
      <p className="gecon__none">
        These scans carry no grounding figures — they predate semantic density and the payload
        estimate. Re-scan to populate them; nothing here is inferred in their absence.
      </p>
    )
  }

  const densityPct = econ.density == null ? null : Math.round(econ.density * 100)
  const orgs = econ.orgs.slice(0, TOP_ORGS)
  const maxRemovable = Math.max(1, ...orgs.map((o) => o.removable))
  // Both payload bars share the "today" scale, so "after" reads as a share of
  // before rather than as its own full-width bar.
  const shareOfCurrent = (v) => (v / econ.current) * 100

  return (
    <div className="gecon">
      <div className="gecon__cols">
        <section className="gecon__panel">
          <h3 className="gecon__k">Semantic density — the accuracy story</h3>
          {densityPct == null ? (
            <p className="gecon__note">Not reported by these scans.</p>
          ) : (
            <>
              <div className="gecon__big">{densityPct}<span className="gecon__unit">%</span></div>
              <div className="gecon__meter">
                <div className="gecon__meterfill" style={{ width: `${densityPct}%` }} />
              </div>
              <p className="gecon__lead">
                of the description text a retriever carries actually disambiguates one field
                from another.
              </p>
              <p className="gecon__note">
                Agentforce grounds by <em>retrieving</em> metadata, not by injecting the whole
                schema — so bloat costs <strong>accuracy</strong> first. The other {100 - densityPct}%
                {' '}restates the field&rsquo;s own name or label, or is filler too generic to separate
                two candidates: text the retriever still ranks on and the planner learns nothing from.
              </p>
              <p className="gecon__fine">
                Weighted by each org&rsquo;s own payload across {econ.orgCount} orgs, so a large noisy
                org outweighs a small clean one. Counted in normalised words — a deterministic
                estimate, not a model tokenizer.
              </p>
            </>
          )}
        </section>

        <section className="gecon__panel">
          <h3 className="gecon__k">Retrieved payload — current vs remediated</h3>
          <div className="gecon__big">
            {fmt(econ.removable)}<span className="gecon__unit"> tok removable</span>
          </div>
          <div className="gecon__ba">
            <div className="gecon__barow">
              <span className="gecon__balabel">today</span>
              <span className="gecon__batrack"><span className="gecon__bafill" style={{ width: '100%' }} /></span>
              <span className="gecon__baval">{fmt(econ.current)}</span>
            </div>
            <div className="gecon__barow">
              <span className="gecon__balabel">remediated</span>
              <span className="gecon__batrack">
                <span className="gecon__bafill gecon__bafill--after"
                      style={{ width: `${shareOfCurrent(econ.remediated)}%` }} />
              </span>
              <span className="gecon__baval">{fmt(econ.remediated)}</span>
            </div>
          </div>
          <p className="gecon__lead">
            {pct(econ.removablePct)} of the corpus is dead weight — removable without losing
            any information the schema did not already carry.
          </p>
          <p className="gecon__note">
            The same fields re-estimated after remediations this tool already tickets. Treat it as
            retrieval surface reclaimed from text that competes with the fields that do carry
            signal — not as a saving to bank.
          </p>
          <p className="gecon__fine">
            Deterministic estimate over normalised words and characters (PRD §5.3) — never a model
            tokenizer&rsquo;s count, never a billed cost.
          </p>
        </section>

        <section className="gecon__panel">
          <h3 className="gecon__k">Where the removable payload comes from</h3>
          {econ.levers ? (
            <>
              <div className="gecon__levers">
                {econ.levers.map((l) => {
                  const bar = (
                    <>
                      <span className="gecon__levertop">
                        <span className="gecon__levername">{l.label}</span>
                        <span className="gecon__leverval">{fmt(l.tokens)} tok</span>
                      </span>
                      <span className="gecon__leverbar">
                        <span className="gecon__leverfill" style={{ width: `${l.pct}%` }} />
                      </span>
                    </>
                  )
                  // A bucket this build has no rule for still shows its tokens —
                  // dropping it would break the attribution line below — but it
                  // has nothing to drill into, so it is not a button.
                  return l.ruleId ? (
                    <button key={l.key}
                            className={`gecon__lever ${rule === l.ruleId ? 'gecon__lever--on' : ''}`}
                            onClick={() => onRule(l.ruleId)}
                            title={`Filter the portfolio to ${l.label} findings`}>{bar}</button>
                  ) : (
                    <div key={l.key} className="gecon__lever gecon__lever--static">{bar}</div>
                  )
                })}
              </div>
              <p className="gecon__fine">
                {fmt(econ.leverTotal)} of {fmt(econ.removable)} removable tokens attributed to a
                play. Click one to filter the portfolio to its findings.
              </p>
            </>
          ) : (
            <p className="gecon__note">
              These scans report the payload totals but not a per-play split, so only the totals are
              shown. A breakdown has to come from the scanner — it cannot be recovered from the
              totals, and nothing is guessed here to fill the gap.
            </p>
          )}
        </section>
      </div>

      <div className="gecon__orgs">
        <h3 className="gecon__k">Most removable payload, by org</h3>
        <div className="gecon__orgrows">
          {orgs.map((o) => (
            <button key={o.externalId} className="gecon__org" onClick={() => go(o.externalId)}
                    title={`Open ${o.name}`}>
              <span className={`gecon__orgband gecon__orgband--${bandKey(o.band)}`} />
              <span className="gecon__orgname">{o.name}</span>
              <span className="gecon__orgbar">
                <span className="gecon__orgfill" style={{ width: `${(o.removable / maxRemovable) * 100}%` }} />
              </span>
              <span className="gecon__orgval">{fmt(o.removable)} tok</span>
              <span className="gecon__orgden">
                {o.density == null ? '—' : `${Math.round(o.density * 100)}% dense`}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
