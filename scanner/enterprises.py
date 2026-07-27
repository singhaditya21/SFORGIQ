#!/usr/bin/env python3
"""
The demo enterprises.

The demo used to be twenty-four unrelated companies, which was a consultancy's
portfolio — the wrong story for a product where one install serves one
enterprise's own estate. So there are two enterprises here, and the dashboard
shows one at a time: an insurer and a bank, because those are the audiences, and
because their schemas look nothing alike.

Two things matter about the shape of this data.

**The orgs in an estate are related.** Every org is derived from its
enterprise's base schema and then drifted, the way a real sandbox drifts from
the org it was copied out of: developer sandboxes run ahead with unreleased
work, UAT sits behind because it was refreshed months ago, production carries
hotfixes that never went back. That is what makes a difference between two orgs
*mean* something. Unrelated companies could never support that reading.

**The schemas start plausible and are then degraded**, which is how real orgs
actually got this way: a considered object, then fifteen years of additions
nobody reviewed. Generating defects directly would produce noise; degrading a
sensible schema produces debt.

Managed-package fields carry a namespace and are deliberately included, because
every real org has them and they are *not* ours to fix — you cannot add a
description to a field you do not own.
"""

from __future__ import annotations

# ---------------------------------------------------------------- vocabulary
#
# (api_name, type, description) — the schema as someone would design it before
# the years happen to it. Descriptions here are real ones; the degrader is what
# strips and muddles them.

INSURANCE_OBJECTS = {
    "Policy__c": [
        ("Policy_Number__c", "Text", "External policy identifier printed on the schedule."),
        ("Effective_Date__c", "Date", "Date cover under this policy begins."),
        ("Expiry_Date__c", "Date", "Date cover lapses unless renewed."),
        ("Annual_Premium__c", "Currency", "Total premium due for the current period, excluding taxes."),
        ("Sum_Insured__c", "Currency", "Maximum aggregate the insurer will pay across all claims."),
        ("Policy_Status__c", "Picklist", "Lifecycle state: Quoted, In Force, Lapsed, Cancelled."),
        ("Renewal_Method__c", "Picklist", "How this policy renews: Automatic, Invited, Non-renewable."),
        ("Broker_Commission_Rate__c", "Percent", "Commission percentage payable to the placing broker."),
        ("Underwriting_Year__c", "Number", "Year of account the premium is earned into."),
        ("Cancellation_Reason__c", "Picklist", "Why cover ended early, where it did."),
        ("No_Claims_Years__c", "Number", "Consecutive claim-free years used in the renewal discount."),
        ("Payment_Frequency__c", "Picklist", "Instalment cadence agreed with the policyholder."),
    ],
    "Claim__c": [
        ("Claim_Reference__c", "Text", "Reference quoted to the claimant in all correspondence."),
        ("Date_Of_Loss__c", "Date", "Date the insured event occurred, not the date it was reported."),
        ("Reported_Date__c", "Date", "Date the claim was first notified to the insurer."),
        ("Reserve_Amount__c", "Currency", "Case reserve currently held against this claim."),
        ("Paid_To_Date__c", "Currency", "Total settled and paid out so far."),
        ("Claim_Status__c", "Picklist", "Open, Under Investigation, Settled, Repudiated, Reopened."),
        ("Fraud_Indicator__c", "Checkbox", "Set when the claim has been referred for fraud review."),
        ("Handler_Queue__c", "Text", "Queue the claim currently sits in for handling."),
        ("Litigation_Flag__c", "Checkbox", "True once proceedings have been issued against the insurer."),
        ("Salvage_Recovery__c", "Currency", "Amount recovered from salvage or subrogation."),
    ],
    "Coverage__c": [
        ("Coverage_Type__c", "Picklist", "Peril or section this coverage line responds to."),
        ("Limit_Amount__c", "Currency", "Maximum payable under this coverage line."),
        ("Deductible__c", "Currency", "Amount borne by the insured before the insurer responds."),
        ("Territory__c", "Picklist", "Geographic scope within which cover applies."),
        ("Aggregate_Limit__c", "Currency", "Cap across all claims on this line for the period."),
        ("Waiting_Period_Days__c", "Number", "Days after inception before this coverage becomes active."),
    ],
    "Underwriting_Decision__c": [
        ("Decision_Outcome__c", "Picklist", "Accept, Decline, Refer, or Accept with terms."),
        ("Referral_Reason__c", "Text", "Why the risk was referred to a senior underwriter."),
        ("Risk_Score__c", "Number", "Model score used to triage the submission."),
        ("Loading_Percent__c", "Percent", "Premium loading applied for adverse risk features."),
        ("Decision_Date__c", "Date", "Date the underwriter recorded the decision."),
        ("Authority_Level__c", "Picklist", "Delegated authority band the decision was made under."),
    ],
    "Broker__c": [
        ("Agency_Code__c", "Text", "Code identifying the broking house in the ledger."),
        ("Commission_Terms__c", "Text", "Agreed commission basis for business placed by this broker."),
        ("Appointment_Date__c", "Date", "Date the agency agreement took effect."),
        ("Regulatory_Status__c", "Picklist", "Current standing with the regulator."),
    ],
}

