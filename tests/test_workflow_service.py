"""Persistence, relationships, and validation for the local workflow."""

import sqlite3
from pathlib import Path

import pytest

from app.services.scenario_runner import run_scenario
from app.services.workflow_service import (
    WorkflowInputError, get_risk, list_risks, record_decision, register_scenario, update_action,
)


@pytest.fixture
def db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    schema = Path("app/schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema)
    yield connection
    connection.close()


def test_saving_scenario_persists_trace_links_action_and_events(db):
    result = run_scenario("conflicting-claims")
    risk_id = register_scenario(db, result)
    risk = get_risk(db, risk_id)
    assert risk["scenario_id"] == "conflicting-claims"
    assert risk["inherent_tier"] == result["risk"]["inherent"]["tier"]
    assert any(claim["evidence_status"] == "conflicting" for claim in risk["rationale"]["claims"])
    assert [action["status"] for action in risk["actions"]] == ["open"]
    assert [event["event_type"] for event in risk["events"]] == ["risk_created", "remediation_created"]
    assert list_risks(db)[0]["open_action_count"] == 1


def test_register_is_idempotent_per_scenario(db):
    result = run_scenario("high-risk-ai")
    first = register_scenario(db, result)
    second = register_scenario(db, result)
    assert first == second
    assert len(list_risks(db)) == 1
    assert len(get_risk(db, first)["actions"]) == 1


def test_action_status_and_notes_are_persisted_with_event(db):
    risk_id = register_scenario(db, run_scenario("high-risk-ai"))
    action = get_risk(db, risk_id)["actions"][0]
    assert update_action(db, action["action_id"], "completed", "Reviewer A", "2026-11-01", "Gaps reviewed") == risk_id
    risk = get_risk(db, risk_id)
    assert risk["actions"][0]["status"] == "completed"
    assert risk["actions"][0]["completion_notes"] == "Gaps reviewed"
    assert risk["events"][-1]["event_type"] == "remediation_updated"
    assert list_risks(db)[0]["open_action_count"] == 0


@pytest.mark.parametrize("status, owner, due_date, notes", [
    ("closed", "Owner", "2026-12-01", ""),
    ("open", "", "2026-12-01", ""),
    ("open", "Owner", "next month", ""),
    ("open", "Owner", "", "x" * 1001),
    ("completed", "Owner", "", ""),
    ("completed", "Owner", "", "   "),
])
def test_invalid_action_updates_are_rejected(db, status, owner, due_date, notes):
    risk_id = register_scenario(db, run_scenario("high-risk-ai"))
    action = get_risk(db, risk_id)["actions"][0]
    with pytest.raises(WorkflowInputError):
        update_action(db, action["action_id"], status, owner, due_date, notes)
    assert get_risk(db, risk_id)["actions"][0]["status"] == "open"


def test_saving_a_non_synthetic_result_is_rejected(db):
    result = run_scenario("evidence-supported")
    result["synthetic_data"] = False
    with pytest.raises(WorkflowInputError):
        register_scenario(db, result)


def test_prohibited_scenario_creates_a_follow_up_without_an_escalation(db):
    result = run_scenario("prohibited-ai-decisions")
    risk_id = register_scenario(db, result)
    risk = get_risk(db, risk_id)
    assert risk["policy_outcome"] == "prohibited"
    assert risk["policy_id"] == "ORG-AI-USE"
    assert risk["policy_version"] == "1.0.0"
    assert risk["inherent_tier"] == "moderate"
    assert risk["residual_tier"] == "low"
    assert len(risk["actions"]) == 1
    assert "exception rationale" in risk["actions"][0]["description"]
    assert risk["decision"] is None
    assert list_risks(db)[0]["decision_disposition"] is None


def _decision(db, risk_id, **overrides):
    payload = {"disposition": "approve", "rationale": "Reviewed the saved result.",
               "decider": "GRC analyst", "conditions": "", "exception_rationale": ""}
    payload.update(overrides)
    return record_decision(db, risk_id, payload["disposition"], payload["rationale"],
                           payload["decider"], payload["conditions"], payload["exception_rationale"])


def test_decision_copies_policy_and_rule_set_from_the_assessment(db):
    result = run_scenario("evidence-supported")
    risk_id = register_scenario(db, result)
    assert _decision(db, risk_id, disposition="approve_with_conditions",
                     conditions="  Limit the integration to the named workspace.  ") == risk_id
    risk = get_risk(db, risk_id)
    decision = risk["decision"]
    assert decision["disposition"] == "approve_with_conditions"
    assert decision["conditions"] == "Limit the integration to the named workspace."
    assert decision["rationale"] == "Reviewed the saved result."
    assert decision["decider"] == "GRC analyst"
    assert decision["exception_rationale"] == ""
    assert decision["policy_id"] == result["risk"]["policy"]["policy_id"]
    assert decision["policy_version"] == result["risk"]["policy"]["policy_version"]
    assert decision["rule_set_version"] == result["risk"]["rule_set_version"]
    assert decision["prohibited_at_decision"] == "not_prohibited"
    assert decision["decided_at"]
    assert risk["events"][-1]["event_type"] == "decision_recorded"
    assert "ORG-AI-USE" in risk["events"][-1]["detail"]
    assert list_risks(db)[0]["decision_disposition"] == "approve_with_conditions"


def test_prohibited_approval_requires_an_exception_and_reject_does_not(db):
    risk_id = register_scenario(db, run_scenario("prohibited-ai-decisions"))
    before = len(get_risk(db, risk_id)["events"])
    with pytest.raises(WorkflowInputError, match="exception rationale"):
        _decision(db, risk_id, disposition="approve")
    with pytest.raises(WorkflowInputError, match="exception rationale"):
        _decision(db, risk_id, disposition="approve_with_conditions", conditions="Officer reviews each case.")
    assert len(get_risk(db, risk_id)["events"]) == before
    assert get_risk(db, risk_id)["decision"] is None

    assert _decision(db, risk_id, disposition="reject", rationale="The use is outside policy.") == risk_id
    rejected = get_risk(db, risk_id)
    assert rejected["decision"]["disposition"] == "reject"
    assert rejected["decision"]["exception_rationale"] == ""
    assert rejected["rationale"]["risk"]["policy_outcome"]["status"] == "prohibited"

    with pytest.raises(WorkflowInputError, match="only recorded when approving"):
        _decision(db, risk_id, disposition="reject", exception_rationale="Not an exception.")

    assert _decision(db, risk_id, disposition="approve_with_conditions",
                     conditions="A named officer decides each eligibility case.",
                     exception_rationale="The model output is advisory and the officer remains the decider.") == risk_id
    approved = get_risk(db, risk_id)
    assert approved["decision"]["disposition"] == "approve_with_conditions"
    assert approved["decision"]["exception_rationale"].startswith("The model output is advisory")
    assert approved["decision"]["prohibited_at_decision"] == "prohibited"
    assert approved["rationale"]["risk"]["policy_outcome"]["status"] == "prohibited"
    assert [event["event_type"] for event in approved["events"]].count("decision_recorded") == 2
    assert "Replaces reject" in approved["events"][-1]["detail"]


def test_exception_is_rejected_when_the_result_is_not_prohibited(db):
    risk_id = register_scenario(db, run_scenario("evidence-supported"))
    with pytest.raises(WorkflowInputError, match="only recorded when approving"):
        _decision(db, risk_id, exception_rationale="There is nothing to override.")
    assert get_risk(db, risk_id)["decision"] is None


@pytest.mark.parametrize("overrides", [
    {"disposition": "accept"},
    {"rationale": "   "},
    {"decider": ""},
    {"decider": "x" * 101},
    {"rationale": "x" * 1001},
    {"disposition": "approve", "conditions": "Should be empty"},
    {"disposition": "approve_with_conditions", "conditions": "  "},
    {"conditions": 12},
])
def test_invalid_decisions_are_rejected(db, overrides):
    risk_id = register_scenario(db, run_scenario("evidence-supported"))
    with pytest.raises(WorkflowInputError):
        _decision(db, risk_id, **overrides)
    assert get_risk(db, risk_id)["decision"] is None


def test_missing_risk_returns_none(db):
    assert record_decision(db, "R-MISSING", "reject", "No such risk.", "Reviewer") is None


def test_old_database_gains_policy_columns_and_decisions(tmp_path):
    from app import create_app
    import sqlite3

    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """CREATE TABLE risks (
            risk_id TEXT PRIMARY KEY,
            scenario_id TEXT NOT NULL UNIQUE,
            scenario_name TEXT NOT NULL,
            risk_statement TEXT NOT NULL,
            inherent_tier TEXT NOT NULL,
            residual_tier TEXT NOT NULL,
            rationale_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );"""
    )
    connection.close()
    create_app({"TESTING": True, "DATABASE": str(path), "REQUIRE_AUTH": False})
    connection = sqlite3.connect(path)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(risks)")}
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    connection.close()
    assert {"policy_id", "policy_version", "policy_outcome"} <= columns
    assert "decisions" in tables
