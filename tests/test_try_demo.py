"""Public demo tests: intake conversion, real-engine results, and access rules."""

import base64
from datetime import date

import pytest

from app import create_app
from app.services.intake_builder import (
    IntakeError, build_intake, clause_evidence_field, remediation_payload, run_intake, workflow_events,
)
from app.services.org_policy import load_org_policy

AS_OF = date(2026, 10, 14)
SAME_ORIGIN = {"Origin": "http://localhost"}
def form(**overrides):
    """A low-risk vendor with reviewed evidence for the access claim and each trust-center artifact."""
    base = {"vendor_name": "Northwind Notes", "data_sensitivity": "internal",
            "integration_permissions": "read_only", "ai_use": "none",
            "model_training_on_customer_data": "no", "external_exposure": "internal_only",
            "retention_deletion": "documented", "decisions_affecting_people": "no",
            "evidence_integration_permissions": "independent_verified",
            "trust_center_url": "", "trust_soc2": "independent_verified",
            "trust_security": "independent_verified", "trust_privacy": "independent_verified"}
    for clause in load_org_policy()["required_contract_clauses"]:
        base[clause_evidence_field(clause["clause_id"])] = "independent_verified"
    base.update(overrides)
    return base


def run(**overrides):
    return run_intake(build_intake(form(**overrides), AS_OF), AS_OF)


def status_of(result, topic):
    return next(c for c in result["claims"] if c["topic"] == topic)["evidence_status"]


def test_low_risk_intake_uses_real_engine_results():
    r = run()
    assert r["risk"]["inherent"]["score"] == 20 and r["risk"]["inherent"]["tier"] == "low"
    assert r["risk"]["evidence_confidence"]["level"] == "high"
    assert r["risk"]["review_path"] == "standard_review"
    assert remediation_payload(r) is None
    clause = r["risk"]["policy"]["required_contract_clauses"][0]
    assert clause["evidence_status"] == "verified"
    assert clause["evidence"][0]["evidence_id"] == "E-CC-001"
    assert {m["control_id"] for m in r["mappings"]} == {"IA-2", "AC-6", "SC-8", "AU-2"}


@pytest.mark.parametrize("option, expected", [
    ("independent_verified", "verified"),
    ("vendor_statement", "self_attested"),
    ("not_reviewed", "not_reviewed"),
    ("expired", "expired"),
    ("contradicts", "conflicting"),
    ("none", "missing"),
])
def test_each_evidence_option_maps_to_its_status(option, expected):
    result = run(trust_soc2=option)
    assert status_of(result, "authentication") == expected
    assert status_of(result, "audit_logging") == expected


def test_contradicting_evidence_escalates_and_drafts_a_ticket():
    r = run(evidence_integration_permissions="contradicts")
    assert "ESC-003" in [e["rule_id"] for e in r["risk"]["escalations"]]
    payload = remediation_payload(r)
    assert payload["_demo_note"].startswith("Mock")
    assert "C-INTEGRATION-PERMISSIONS" in [item["claim_id"] for item in payload["evidence_requests"]]


def test_decisions_that_affect_people_are_prohibited_without_changing_the_score():
    allowed = run(ai_use="assistive", decisions_affecting_people="no")
    blocked = run(ai_use="assistive", decisions_affecting_people="yes")
    assert allowed["risk"]["inherent"] == blocked["risk"]["inherent"]
    assert blocked["risk"]["policy_outcome"]["status"] == "prohibited"
    assert blocked["risk"]["policy_outcome"]["restrictions"][0]["restriction_id"] == "HR-001"
    assert remediation_payload(blocked)["priority"] == "Policy restriction — human decision required"
    assert remediation_payload(blocked)["restrictions"] == ["HR-001"]
    assert remediation_payload(allowed) is None
    titles = [event["title"] for event in workflow_events(blocked)]
    assert "Policy check" in titles


def test_public_form_asks_the_policy_question(gated_client):
    response = gated_client.get("/try/")
    assert response.status_code == 200
    assert b"fully automated decisions" in response.data
    assert b"no human review" in response.data


def test_public_yes_answer_shows_the_restriction(gated_client):
    response = gated_client.post("/try/assess", data=form(ai_use="assistive", decisions_affecting_people="yes"),
                                 headers=SAME_ORIGIN)
    assert response.status_code == 200
    assert b"HR-001" in response.data
    assert b"ORG-AI-USE" in response.data
    assert b"CC-001" in response.data
    assert b"Evidence basis" in response.data
    assert b"Listed, not enforced" not in response.data
    assert b"Not Prohibited" not in response.data


@pytest.mark.parametrize("option, expected", [
    ("independent_verified", "verified"),
    ("vendor_statement", "self_attested"),
    ("contradicts", "conflicting"),
    ("none", "missing"),
])
def test_clause_evidence_option_sets_cc_001_status(option, expected):
    result = run(**{clause_evidence_field("CC-001"): option})
    clause = result["risk"]["policy"]["required_contract_clauses"][0]
    assert clause["evidence_status"] == expected
    assert result["risk"]["inherent"]["score"] == 20
    assert result["risk"]["review_path"] == "standard_review"