BANKING_OBJECTS = {
    "Loan__c": [
        ("Loan_Reference__c", "Text", "Reference used on statements and in the core system."),
        ("Principal_Amount__c", "Currency", "Original advanced amount, before any repayment."),
        ("Outstanding_Balance__c", "Currency", "Capital still owed as at the last reconciliation."),
        ("Interest_Rate__c", "Percent", "Current nominal annual rate applied to the balance."),
        ("Rate_Type__c", "Picklist", "Fixed, Variable, or Tracker."),
        ("Term_Months__c", "Number", "Contractual term of the facility in months."),
        ("Maturity_Date__c", "Date", "Date the final repayment falls due."),
        ("Arrears_Days__c", "Number", "Days the account has been past due."),
        ("Loan_Purpose__c", "Picklist", "Declared use of funds, as captured at application."),
        ("Repayment_Method__c", "Picklist", "Direct debit, standing order, or manual."),
        ("Early_Settlement_Fee__c", "Currency", "Fee chargeable if the facility is repaid ahead of term."),
    ],
    "Account_Application__c": [
        ("Application_Reference__c", "Text", "Reference quoted to the applicant while in progress."),
        ("Submitted_Date__c", "Date", "Date the completed application was received."),
        ("Application_Stage__c", "Picklist", "Where the application sits in the assessment workflow."),
        ("Declared_Income__c", "Currency", "Gross annual income as stated by the applicant."),
        ("Employment_Status__c", "Picklist", "Employment basis declared at application."),
        ("Channel__c", "Picklist", "Branch, broker, digital, or telephony."),
        ("Decline_Reason__c", "Text", "Reason recorded where the application was declined."),
        ("Affordability_Result__c", "Picklist", "Outcome of the affordability assessment."),
    ],
    "Collateral__c": [
        ("Collateral_Type__c", "Picklist", "Asset class pledged against the facility."),
        ("Valuation_Amount__c", "Currency", "Most recent independent valuation of the asset."),
        ("Valuation_Date__c", "Date", "Date of the valuation currently relied on."),
        ("Charge_Priority__c", "Number", "Ranking of the bank's charge against the asset."),
        ("Insurance_Verified__c", "Checkbox", "Set once cover over the asset has been evidenced."),
    ],
    "KYC_Check__c": [
        ("Check_Type__c", "Picklist", "Identity, address, sanctions, PEP, or adverse media."),
        ("Check_Outcome__c", "Picklist", "Pass, Refer, or Fail."),
        ("Performed_Date__c", "Date", "Date the check was carried out."),
        ("Expiry_Date__c", "Date", "Date the check must be refreshed by."),
        ("Provider_Reference__c", "Text", "Reference returned by the screening provider."),
        ("Risk_Rating__c", "Picklist", "Customer risk rating resulting from the check."),
    ],
    "Credit_Decision__c": [
        ("Decision__c", "Picklist", "Approve, Decline, or Refer to credit committee."),
        ("Credit_Score__c", "Number", "Bureau score at the point of decision."),
        ("Approved_Limit__c", "Currency", "Limit sanctioned by the decisioning authority."),
        ("Decision_Date__c", "Date", "Date the credit decision was recorded."),
        ("Mandate_Level__c", "Picklist", "Lending mandate the decision was taken under."),
    ],
}

# Fields the org does not own. Every real org has them, and no remediation
# ticket can touch them — you cannot add a description to someone else's field.
MANAGED_FIELDS = {
    "insurance": [("vlocity_ins__PolicyNumber__c", "Text"),
                  ("vlocity_ins__RatingEngineId__c", "Text"),
                  ("nFORCE__LegacyKey__c", "Text")],
    "banking": [("nCino__LoanNumber__c", "Text"),
                ("nCino__CreditMemoId__c", "Text"),
                ("fferpcore__LedgerCode__c", "Text")],
}

