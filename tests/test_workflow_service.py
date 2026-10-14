"""Persistence, relationships, and validation for the local workflow."""

import sqlite3
from pathlib import Path

import pytest

from app.services.scenario_runner import run_scenario
from app.services.workflow_service import (
    WorkflowInputError, get_risk, list_risks, register_scenario, update_action,
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
