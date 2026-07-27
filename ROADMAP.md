# OrgIQ — product roadmap

**Status:** draft for review · written 2026-07-27 · supersedes the workstream list in PRD §11

This is a product roadmap, not a backlog. It sequences by dependency and risk and
names the decisions that have to be made rather than the tasks that follow from
them. Every number in it was measured against the code or the org during the
audit that prompted it; assumptions are marked as such.

---

## Where the product actually is

Built and verified: 31 rules across five dimensions plus cross-org drift; source
mode and org mode both real, with org mode's record probes the only reason D2 can
be assessed at all; ingestion of Code Analyzer, Health Check and Optimizer with
provenance and overlap merging; persona capability surfaces; finding survival;
an evidence-responsive effort model; the rubric extracted to data; tenant
isolation with a Private default; a scheduled scan that fails on regression; and
a backlog whose every ticket carries a remediation, acceptance criteria and an
owning role. 283 tests. The dashboard is live.

What that adds up to is a **working prototype with an unmeasured error rate.**

The first time the rules ever ran against real Salesforce metadata — this
repository's own org, during the audit — they produced a High-severity ticket
telling someone to merge 101 records that must not be merged, on an object with
zero duplicates. It was fixed. The point is not the bug; it is that **one run
against one small real org was enough to find it**, and there has never been a
second org.

That single fact sets the order of everything below.

---

## Sequencing thesis

> **Credibility before distribution.**

Every rule's false-positive rate is unknown. An ISV's reputation dies on false
positives, not on missing features — a practitioner who is told to merge good
records once will not open the next report. Distribution multiplies whatever the
error rate is by the number of installs, so packaging an unvalidated rule pack is
the one sequencing mistake that cannot be walked back.

Nothing downstream is blocked by packaging. Rules can be validated, the output
made to survive real volume, and effort calibrated, all before a single line of
Apex exists. So the Apex port — the largest single cost in this plan — comes
last, and only if the distribution decision calls for it.

---

## Phase 0 — Unblock (days, one person)

Small, unglamorous, and blocking things that are already built.

| Item | Why it blocks | State |
|---|---|---|
| Salesforce org keep-alive | The org holds every scan and is deleted after ~45 days without a login. The workflow is written and the setup script now refuses to store a dead token, but the token expired and Salesforce will not issue a new one to a script. **Needs one browser login.** | Red |
| Rotate the GitHub PAT | Shared in plaintext during development | Open |
| Prove the live-mode login | All eleven server-side preconditions pass (`scripts/verify-live-mode.py`). What has never been observed is a human completing the browser round trip — and a second person cannot try, because nobody else has a user in the org. | Unproven |

**Done when:** the keep-alive is green, and one person other than the author has
signed in and seen live data.

---

## Phase 1 — Trustworthy (the spine)

**Goal: state a false-positive rate with a number behind it.**

Today the PRD describes a rule maturity ladder and a three-tier validation model.
Neither has been exercised: every rule ships as `experimental` and no rule has a
measured precision. This phase makes the ladder real.

**The route exists.** `salesforce/precision_kit.py` is the same shape as the
effort calibration kit: a stratified worksheet, an import matched on the External
ID the backlog already carries, and a per-rule report. `Verdict__c` answers "was
this correct" and is deliberately separate from `Status__c`, which answers "will
anyone act on it" — a rule can be perfectly precise and still not worth shipping.
Measured precision is written back into `rubric.json`, which is where the scanner
reads `Rule_Maturity__c` from, so scoring findings is the only thing that moves a
rule up the ladder. What is missing is not plumbing. It is orgs.

1. **Assemble a validation corpus.** Ten to twenty real orgs across industries and
   ages — partner sandboxes, Trailhead playgrounds, friendly customers, the
   consultancy's own estate. Source mode alone gets most of it; org mode where
   permission allows.
2. **Score every finding by hand, once.** Precision per rule, not overall — a pack
   that is 90% precise on average can be 40% precise on the rule that fires most.
3. **Promote, demote, or withdraw each rule** on that evidence. A rule under its
   precision floor either gets a narrower trigger, a lower confidence, or leaves
   the pack. `Rule_Maturity__c` starts meaning something.
4. **Publish the number.** "31 rules, precision measured on 18 orgs, median 0.87,
   worst rule 0.61 and labelled experimental" is a sentence no competitor can say
   casually, and it is the thing that makes the backlog worth importing.

**Risk this addresses:** the largest one. Two of the three defects found in the
first real-org run were rules being confidently wrong.

**Done when:** every rule carries a measured precision and the maturity label
reflects it.

---

## Phase 2 — Survivable at real volume

**Goal: the output stays usable on an org 26× bigger than the demo.**

Measured during the audit, on one synthetic enterprise-shaped org (3,213 fields):

| | Demo | One real org | One estate (8 orgs) |
|---|---|---|---|
| Findings | 103/org | **~2,690** | ~21,500 |
| Tickets after the §4.6 gate | — | ~2,500 (**93% pass**) | **~20,000** |
| Findings-org storage | 3 MB | — | **~42 MB** (DE limit 5 MB) |
| Dashboard payload | 1.5 MB | — | **~55 MB** |

Three consequences, in order of severity:

