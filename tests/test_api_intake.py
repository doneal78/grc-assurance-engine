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


def _risk_names(client):
    with client.application.app_context():
        return [risk["scenario_name"] for risk in list_risks(get_db())]


def test_explicit_persist_false_still_saves_nothing(client):
    response = client.post("/api/v1/intake/assess", json=payload(persist=False))
    assert response.status_code == 200
    body = response.get_json()
    assert body["persisted"] is False
    assert body["decision"] is None
    assert body["risk_id"] is None
    assert body["residual"]["tier"] == "low"
    assert _risk_names(client) == []


def test_persist_records_a_low_tier_without_treating_it_as_approval(client):
    response = client.post("/api/v1/intake/assess", json=payload(persist=True, decision={
        "disposition": "escalate",
        "rationale": "Low residual tier is not an approval.",
        "decider": "GRC analyst",
    }))
    assert response.status_code == 200
    body = response.get_json()
    assert body["persisted"] is True
    assert body["residual"]["tier"] == "low"
    assert body["automatic_approval"] is None
    assert body["decision"]["disposition"] == "escalate"
    assert body["decision"]["separate_from_score"] is True
    assert body["decision"]["rationale"] == "Low residual tier is not an approval."
    assert body["risk_id"]
    assert _risk_names(client) == ["Northwind Notes"]
    detail = client.get(f"/risks/{body['risk_id']}")
    assert detail.status_code == 200
    assert b"Northwind Notes" in detail.data
    assert b"Escalate" in detail.data
    assert b"not an approval" in detail.data


def test_invalid_persist_decision_writes_no_register_row(client):
    rejected = client.post("/api/v1/intake/assess", json=payload(persist=True, decision={
        "disposition": "accept",
        "rationale": "Not a disposition.",
        "decider": "GRC analyst",
    }))
    assert rejected.status_code == 400
    error = rejected.get_json()
    assert error["error"] == "validation"
    assert error["persisted"] is False
    assert error["assessed"] is False
    assert any("disposition" in problem for problem in error["problems"])

    extra = client.post("/api/v1/intake/assess", json=payload(decision={
        "disposition": "reject",
        "rationale": "This should not be stored.",
        "decider": "GRC analyst",
    }))
    assert extra.status_code == 400
    assert extra.get_json()["persisted"] is False

    prohibited = client.post("/api/v1/intake/assess", json=payload(
        persist=True,
        form=form(ai_use="assistive", decisions_affecting_people="yes"),
        decision={"disposition": "approve", "rationale": "The score looks fine.", "decider": "GRC analyst"},
    ))
    assert prohibited.status_code == 400
    assert any("exception" in problem for problem in prohibited.get_json()["problems"])
    assert _risk_names(client) == []


def test_optional_handling_minutes_persist_or_reject_without_saving(client):
    omitted = client.post("/api/v1/intake/assess", json=payload(persist=True, decision={
        "disposition": "escalate",
        "rationale": "Low residual tier is not an approval.",
        "decider": "GRC analyst",
    }))
    assert omitted.status_code == 200
    body = omitted.get_json()
    assert body["decision"]["handling_minutes"] is None
    assert body["decision"]["disposition"] == "escalate"

    blank = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Blank Minutes"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "Blank means unmeasured.",
            "decider": "GRC analyst",
            "handling_minutes": "",
        },
    ))
    assert blank.status_code == 200
    assert blank.get_json()["decision"]["handling_minutes"] is None

    reported = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Reported Minutes"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "A person typed the minutes.",
            "decider": "GRC analyst",
            "handling_minutes": 40,
        },
    ))
    assert reported.status_code == 200
    reported_body = reported.get_json()
    assert reported_body["decision"]["handling_minutes"] == 40
    assert reported_body["residual"]["tier"] != reported_body["decision"]["disposition"]

    digit_string = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Digit String"),
        persist=True,
        decision={
            "disposition": "reject",
            "rationale": "A digit string is the same whole number.",
            "decider": "GRC analyst",
            "handling_minutes": "18",
        },
    ))
    assert digit_string.status_code == 200
    assert digit_string.get_json()["decision"]["handling_minutes"] == 18

    negative = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Negative Minutes"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "This must not be stored.",
            "decider": "GRC analyst",
            "handling_minutes": -5,
        },
    ))
    assert negative.status_code == 400
    assert negative.get_json()["persisted"] is False
    assert negative.get_json()["assessed"] is False
    assert any("negative" in problem for problem in negative.get_json()["problems"])

    fraction = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Fractional Minutes"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "A fraction must not be rounded.",
            "decider": "GRC analyst",
            "handling_minutes": 12.0,
        },
    ))
    assert fraction.status_code == 400
    assert fraction.get_json()["persisted"] is False
    assert any("fractional" in problem for problem in fraction.get_json()["problems"])
    assert "Fractional Minutes" not in _risk_names(client)
    assert "Negative Minutes" not in _risk_names(client)
    assert "Reported Minutes" in _risk_names(client)


