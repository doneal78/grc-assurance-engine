"""Phase 1 tests: application factory, health route, and dashboard."""

from pathlib import Path

from app import create_app

SAME_ORIGIN = {"Origin": "http://localhost"}


def test_factory_defaults_to_not_testing():
    assert create_app().testing is False


def test_factory_applies_test_config(app):
    assert app.testing is True
    assert app.config["DATABASE"].endswith("test.sqlite3")


def test_auth_is_disabled_by_default(app):
    assert app.config["REQUIRE_AUTH"] is False


def test_required_auth_fails_closed_without_credentials():
    import pytest

    with pytest.raises(ValueError, match="DEMO_USERNAME and DEMO_PASSWORD"):
        create_app({"REQUIRE_AUTH": True})


def test_required_auth_protects_pages_and_allows_health_check(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "auth.sqlite3"),
        "REQUIRE_AUTH": True,
        "DEMO_USERNAME": "demo",
        "DEMO_PASSWORD": "correct horse battery staple",
    })
    client = app.test_client()

    assert client.get("/").status_code == 401
    assert client.get("/").headers["WWW-Authenticate"].startswith("Basic ")
    assert client.get("/mappings").status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/", auth=("demo", "wrong password")).status_code == 401
    assert client.get("/", auth=("demo", "correct horse battery staple")).status_code == 200


def test_health_returns_documented_response(client, app):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "service": "grc-assurance-engine",
        "database": "reachable",
    }
    text = response.get_data(as_text=True)
    assert app.config["DATABASE"] not in text
    assert "SELECT" not in text
    assert "sqlite_master" not in text


def test_health_reports_unreachable_when_the_database_file_is_gone(app):
    path = Path(app.config["DATABASE"])
    assert path.is_file()
    path.unlink()
    response = app.test_client().get("/health")
    assert response.status_code == 503
    assert response.get_json() == {
        "status": "unavailable",
        "service": "grc-assurance-engine",
        "database": "unreachable",
    }
    text = response.get_data(as_text=True)
    assert str(path) not in text
    assert "SELECT" not in text
    assert "sqlite_master" not in text
    assert "sqlite" not in text.lower()
    assert not path.exists()


def test_health_reports_unreachable_when_the_database_is_not_sqlite(app):
    path = Path(app.config["DATABASE"])
    path.write_bytes(b"not sqlite")
    response = app.test_client().get("/health")
    assert response.status_code == 503
    body = response.get_json()
    assert body == {
        "status": "unavailable",
        "service": "grc-assurance-engine",
        "database": "unreachable",
    }
    text = response.get_data(as_text=True)
    assert "not sqlite" not in text
    assert str(path) not in text
    assert "SELECT" not in text
    assert "sqlite_master" not in text


def test_database_is_readable_uses_a_temp_file_without_creating_a_missing_one(tmp_path):
    import sqlite3

    from app.db import database_is_readable

    ready = tmp_path / "ready.sqlite3"
    connection = sqlite3.connect(ready)
    connection.execute("CREATE TABLE example (id INTEGER)")
    connection.commit()
    connection.close()
    missing = tmp_path / "missing.sqlite3"
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")

    assert database_is_readable(str(ready)) is True
    assert database_is_readable(str(missing)) is False
    assert database_is_readable(str(blocker / "db.sqlite3")) is False
    assert database_is_readable(str(tmp_path)) is False
    assert database_is_readable("") is False
    assert not missing.exists()
    assert ready.is_file()


def test_health_rejects_post(client):
    assert client.post("/health").status_code == 405


def test_unknown_route_returns_404(client):
    assert client.get("/does-not-exist").status_code == 404


