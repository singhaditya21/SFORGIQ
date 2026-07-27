# OrgIQ — Project Status

**Agentforce Readiness Analyzer.** A tool that reads a Salesforce org's *source
metadata* and reports whether the org can support agents — terminating in a
prioritised, importable tech backlog rather than a dashboard.

Last updated: 24 July 2026

**Scope, stated up front.** Everything here runs in **source mode**: the scanner
parses files in an SFDX directory. There is no org connection anywhere in
`scanner/`. `--mode Org` and `--mode Hybrid` are labels recorded on the scan
result, nothing more — see [What the scanner actually reads](#what-the-scanner-actually-reads).

**Live dashboard:** https://singhaditya21.github.io/SFORGIQ/ — demo mode, reading a
bundled JSON export of a **synthetic** two-enterprise estate — an insurer and a
bank, 14 orgs between them. The rules that produced it are the real ones; the orgs
they ran against are generated.

---

## What it does, in one line

Point it at an SFDX repository. It tells you what's wrong, with evidence, and gives
you a CSV that imports into Jira.

```
python3 scanner/orgiq_spike.py ./force-app --name "Client X" --backlog backlog.csv
```

There is no packaged `orgiq` command yet — no `setup.py`, no `pyproject.toml`, no
console entry point. Invoke the module directly, as above.

---

## Current state

Every count below is computed by `scripts/repo_facts.py` and asserted by
`tests/test_docs.py`, because this table has now gone stale twice — most
recently claiming 22 rules when there were 31, and claiming the scanner could
not read an org while `scanner/org_mode.py` was issuing real SOQL against one.

| Piece | Status |
|---|---|
| Specification (`PRD.md`) | v0.9 — 13 sections + 3 appendices |
| Scanner (`scanner/`) | **31 rules** across **D1–D5** (7 × D1, 3 × D2, 5 × D3, 10 × D4, 6 × D5), plus cross-org drift, which is reported outside the five dimensions so it never penalises a score |
| Modes | **Source and Org are both real.** Source mode parses an SFDX directory. Org mode (`scanner/org_mode.py`, ~1,200 lines) authenticates through the `sf` CLI and collects field schema, Flows, Apex, triggers, permission sets, reports and **record-level probes** — the last of which is what lets D2 run at all |
| Free-tool ingestion | **Built** (`scanner/external.py`, ~1,100 lines). Code Analyzer (v4/v5/SARIF, and it can invoke the CLI itself), Security Health Check, and an Optimizer export — each finding carries its source, and overlaps with OrgIQ's own rules are deduplicated rather than double-counted |
| Tenant isolation | `OrgIQ_Enterprise__c` is a record with a Private org-wide default; an org is a **master-detail child** of it, and every scan carries the tenant key. An enterprise used to be a prefix in a free-text org name. Within one Salesforce org this is sharing, not a VPC — one install per enterprise remains the answer — but the boundary is now something `tests/test_isolation.py` and `scripts/verify-live-mode.py` check rather than something the architecture asserts |
| Personas | Profiles, layouts, flows, approvals and validation rules are read together into a **capability surface** per identity, stored as `OrgIQ_Persona__c` and shown in the dashboard |
| Tests / CI | **283 pytest tests** over the rule packs, scoring, drift, personas, effort, survival and the rubric, plus an end-to-end fixture smoke test; CI also builds the dashboard. **every one of the 31 rules has a test**, and `tests/test_rubric.py` fails if a rule ever ships without a remediation playbook |
| Data generator (`fixtures/`) | CSV generator, messy-org fixture, and the estate generator behind the demo portfolio |
| Salesforce objects (`salesforce/`) | **6 objects, 78 fields**, all deployed to `orgiq` and confirmed by query, plus the `OrgIQ_Admin` permission set, Connected App, CORS origin and `Security.settings` |
| Salesforce data | **Loaded and confirmed in the org.** The portfolio is synthetic: **2 enterprises, 14 orgs, 20 scans, 1,440 findings, 100 dimension scores, 114 persona surfaces** |
| Backlog CSV output | Threshold-gated Jira CSV — **1,222 tickets** from the current portfolio, epic-clustered, with remediation and acceptance criteria |
| Ownership | Every finding carries an **Owner Role** — Data Steward, Platform Developer, Security & Access, Release Management — derived from the rule and its dimension, and carried into the Jira CSV. Routed by rule rather than by dimension where the two disagree: a safe field rename is a developer's job even though it sits in D1 |
| Cadence | `.github/workflows/scan.yml` scans weekly, loads the result, and **fails when an org regressed** — a composite that fell past tolerance, a new Critical, or a resolved finding that came back. Skips cleanly with no targets configured. This is also the only way the history survival and burn-down depend on ever accumulates |
| Effort model | Responds to measured evidence (dependants, cluster size, org type) and is **explicitly uncalibrated** — `salesforce/calibration_kit.py` is the route real numbers arrive by |
| Dashboard (`dashboard/`) | **Live on GitHub Pages in demo mode.** OAuth live mode: every server-side precondition is verified by `scripts/verify-live-mode.py` (11 checks, all passing). **The browser login itself has not been observed to complete** — that needs a person, and live mode also needs the `OrgIQ_Admin` permission set, without which a successful sign-in still shows nothing |

**Environment done:** Salesforce CLI installed (macOS arm64), Developer Edition org
created, `sf org login web --alias orgiq` complete.

**Keeping it alive.** GitHub Pages is static and effectively always-up; the public
dashboard's demo mode reads a bundled JSON, so it stays live even if the org is
gone. The one perishable piece is the **Agentforce dev org**, which Salesforce
deletes after ~45 days without a login. `.github/workflows/keepalive.yml` performs
that login weekly and writes a heartbeat commit so GitHub never disables the
scheduler — the two run independently, because they defend against two unrelated
clocks and chaining them once let a dead token take the scheduler down too.

One-time setup: `bash scripts/setup-keepalive.sh`, which now proves the refresh
token works *before* storing it. **It is currently not set up**: the stored token
expired, and Salesforce will not issue a refresh token to a script, so this needs
one `sf org login web --alias orgiq` followed by the setup script.

---

## The five dimensions

| | Dimension | Question it answers |
|---|---|---|
| D1 | Grounding Quality | Can a model understand this schema? |
| D2 | Data Foundation | Is the data trustworthy enough to ground on? |
| D3 | Action Surface | Can the agent safely *do* anything? |
| D4 | Permission Blast Radius | What can it reach if something goes wrong? |
| D5 | Automation Collision | Will its writes trigger cascading chaos? |

D1 and D3 are agent-native. D2, D4, D5 are pre-existing org health problems that agents
amplify.

**All five now have rule packs**, and each is assessed only when the input it needs is
actually present (`OrgMetadata.assessable_dims`): D1 from field metadata, D3 from Flows
and Apex, D4 from permission sets, D5 from triggers and record-triggered Flows. **D2
needs record-level data**, so a source-mode scan of a bare SFDX directory reports it as
*Not Assessed* rather than guessing — which also means D2's three rules have only ever
executed against inputs the portfolio generator invented. The demo portfolio supplies
synthetic inputs for all five: the rules are real, the fictional orgs' inputs are
generated.

---

## What the scanner actually reads

**In source mode** `scanner/` walks the directory you point it at with `Path.rglob`
and parses exactly these patterns — nothing else in the tree is opened. Org mode
collects the same shapes from a live org over the API instead, so the table below
is what the *rules* consume either way:

| Glob | Parsed by | Feeds |
|---|---|---|
| `*.field-meta.xml` | `orgiq_spike.parse_project` | D1 (all six rules), semantic density, grounding-payload estimate |
| `*.flow-meta.xml` | `metadata.parse_flows` | D3 (autolaunched flows as candidate actions), D5 (record-triggered flows); re-read as raw text for `D1.UNREFERENCED_FIELD` |
| `*.cls` | `metadata.parse_apex` | D3 (`@InvocableMethod` count and labels, test classes); body text for `D1.UNREFERENCED_FIELD` |
| `*.trigger` | `metadata.parse_triggers` | D5 (triggers per object, loop and recursion-guard heuristics); body text for `D1.UNREFERENCED_FIELD` |
| `*.permissionset-meta.xml` | `metadata.parse_permission_sets` | D4 (`ModifyAllData`, `ViewAllData`, per-object grants) |
| `*.profile-meta.xml` | `metadata.parse_profiles` | persona surfaces (object rights, layout assignments, flow access) |
| `*.layout-meta.xml` | `metadata.parse_layouts` | persona surfaces (which fields are actually put in front of a persona, and which buttons) |
| `*.validationRule-meta.xml` | `metadata.parse_validation_rules` | persona surfaces (what will refuse a persona's save) |
| `*.approvalProcess-meta.xml` | `metadata.parse_approval_processes` | persona surfaces (the processes a persona takes part in) |
| `*.report-meta.xml`, `*.dashboard-meta.xml` | `metadata.parse_reports` | blast-radius weighting of D1 findings; gates `D1.UNREFERENCED_FIELD` |

D2 has no glob. There is no file in an SFDX repository that carries fill rates,
record staleness or duplicate counts.

The five persona-facing globs are read together rather than separately, because no
one of them answers the question. A **capability surface** is what a profile grants,
narrowed by the layouts it is actually assigned, plus the flows it can start, the
approvals it takes part in and the validation rules that will refuse its saves. An
agent runs as a persona and can therefore do exactly what that persona can do, so the
surface *is* the answer to "what can this agent reach?" — and `OrgIQ_Persona__c`
records every one of them, not only the ones a rule objected to. Two limits are
stated on the record rather than hidden: effective access is profile plus permission
sets plus permission set groups minus muting, and metadata alone does not say which
users hold which, so a surface is the access a persona **grants**, not what a named
person ended up with; and sharing rules decide record-level visibility on a different
axis that nothing here models.

Everything else in an org is invisible from here: formula and roll-up references,
sharing rules, custom metadata types, LWC and Aura, managed packages, external
integrations, Setup Audit Trail, `MetadataComponentDependency`, and all record data. That list is the reason several
rules cap their own confidence, and the reason `D1.UNREFERENCED_FIELD` returns nothing
at all unless report or dashboard metadata was found — with no evidence of consumption,
an unused field and an unobserved field look identical.

**Both modes are real, and they differ in what they can see.** Source mode parses
a directory: no authentication, no org traffic, and D2 cannot run because no
repository carries record counts. Org mode (`--mode Org`) authenticates through
the `sf` CLI and collects the same metadata from a live org *plus* record-level
probes — fill rates, staleness, and a duplicate probe where something groupable
exists — which is what lets D2 report anything at all. Where a probe cannot run,
the collector records why, and the dimension is reported as partially assessed
rather than silently scored on what did run.

Reading a *target* org is read-only by design. The only writes anywhere are to
the separate OrgIQ findings org, which is where results are stored
(`salesforce/load_*.py`, `dashboard/export_*.py`).

---

## How this compares to the free Salesforce tools

PRD §2.4 commits to carrying a factual capability comparison and not carrying
competitive criticism. This is it. Two things to read before the table:

- **OrgIQ ingests none of these tools today.** PRD EXT-6 (Optimizer / Health Check
  ingestion) and EXT-7 (Code Analyzer invocation) are roadmap items at v0.3 and v0.4.
  Nothing in `scanner/` reads their output. Every finding carries `Source = OrgIQ`
  because that is currently the only value the emitter can produce; the column exists
  so ingested findings can share the record set later without a schema change.
- **This table is read off each tool's documentation, not off a bake-off.** None of
  them has been run against the same org as OrgIQ and compared. Where a free tool
  overlaps OrgIQ, assume the free tool is the more trustworthy of the two until
  measured otherwise: they run against a live org with a real parser, OrgIQ runs
  against committed text files with regular expressions.

| | Salesforce Optimizer | Security Health Check | Salesforce Code Analyzer | OrgIQ (today) |
|---|---|---|---|---|
| **What it covers** | Org-health inventory computed from live org data: unused and under-used custom fields, unused reports and dashboards, limits and storage headroom, duplicate/obsolete configuration, profile and permission-set sprawl, Lightning readiness | Org-wide security *settings* scored against Salesforce's Baseline Standard (or an uploaded custom baseline): password and session policies, network access, certificate and key management, file upload/download policy, login access policy. Per-setting risk levels with in-place fixes | Static analysis of source: PMD (Apex/Visualforce, including performance rules that catch SOQL and DML inside loops), ESLint (LWC/Aura/JS), RetireJS (vulnerable JS libraries), Salesforce Graph Engine (path-based data-flow, e.g. CRUD/FLS violations) | Agent-readiness lens across five dimensions. D1 grounding quality (descriptions, cryptic names, semantic duplicates, numbered families, unreferenced fields), plus semantic-density and grounding-payload estimates, D3 action surface, D4 permission blast radius, D5 automation collision |
| **Licensing / cost** | Free, included in the platform | Free, included in the platform | Free and open source | Apache 2.0, personal copyright (PRD §9) |
| **Install requirement** | None — native Setup app, run by an admin inside the org | None — native Setup page | `sf` CLI plugin install; a JDK for the PMD and Graph Engine engines | None. Python 3.9, standard library only, no third-party dependencies and no model SDK |
| **Needs an org connection** | Yes — it *is* the org | Yes | No for source scanning | No. Files only |
| **Output** | Findings in the Optimizer app in Setup | A score and a settings list in Setup | Machine-readable results (JSON/CSV/SARIF/HTML) for CI | Markdown report, a scan-result JSON matching the Salesforce schema, and a threshold-gated Jira/ADO CSV with stable external IDs, epics, remediation, acceptance criteria and provisional effort points |
| **What OrgIQ adds over it** | Grounding *quality*, not just usage: whether a field's description, name and neighbours let a retriever pick it correctly. And it runs on a repo with no org at all, so it works before an engagement has org access | Nothing on security posture. The adjacent question only: what an *agent's* permission set can reach if a plan goes wrong. These are complementary, not competing | The agent lens over the same source tree — action discoverability and describability, grounding quality, and the automation-collision framing — plus the backlog conversion. Code Analyzer is the better tool for the code correctness questions they both touch | — |

### Where OrgIQ overlaps, and where it should defer

Stated plainly, because the overlaps are the places OrgIQ is weakest.

**D5.DML_IN_LOOP / D5.SOQL_IN_LOOP / D5.NO_RECURSION_GUARD are approximate
source-mode heuristics.** `metadata.py` brace-matches `for` and `while` blocks and
regex-searches inside them. It does not parse Apex. It will miss DML in a helper
method called from a loop, and it will flag DML sitting in a commented-out block. The
recursion-guard check looks for a `static Boolean` / `static Set<Id>` or a name like
`hasRun` — a real guard written any other way reads as absent. Code Analyzer does this
properly, with a parser and a data-flow graph. These rules exist because source mode
has to produce *something* for D5 without a Java toolchain; the PRD's stated posture
(§2.3, §7.3) is that OrgIQ **defers to Code Analyzer and ingests its findings rather
than reimplementing them** once org mode arrives. Read the D5 loop findings as
"worth a look", not as a verdict.

**Optimizer answers `D1.UNREFERENCED_FIELD` better than OrgIQ does today.** It has the
whole org: every report, every layout, every dependency. OrgIQ sees only the
`*.report-meta.xml` and `*.dashboard-meta.xml` files that happen to be committed to the
repository, plus textual matches of the field's API name in Apex, trigger and Flow
source. This is why the rule never emits above Medium confidence, drops to Low when
there is no Apex or Flow source to search, and returns nothing at all when no report
metadata is present.

**D4 is not a security scan and does not try to be.** It reads committed permission
sets and flags broad grants through an agent-blast-radius lens. It says nothing about
password policy, session settings, sharing model or certificate hygiene. Health Check
covers that ground; PRD §2.3 lists "a security scanner" as an explicit non-goal.

**Source mode reports intended state, not actual state.** Permission changes made
directly in production do not appear in the repository, so D4 findings describe what
the repo says the org should be (PRD §7.2). Optimizer and Health Check report what it
actually is.

---

## Traps that will bite a fresh clone

**Deploying `salesforce/force-app` to a *fresh* org silently breaks live mode.**
`OrgIQ_Dashboard.connectedApp-meta.xml` carries no `<consumerKey>`. That is correct —
the key is minted per org and cannot be checked in — but it means a deploy into a new
org creates a connected app with a *new* consumer key, while
`dashboard/src/lib/sfConfig.js` still holds the old one hardcoded. Nothing fails at
deploy time. The dashboard's OAuth redirect just comes back rejected. After deploying
to a new org:

1. Setup → App Manager → **OrgIQ Dashboard** → View → copy the Consumer Key.
2. Put it in `sfConfig.clientId`, and set `sfConfig.loginUrl` to the new org's My
   Domain URL.
3. If the dashboard is not served from `https://singhaditya21.github.io/SFORGIQ/`,
   update `<callbackUrl>` in the connected app and `<urlPattern>` in
   `OrgIQ_Pages.corsWhitelistOrigin-meta.xml` to match the new origin.

**Live mode needs two separate CORS switches, not one.** `CorsWhitelistOrigin` allows
the origin to call the REST API. It does **not** cover the OAuth endpoints —
`/services/oauth2/token` is gated separately by `enableOauthCorsPolicy` under
`SecuritySettings`, which is the only reason
`salesforce/force-app/main/default/settings/Security.settings-meta.xml` exists (Setup →
CORS → *Allow OAuth endpoints*). With that switch off, the browser-side PKCE token
exchange is refused and "Connect Salesforce" cannot complete. **This is why live mode
has never been seen to work end to end**: the org had it disabled, and the setting was
only committed afterwards and has not been deployed and retested. The authorization
code is single-use and is spent by the failed attempt, so reloading does not recover
it — fix the setting, then sign in again.

**The dev org expires.** Salesforce deletes a Developer Edition org after ~45 days
without a login; `.github/workflows/keepalive.yml` is what stops that. If the
`SFDX_AUTH_URL` secret is missing or stale the run fails — loudly in the Actions tab,
silently to anyone not watching it — and the org goes, taking live mode and both export
scripts with it. Demo mode survives, because it reads a committed JSON file.

---

## Giving someone else access to live mode

**Live mode is for people who have a login in the OrgIQ org. Everyone else sees demo
data, and that is by design** — the public dashboard reads a bundled JSON that needs no
auth, so the link works for anyone who opens it. "Connect Salesforce" is a door into one
Developer Edition org that holds the real scan records, and a door needs a key.

**Signing in is not the key on its own.** The three OrgIQ objects are reachable only
through the **`OrgIQ_Admin`** permission set. Without it a colleague completes the OAuth
flow, gets a valid token, runs a query Salesforce refuses, and lands back on demo data —
which is why "connect to Salesforce doesn't work" outlived the CORS fix above. It was a
second, unrelated wall wearing the same face. The dashboard now names which wall it hit;
this section is how to remove it.

**1. Create the user.** Setup → Users → Users → New User, on a licence with API access
(Salesforce, or Salesforce Platform). Salesforce usernames are globally unique across
*every* org and look like an email without being one — if `name@company.com` is taken,
use something like `name@company.com.orgiq`. Salesforce emails them an activation link
and they set their own password; nobody else handles it.

**2. Grant access.** One command, run by whoever owns the org:

```
bash scripts/grant-orgiq-access.sh name@company.com.orgiq        # org alias "orgiq"
bash scripts/grant-orgiq-access.sh name@company.com.orgiq myalias
```

It assigns `OrgIQ_Admin`, then verifies the assignment by querying it back — an
assignment that did not land is never reported as access granted. It **does not create
users**, on purpose: that needs a real name, email, profile and licence, which is the
owner's call and not a script's, so an unknown username stops it with instructions
rather than a guess.

**3. They connect.** Open the dashboard, hard-refresh (Cmd/Ctrl + Shift + R), click
**Connect Salesforce**, sign in. If they had already connected and were staring at demo
data, **Re-check live access** in the header picks the new grant up without a second trip
through OAuth.

### When it still shows demo data

Falling back to demo data is deliberate — the public site must never break — but it is
never silent. The banner names which case it is, and they need different fixes:

| The banner says | What actually happened | What fixes it |
|---|---|---|
| `OrgIQ_Scan__c is not visible to your Salesforce user` | Authenticated; the org refuses this user the objects | Step 2. (Salesforce reports "not visible to you" and "not deployed here" identically, so this is also what a *fresh* org with no OrgIQ metadata looks like) |
| `This org holds N scans, but none of them are visible` | Object access is fine, record-level sharing is not | Step 2 — `OrgIQ_Admin` grants View All on the objects |
| `this OrgIQ org simply has no scans loaded` | Permissions are fine; the org is empty | `python3 salesforce/load_portfolio.py` — not a permissions problem |
| `no scans came back` … `the org would not tell us which` | Empty result, and the org would not say whether records exist | Try step 2 first; if the user already holds `OrgIQ_Admin`, the org is genuinely empty |
| `Could not reach the OrgIQ org` | No answer at all — offline, or the origin is not on the CORS allowlist | [Traps](#traps-that-will-bite-a-fresh-clone) |
| `The org rejected the access token` | The Salesforce session timed out | Connect again; nothing to do with permissions |

The banner also prints the signed-in username — which is exactly the value step 2 needs,
and worth checking when someone has more than one Salesforce login and used the wrong
one. Between the header pill (`Demo · N orgs` / `● Live · N orgs`) and the footer, it is
always stated on screen which of the two you are looking at.

---

## Decisions made, and why

Recorded so they don't get re-litigated.

**Scratch orgs, not persistent Developer Edition, for the fixture.** DE gives 5 MB storage
(~2,500 records) and 5,000 API calls per day — the second limit bites hardest during rule
iteration. Scratch orgs are declarative and disposable.

**Source mode is a first-class input path, not a degraded one.** The scanner reads SFDX
directories with no org connection, no credentials, no API consumption. This is what makes
public-corpus validation practical and CI adoption possible. It is also, so far, the
*only* input path that exists — see [What the scanner actually reads](#what-the-scanner-actually-reads).

**Partial coverage excludes a dimension from the composite.** A dimension scored from 40% of
its rules isn't a lower score, it's an unreliable one. Coverage below 70% → marked
`partially assessed`, excluded from the composite, stated in the report.

**Rule confidence is capped by validation evidence.** Rules ship `experimental`, reach
`validated` on the public corpus, and `field-proven` only on adjudicated real-world
precision. **This ladder is a policy, not yet a mechanism.** `Rule Maturity` is a
hardcoded literal `"experimental"` in both `backlog.py` and `scan_result.py`, and
maturity gates nothing: the only thing deciding whether a finding becomes a ticket is
`severity >= Medium AND confidence >= Medium`. Experimental rules do auto-emit today.

**Read-only against target orgs, always.** Findings are written to a *separate* OrgIQ org.
The target org is never written to — trivially true so far, since nothing in the scanner
connects to a target org at all.

**Dashboard architecture:** GitHub Pages static site → OAuth PKCE → OrgIQ org REST API.
No server. Needs a Connected App, a CORS allowlist entry *and* the separate OAuth-endpoint
CORS setting ([Traps](#traps-that-will-bite-a-fresh-clone)). Must have a demo mode reading
a bundled sample JSON, otherwise anyone opening the public link sees a login screen — and,
as it turns out, otherwise the public link would show nothing at all, since the live path
has never completed.

**Apache 2.0, personal copyright.** The only structure where the open-source project, the
employer's use of it, and personal retention of the asset all work.

---

## Corrections made along the way

The expensive ones, kept so they aren't repeated.

**§5 was built on a wrong model of how Agentforce grounds.** The original version assumed
full-schema injection — every field into context, cost scaling with field count. Agentforce
grounds through *retrieval*. Corrected to a two-surface model: on the grounding surface the
cost of bloat is **accuracy**, not tokens; on the action surface it's both. Cost survives
via turns-to-resolution (ambiguity → wrong selection → re-plan → extra round trips), not
payload size.

**The spike found three bugs in its own rules.** Words like *number*, *total*, *date*,
*amount* were being stripped as encoding markers, which made `Date_Field__c` and
`Amount_Field__c` a **High-confidence** false positive. Numbered families
(`Contact1Imported__c` / `Contact2Imported__c`) were being read as semantic duplicates —
that became its own rule, `D1.NUMBERED_FAMILY`, which the spec didn't have.
Semantic duplicate findings went **59 → 38 → 4** across those fixes. The naive version was
~93% false positives.

**Public corpus validates correctness, not prevalence.** NPSP came in at 77.6% description
coverage and 0.5% semantic duplication — *good* metadata. The two sample apps were at 0%
coverage. Curated packages are maintained under review; demo apps aren't maintained at all.
Neither resembles a fifteen-year-old enterprise org.

---

## Open questions

1. **Prevalence is unmeasured, and the thesis depends on it.** The premise is that orgs are
   full of ambiguous undocumented fields. One data point (NPSP) points the other way. The
   public corpus will understate it; the fixture can't test it without circularity.
   Until measured: report findings as *observed in this org*, never as *typical*.
2. **Effort estimation is hand-waved** and it carries the whole value claim — a backlog beats
   a dashboard only because work can be costed. Needs real engagement data.
3. **Nobody has been asked.** No Salesforce architect has seen any of this. Three
   conversations would validate or kill more assumptions than three more sections.
4. **The free tools have never been run alongside it.** The comparison above is read off
   documentation. Until Optimizer, Health Check and Code Analyzer have been run against
   the same org as OrgIQ and the findings reconciled, the overlap is estimated, the
   claimed additions are unproven, and the ingestion design in PRD §7.3 rests on
   assumptions about output formats nobody has parsed.
5. Naming — `OrgIQ` is provisional.

---

## Immediate next steps

1. ~~**Deploy the objects**~~ — **done.** Deployed to `orgiq` via `sf project deploy start --source-dir salesforce/force-app --target-org orgiq` (needs `sfdx-project.json`, now at repo root). Access is granted by the `OrgIQ_Admin` permission set.
2. ~~**Backlog CSV emitter**~~ — **done.** `scanner/backlog.py`; run with `--backlog out.csv` (see below).
3. ~~**Shareable report**~~ — **done, as a React dashboard** (superseded the flat HTML report). Lives in `dashboard/`, deployed to GitHub Pages.
4. ~~**Dashboard demo mode**~~ — **done.** `dashboard/public/portfolio.json` is exported from the org by `dashboard/export_portfolio.py`; the public site reads it, no auth. This is the only path the live dashboard has ever exercised.
5. **OAuth live mode** — **code complete, never verified end to end.** A PKCE public-client Connected App, a CORS origin and the `enableOauthCorsPolicy` security setting are in `salesforce/force-app`. The dashboard's "Connect Salesforce" button runs the browser PKCE flow and, on success, queries `OrgIQ_Scan__c` / `OrgIQ_Dimension_Score__c` / `OrgIQ_Finding__c` over the REST API and renders the org's own data in place of the bundled JSON. That path has not been observed to succeed: the org had OAuth-endpoint CORS disabled, so the token exchange was refused in the browser, and the setting that fixes it was committed afterwards and has not been deployed and retested. Treat this as *intended behaviour with a setup requirement*, not as a working feature. Sign-in only works from the registered callback origin. Sign-in is also not sufficient: the OrgIQ objects are gated by the `OrgIQ_Admin` permission set, which was assigned to exactly one user, so a second person could authenticate successfully and still see nothing. That is now a stated reason on screen rather than a silent fall back to demo data, and `scripts/grant-orgiq-access.sh` grants the permission set — see [Giving someone else access to live mode](#giving-someone-else-access-to-live-mode).

The source-mode slice is live: portfolio → Salesforce → backlog CSV + dashboard in demo mode, across all five dimensions on synthetic inputs. Remaining: **an actual org connection** (nothing in `scanner/` has one), real non-synthetic D2–D5 assessment, a verified live-mode round trip, effort calibration, and the public-corpus validation from the PRD roadmap.

---

## Folder contents

```
SFORGIQ/
  README.md              this file
  PRD.md                 full specification, v0.7
  sfdx-project.json      SFDX config so the objects can be deployed
  scanner/               CLI entry point + every rule, stdlib only
    orgiq_spike.py       CLI, field parsing, the 6 D1 rules, report weighting
    rules_ext.py         the D2-D5 rule packs
    metadata.py          SFDX parsers: Flows, Apex, triggers, permission sets,
                         profiles, layouts, validation rules, approval processes,
                         reports/dashboards; the Apex body heuristics
    persona.py           capability surfaces (what an identity can actually do)
                         and blast radius (what depends on a component)
    drift.py             cross-org drift: where an estate disagrees with itself
    lifecycle.py         survival — how many consecutive scans a finding lived through
    effort.py            evidence-responsive effort estimates + the calibration loop
    rubric.py            loads rubric.json; the judgement half, kept out of the engine
    rubric.json          bands, penalties, the emission gate, the effort model and
                         the 35-entry remediation playbook — data, not code, so a
                         practitioner can tune it and a port carries the engine only
    density.py           semantic density + grounding-payload ESTIMATES (no tokenizer)
    backlog.py           Jira-importable backlog CSV emitter (threshold-gated)
    scan_result.py       assembles the full scan record set (Salesforce schema)
    enterprises.py       the two demo estates: schemas, orgs, personas, rules
    scan_portfolio.py    generates the demo portfolio in memory
  fixtures/
    seed_data.py         fixture data generator (D2 record data)
    gen_messy_org.py     generates the messy-org metadata fixture
    messy_org/           the generated defect-catalogue fixture (3 objects, 42
                         fields, 7 reports, 2 dashboards)
  salesforce/
    force-app/           3 custom objects (38 fields in source, 32 deployed),
                         OrgIQ_Admin permission set, Connected App, CORS origin,
                         Security settings (OAuth-endpoint CORS)
    load_scan.py         idempotent Bulk-API loader (scan result JSON -> org),
                         incl. the finding lifecycle and the survival recompute
    load_portfolio.py    the same, for a whole portfolio
    calibration_kit.py   worksheet / import / report — the routes real effort
                         numbers arrive by (actual, expert, survival)
  dashboard/             React portfolio dashboard; deployed to GitHub Pages
    src/views/           PortfolioView (overview) + OrgDetail (drill-down)
    src/lib/sfConfig.js  hardcoded OAuth client id — see Traps before redeploying
    src/lib/live.js      OAuth PKCE + the live REST read, and the classification
                         of every way it can fail (see Giving someone else access)
    export_portfolio.py  exports every scan from the org into public/portfolio.json
    export_demo_data.py  exports a single scan (legacy, single-scan view)
  scripts/
    setup-keepalive.sh   one-time: store SFDX_AUTH_URL so keepalive can log in
    grant-orgiq-access.sh  assign OrgIQ_Admin to a colleague, so live mode works
                         for someone other than the org owner
  .github/workflows/     CI (tests + fixture smoke + dashboard build),
                         GitHub Pages deploy, org keepalive
```

**End-to-end run** (portfolio → Salesforce → dashboard data):

```
# generate the demo estate and bulk-load it into the org
python3 scanner/scan_portfolio.py --out portfolio.json
python3 salesforce/load_portfolio.py portfolio.json --target-org orgiq
# export it back out for the dashboard's demo mode
python3 dashboard/export_portfolio.py --target-org orgiq --out dashboard/public/portfolio.json
```

Single-org flow (fixture → scan → org) is still available via
`fixtures/gen_messy_org.py`, `orgiq_spike.py --scan-json`, and `salesforce/load_scan.py`.

**Running the tests:**

```
python3 -m pytest tests/ -q
```

Covers all five rule packs (including regression tests for the false positives the
spike shipped and fixed), the §4.6 backlog gate, external-id idempotency, the
readiness bands, and the gate caps. CI runs these plus a full fixture scan and a
dashboard build on every push.

Not yet covered, as of this writing: `D1.UNREFERENCED_FIELD`, `D4.VIEW_ALL_DATA`,
the report/dashboard parser and blast-radius weighting in `scanner/metadata.py`, and
everything in `scanner/density.py`. The fixture smoke test exercises them, so a crash
is caught; wrong *numbers* are not.

**Running the scanner:**

```
python3 scanner/orgiq_spike.py /path/to/sfdx-project --name "Client X"
```

Prints a Markdown report: per-rule counts, description coverage, semantic density,
the before/after grounding-payload estimate, and how many reporting documents were
parsed. `--out FILE` writes it instead. `--scan-json FILE` writes the full scan record
set. `--mode Org|Hybrid` only changes a label on that record — it does not connect to
anything.

**Emitting a backlog CSV** (importable into Jira / Azure DevOps):

```
python3 scanner/orgiq_spike.py /path/to/sfdx-project --name "Client X" --backlog backlog.csv
```

Only findings meeting `severity >= Medium AND confidence >= Medium` are emitted
as tickets (PRD §4.6); everything else is held back as an observation. Each row
carries remediation steps, acceptance criteria, a **provisional** effort estimate,
and a deterministic External ID so re-imports update tickets instead of duplicating
them.

**Generating fixture data:**

```
python3 fixtures/seed_data.py --volume 2000 --out contacts.csv
```

Prints expected fill rates, staleness ratio and duplicate rate — that output is the
ground truth D2 rules will be graded against.
