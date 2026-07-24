# OrgIQ — Agentforce Readiness Analyzer

**Product Requirements Document**

| | |
|---|---|
| **Status** | Draft for review — specification with validation evidence |
| **Version** | 0.7 |
| **Author** | Aditya Singh |
| **Last updated** | 2026-07-23 |
| **License** | Apache 2.0 (proposed — see §9) |
| **Repo posture** | Public, open source, contributions invited |

> **Working title.** `OrgIQ` is provisional. Naming decision open — see §10.

**Changelog**

- **v0.7** — Consolidated into a single document. Spike executed against a public corpus; results, defects found, and implications recorded in §13. D1.NUMBERED_FAMILY added as a rule. Tier 2 corpus limitation identified and recorded (§6.4.1). GRND-7 rescoped. Spike implementation included as Appendix C.
- **v0.6** — §5 re-anchored on the two-surface model after correcting a wrong assumption about how Agentforce grounds. Selection Precision replaces raw token cost as the primary metric; cost impact re-derived through turns-to-resolution and labelled a hypothesis pending measurement (§5.7). Thesis updated (§1). GRND-7 and GRND-8 added.
- **v0.5** — Source mode added as a first-class input path (§7.2). Capability-declaring rules and mechanical degradation. Partial-coverage dimensions excluded from the composite (§7.2.4, §4.2). UC-7 CI gate added. SRC workstream added to roadmap.
- **v0.4** — Objectives made explicit and staged (§12). Ownership and IP structure defined. Contribution guide moved forward to v0.1.
- **v0.3** — Defect-first rule authoring discipline defined (§6.3.7). Fixture realism ceiling addressed via a three-tier validation model and rule maturity ladder (§6.4). Rule confidence now gated by validation evidence (§4.5). Roadmap extended with the VAL workstream (§11).
- **v0.2** — Seed environment specified as a first-class test fixture (§6.3). Target environment changed from persistent Developer Edition to scratch orgs. Evaluation prompt provenance resolved and moved out of open questions. False-positive measurement method defined (§8.1). Roadmap items identified (§11).
- **v0.1** — Initial draft.

---

## 1. Problem & Thesis

### 1.1 The situation

Enterprises are buying agentic capability on Salesforce faster than they are preparing their orgs for it. Agent programmes are being scoped against org configurations that accumulated over eight to fifteen years of unreviewed change — thousands of custom fields, stacked automation, undocumented schema, and permission models nobody has audited since the original implementation.

Agents fail in these environments for reasons that have nothing to do with model quality. They hallucinate because the schema they are grounded on is ambiguous. They cannot act because no existing automation is safely invocable. They breach because they inherit permissions that were never designed for a non-human actor. They cause data incidents because their writes collide with automation nobody mapped.

### 1.2 Three specific failures

**Readiness is asserted, not measured.** Current practice is a senior architect reading Setup for two weeks and forming a professional opinion. That opinion is expensive, unrepeatable, unfalsifiable, and impossible to trend. Two architects assessing the same org will produce different answers, and neither can show their work.

**Org debt is diagnosed but not costed.** Free tools (Optimizer, Health Check, Code Analyzer) and licensed platforms both produce findings. Neither reliably produces *sequenced, estimated, ready-to-import work*. The gap between a technical debt dashboard and forty-seven prioritised tickets in the client's Jira is precisely the gap where remediation programmes die — unfunded, because nobody converted the finding into a business case.

**Selection quality is invisible.** Agents ground through retrieval, which means something must choose the right field, and the right action, from ambiguous candidates. Where three fields carry the same business meaning and none is meaningfully described, that choice is made on noise — silently, with no error raised. Wrong selection produces an insufficient result, the controller re-plans, and the conversation takes five turns instead of two. Nothing in the ecosystem measures this, so nobody manages it.

### 1.3 Thesis

> Agent readiness is measurable from metadata that Salesforce already exposes for free. The measurement is only worth making if it terminates in costed, sequenced, importable work. And the single most under-measured dimension — whether an agent can reliably select the right field and the right action from what the org exposes — is both quantifiable and directly improvable.

### 1.4 Why now

Three conditions have converged. Agentforce adoption has moved from pilot to production budget, so readiness questions now have money attached. The dependency and metadata APIs needed to answer them are free and mature. And token cost has become a line item that CIOs actually see on an invoice, which makes grounding efficiency a conversation a CIO will have.

---

## 2. Positioning & Non-Goals

### 2.1 Where this sits

The ecosystem has two established tiers.

**Free point tools** — Salesforce Optimizer, Security Health Check, Code Analyzer, Field Trip, OrgCheck. Strong signal, genuinely free, but each answers one narrow question and none synthesise. The output is a set of disconnected reports that a human must reconcile.

**Licensed platforms** — metadata dictionaries, dependency analysis, documentation automation, change intelligence. Comprehensive and mature. They require a managed package install and an authorised org connection, which places them behind a security review and a procurement cycle. They are architected for *continuous* documentation and change management across the life of an org.

OrgIQ occupies neither position. It is a **zero-install, read-only, point-in-time readiness assessment that terminates in a backlog.**

### 2.2 Three deliberate differences

**It runs before procurement.** CLI plus a read-only permission set. No managed package, no AppExchange install, no security review. In regulated sectors that difference is three to six months, which is the difference between assessing an org in week one of an engagement and assessing it after the engagement has already been scoped.

**It can run with no org access at all.** Source mode (§7.2) analyses an SFDX repository directly — no authentication, no credentials, no API consumption. This clears an adoption bar nothing else in the category clears, and makes the tool viable inside a client's CI pipeline before any commercial relationship exists.

**The output is work, not a dashboard.** Every finding carries evidence, blast radius, remediation steps, an effort estimate, and acceptance criteria. The primary artifact is a CSV that imports into Jira or Azure DevOps, not a visualisation.

**It measures selection economics.** No other tool quantifies whether an agent can reliably choose the right field and action from what an org exposes, or treats that as an optimisation target with a measured accuracy constraint. See §5.

### 2.3 Explicit non-goals

These are commitments, not omissions. Scope discipline is the primary risk control on this project.

| Not this | Because |
|---|---|
| A metadata dictionary or documentation platform | Licensed platforms do this well and continuously. OrgIQ ingests their exports where present. |
| A deployment, CI/CD, or DevOps tool | Different problem, crowded market. |
| A replacement for licensed platforms | Explicitly designed to coexist. Complement, not compete. |
| A security scanner | Defers to Health Check and Code Analyzer; ingests their output rather than reimplementing it. |
| A write-back or remediation tool | **Read-only is a hard architectural constraint.** OrgIQ never writes to a customer org. |
| A Data Cloud implementation tool | It assesses readiness for Data Cloud identity resolution; it does not configure it. |
| A general org health scanner | Readiness for agentic workloads is the lens. Findings unrelated to that lens are out of scope. |

### 2.4 Comparison posture

The repository will carry a factual capability comparison against major alternatives — what each tool covers, licensing model, install requirement. It will not carry competitive criticism. Fair comparison builds credibility with the practitioner audience; positioning against named vendors ages badly and forecloses partnership.

---

## 3. Users & Use Cases

### 3.1 Personas

**Primary — CoE Architect.** Runs the scan in week one of a client engagement. Needs defensible evidence to justify a remediation phase before agent build begins. Success for them is walking into a steering committee with a number and a backlog instead of an opinion.

**Secondary — Delivery Lead.** Needs the findings as estimated, sequenced tickets inside the tracker the team already uses. Will not adopt anything requiring manual transcription.

**Secondary — Client Salesforce Architect / Admin.** The open-source user. Runs it on their own org without any consulting relationship. This persona is why the project is open source, and their adoption is what makes the rule packs good.

**Audience, not user — Client CIO / Head of CRM.** Never runs the tool. Reads the index, the trend, and the cost-per-conversation number. Approves or declines funding.

### 3.2 Use cases

| ID | Use case | Primary persona |
|---|---|---|
| UC-1 | Pre-engagement readiness assessment | CoE Architect |
| UC-2 | Agent use-case feasibility triage — which of six candidate agents are viable on this org today | CoE Architect |
| UC-3 | Remediation backlog generation and import | Delivery Lead |
| UC-4 | Quarterly re-scan and burn-down trend | Delivery Lead |
| UC-5 | Pre-go-live readiness gate | CoE Architect |
| UC-6 | Self-service org assessment | Client Architect |
| UC-7 | CI pipeline gate on every pull request, zero org access | Client Architect |

UC-1 is the wedge. UC-4 is what converts a one-off audit into a retained relationship. UC-6 is what builds the community, and UC-7 is what makes adoption frictionless enough for that to happen — a tool that runs against a repository with no credentials clears an adoption bar that a tool needing org access does not.

---

## 4. The Readiness Model

### 4.1 Five dimensions

Each dimension answers one question about whether an agent can operate on this org.

---

**D1 — Grounding Quality**
*Can a language model correctly understand this schema?*

- Field description coverage on agent-exposed objects
- Help text coverage on user-facing fields
- API name interpretability — abbreviations, opaque identifiers, `Field1__c` patterns
- Semantic duplication — multiple fields carrying the same business meaning
- Numbered field families — repeating groups presenting N near-identical retrieval candidates, typically with identical descriptions
- Low-information descriptions — text restating the label, adding payload without disambiguation (§5.5)
- Picklist value hygiene — undocumented codes, orphaned values, inconsistent casing
- Object-level description coverage

---

**D2 — Data Foundation**
*Is the data underneath trustworthy enough to ground on?*