STANDARD_OBJECTS = ["Account", "Contact", "Case", "Opportunity"]


# ------------------------------------------------------------------ estates
#
# Each org is (name, type, defect_ratio, drift, last_refreshed, notes) and may
# carry two more: the scan mode, and how many prior quarterly scans to generate.
# History is what turns a score into a burn-down — the estate model dates its
# scan ids, so an org can hold more than one.
#
# drift: how this org differs from the enterprise's base schema.
#   base      the reference — production
#   ahead     unreleased work: extra fields the rest of the estate lacks
#   behind    refreshed long ago: missing what has been added since
#   hotfix    production-only fixes that never went back down the path
#   divergent an acquisition — related business, unrelated schema
#
# defect_ratio drives how degraded the schema is; older, less governed orgs are
# messier. A developer sandbox refreshed last week inherits production's debt,
# so it is not automatically cleaner.

ENTERPRISES = [
    {
        "name": "Meridian Insurance",
        "industry": "insurance",
        "objects": INSURANCE_OBJECTS,
        "orgs": [
            ("prod",         "Production", 0.66, "hotfix",    "2019-04-01",
             "Org of record. Carries four hotfixes applied directly in production.",
             "Org", 3),
            ("uat",          "UAT",        0.60, "behind",    "2025-11-02",
             "Refreshed from production; two releases behind by the time testing starts."),
            ("staging",      "Staging",    0.44, "base",      "2026-05-18", ""),
            ("qa",           "QA",         0.34, "behind",    "2026-04-11", ""),
            ("dev-core",     "Developer",  0.40, "ahead",     "2026-06-30",
             "Renewals rework in progress — fields here are not in production yet.",
             "Source", 0),
            ("dev-claims",   "Developer",  0.16, "ahead",     "2026-07-02", ""),
            ("training",     "Training",   0.12, "behind",    "2025-08-20",
             "Used for onboarding; deliberately frozen."),
            ("gladstone",    "Other",      0.95, "divergent", "",
             "Acquired 2024. Separate instance, never merged into the estate."),
        ],
    },
    {
        "name": "Northgate Bank",
        "industry": "banking",
        "objects": BANKING_OBJECTS,
        "orgs": [
            ("prod",       "Production", 0.63, "hotfix",    "2017-09-12",
             "Org of record since the 2017 core migration.",
             "Org", 3),
            ("uat",        "UAT",        0.56, "behind",    "2026-01-15",
             "Refreshed in January; lending changes since then are not present."),
            ("qa",         "QA",         0.30, "base",      "2026-05-30", ""),
            ("dev-lending", "Developer", 0.18, "ahead",     "2026-07-05",
             "Affordability rework — new fields not yet released."),
            ("dev-onboard", "Developer", 0.38, "ahead",     "2026-06-22", ""),
            ("legacy-core", "Other",     0.97, "divergent", "",
             "Pre-migration instance, read-only, retained for regulatory history."),
        ],
    },
]


def org_display_name(enterprise: str, org: str) -> str:
    """"Meridian Insurance · prod".

    The separator is load-bearing: the dashboard splits on it to group an
    estate, which is how demo mode shows two enterprises without either the
    Salesforce schema or the product model gaining a concept of "enterprise".
    A real install has one estate and no prefix.
    """
    return f"{enterprise} · {org}"


# ----------------------------------------------------------------- personas
#
# The jobs people actually hold in these two businesses, as the access those
# jobs need. This exists because the persona model reads five kinds of metadata
# — profile, layout, flow, approval process, validation rule — and the demo
# estate was feeding it exactly one, a single blanket permission set. Every
# surface it produced was therefore the same shape, and the sentence the whole
# feature is for ("this persona edits Claim, sees 34 of 61 fields, starts two
# flows, and two validation rules constrain it") could not be produced at all.
#
# `edits` / `reads` are named by object so a persona is recognisably a job
# rather than a random subset. `laid_out` is the objects this role has a screen
# for — normally the same as `edits`, and deliberately narrower for the roles
# where real orgs hand out rights nobody built a process for.

