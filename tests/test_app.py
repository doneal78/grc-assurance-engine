"""Phase 1 tests: application factory, health route, and dashboard."""

from app import create_app


def test_factory_defaults_to_not_testing():
    assert create_app().testing is False


def test_factory_applies_test_config(app):
    assert app.testing is True
    assert app.config["DATABASE"].endswith("test.sqlite3")


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


def test_unknown_demo_scenario_returns_404(client):
    assert client.get("/demo/not-a-scenario").status_code == 404


def test_scenario_can_be_added_to_register(client):
    response = client.post("/demo/high-risk-ai/register")
    assert response.status_code == 302
    detail = client.get(response.headers["Location"])
    assert detail.status_code == 200
    assert b"Remediation actions" in detail.data
    assert b"Workflow history" in detail.data
    assert client.get("/risks").status_code == 200


def test_remediation_form_validates_and_saves(client, app):
    response = client.post("/demo/high-risk-ai/register")
    risk_id = response.headers["Location"].rsplit("/", 1)[-1]
    from app.db import get_db
    from app.services.workflow_service import get_risk
    with app.app_context():
        action = get_risk(get_db(), risk_id)["actions"][0]
    invalid = client.post(f"/remediation/{action['action_id']}", data={
        "risk_id": risk_id, "status": "done", "owner": "Reviewer", "due_date": "", "completion_notes": ""
    })
    assert invalid.status_code == 400
    assert b"INPUT NOT SAVED" in invalid.data
    updated = client.post(f"/remediation/{action['action_id']}", data={
        "risk_id": risk_id, "status": "in_progress", "owner": "Reviewer", "due_date": "2026-11-01", "completion_notes": ""
    })
    assert updated.status_code == 302
    assert client.get(updated.headers["Location"]).status_code == 200


def test_stylesheet_is_served(client):
    assert client.get("/static/css/styles.css").status_code == 200


def test_methodology_page_explains_cost_limits(client):
    response = client.get("/methodology")
    assert response.status_code == 200
    assert b"labor capacity, not cash savings" in response.data
