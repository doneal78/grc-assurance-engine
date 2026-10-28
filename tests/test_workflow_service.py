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
    assert risk["policy_version"] == "1.1.0"
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
                           payload["decider"], payload["conditions"], payload["exception_rationale"],
                           payload.get("handling_minutes"), payload.get("rework_minutes"))


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


def test_clause_conflict_creates_follow_up_and_can_still_be_approved(db):
    result = run_scenario("contract-clause-conflict")
    risk_id = register_scenario(db, result)
    risk = get_risk(db, risk_id)
    assert risk["policy_outcome"] == "not_prohibited"
    assert risk["inherent_tier"] == "moderate"
    assert risk["residual_tier"] == "low"
    assert len(risk["actions"]) == 1
    assert "CC-001" in risk["actions"][0]["description"]
    assert "score is unchanged" in risk["actions"][0]["description"]
    clause = risk["rationale"]["risk"]["policy"]["required_contract_clauses"][0]
    assert clause["evidence_status"] == "conflicting"
    assert _decision(db, risk_id, disposition="approve", rationale="The conflict is recorded and accepted for now.") == risk_id
    saved = get_risk(db, risk_id)
    assert saved["decision"]["disposition"] == "approve"
    assert saved["decision"]["exception_rationale"] == ""
    assert saved["rationale"]["risk"]["policy"]["required_contract_clauses"][0]["evidence_status"] == "conflicting"


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


def test_existing_decision_survives_adding_escalate(tmp_path):
    from app import create_app
    import sqlite3

    path = tmp_path / "legacy.sqlite3"
    schema = Path("app/schema.sql").read_text(encoding="utf-8").replace(
        "'approve', 'approve_with_conditions', 'escalate', 'reject'",
        "'approve', 'approve_with_conditions', 'reject'",
    )
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.execute(
        """INSERT INTO risks
        (risk_id, scenario_id, scenario_name, risk_statement, inherent_tier, residual_tier,
         rationale_json, created_at, policy_id, policy_version, policy_outcome)
        VALUES ('R-OLD', 'legacy-scenario', 'Legacy', 'Synthetic statement', 'low', 'low', '{}',
                '2026-10-01T00:00:00+00:00', 'ORG-AI-USE', '1.1.0', 'not_prohibited')"""
    )
    connection.execute(
        """INSERT INTO decisions
        (risk_id, disposition, rationale, decider, policy_id, policy_version, rule_set_version,
         prohibited_at_decision, decided_at)
        VALUES ('R-OLD', 'reject', 'Kept.', 'Reviewer', 'ORG-AI-USE', '1.1.0', '0.3.0',
                'not_prohibited', '2026-10-01T00:00:00+00:00')"""
    )
    connection.commit()
    connection.close()
    create_app({"TESTING": True, "DATABASE": str(path), "REQUIRE_AUTH": False})
    connection = sqlite3.connect(path)
    sql = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'decisions'").fetchone()[0]
    row = connection.execute(
        "SELECT disposition, rationale FROM decisions WHERE risk_id = 'R-OLD'"
    ).fetchone()
    connection.close()
    assert "escalate" in sql
    assert row == ("reject", "Kept.")