1. **The emission gate does not do its job at scale.** Its stated purpose is to
   prevent "a four-thousand-ticket dump nobody imports"; at real volume it passes
   93% and produces twenty thousand. Severity and confidence do not discriminate
   when most findings genuinely are Medium-or-above. The gate needs a second
   axis — a volume budget, a per-epic cap, a "what would you fix this quarter"
   view — and that is **a rubric decision, not a bug fix**.
2. **The findings store outgrows a Developer Edition org** at one estate. See the
   decision below.
3. **The dashboard payload becomes a 55 MB download.** Rendering itself survives
   (2,690 rows, 898 ms, 30k DOM nodes — measured), so this is a delivery problem,
   not a UI one: pre-aggregate, paginate the bundle, or serve from the org.

**Done when:** a real 3,000-field org produces a backlog a team agrees is
importable, and the dashboard opens on it in under two seconds.

---

## Phase 3 — Costed

**Goal: effort points that survive being challenged in front of a client.**

There are 1,222 tickets in the demo, each carrying story points, under a model
stamped `effort-0.2-uncalibrated`. The routes for real numbers exist and are
tested — `salesforce/calibration_kit.py` takes actuals from wherever work is
tracked, expert estimates from a worksheet, and survival from the scans already
held — and **not one of them has been used.**

- **Cheapest first:** one practitioner, one afternoon, the stratified worksheet.
  Moves the model from *uncalibrated* to *elicited* and, more useful, says
  per-rule where our judgement and theirs diverge.
- **Then actuals**, as the first remediation tickets close. Thirty samples is the
  stated floor before the model moves.
- **Survival is already free** and needs nobody — but it only accumulates if
  Phase 0's cadence is running.

**Done when:** the effort model version no longer says "uncalibrated".

---

## Phase 4 — Distributable

**Goal: someone other than us can run it.**

This is where the branching decision sits, and it should not be made before
Phase 1 reports a precision number.

**The decision: what is OrgIQ delivered as?**

| Option | What it needs | What it buys |
|---|---|---|
| **A. Consultant's tool** (closest to today) | Packaging the CLI, a report a client keeps, an engagement playbook | Revenue now, through services. No platform risk. Does not scale past the people running it. |
| **B. Managed package** (the AppExchange path) | **Port the engine to Apex** — the largest cost in this plan. Namespace, security review, per-tenant operations, an upgrade story for the rubric. | Distribution. Recurring revenue. The thing an ISV is built for. |
| **C. Hosted service** | Multi-tenant infrastructure, per-customer auth, the security questionnaire that comes with holding customer metadata | Distribution without the Apex port. Shifts the burden to us: we hold the data, so isolation becomes an ops problem rather than a schema one. |

The rubric extraction already halved B's cost — a port carries the engine only,
because `rubric.json` goes with it unchanged. The engine port itself has not
started, and today there are zero Apex classes, an empty namespace, and a
hardcoded client id and org URL in the dashboard config.

**Recommendation:** hold this decision open until Phase 1 produces a number, then
choose. If precision is high, B justifies its cost. If it is uneven across rules,
A lets a practitioner apply judgement the package cannot.

---

## Running alongside

- **Rule pack growth** — driven by what the validation corpus turns up, not by a
  list written in advance. Every new rule enters at `experimental` with a
  remediation playbook, or `tests/test_rubric.py` fails.
- **Cadence** — the scheduled scan and its regression gate exist; they need real
  targets, which need Phase 0.
- **Provenance discipline** — the habit that has caught the most: a signal that
  could not be collected is reported as unavailable, never defaulted. Every new
  probe inherits it.

---

## Explicitly not doing

- **An LLM enrichment tier.** Specified in PRD §5.8, no code, and nothing in the
  product depends on it. The scanner is standard-library-only and every "token"
  it reports is a deterministic estimate. Adding a model would put a cost and a
  non-determinism into a tool whose whole claim is that its findings are
  reproducible.
- **Rebuilding what the platform gives free.** Code Analyzer, Health Check and
  Optimizer are ingested, deduplicated against our own rules, and excluded from
  the dimension scores. That is a scope commitment, not an interim state.
- **More demo enterprises.** Two is enough to prove isolation and drift. What the
  demo lacks is *scale*, not variety, and Phase 2 addresses that.

---

## Open decisions

1. **Where does the findings store live at real volume?** A Developer Edition org
   holds 5 MB and one estate needs ~42 MB. Options: the customer's own org (they
   own the storage and the data), a hosted store (we do), or archive-on-write
   keeping only the newest N scans — which would cost the survival and burn-down
   features that depend on history. **Blocks Phase 2.**
2. **Who owns the rubric?** If each customer tunes `rubric.json`, cross-customer
   benchmarking becomes impossible and every score is local. If we own it, it is
   a benchmark and a differentiator, but a practitioner who disagrees has no
   recourse. A middle path — our defaults, their overrides, both recorded on the
   scan — is more work than either.
3. **Does D2 justify org mode as a requirement?** D2 is assessable only with
   record probes, so a source-only customer gets four dimensions out of five.
   Either that is stated plainly as a tier, or org mode becomes mandatory and the
   product needs org credentials from day one.

---

## How we would know it is working

| Phase | The measure |
|---|---|
| 0 | Someone other than the author has seen live data |
| 1 | A published per-rule precision, measured on ≥10 real orgs |
| 2 | A 3,000-field org produces a backlog a team calls importable |
| 3 | `MODEL_VERSION` no longer contains the word *uncalibrated* |
| 4 | An install we did not perform |