- Field population rate, measured on records modified in the trailing twelve months
- Identity key completeness — email, phone, external ID fill rates across Lead, Contact, Account. This is the direct predictor of Data Cloud identity resolution quality.
- Duplicate rate on core objects
- Stale record ratio
- Validation rule bypass patterns and required-but-empty fields

*Note: D2 is the only dimension requiring record data access. It degrades gracefully — see §7.6.*

---

**D3 — Action Surface**
*Can the agent safely do anything, or only talk?*

- Inventory of invocable Apex methods and Flows
- Bulk safety — SOQL and DML in loops, governor limit exposure
- Idempotency signals — does re-invocation duplicate records
- Error handling presence and quality on invocable paths
- Test coverage measured **on invocable paths specifically**, not org-wide average
- Deterministic failure modes — does the action fail predictably

Most orgs score very low here. The automation exists but was written for human-triggered, single-record, happy-path execution. This dimension usually generates the largest backlog.

---

**D4 — Permission Blast Radius**
*What can the agent reach if something goes wrong?*

- Profiles and permission sets carrying View All / Modify All at object or system level
- Field-level security gaps on sensitive fields
- Sharing model complexity and manual share dependencies
- Guest and community user exposure paths
- Delta between the intended agent user's permissions and a least-privilege baseline

An agent inherits the permissions of the user it runs as. In regulated sectors this is an audit finding waiting to be written.

---

**D5 — Automation Collision**
*Will the agent's writes trigger cascading chaos?*

- Trigger and record-triggered flow count per object
- Order-of-execution risk where multiple automations write to the same fields
- Recursive and cascading automation chains
- Async job density and queue pressure
- Governor limit headroom on high-traffic objects

---

### 4.2 Scoring methodology

**Decision: composite plus sub-scores, never composite alone.** Each dimension scores 0–100 from weighted sub-measures. The composite is a weighted mean of the five. The composite is never displayed without the five sub-scores beside it — a single number invites gaming and hides exactly the detail that makes the finding actionable.

**Decision: absolute rubric in v1.** Scores are computed against a fixed, published rubric, not against a peer benchmark. Relative percentile scoring is more persuasive but requires a corpus of scanned orgs that does not yet exist. The schema carries a `rubric_version` field so that relative scoring can be added later without invalidating historical scans.

**Decision: configurable weighting with shipped profiles.** Weights are declared in a YAML profile. Two profiles ship: `default` (equal weighting) and `bfsi` (D4 weighted materially higher). Profiles are a natural community contribution surface.

**Decision: gate rules cap the composite.** A high composite must never mask a critical failure:

- Any Critical-severity D4 finding caps the composite at **60**
- Any dimension scoring below **30** caps the composite at **70**

Gate rules are declared in the rubric file and always reported explicitly — the output states that a cap was applied and why.

**Decision: partial coverage excludes a dimension from the composite.** Where the input mode or available signals allow only part of a dimension's rule set to run, the dimension is reported with its coverage percentage and, below the coverage threshold, excluded from the composite entirely. See §7.2.4.

### 4.3 Readiness bands

| Score | Band | Meaning |
|---|---|---|
| 0–40 | **Not Ready** | Agent deployment will fail. Foundational remediation required first. |
| 41–60 | **Foundational Work Required** | Narrow, low-risk agents feasible. Broad deployment is not. |
| 61–80 | **Conditionally Ready** | Deploy with named mitigations and a monitoring plan. |
| 81–100 | **Ready** | No structural blockers identified. |

### 4.4 Finding schema

Every finding is a record with this shape. The schema is the contract between the detection layer and everything downstream.

```
finding_id            deterministic hash — see idempotency below
rule_id               stable rule identifier
rubric_version        semver of the rubric that produced this
dimension             D1..D5
severity              Critical | High | Medium | Low
confidence            High | Medium | Low
component_type        CustomField | ApexClass | Flow | PermissionSet | ...
component_api_name    fully qualified API name
evidence_query        the exact query or extraction that proves this finding
evidence_payload      the returned values
blast_radius_count    dependent components, from the dependency graph
remediation           ordered remediation steps
effort_points         from a published calibration table
acceptance_criteria   how to verify the fix
first_seen_scan       scan id
last_seen_scan        scan id
status                open | resolved | suppressed
```

### 4.5 Confidence, and why it is mandatory

**Decision: every finding carries a confidence attribute.** Static analysis of a Salesforce org produces false positives — a field that appears unused may be referenced in a managed package, a formula, or an integration outside the dependency graph. A tool that presents low-confidence findings with the same authority as high-confidence ones destroys its own credibility on first contact with a knowledgeable architect.

Low-confidence findings are recorded and reported but **never auto-emit as backlog items**. They appear in an observations appendix flagged for human review.

A finding's confidence is additionally **capped by the maturity of the rule that produced it**. A rule validated only against the synthetic fixture cannot emit High-confidence findings regardless of how certain its logic is, because fixture validation proves internal correctness and not real-world precision. See §6.4.

### 4.6 Backlog conversion

**Decision: threshold-gated emission.** All findings are recorded. Only findings meeting `severity >= Medium AND confidence >= Medium` auto-emit as backlog items. Everything else lands in the observations appendix. Without this gate, a large org produces a four-thousand-ticket dump that nobody imports.

Findings are clustered into epics before emission — "Retire 383 unreferenced fields on Account and Contact" is one epic with 383 child items, not 383 loose tickets.

**Idempotency.** `finding_id = hash(rule_id + component_api_name + org_id)`. Re-scanning updates existing tickets, closes resolved findings, and creates only what is new. This is what converts a one-off audit into a trackable burn-down, and the burn-down is what gets funded.

### 4.7 Published, versioned rubric

**Decision: the rubric is part of the open-source artifact.** It lives at `rubric/v1.0.0.yaml`, is semver-versioned, and every scan output carries the rubric version that produced it. Scores are only comparable within a rubric major version, and the tool states this explicitly.

This is deliberate. A scoring model that cannot be inspected is not credible to the practitioner audience, and a scoring model that changes silently between releases makes trending meaningless.

---

## 5. Grounding & Selection Economics

This is the dimension nothing else in the ecosystem measures, and the core original contribution of the project.

### 5.1 The architecture this operates in

An earlier draft of this section modelled grounding as full-schema injection — every field on an object entering context on every turn, with cost scaling directly with field count. That is not how the platform works, and the correction materially changes the metric.

Agentforce grounds through retrieval. The Atlas controller pulls context from Data 360 records, Agentforce Data Library indexes, prompt templates, and conversational memory, and makes multiple model calls per user turn rather than a single round trip. A retriever selects what enters context. The full schema does not.

This splits into **two distinct surfaces with different cost profiles**, which the earlier model conflated:

| | Grounding surface | Action surface |
|---|---|---|
| What enters context | Fields selected by a retriever | Topic-scoped action definitions and parameter schemas |
| Payload bounded by | Retriever configuration | Topic design |
| Dominant failure | Wrong field retrieved | Wrong action selected, or parameters misfilled |
| Cost scales with | Failed turns, not field count | Action count and definition verbosity |

The consequence: **on the grounding surface the cost of schema bloat is accuracy, not tokens.** On the action surface it is both.

### 5.2 The two failure modes

**Selection error.** Three fields carrying the same business meaning, none adequately described, means the retriever ranks on ambiguous text and returns one of them — silently. Under full-schema injection the model would at least see all three and could reason about the ambiguity. Under retrieval it does not get the chance. **Retrieval makes disambiguation more important, not less.**

The same holds on the action surface: two similarly-described invocable actions produce mis-selection during planning.

**Payload cost.** Action definitions and their parameter schemas enter the planning context for every turn within a topic. An org exposing eighty verbosely-defined actions on a topic pays that on every planning cycle. This is where token cost genuinely scales.

### 5.3 Metrics

| Metric | Definition | Surface |
|---|---|---|
| **Selection Precision** | Proportion of evaluation prompts where the correct field or action is chosen | Both |
| **Context Payload** | Tokens consumed by the candidate definition set at planning time | Action, primarily |
| **Semantic Density** | Proportion of metadata tokens carrying disambiguating information | Both |
| **Turns-to-Resolution** | Mean user turns to complete a task | Both |

### 5.4 The economic bridge

Cost per conversation survives as a headline number, but it is derived differently than the earlier model claimed.

Atlas re-plans when a result is insufficient rather than failing outright. So the chain is:

```
ambiguous metadata → wrong selection → insufficient result
                  → re-plan → additional model round trips
```

**Ambiguity costs money through turn count, not through payload size.** A conversation that resolves in two turns instead of five costs less than half as much, and the difference is attributable to metadata quality.

```
cost per conversation ≈ turns_to_resolution × per_turn_payload × price
```

Both terms are addressable. Disambiguation reduces the first; action surface hygiene reduces the second. The original claim — that cost scales with field count — was wrong in mechanism while being right in direction, and the corrected model is both defensible and still legible to a CIO.

### 5.5 The description trap

Naive description-filling makes things **worse**, and worse under retrieval than under injection.

A description reading "Segment" on a field named `Segment__c` adds tokens and no disambiguating information. Under full-schema injection that is merely wasteful. Under retrieval it is actively harmful, because the retriever *ranks on that text* — noise degrades ranking quality directly.

This means **documentation coverage is a misleading metric.** An org can raise description coverage from 20% to 100% with generated text and measurably worsen selection precision. Semantic Density exists to catch exactly this, and it is why auto-generating descriptions across an org — a feature several tools offer — is not obviously an improvement.