def _intake(**overrides):
    from datetime import date

    from app.services.intake_builder import build_intake, clause_evidence_field, run_intake
    from app.services.org_policy import load_org_policy

    form = {
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
        form[clause_evidence_field(clause["clause_id"])] = "independent_verified"
    form.update(overrides)
    as_of = date(2026, 10, 14)
    return run_intake(build_intake(form, as_of), as_of)


def _save_intake(db, result=None, **overrides):
    from app.services.workflow_service import register_intake

    decision = {"disposition": "escalate", "rationale": "Low residual tier is not an approval.",
                "decider": "GRC analyst", "conditions": "", "exception_rationale": ""}
    decision.update(overrides)
    return register_intake(db, result or _intake(), decision)


def test_general_intake_save_keeps_the_decision_off_the_score(db):
    from app.services.workflow_service import get_risk, register_intake

    result = _intake()
    assert result["risk"]["residual"]["tier"] == "low"
    risk_id = _save_intake(db, result)
    risk = get_risk(db, risk_id)
    assert risk["scenario_name"] == "Northwind Notes"
    assert risk["scenario_id"].startswith("intake-")
    assert risk["residual_tier"] == "low"
    assert risk["inherent_tier"] == result["risk"]["inherent"]["tier"]
    assert risk["decision"]["disposition"] == "escalate"
    assert risk["decision"]["disposition"] != risk["residual_tier"]
    assert "not an approval" in risk["risk_statement"]
    assert risk["rationale"]["intake_origin"] == "general_intake"
    assert [event["event_type"] for event in risk["events"]] == [
        "intake_received", "risk_created", "decision_recorded",
    ]
    assert list_risks(db)[0]["decision_disposition"] == "escalate"
    again = register_intake(db, result, {"disposition": "reject", "rationale": "A second confirmed save.",
                                         "decider": "GRC analyst"})
    assert again != risk_id
    assert len(list_risks(db)) == 2


def test_intake_with_a_gap_gets_a_follow_up_action(db):
    from app.services.workflow_service import get_risk

    result = _intake(evidence_integration_permissions="contradicts")
    risk_id = _save_intake(db, result, disposition="reject", rationale="The conflict needs a person.")
    risk = get_risk(db, risk_id)
    assert risk["actions"][0]["status"] == "open"
    assert "remediation_created" in [event["event_type"] for event in risk["events"]]
    assert risk["decision"]["disposition"] == "reject"
    assert risk["residual_tier"] == result["risk"]["residual"]["tier"]


def test_invalid_intake_disposition_writes_nothing(db):
    from app.services.workflow_service import WorkflowInputError, register_intake

    result = _intake()
    with pytest.raises(WorkflowInputError, match="disposition"):
        register_intake(db, result, {"disposition": "accept", "rationale": "No.", "decider": "GRC analyst"})
    assert list_risks(db) == []
    prohibited = _intake(ai_use="assistive", decisions_affecting_people="yes")
    with pytest.raises(WorkflowInputError, match="exception rationale"):
        register_intake(db, prohibited, {"disposition": "approve", "rationale": "The score looks low.",
                                         "decider": "GRC analyst"})
    assert list_risks(db) == []
    risk_id = register_intake(db, prohibited, {"disposition": "escalate",
                                               "rationale": "A person is sending this on.",
                                               "decider": "GRC analyst"})
    saved = get_risk(db, risk_id)
    assert saved["decision"]["disposition"] == "escalate"
    assert saved["policy_outcome"] == "prohibited"
    assert saved["decision"]["exception_rationale"] == ""


def test_non_synthetic_intake_is_rejected(db):
    from app.services.workflow_service import WorkflowInputError

    result = _intake()
    result["synthetic_data"] = False
    with pytest.raises(WorkflowInputError):
        _save_intake(db, result)
    assert list_risks(db) == []


def test_omitted_handling_minutes_stay_null(db):
    risk_id = register_scenario(db, run_scenario("evidence-supported"))
    assert _decision(db, risk_id) == risk_id
    decision = get_risk(db, risk_id)["decision"]
    assert decision["handling_minutes"] is None
    assert decision["rework_minutes"] is None
    assert "Self-reported handling minutes" not in get_risk(db, risk_id)["events"][-1]["detail"]
    assert "Self-reported rework minutes" not in get_risk(db, risk_id)["events"][-1]["detail"]
    saved = _save_intake(db)
    intake = get_risk(db, saved)["decision"]
    assert intake["handling_minutes"] is None
    assert intake["rework_minutes"] is None


@pytest.mark.parametrize("value, stored", [
    (25, 25),
    ("25", 25),
    (" 25 ", 25),
    (0, 0),
    ("0", 0),
])
def test_valid_handling_minutes_are_stored(db, value, stored):
    risk_id = register_scenario(db, run_scenario("evidence-supported"))
    assert _decision(db, risk_id, handling_minutes=value) == risk_id
    decision = get_risk(db, risk_id)["decision"]
    assert decision["handling_minutes"] == stored
    assert f"Self-reported handling minutes: {stored}." in get_risk(db, risk_id)["events"][-1]["detail"]


@pytest.mark.parametrize("value", [-1, "-3", "12.5", "12.0", 12.0, True, False, "abc", "01", "+5", "12 minutes", "1e2"])
def test_invalid_handling_minutes_are_rejected_without_coercion(db, value):
    risk_id = register_scenario(db, run_scenario("evidence-supported"))
    _decision(db, risk_id, handling_minutes=15)
    before = get_risk(db, risk_id)["decision"]["decided_at"]
    with pytest.raises(WorkflowInputError, match="handling_minutes"):
        _decision(db, risk_id, disposition="reject", rationale="A later decision.", handling_minutes=value)
    decision = get_risk(db, risk_id)["decision"]
    assert decision["disposition"] == "approve"
    assert decision["handling_minutes"] == 15
    assert decision["decided_at"] == before


def test_blank_handling_minutes_clear_a_previously_reported_value(db):
    risk_id = register_scenario(db, run_scenario("evidence-supported"))
    _decision(db, risk_id, handling_minutes=15)
    _decision(db, risk_id, handling_minutes="")
    decision = get_risk(db, risk_id)["decision"]
    assert decision["handling_minutes"] is None
    _decision(db, risk_id, handling_minutes="   ")
    assert get_risk(db, risk_id)["decision"]["handling_minutes"] is None
    _decision(db, risk_id, handling_minutes=None)
    assert get_risk(db, risk_id)["decision"]["handling_minutes"] is None


def test_invalid_handling_minutes_do_not_save_an_intake(db):
    from app.services.workflow_service import WorkflowInputError, register_intake

    result = _intake()
    with pytest.raises(WorkflowInputError, match="handling_minutes"):
        register_intake(db, result, {
            "disposition": "escalate",
            "rationale": "Low residual tier is not an approval.",
            "decider": "GRC analyst",
            "handling_minutes": "-4",
        })
    assert list_risks(db) == []


def test_existing_decision_gains_a_null_handling_minutes_column(tmp_path):
    from app import create_app
    import sqlite3

    path = tmp_path / "minutes.sqlite3"
    schema = Path("app/schema.sql").read_text(encoding="utf-8")
    for column in ("rework_minutes", "handling_minutes"):
        schema = schema.replace(f",\n    {column} INTEGER", "")
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.execute(
        """INSERT INTO risks
        (risk_id, scenario_id, scenario_name, risk_statement, inherent_tier, residual_tier,
         rationale_json, created_at, policy_id, policy_version, policy_outcome)
        VALUES ('R-OLD', 'legacy-minutes', 'Legacy', 'Synthetic statement', 'low', 'low', '{}',
                '2026-10-01T00:00:00+00:00', 'ORG-AI-USE', '1.1.0', 'not_prohibited')"""
    )
    connection.execute(
        """INSERT INTO decisions
        (risk_id, disposition, rationale, decider, policy_id, policy_version, rule_set_version,
         prohibited_at_decision, decided_at)
        VALUES ('R-OLD', 'reject', 'Kept.', 'Reviewer', 'ORG-AI-USE', '1.1.0', '0.3.0',
                'not_prohibited', '2026-10-01T00:00:00+00:00')"""
    )
    connection.commit()
    connection.close()
    create_app({"TESTING": True, "DATABASE": str(path), "REQUIRE_AUTH": False})
    connection = sqlite3.connect(path)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(decisions)")]
    row = connection.execute(
        "SELECT disposition, handling_minutes, rework_minutes FROM decisions WHERE risk_id = 'R-OLD'"
    ).fetchone()
    connection.close()
    assert "handling_minutes" in columns
    assert "rework_minutes" in columns
    assert row == ("reject", None, None)


def test_existing_decision_gains_a_null_rework_minutes_column(tmp_path):
    from app import create_app
    import sqlite3

    path = tmp_path / "rework.sqlite3"
    schema = Path("app/schema.sql").read_text(encoding="utf-8").replace(
        ",\n    rework_minutes INTEGER", "",
    )
    connection = sqlite3.connect(path)
    connection.executescript(schema)
    connection.execute(
        """INSERT INTO risks
        (risk_id, scenario_id, scenario_name, risk_statement, inherent_tier, residual_tier,
         rationale_json, created_at, policy_id, policy_version, policy_outcome)
        VALUES ('R-OLD', 'legacy-rework', 'Legacy', 'Synthetic statement', 'low', 'low', '{}',
                '2026-10-01T00:00:00+00:00', 'ORG-AI-USE', '1.1.0', 'not_prohibited')"""
    )
    connection.execute(
        """INSERT INTO decisions
        (risk_id, disposition, rationale, decider, policy_id, policy_version, rule_set_version,
         prohibited_at_decision, decided_at, handling_minutes)
        VALUES ('R-OLD', 'reject', 'Kept.', 'Reviewer', 'ORG-AI-USE', '1.1.0', '0.3.0',
                'not_prohibited', '2026-10-01T00:00:00+00:00', 12)"""
    )
    connection.commit()
    connection.close()
    create_app({"TESTING": True, "DATABASE": str(path), "REQUIRE_AUTH": False})
    connection = sqlite3.connect(path)
    columns = [row[1] for row in connection.execute("PRAGMA table_info(decisions)")]
    row = connection.execute(
        "SELECT disposition, handling_minutes, rework_minutes FROM decisions WHERE risk_id = 'R-OLD'"
    ).fetchone()
    connection.close()
    assert "rework_minutes" in columns
    assert row == ("reject", 12, None)


@pytest.mark.parametrize("value, stored", [
    (25, 25),
    ("25", 25),
    (" 25 ", 25),
    (0, 0),
    ("0", 0),
])
def test_valid_rework_minutes_are_stored(db, value, stored):
    risk_id = register_scenario(db, run_scenario("evidence-supported"))
    assert _decision(db, risk_id, handling_minutes=15, rework_minutes=value) == risk_id
    decision = get_risk(db, risk_id)["decision"]
    assert decision["rework_minutes"] == stored
    assert decision["handling_minutes"] == 15
    detail = get_risk(db, risk_id)["events"][-1]["detail"]
    assert f"Self-reported rework minutes: {stored}." in detail
    assert "Self-reported handling minutes: 15." in detail


@pytest.mark.parametrize("value", [-1, "-3", "12.5", "12.0", 12.0, True, False, "abc", "01", "+5", "12 minutes", "1e2"])
def test_invalid_rework_minutes_are_rejected_without_coercion(db, value):
    risk_id = register_scenario(db, run_scenario("evidence-supported"))
    _decision(db, risk_id, handling_minutes=15, rework_minutes=40)
    before = get_risk(db, risk_id)["decision"]["decided_at"]
    with pytest.raises(WorkflowInputError, match="rework_minutes"):
        _decision(db, risk_id, disposition="reject", rationale="A later decision.", rework_minutes=value)
    decision = get_risk(db, risk_id)["decision"]
    assert decision["disposition"] == "approve"
    assert decision["handling_minutes"] == 15
    assert decision["rework_minutes"] == 40
    assert decision["decided_at"] == before


def test_blank_rework_minutes_clear_a_previously_reported_value(db):
    risk_id = register_scenario(db, run_scenario("evidence-supported"))
    _decision(db, risk_id, handling_minutes=15, rework_minutes=40)
    _decision(db, risk_id, handling_minutes=15, rework_minutes="")
    decision = get_risk(db, risk_id)["decision"]
    assert decision["handling_minutes"] == 15
    assert decision["rework_minutes"] is None
    _decision(db, risk_id, handling_minutes=15, rework_minutes="   ")
    assert get_risk(db, risk_id)["decision"]["rework_minutes"] is None
    _decision(db, risk_id, handling_minutes=15, rework_minutes=None)
    assert get_risk(db, risk_id)["decision"]["rework_minutes"] is None
    assert get_risk(db, risk_id)["decision"]["handling_minutes"] == 15


def test_invalid_rework_minutes_do_not_save_an_intake(db):
    from app.services.workflow_service import WorkflowInputError, register_intake

    result = _intake()
    with pytest.raises(WorkflowInputError, match="rework_minutes"):
        register_intake(db, result, {
            "disposition": "escalate",
            "rationale": "Low residual tier is not an approval.",
            "decider": "GRC analyst",
            "handling_minutes": 9,
            "rework_minutes": "-4",
        })
    assert list_risks(db) == []
