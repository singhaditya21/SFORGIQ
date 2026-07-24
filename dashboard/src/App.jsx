import { useEffect, useState } from 'react'
import { loadScan } from './lib/data.js'
import ReadinessHero from './components/ReadinessHero.jsx'
import DimensionGrid from './components/DimensionGrid.jsx'
import BacklogSummary from './components/BacklogSummary.jsx'
import FindingsTable from './components/FindingsTable.jsx'

export default function App() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadScan().then(setData).catch((e) => setError(e.message))
  }, [])

  if (error) {
    return (
      <div className="app">
        <div className="state state--error">Failed to load scan data: {error}</div>
      </div>
    )
  }
  if (!data) {
    return (
      <div className="app">
        <div className="state">Loading scan…</div>
      </div>
    )
  }

  const { scan, dimensions, findings } = data
  const scanDate = new Date(scan.timestamp)
  const dateLabel = isNaN(scanDate)
    ? scan.timestamp
    : scanDate.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__brand">
          <span className="topbar__logo" aria-hidden>🛰️</span>
          <div>
            <div className="topbar__title">OrgIQ</div>
            <div className="topbar__subtitle">Agentforce Readiness Analyzer</div>
          </div>
        </div>
        <div className="topbar__meta">
          <span className="pill pill--demo" title="Data bundled from the OrgIQ Salesforce org">
            Demo data · from Salesforce
          </span>
        </div>
      </header>

      <div className="scanline">
        <div className="scanline__title">
          <span className="scanline__org">{scan.targetOrg}</span>
          <span className="scanline__sep">·</span>
          <span>{scan.name}</span>
        </div>
        <div className="scanline__facts">
          <span>{scan.scanMode} mode</span>
          <span className="scanline__sep">·</span>
          <span>{scan.componentsScanned} components</span>
          <span className="scanline__sep">·</span>
          <span>rubric {scan.rubricVersion}</span>
          <span className="scanline__sep">·</span>
          <span>{dateLabel}</span>
        </div>
      </div>

      <main className="grid">
        <ReadinessHero scan={scan} />
        <DimensionGrid dimensions={dimensions} />
        <BacklogSummary findings={findings} />
        <FindingsTable findings={findings} />
      </main>

      <footer className="foot">
        <span>
          OrgIQ is a readiness assessment, not a certification. Findings are
          observed in this org, not asserted as typical. Effort points are
          provisional.
        </span>
        <a href="https://github.com/singhaditya21/SFORGIQ" target="_blank" rel="noreferrer">
          github.com/singhaditya21/SFORGIQ
        </a>
      </footer>
    </div>
  )
}
