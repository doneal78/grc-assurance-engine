"""Observed workflow metrics from persisted rows and event timestamps."""

import json
import sqlite3
from pathlib import Path

from app.services.scenario_runner import run_scenario
from app.services.workflow_metrics import (
    REMEDIATION_STATUSES, format_elapsed_seconds, observed_metrics, summarize_register,
)
from app.services.workflow_service import (
    ACTION_STATUSES, DISPOSITIONS, get_risk, record_decision, register_scenario, update_action,
)
from tests.test_workflow_service import _save_intake


def _db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(Path("app/schema.sql").read_text(encoding="utf-8"))
    return connection


def _stamp(db, risk_id, event_type, occurred_at, index=0):
    rows = db.execute(
        """SELECT event_id FROM workflow_events
           WHERE risk_id = ? AND event_type = ? ORDER BY event_id""",
        (risk_id, event_type),
    ).fetchall()
    db.execute(
        "UPDATE workflow_events SET occurred_at = ? WHERE event_id = ?",
        (occurred_at, rows[index]["event_id"]),
    )
    db.commit()


def _partition(metrics):
    cycle = metrics["cycle_time"]
    excluded = cycle["excluded"]
    return (cycle["measured_count"] + excluded["no_intake_event"]
            + excluded["no_disposition_event"] + excluded["unusable_timestamps"])


def _counts(rows):
    return {row["name"]: row["count"] for row in rows}


def _risk(risk_id, scenario_id="scenario-a", tier="low", claims=None, clauses=None,
          origin=None, rationale=None):
    if rationale is None:
        stored = {"claims": [{"evidence_status": "verified"}] if claims is None else claims,
                  "risk": {"policy": {}}}
        if clauses is not None:
            stored["risk"]["policy"]["required_contract_clauses"] = clauses
        if origin:
            stored["intake_origin"] = origin
        rationale = json.dumps(stored)
    return {"risk_id": risk_id, "scenario_id": scenario_id, "residual_tier": tier,
            "rationale_json": rationale}


def _event(risk_id, event_type, occurred_at):
    return {"risk_id": risk_id, "event_type": event_type, "occurred_at": occurred_at}


def test_status_vocabulary_matches_the_workflow_service():
    assert set(REMEDIATION_STATUSES) == ACTION_STATUSES
    empty = summarize_register([], [], [], [])
    assert [row["name"] for row in empty["dispositions"]["by_disposition"]] == list(DISPOSITIONS)
    assert [row["name"] for row in empty["residual_tiers"]] == [
        "low", "moderate", "high", "critical", "undetermined",
    ]


def test_empty_database_reports_zeros_and_leaves_cycle_time_unmeasured():
    db = _db()
    metrics = observed_metrics(db)
    assert metrics["kind"] == "observed"
    assert metrics["definition_version"] == "1"
    assert metrics["feeds_cost_model"] is False
    assert "cash_savings" not in metrics
    assert "net_capacity_value" not in metrics
    assert metrics["assessment_volume"] == {"total": 0, "general_intake": 0, "scenario_fixture": 0}
    assert metrics["remediation"]["not_completed"] == 0
    assert metrics["remediation"]["total"] == 0
    assert metrics["claim_count"] == 0
    assert metrics["clause_count"] == 0
    assert metrics["dispositions"]["recorded"] == 0
    assert metrics["dispositions"]["risks_without_decision"] == 0
    assert metrics["decision_event_count"] == 0
    assert all(row["count"] == 0 for row in metrics["evidence_statuses"])
    assert all(row["count"] == 0 for row in metrics["residual_tiers"])
    cycle = metrics["cycle_time"]
    assert cycle["measured_count"] == 0
    assert cycle["median_seconds"] is None
    assert cycle["mean_seconds"] is None
    assert cycle["total_seconds"] == 0
    assert cycle["excluded"] == {
        "no_intake_event": 0, "no_disposition_event": 0, "unusable_timestamps": 0,
    }
    assert _partition(metrics) == 0
    assert observed_metrics(db) == metrics
    db.close()