def test_dashboard_shows_honest_empty_state(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Repeatable scenarios" in response.data
    assert b"Synthetic scenarios" in response.data
    assert b"Synthetic data only" in response.data


def test_demo_scenario_page_shows_traceable_results(client):
    response = client.get("/demo/conflicting-claims")
    assert response.status_code == 200
    assert b"Conflicting permissions claim" in response.data
    assert b"Conflicting" in response.data
    assert b"IA-2" in response.data
    assert b"Evidence conflict review" in response.data
    assert b"Evidence reviewer" in response.data
    assert b"Required output" in response.data


def test_high_risk_result_names_each_deeper_assessment(client):
    response = client.get("/demo/high-risk-ai")
    assert response.status_code == 200
    assert b"Privileged-access impact assessment" in response.data
    assert b"AI impact assessment" in response.data
    assert b"Model-training assessment" in response.data
    assert b"Retention and deletion review" in response.data
    assert b"Owner role" in response.data
    assert b"Next step" in response.data
    assert b"CC-001" in response.data
    assert b"No evidence records for this clause" in response.data
    body = response.get_data(as_text=True)
    assert "A.6.2.8" in body
    assert "A.6.2.6" in body
    assert "A.7.2" not in body
    assert "A.5.14" not in body


def test_contract_clause_conflict_page_shows_the_evidence_basis(client):
    response = client.get("/demo/contract-clause-conflict")
    assert response.status_code == 200
    assert b"CC-001" in response.data
    assert b"Conflicting" in response.data
    assert b"E-CC-001-VENDOR" in response.data
    assert b"E-CC-001-CONFLICT" in response.data
    assert b"Evidence basis" in response.data
    assert b"Moderate" in response.data
    assert b"Not Prohibited" in response.data


def test_unknown_demo_scenario_returns_404(client):
    assert client.get("/demo/not-a-scenario").status_code == 404


def test_scenario_can_be_added_to_register(client):
    response = client.post("/demo/high-risk-ai/register", headers=SAME_ORIGIN)
    assert response.status_code == 302
    detail = client.get(response.headers["Location"])
    assert detail.status_code == 200
    assert b"Remediation actions" in detail.data
    assert b"Workflow history" in detail.data
    assert b"Privileged-access impact assessment" in detail.data
    assert b"AI governance reviewer" in detail.data
    assert client.get("/risks").status_code == 200


def test_remediation_form_validates_and_saves(client, app):
    response = client.post("/demo/high-risk-ai/register", headers=SAME_ORIGIN)
    risk_id = response.headers["Location"].rsplit("/", 1)[-1]
    from app.db import get_db
    from app.services.workflow_service import get_risk
    with app.app_context():
        action = get_risk(get_db(), risk_id)["actions"][0]
    invalid = client.post(f"/remediation/{action['action_id']}", data={
        "risk_id": risk_id, "status": "done", "owner": "Reviewer", "due_date": "", "completion_notes": ""
    }, headers=SAME_ORIGIN)
    assert invalid.status_code == 400
    assert b"INPUT NOT SAVED" in invalid.data
    updated = client.post(f"/remediation/{action['action_id']}", data={
        "risk_id": risk_id, "status": "in_progress", "owner": "Reviewer", "due_date": "2026-11-01", "completion_notes": ""
    }, headers=SAME_ORIGIN)
    assert updated.status_code == 302
    assert client.get(updated.headers["Location"]).status_code == 200


def test_stylesheet_is_served(client):
    assert client.get("/static/css/styles.css").status_code == 200


def test_mappings_page_lists_every_library_entry(client):
    from app.services.control_mapper import list_library

    library = list_library()
    response = client.get("/mappings")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Control mappings" in body
    assert 'href="/mappings"' in body
    assert f"MAPPING SET {library['mapping_set_version']}" in body
    assert library["source_note"] in body
    assert "does not certify a vendor or an organization" in body
    assert "does not treat one framework as equivalent to another" in body
    assert "draft portfolio review prompts" in body
    assert "are not in this library" not in body
    assert "ISO/IEC 27001" in body and "ISO/IEC 42001" in body
    assert "status-reviewed" not in body
    assert body.count("status-draft") == len(library["mappings"])
    for mapping in library["mappings"]:
        assert mapping["control_id"] in body
        assert mapping["title"] in body
        assert mapping["framework"] in body
        assert mapping["framework_version"] in body
        assert mapping["applicability_note"] in body
        assert mapping["rationale"] in body
        assert f'href="{mapping["source_reference"]}"' in body
        for topic in mapping["claim_topics"]:
            assert topic in body
    assert "Related claim topics" in body
    assert "Review status" in body
    assert "Mapping-set version" in body
    assert "Framework version" in body


def test_scenario_mapping_prompts_use_library_field_labels(client):
    response = client.get("/demo/evidence-supported")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Related control mapping prompts" in body
    assert "Related claim topics" in body
    assert "Source reference" in body
    assert "Review status" in body
    assert "Mapping-set version" in body
    assert "Applicability" in body
    assert "status-draft" in body
    assert "status-reviewed" not in body
    assert "AC-6" in body
    assert "A.5.15" in body
    assert "A.8.5" in body
    assert "A.5.14" in body
    assert "A.8.15" not in body
    assert "A.6.2.8" not in body
    assert "A.7.2" not in body
    assert "https://csrc.nist.gov/Projects/risk-management/sp800-53-controls/downloads" in body
    assert 'href="/mappings"' in body


def test_saved_risk_mapping_prompts_use_the_same_labels(client):
    response = client.post("/demo/evidence-supported/register", headers=SAME_ORIGIN)
    assert response.status_code == 302
    detail = client.get(response.headers["Location"])
    assert detail.status_code == 200
    body = detail.get_data(as_text=True)
    assert "Related control mapping prompts" in body
    assert "Related claim topics" in body
    assert "Review status" in body
    assert "status-draft" in body
    assert "IA-2" in body
    assert 'href="/mappings"' in body


def test_methodology_page_links_to_the_mapping_library(client):
    response = client.get("/methodology")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'href="/mappings"' in body
    assert "mapping set 0.2.0" in body
    assert "draft portfolio review prompts" in body
    assert "are not in the library" not in body
    assert "ISO/IEC 27001" in body
    assert "ISO/IEC 42001" in body


def test_methodology_page_explains_cost_limits(client):
    response = client.get("/methodology")
    assert response.status_code == 200
    assert b"labor capacity, not cash savings" in response.data


def test_methodology_page_lists_escalation_assessments(client):
    response = client.get("/methodology")
    assert response.status_code == 200
    body = response.data
    assert b"illustrative rule set 0.3.0" in body
    assert b"ORG-AI-USE" in body
    assert b"HR-001" in body
    assert b"Checked against evidence" in body
    assert b"does not block a human decision" in body
    assert b"CC-001" in body
    assert b"Data-classification review" in body
    assert b"Integration access review" in body
    assert b"AI use determination" in body
    assert b"Records owner" in body
    assert b"Required output" in body
    assert b"Business owner" in body


def test_cross_site_post_is_rejected_and_saves_nothing(client):
    response = client.post("/demo/high-risk-ai/register", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert b"Synthetic data only" in client.get("/risks").data
    assert b"high-risk-ai" not in client.get("/risks").data


def test_post_without_origin_or_referer_is_rejected(client):
    assert client.post("/demo/high-risk-ai/register").status_code == 403


def test_same_site_referer_is_accepted_when_origin_is_absent(client):
    response = client.post("/demo/high-risk-ai/register", headers={"Referer": "http://localhost/demo/high-risk-ai"})
    assert response.status_code == 302


def _register(client, scenario_id):
    response = client.post(f"/demo/{scenario_id}/register", headers=SAME_ORIGIN)
    assert response.status_code == 302
    return response.headers["Location"].rsplit("/", 1)[-1]


def test_prohibited_result_page_requires_an_exception_to_approve(client):
    risk_id = _register(client, "prohibited-ai-decisions")
    detail = client.get(f"/risks/{risk_id}")
    assert detail.status_code == 200
    assert b"Prohibited" in detail.data
    assert b"HR-001" in detail.data
    assert b"ORG-AI-USE" in detail.data
    assert b"E-CC-001" in detail.data
    assert b"Evidence basis" in detail.data
    assert b"Listed, not enforced" not in detail.data
    assert b"Moderate" in detail.data and b"Low" in detail.data
    rejected = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve", "rationale": "Looks fine", "decider": "GRC analyst",
        "conditions": "", "exception_rationale": "",
    }, headers=SAME_ORIGIN)
    assert rejected.status_code == 400
    assert b"exception" in rejected.data.lower()
    assert b"Looks fine" not in client.get(f"/risks/{risk_id}").data
    accepted = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve",
        "rationale": "The output is advisory.",
        "decider": "Reviewer <role>",
        "conditions": "",
        "exception_rationale": "A named officer decides each eligibility case.",
    }, headers=SAME_ORIGIN)
    assert accepted.status_code == 302
    page = client.get(accepted.headers["Location"])
    body = page.data
    assert b"Reviewer &lt;role&gt;" in body
    assert b"A named officer decides each eligibility case." in body
    assert b"ORG-AI-USE" in body
    assert b"0.3.0" in body
    assert b"Decision Recorded" in body
    assert b"Prohibited" in body


