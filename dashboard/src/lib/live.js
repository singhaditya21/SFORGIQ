// Live mode: OAuth 2.0 Authorization Code + PKCE against the OrgIQ Salesforce
// org, then read scans/findings via the REST query API. No backend — the token
// exchange happens in the browser, which is why the org needs this origin on
// its CORS allowlist.
//
// SIGNING IN AND SEEING DATA ARE TWO DIFFERENT THINGS, and the gap between them
// is where this file used to lie. OrgIQ's three objects live in one Developer
// Edition org and are reachable only through the OrgIQ_Admin permission set,
// which is assigned to a handful of named users. Everyone else completed the
// OAuth flow, got a real token, ran a query that came back refused or empty, and
// was dropped into demo data with no explanation — so from their side "connect
// to Salesforce doesn't work" stayed true, just for a new reason.
//
// So loadLive() classifies its outcome (see LIVE) instead of collapsing every
// non-success into one failure. A user who cannot see the objects, a user who
// can see them in an org with nothing loaded, and a user whose session has
// expired each need a different thing done, and none of those things is "the
// connection is broken". Where a signal is not available — who is signed in,
// whether the org holds any scans at all — this says so rather than assuming the
// friendlier reading.

import { sfConfig, redirectUri } from './sfConfig.js'
import { randomString, challengeFromVerifier } from './pkce.js'

const V = 'orgiq_pkce_verifier'
const S = 'orgiq_pkce_state'
const TOK = 'orgiq_sf_token'

// The permission set that makes OrgIQ_Scan__c / _Finding__c / _Dimension_Score__c
// readable, exported because every "you cannot see the data" message has to end
// in something the reader can act on, and this is that thing.
export const ACCESS_PERM_SET = 'OrgIQ_Admin'
export const GRANT_SCRIPT = 'scripts/grant-orgiq-access.sh'

// The outcome of a live load. Everything except OK falls back to demo data, but
// each one is a different sentence on screen and a different fix off it.
export const LIVE = {
  OK: 'live',                 // authenticated, and scans came back
  NO_ACCESS: 'no-access',     // authenticated, but the org will not show this user the data
  EMPTY: 'empty',             // authenticated, permissions fine, nothing loaded to show
  EXPIRED: 'expired',         // the token is no longer good — sign in again
  UNREACHABLE: 'unreachable', // no answer from the org at all (network / CORS)
  ERROR: 'error',             // the org answered with something we do not recognise
  SIGN_IN_FAILED: 'sign-in-failed', // never got a token (OAuth redirect / token exchange)
}

export function isConfigured() {
  return !!sfConfig.clientId
}

export function getStoredToken() {
  try { return JSON.parse(sessionStorage.getItem(TOK) || 'null') } catch { return null }
}

export function logout() {
  sessionStorage.removeItem(TOK)
}

export async function beginLogin() {
  const verifier = randomString(96)
  const state = randomString(24)
  sessionStorage.setItem(V, verifier)
  sessionStorage.setItem(S, state)
  const challenge = await challengeFromVerifier(verifier)
  const p = new URLSearchParams({
    response_type: 'code',
    client_id: sfConfig.clientId,
    redirect_uri: redirectUri(),
    // `openid` is what makes /services/oauth2/userinfo answer, which is how the
    // dashboard can name the signed-in user when the data queries are refused.
    scope: 'api refresh_token openid',
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  })
  window.location.href = `${sfConfig.loginUrl}/services/oauth2/authorize?${p}`
}

function cleanUrl() {
  window.history.replaceState({}, '', window.location.origin + window.location.pathname + '#/')
}