def test_scenario_only_rows_are_counted_and_excluded_from_cycle_time():
    db = _db()
    supported = run_scenario("evidence-supported")
    high = run_scenario("high-risk-ai")
    supported_id = register_scenario(db, supported)
    high_id = register_scenario(db, high)
    record_decision(db, supported_id, "approve", "Reviewed the saved result.", "GRC analyst")
    action = get_risk(db, high_id)["actions"][0]
    update_action(db, action["action_id"], "in_progress", "Reviewer A", "2026-11-01", "")

    before = db.execute("SELECT COUNT(*) AS n FROM workflow_events").fetchone()["n"]
    metrics = observed_metrics(db)
    after = db.execute("SELECT COUNT(*) AS n FROM workflow_events").fetchone()["n"]
    assert before == after

    assert metrics["assessment_volume"] == {"total": 2, "general_intake": 0, "scenario_fixture": 2}
    assert metrics["cycle_time"]["measured_count"] == 0
    assert metrics["cycle_time"]["excluded"]["no_intake_event"] == 2
    assert metrics["dispositions"]["recorded"] == 1
    assert metrics["dispositions"]["risks_without_decision"] == 1
    assert _counts(metrics["dispositions"]["by_disposition"])["approve"] == 1
    assert metrics["decision_event_count"] == 1
    assert metrics["remediation"]["not_completed"] == 1
    assert _counts(metrics["remediation"]["by_status"])["in_progress"] == 1
    assert _partition(metrics) == 2

    expected_claims = {}
    expected_clauses = {}
    expected_tiers = {}
    for result in (supported, high):
        expected_tiers[result["risk"]["residual"]["tier"]] = expected_tiers.get(
            result["risk"]["residual"]["tier"], 0) + 1
        for claim in result["claims"]:
            status = claim["evidence_status"]
            expected_claims[status] = expected_claims.get(status, 0) + 1
        for clause in result["risk"]["policy"]["required_contract_clauses"]:
            status = clause["evidence_status"]
            expected_clauses[status] = expected_clauses.get(status, 0) + 1
    assert {name: count for name, count in _counts(metrics["residual_tiers"]).items() if count} == expected_tiers
    assert {name: count for name, count in _counts(metrics["evidence_statuses"]).items() if count} == expected_claims
    assert {name: count for name, count in _counts(metrics["clause_evidence_statuses"]).items() if count} == expected_clauses

    update_action(db, action["action_id"], "completed", "Reviewer A", "2026-11-01", "Gaps reviewed.")
    assert observed_metrics(db)["remediation"]["not_completed"] == 0
    db.close()


def test_persisted_intake_measures_elapsed_time_between_its_events():
    db = _db()
    same_second = _save_intake(db)
    later = _save_intake(db)
    _stamp(db, same_second, "intake_received", "2026-10-01T00:00:00+00:00")
    _stamp(db, same_second, "decision_recorded", "2026-10-01T00:00:00+00:00")
    _stamp(db, later, "intake_received", "2026-10-01T00:00:00+00:00")
    _stamp(db, later, "decision_recorded", "2026-10-01T00:02:00+00:00")

    metrics = observed_metrics(db)
    assert metrics["assessment_volume"] == {"total": 2, "general_intake": 2, "scenario_fixture": 0}
    assert _counts(metrics["dispositions"]["by_disposition"])["escalate"] == 2
    cycle = metrics["cycle_time"]
    assert cycle["measured_count"] == 2
    assert cycle["zero_span_count"] == 1
    assert cycle["minimum_seconds"] == 0
    assert cycle["maximum_seconds"] == 120
    assert cycle["median_seconds"] == 60
    assert cycle["mean_seconds"] == 60
    assert cycle["total_seconds"] == 120
    assert cycle["median_label"] == "60 elapsed seconds"
    assert cycle["excluded"] == {
        "no_intake_event": 0, "no_disposition_event": 0, "unusable_timestamps": 0,
    }
    assert _partition(metrics) == 2
    db.close()