def test_prohibited_result_can_be_rejected_without_an_exception(client):
    risk_id = _register(client, "prohibited-ai-decisions")
    response = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "reject", "rationale": "The use is outside the policy.",
        "decider": "AI governance reviewer", "conditions": "", "exception_rationale": "",
    }, headers=SAME_ORIGIN)
    assert response.status_code == 302
    page = client.get(response.headers["Location"])
    assert b"Reject" in page.data
    assert b"The use is outside the policy." in page.data


def test_standard_result_can_be_approved_without_an_exception(client):
    risk_id = _register(client, "evidence-supported")
    response = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve", "rationale": "No restriction matched.",
        "decider": "GRC analyst", "conditions": "", "exception_rationale": "",
    }, headers=SAME_ORIGIN)
    assert response.status_code == 302
    assert b"No restriction matched." in client.get(f"/risks/{risk_id}").data


def test_decision_post_without_origin_is_rejected(client):
    risk_id = _register(client, "evidence-supported")
    response = client.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve", "rationale": "Should not save.", "decider": "GRC analyst",
    })
    assert response.status_code == 403
    assert b"Should not save." not in client.get(f"/risks/{risk_id}").data


def test_completing_an_action_requires_notes(client, app):
    response = client.post("/demo/high-risk-ai/register", headers=SAME_ORIGIN)
    risk_id = response.headers["Location"].rsplit("/", 1)[-1]
    from app.db import get_db
    from app.services.workflow_service import get_risk
    with app.app_context():
        action = get_risk(get_db(), risk_id)["actions"][0]
    rejected = client.post(f"/remediation/{action['action_id']}", data={
        "risk_id": risk_id, "status": "completed", "owner": "Reviewer", "due_date": "", "completion_notes": ""
    }, headers=SAME_ORIGIN)
    assert rejected.status_code == 400
    accepted = client.post(f"/remediation/{action['action_id']}", data={
        "risk_id": risk_id, "status": "completed", "owner": "Reviewer", "due_date": "",
        "completion_notes": "Retention terms confirmed in contract"
    }, headers=SAME_ORIGIN)
    assert accepted.status_code == 302


def test_non_ascii_basic_credentials_return_401_not_500(tmp_path):
    import base64
    from app import create_app
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "auth.sqlite3"),
                      "REQUIRE_AUTH": True, "DEMO_USERNAME": "demo", "DEMO_PASSWORD": "pw"})
    client = app.test_client()
    bad = base64.b64encode("d\u00e9mo:pw".encode("utf-8")).decode()
    good = base64.b64encode(b"demo:pw").decode()
    assert client.get("/", headers={"Authorization": f"Basic {bad}"}).status_code == 401
    assert client.get("/", headers={"Authorization": f"Basic {good}"}).status_code == 200