// Call once on load: if we're back from Salesforce with ?code=, exchange it.
// Returns a token, or null if this isn't a redirect. Throws on OAuth error.
export async function handleRedirect() {
  const u = new URL(window.location.href)
  const err = u.searchParams.get('error')
  const code = u.searchParams.get('code')
  if (!err && !code) return null // not a redirect — leave the address bar alone

  // Salesforce spends the code the moment it hands it to us, so it is dead
  // whichever way this ends — including when fetch() itself rejects. Clean the
  // URL in a finally so it happens exactly once and a reload can never replay it.
  try {
    if (err) throw new Error(u.searchParams.get('error_description') || err)
    if (u.searchParams.get('state') !== sessionStorage.getItem(S)) {
      throw new Error('OAuth state mismatch')
    }
    const body = new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      client_id: sfConfig.clientId,
      redirect_uri: redirectUri(),
      code_verifier: sessionStorage.getItem(V) || '',
    })
    let res
    try {
      res = await fetch(`${sfConfig.loginUrl}/services/oauth2/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body,
      })
    } catch (e) {
      // fetch() only rejects like this on a network/CORS failure. This POST is
      // CORS-simple, so there is no preflight to block it: the org almost
      // certainly processed the exchange and we were denied the response body
      // for want of an Access-Control-Allow-Origin header.
      const why = (e && e.message) || String(e)
      throw new Error(
        `could not read the token response from ${sfConfig.loginUrl} (${why}). ` +
        `Most likely this origin (${window.location.origin}) is not on the org's ` +
        'CORS allowlist with "Allow OAuth endpoints" enabled (Setup → CORS). ' +
        'The authorization code is single-use and is now spent, so sign in again ' +
        'after fixing the allowlist — reloading this page will not recover it'
      )
    }
    if (!res.ok) {
      // Getting a response at all means CORS is fine — do not blame it. Salesforce
      // returns its own reason in the body, so show that instead of a guess.
      let detail = ''
      try {
        const err = await res.json()
        detail = [err.error, err.error_description].filter(Boolean).join(' — ')
      } catch {
        detail = (await res.text().catch(() => '')).slice(0, 200)
      }
      const hint = /invalid_grant/.test(detail)
        ? ' The authorization code is single-use: if you reloaded, or came back to an ' +
          'old tab, start the sign-in again rather than retrying this one.'
        : ''
      throw new Error(`Salesforce rejected the token exchange (${res.status}): ${detail || 'no reason given'}.${hint}`)
    }
    const t = await res.json()
    const tok = { accessToken: t.access_token, instanceUrl: t.instance_url }
    sessionStorage.setItem(TOK, JSON.stringify(tok))
    return tok
  } finally {
    cleanUrl()
  }
}

// ---- classified failures -------------------------------------------------
//
// `reason` is what happened, `fix` is what to do about it, and they stay
// separate so the banner can render them as two sentences and neither one has to
// carry the other's job. `detail` is the raw Salesforce code, kept for the
// console — useful when debugging, useless in a banner.
class LiveError extends Error {
  constructor(status, reason, fix = '', detail = '') {
    super(reason)
    this.status = status
    this.reason = reason
    this.fix = fix
    this.detail = detail
  }
}

const GRANT_FIX =
  `Ask whoever owns the OrgIQ org to assign you the ${ACCESS_PERM_SET} permission set ` +
  `(one command: ${GRANT_SCRIPT}), then hard-refresh this page.`

// Salesforce answers a bad query with [{ message, errorCode }], where message is
// the whole query plus a caret diagram and only its last line is a sentence.
// Pull out the code (what we branch on) and that sentence (what we show when the
// code is one we do not recognise).
async function readSfError(res) {
  const text = await res.text().catch(() => '')
  let body = null
  try { body = JSON.parse(text) } catch { /* not JSON — fall through to raw text */ }
  const first = Array.isArray(body) ? body[0] : body
  if (!first || typeof first !== 'object') return { code: '', message: text.slice(0, 300) }
  const raw = String(first.message || first.error_description || first.error || '')
  const line = raw.split('\n').map((s) => s.trim()).filter(Boolean).pop() || ''
  // Drop the boilerplate tail ("…be sure to append the '__c'…", "Please
  // reference your WSDL…"). It is advice for a developer who mistyped a name,
  // not for a user who is missing a permission, and it buries the actual reason.
  const message = line.split(/ (?:If you are attempting|Please reference)/)[0].trim()
  return { code: String(first.errorCode || first.error || ''), message: message || line }
}

