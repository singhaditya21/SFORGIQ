import { useState } from 'react'
import { shownShare } from '../lib/data.js'

// What each identity can actually do.
//
// The rest of this dashboard reports what is wrong. This reports what *is* —
// the capability surface assembled from the profile, the layouts it is given,
// the flows it can start, the approvals it takes part in and the validation
// rules that constrain it. An agent runs as a persona and can therefore do
// exactly what that persona can do, so this is the question a reviewer signing
// off an agent actually has, and a backlog of problems cannot answer it: it
// lists the personas that are wrong and says nothing about the ones that are
// right, which is most of them.
//
// Two things are deliberately not rendered as zero. A permission set assigns no
// layouts, so it has no visible-field share — shown as "—", because 0% would
// read as a finding about the persona instead of a fact about where layouts
// live. And a persona with blanket access has no meaningful object count: it
// reaches everything, and a number would imply a boundary.

function Bar({ share }) {
  if (share == null) return <span className="psurface__na" title="A permission set assigns no layouts, so it has no visible-field count.">—</span>
  const pct = Math.round(share * 100)
  return (
    <span className="psurface__bar" title={`${pct}% of the fields this persona may read are on a layout assigned to it`}>
      <span className="psurface__fill" style={{ width: `${Math.max(2, pct)}%` }} />
      <span className="psurface__pct">{pct}%</span>
    </span>
  )
}

function Detail({ p }) {
  const lists = [
    ['Can edit', p.editableObjects],
    ['Can start', p.flowNames],
    ['Constrained by', p.blockingRules],
  ].filter(([, v]) => v && v.length)

  return (
    <div className="psurface__detail">
      {lists.map(([label, items]) => (
        <div key={label} className="psurface__list">
          <div className="psurface__listhead">{label}</div>
          <div className="psurface__chips">
            {items.map((i) => <span key={i} className="psurface__chip">{i}</span>)}
          </div>
        </div>
      ))}
      {!lists.length && (
        <div className="psurface__listhead">
          Nothing recorded beyond the counts — this persona grants blanket access,
          which is not a list of objects.
        </div>
      )}
      <p className="psurface__caveat">
        Effective access is profile plus permission sets plus permission set
        groups minus muting, and metadata alone does not say which users hold
        which — so this is the access this persona <b>grants</b>, not what a named
        person ended up with. Sharing rules decide record visibility on a
        different axis and are not modelled.
      </p>
    </div>
  )
}

export default function PersonaPanel({ rows, showOrg = true }) {
  const [open, setOpen] = useState(null)

  if (!rows.length) {
    return (
      <div className="drift__none">
        No persona surfaces — this scan could not read profile or permission-set
        metadata, which is not the same as the org having no personas.
      </div>
    )
  }

  return (
    <div className={`psurface${showOrg ? '' : ' psurface--noorg'}`}>
      <div className="psurface__row psurface__row--head">
        <span>Persona</span>
        {showOrg && <span>Org</span>}
        <span className="psurface__n">Edits</span>
        <span className="psurface__n">Deletes</span>
        <span>Shown</span>
        <span className="psurface__n">Starts</span>
        <span className="psurface__n">Approves</span>
        <span className="psurface__n">Blocked</span>
      </div>
      {rows.map((p) => {
        const key = `${p.scanId}|${p.kind}|${p.name}`
        const isOpen = open === key
        return (
          <div key={key} className={`psurface__item${isOpen ? ' is-open' : ''}`}>
            <button className="psurface__row" onClick={() => setOpen(isOpen ? null : key)}
                    title={p.summary}>
              <span className="psurface__name">
                <span className={`psurface__kind psurface__kind--${p.kind === 'Profile' ? 'profile' : 'permset'}`}>
                  {p.kind === 'Profile' ? 'PRF' : 'PS'}
                </span>
                {p.name}
                {p.unbounded && <span className="tag tag--critical">unbounded</span>}
              </span>
              {showOrg && <span className="psurface__org">{p.org}</span>}
              <span className="psurface__n">{p.unbounded ? 'all' : p.objectsEditable}</span>
              <span className="psurface__n">{p.objectsDeletable || '·'}</span>
              <Bar share={shownShare(p)} />
              <span className="psurface__n">{p.flows || '·'}</span>
              <span className="psurface__n">{p.approvals || '·'}</span>
              <span className="psurface__n">{p.blockedBy || '·'}</span>
            </button>
            {isOpen && <Detail p={p} />}
          </div>
        )
      })}
    </div>
  )
}
