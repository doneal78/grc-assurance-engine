"""Reviewer package: questionnaire invariants, scenario export, and saved-risk export."""

import copy
import json
import re

import pytest

from app.db import get_db
from app.services.evidence_validator import load_policy
from app.services.intake_builder import field_choices
from app.services.intake_export import build_package, package_from_saved_risk, render_markdown
from app.services.intake_questionnaire import QuestionnaireError, load_questionnaire, validate_questionnaire
from app.services.org_policy import load_org_policy
from app.services.risk_engine import load_rules
from app.services.scenario_runner import run_scenario
from app.services.workflow_service import get_risk

SAME_ORIGIN = {"Origin": "http://localhost"}


def test_questionnaire_version_cites_only_real_rules():
    questionnaire = load_questionnaire()
    assert questionnaire["questionnaire_version"] == "1.1.0"
    assert questionnaire["direction_context"]["scored"] is False
    rules = load_rules()
    known = {factor["rule_id"] for factor in rules["inherent_factors"].values()}
    known.update(rule["rule_id"] for rule in rules["escalation_rules"])
    policy = load_org_policy()
    known.update(item["restriction_id"] for item in policy["hard_restrictions"])
    known.update(item["clause_id"] for item in policy["required_contract_clauses"])
    cited = set(re.findall(r"\b(?:INH-[A-Z]+|ESC-\d+|HR-\d+|CC-\d+)\b", json.dumps(questionnaire)))
    assert cited <= known
    assert {"INH-TRAIN", "HR-001", "ESC-003", "ESC-004", "ESC-006", "CC-001"} <= cited
    topics = [topic["topic"] for pointer in questionnaire["trust_center"]["pointers"] for topic in pointer["topics"]]
    assert topics.count("authentication") == 1
    assert "privacy" in topics
    assert questionnaire["access_evidence"]["topic"] not in topics


def test_unknown_trust_center_source_is_rejected():
    broken = copy.deepcopy(load_questionnaire())
    broken["trust_center"]["pointers"][0]["source_by_option"]["independent_verified"] = "blog"
    with pytest.raises(QuestionnaireError, match="source"):
        validate_questionnaire(broken, field_choices(), load_org_policy(), load_policy())


def test_scenario_package_has_answers_and_no_trust_center_or_approval():
    result = run_scenario("evidence-supported")
    first = build_package(result)
    second = build_package(result)
    assert first == second
    assert first["automatic_approval"] is None
    assert first["source"] == "scenario"
    assert first["decision"] is None
    assert first["trust_center"]["collection"] == "not_supplied"
    assert first["trust_center"]["fetched"] is False
    assert first["versions"]["questionnaire"] is None
    assert first["versions"]["rule_set"] == "0.3.0"
    answers = {item["field"]: item["value"] for item in first["intake_answers"]}
    assert answers["decisions_affecting_people"] == "no"
    assert answers["model_training_on_customer_data"] == "no"
    assert first["required_clauses"][0]["clause_id"] == "CC-001"
    assert first["required_clauses"][0]["evidence_status"] == "verified"
    text = render_markdown(first)
    assert "Evidence-supported collaboration tool" in text
    assert "CC-001: verified" in text
    assert "Fetched: no" in text
    assert "No decision recorded" in text
    assert "not an approval" in text


def test_package_says_when_older_results_have_no_intake_answers():
    result = run_scenario("high-risk-ai")
    del result["assessment_inputs"]
    package = build_package(result)
    assert package["intake_answers"] is None
    assert "before the reviewer package" in package["intake_answers_note"]
    assert "ESC-001" in render_markdown(package)