def test_cycle_time_uses_the_earliest_timestamp_of_each_event():
    db = _db()
    risk_id = _save_intake(db)
    record_decision(db, risk_id, "reject", "A later human decision.", "GRC analyst")
    _stamp(db, risk_id, "intake_received", "2026-10-01T00:00:00+00:00")
    _stamp(db, risk_id, "decision_recorded", "2026-10-01T00:05:00+00:00", index=0)
    _stamp(db, risk_id, "decision_recorded", "2026-10-01T00:01:00+00:00", index=1)
    metrics = observed_metrics(db)
    assert metrics["cycle_time"]["median_seconds"] == 60
    assert metrics["decision_event_count"] == 2
    assert metrics["dispositions"]["recorded"] == 1
    assert _counts(metrics["dispositions"]["by_disposition"])["reject"] == 1
    db.close()


def test_mixed_register_measures_only_the_intake_span():
    db = _db()
    register_scenario(db, run_scenario("evidence-supported"))
    risk_id = _save_intake(db)
    _stamp(db, risk_id, "intake_received", "2026-10-01T00:00:00+00:00")
    _stamp(db, risk_id, "decision_recorded", "2026-10-01T00:00:30+00:00")
    metrics = observed_metrics(db)
    assert metrics["assessment_volume"] == {"total": 2, "general_intake": 1, "scenario_fixture": 1}
    assert metrics["cycle_time"]["measured_count"] == 1
    assert metrics["cycle_time"]["median_seconds"] == 30
    assert metrics["cycle_time"]["excluded"]["no_intake_event"] == 1
    assert _partition(metrics) == 2
    db.close()


def test_unusable_and_missing_events_stay_out_of_the_average():
    db = _db()
    missing_event = _save_intake(db)
    reversed_pair = _save_intake(db)
    garbage = _save_intake(db)
    naive = _save_intake(db)
    db.execute(
        "DELETE FROM workflow_events WHERE risk_id = ? AND event_type = 'decision_recorded'",
        (missing_event,),
    )
    _stamp(db, reversed_pair, "intake_received", "2026-10-01T00:02:00+00:00")
    _stamp(db, reversed_pair, "decision_recorded", "2026-10-01T00:00:00+00:00")
    _stamp(db, garbage, "intake_received", "2026-10-01T00:00:00+00:00")
    _stamp(db, garbage, "decision_recorded", "yesterday")
    _stamp(db, naive, "intake_received", "2026-10-01T00:00:00")
    _stamp(db, naive, "decision_recorded", "2026-10-01T00:01:00+00:00")
    db.commit()

    metrics = observed_metrics(db)
    assert metrics["cycle_time"]["measured_count"] == 0
    assert metrics["cycle_time"]["median_seconds"] is None
    assert metrics["cycle_time"]["excluded"] == {
        "no_intake_event": 0, "no_disposition_event": 1, "unusable_timestamps": 3,
    }
    assert metrics["dispositions"]["recorded"] == 4
    assert metrics["dispositions"]["risks_without_decision"] == 0
    assert _partition(metrics) == 4
    db.close()


def test_equivalent_offsets_fractional_seconds_and_zulu_timestamps():
    db = _db()
    same_instant = _save_intake(db)
    half_second = _save_intake(db)
    zulu = _save_intake(db)
    _stamp(db, same_instant, "intake_received", "2026-10-01T12:00:00+00:00")
    _stamp(db, same_instant, "decision_recorded", "2026-10-01T13:00:00+01:00")
    _stamp(db, half_second, "intake_received", "2026-10-01T00:00:00+00:00")
    _stamp(db, half_second, "decision_recorded", "2026-10-01T00:00:00.500000+00:00")
    _stamp(db, zulu, "intake_received", "2026-10-01T00:00:00Z")
    _stamp(db, zulu, "decision_recorded", "2026-10-01T00:00:30Z")
    cycle = observed_metrics(db)["cycle_time"]
    assert cycle["measured_count"] == 3
    assert cycle["zero_span_count"] == 1
    assert cycle["minimum_seconds"] == 0
    assert cycle["median_seconds"] == 0.5
    assert cycle["maximum_seconds"] == 30
    assert cycle["total_seconds"] == 30.5
    db.close()


