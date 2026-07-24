# OrgIQ — Project Status

**Agentforce Readiness Analyzer.** A tool that reads a Salesforce org (or just its
source repository) and reports whether it can actually support agents — terminating
in a prioritised, importable tech backlog rather than a dashboard.

Last updated: 24 July 2026

**Live dashboard:** https://singhaditya21.github.io/SFORGIQ/ — demo mode, showing a
real scan loaded into the OrgIQ Salesforce org.

---

## What it does, in one line

Point it at an org or a repo. It tells you what's wrong, with evidence, and gives you
a CSV that imports into Jira.

```
orgiq scan --source ./force-app     # files only, no org needed
orgiq scan --org my-client-org      # full scan
```

---

## Current state

| Piece | Status |
|---|---|
| Specification (`PRD.md`) | v0.7 — complete, 13 sections + appendices |
| Scanner (`scanner/`) | 20 rules across **D1–D5**, all running on parsed metadata (fields, Flows, Apex, triggers, permission sets) |
| Tests / CI | 39 pytest tests over the rule packs + scoring, plus an end-to-end fixture smoke test; CI also builds the dashboard |
| Data generator (`fixtures/`) | Working. CSV generator, messy-org fixture, and a 24-org portfolio generator |
| Salesforce objects (`salesforce/`) | **Deployed to `orgiq`** (3 objects, 32 fields) + `OrgIQ_Admin` permission set, Connected App, CORS origin |
| Salesforce data | **Loaded & confirmed** — 24-org portfolio: 24 scans, 120 dimension scores, 1,976 findings across D1–D5 (~4/5 MB) |
| Backlog CSV output | Working. Threshold-gated Jira CSV, remediation + provisional effort points |
| Dashboard (`dashboard/`) | **Live on GitHub Pages.** Portfolio overview + per-org drill-down (radar, trend, backlog); demo + OAuth live mode |

**Environment done:** Salesforce CLI installed (macOS arm64), Developer Edition org
created, `sf org login web --alias orgiq` complete.

**Keeping it alive.** GitHub Pages is static and effectively always-up; the public
dashboard's demo mode reads a bundled JSON, so it stays live even if the org is
gone. The one perishable piece is the **Agentforce dev org**, which Salesforce
deletes after ~45 days without a login. `.github/workflows/keepalive.yml` logs in
weekly (and writes a heartbeat commit so GitHub never disables the scheduler), so
nothing ever has to be done by hand. One-time setup: `bash scripts/setup-keepalive.sh`
to store the `SFDX_AUTH_URL` secret.

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
*Not Assessed* rather than guessing. The demo portfolio supplies synthetic inputs for all
five — the rules are real, the fictional orgs' inputs are generated.

---

## Decisions made, and why

Recorded so they don't get re-litigated.

**Scratch orgs, not persistent Developer Edition, for the fixture.** DE gives 5 MB storage
(~2,500 records) and 5,000 API calls per day — the second limit bites hardest during rule
iteration. Scratch orgs are declarative and disposable.

**Source mode is a first-class input path, not a degraded one.** The scanner reads SFDX
directories with no org connection, no credentials, no API consumption. This is what makes
public-corpus validation practical and CI adoption possible.

**Partial coverage excludes a dimension from the composite.** A dimension scored from 40% of
its rules isn't a lower score, it's an unreliable one. Coverage below 70% → marked
`partially assessed`, excluded from the composite, stated in the report.

**Rule confidence is capped by validation evidence.** Rules ship `experimental` (fixture only,
Low confidence, never auto-emits), reach `validated` on the public corpus, and `field-proven`
only on adjudicated real-world precision.

**Read-only against target orgs, always.** Findings are written to a *separate* OrgIQ org.
The target org is never written to.

**Dashboard architecture:** GitHub Pages static site → OAuth PKCE → OrgIQ org REST API.
No server. Needs a Connected App and a CORS allowlist entry. Must have a demo mode reading
a bundled sample JSON, otherwise anyone opening the public link sees a login screen.

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
4. Naming — `OrgIQ` is provisional.

---

## Immediate next steps

1. ~~**Deploy the objects**~~ — **done.** Deployed to `orgiq` via `sf project deploy start --source-dir salesforce/force-app --target-org orgiq` (needs `sfdx-project.json`, now at repo root). Access is granted by the `OrgIQ_Admin` permission set.
2. ~~**Backlog CSV emitter**~~ — **done.** `scanner/backlog.py`; run with `--backlog out.csv` (see below).
3. ~~**Shareable report**~~ — **done, as a React dashboard** (superseded the flat HTML report). Lives in `dashboard/`, deployed to GitHub Pages.
4. ~~**Dashboard demo mode**~~ — **done.** `dashboard/public/sample-scan.json` is exported from the org; the public site reads it, no auth.
5. ~~**OAuth live mode**~~ — **done.** A PKCE public-client Connected App + CORS origin are deployed; the dashboard's "Connect Salesforce" button runs the browser OAuth flow and reads the org live. (The interactive sign-in is the org owner's action and only works from the Pages origin.)

The full slice is live: portfolio → Salesforce → backlog CSV + dashboard (demo **and** OAuth live mode), across all five dimensions. Remaining: real (non-synthetic) D2–D5 assessment against org metadata, effort calibration, and the public-corpus validation from the PRD roadmap.

---

## Folder contents

```
SFORGIQ/
  README.md              this file
  PRD.md                 full specification, v0.7
  sfdx-project.json      SFDX config so the objects can be deployed
  scanner/
    orgiq_spike.py       working scanner, 5 D1 rules, stdlib only
    backlog.py           Jira-importable backlog CSV emitter (threshold-gated)
    scan_result.py       assembles the full scan record set (Salesforce schema)
  fixtures/
    seed_data.py         fixture data generator (D2 record data)
    gen_messy_org.py     generates the messy-org metadata fixture
    messy_org/           the generated defect-catalogue fixture (3 objects, 42 fields)
  salesforce/
    force-app/           3 custom objects, 32 fields, OrgIQ_Admin permission set
    load_scan.py         idempotent Bulk-API loader (scan result JSON -> org)
  dashboard/             React portfolio dashboard; deployed to GitHub Pages
    src/views/           PortfolioView (overview) + OrgDetail (drill-down)
    export_portfolio.py  exports every scan from the org into public/portfolio.json
    export_demo_data.py  exports a single scan (legacy, single-scan view)
  .github/workflows/     GitHub Pages build + deploy
```

**End-to-end run** (portfolio → Salesforce → dashboard data):

```
# generate a 24-org portfolio and bulk-load it into the org
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

Covers every rule pack (including regression tests for the false positives the
spike shipped and fixed), the §4.6 backlog gate, external-id idempotency, the
readiness bands, and the gate caps. CI runs these plus a full fixture scan and a
dashboard build on every push.

**Running the scanner:**

```
python3 scanner/orgiq_spike.py /path/to/sfdx-project --name "Client X"
```

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
