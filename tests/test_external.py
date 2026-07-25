"""Free-tool ingestion (scanner/external.py).

Covers the four things that make ingestion honest rather than decorative:
parsing each tool's real output shape, mapping its severity onto OrgIQ's scale
without inventing precision, keeping provenance on every finding, and merging an
overlapping defect into ONE backlog item instead of two.

Fixtures are inline and modelled on the tools' documented output — the v5 and v4
Code Analyzer JSON shapes, SARIF 2.1.0, and the Tooling API rows
`SecurityHealthCheckRisks` actually returns (these were taken from a live query
against the OrgIQ org).
"""

import csv
import json

import backlog
import external as ex
import scan_result
from orgiq_spike import Finding


def native(rule, dim, sev="High", conf="Medium", component="AccountTrigger",
           evidence="native evidence", detail=""):
    """A finding as the OrgIQ rule packs emit it — no `source` attribute at all,
    which is exactly how `source_of` has to see them."""
    return Finding(rule, dim, sev, conf, component, evidence, detail)


# ============================================================ Code Analyzer

CA_V5 = {
    "runDir": "/repo/",
    "violationCounts": {"total": 4, "sev1": 1, "sev2": 2},
    "violations": [
        {
            "rule": "AvoidDmlStatementsInLoops", "engine": "pmd", "severity": 2,
            "tags": ["Recommended", "Performance", "Apex"],
            "primaryLocationIndex": 0,
            "locations": [{"file": "/repo/force-app/main/default/triggers/"
                                   "AccountTrigger.trigger",
                           "startLine": 18, "startColumn": 9}],
            "message": "Avoid DML statements inside loops",
            "resources": ["https://pmd.github.io/rules/apex/performance.html"],
        },
        {
            "rule": "AvoidDmlStatementsInLoops", "engine": "pmd", "severity": 3,
            "tags": ["Recommended", "Performance", "Apex"],
            "primaryLocationIndex": 0,
            "locations": [{"file": "/repo/force-app/main/default/triggers/"
                                   "AccountTrigger.trigger",
                           "startLine": 42, "startColumn": 13}],
            "message": "Avoid DML statements inside loops",
            "resources": [],
        },
        {
            "rule": "ApexCRUDViolation", "engine": "pmd", "severity": 1,
            "tags": ["Recommended", "Security", "Apex"],
            "primaryLocationIndex": 0,
            "locations": [{"file": "/repo/force-app/main/default/classes/"
                                   "AccountService.cls", "startLine": 31}],
            "message": "Validate CRUD permission before SOQL/DML operation",
            "resources": [],
        },
        {
            "rule": "ApexDoc", "engine": "pmd", "severity": 3,
            "tags": ["Documentation", "Apex"],
            "primaryLocationIndex": 0,
            "locations": [{"file": "/repo/force-app/main/default/classes/"
                                   "AccountService.cls", "startLine": 1}],
            "message": "Missing ApexDoc comment",
            "resources": [],
        },
    ],
}

CA_V4 = [{
    "engine": "pmd",
    "fileName": "/repo/force-app/main/default/classes/BillingService.cls",
    "violations": [{
        "line": "77", "column": "9", "severity": 1,
        "ruleName": "AvoidSoqlInLoops", "category": "Performance",
        "url": "https://pmd.github.io/rules/apex/performance.html",
        "message": "Avoid SOQL queries inside loops",
    }],
}]

SARIF = {
    "version": "2.1.0",
    "runs": [{
        "tool": {"driver": {
            "name": "pmd",
            "rules": [{
                "id": "ApexUnitTestClassShouldHaveAsserts",
                "properties": {"category": "Best Practices"},
                "helpUri": "https://pmd.github.io/rules/apex/bestpractices.html",
            }],
        }},
        "results": [{
            "ruleId": "ApexUnitTestClassShouldHaveAsserts", "ruleIndex": 0,
            "level": "warning",
            "message": {"text": "Apex unit test classes should have at least one "
                                "System.assert() or assertEquals() call"},
            "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": "file:///repo/force-app/main/default/"
                                            "classes/BillingServiceTest.cls"},
                "region": {"startLine": 12},
            }}],
        }],
    }],
}