def test_optional_rework_minutes_persist_or_reject_without_saving(client):
    omitted = client.post("/api/v1/intake/assess", json=payload(persist=True, decision={
        "disposition": "escalate",
        "rationale": "Low residual tier is not an approval.",
        "decider": "GRC analyst",
        "handling_minutes": 11,
    }))
    assert omitted.status_code == 200
    body = omitted.get_json()
    assert body["decision"]["handling_minutes"] == 11
    assert body["decision"]["rework_minutes"] is None

    blank = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Blank Rework"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "Blank means unmeasured.",
            "decider": "GRC analyst",
            "rework_minutes": "",
        },
    ))
    assert blank.status_code == 200
    assert blank.get_json()["decision"]["rework_minutes"] is None
    assert blank.get_json()["decision"]["handling_minutes"] is None

    reported = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Reported Rework"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "A person typed the rework minutes.",
            "decider": "GRC analyst",
            "handling_minutes": 6,
            "rework_minutes": 14,
        },
    ))
    assert reported.status_code == 200
    reported_body = reported.get_json()
    assert reported_body["decision"]["rework_minutes"] == 14
    assert reported_body["decision"]["handling_minutes"] == 6

    digit_string = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Rework Digit String"),
        persist=True,
        decision={
            "disposition": "reject",
            "rationale": "A digit string is the same whole number.",
            "decider": "GRC analyst",
            "rework_minutes": "0",
        },
    ))
    assert digit_string.status_code == 200
    assert digit_string.get_json()["decision"]["rework_minutes"] == 0

    negative = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Negative Rework"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "This must not be stored.",
            "decider": "GRC analyst",
            "rework_minutes": -5,
        },
    ))
    assert negative.status_code == 400
    assert negative.get_json()["persisted"] is False
    assert any("rework_minutes" in problem and "negative" in problem for problem in negative.get_json()["problems"])

    fraction = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Fractional Rework"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "A fraction must not be rounded.",
            "decider": "GRC analyst",
            "handling_minutes": 4,
            "rework_minutes": True,
        },
    ))
    assert fraction.status_code == 400
    assert fraction.get_json()["persisted"] is False
    assert any("boolean" in problem for problem in fraction.get_json()["problems"])
    assert "Fractional Rework" not in _risk_names(client)
    assert "Negative Rework" not in _risk_names(client)
    assert "Reported Rework" in _risk_names(client)


def test_optional_manual_touches_persist_or_reject_without_saving(client):
    omitted = client.post("/api/v1/intake/assess", json=payload(persist=True, decision={
        "disposition": "escalate",
        "rationale": "Low residual tier is not an approval.",
        "decider": "GRC analyst",
        "handling_minutes": 11,
        "rework_minutes": 3,
    }))
    assert omitted.status_code == 200
    body = omitted.get_json()
    assert body["decision"]["handling_minutes"] == 11
    assert body["decision"]["rework_minutes"] == 3
    assert body["decision"]["manual_touches"] is None

    blank = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Blank Touches"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "Blank means unmeasured.",
            "decider": "GRC analyst",
            "manual_touches": "",
        },
    ))
    assert blank.status_code == 200
    assert blank.get_json()["decision"]["manual_touches"] is None
    assert blank.get_json()["decision"]["handling_minutes"] is None
    assert blank.get_json()["decision"]["rework_minutes"] is None

    reported = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Reported Touches"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "A person typed the touchpoint count.",
            "decider": "GRC analyst",
            "handling_minutes": 6,
            "rework_minutes": 1,
            "manual_touches": 4,
        },
    ))
    assert reported.status_code == 200
    reported_body = reported.get_json()
    assert reported_body["decision"]["manual_touches"] == 4
    assert reported_body["decision"]["handling_minutes"] == 6
    assert reported_body["decision"]["rework_minutes"] == 1

    digit_string = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Touches Digit String"),
        persist=True,
        decision={
            "disposition": "reject",
            "rationale": "A digit string is the same whole number.",
            "decider": "GRC analyst",
            "manual_touches": "0",
        },
    ))
    assert digit_string.status_code == 200
    assert digit_string.get_json()["decision"]["manual_touches"] == 0

    negative = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Negative Touches"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "This must not be stored.",
            "decider": "GRC analyst",
            "manual_touches": -5,
        },
    ))
    assert negative.status_code == 400
    assert negative.get_json()["persisted"] is False
    assert any("manual_touches" in problem and "negative" in problem for problem in negative.get_json()["problems"])

    fraction = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Fractional Touches"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "A fraction must not be rounded.",
            "decider": "GRC analyst",
            "handling_minutes": 4,
            "manual_touches": True,
        },
    ))
    assert fraction.status_code == 400
    assert fraction.get_json()["persisted"] is False
    assert any("boolean" in problem for problem in fraction.get_json()["problems"])
    assert "Fractional Touches" not in _risk_names(client)
    assert "Negative Touches" not in _risk_names(client)
    assert "Reported Touches" in _risk_names(client)