def test_scenario_download_and_saved_risk_download_include_the_decision(client):
    scenario = client.get("/try/scenario/contract-clause-conflict/export/markdown")
    assert scenario.status_code == 200
    assert "text/markdown" in scenario.content_type
    assert b"CC-001: conflicting" in scenario.data
    assert b"Fetched: no" in scenario.data
    assert client.get("/try/scenario/contract-clause-conflict/export/pdf").status_code == 404
    assert client.get("/try/scenario/missing/export/json").status_code == 404

    registered = client.post("/demo/prohibited-ai-decisions/register", headers=SAME_ORIGIN)
    assert registered.status_code == 302
    risk_id = registered.headers["Location"].rsplit("/", 1)[-1]
    before = client.get(f"/risks/{risk_id}/export/json")
    assert before.status_code == 200
    assert 'filename="ai-tool-that-decides-eligibility-intake.json"' in before.headers["Content-Disposition"]
    package = json.loads(before.data)
    assert package["saved_risk_id"] == risk_id
    assert package["source"] == "saved_risk"
    assert package["automatic_approval"] is None
    assert package["decision"] is None
    assert package["policy_outcome"]["status"] == "prohibited"
    assert package["policy_outcome"]["restrictions"][0]["restriction_id"] == "HR-001"
    assert package["intake_answers"]
    page = client.get(f"/risks/{risk_id}")
    assert b"Download JSON" in page.data
    assert b"did not cite a trust center" in page.data

    saved = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve",
        "rationale": "The output is advisory.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "A named officer decides each eligibility case.",
    }, headers=SAME_ORIGIN)
    assert saved.status_code == 302
    downloaded = client.get(f"/risks/{risk_id}/export/markdown")
    assert b"A named officer decides each eligibility case." in downloaded.data
    assert b"Disposition: approve" in downloaded.data
    assert b"Nothing in this package approves the vendor." in downloaded.data
    with client.application.app_context():
        stored = package_from_saved_risk(get_risk(get_db(), risk_id))
    assert stored["decision"]["exception_rationale"] == "A named officer decides each eligibility case."
    assert stored["decision"]["handling_minutes"] is None
    assert stored["decision"]["rework_minutes"] is None
    assert stored["decision"]["manual_touches"] is None
    assert stored["decision"]["handoffs"] is None
    assert stored["decision"]["rework_time_note"] == "Rework time was not reported."
    assert stored["decision"]["manual_touches_note"] == "Manual touches were not reported."
    assert stored["decision"]["handoffs_note"] == "Handoffs were not reported."
    assert b"not reported (unmeasured)." in downloaded.data
    assert b"Rework time: was not reported." in downloaded.data
    assert b"Handoffs: handoffs were not reported." in downloaded.data
    assert stored["automatic_approval"] is None
    assert stored["intake_answers"]

    with_minutes = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve",
        "rationale": "The output is advisory.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "A named officer decides each eligibility case.",
        "handling_minutes": "40",
    }, headers=SAME_ORIGIN)
    assert with_minutes.status_code == 302
    package = json.loads(client.get(f"/risks/{risk_id}/export/json").data)
    assert package["decision"]["handling_minutes"] == 40
    assert package["decision"]["rework_minutes"] is None
    assert package["decision"]["rework_time_note"] == "Rework time was not reported."
    assert "not an input to the cost model" in package["decision"]["handling_time_note"]
    summary = client.get(f"/risks/{risk_id}/export/markdown").data
    assert b"40 self-reported minutes" in summary
    assert b"Rework time: was not reported." in summary
    nonsense = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve",
        "rationale": "The output is advisory.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "A named officer decides each eligibility case.",
        "handling_minutes": "12.5",
    }, headers=SAME_ORIGIN)
    assert nonsense.status_code == 400
    assert b"handling_minutes" in nonsense.data
    with client.application.app_context():
        kept = get_risk(get_db(), risk_id)["decision"]
    assert kept["handling_minutes"] == 40
    assert kept["rework_minutes"] is None
    assert kept["disposition"] == "approve"

    with_rework = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve",
        "rationale": "The output is advisory.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "A named officer decides each eligibility case.",
        "handling_minutes": "40",
        "rework_minutes": "8",
    }, headers=SAME_ORIGIN)
    assert with_rework.status_code == 302
    package = json.loads(client.get(f"/risks/{risk_id}/export/json").data)
    assert package["decision"]["handling_minutes"] == 40
    assert package["decision"]["rework_minutes"] == 8
    assert "not handling minutes" in package["decision"]["rework_time_note"]
    summary = client.get(f"/risks/{risk_id}/export/markdown").data
    assert b"8 self-reported minutes" in summary
    assert b"Not handling time." in summary
    bad_rework = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "reject",
        "rationale": "This must not replace the saved decision.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "",
        "handling_minutes": "1",
        "rework_minutes": "12.5",
    }, headers=SAME_ORIGIN)
    assert bad_rework.status_code == 400
    assert b"rework_minutes" in bad_rework.data
    assert b"8 self-reported rework minutes" in bad_rework.data
    with client.application.app_context():
        kept = get_risk(get_db(), risk_id)["decision"]
    assert kept["rework_minutes"] == 8
    assert kept["handling_minutes"] == 40
    assert kept["manual_touches"] is None
    assert kept["disposition"] == "approve"

    with_touches = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve",
        "rationale": "The output is advisory.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "A named officer decides each eligibility case.",
        "handling_minutes": "40",
        "rework_minutes": "8",
        "manual_touches": "3",
    }, headers=SAME_ORIGIN)
    assert with_touches.status_code == 302
    package = json.loads(client.get(f"/risks/{risk_id}/export/json").data)
    assert package["decision"]["manual_touches"] == 3
    assert package["decision"]["handling_minutes"] == 40
    assert package["decision"]["rework_minutes"] == 8
    assert "not handling minutes" in package["decision"]["manual_touches_note"]
    assert "not rework minutes" in package["decision"]["manual_touches_note"]
    summary = client.get(f"/risks/{risk_id}/export/markdown").data
    assert b"3 self-reported touches" in summary
    assert b"Not rework minutes." in summary
    bad_touches = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "reject",
        "rationale": "This must not replace the saved decision.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "",
        "handling_minutes": "1",
        "rework_minutes": "1",
        "manual_touches": "2.5",
    }, headers=SAME_ORIGIN)
    assert bad_touches.status_code == 400
    assert b"manual_touches" in bad_touches.data
    assert b"3 self-reported touches" in bad_touches.data
    with client.application.app_context():
        kept = get_risk(get_db(), risk_id)["decision"]
    assert kept["manual_touches"] == 3
    assert kept["rework_minutes"] == 8
    assert kept["handling_minutes"] == 40
    assert kept["disposition"] == "approve"

    cleared = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve",
        "rationale": "The output is advisory.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "A named officer decides each eligibility case.",
        "handling_minutes": "40",
        "rework_minutes": "8",
        "manual_touches": "",
    }, headers=SAME_ORIGIN)
    assert cleared.status_code == 302
    package = json.loads(client.get(f"/risks/{risk_id}/export/json").data)
    assert package["decision"]["manual_touches"] is None
    assert package["decision"]["manual_touches_note"] == "Manual touches were not reported."
    assert package["decision"]["handoffs"] is None
    assert package["decision"]["handoffs_note"] == "Handoffs were not reported."
    summary = client.get(f"/risks/{risk_id}/export/markdown").data
    assert b"Manual touches: manual touches were not reported." in summary
    assert b"Handoffs: handoffs were not reported." in summary

    with_handoffs = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve",
        "rationale": "The output is advisory.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "A named officer decides each eligibility case.",
        "handling_minutes": "40",
        "rework_minutes": "8",
        "manual_touches": "3",
        "handoffs": "2",
    }, headers=SAME_ORIGIN)
    assert with_handoffs.status_code == 302
    package = json.loads(client.get(f"/risks/{risk_id}/export/json").data)
    assert package["decision"]["handoffs"] == 2
    assert package["decision"]["manual_touches"] == 3
    assert package["decision"]["handling_minutes"] == 40
    assert package["decision"]["rework_minutes"] == 8
    assert "not handling minutes" in package["decision"]["handoffs_note"]
    assert "not rework minutes" in package["decision"]["handoffs_note"]
    assert "not manual touches" in package["decision"]["handoffs_note"]
    summary = client.get(f"/risks/{risk_id}/export/markdown").data
    assert b"2 self-reported handoffs" in summary
    assert b"Not manual touches." in summary
    bad_handoffs = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "reject",
        "rationale": "This must not replace the saved decision.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "",
        "handling_minutes": "1",
        "rework_minutes": "1",
        "manual_touches": "1",
        "handoffs": "1.5",
    }, headers=SAME_ORIGIN)
    assert bad_handoffs.status_code == 400
    assert b"handoffs" in bad_handoffs.data
    assert b"2 self-reported handoffs" in bad_handoffs.data
    with client.application.app_context():
        kept = get_risk(get_db(), risk_id)["decision"]
    assert kept["handoffs"] == 2
    assert kept["manual_touches"] == 3
    assert kept["rework_minutes"] == 8
    assert kept["handling_minutes"] == 40
    assert kept["disposition"] == "approve"

    cleared_handoffs = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve",
        "rationale": "The output is advisory.",
        "decider": "AI governance reviewer",
        "conditions": "",
        "exception_rationale": "A named officer decides each eligibility case.",
        "handling_minutes": "40",
        "rework_minutes": "8",
        "manual_touches": "3",
        "handoffs": "",
    }, headers=SAME_ORIGIN)
    assert cleared_handoffs.status_code == 302
    package = json.loads(client.get(f"/risks/{risk_id}/export/json").data)
    assert package["decision"]["handoffs"] is None
    assert package["decision"]["handoffs_note"] == "Handoffs were not reported."
    assert package["decision"]["manual_touches"] == 3
    assert package["decision"]["handling_minutes"] == 40
    summary = client.get(f"/risks/{risk_id}/export/markdown").data
    assert b"Handoffs: handoffs were not reported." in summary
    assert b"3 self-reported touches" in summary


def test_methods_page_describes_the_questionnaire(client):
    response = client.get("/methodology")
    assert response.status_code == 200
    body = response.data
    assert b"Intake questionnaire" in body
    assert b"1.1.0" in body
    assert b"not scored" in body
    assert b"does not open the page" in body
    assert b"not verified evidence" in body
    assert b"not a disposition" in body


def test_demo_page_links_to_the_package(client):
    response = client.get("/demo/evidence-supported")
    assert response.status_code == 200
    assert b"Download JSON" in response.data
    assert b"Download summary" in response.data