The optimisation objective is two-sided: **payload down, disambiguating information up.**

### 5.6 The harness

No recommendation is issued without evidence that selection still works. This is non-negotiable and is what makes the dimension defensible rather than a counting exercise.

For each assessed object and each topic action set, the harness runs a fixed evaluation set of 30–50 representative prompts against both raw and optimised metadata, measuring selection precision and, where an agent is available to exercise, turns-to-resolution.

```
Account:  selection precision  0.71 → 0.93   (+0.22)
          context payload      4,180 → 890 tokens
          semantic density     0.31 → 0.88
          VERDICT: accept
```

If selection precision degrades beyond a configured tolerance, the optimisation is **rejected** and reported as rejected.

Evaluation prompt sets are hand-authored per object and versioned alongside the seed defect catalogue — see §6.3.5. For client engagements, prompts derive from the candidate agent use cases in scope, so the harness measures accuracy on the questions that org actually intends to ask.

### 5.7 Validation status

The re-planning cost model in §5.4 is a **hypothesis pending measurement**, and is labelled as such wherever it appears in client-facing output until measured.

Two experiments settle it, both cheap:

1. **Ambiguity prevalence.** Parse public Salesforce repositories and count semantic collisions per object. Establishes whether the problem is common enough to matter.
2. **Mis-retrieval demonstration.** Configure a retriever over a seeded object with deliberate collisions and measure selection precision against the fixture's known-correct answers. Establishes whether ambiguity actually degrades retrieval, and by how much.

Until experiment 2 returns, no client-facing material asserts a cost saving. Selection precision is reported as measured; cost impact is reported as modelled. See GRND-7 and GRND-8.

### 5.8 The tool's own token economics

The analyser must be cheap enough that the scan can be given away. Target: **under 150,000 LLM input tokens for a full scan, under 10,000 for a delta scan.**

Achieved by:

1. **Deterministic detection first.** Rule packs find violations. The LLM never sees a clean component. This alone removes roughly 95% of volume.
2. **Fingerprint deduplication.** Findings hash to `rule_id + component_type + pattern`. Four hundred instances of the same finding shape cost one LLM call and four hundred applications. The cache persists across orgs.
3. **Symbol tables, not source.** Apex is sent as a signature graph — class, methods, SOQL line references, complexity, callers — not as a body. Roughly 8,000 tokens becomes 200.
4. **Canonical compact representation.** Metadata XML is normalised to tabular form before anything downstream sees it.
5. **Tiered models.** A small model handles triage and classification; the expensive model is reserved for the top findings and the executive narrative.
6. **Delta scanning.** Subsequent scans process only metadata whose `LastModifiedDate` has moved.

Token consumption per scan is itself reported as a product metric.

---


## 6. Scope & Release Plan

Five dimensions is the destination, not the first release. The cut lines below are firm — **v0.1 must stand alone and be demonstrable even if nothing after it ships.**

| Release | Contents | Notes |
|---|---|---|
| **v0.1** | D1 Grounding Quality only, **source mode first**. Parse → DuckDB → ~15 rules → HTML report + Jira CSV. **No LLM.** Seed fixture with D1 defect catalogue and validation harness (§6.3). Org mode for dependency and usage signals. | Proves the full vertical slice end to end. The fixture is a blocker, not an add-on. |
| **v0.2** | Grounding Economics measurement, accuracy harness, hand-authored eval prompt sets. | The demonstrable differentiator. |
| **v0.3** | D5 Automation Collision, D4 Permission Blast Radius. | Both pure metadata — no record data access required. |
| **v0.4** | D3 Action Surface. Code Analyzer integration. | Static analysis dependency. |
| **v0.5** | D2 Data Foundation. | Requires record data access; most sensitive, deliberately last. |
| **v1.0** | Composite index, gate rules, delta scanning, trend reporting, published rubric, contribution guide, documentation. | |

Every dimension release includes its own defect catalogue extension and validation coverage. **A dimension does not ship until its rules pass the fixture at declared precision.**

### 6.1 Out of scope for v1.0

No web UI beyond static HTML output. No multi-org orchestration. No CI/CD integration. No scheduled or hosted execution. No write-back under any circumstance.

### 6.2 Sequencing note

The seed environment is a **v0.1 blocker, not demo polish**. Detection rules cannot be validated without ground truth, so the defect catalogue and expected-findings manifest must exist before or alongside the first rule pack.

### 6.3 Seed Environment & Test Fixture

**Design principle.** The seeded org is not demo scaffolding. It is the project's regression fixture and its source of ground truth. Every planted defect declares the rule it must trigger, which means the scanner is graded against a known answer rather than an opinion.

#### 6.3.1 Target environment

**Decision: scratch orgs, created from a Developer Edition org enabled as a free Dev Hub.**

A persistent Developer Edition org is a poor fixture:

| DE constraint | Consequence |
|---|---|
| 5 MB data storage (order of 2,500 records at typical record size) | Insufficient for credible population, duplicate, and staleness distributions |
| 5,000 API calls per 24 hours | Exhausted quickly by repeated scans during rule development — throttles you exactly when iterating fastest |
| Two full licenses | Constrains multi-persona permission scenarios for D4 |
| Persistent state | Reset requires a cleanup script that must itself be maintained and trusted |

Scratch orgs are declarative, source-defined, and disposable. Reset is deletion and recreation, so "resettable in minutes" is literally true rather than aspirational, and no cleanup path can silently drift.

*Override note:* if a persistent client-facing demo org is later required, the same seed artifacts deploy to it unchanged. The fixture role stays with scratch orgs regardless.

#### 6.3.2 Repository structure

```
seed/
  scratch-def.json           org shape and enabled features
  defects/
    d1-grounding.yaml
    d3-action-surface.yaml
    d4-permissions.yaml
    d5-automation.yaml
  metadata/                  generated source metadata
  data/
    plan.json                sf data import tree plan
    *.json                   record trees
  eval/
    account-prompts.yaml
    contact-prompts.yaml
  expected-findings.json     generated ground truth
```

#### 6.3.3 Defect catalogue

Each defect declares both what it plants and what the scanner must detect:

```yaml
- defect_id: D1-DUP-001
  dimension: D1
  description: Three Account fields carrying identical business meaning
  plants:
    - CustomField: Account.Segment__c
    - CustomField: Account.Cust_Seg__c
    - CustomField: Account.SegmentCode__c
  expects:
    rule_id: D1.SEMANTIC_DUPLICATE
    severity: Medium
    confidence: Medium
    count: 1
```

Coverage target: at least three defect instances per shipped rule — the obvious case, a boundary case, and a near-miss that must **not** trigger. Negative cases matter more than positive ones, because they are what actually measures false positives.

#### 6.3.4 Record data generation

Metadata debt is easy to plant. Record data is where synthetic fixtures usually fail, because uniform random generation produces population percentages no real org exhibits.

Declared per field as a target with a distribution shape:

```yaml
Contact:
  volume: 2000
  fields:
    Email:          { fill: 0.62, shape: power_law_by_created_date }
    Phone:          { fill: 0.41, shape: uniform }
    External_Id__c: { fill: 0.18, shape: recent_only }
  duplicates:
    rate: 0.07
    patterns: [whitespace, case, abbreviation, transposition]
  staleness:
    outside_12_months: 0.55
```

Two constraints worth stating explicitly:

- **Duplicates must be near-matches, not copies.** Exact duplicates are trivially detected and prove nothing about a rule's real-world precision.
- **Audit field backdating requires explicit enablement.** `CreatedDate` and `LastModifiedDate` cannot be set on insert unless *Set Audit Fields upon Record Creation* is enabled. The scratch org definition must request it, and the seed must fail loudly if unavailable — otherwise staleness ratios silently seed as zero and D2 scores are meaningless.

#### 6.3.5 Evaluation prompt sets

30–50 prompts per seeded object, each declaring the fields a correct answer must select.

**Decision: hand-authored, not generated.** Generated prompts inherit the generator's understanding of the schema, which is precisely the thing under test — a generator that already knows `Cust_Seg__c` means customer segment will not produce the prompts that expose the ambiguity. Hand-authoring is slower, and that is the point.

Prompt sets version alongside the defect catalogue, since any schema change invalidates the expected field selections.

#### 6.3.6 Expected-findings manifest and validation harness

The manifest is generated from the defect catalogue at seed time and serves as machine-readable ground truth.

The validation harness runs a full scan against the seeded org, diffs results against the manifest, and emits **precision, recall, and F1 per rule**. This is the measurement method behind the false-positive target in §8.1 — without it, that target is an assertion.

The harness runs in CI on every rule pack change. Any rule whose precision falls below its declared threshold fails the build.

**Source-mode validation shortcut.** The fixture's metadata is generated source, so rules requiring only metadata signals — all of D1, and much of D3 and D5 — are gradeable against that source directly, with no scratch org deployment. Only org-mode signals (dependency graph, usage, records, test results) require the org to be spun up. This makes the v0.1 CI loop a directory read rather than an org provisioning cycle, and removes the API limit pressure that would otherwise bite during rule iteration.

#### 6.3.7 Defect-first rule authoring

Sequencing is a working discipline, not a Gantt dependency. Rules and their defects are co-authored, defect first:

1. Write the defect catalogue entries — **including the near-miss cases that must not trigger**
2. Deploy the seed; confirm the scan finds nothing
3. Write the rule
4. Confirm precision and recall against the manifest
5. **A rule cannot merge without its catalogue entries**

