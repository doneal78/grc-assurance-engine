"""Phase 1 tests: application factory, health route, and dashboard."""

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
    assert client.get("/health").status_code == 200
    assert client.get("/", auth=("demo", "wrong password")).status_code == 401
    assert client.get("/", auth=("demo", "correct horse battery staple")).status_code == 200


def test_health_returns_documented_response(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": "grc-assurance-engine"}


def test_health_rejects_post(client):
    assert client.post("/health").status_code == 405


def test_unknown_route_returns_404(client):
    assert client.get("/does-not-exist").status_code == 404


def test_dashboard_shows_honest_empty_state(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Three repeatable scenarios" in response.data
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


def test_methodology_page_explains_cost_limits(client):
    response = client.get("/methodology")
    assert response.status_code == 200
    assert b"labor capacity, not cash savings" in response.data


def test_methodology_page_lists_escalation_assessments(client):
    response = client.get("/methodology")
    assert response.status_code == 200
    body = response.data
    assert b"0.2.0" in body
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