PERSONAS = {
    "insurance": [
        {"api": "Claims_Handler", "label": "Claims Handler",
         "edits": ["Claim__c", "Coverage__c"],
         "reads": ["Policy__c", "Broker__c"],
         "laid_out": ["Claim__c", "Coverage__c"]},
        {"api": "Underwriter", "label": "Underwriter",
         "edits": ["Underwriting_Decision__c", "Policy__c"],
         "reads": ["Claim__c", "Coverage__c", "Broker__c"],
         "laid_out": ["Underwriting_Decision__c", "Policy__c"],
         "approves": True},
        {"api": "Service_Agent", "label": "Service Agent",
         "edits": ["Policy__c"],
         "reads": ["Claim__c", "Coverage__c"],
         "laid_out": ["Policy__c"]},
        {"api": "Broker_Operations", "label": "Broker Operations",
         "edits": ["Broker__c"],
         "reads": ["Policy__c"],
         "laid_out": ["Broker__c"],
         "deletes": ["Broker__c"]},
        # The archetype every long-lived org has: someone who was given edit
        # rights across the estate over the years and still works one screen.
        # Not planted as a defect — it is stated as the access this role holds,
        # and D4.PERSONA_BEYOND_PROCESS has to notice the gap on its own.
        {"api": "Operations_Manager", "label": "Operations Manager",
         "edits": ["Claim__c", "Policy__c", "Coverage__c",
                   "Underwriting_Decision__c", "Broker__c"],
         "reads": [],
         "laid_out": ["Claim__c"]},
    ],
    "banking": [
        {"api": "Relationship_Manager", "label": "Relationship Manager",
         "edits": ["Loan__c", "Account_Application__c"],
         "reads": ["Collateral__c", "Credit_Decision__c"],
         "laid_out": ["Loan__c", "Account_Application__c"]},
        {"api": "Credit_Officer", "label": "Credit Officer",
         "edits": ["Credit_Decision__c"],
         "reads": ["Loan__c", "Account_Application__c", "Collateral__c"],
         "laid_out": ["Credit_Decision__c"],
         "approves": True},
        {"api": "Onboarding_Analyst", "label": "Onboarding Analyst",
         "edits": ["Account_Application__c", "KYC_Check__c"],
         "reads": ["Loan__c"],
         "laid_out": ["Account_Application__c", "KYC_Check__c"]},
        {"api": "Collections_Officer", "label": "Collections Officer",
         "edits": ["Loan__c"],
         "reads": ["Collateral__c", "Credit_Decision__c"],
         "laid_out": ["Loan__c"],
         "deletes": ["Loan__c"]},
        {"api": "Branch_Operations", "label": "Branch Operations",
         "edits": ["Loan__c", "Account_Application__c", "KYC_Check__c",
                   "Collateral__c", "Credit_Decision__c"],
         "reads": [],
         "laid_out": ["Account_Application__c"]},
    ],
}

# The rules that refuse a save. Two per object at most: a persona constrained by
# fourteen validation rules is a different (and rarer) story than the one this
# demo tells, and inflating the count would make the constraint column noise.
VALIDATION_RULES = {
    "insurance": {
        "Policy__c": [("Expiry_After_Effective", "Cover cannot lapse before it begins."),
                      ("Premium_Positive", "A policy in force must carry a premium.")],
        "Claim__c": [("Loss_Before_Report", "A loss cannot be reported before it occurred."),
                     ("Reserve_Required_When_Open", "An open claim must hold a reserve.")],
        "Coverage__c": [("Deductible_Below_Limit", "A deductible above the limit leaves no cover.")],
        "Underwriting_Decision__c": [
            ("Referral_Needs_Reason", "A referred risk must record why.")],
        "Broker__c": [("Agency_Code_Format", "Agency codes follow the ledger's format.")],
    },
    "banking": {
        "Loan__c": [("Balance_Not_Above_Principal", "Outstanding cannot exceed what was advanced."),
                    ("Maturity_After_Drawdown", "A facility cannot mature before it starts.")],
        "Account_Application__c": [
            ("Decline_Needs_Reason", "A declined application must record why."),
            ("Income_Required_For_Affordability", "Affordability needs a declared income.")],
        "Collateral__c": [("Valuation_Not_Stale", "A valuation over twelve months old cannot be relied on.")],
        "KYC_Check__c": [("Outcome_Requires_Provider_Ref", "A completed check must cite its provider reference.")],
        "Credit_Decision__c": [("Approval_Within_Mandate", "An approval must sit inside the mandate it was taken under.")],
    },
}

# The processes a decision has to pass through. Keyed to the object the
# approving persona edits, which is what makes it that persona's process.
APPROVALS = {
    "insurance": [("Referred_Risk_Approval", "Underwriting_Decision__c"),
                  ("Large_Claim_Settlement", "Claim__c")],
    "banking": [("Credit_Committee_Sanction", "Credit_Decision__c"),
                ("Above_Mandate_Lending", "Loan__c")],
}