This is test-driven development applied to detection, and it exists to prevent a specific failure: if the fixture is built after fifteen rules already exist, every disagreement between rule and fixture is ambiguous — you cannot tell which one is wrong, and you debug both simultaneously against each other.

**Cross-contamination testing.** Every rule is graded against the *entire* seeded org, not only its own defects. Any finding a rule produces outside its declared expectations counts as a false positive. This makes the fixture compound in value: each defect added for one rule becomes a negative test case for every other rule.

**The blind-spot caveat.** A defect and a rule written by the same author encode the same assumptions, so the fixture passes trivially and proves less than it appears to. Two mitigations: near-miss cases must be authored before the rule, at a minimum ratio of one negative per positive; and catalogue contributions from authors who did not write the corresponding rule are explicitly solicited. This is a technical argument for the open-source model, not only a commercial one.

### 6.4 Validation tiers and rule maturity

A synthetic fixture proves that rule logic is internally correct. It cannot prove precision against real orgs, which contain patterns nobody thought to seed. That ceiling is real and cannot be removed — but it can be made visible and progressively closed.

#### 6.4.1 Three tiers of evidence

**Tier 1 — Synthetic fixture.** The seeded scratch org (§6.3). Proves logic correctness. Available from day one, costs nothing, catches regressions. Cannot prove real-world precision.

**Tier 2 — Public corpus.** Real, human-authored Salesforce metadata that is already public: open-source SFDX projects, Salesforce sample applications, and open-source managed packages published on GitHub. This is genuine accumulated debt written by real teams over real timescales, with no consent problem because the metadata is already published under open licences.

The corpus has no record data and limited permission metadata, so it validates D1, D3, and D5 well, D4 partially, and D2 not at all. Licence terms must be verified per repository before inclusion, and the corpus manifest lists source and licence for each entry.

**Source mode (§7.2) is what makes this practical.** These are SFDX repositories, not live orgs. Deploying each into a scratch org before scanning would be slow, fragile, and would fail routinely on missing dependencies and API version mismatches. Source mode analyses them where they are — a corpus scan is a git clone and a directory read.

Tier 2 converts "the rule works on defects I invented" into "the rule works on metadata I did not write." That is a genuine unlock for **rule correctness**.

**It does not establish prevalence, and measurement confirms this (§13).** The public corpus is bimodal: curated packages are maintained under code review and show good metadata hygiene, while sample and demo applications are not maintained at all and show none. Neither resembles a long-lived enterprise org shaped by years of admin-driven change, which is the actual target. Tier 2 will systematically **understate** how common these problems are in the population that matters.

Prevalence therefore remains unmeasured. The fixture cannot answer it either, since fixture defect density is chosen by the author — measuring prevalence against invented defects is circular. This is recorded as an open question (§10.3) rather than papered over.

**Tier 3 — Field evidence.** Adjudicated outcomes from real scans, contributed by users.

#### 6.4.2 Field evidence without collecting org content

The obvious approach — collecting anonymised findings — still transmits component names and metadata structure, which is schema disclosure and unacceptable to exactly the regulated clients this tool targets.

**Decision: transmit adjudications, never content.** An `orgiq review` command walks findings locally and records a verdict per finding. The optional telemetry payload is:

```
rule_id, rubric_version, verdict (true_positive | false_positive | unclear),
org_size_band, industry_band
```

No component names. No API names. No metadata. No record data. The payload cannot be reversed into anything about the org, which means it can be shared under a consent model simple enough that people will actually agree to it.

**Suppression as passive signal.** Local suppression files are needed for usability regardless. Aggregate suppression rate per rule is a proxy for precision even without explicit adjudication, and is computed locally whether or not telemetry is enabled.

#### 6.4.3 Rule maturity ladder

Every rule carries a maturity level, published in the rule pack, which caps the confidence of findings it produces:

| Maturity | Evidence required | Max finding confidence | Auto-emits? |
|---|---|---|---|
| `experimental` | Passes Tier 1 fixture | Low | No |
| `validated` | Passes Tier 1 and Tier 2 corpus | Medium | Yes |
| `field-proven` | Adjudicated precision above threshold across a minimum number of distinct real orgs | High | Yes |

New contributions enter at `experimental` and are promoted on evidence. Nothing is promoted on the author's confidence.

This makes the ceiling a visible product property rather than a hidden weakness. The tool never claims more certainty than its evidence supports, which is the same principle as §4.5 applied one level up — and a reviewing architect who checks the rule pack and finds honest maturity labels will trust the findings more, not less.

---

## 7. Architecture & Free-Tool Stack

### 7.1 Pipeline

```
Extract → Normalise → Detect → Enrich → Score → Emit → Track
```

Each stage writes to the canonical store. Stages are independently runnable, which matters for debugging and for clients who will only permit some extraction.

### 7.2 Input modes

OrgIQ supports two first-class input paths. Neither is a degraded form of the other; they answer different questions and are available at different points in an engagement.

**Source mode.** Reads an SFDX project directory. No org connection, no authentication, no API consumption. Analyses metadata as committed to version control.

**Org mode.** Connects read-only to a live org. Adds the dependency graph, usage signals, record data, and org-native health reports.

**Hybrid.** Source for metadata, org for enrichment. The preferred configuration where both are available — fast metadata parsing from the repository, dependency and usage signals from the org.

#### 7.2.1 Signal availability

| Signal | Source | Org |
|---|---|---|
| Component inventory | ✓ | ✓ |
| Field schema, descriptions, help text, API names | ✓ | ✓ |
| Picklist definitions | ✓ | ✓ |
| Apex and LWC source for static analysis | ✓ | ✓ |
| Flow definitions | ✓ | ✓ |
| Profiles and permission sets | as committed | actual |
| Dependency graph (`MetadataComponentDependency`) | ✗ | ✓ |
| Report and dashboard field references | if committed | ✓ |
| Field population rates | ✗ | ✓ |
| Record data — duplicates, staleness | ✗ | ✓ |
| Apex test results and coverage | ✗ | ✓ |
| Setup Audit Trail | ✗ | ✓ |
| Optimizer and Health Check output | ✗ | ✓ |

**Intended versus actual state.** Source mode reports what the repository says the org should be. Org mode reports what it is. For profiles and permission sets in particular these routinely diverge, since permission changes are frequently made directly in production. Source-mode D4 findings must be labelled as assessing intended configuration, and the divergence itself is a finding worth surfacing where both inputs are present (SRC-8).

#### 7.2.2 Dimension coverage by mode

| Dimension | Source | Org |
|---|---|---|
| D1 Grounding Quality | Full | Full |
| D2 Data Foundation | None | Full |
| D3 Action Surface | Partial — static analysis only, no test results | Full |
| D4 Permission Blast Radius | Partial — intended state only | Full |
| D5 Automation Collision | Partial — no async or limit headroom | Full |

D1 being fully source-capable is why v0.1 can ship source-mode-first, and why the fixture's D1 rules can be validated against generated source without deploying to an org at all.

#### 7.2.3 Capability resolution

Degradation is mechanical, not hand-coded per mode. Each rule declares the signals it requires:

```yaml
- rule_id: D1.SEMANTIC_DUPLICATE
  requires: [metadata.field_schema]

- rule_id: D1.UNREFERENCED_FIELD
  requires: [metadata.field_schema, dependency.graph, usage.report_references]
```

At scan time the resolver computes which rules can run given the signals actually available, executes those, and reports the remainder as skipped with the missing signal named. Adding a rule requires no mode-specific logic.

#### 7.2.4 Partial coverage must not masquerade as a score

A dimension scored from 40% of its rules is not a lower score — it is an **unreliable** score, and presenting it alongside fully-assessed dimensions is misleading.

- Every dimension score is reported with a **rule coverage percentage**
- Dimensions below **70% coverage** are marked `partially assessed` and **excluded from the composite**
- The report states which dimensions were excluded and which signals were missing

A source-mode scan therefore typically returns a composite over D1 alone, with D3, D4 and D5 reported as partially assessed and D2 as not assessed. That is an honest output. A single blended number computed across full and partial dimensions is not.

### 7.3 Extract

| Source | Provides |
|---|---|
| `sf` CLI / Metadata API | Component inventory |
| Tooling API — `MetadataComponentDependency` | Dependency graph |
| Tooling API — `EntityDefinition`, `FieldDefinition` | Schema, descriptions, FLS |
| Salesforce Optimizer | Pre-computed health findings |
| Security Health Check | Baseline security posture |
| Salesforce Code Analyzer (PMD, Graph Engine) | Static analysis findings |
| Report & Dashboard metadata | Business-visible field references |
| Setup Audit Trail | Change velocity and concentration |
| Licensed platform exports (where present) | Ingested, not duplicated |

All sources are free or already licensed by the client.

### 7.4 Canonical store

DuckDB, local file, five core tables:

```
scan            scan_id, org_id, timestamp, rubric_version, token_cost
component       component_id, type, api_name, attributes
dependency_edge from_component, to_component, dependency_type
usage_signal    component_id, signal_type, value, observed_at
finding         (schema per §4.4)
```

The dependency graph is loaded into NetworkX for blast-radius computation.

### 7.5 Detect, Enrich, Score, Emit

**Detect** — YAML rule packs, fully deterministic, zero LLM involvement. Rule packs are the primary community contribution surface.

**Enrich** — optional LLM tier for clustering, narrative, and estimation. Fingerprint-cached, tiered by model, and swappable to a local model.

**Score** — applies the versioned rubric and gate rules.

**Emit** — static HTML report, Jira/ADO CSV, JSON, and Markdown.

### 7.6 Security and deployment posture

This section is load-bearing for regulated-sector adoption.