// Turn an HTTP status + Salesforce error code into one of LIVE's states.
// `object` is the sObject the refused query named, so the message can say which
// one was refused rather than "a query failed".
function classifyQueryError(status, code, message, object) {
  const at = `${code || `HTTP ${status}`} on ${object}`

  if (code === 'API_DISABLED_FOR_ORG' || code === 'API_CURRENTLY_DISABLED') {
    return new LiveError(LIVE.NO_ACCESS,
      'Your Salesforce user is not allowed to call the API, so the dashboard cannot read anything from the org.',
      'That is the "API Enabled" permission on your profile — a Salesforce admin has to turn it on. '
      + `It is separate from ${ACCESS_PERM_SET}, and you will need both.`, at)
  }
  if (code === 'INVALID_TYPE') {
    return new LiveError(LIVE.NO_ACCESS,
      `${object} is not visible to your Salesforce user.`,
      // Honest about the ambiguity: Salesforce returns the identical error for
      // "you may not see this object" and "this object does not exist here", so
      // this same failure is what a correctly-permissioned user would see
      // against an org where OrgIQ was never deployed.
      `${GRANT_FIX} Salesforce reports "not visible to you" and "not present in this org" `
      + 'with the same error, so if the objects were never deployed to this org the '
      + 'permission set will not help either.', at)
  }
  if (code === 'INVALID_FIELD') {
    return new LiveError(LIVE.NO_ACCESS,
      `You can see ${object}, but not all of the fields the dashboard reads (${message || 'field-level security'}).`,
      `${GRANT_FIX} It grants field-level access as well as object access.`, at)
  }
  if (code === 'INSUFFICIENT_ACCESS' || code === 'INSUFFICIENT_ACCESS_OR_READONLY' || status === 403) {
    return new LiveError(LIVE.NO_ACCESS,
      `Salesforce refused your user read access to ${object}.`, GRANT_FIX, at)
  }
  return new LiveError(LIVE.ERROR,
    `Salesforce refused the query for ${object}: ${message || `HTTP ${status}`}.`,
    'This is not a permission error the dashboard recognises — the raw code is in the browser console.', at)
}

async function soql(tok, q, object) {
  let url = `${tok.instanceUrl}/services/data/${sfConfig.apiVersion}/query?q=${encodeURIComponent(q)}`
  const rows = []
  while (url) {
    let res
    try {
      res = await fetch(url, { headers: { Authorization: `Bearer ${tok.accessToken}` } })
    } catch (e) {
      // A rejected fetch is a network or CORS failure — the org never answered,
      // so we know nothing about this user's permissions and must not guess.
      throw new LiveError(LIVE.UNREACHABLE,
        `The OrgIQ org did not answer the query for ${object}.`,
        `Check that you are online and that this origin (${window.location.origin}) is on the `
        + "org's CORS allowlist (Setup → CORS).", (e && e.message) || String(e))
    }
    if (res.status === 401) {
      throw new LiveError(LIVE.EXPIRED,
        'The org rejected the access token this tab was holding, so it has been discarded.',
        'Click Connect Salesforce to sign in again. Nothing is wrong with your permissions — '
        + 'Salesforce sessions simply time out.', `HTTP 401 on ${object}`)
    }
    if (!res.ok) {
      const { code, message } = await readSfError(res)
      throw classifyQueryError(res.status, code, message, object)
    }
    const page = await res.json()
    rows.push(...page.records)
    url = page.done ? null : tok.instanceUrl + page.nextRecordsUrl
  }
  return rows
}

// ---- best-effort side signals -------------------------------------------
//
// Both of these answer questions the main queries cannot, and both are allowed
// to fail: when they do we say we could not check, we never fall back to the
// friendlier explanation.

// Who is signed in. Needs the `openid` scope and no object permissions at all,
// which is the point — it still answers when the data queries are refused, so a
// user who cannot see anything can at least be told which Salesforce user they
// are and hand that username to the org owner.
async function fetchIdentity(tok) {
  try {
    const res = await fetch(`${tok.instanceUrl}/services/oauth2/userinfo`, {
      headers: { Authorization: `Bearer ${tok.accessToken}` },
    })
    if (!res.ok) return null
    const u = await res.json()
    return {
      username: u.preferred_username || u.username || null,
      name: u.name || null,
    }
  } catch {
    return null
  }
}

// Does the org hold scans that this user simply cannot see? /limits/recordCount
// is an org-wide count that ignores record sharing, so it separates "nothing has
// been loaded here" from "records exist but none are shared with you" — the two
// readings of an empty result, which are indistinguishable from the query alone.
// Returns null when the org will not tell us, and null means unknown, not zero.
async function orgRecordCount(tok, object) {
  try {
    const res = await fetch(
      `${tok.instanceUrl}/services/data/${sfConfig.apiVersion}/limits/recordCount`
      + `?sObjects=${encodeURIComponent(object)}`,
      { headers: { Authorization: `Bearer ${tok.accessToken}` } })
    if (!res.ok) return null
    const body = await res.json()
    const row = (body.sObjects || []).find((s) => s.name === object)
    return row && typeof row.count === 'number' ? row.count : null
  } catch {
    return null
  }
}

const dimCode = (n) => n.split(' ', 1)[0]
const dimShort = (n) => (n.includes(' ') ? n.slice(n.indexOf(' ') + 1) : n)