def test_missing_clause_evidence_drafts_a_ticket_without_blocking():
    result = run(**{clause_evidence_field("CC-001"): "none"})
    payload = remediation_payload(result)
    assert payload["contract_clauses"][0]["clause_id"] == "CC-001"
    assert payload["contract_clauses"][0]["status"] == "missing"
    assert payload["review_path"] == "standard_review"
    assert result["risk"]["policy_outcome"]["status"] == "not_prohibited"
    detail = next(event["detail"] for event in workflow_events(result) if event["title"] == "Policy check")
    assert "CC-001 missing" in detail


def test_public_form_asks_for_clause_evidence(gated_client):
    response = gated_client.get("/try/")
    assert response.status_code == 200
    assert b"required contract clause" in response.data
    assert b"CC-001" in response.data
    assert b"must not train or improve models" in response.data


def test_unknown_answers_are_undetermined_not_low():
    r = run(data_sensitivity="unknown")
    assert r["risk"]["inherent"]["tier"] == "undetermined"
    assert remediation_payload(r)["priority"].endswith("(result undetermined)")


def test_event_log_lists_steps_in_order():
    titles = [e["title"] for e in workflow_events(run(trust_soc2="none"))]
    assert titles == ["Intake received", "Evidence validated", "Risk evaluated", "Policy check",
                      "Escalation check", "Controls mapped", "Remediation ticket drafted"]


@pytest.mark.parametrize("overrides, expected", [
    ({"vendor_name": ""}, "name is required"),
    ({"vendor_name": "x" * 81}, "80 characters"),
    ({"data_sensitivity": "secret"}, "most sensitive data"),
    ({"trust_soc2": "trust_me"}, "SOC 2"),
])
def test_invalid_intake_is_rejected(overrides, expected):
    with pytest.raises(IntakeError) as exc:
        build_intake(form(**overrides), AS_OF)
    assert any(expected in p for p in exc.value.problems)


@pytest.fixture
def gated_client(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "public.sqlite3"),
                      "REQUIRE_AUTH": True, "DEMO_USERNAME": "demo", "DEMO_PASSWORD": "pw"})
    return app.test_client()


def test_public_pages_open_without_login_but_full_demo_stays_locked(gated_client):
    assert gated_client.get("/try/").status_code == 200
    assert gated_client.get("/try/scenario/high-risk-ai").status_code == 200
    assert gated_client.get("/static/css/styles.css").status_code == 200
    assert gated_client.get("/").status_code == 401
    assert gated_client.get("/risks").status_code == 401
    assert gated_client.get("/demo/").status_code == 401
    assert gated_client.get("/walkthrough").status_code == 401
    assert gated_client.get("/walkthrough/").status_code == 401


def test_public_assessment_runs_and_saves_nothing(gated_client):
    response = gated_client.post("/try/assess", data=form(), headers=SAME_ORIGIN)
    assert response.status_code == 200
    assert b"Northwind Notes" in response.data and b"Workflow event log" in response.data
    login = {"Authorization": "Basic " + base64.b64encode(b"demo:pw").decode()}
    assert b"Northwind Notes" not in gated_client.get("/risks", headers=login).data


def test_public_form_errors_are_shown(gated_client):
    response = gated_client.post("/try/assess", data=form(vendor_name=""), headers=SAME_ORIGIN)
    assert response.status_code == 400 and b"Please fix these fields" in response.data


def test_public_form_rejects_cross_site_posts(gated_client):
    assert gated_client.post("/try/assess", data=form(), headers={"Origin": "https://evil.example"}).status_code == 403


def test_vendor_name_is_escaped(gated_client):
    response = gated_client.post("/try/assess", data=form(vendor_name="<script>x</script>",
                                                          evidence_audit_logging="none"), headers=SAME_ORIGIN)
    assert response.status_code == 200
    assert b"<script>x</script>" not in response.data


def test_oversized_post_is_rejected(gated_client):
    big = form(vendor_name="ok")
    big["padding"] = "x" * 20000
    assert gated_client.post("/try/assess", data=big, headers=SAME_ORIGIN).status_code == 413


def test_unknown_public_scenario_returns_404(gated_client):
    assert gated_client.get("/try/scenario/not-real").status_code == 404


def test_omitted_training_is_not_applicable_when_ai_use_is_none():
    posted = form()
    del posted["model_training_on_customer_data"]
    result = run_intake(build_intake(posted, AS_OF), AS_OF)
    assert result["assessment_inputs"]["model_training_on_customer_data"] == "no"
    assert result["answer_applicability"]["model_training_on_customer_data"] == "not_applicable"
    assert result["risk"]["inherent"]["score"] == 20
    assert "INH-TRAIN" not in [factor["rule_id"] for factor in result["risk"]["inherent"]["factors"]]


def test_submitted_training_answer_is_kept_when_ai_use_is_none():
    result = run(model_training_on_customer_data="yes")
    assert result["assessment_inputs"]["model_training_on_customer_data"] == "yes"
    assert result["answer_applicability"] == {}
    assert result["risk"]["inherent"]["score"] == 20