- **Read-only.** OrgIQ requests no write scope. A documented read-only permission set ships with the repository.
- **Local-first.** All artifacts are written locally. Nothing leaves the machine by default.
- **No telemetry without explicit opt-in.**
- **LLM-optional.** The rules engine, scoring, and backlog emission run with no LLM at all. Enrichment is additive. For clients where metadata cannot leave the tenant — field names and picklist values constitute schema disclosure — the LLM layer is swappable to a local model.
- **Graceful degradation.** Any dimension whose source data is unavailable is reported as `not assessed` and excluded from the composite, with the exclusion stated on the report. The tool never silently scores a dimension it could not measure.

### 7.7 Stack

Python 3.11+, `sf` CLI, DuckDB, Pydantic, NetworkX, Jinja2, pytest. All free, no hosted dependencies.

---

## 8. Success Metrics

### 8.1 Product

| Metric | Target |
|---|---|
| Full scan wall-clock, 5,000-component org | < 30 minutes |
| LLM tokens, full scan | < 150,000 |
| LLM tokens, delta scan | < 10,000 |
| False positive rate on high-confidence findings | < 10%, measured per-rule against the seed fixture manifest (§6.3.6) |
| Backlog CSV import success into Jira/ADO | 100%, no manual cleanup |

### 8.2 Engagement

- Proportion of scans converting to a funded remediation phase
- Elapsed time from scan completion to approved backlog
- Measured grounding token reduction achieved post-remediation
- Readiness index delta across re-scans

### 8.3 Open source

- Contributors and merged rule-pack contributions
- Orgs scanned (opt-in telemetry only)
- Rubric fork/adaptation by third parties

Rule-pack contribution count is the leading indicator that matters. It signals the community is extending the commons rather than only consuming it.

---

## 9. Commercial & Contribution Model

### 9.1 Why a free tool and a paid service coexist

The obvious objection: if the tool is free and open, what is there to sell?

The tool produces a diagnosis. The diagnosis is roughly two days of work. The remediation is eight to twelve weeks of skilled delivery — retiring fields safely, rewriting automation to be bulk-safe and idempotent, restructuring permissions, and doing all of it without breaking a production org. The tool makes the expensive work *visible and fundable*; it does not make it cheaper.

Open sourcing the diagnosis is therefore not giving away the product. It is manufacturing qualified demand, and doing it with an artifact whose credibility comes precisely from being inspectable.

There is a second-order benefit. Every architect who runs OrgIQ on their own org and finds it accurate becomes a reference for the methodology.

### 9.2 Licence

**Apache 2.0.** Permissive, includes an explicit patent grant, and is unambiguously acceptable to enterprise legal review. A copyleft licence would obstruct exactly the enterprise adoption the project depends on.

### 9.3 What is open and what is not

| Open | Retained |
|---|---|
| Extraction, normalisation, detection engine | Engagement playbooks |
| Rule packs and rubric | Remediation runbooks |
| Scoring model and gate rules | Effort calibration data from real engagements |
| Report and backlog emitters | Client benchmark corpus |
| Demo seeding script | Pricing and commercial model |

The line is drawn at **measurement versus remediation**. Everything needed to produce a trustworthy score is open. Everything encoding how to fix what the score reveals is service IP.

### 9.4 Governance

Single maintainer initially, with a documented RFC process for rubric changes — because rubric changes alter scores, and score stability is what makes trending credible. Rule pack contributions follow standard PR review. Contribution guide, code of conduct, and a rule-authoring guide ship with v1.0.

---

## 10. Risks, Constraints & Open Questions

### 10.1 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| False positives destroy credibility on first contact | High | Mandatory confidence attribute; low-confidence findings never auto-emit; documented sampling protocol for validating rules |
| Client will not permit record data access (blocks D2) | High | D2 optional by design; graceful degradation with explicit `not assessed` reporting |
| Metadata egress prohibited in regulated clients | High | Local-first architecture; LLM layer optional and swappable to local model |
| Scope overrun for a single builder | High | Firm release cut lines; v0.1 must be independently demonstrable |
| Salesforce API changes break extraction | Medium | Pinned API version; extraction test matrix; version compatibility documented |
| Score is gamed or misread as a vanity metric | Medium | Composite never shown without sub-scores; gate rules; published rubric |
| Vendor relations damaged by competitive framing | Medium | Factual capability comparison only; no competitive criticism in any public artifact |
| Effort estimates are uncalibrated at launch | Medium | Ship with a published, explicitly provisional calibration table; refine from engagement data |

### 10.2 Constraint: intellectual property

The project must be developed on personal time and personal equipment, against a personally-owned Developer Edition org, with no employer or client data at any stage. The current employment agreement should be reviewed for assignment and moonlighting clauses **before the first commit**, since a public repository is a matter of public record and a dated one. This is not legal advice — it warrants an actual read of the agreement, and a lawyer's view if the clauses are ambiguous.

### 10.3 Open questions

1. **Naming.** `OrgIQ` is provisional. A name describing the function is generally better for open-source discovery than a brandable one.
2. **Telemetry design.** Opt-in anonymous scan telemetry would build the corpus needed for relative percentile scoring in v2. What is the minimum viable payload that is genuinely non-identifying?
3. **Rubric as a standard.** Is there value in proposing the readiness rubric as a community standard independent of this implementation?
4. **Managed package handling.** Components inside managed packages are partially opaque to the dependency API. What is the correct reporting posture — exclude, or include with a confidence penalty?
5. **Corpus licence compatibility.** Which public repositories can be redistributed as a test corpus versus referenced and fetched at test time? Affects whether the corpus ships in the repo or is assembled by a script.
6. **Prevalence measurement.** The public corpus cannot establish how common grounding defects are in long-lived enterprise orgs, and the fixture cannot either without circularity. What corpus or consent model would give an honest prevalence figure? Until this is answered, prevalence claims in client-facing material must be framed as observed-in-this-org rather than typical.
7. **Field-proven thresholds.** What adjudicated precision, across how many distinct orgs, justifies promotion to `field-proven`? Unanswerable until Tier 3 data exists; the ladder is designed so this can be set later without invalidating earlier scans.

*Resolved in v0.2:* evaluation prompt provenance (§6.3.5), seed target environment (§6.3.1), false-positive measurement method (§6.3.6).

*Resolved in v0.3:* rule/fixture sequencing (§6.3.7), fixture realism ceiling (§6.4), telemetry payload design (§6.4.2).

---

## 11. Roadmap Items

Work items by workstream. Items marked **†** were surfaced by the v0.2 seed-fixture work. Items marked **‡** were surfaced by the v0.3 validation-tier work. Items marked **§** were surfaced by the v0.5 source-mode work.

### SRC — Input modes

| ID | Item | Release | Depends on |
|---|---|---|---|
| SRC-1 § | SFDX project parser — metadata XML to canonical components | v0.1 | STORE-1 |
| SRC-2 § | Rule capability declaration in rule pack schema | v0.1 | RULE-1 |
| SRC-3 § | Capability resolver — runnable rule set from available signals | v0.1 | SRC-2 |
| SRC-4 § | Coverage reporting; partial-assessment marking and composite exclusion | v0.1 | SRC-3 |
| SRC-5 § | CLI mode selection — source, org, hybrid | v0.1 | SRC-1 |
| SRC-6 § | GitHub Action packaging for CI use | v0.2 | SRC-5 |
| SRC-7 § | Hybrid mode — source metadata with org enrichment | v0.3 | SRC-5, EXT-4 |
| SRC-8 § | Source-versus-org drift detection as a finding class | post-v1.0 | SRC-7 |

### VAL — Validation & rule maturity

| ID | Item | Release | Depends on |
|---|---|---|---|
| VAL-1 ‡ | Rule maturity field in rule pack schema; confidence capping | v0.1 | RULE-1 |
| VAL-2 ‡ | Cross-contamination grading — every rule scored against full corpus | v0.1 | SEED-5 |
| VAL-3 ‡ | Negative-case ratio enforcement in CI | v0.1 | SEED-6 |
| VAL-4 ‡ | Public corpus manifest; licence verification per source | v0.2 | — |
| VAL-5 ‡ | Corpus fetch-and-scan harness | v0.2 | VAL-4, SRC-1 |
| VAL-6 ‡ | Tier 2 promotion gate — `experimental` to `validated` | v0.2 | VAL-5 |
| VAL-7 ‡ | Local suppression file format and handling | v0.3 | EMIT-1 |
| VAL-8 ‡ | `orgiq review` adjudication command | v1.0 | EMIT-1 |
| VAL-9 ‡ | Suppression-rate precision proxy, computed locally | v1.0 | VAL-7 |
| VAL-10 ‡ | Opt-in adjudication telemetry; consent flow | post-v1.0 | VAL-8 |
| VAL-11 ‡ | Tier 3 promotion gate — `validated` to `field-proven` | post-v1.0 | VAL-10 |

### SEED — Seed environment & fixture

| ID | Item | Release | Depends on |
|---|---|---|---|
| SEED-1 † | Dev Hub setup; scratch org definition incl. audit-field enablement | v0.1 | — |
| SEED-2 † | Defect catalogue schema + D1 catalogue | v0.1 | SEED-1 |
| SEED-3 † | Metadata generator — catalogue to deployable source | v0.1 | SEED-2 |
| SEED-4 † | Expected-findings manifest generator | v0.1 | SEED-2 |
| SEED-5 † | Validation harness — precision, recall, F1 per rule | v0.1 | SEED-4, RULE-2 |
| SEED-6 † | CI integration; precision gate fails build on regression | v0.1 | SEED-5 |
| SEED-7 † | Record data generator with distribution shapes | v0.5 | SEED-1 |
| SEED-8 † | Near-match duplicate generator | v0.5 | SEED-7 |
| SEED-9 † | Eval prompt sets — Account, Contact | v0.2 | SEED-3 |
| SEED-10 † | Defect catalogue extensions for D3, D4, D5 | v0.3–v0.4 | SEED-2 |

