"""HTTP JSON intake API. Computes a result and does not save it."""

import json
from datetime import date

import pytest

from app import create_app
from app.db import get_db
from app.services.bot_intake import assess_request
from app.services.intake_builder import clause_evidence_field
from app.services.org_policy import load_org_policy
from app.services.workflow_service import list_risks

AS_OF = "2026-10-14"
SAME_ORIGIN = {"Origin": "http://localhost"}


def form(**overrides):
    base = {
        "vendor_name": "Northwind Notes",
        "data_sensitivity": "internal",
        "integration_permissions": "read_only",
        "ai_use": "none",
        "model_training_on_customer_data": "no",
        "external_exposure": "internal_only",
        "retention_deletion": "documented",
        "decisions_affecting_people": "no",
        "evidence_integration_permissions": "independent_verified",
        "trust_center_url": "",
        "trust_soc2": "independent_verified",
        "trust_security": "independent_verified",
        "trust_privacy": "independent_verified",
    }
    for clause in load_org_policy()["required_contract_clauses"]:
        base[clause_evidence_field(clause["clause_id"])] = "independent_verified"
    base.update(overrides)
    return base


def payload(**overrides):
    body = {"as_of": AS_OF, "form": form()}
    body.update(overrides)
    return body


@pytest.fixture
def gated_app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "auth.sqlite3"),
        "REQUIRE_AUTH": True,
        "DEMO_USERNAME": "demo",
        "DEMO_PASSWORD": "correct horse battery staple",
    })


def test_contract_lists_live_fields(client):
    response = client.get("/api/v1/intake/contract")
    assert response.status_code == 200
    body = response.get_json()
    assert body["contract"] == "grc.intake.contract"
    assert body["persisted"] is False
    assert body["automatic_approval"] is None
    assert body["human_review_required"] is True
    columns = [item["column"] for item in body["fields"]]
    assert columns[0] == "vendor_name"
    assert "decisions_affecting_people" in columns
    assert "evidence_clause_CC-001" in columns
    assert body["endpoints"]["assess"]["path"] == "/api/v1/intake/assess"
    assert "python -m app.cli assess" in body["cli"]["assess"]


def test_assess_matches_the_service_and_saves_nothing(client):
    with client.application.app_context():
        before = list_risks(get_db())
    response = client.post("/api/v1/intake/assess", json=payload())
    assert response.status_code == 200
    assert response.is_json
    body = response.get_json()
    assert body == assess_request(payload())
    assert body["residual"]["tier"] == "low"
    assert body["persisted"] is False
    assert body["automatic_approval"] is None
    with client.application.app_context():
        assert list_risks(get_db()) == before


def test_policy_restriction_and_validation_errors(client):
    blocked = client.post("/api/v1/intake/assess", json=payload(
        form=form(ai_use="assistive", decisions_affecting_people="yes")))
    assert blocked.status_code == 200
    body = blocked.get_json()
    assert body["policy_outcome"]["status"] == "prohibited"
    assert body["policy_outcome"]["restrictions"][0]["restriction_id"] == "HR-001"
    assert body["review_path"] == "escalated_review"
    assert body["persisted"] is False

    missing = client.post("/api/v1/intake/assess", json={"as_of": AS_OF, "form": {}})
    assert missing.status_code == 400
    error = missing.get_json()
    assert error["error"] == "validation"
    assert error["assessed"] is False
    assert error["persisted"] is False
    assert any("vendor_name" in problem for problem in error["problems"])

    injected = form()
    injected["residual_tier"] = "low"
    rejected = client.post("/api/v1/intake/assess", json={"as_of": AS_OF, "form": injected})
    assert rejected.status_code == 400
    assert rejected.get_json()["assessed"] is False


def test_content_type_cross_site_and_size(client):
    plain = client.post("/api/v1/intake/assess", data=json.dumps(payload()))
    assert plain.status_code == 415
    assert plain.get_json()["error"] == "validation"

    cross_site = client.post(
        "/api/v1/intake/assess", json=payload(), headers={"Origin": "https://evil.example"})
    assert cross_site.status_code == 403

    same_origin = client.post("/api/v1/intake/assess", json=payload(), headers=SAME_ORIGIN)
    assert same_origin.status_code == 200

    huge = {"as_of": AS_OF, "form": {"vendor_name": "n" * 20000}}
    assert client.post("/api/v1/intake/assess", json=huge).status_code == 413
    assert client.get("/api/v1/intake/assess").status_code == 405


def test_engine_error_returns_500(client, monkeypatch):
    def boom(_intake, _as_of):
        raise RuntimeError("rules failed")

    monkeypatch.setattr("app.services.bot_intake.run_intake", boom)
    response = client.post("/api/v1/intake/assess", json=payload())
    assert response.status_code == 500
    body = response.get_json()
    assert body["error"] == "engine"
    assert body["assessed"] is False
    assert body["persisted"] is False
    assert "rules failed" in body["problems"][0]


def test_auth_gate_applies_when_required(gated_app):
    client = gated_app.test_client()
    assert client.get("/api/v1/intake/contract").status_code == 401
    assert client.post("/api/v1/intake/assess", json=payload()).status_code == 401
    authed = client.post(
        "/api/v1/intake/assess", json=payload(),
        auth=("demo", "correct horse battery staple"),
    )
    assert authed.status_code == 200
    assert authed.get_json()["persisted"] is False
    assert client.get("/try/").status_code == 200


def test_api_date_is_the_evaluation_date(client):
    response = client.post("/api/v1/intake/assess", json=payload())
    assert response.get_json()["as_of"] == date(2026, 10, 14).isoformat()