def test_unreadable_rationale_keeps_the_volume_and_the_stored_tier():
    db = _db()
    risk_id = register_scenario(db, run_scenario("evidence-supported"))
    tier = get_risk(db, risk_id)["residual_tier"]
    db.execute("UPDATE risks SET rationale_json = ? WHERE risk_id = ?", ("{", risk_id))
    db.commit()
    metrics = observed_metrics(db)
    assert metrics["assessment_volume"]["total"] == 1
    assert metrics["rationale_unreadable"] == 1
    assert metrics["claim_count"] == 0
    assert _counts(metrics["residual_tiers"])[tier] == 1
    assert _partition(metrics) == 1
    db.close()


def test_summary_keeps_unexpected_values_and_ignores_other_events():
    risks = [
        _risk("R-1", tier="severe", claims=[{"evidence_status": "trust_me"}, {"evidence_status": " "}],
              clauses="not-a-list"),
        _risk("R-2", scenario_id="intake-other", tier="low", claims="nope"),
        _risk("R-3", rationale="[]"),
        _risk("R-4", scenario_id="intake-bad", tier="low"),
    ]
    events = [
        _event("R-1", "risk_created", "2026-01-01T00:00:00+00:00"),
        _event("R-1", "intake_received", "2026-10-01T00:00:00+00:00"),
        _event("R-1", "decision_recorded", "2026-10-01T00:00:10+00:00"),
        _event("R-4", "intake_received", "2026-10-01T00:00:00+00:00"),
        _event("R-4", "decision_recorded", "not-a-time"),
    ]
    actions = [
        {"status": "open"}, {"status": "in_progress"},
        {"status": "completed"}, {"status": "completed"},
    ]
    decisions = [{"risk_id": "R-1", "disposition": "approve"}, {"risk_id": "R-9", "disposition": "reject"}]
    metrics = summarize_register(risks, actions, decisions, events)
    assert _counts(metrics["residual_tiers"])["severe"] == 1
    assert _counts(metrics["evidence_statuses"])["trust_me"] == 1
    assert metrics["claims_missing_status"] == 1
    assert metrics["claims_unreadable"] == 1
    assert metrics["rationale_unreadable"] == 1
    assert metrics["clause_records_unreadable"] == 1
    assert metrics["remediation"]["not_completed"] == 2
    assert metrics["remediation"]["total"] == 4
    assert metrics["dispositions"]["recorded"] == 2
    assert metrics["dispositions"]["risks_without_decision"] == 3
    assert metrics["cycle_time"]["measured_count"] == 1
    assert metrics["cycle_time"]["median_seconds"] == 10
    assert metrics["cycle_time"]["excluded"]["unusable_timestamps"] == 1
    assert metrics["cycle_time"]["excluded"]["no_intake_event"] == 2
    assert metrics["assessment_volume"]["general_intake"] == 2
    assert metrics["assessment_volume"]["scenario_fixture"] == 2
    assert _partition(metrics) == 4