### EXT — Extraction

| ID | Item | Release |
|---|---|---|
| EXT-1 | `sf` CLI wrapper, auth, read-only permission set | v0.1 |
| EXT-2 | Metadata API component inventory | v0.1 |
| EXT-3 | Tooling API — `EntityDefinition`, `FieldDefinition` | v0.1 |
| EXT-4 | Tooling API — `MetadataComponentDependency` graph | v0.1 |
| EXT-5 | Report and dashboard field-reference extraction | v0.1 |
| EXT-6 | Optimizer and Health Check ingestion | v0.3 |
| EXT-7 | Code Analyzer invocation and result ingestion | v0.4 |
| EXT-8 | Setup Audit Trail ingestion | v0.3 |
| EXT-9 | Record data sampling for D2 | v0.5 |
| EXT-10 | Licensed platform export adapters | post-v1.0 |

### STORE — Canonical store

| ID | Item | Release |
|---|---|---|
| STORE-1 | DuckDB schema — scan, component, dependency_edge, usage_signal, finding | v0.1 |
| STORE-2 | NetworkX graph load; blast radius computation | v0.1 |
| STORE-3 | Delta detection via `LastModifiedDate` | v1.0 |
| STORE-4 | Scan history and trend queries | v1.0 |

### RULE — Detection

| ID | Item | Release |
|---|---|---|
| RULE-1 | YAML rule pack schema and loader | v0.1 |
| RULE-2 | D1 Grounding Quality pack (~15 rules) | v0.1 |
| RULE-3 | Confidence assignment framework | v0.1 |
| RULE-4 | D5 Automation Collision pack | v0.3 |
| RULE-5 | D4 Permission Blast Radius pack | v0.3 |
| RULE-6 | D3 Action Surface pack | v0.4 |
| RULE-7 | D2 Data Foundation pack | v0.5 |
| RULE-8 | Rule authoring guide | v1.0 |

### SCORE — Rubric & scoring

| ID | Item | Release |
|---|---|---|
| SCORE-1 | Rubric YAML schema, semver versioning | v0.1 |
| SCORE-2 | Per-dimension scoring | v0.1 |
| SCORE-3 | Composite + weighting profiles (`default`, `bfsi`) | v1.0 |
| SCORE-4 | Gate rules and cap reporting | v1.0 |
| SCORE-5 | Readiness bands | v1.0 |
| SCORE-6 | Graceful degradation — `not assessed` handling | v0.3 |

### GRND — Grounding & selection economics

| ID | Item | Release | Depends on |
|---|---|---|---|
| GRND-1 | Metadata payload tokeniser | v0.2 | — |
| GRND-2 | Context payload computation, grounding and action surfaces | v0.2 | GRND-1 |
| GRND-3 | Semantic density metric | v0.2 | GRND-1 |
| GRND-4 | Selection precision harness runner | v0.2 | SEED-9 |
| GRND-5 | Accept/reject verdict logic | v0.2 | GRND-4 |
| GRND-6 | Cost model via turns-to-resolution | v0.2 | GRND-2 |
| GRND-7 | Experiment — rule correctness across public corpus (**executed, §13**) | v0.2 | SRC-1, VAL-4 |
| GRND-8 | Experiment — mis-retrieval demonstration against fixture | v0.2 | SEED-9, GRND-4 |
| GRND-9 | Prevalence measurement design — corpus that represents long-lived enterprise orgs | v0.3 | GRND-7 |

### EMIT — Reporting & backlog

| ID | Item | Release |
|---|---|---|
| EMIT-1 | Finding schema; deterministic `finding_id` | v0.1 |
| EMIT-2 | Threshold-gated backlog conversion | v0.1 |
| EMIT-3 | Jira CSV emitter | v0.1 |
| EMIT-4 | Static HTML report | v0.1 |
| EMIT-5 | Epic clustering | v0.3 |
| EMIT-6 | ADO, JSON, Markdown emitters | v0.3 |
| EMIT-7 | Effort calibration table (provisional) | v0.3 |
| EMIT-8 | Idempotent re-scan — update, close, create | v1.0 |
| EMIT-9 | Burn-down and trend reporting | v1.0 |

### LLM — Enrichment tier

| ID | Item | Release |
|---|---|---|
| LLM-1 | Provider abstraction incl. local model support | v0.3 |
| LLM-2 | Fingerprint cache | v0.3 |
| LLM-3 | Apex symbol table serialiser | v0.4 |
| LLM-4 | Tiered model routing | v0.3 |
| LLM-5 | Token budget tracking and reporting | v0.3 |
| LLM-6 | Narrative and clustering prompts | v0.3 |

### OSS — Open source infrastructure

| ID | Item | Release |
|---|---|---|
| OSS-1 | Apache 2.0 licence, NOTICE, code of conduct | v0.1 |
| OSS-2 | README incl. factual capability comparison | v0.1 |
| OSS-3 | Contribution guide; rule pack extension points documented | v0.1 |
| OSS-4 | Rubric RFC process | v1.0 |
| OSS-5 | Documentation site | v1.0 |
| OSS-6 | Opt-in telemetry design | post-v1.0 |

### SEC — Security posture

| ID | Item | Release |
|---|---|---|
| SEC-1 | Read-only permission set definition, shipped in repo | v0.1 |
| SEC-2 | Local-first artifact handling; no default egress | v0.1 |
| SEC-3 | LLM-optional verification — full pipeline with no LLM | v0.1 |
| SEC-4 | Data residency documentation | v0.3 |

### 11.1 v0.1 critical path

```
EXT-1 → EXT-2, EXT-3 → STORE-1 → RULE-1 → EMIT-1 → EMIT-2 → EMIT-3, EMIT-4
                                    ↓
                    SEED-1 → SEED-2 → SEED-3, SEED-4 → SEED-5 → SEED-6
                                    ↓                     ↑
                                 RULE-2 ──────────────────┘
                                (defect-first, per §6.3.7)
```

RULE-2 is not a single block of work preceding validation. Each of the ~15 D1 rules is authored defect-first: catalogue entry with negative cases, then rule, then grade. RULE-2 and SEED-2 therefore interleave rule by rule rather than running as sequential phases.

The distinction matters because building the fixture after the rule pack means every rule/fixture disagreement is ambiguous — you cannot tell which side is wrong, and the precision problem surfaces at the point where it is most expensive to diagnose.

### 11.2 OSS-6 superseded

Telemetry design was listed as a post-v1.0 open item in v0.2. It is now specified in §6.4.2 and tracked as VAL-10, with the payload defined rather than deferred.

---

## 12. Objectives & Staging

This project serves three objectives. They are pursued in sequence, not in parallel, because each produces the input the next requires.

### 12.1 The three objectives

| | Objective | Beneficiary |
|---|---|---|
| **O-A** | Demonstrate architectural and product judgment through a shipped, inspectable artifact | Author |
| **O-B** | Establish a maintained open-source assessment tool with an external contributor base | Community |
| **O-C** | Underpin a repeatable Centre of Excellence assessment and remediation service | Employer / clients |

### 12.2 Why they reinforce rather than compete

O-A produces the working slice and the specification that O-B needs in order to exist as a project rather than an intention.

O-B produces the rule corpus, the contributor-authored defect catalogue (§6.3.7), and the public-corpus validation that O-C needs in order to make defensible claims to a paying client.

O-C produces the adjudicated field evidence that O-B cannot generate on its own. **This is the closing link.** Tier 3 validation (§6.4.1) requires outcomes from real scans of real orgs, which only arise from commercial engagements. Without O-C, the rule maturity ladder is permanently capped at `validated` and the tool can never honestly claim `field-proven` status for any rule.

The commercial objective is therefore not an extraction from the open-source project. It is the only mechanism by which the open-source project's central validation problem gets solved.

### 12.3 Stage gates

**Stage 1 — O-A.** This specification, plus v0.1 shipped against the seed fixture, plus the grounding economics demonstration.
*Gate to Stage 2:* v0.1 passes the fixture at declared precision; repository public with licence, README, and contribution guide.

**Stage 2 — O-B.** v0.2 through v1.0. Public corpus validation, rule packs across all five dimensions, contribution process operating.
*Gate to Stage 3:* a majority of shipped rules at `validated` maturity; at least one externally authored contribution merged.

**Stage 3 — O-C.** Engagement playbooks, effort calibration from real scans, adjudication telemetry, remediation runbooks.
*Requires:* organisational context, client access, and delivery capacity. Cannot begin before those exist.

### 12.4 Ownership and IP structure

The staging above only works under one ownership arrangement: **personal copyright, released under Apache 2.0.**

This is deliberate and load-bearing. A permissive licence held personally means an employer can adopt, deploy, and build on the tool without any assignment of rights, while the author retains the asset across employment changes. The commercial layer enumerated in §9.3 — playbooks, runbooks, calibration data, benchmarks — is retained separately and is not published.

The alternative arrangements both fail. Work assigned to an employer cannot be open sourced without their consent and cannot follow the author. Work built on employer time or equipment may be assignable regardless of where it is published, and a public repository is a dated public record of exactly when it was built.

