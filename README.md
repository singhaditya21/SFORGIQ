# OrgIQ — Project Status

**Agentforce Readiness Analyzer.** A tool that reads a Salesforce org (or just its
source repository) and reports whether it can actually support agents — terminating
in a prioritised, importable tech backlog rather than a dashboard.

Last updated: 24 July 2026

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
| Scanner (`scanner/`) | Working spike. 5 D1 rules, source mode, runs on real metadata |
| Data generator (`fixtures/`) | Working. Generates CSV with controlled distributions |
| Salesforce objects (`salesforce/`) | Built, XML-validated, **deployed to `orgiq`** (3 objects, 32 fields) |
| Dashboard | Not started |
| Backlog CSV output | Working. Threshold-gated Jira CSV, remediation + provisional effort points |
| HTML report | Not started |

**Environment done:** Salesforce CLI installed (macOS arm64), Developer Edition org
created, `sf org login web --alias orgiq` complete.

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
amplify. Only D1 is implemented.

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

1. ~~**Deploy the objects**~~ — **done.** Deployed to `orgiq` via `sf project deploy start --source-dir salesforce/force-app --target-org orgiq` (needs `sfdx-project.json`, now at repo root).
2. ~~**Backlog CSV emitter**~~ — **done.** `scanner/backlog.py`; run with `--backlog out.csv` (see below).
3. **HTML report** — the scan output as something shareable
4. **Dashboard demo mode** — static site reading bundled sample data, no auth
5. **OAuth live mode** — Connected App + CORS, then real data

Step 3 completes the first end-to-end slice (scan → shareable output). Everything after is additive.

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
  fixtures/
    seed_data.py         fixture data generator
  salesforce/
    force-app/           3 custom objects, 32 fields (deployed to orgiq)
```

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
