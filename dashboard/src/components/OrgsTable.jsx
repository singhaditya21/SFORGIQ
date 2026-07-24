import { useMemo, useState } from 'react'
import { BAND_ORDER, bandKey, BAND_META } from '../lib/data.js'

const COLUMNS = [
  { key: 'name', label: 'Org', align: 'left' },
  { key: 'mode', label: 'Mode', align: 'left' },
  { key: 'composite', label: 'Readiness', align: 'right' },
  { key: 'band', label: 'Band', align: 'left' },
  { key: 'findings', label: 'Findings', align: 'right' },
  { key: 'backlog', label: 'Backlog', align: 'right' },
  { key: 'effort', label: 'Effort', align: 'right' },
  { key: 'topIssue', label: 'Top issue', align: 'left' },
]

export default function OrgsTable({ rows }) {
  const [sort, setSort] = useState({ key: 'composite', dir: 'asc' })
  const [band, setBand] = useState('All')
  const [q, setQ] = useState('')

  const view = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const filtered = rows
      .filter((r) => band === 'All' || r.band === band)
      .filter((r) => !needle || r.name.toLowerCase().includes(needle))
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...filtered].sort((a, b) => {
      const va = a[sort.key], vb = b[sort.key]
      if (typeof va === 'number') return (va - vb) * dir
      return String(va).localeCompare(String(vb)) * dir
    })
  }, [rows, band, q, sort])

  const clickSort = (key) =>
    setSort((s) => s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
      : { key, dir: key === 'name' || key === 'topIssue' || key === 'mode' ? 'asc' : 'desc' })

  const go = (id) => { window.location.hash = `#/org/${encodeURIComponent(id)}` }

  return (
    <div className="orgs">
      <div className="filters">
        <input className="filters__search" type="search" placeholder="Search orgs…"
               value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={band} onChange={(e) => setBand(e.target.value)}>
          <option value="All">All bands</option>
          {BAND_ORDER.map((b) => <option key={b} value={b}>{b}</option>)}
        </select>
        <span className="filters__count">{view.length} of {rows.length}</span>
      </div>
      <div className="table__wrap">
        <table className="table orgs__table">
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th key={c.key}
                    className={`${c.align === 'right' ? 'c-num' : ''} th-sort ${sort.key === c.key ? 'th-sort--on' : ''}`}
                    onClick={() => clickSort(c.key)}>
                  {c.label}{sort.key === c.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.map((r) => (
              <tr key={r.externalId} className="row" onClick={() => go(r.externalId)}>
                <td className="org-name">{r.name}</td>
                <td className="c-mode">{r.mode}</td>
                <td className="c-num"><b>{r.composite}</b></td>
                <td>
                  <span className={`tag tag--band-${bandKey(r.band)}`}>{BAND_META[r.band].short}</span>
                </td>
                <td className="c-num">{r.findings}</td>
                <td className="c-num">{r.backlog}</td>
                <td className="c-num">{r.effort}</td>
                <td className="c-topissue">{r.topIssue}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