**This makes the employment agreement review in §10.2 a Stage 1 blocker rather than a caution.** It must be resolved before the first commit, not before launch.

### 12.5 Constraints across all stages

- No Stage 2 work before v0.1 ships. O-A is the gate for both other objectives; if it does not complete, neither of them begins.
- No commercial artifacts in the public repository at any stage.
- No client data, employer metadata, or engagement-derived content in the fixture or corpus at any stage — including Stage 3, where the temptation is highest and the telemetry design in §6.4.2 exists specifically to remove the need.

---

---

## 13. Validation Evidence

A spike was executed before committing to the v0.1 build, to test whether the D1 rules find anything meaningful on real metadata. Implementation in Appendix C.

### 13.1 Method

Source mode only. Four rules, later five, run against three public SFDX repositories with no org connection, no LLM, and no dependencies beyond the Python standard library. Deterministic throughout.

### 13.2 Corpus and results

| Repository | Fields | Objects | Description coverage |
|---|---:|---:|---:|
| NPSP (mature managed package) | 765 | 62 | 77.6% |
| dreamhouse-lwc (sample app) | 32 | 4 | 0.0% |
| ebikes-lwc (sample app) | 31 | 4 | 0.0% |

Findings on NPSP, as a proportion of fields:

| Rule | Findings | % |
|---|---:|---:|
| D1.MISSING_DESCRIPTION | 171 | 22.4% |
| D1.CRYPTIC_API_NAME | 45 | 5.9% |
| D1.NUMBERED_FAMILY | 34 | 4.4% |
| D1.LOW_INFO_DESCRIPTION | 6 | 0.8% |
| D1.SEMANTIC_DUPLICATE | 4 | 0.5% |

### 13.3 Defects found in the rules themselves

The spike's primary value was catching its own errors. Three iterations were required.

**Semantic operators misclassified as encoding markers.** The first implementation stripped words like *number*, *total*, *date*, and *amount* as representation markers before comparison, on the theory that `SegmentCode__c` and `Segment__c` mean the same thing. They do — but the same stripping made `Date_Field__c` and `Amount_Field__c` identical, producing a **High-confidence false positive**, the worst outcome the confidence model in §4.5 exists to prevent. These words look like type markers and are in fact semantic operators: stripping them makes a count and a sum indistinguishable.

*Correction:* `TYPE_MARKERS` narrowed to genuine encoding words only, and duplicate detection split into two tiers — full-token comparison at High confidence, marker-stripped comparison at Low confidence with a guard against degenerate or entirely generic residuals.

**Numbered families misread as duplication.** `Contact1Imported__c` and `Contact2Imported__c` were flagged as semantic duplicates. They are a repeating group — a legitimate, common Salesforce pattern.

*Correction:* a new rule. **D1.NUMBERED_FAMILY** is a real grounding problem (N near-identical retrieval candidates, typically sharing identical descriptions) but a distinct one from semantic collision. This rule did not exist in the specification before the spike surfaced it.

**Vowel-less token heuristic too crude.** `Sync` was flagged as an unreadable abbreviation because `y` was not treated as a vowel.

Semantic duplicate findings fell **59 → 38 → 4** across these corrections. The naive implementation was approximately 93% false positives.

### 13.4 Quality of surviving findings

Of the four remaining semantic duplicates on NPSP, three are genuine:

- `Payment_Gateway_Payment_ID__c` / `Payment_Gateway_ID__c` — precisely the §5.2 failure mode. A retriever asked for the payment gateway identifier chooses one silently.
- `Recurring_Donation_Elevate_Recurring_ID__c` / `Donation_Elevate_Recurring_ID__c`
- `Rollups_AcctContactSoftCredit_Batch_Size__c` / `Rollups_Account_Soft_Credit_Batch_Size__c` — detected only because abbreviation expansion resolved `Acct` to `Account`.

One is a false positive: `MailingStreet__c` / `MailingStreet2__c` is an address-line pattern the family detector failed to group. Approximate precision 75% on a small sample.

### 13.5 Implications

**The rules work, and defect-first authoring works.** Three real defects were caught in an afternoon by grading rules against real metadata. §6.3.7's discipline is validated in miniature.

**The public corpus is bimodal, and neither mode is the target.** Curated packages are maintained under code review; sample applications are not maintained at all. NPSP at 77.6% description coverage and 0.5% semantic duplication has *good* metadata. The sample apps at 0% coverage have none. A fifteen-year-old enterprise org shaped by admin-driven change resembles neither.

**Prevalence remains unmeasured, and the thesis depends on it.** §1 asserts that orgs are full of ambiguous, undocumented fields. That is untested. The public corpus will understate it; the fixture cannot test it without circularity. Recorded as open question 6 in §10.3, with GRND-9 added to design an honest measurement.

**Client-facing framing must reflect this.** Until prevalence is measured, findings are reported as *observed in this org*, never as *typical*.


---

## Appendix A — Glossary

| Term | Definition |
|---|---|
| **Grounding payload** | The schema context supplied to a language model so it can reason about an object |
| **Grounding Efficiency Ratio** | Optimised grounding tokens divided by raw grounding tokens |
| **Semantic Density** | Proportion of grounding tokens carrying disambiguating information |
| **Blast radius** | Count of components dependent on a given component |
| **Gate rule** | A rule capping the composite score when a critical condition is met |
| **Rule pack** | A versioned YAML collection of deterministic detection rules |
| **Delta scan** | A scan processing only metadata modified since the previous scan |

## Appendix B — References

*[To be completed — Salesforce Metadata API, Tooling API `MetadataComponentDependency`, Code Analyzer, Optimizer, Security Health Check documentation]*

---

## Appendix C — Spike Implementation

Source mode, five D1 rules, standard library only. Executed against the corpus in §13.