// A child row is attributed to its scan through Scan__r. That comes back null
// when the parent scan is not visible to this user, and a null parent is not an
// error we can render — the row belongs to a scan that is not on screen. Count
// them so the drop is at least visible in the console rather than silent.
function attributeByScan(rows, label, shape) {
  const by = {}
  let orphans = 0
  for (const r of rows) {
    const sid = r.Scan__r && r.Scan__r.External_Scan_Id__c
    if (!sid) { orphans += 1; continue }
    (by[sid] ||= []).push(shape(r))
  }
  if (orphans) {
    console.warn(`OrgIQ: skipped ${orphans} ${label} row(s) whose parent scan was not visible.`)
  }
  return by
}

// Query the org and return the same shape as the bundled portfolio.json.
async function queryPortfolio(tok) {
  const scans = await soql(tok,
    'SELECT Name,External_Scan_Id__c,Target_Org__c,Scan_Mode__c,Rubric_Version__c,' +
    'Composite_Score__c,Readiness_Band__c,Components_Scanned__c,Gate_Applied__c,' +
    'Gate_Reason__c,Scan_Timestamp__c FROM OrgIQ_Scan__c ORDER BY Composite_Score__c ASC',
    'OrgIQ_Scan__c')
  // Nothing to hang findings off, and two more queries would only be able to
  // confirm it. The caller works out *why* it is empty.
  if (!scans.length) return { source: 'live', scans: [] }

  const dims = await soql(tok,
    'SELECT Scan__r.External_Scan_Id__c,Dimension__c,Score__c,Rule_Coverage__c,' +
    'In_Composite__c,Assessment_Status__c,Missing_Signals__c FROM OrgIQ_Dimension_Score__c',
    'OrgIQ_Dimension_Score__c')
  const finds = await soql(tok,
    'SELECT Scan__r.External_Scan_Id__c,External_Finding_Id__c,Rule_Id__c,Dimension__c,' +
    'Severity__c,Confidence__c,Component_Type__c,Component_Api_Name__c,Evidence__c,' +
    'Remediation__c,Effort_Points__c,Blast_Radius__c,Emits_To_Backlog__c,Rule_Maturity__c,' +
    'Status__c,Survived_Scans__c,Resolved_In_Scan__c FROM OrgIQ_Finding__c',
    'OrgIQ_Finding__c')
  // Live mode has to return the same shape demo mode does, or the dashboard
  // renders less against a real org than it does against the bundled file —
  // which is the worst possible direction for that difference to run.
  const people = await soql(tok,
    'SELECT Scan__r.External_Scan_Id__c,Name,Persona_Kind__c,Summary__c,Unbounded__c,' +
    'Blanket_Perms__c,Reach__c,Objects_Editable__c,Objects_Readable__c,Objects_Deletable__c,' +
    'Fields_Visible__c,Fields_Available__c,Flows__c,Approvals__c,Blocked_By__c,Actions__c,' +
    'Editable_Objects__c,Flow_Names__c,Blocking_Rules__c FROM OrgIQ_Persona__c ' +
    'ORDER BY Unbounded__c DESC,Reach__c DESC',
    'OrgIQ_Persona__c')

  const dByScan = attributeByScan(dims, 'dimension score', (d) => ({
    code: dimCode(d.Dimension__c), name: dimShort(d.Dimension__c), fullName: d.Dimension__c,
    score: d.Score__c, coverage: d.Rule_Coverage__c, inComposite: d.In_Composite__c,
    status: d.Assessment_Status__c, missingSignals: d.Missing_Signals__c || '',
  }))
  const fByScan = attributeByScan(finds, 'finding', (f) => ({
    externalId: f.External_Finding_Id__c, ruleId: f.Rule_Id__c, dimension: f.Dimension__c,
    severity: f.Severity__c, confidence: f.Confidence__c, componentType: f.Component_Type__c,
    component: f.Component_Api_Name__c, evidence: f.Evidence__c || '',
    remediation: f.Remediation__c || '', effortPoints: f.Effort_Points__c,
    blastRadius: f.Blast_Radius__c, emitsToBacklog: f.Emits_To_Backlog__c,
    ruleMaturity: f.Rule_Maturity__c, status: f.Status__c,
    // null, not 0, where no scan history could establish a run.
    survivedScans: f.Survived_Scans__c, resolvedInScan: f.Resolved_In_Scan__c || '',
  }))
  const splitList = (t) => (t || '').split(' | ').filter(Boolean)
  const pByScan = attributeByScan(people, 'persona', (p) => ({
    name: p.Name, kind: p.Persona_Kind__c, summary: p.Summary__c || '',
    unbounded: p.Unbounded__c, blanketPerms: p.Blanket_Perms__c || '', reach: p.Reach__c,
    objectsEditable: p.Objects_Editable__c, objectsReadable: p.Objects_Readable__c,
    objectsDeletable: p.Objects_Deletable__c,
    // Genuinely null for a permission set — it assigns no layouts.
    fieldsVisible: p.Fields_Visible__c, fieldsAvailable: p.Fields_Available__c,
    flows: p.Flows__c, approvals: p.Approvals__c, blockedBy: p.Blocked_By__c,
    actions: p.Actions__c, editableObjects: splitList(p.Editable_Objects__c),
    flowNames: splitList(p.Flow_Names__c), blockingRules: splitList(p.Blocking_Rules__c),
  }))

  return {
    source: 'live',
    scans: scans.map((s) => {
      const sid = s.External_Scan_Id__c
      return {
        scan: {
          name: s.Name, externalId: sid, targetOrg: s.Target_Org__c, scanMode: s.Scan_Mode__c,
          rubricVersion: s.Rubric_Version__c, compositeScore: s.Composite_Score__c,
          readinessBand: s.Readiness_Band__c, componentsScanned: s.Components_Scanned__c,
          gateApplied: s.Gate_Applied__c, gateReason: s.Gate_Reason__c || '', timestamp: s.Scan_Timestamp__c,
        },
        dimensions: (dByScan[sid] || []).sort((a, b) => a.code.localeCompare(b.code)),
        findings: fByScan[sid] || [],
        personas: pByScan[sid] || [],
      }
    }),
  }
}