def test_training_is_required_when_ai_is_in_use():
    posted = form(ai_use="assistive")
    del posted["model_training_on_customer_data"]
    with pytest.raises(IntakeError) as exc:
        build_intake(posted, AS_OF)
    assert any("train or improve models" in problem for problem in exc.value.problems)


def test_soc_citation_is_auditor_evidence_and_the_url_is_not_on_other_records():
    result = run(trust_center_url="https://trust.example.test/northwind")
    auth = next(claim for claim in result["claims"] if claim["topic"] == "authentication")
    privacy = next(claim for claim in result["claims"] if claim["topic"] == "privacy")
    access = next(claim for claim in result["claims"] if claim["topic"] == "integration_permissions")
    clause = result["risk"]["policy"]["required_contract_clauses"][0]
    assert auth["evidence"][0]["source"] == "independent_auditor"
    assert auth["evidence"][0]["pointer_id"] == "soc2"
    assert auth["evidence"][0]["trust_center_url"] == "https://trust.example.test/northwind"
    assert privacy["evidence"][0]["source"] == "internal_observation"
    assert privacy["evidence"][0]["artifact_type"] == "policy_document"
    assert "trust_center_url" not in access["evidence"][0]
    assert "trust_center_url" not in clause["evidence"][0]
    assert result["trust_center"]["fetched"] is False
    assert result["questionnaire_version"] == "1.1.0"
    detail = next(event["detail"] for event in workflow_events(result) if event["title"] == "Evidence validated")
    assert "not fetched" in detail


def test_vendor_described_security_doc_stays_self_attested():
    result = run(trust_security="vendor_statement")
    assert status_of(result, "transmission_security") == "self_attested"
    claim = next(item for item in result["claims"] if item["topic"] == "transmission_security")
    assert claim["evidence"][0]["source"] == "vendor"


def test_trust_center_url_alone_does_not_verify_or_approve():
    result = run(trust_center_url="https://trust.example.test/northwind",
                 evidence_integration_permissions="none", trust_soc2="none",
                 trust_security="none", trust_privacy="none",
                 **{clause_evidence_field("CC-001"): "none"})
    assert {claim["evidence_status"] for claim in result["claims"]} == {"missing"}
    assert result["risk"]["policy"]["required_contract_clauses"][0]["evidence_status"] == "missing"
    assert result["risk"]["policy_outcome"]["status"] == "not_prohibited"
    assert result["risk"]["review_path"] == "standard_review"
    assert result["risk"]["inherent"]["score"] == 20
    assert result["trust_center"]["fetched"] is False
    assert all(pointer["evidence_ids"] == [] for pointer in result["trust_center"]["pointers"])


@pytest.mark.parametrize("url, expected", [
    ("javascript:alert(1)", "http:// or https://"),
    ("ftp://trust.example.test/vendor", "http:// or https://"),
    ("https://user:secret@trust.example.test/vendor", "username or password"),
    ("https://trust.example.test/vendor with space", "unsupported characters"),
    ("https://trust.example.test/" + "a" * 180, "200 characters"),
])
def test_bad_trust_center_url_is_rejected(url, expected):
    with pytest.raises(IntakeError) as exc:
        build_intake(form(trust_center_url=url), AS_OF)
    assert any(expected in problem for problem in exc.value.problems)


def test_public_form_explains_proportion_and_trust_center(gated_client):
    response = gated_client.get("/try/")
    assert response.status_code == 200
    body = response.data
    assert b"data-ask-when=\"ai_not_none\"" in body
    assert b"Asked only when AI use is not none" in body
    assert b"does not open the page" in body
    assert b"not verified evidence" in body
    assert b"What supports the access claim?" in body
    assert b"Privacy notice" in body
    assert b"https://trust.example.test/northwind" in body


def test_public_download_is_the_same_result_and_saves_nothing(gated_client):
    posted = form(trust_center_url="https://trust.example.test/northwind")
    downloaded = gated_client.post("/try/assess", data={**posted, "export_format": "json"}, headers=SAME_ORIGIN)
    assert downloaded.status_code == 200
    assert "attachment;" in downloaded.headers["Content-Disposition"]
    assert downloaded.headers["Content-Disposition"].endswith('northwind-notes-intake.json"')
    package = downloaded.get_json()
    assert package["automatic_approval"] is None
    assert package["trust_center"]["fetched"] is False
    assert package["trust_center"]["url"] == "https://trust.example.test/northwind"
    assert package["source"] == "public_intake"
    assert package["decision"] is None
    assert package["versions"]["questionnaire"] == "1.1.0"
    login = {"Authorization": "Basic " + base64.b64encode(b"demo:pw").decode()}
    assert b"Northwind Notes" not in gated_client.get("/risks", headers=login).data


def test_unknown_export_format_is_rejected(gated_client):
    response = gated_client.post("/try/assess", data={**form(), "export_format": "pdf"}, headers=SAME_ORIGIN)
    assert response.status_code == 400