```python
#!/usr/bin/env python3
"""
OrgIQ spike — D1 Grounding Quality, source mode.

Parses an SFDX project directory and runs four deterministic D1 rules.
No org connection, no LLM, no dependencies beyond the standard library.

Purpose: test whether the D1 rules find anything interesting on real
metadata before committing to the full v0.1 build. Also produces the
first data point for GRND-7 (ambiguity prevalence).
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field as dc_field
from pathlib import Path

NS = {"sf": "http://soap.sforce.com/2006/04/metadata"}

# ---------------------------------------------------------------- model

@dataclass
class Field:
    object_name: str
    api_name: str
    label: str
    type: str
    description: str
    help_text: str
    path: str

    @property
    def stem(self) -> str:
        return re.sub(r"__(c|mdt|e)$", "", self.api_name, flags=re.I)


@dataclass
class Finding:
    rule_id: str
    dimension: str
    severity: str
    confidence: str
    component: str
    evidence: str
    detail: str = ""


# ------------------------------------------------------------- parsing

def parse_project(root: Path) -> list[Field]:
    fields = []
    for p in root.rglob("*.field-meta.xml"):
        try:
            tree = ET.parse(p)
        except ET.ParseError:
            continue
        r = tree.getroot()

        def get(tag: str) -> str:
            el = r.find(f"sf:{tag}", NS)
            return (el.text or "").strip() if el is not None and el.text else ""

        # .../objects/<Object>/fields/<Field>.field-meta.xml
        obj = "Unknown"
        parts = p.parts
        if "objects" in parts:
            i = parts.index("objects")
            if i + 1 < len(parts):
                obj = parts[i + 1]

        fields.append(Field(
            object_name=obj,
            api_name=get("fullName") or p.stem.replace(".field-meta", ""),
            label=get("label"),
            type=get("type"),
            description=get("description"),
            help_text=get("inlineHelpText"),
            path=str(p),
        ))
    return fields


# --------------------------------------------------------- normalisation

ABBREV = {
    "acct": "account", "amt": "amount", "addr": "address", "adj": "adjustment",
    "agmt": "agreement", "apt": "appointment", "attr": "attribute", "auth": "authorisation",
    "avg": "average", "bal": "balance", "cat": "category", "cd": "code",
    "cfg": "configuration", "chk": "check", "cnt": "count", "cntct": "contact",
    "co": "company", "cmp": "campaign", "comm": "communication", "conf": "confirmation",
    "cust": "customer", "dept": "department", "desc": "description", "dt": "date",
    "dtl": "detail", "dup": "duplicate", "eff": "effective", "elig": "eligibility",
    "emp": "employee", "err": "error", "est": "estimate", "exp": "expiration",
    "ext": "external", "flg": "flag", "freq": "frequency", "grp": "group",
    "hist": "history", "id": "identifier", "img": "image", "ind": "indicator",
    "info": "information", "init": "initial", "inv": "invoice", "loc": "location",
    "max": "maximum", "min": "minimum", "mgr": "manager", "mo": "month",
    "num": "number", "nbr": "number", "obj": "object", "opp": "opportunity",
    "org": "organisation", "pct": "percent", "pmt": "payment", "prev": "previous",
    "prod": "product", "prof": "profile", "qty": "quantity", "ref": "reference",
    "req": "required", "rev": "revenue", "seg": "segment", "seq": "sequence",
    "src": "source", "stat": "status", "sub": "subscription", "svc": "service",
    "tot": "total", "trans": "transaction", "txn": "transaction", "typ": "type",
    "usr": "user", "val": "value", "ver": "version", "yr": "year",
}

# Tokens describing how a value is ENCODED, not what it MEANS.
# Deliberately narrow: words like number/total/date/amount look like type
# markers but are semantic operators — stripping them makes a count and a
# sum look identical, which is a false-positive generator.
TYPE_MARKERS = {"code", "identifier", "text", "flag", "indicator", "key"}

# Words too generic to establish shared meaning on their own.
GENERIC = {"field", "value", "name", "type", "status", "data", "info",
           "record", "item", "detail", "setting", "option"}

STOP = {"the", "a", "an", "of", "for", "to", "is", "in", "on", "and", "or"}


def tokenise(s: str) -> list[str]:
    s = re.sub(r"__(c|mdt|e)$", "", s, flags=re.I)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    s = re.sub(r"[^A-Za-z0-9]+", " ", s)
    return [t.lower() for t in s.split() if t]


def normalise(s: str) -> frozenset[str]:
    out = set()
    for t in tokenise(s):
        t = re.sub(r"\d+$", "", t)
        if not t or t in STOP:
            continue
        t = ABBREV.get(t, t)
        if len(t) > 3 and t.endswith("s"):
            t = t[:-1]
        out.add(t)
    return frozenset(out)


def meaning(s: str) -> frozenset[str]:
    """Normalised tokens with representation markers removed."""
    return frozenset(normalise(s) - TYPE_MARKERS)


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ------------------------------------------------------------- rules

VOWELS = set("aeiouy")


def rule_missing_description(fields: list[Field]) -> list[Finding]:
    out = []
    for f in fields:
        if not f.description.strip():
            out.append(Finding(
                "D1.MISSING_DESCRIPTION", "D1", "Medium", "High",
                f"{f.object_name}.{f.api_name}",
                "no <description> element",
                f"label={f.label!r}",
            ))
    return out


def rule_low_information_description(fields: list[Field]) -> list[Finding]:
    """A description that restates the label carries no disambiguating
    information — it is payload with no retrieval benefit (PRD §5.5)."""
    out = []
    for f in fields:
        d = f.description.strip()
        if not d:
            continue
        dn, ln = normalise(d), normalise(f.label or f.api_name)
        if not dn:
            continue
        # description adds no tokens beyond the label
        if dn <= ln or jaccard(dn, ln) >= 0.85:
            out.append(Finding(
                "D1.LOW_INFO_DESCRIPTION", "D1", "Low", "Medium",
                f"{f.object_name}.{f.api_name}",
                f"description restates label",
                f"label={f.label!r} desc={d[:60]!r}",
            ))
    return out


def rule_cryptic_api_name(fields: list[Field]) -> list[Finding]:
    out = []
    for f in fields:
        stem, toks = f.stem, tokenise(f.api_name)
        reasons = []
        if len(stem) <= 3:
            reasons.append("very short name")
        if re.search(r"\d$", stem) and len(toks) <= 2:
            reasons.append("sequence-numbered name")
        unknown = [t for t in toks
                   if len(t) <= 4 and t not in ABBREV and not (set(t) & VOWELS)]
        if unknown:
            reasons.append(f"vowel-less token(s): {','.join(unknown)}")
        abbrevs = [t for t in toks if t in ABBREV]
        if abbrevs and not f.description.strip():
            reasons.append(f"undocumented abbreviation(s): {','.join(abbrevs)}")
        if reasons:
            out.append(Finding(
                "D1.CRYPTIC_API_NAME", "D1", "Medium",
                "High" if len(reasons) > 1 else "Medium",
                f"{f.object_name}.{f.api_name}",
                "; ".join(reasons),
                f"label={f.label!r}",
            ))
    return out


def _family_key(name: str) -> str:
    """Name with embedded digits removed. Contact1Imported__c and
    Contact2Imported__c share a key; they are a numbered family, not
    a semantic duplicate."""
    return re.sub(r"\d+", "#", re.sub(r"__(c|mdt|e)$", "", name, flags=re.I)).lower()


def rule_numbered_family(fields: list[Field], min_size: int = 2) -> list[Finding]:
    """Repeating numbered field groups. Legitimate as a design choice, but a
    real grounding problem: N near-identical candidates for a retriever to
    choose between, usually with identical descriptions."""
    out = []
    by_obj = defaultdict(lambda: defaultdict(list))
    for f in fields:
        k = _family_key(f.api_name)
        if "#" in k:
            by_obj[f.object_name][k].append(f)
    for obj, fams in by_obj.items():
        for k, fs in fams.items():
            if len(fs) < min_size:
                continue
            out.append(Finding(
                "D1.NUMBERED_FAMILY", "D1", "Medium",
                "High" if len(fs) >= 3 else "Medium",
                f"{obj} [{len(fs)} fields]",
                f"repeating group `{k}`",
                " | ".join(sorted(f.api_name for f in fs)[:6]),
            ))
    return out


def rule_semantic_duplicate(fields: list[Field], threshold: float = 0.85) -> list[Finding]:
    """Two-tier. Tier 1 compares full normalised tokens — a match there is a
    strong signal. Tier 2 compares after stripping encoding markers, which is
    weaker and emits at Low confidence only, and never where the residual
    meaning is degenerate or entirely generic."""
    out = []
    by_obj = defaultdict(list)
    for f in fields:
        by_obj[f.object_name].append(f)

    for obj, fs in by_obj.items():
        sigs = []
        for f in fs:
            full = normalise(f.api_name) | normalise(f.label)
            stripped = meaning(f.api_name) | meaning(f.label)
            if full:
                sigs.append((f, full, stripped))

        seen = set()
        for i in range(len(sigs)):
            fa, fulla, stripa = sigs[i]
            if fa.api_name in seen:
                continue
            tier1, tier2 = [], []
            for j in range(i + 1, len(sigs)):
                fb, fullb, stripb = sigs[j]
                if fb.api_name in seen:
                    continue
                if _family_key(fa.api_name) == _family_key(fb.api_name):
                    continue  # numbered family, handled separately
                if jaccard(fulla, fullb) >= threshold:
                    tier1.append(fb)
                elif (jaccard(stripa, stripb) >= threshold
                      and len(stripa) >= 2
                      and not (stripa <= GENERIC)):
                    tier2.append(fb)

            for group, tier in ((tier1, 1), (tier2, 2)):
                if not group:
                    continue
                names = [fa.api_name] + [g.api_name for g in group]
                for n in names:
                    seen.add(n)
                same_type = len({fa.type} | {g.type for g in group}) == 1
                shared = sorted(fulla if tier == 1 else stripa)
                if tier == 1:
                    conf = "High" if same_type else "Medium"
                    sev = "High" if same_type else "Medium"
                    ev = f"near-identical naming: {{{', '.join(shared)}}}"
                else:
                    conf = "Low"
                    sev = "Medium"
                    ev = f"possible shared meaning after normalisation: {{{', '.join(shared)}}}"
                out.append(Finding(
                    "D1.SEMANTIC_DUPLICATE", "D1", sev, conf,
                    f"{obj} [{len(names)} fields]", ev, " | ".join(names),
                ))
    return out


RULES = [
    ("D1.MISSING_DESCRIPTION", rule_missing_description),
    ("D1.LOW_INFO_DESCRIPTION", rule_low_information_description),
    ("D1.CRYPTIC_API_NAME", rule_cryptic_api_name),
    ("D1.NUMBERED_FAMILY", rule_numbered_family),
    ("D1.SEMANTIC_DUPLICATE", rule_semantic_duplicate),
]


# ------------------------------------------------------------- report

def report(name: str, fields: list[Field], findings: list[Finding], show: int) -> str:
    L = []
    L.append(f"# OrgIQ spike — {name}\n")
    L.append(f"Fields parsed: **{len(fields)}** across "
             f"**{len({f.object_name for f in fields})}** objects\n")

    by_rule = defaultdict(list)
    for f in findings:
        by_rule[f.rule_id].append(f)

    L.append("## Summary\n")
    L.append("| Rule | Findings | % of fields |")
    L.append("|---|---:|---:|")
    for rid, _ in RULES:
        n = len(by_rule[rid])
        pct = (n / len(fields) * 100) if fields else 0
        L.append(f"| {rid} | {n} | {pct:.1f}% |")
    L.append("")

    described = sum(1 for f in fields if f.description.strip())
    low_info = len(by_rule["D1.LOW_INFO_DESCRIPTION"])
    L.append(f"Description coverage: **{described}/{len(fields)} "
             f"({described/len(fields)*100:.1f}%)** — of which "
             f"**{low_info}** carry no information beyond the label, "
             f"so effective coverage is "
             f"**{(described-low_info)/len(fields)*100:.1f}%**\n")

    for rid, _ in RULES:
        fs = by_rule[rid]
        if not fs:
            continue
        L.append(f"## {rid} ({len(fs)})\n")
        L.append("| Component | Confidence | Evidence |")
        L.append("|---|---|---|")
        for f in fs[:show]:
            ev = f.evidence if not f.detail else f"{f.evidence} — `{f.detail[:90]}`"
            L.append(f"| `{f.component}` | {f.confidence} | {ev} |")
        if len(fs) > show:
            L.append(f"| … | | *{len(fs)-show} more* |")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="OrgIQ spike — D1 source mode")
    ap.add_argument("path")
    ap.add_argument("--name", default=None)
    ap.add_argument("--show", type=int, default=10)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    root = Path(a.path)
    if not root.exists():
        sys.exit(f"not found: {root}")

    fields = parse_project(root)
    if not fields:
        sys.exit("no field metadata found")

    findings = []
    for _, fn in RULES:
        findings.extend(fn(fields))

    md = report(a.name or root.name, fields, findings, a.show)
    if a.out:
        Path(a.out).write_text(md)
        print(f"wrote {a.out}")
    else:
        print(md)


if __name__ == "__main__":
    main()
```
