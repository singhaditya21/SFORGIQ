import { useEffect, useState } from 'react'
import { loadPortfolio, enterprisesOf, scansForEnterprise, latestScans } from './lib/data.js'
import {
  LIVE, isConfigured, beginLogin, handleRedirect, getStoredToken, loadLive, logout,
} from './lib/live.js'
import PortfolioView from './views/PortfolioView.jsx'
import OrgDetail from './views/OrgDetail.jsx'

function useHashRoute() {
  const [hash, setHash] = useState(window.location.hash || '#/')
  useEffect(() => {
    const on = () => setHash(window.location.hash || '#/')
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return hash
}

// Headline for each way live mode can end short of showing live data. The body
// of the message comes from live.js, which knows what actually happened; this is
// only the first sentence, and it exists so the banner leads with the state
// rather than with a stack of prose.
const NOTICE_TITLE = {
  [LIVE.NO_ACCESS]: 'Connected to Salesforce, but you cannot see the OrgIQ data.',
  [LIVE.EMPTY]: 'Connected to Salesforce, but there are no scans to show.',
  [LIVE.EXPIRED]: 'Your Salesforce session has expired.',
  [LIVE.UNREACHABLE]: 'Could not reach the OrgIQ org.',
  [LIVE.ERROR]: 'Could not load live data.',
  [LIVE.SIGN_IN_FAILED]: 'Salesforce sign-in did not complete.',
}

export default function App() {
  const [data, setData] = useState(null)
  const [source, setSource] = useState('demo')   // 'demo' | 'live'
  // Why we are not on live data, when we are not. Null means nothing to explain:
  // either live mode is working, or nobody has tried to connect.
  const [live, setLive] = useState(null)
  // Do we hold a token at all? It decides whether the right offer is "connect"
  // or "you are already connected, here is what is missing".
  const [authed, setAuthed] = useState(false)
  const [error, setError] = useState(null)
  // Demo mode carries two estates so an insurer and a bank each see themselves.
  // Only ever one at a time: showing both together would read as a consultancy's
  // portfolio, which is exactly what this product is not. A real install has one
  // estate and never renders this control.
  const [estate, setEstate] = useState(null)
  const hash = useHashRoute()

  useEffect(() => {
    (async () => {
      let tok = null
      let signInFailure = null
      try {
        tok = await handleRedirect()             // just came back from Salesforce?
      } catch (e) {
        signInFailure = e.message
      }
      tok = tok || getStoredToken()
      setAuthed(!!tok)

      if (tok) {
        // A stored token that still works is the more relevant state than a
        // failed re-auth, so the load result supersedes signInFailure here.
        const res = await loadLive(tok)
        setLive(res.status === LIVE.OK ? null : res)
        if (res.status === LIVE.OK) {
          setData(res.data)
          setSource('live')
          return
        }
        // Only an expired token is worth discarding. Keep it for a missing
        // permission or an empty org: those get fixed in Salesforce, and then a
        // refresh should land on live data without a second trip through OAuth.
        if (res.status === LIVE.EXPIRED) {
          logout()
          setAuthed(false)
        }
      } else if (signInFailure) {
        setLive({
          status: LIVE.SIGN_IN_FAILED,
          reason: signInFailure,
          fix: 'Click Connect Salesforce to try again — the previous authorization code is spent.',
        })
      }

      try {
        setData(await loadPortfolio())
        setSource('demo')
      } catch (e) {
        setError(e.message)
      }
    })()
  }, [])

  const disconnect = () => { logout(); window.location.reload() }
  const retry = () => window.location.reload()

  const estates = data ? enterprisesOf(data.scans) : []
  const current = estate && estates.includes(estate) ? estate : estates[0]
  // Latest scan per org: the portfolio describes the estate as it stands,
  // while OrgDetail still gets the full history for its trend.
  const view = data
    ? { ...data, scans: latestScans(scansForEnterprise(data.scans, current)) }
    : null

  const orgMatch = hash.match(/^#\/org\/(.+)$/)
  const selected = orgMatch
    ? data?.scans.find((s) => s.scan.externalId === decodeURIComponent(orgMatch[1]))
    : null

  const who = live?.identity
  return (
    <div className="app">
      <header className="topbar">
        <a className="topbar__brand" href="#/">
          <span className="topbar__logo" aria-hidden>🛰️</span>
          <div>
            <div className="topbar__title">OrgIQ</div>
            <div className="topbar__subtitle">Agentforce Readiness Analyzer</div>
          </div>
        </a>
        <div className="topbar__actions">
          {source === 'live' ? (
            <>
              <span className="pill pill--live">● Live · {data ? data.scans.length : '…'} orgs</span>
              <button className="btn btn--sm" onClick={disconnect}>Disconnect</button>
            </>
          ) : (
            <>
              <span className="pill pill--demo">Demo · {data ? data.scans.length : '…'} orgs</span>
              {/* Signed in but still on demo data: "Connect Salesforce" would be a
                  lie — they are connected, and the problem is on the org side.
                  Offer a re-check instead, for once the permission lands. */}
              {authed ? (
                <>
                  <button className="btn btn--sm" onClick={retry}>Re-check live access</button>
                  <button className="btn btn--sm" onClick={disconnect}>Sign out</button>
                </>
              ) : isConfigured() && (
                <button className="btn btn--sm" onClick={() => beginLogin()}>
                  Connect Salesforce
                </button>
              )}
            </>
          )}
        </div>
      </header>

      {live && (
        <div className="banner">
          <strong>{NOTICE_TITLE[live.status] || 'Live mode is not active.'}</strong>{' '}
          {/* Who, then what, then what to do about it. The username comes first
              because it is what the org owner needs in order to fix this, and
              because a user with two Salesforce logins has to know which one
              arrived here. */}
          {/* Not on EXPIRED: the session it identifies is over, so "signed in
              as" would be describing something that no longer exists. */}
          {who?.username && live.status !== LIVE.EXPIRED && (
            <>Signed in as <code>{who.username}</code>{who.name ? ` (${who.name})` : ''}. </>
          )}
          {live.reason}
          {live.fix && <> {live.fix}</>}
          {' '}Showing bundled demo data in the meantime — every number below is demo data,
          not this org&rsquo;s.
        </div>
      )}
      {error && <div className="state state--error">Failed to load portfolio: {error}</div>}
      {!error && !data && <div className="state">Loading portfolio…</div>}

      {data && estates.length > 1 && !selected && (
        <div className="estates">
          <span className="estates__label">Estate</span>
          {estates.map((e) => (
            <button key={e} className={`estates__pick ${e === current ? 'estates__pick--on' : ''}`}
                    onClick={() => setEstate(e)}>{e}</button>
          ))}
          <span className="estates__note">
            Demo data. One enterprise at a time — an install sees only its own estate.
          </span>
        </div>
      )}

      {view && !selected && <PortfolioView data={view} />}
      {data && selected && <OrgDetail data={data} scan={selected} />}

      <footer className="foot">
        <span>
          OrgIQ is a readiness assessment, not a certification. Findings are observed
          in each org, not asserted as typical; D2–D5 rules and effort points are
          provisional.{' '}
          {source === 'demo'
            ? 'You are looking at demo data — a synthetic portfolio bundled from the OrgIQ org, '
              + 'not a live read. Live mode needs a login in the OrgIQ org.'
            : 'You are looking at live data read from the OrgIQ org.'}
        </span>
        <a href="https://github.com/singhaditya21/SFORGIQ" target="_blank" rel="noreferrer">
          github.com/singhaditya21/SFORGIQ
        </a>
      </footer>
    </div>
  )
}