// An empty result is two different problems wearing the same face. Separate them
// with the org-wide record count, and when that is unavailable say the question
// is open instead of picking an answer.
async function explainEmpty(tok, identity) {
  const total = await orgRecordCount(tok, 'OrgIQ_Scan__c')
  if (total === null) {
    return {
      status: LIVE.EMPTY, data: null, identity,
      reason: 'Your user can read the OrgIQ objects, but no scans came back.',
      fix: 'Either this org has no scans loaded, or scans exist and none of them are shared with '
        + `your user — the org would not tell us which. ${ACCESS_PERM_SET} grants View All on `
        + 'these objects, which rules out the second; if you already have it, the org is empty.',
      detail: 'record count unavailable',
    }
  }
  if (total > 0) {
    // Object access is fine (the query ran) but no records reached this user —
    // that is record-level sharing, not object permissions.
    return {
      status: LIVE.NO_ACCESS, data: null, identity,
      reason: `This org holds ${total} scan${total === 1 ? '' : 's'}, but none of them are visible to your Salesforce user.`,
      fix: 'Your user can read the objects but not these records, so this is record-level '
        + `sharing rather than object permissions. ${GRANT_FIX} It grants View All on these `
        + 'objects, which covers exactly this case.',
      detail: `recordCount=${total}, query returned 0`,
    }
  }
  return {
    status: LIVE.EMPTY, data: null, identity,
    reason: 'Your permissions are fine — this OrgIQ org simply has no scans loaded.',
    fix: 'Load one with salesforce/load_portfolio.py (or salesforce/load_scan.py for a single scan). '
      + 'This is not a permissions problem.',
    detail: 'recordCount=0',
  }
}

// The one entry point the dashboard calls after it has a token.
//
// Always resolves — never throws — to { status, data, identity, reason, fix,
// detail }. `data` is set only when status is LIVE.OK; every other status
// carries a reason the caller is expected to put on screen, because the whole
// point is that no outcome silently becomes "showing demo data".
export async function loadLive(tok) {
  // First, because it is the one thing that still works when everything else is
  // refused, and naming the user is most of what makes the refusal actionable.
  const identity = await fetchIdentity(tok)
  try {
    const portfolio = await queryPortfolio(tok)
    if (!portfolio.scans.length) return explainEmpty(tok, identity)
    return { status: LIVE.OK, data: portfolio, identity, reason: '', fix: '', detail: '' }
  } catch (e) {
    if (e instanceof LiveError) {
      if (e.detail) console.warn(`OrgIQ live mode: ${e.detail}`)
      return { status: e.status, data: null, identity, reason: e.reason, fix: e.fix, detail: e.detail }
    }
    // Anything else is a bug in this file, not a state of the org. Say so rather
    // than dressing it up as a Salesforce problem.
    console.error('OrgIQ live mode: unexpected failure', e)
    return {
      status: LIVE.ERROR, data: null, identity,
      reason: `The dashboard failed while reading live data: ${(e && e.message) || String(e)}.`,
      fix: 'This is a dashboard bug rather than an org or permission problem — details are in the browser console.',
      detail: '',
    }
  }
}