def test_optional_handoffs_persist_or_reject_without_saving(client):
    omitted = client.post("/api/v1/intake/assess", json=payload(persist=True, decision={
        "disposition": "escalate",
        "rationale": "Low residual tier is not an approval.",
        "decider": "GRC analyst",
        "handling_minutes": 11,
        "rework_minutes": 3,
        "manual_touches": 2,
    }))
    assert omitted.status_code == 200
    body = omitted.get_json()
    assert body["decision"]["handling_minutes"] == 11
    assert body["decision"]["rework_minutes"] == 3
    assert body["decision"]["manual_touches"] == 2
    assert body["decision"]["handoffs"] is None

    blank = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Blank Handoffs"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "Blank means unmeasured.",
            "decider": "GRC analyst",
            "handoffs": "",
        },
    ))
    assert blank.status_code == 200
    assert blank.get_json()["decision"]["handoffs"] is None
    assert blank.get_json()["decision"]["handling_minutes"] is None
    assert blank.get_json()["decision"]["rework_minutes"] is None
    assert blank.get_json()["decision"]["manual_touches"] is None

    reported = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Reported Handoffs"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "A person typed the handoff count.",
            "decider": "GRC analyst",
            "handling_minutes": 6,
            "rework_minutes": 1,
            "manual_touches": 2,
            "handoffs": 4,
        },
    ))
    assert reported.status_code == 200
    reported_body = reported.get_json()
    assert reported_body["decision"]["handoffs"] == 4
    assert reported_body["decision"]["handling_minutes"] == 6
    assert reported_body["decision"]["rework_minutes"] == 1
    assert reported_body["decision"]["manual_touches"] == 2

    digit_string = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Handoffs Digit String"),
        persist=True,
        decision={
            "disposition": "reject",
            "rationale": "A digit string is the same whole number.",
            "decider": "GRC analyst",
            "handoffs": "0",
        },
    ))
    assert digit_string.status_code == 200
    assert digit_string.get_json()["decision"]["handoffs"] == 0

    negative = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Negative Handoffs"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "This must not be stored.",
            "decider": "GRC analyst",
            "handoffs": -5,
        },
    ))
    assert negative.status_code == 400
    assert negative.get_json()["persisted"] is False
    assert any("handoffs" in problem and "negative" in problem for problem in negative.get_json()["problems"])

    fraction = client.post("/api/v1/intake/assess", json=payload(
        form=form(vendor_name="Fractional Handoffs"),
        persist=True,
        decision={
            "disposition": "escalate",
            "rationale": "A fraction must not be rounded.",
            "decider": "GRC analyst",
            "handling_minutes": 4,
            "handoffs": 1.5,
        },
    ))
    assert fraction.status_code == 400
    assert fraction.get_json()["persisted"] is False
    assert any("fractional" in problem for problem in fraction.get_json()["problems"])
    assert "Fractional Handoffs" not in _risk_names(client)
    assert "Negative Handoffs" not in _risk_names(client)
    assert "Reported Handoffs" in _risk_names(client)


def test_cross_site_persist_is_rejected(client):
    response = client.post(
        "/api/v1/intake/assess",
        json=payload(persist=True, decision={
            "disposition": "approve",
            "rationale": "Cross-site attempt.",
            "decider": "Someone else",
        }),
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert _risk_names(client) == []