def write(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


def by_rule(findings):
    return {f.rule_id: f for f in findings}


def test_v5_json_maps_dimensions_severity_and_provenance(tmp_path):
    res = ex.code_analyzer_findings(results_file=write(tmp_path, "r.json", CA_V5))
    assert res.ran is True
    got = by_rule(res.findings)
    assert set(got) == {"D5.EXT_BULK_SAFETY", "D4.EXT_SECURITY_VIOLATION"}

    dml = got["D5.EXT_BULK_SAFETY"]
    assert (dml.dimension, dml.severity) == ("D5", "High")   # v5 severity 2 -> High
    assert dml.source == ex.SOURCE_CODE_ANALYZER
    assert dml.tool_rule == "pmd/AvoidDmlStatementsInLoops"
    assert dml.component == "AccountTrigger.trigger"
    assert dml.component_type == "ApexTrigger"
    assert dml.reference.startswith("https://")

    crud = got["D4.EXT_SECURITY_VIOLATION"]
    assert (crud.dimension, crud.severity) == ("D4", "Critical")  # severity 1
    assert crud.component == "AccountService.cls"


def test_repeat_violations_in_one_file_become_one_finding(tmp_path):
    res = ex.code_analyzer_findings(results_file=write(tmp_path, "r.json", CA_V5))
    dml = by_rule(res.findings)["D5.EXT_BULK_SAFETY"]
    # Two rows, one ticket — and the worst of the two severities, not the last.
    assert "(2 occurrences)" in dml.evidence
    assert "18, 42" in dml.detail
    assert dml.severity == "High"


def test_rules_outside_the_rubric_are_counted_not_re_filed(tmp_path):
    res = ex.code_analyzer_findings(results_file=write(tmp_path, "r.json", CA_V5))
    # ApexDoc is a real violation with no OrgIQ dimension. It must not land in
    # whichever dimension happens to be nearest — that would move a score on a
    # signal the rubric does not model.
    assert res.unmapped == 1
    assert "matched no OrgIQ dimension" in res.detail
    assert all("ApexDoc" not in f.evidence for f in res.findings)


def test_v4_severity_scale_is_not_read_as_the_v5_scale(tmp_path):
    res = ex.code_analyzer_findings(results_file=write(tmp_path, "r.json", CA_V4))
    (soql,) = res.findings
    # Severity 1 means "high" in v4 and "critical" in v5. One shared table would
    # silently promote every v4 finding a full band.
    assert soql.severity == "High"
    assert soql.rule_id == "D5.EXT_BULK_SAFETY"
    assert soql.component == "BillingService.cls"


def test_sarif_is_parsed_with_rule_metadata(tmp_path):
    res = ex.code_analyzer_findings(results_file=write(tmp_path, "r.sarif", SARIF))
    (test_quality,) = res.findings
    assert test_quality.rule_id == "D3.EXT_TEST_QUALITY"
    assert test_quality.severity == "Medium"          # SARIF level "warning"
    assert test_quality.source == ex.SOURCE_CODE_ANALYZER
    assert test_quality.reference.endswith("bestpractices.html")
    assert "SARIF" in res.detail


def test_cli_json_envelope_is_unwrapped():
    violations, fmt = ex.parse_code_analyzer({"status": 0, "result": CA_V5})
    assert len(violations) == 4 and "v5" in fmt


# ------------------------------------------------- graceful absence

def test_missing_results_file_is_a_no_op_that_says_why(tmp_path):
    res = ex.code_analyzer_findings(results_file=str(tmp_path / "nope.json"))
    assert (res.ran, res.findings) == (False, [])
    assert "not ingested" in res.detail and "none of its signal is assumed" in res.detail


def test_unparseable_results_file_never_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("<xml>not json</xml>", encoding="utf-8")
    res = ex.code_analyzer_findings(results_file=str(bad))
    assert (res.ran, res.findings) == (False, [])
    assert "nothing ingested" in res.detail


def test_unrecognised_payload_shape_is_reported_not_guessed(tmp_path):
    res = ex.code_analyzer_findings(results_file=write(tmp_path, "r.json", {"foo": 1}))
    assert (res.ran, res.findings) == (False, [])
    assert "unrecognised" in res.detail


def test_no_input_at_all_contributes_nothing():
    res = ex.code_analyzer_findings()
    assert (res.ran, res.findings, res.ingested) == (False, [], 0)
    assert "contributed nothing" in res.detail


def test_invocation_failure_does_not_fail_the_scan():
    def broken_runner(workspace, timeout):
        return None, "the plugin exited 1 (no Java runtime found)"

    res = ex.code_analyzer_findings(invoke=True, workspace=".", runner=broken_runner)
    assert (res.ran, res.findings) == (False, [])
    assert "no Java runtime" in res.detail


def test_a_just_in_time_plugin_entry_does_not_count_as_installed():
    # Regression, found running this against a real CLI: `sf plugins --json`
    # lists code-analyzer even when it has never been installed, marked
    # "type": "jit". Treating that as installed makes an OrgIQ scan trigger a
    # plugin download (and demand a JDK) halfway through.
    jit = [{"name": "@salesforce/plugin-code-analyzer", "type": "jit",
            "version": "5.14.0"}]
    installed = [{"name": "@salesforce/plugin-code-analyzer", "type": "user",
                  "version": "5.14.0"}]
    assert ex._has_code_analyzer(jit) is False
    assert ex._has_code_analyzer(installed) is True
    assert ex._has_code_analyzer([{"name": "@salesforce/plugin-data",
                                   "type": "core"}]) is False
    assert ex._has_code_analyzer("not a list") is False


def test_invocation_is_skipped_when_the_plugin_is_absent(monkeypatch):
    monkeypatch.setattr(ex, "code_analyzer_installed", lambda: False)
    res = ex.code_analyzer_findings(invoke=True, workspace=".")
    assert (res.ran, res.findings) == (False, [])
    assert "not installed" in res.detail
    assert "OrgIQ's own D5 loop heuristics" in res.detail


def test_invocation_ingests_what_the_plugin_returns():
    res = ex.code_analyzer_findings(invoke=True, workspace="/repo",
                                    runner=lambda ws, t: (CA_V5, ""))
    assert res.ran is True and len(res.findings) == 2
    assert "code-analyzer run" in res.detail


# ============================================================= Health Check

HC_RISKS = [
    {"DurableId": "SessionSettings.clickjackVisualForceHeaders", "RiskType": "HIGH_RISK",
     "Setting": "Enable clickjack protection for customer Visualforce pages with "
                "standard headers", "SettingGroup": "SessionSettings",
     "SettingRiskCategory": "HIGH_RISK", "OrgValue": "Disabled",
     "StandardValue": "Enabled"},
    {"DurableId": "PasswordPolicies.minPasswordLength", "RiskType": "MEDIUM_RISK",
     "Setting": "Minimum password length", "SettingGroup": "PasswordPolicies",
     "SettingRiskCategory": "MEDIUM_RISK", "OrgValue": "8", "StandardValue": "10"},
    {"DurableId": "Identity.mfaEnabled", "RiskType": "MEETS_STANDARD",
     "Setting": "MFA Enabled", "SettingGroup": "Identity",
     "SettingRiskCategory": "HIGH_RISK", "OrgValue": "true", "StandardValue": "true"},
]


def hc_runner(soql):
    if "SecurityHealthCheckRisks" in soql:
        return list(HC_RISKS)
    return [{"DurableId": "0", "Score": "66"}]


def test_health_check_emits_d4_findings_carrying_score_and_setting():
    res = ex.health_check_findings(org="orgiq", runner=hc_runner)
    assert res.ran is True and res.score == "66"
    assert len(res.findings) == 2                    # MEETS_STANDARD is not a finding
    high, medium = res.findings
    assert (high.rule_id, high.dimension) == ("D4.HEALTH_CHECK_RISK", "D4")
    assert (high.severity, medium.severity) == ("High", "Medium")
    assert high.source == ex.SOURCE_HEALTH_CHECK
    assert high.component == "SessionSettings.clickjackVisualForceHeaders"
    assert high.component_type == "Security Setting"
    assert "clickjack protection" in high.evidence
    assert "'Disabled'" in high.evidence and "'Enabled'" in high.evidence
    assert "score 66%" in high.evidence


def test_health_check_risks_are_reported_but_do_not_score_d4():
    res = ex.health_check_findings(org="orgiq", runner=hc_runner)
    ca = ex.code_analyzer_findings(invoke=True, runner=lambda ws, t: (CA_V5, "")).findings
    everything = res.findings + ca
    scored = ex.scoreable(everything)
    # Ticketed and reported, excluded from the arithmetic: D4 measures agent
    # blast radius, not org security posture (PRD §2.3 non-goal).
    assert all(f.rule_id != "D4.HEALTH_CHECK_RISK" for f in scored)
    assert len(scored) == len(ca)


def test_health_check_query_failure_collects_nothing_and_says_so():
    def failing(soql):
        raise ex.SfQueryError("INVALID_TYPE: sObject type 'SecurityHealthCheckRisks' "
                              "is not supported")

    res = ex.health_check_findings(org="orgiq", runner=failing)
    assert (res.ran, res.findings) == (False, [])
    assert "no security-posture signal was collected and none is assumed" in res.detail


def test_health_check_without_an_org_is_a_no_op():
    res = ex.health_check_findings()
    assert (res.ran, res.findings) == (False, [])
    assert "no org alias supplied" in res.detail


def test_health_check_survives_an_unavailable_score():
    def risks_only(soql):
        if "SecurityHealthCheckRisks" in soql:
            return list(HC_RISKS)
        raise ex.SfQueryError("no rows")

    res = ex.health_check_findings(org="orgiq", runner=risks_only)
    assert res.ran is True and res.score == ""
    assert len(res.findings) == 2
    assert "score unavailable" in res.detail
    # No score to quote, so the evidence quotes none — it does not invent one.
    assert "score" not in res.findings[0].evidence


# ================================================================ Optimizer

OPTIMIZER_JSON = [
    {"category": "Unused Custom Fields", "component": "Account.Legacy_Code__c",
     "severity": "Medium",
     "description": "This field has not been used in a report, list view or "
                    "process in the last 90 days"},
    {"category": "Permission Sets", "component": "Legacy_Admin_PS",
     "severity": "High", "description": "Permission set is assigned to no users"},
    {"category": "Lightning Experience Readiness", "component": "Account",
     "description": "JavaScript button not supported in Lightning"},
]


def test_optimizer_export_is_ingested_with_provenance(tmp_path):
    path = tmp_path / "optimizer.json"
    path.write_text(json.dumps(OPTIMIZER_JSON), encoding="utf-8")
    res = ex.optimizer_findings(export_file=str(path))
    assert res.ran is True
    got = by_rule(res.findings)
    assert set(got) == {"D1.OPTIMIZER_UNUSED_FIELD", "D4.OPTIMIZER_PERMISSION_RISK"}
    unused = got["D1.OPTIMIZER_UNUSED_FIELD"]
    assert unused.source == ex.SOURCE_OPTIMIZER
    assert unused.component == "Account.Legacy_Code__c"
    assert unused.severity == "Medium"
    assert got["D4.OPTIMIZER_PERMISSION_RISK"].severity == "High"
    # Lightning readiness is a real Optimizer category with no OrgIQ dimension.
    assert res.unmapped == 1
    assert "OrgIQ does not model" in res.detail


def test_optimizer_reads_a_csv_export(tmp_path):
    path = tmp_path / "optimizer.csv"
    path.write_text("Category,Component,Severity,Description\n"
                    "Unused Custom Fields,Account.Old__c,Low,Never referenced\n",
                    encoding="utf-8")
    res = ex.optimizer_findings(export_file=str(path))
    (f,) = res.findings
    assert (f.rule_id, f.component, f.severity) == ("D1.OPTIMIZER_UNUSED_FIELD",
                                                    "Account.Old__c", "Low")


def test_optimizer_without_a_file_is_a_no_op_that_admits_there_is_no_api():
    res = ex.optimizer_findings()
    assert (res.ran, res.findings) == (False, [])
    assert "no Optimizer API" in res.detail


def test_optimizer_missing_file_never_raises(tmp_path):
    res = ex.optimizer_findings(export_file=str(tmp_path / "gone.csv"))
    assert (res.ran, res.findings) == (False, [])


# ============================================================ deduplication

def ca_findings():
    return ex.code_analyzer_findings(invoke=True,
                                     runner=lambda ws, t: (CA_V5, "")).findings


def test_external_and_native_report_of_one_defect_becomes_one_finding():
    heuristic = native("D5.DML_IN_LOOP", "D5", sev="High", conf="Medium",
                       component="AccountTrigger",
                       evidence="2 DML statement(s) inside a loop")
    external = [f for f in ca_findings() if f.rule_id == "D5.EXT_BULK_SAFETY"]

    merged, merges = ex.merge_findings([heuristic] + external)
    assert len(merged) == 1
    kept = merged[0]
    # The parser wins over the regex, and the ticket points at the tool that can
    # actually clear it.
    assert kept.rule_id == "D5.EXT_BULK_SAFETY"
    assert ex.source_of(kept) == ex.SOURCE_CODE_ANALYZER
    assert "corroborated by OrgIQ D5.DML_IN_LOOP" in kept.evidence
    assert kept.corroborated_by == ["OrgIQ D5.DML_IN_LOOP"]
    assert len(merges) == 1
    assert merges[0].defect == "dml-in-loop"
    assert merges[0].folded == ("OrgIQ D5.DML_IN_LOOP",)


def test_corroboration_does_not_double_count_the_backlog():
    heuristic = native("D5.DML_IN_LOOP", "D5", component="AccountTrigger")
    external = [f for f in ca_findings() if f.rule_id == "D5.EXT_BULK_SAFETY"]
    both = [heuristic] + external

    unmerged_rows, _ = backlog.to_rows(both, "DemoOrg")
    merged_rows, _ = backlog.to_rows(ex.merge_findings(both)[0], "DemoOrg")
    assert backlog.count_tickets(unmerged_rows) == 2      # one defect, two tickets
    assert backlog.count_tickets(merged_rows) == 1        # ...merged into one


def test_merging_never_downgrades_severity_and_can_raise_confidence():
    # A Low-confidence OrgIQ heuristic that an actual parser confirms is no
    # longer a guess — and a merge must never quietly soften the severity.
    heuristic = native("D5.DML_IN_LOOP", "D5", sev="Critical", conf="Low",
                       component="AccountTrigger")
    external = [f for f in ca_findings() if f.rule_id == "D5.EXT_BULK_SAFETY"]
    external[0].severity = "Low"

    (kept,), _ = ex.merge_findings([heuristic] + external)
    assert (kept.severity, kept.confidence) == ("Critical", "High")
    assert kept.rule_id == "D5.EXT_BULK_SAFETY"
    assert backlog.emits_to_backlog(kept) is True


def test_apex_test_quality_merges_with_the_native_no_tests_rule(tmp_path):
    heuristic = native("D3.APEX_NO_TESTS", "D3", sev="Medium", conf="Medium",
                       component="BillingServiceTest.cls",
                       evidence="agent-invocable Apex has no test class referencing it")
    external = ex.code_analyzer_findings(
        results_file=write(tmp_path, "r.sarif", SARIF)).findings

    merged, merges = ex.merge_findings([heuristic] + external)
    assert len(merged) == 1
    assert merged[0].rule_id == "D3.EXT_TEST_QUALITY"
    assert merges[0].defect == "apex-test-quality"


def test_optimizer_outranks_the_orgiq_unreferenced_field_heuristic(tmp_path):
    path = tmp_path / "optimizer.json"
    path.write_text(json.dumps(OPTIMIZER_JSON[:1]), encoding="utf-8")
    optimizer = ex.optimizer_findings(export_file=str(path)).findings
    heuristic = native("D1.UNREFERENCED_FIELD", "D1", sev="Medium", conf="Low",
                       component="Account.Legacy_Code__c",
                       evidence="not referenced by any of the 3 report file(s)")

    (kept,), merges = ex.merge_findings([heuristic] + optimizer)
    # Optimizer sees the whole org; OrgIQ sees committed report XML.
    assert ex.source_of(kept) == ex.SOURCE_OPTIMIZER
    assert kept.rule_id == "D1.OPTIMIZER_UNUSED_FIELD"
    assert kept.confidence == "High"
    assert merges[0].folded == ("OrgIQ D1.UNREFERENCED_FIELD",)


def test_different_components_and_different_defects_never_merge():
    findings = [
        native("D5.DML_IN_LOOP", "D5", component="AccountTrigger"),
        native("D5.DML_IN_LOOP", "D5", component="ContactTrigger"),
        native("D5.SOQL_IN_LOOP", "D5", component="AccountTrigger"),
    ] + ca_findings()
    merged, merges = ex.merge_findings(findings)
    # Only the AccountTrigger DML pair collapses.
    assert len(merged) == len(findings) - 1
    assert [m.defect for m in merges] == ["dml-in-loop"]


def test_two_distinct_clusters_on_one_object_are_not_one_defect():
    # Regression, found merging a real fixture scan: two semantic-duplicate
    # clusters on one object both render as "Obj [2 fields]" and are told apart
    # only by their member list. Keying on (component, rule) alone silently
    # dropped the second one — a merge must never lose a finding.
    a = native("D1.SEMANTIC_DUPLICATE", "D1", component="Legacy_Customer__c [2 fields]",
               detail="Cust_Nm__c | Customer_Name__c")
    b = native("D1.SEMANTIC_DUPLICATE", "D1", component="Legacy_Customer__c [2 fields]",
               detail="Phone1__c | Phone_Number__c")
    merged, merges = ex.merge_findings([a, b])
    assert len(merged) == 2 and merges == []
    # The same finding twice, however, is still one finding.
    again, _ = ex.merge_findings([a, a])
    assert len(again) == 1


def test_merge_is_stable_and_order_preserving():
    heuristic = native("D5.DML_IN_LOOP", "D5", component="AccountTrigger")
    other = native("D3.UNDOCUMENTED_ACTION", "D3", component="Flow_A")
    external = ca_findings()
    merged, _ = ex.merge_findings([heuristic, other] + external)
    assert [f.rule_id for f in merged] == ["D5.EXT_BULK_SAFETY",
                                           "D3.UNDOCUMENTED_ACTION",
                                           "D4.EXT_SECURITY_VIOLATION"]


def test_a_native_only_scan_passes_through_the_merge_untouched():
    # Ingestion is additive. With no external tool available, running the merge
    # must not perturb a single native finding — same objects, same severities,
    # same evidence text.
    findings = [
        native("D1.MISSING_DESCRIPTION", "D1", component="Acct__c.A__c"),
        native("D1.MISSING_DESCRIPTION", "D1", component="Acct__c.B__c"),
        native("D5.DML_IN_LOOP", "D5", component="AccountTrigger"),
        native("D5.NO_RECURSION_GUARD", "D5", conf="Low", component="AccountTrigger"),
        native("D4.WIDE_OBJECT_ACCESS", "D4", component="Agent_PS:Case"),
    ]
    before = [(f.rule_id, f.component, f.severity, f.confidence, f.evidence)
              for f in findings]
    merged, merges = ex.merge_findings(findings)
    assert merges == []
    assert [(f.rule_id, f.component, f.severity, f.confidence, f.evidence)
            for f in merged] == before


def test_findings_with_no_source_attribute_read_as_orgiq():
    assert ex.source_of(native("D1.MISSING_DESCRIPTION", "D1")) == "OrgIQ"


# ================================================== emission and provenance

NEW_RULE_IDS = ["D5.EXT_BULK_SAFETY", "D4.EXT_SECURITY_VIOLATION",
                "D3.EXT_TEST_QUALITY", "D4.HEALTH_CHECK_RISK",
                "D1.OPTIMIZER_UNUSED_FIELD", "D4.OPTIMIZER_PERMISSION_RISK"]

TOOL_FOR_RULE = {
    "D5.EXT_BULK_SAFETY": "Code Analyzer",
    "D4.EXT_SECURITY_VIOLATION": "Code Analyzer",
    "D3.EXT_TEST_QUALITY": "Code Analyzer",
    "D4.HEALTH_CHECK_RISK": "Health Check",
    "D1.OPTIMIZER_UNUSED_FIELD": "Optimizer",
    "D4.OPTIMIZER_PERMISSION_RISK": "Optimizer",
}


def test_every_ingested_rule_id_has_a_playbook_entry():
    for rule_id in NEW_RULE_IDS:
        play = backlog._play(rule_id)
        assert play is not backlog._UNKNOWN, rule_id
        assert play["points"] > 0 and play["epic"]
        assert play["remediation"].startswith("1. ")


def test_acceptance_criteria_name_the_tool_that_can_actually_clear_it():
    # An OrgIQ re-scan cannot clear a Code Analyzer violation; saying it could
    # would be an acceptance criterion nobody can satisfy.
    for rule_id, tool in TOOL_FOR_RULE.items():
        assert tool in backlog._play(rule_id)["acceptance"], rule_id


def test_ingested_rules_share_the_native_epic_where_the_fix_is_the_same():
    assert (backlog._play("D5.EXT_BULK_SAFETY")["epic"]
            == backlog._play("D5.DML_IN_LOOP")["epic"])
    assert (backlog._play("D3.EXT_TEST_QUALITY")["epic"]
            == backlog._play("D3.APEX_NO_TESTS")["epic"])
    assert (backlog._play("D1.OPTIMIZER_UNUSED_FIELD")["epic"]
            == backlog._play("D1.UNREFERENCED_FIELD")["epic"])


def test_backlog_csv_carries_the_tool_and_the_component_type(tmp_path):
    findings = ca_findings() + ex.health_check_findings(org="o",
                                                        runner=hc_runner).findings
    out = tmp_path / "backlog.csv"
    backlog.write_csv(findings, "DemoOrg", str(out))
    rows = [r for r in csv.DictReader(out.open()) if r["Issue Type"] == "Task"]

    assert list(csv.DictReader(out.open()).fieldnames) == backlog.BACKLOG_COLUMNS
    by_component = {r["Salesforce Component"]: r for r in rows}
    trigger = by_component["AccountTrigger.trigger"]
    assert trigger["Source"] == "Code Analyzer"
    assert trigger["Component Type"] == "ApexTrigger"
    assert "pmd/AvoidDmlStatementsInLoops" in trigger["Description"]
    assert "Automation Collision" in trigger["Description"]
    setting = by_component["SessionSettings.clickjackVisualForceHeaders"]
    assert setting["Source"] == "Health Check"
    assert setting["Component Type"] == "Security Setting"


def test_epic_rollup_names_the_engine_that_can_close_it():
    ca = ca_findings()
    epic = backlog._epic_description("Bulkify automation", ca[:1], "DemoOrg")
    assert "clears a re-run of Code Analyzer" in epic
    # An all-native epic still reads the way it always did.
    plain = backlog._epic_description("Bulkify automation",
                                      [native("D5.DML_IN_LOOP", "D5")], "DemoOrg")
    assert "clears a re-scan" in plain


def test_backlog_columns_are_unchanged():
    assert backlog.BACKLOG_COLUMNS == [
        "External ID", "Issue Type", "Epic Name", "Epic Link", "Summary",
        "Priority", "Story Points (provisional)", "Labels",
        "Salesforce Component", "Component Type", "Rule ID", "Dimension",
        "Severity", "Confidence", "Rule Maturity", "Source", "Description",
    ]


def test_merged_ticket_records_the_corroborating_engine(tmp_path):
    heuristic = native("D5.DML_IN_LOOP", "D5", component="AccountTrigger")
    merged, _ = ex.merge_findings([heuristic] + ca_findings())
    out = tmp_path / "backlog.csv"
    backlog.write_csv(merged, "DemoOrg", str(out))
    rows = [r for r in csv.DictReader(out.open()) if r["Issue Type"] == "Task"]
    ticket = [r for r in rows if r["Salesforce Component"] == "AccountTrigger.trigger"]
    assert len(ticket) == 1
    assert "Corroborated by: OrgIQ D5.DML_IN_LOOP" in ticket[0]["Description"]


def test_scan_result_records_keep_the_tool_of_origin():
    findings = ca_findings()
    result = scan_result.build([], findings, "DemoOrg", scan_mode="Hybrid",
                               assessed_dims=frozenset({"D4", "D5"}))
    sources = {r["source"] for r in result["findings"]}
    assert sources == {"Code Analyzer"}
    types = {r["component_type"] for r in result["findings"]}
    assert types == {"ApexTrigger", "ApexClass"}


# ==================================================== collection wiring

def test_collect_reports_every_tool_that_did_not_run(tmp_path):
    scan = ex.collect(code_analyzer_results=write(tmp_path, "r.json", CA_V5))
    assert scan.ran() == ["Code Analyzer"]
    missing = dict(scan.missing())
    assert set(missing) == {"Health Check", "Optimizer"}
    assert "no org alias supplied" in missing["Health Check"]
    assert "no Optimizer API" in missing["Optimizer"]
    assert len(scan.findings) == 2