def test_mean_rounds_half_up_and_median_uses_the_middle_spans():
    risks = [_risk(f"R-{index}", scenario_id=f"intake-{index}") for index in range(3)]
    events = []
    for index, seconds in enumerate((10, 20, 40)):
        start = "2026-10-01T00:00:00+00:00"
        end = f"2026-10-01T00:00:{seconds:02d}+00:00"
        events.append(_event(risks[index]["risk_id"], "intake_received", start))
        events.append(_event(risks[index]["risk_id"], "decision_recorded", end))
    cycle = summarize_register(risks, [], [], events)["cycle_time"]
    assert cycle["median_seconds"] == 20
    assert cycle["mean_seconds"] == 23.33
    assert cycle["mean_label"] == "23.33 elapsed seconds"
    assert cycle["total_seconds"] == 70

    eight = [_risk(f"S-{index}", scenario_id=f"intake-s{index}") for index in range(8)]
    eight_events = []
    for index, risk in enumerate(eight):
        eight_events.append(_event(risk["risk_id"], "intake_received", "2026-10-01T00:00:00+00:00"))
        end = "2026-10-01T00:00:01+00:00" if index == 0 else "2026-10-01T00:00:00+00:00"
        eight_events.append(_event(risk["risk_id"], "decision_recorded", end))
    rounded = summarize_register(eight, [], [], eight_events)["cycle_time"]
    assert rounded["total_seconds"] == 1
    assert rounded["mean_seconds"] == 0.13
    assert rounded["mean_label"] == "0.13 elapsed seconds"
    assert rounded["median_seconds"] == 0
    assert rounded["zero_span_count"] == 7

    pair = [_risk("P-1", scenario_id="intake-p1"), _risk("P-2", scenario_id="intake-p2")]
    pair_events = [
        _event("P-1", "intake_received", "2026-10-01T00:00:00+00:00"),
        _event("P-1", "decision_recorded", "2026-10-01T00:00:10+00:00"),
        _event("P-2", "intake_received", "2026-10-01T00:00:00+00:00"),
        _event("P-2", "decision_recorded", "2026-10-01T00:00:20+00:00"),
    ]
    assert summarize_register(pair, [], [], pair_events)["cycle_time"]["median_seconds"] == 15


def test_elapsed_labels_use_the_second_as_their_unit():
    assert format_elapsed_seconds(None) is None
    assert format_elapsed_seconds(0) == "0 elapsed seconds"
    assert format_elapsed_seconds(1) == "1 elapsed second"
    assert format_elapsed_seconds(120) == "120 elapsed seconds"


def _observed_section(body):
    text = body.decode() if isinstance(body, bytes) else body
    return text.split("observed-metrics-start", 1)[1].split("observed-metrics-end", 1)[0]


def test_dashboard_and_methods_show_empty_observed_metrics(client):
    for path in ("/", "/methodology"):
        response = client.get(path)
        assert response.status_code == 200
        observed = _observed_section(response.data)
        assert "Saved assessments: 0." in observed
        assert "Open remediation: 0." in observed
        assert "Persisted dispositions: 0." in observed
        assert "Not measured" in observed
        assert "$" not in observed


def test_dashboard_keeps_the_illustrative_cost_panel(client):
    body = client.get("/").data.decode()
    assert "OBSERVED" in body
    assert "MODELED EXAMPLE" in body
    assert "180.00" in body
    assert "600.00" in body
    assert "versioned example" in body
    observed = _observed_section(body)
    assert "180.00" not in observed
    assert "600.00" not in observed
    assert "illustrative formula is unchanged" in observed


def test_methods_page_lists_unmeasured_handling_time(client):
    body = client.get("/methodology").data.decode()
    assert "Human handling time." in body
    assert "when the application wrote the event" in body
    assert "labor capacity, not cash savings" in body
    assert "stay out of these inputs" in body
    assert "Counted from the local register" in body


def test_dashboard_shows_a_measured_span_without_changing_the_cost_example(client, app):
    from app.db import get_db

    with app.app_context():
        risk_id = _save_intake(get_db())
        _stamp(get_db(), risk_id, "intake_received", "2026-10-01T00:00:00+00:00")
        _stamp(get_db(), risk_id, "decision_recorded", "2026-10-01T00:02:00+00:00")
    body = client.get("/").data.decode()
    observed = _observed_section(body)
    assert "Saved assessments: 1." in observed
    assert "General intake: 1." in observed
    assert "120 elapsed seconds" in observed
    assert "Persisted dispositions: 1." in observed
    assert "$" not in observed
    assert "180.00" in body
    assert "600.00" in body


def test_dashboard_scenario_save_does_not_invent_cycle_time(client, app):
    from app.db import get_db

    with app.app_context():
        register_scenario(get_db(), run_scenario("conflicting-claims"))
    observed = _observed_section(client.get("/").data)
    assert "Saved assessments: 1." in observed
    assert "Scenario fixtures: 1." in observed
    assert "General intake: 0." in observed
    assert "Open remediation: 1." in observed
    assert "Not measured" in observed
    assert "1 without an intake event" in observed
