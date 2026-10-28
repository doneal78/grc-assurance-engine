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


def _stamp_decision(db, risk_id, decided_at):
    db.execute(
        "UPDATE decisions SET decided_at = ? WHERE risk_id = ?",
        (decided_at, risk_id),
    )
    db.commit()


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
    assert metrics["definition_version"] == "6"
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
    handling = metrics["handling_time"]
    assert handling["kind"] == "self_reported"
    assert handling["recorded_count"] == 0
    assert handling["unmeasured_decisions"] == 0
    assert handling["median_minutes"] is None
    assert handling["mean_minutes"] is None
    assert handling["feeds_cost_model"] is False
    assert handling["authenticated"] is False
    rework = metrics["rework_time"]
    assert rework["kind"] == "self_reported"
    assert rework["label"] == "Self-reported rework time"
    assert rework["recorded_count"] == 0
    assert rework["unmeasured_decisions"] == 0
    assert rework["median_minutes"] is None
    assert rework["feeds_cost_model"] is False
    assert rework["authenticated"] is False
    touches = metrics["manual_touches"]
    assert touches["kind"] == "self_reported"
    assert touches["label"] == "Self-reported manual touches"
    assert touches["unit"] == "touches"
    assert touches["recorded_count"] == 0
    assert touches["unmeasured_decisions"] == 0
    assert touches["median_touches"] is None
    assert touches["feeds_cost_model"] is False
    assert touches["authenticated"] is False
    assert "not handling minutes" in touches["definition"]
    assert "not rework minutes" in touches["definition"]
    handoffs = metrics["handoffs"]
    assert handoffs["kind"] == "self_reported"
    assert handoffs["label"] == "Self-reported handoffs"
    assert handoffs["unit"] == "handoffs"
    assert handoffs["recorded_count"] == 0
    assert handoffs["unmeasured_decisions"] == 0
    assert handoffs["median_handoffs"] is None
    assert handoffs["feeds_cost_model"] is False
    assert handoffs["authenticated"] is False
    assert "not handling minutes" in handoffs["definition"]
    assert "not rework minutes" in handoffs["definition"]
    assert "not a manual-touch count" in handoffs["definition"]
    rate = metrics["monthly_assessment_rate"]
    assert rate["kind"] == "observed_rate"
    assert rate["measured"] is False
    assert rate["rate"] is None
    assert rate["rate_label"] is None
    assert rate["reason"] == "no_decisions"
    assert rate["window_days"] == 30
    assert rate["feeds_cost_model"] is False
    assert "not scaled" in rate["definition"]
    assert "not copied into the cost formula" in rate["definition"]
    assert "No current decision is stored." in rate["detail"]
    assert "rework_time" not in {item["id"] for item in metrics["not_measured"]}
    assert "manual_touches" not in {item["id"] for item in metrics["not_measured"]}
    assert "handoffs" not in {item["id"] for item in metrics["not_measured"]}
    assert "monthly_assessment_rate" not in {item["id"] for item in metrics["not_measured"]}
    assert "authenticated_effort" in {item["id"] for item in metrics["not_measured"]}
    assert "cash_savings" in {item["id"] for item in metrics["not_measured"]}
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
        assert "MONTHLY ASSESSMENT RATE" in observed
        assert "No current decision is stored." in observed
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


def test_methods_page_describes_self_reported_handling_time(client):
    body = client.get("/methodology").data.decode()
    assert "Self-reported human handling time" in body
    assert "not checked against an identity system" in body
    assert "not elapsed cycle time" in body
    assert "SELF-REPORTED MANUAL TOUCHES" in body
    assert "SELF-REPORTED HANDOFFS" in body
    assert "MONTHLY ASSESSMENT RATE" in body
    assert "closed 30-day window" in body
    assert "at least 30 days" in body
    assert "<strong>Monthly assessment rate.</strong>" not in body
    assert "The observed monthly assessment rate is not an input to this formula." in body
    assert "Self-reported handling minutes are not inputs to this formula." in body
    assert "Self-reported rework minutes are not inputs to this formula." in body
    assert "Self-reported manual touches are not inputs to this formula." in body
    assert "Self-reported handoffs are not inputs to this formula." in body
    assert "Rework minutes are not handling minutes." in body
    assert "Rework duration." not in body
    assert "Authenticated effort." in body
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


def test_handling_minutes_ignore_nulls_and_leave_the_cost_formula_unchanged():
    from app.services.cost_model import calculate_cost

    db = _db()
    before = calculate_cost()
    _save_intake(db, handling_minutes=10)
    _save_intake(db)
    _save_intake(db, handling_minutes=30)
    metrics = observed_metrics(db)
    handling = metrics["handling_time"]
    assert handling["recorded_count"] == 2
    assert handling["unmeasured_decisions"] == 1
    assert handling["median_minutes"] == 20
    assert handling["mean_minutes"] == 20
    assert handling["minimum_minutes"] == 10
    assert handling["maximum_minutes"] == 30
    assert handling["total_minutes"] == 40
    assert handling["median_label"] == "20 minutes"
    assert handling["feeds_cost_model"] is False
    assert metrics["feeds_cost_model"] is False
    assert calculate_cost() == before
    assert "handling_minutes" not in before["assumptions"]
    db.close()


def test_handling_summary_uses_the_median_of_reported_rows_only():
    decisions = [
        {"risk_id": "R-1", "disposition": "approve", "handling_minutes": 10},
        {"risk_id": "R-2", "disposition": "reject", "handling_minutes": None},
        {"risk_id": "R-3", "disposition": "escalate", "handling_minutes": 20},
        {"risk_id": "R-4", "disposition": "approve", "handling_minutes": "25"},
    ]
    handling = summarize_register([], [], decisions, [])["handling_time"]
    assert handling["recorded_count"] == 2
    assert handling["unmeasured_decisions"] == 2
    assert handling["median_minutes"] == 15
    assert handling["mean_minutes"] == 15
    assert handling["median_label"] == "15 minutes"
    rounded = summarize_register([], [], [
        {"handling_minutes": 1},
        {"handling_minutes": 1},
        {"handling_minutes": 2},
    ], [])["handling_time"]
    assert rounded["recorded_count"] == 3
    assert rounded["median_minutes"] == 1
    assert rounded["mean_minutes"] == 1.33
    assert rounded["mean_label"] == "1.33 minutes"
    assert rounded["median_label"] == "1 minute"


def test_dashboard_shows_self_reported_minutes_apart_from_the_cost_panel(client, app):
    from app.db import get_db
    from app.services.cost_model import calculate_cost

    before = calculate_cost()
    with app.app_context():
        _save_intake(get_db(), handling_minutes=25)
        _save_intake(get_db())
    body = client.get("/").data.decode()
    observed = _observed_section(body)
    assert "SELF-REPORTED HANDLING TIME" in observed
    assert "25 minutes" in observed
    assert "Self-reported human handling time." in observed
    assert "Not used by the cost model." in observed
    assert "1 saved decision has no minutes." in observed
    assert "$" not in observed
    assert "180.00" in body
    assert "600.00" in body
    assert calculate_cost() == before
    methods = client.get("/methodology").data.decode()
    assert "25 minutes" in _observed_section(methods)
    assert "180.00" not in _observed_section(methods)


def test_rework_minutes_ignore_nulls_and_leave_the_cost_formula_unchanged():
    from app.services.cost_model import calculate_cost

    db = _db()
    before = calculate_cost()
    _save_intake(db, handling_minutes=10, rework_minutes=40)
    _save_intake(db, handling_minutes=30)
    _save_intake(db, rework_minutes=0)
    metrics = observed_metrics(db)
    handling = metrics["handling_time"]
    rework = metrics["rework_time"]
    assert handling["recorded_count"] == 2
    assert handling["median_minutes"] == 20
    assert rework["recorded_count"] == 2
    assert rework["unmeasured_decisions"] == 1
    assert rework["median_minutes"] == 20
    assert rework["mean_minutes"] == 20
    assert rework["minimum_minutes"] == 0
    assert rework["maximum_minutes"] == 40
    assert rework["total_minutes"] == 40
    assert rework["median_label"] == "20 minutes"
    assert rework["feeds_cost_model"] is False
    assert "not handling minutes" in rework["definition"]
    assert calculate_cost() == before
    assert "rework_minutes" not in before["assumptions"]
    assert "handling_minutes" not in before["assumptions"]
    db.close()


def test_rework_summary_uses_the_median_of_reported_rows_only():
    decisions = [
        {"risk_id": "R-1", "disposition": "approve", "handling_minutes": 10, "rework_minutes": 4},
        {"risk_id": "R-2", "disposition": "reject", "handling_minutes": None, "rework_minutes": None},
        {"risk_id": "R-3", "disposition": "escalate", "handling_minutes": 20, "rework_minutes": 8},
        {"risk_id": "R-4", "disposition": "approve", "handling_minutes": "25", "rework_minutes": "9"},
    ]
    summary = summarize_register([], [], decisions, [])
    rework = summary["rework_time"]
    handling = summary["handling_time"]
    assert handling["recorded_count"] == 2
    assert handling["median_minutes"] == 15
    assert rework["recorded_count"] == 2
    assert rework["unmeasured_decisions"] == 2
    assert rework["median_minutes"] == 6
    assert rework["mean_minutes"] == 6
    assert rework["median_label"] == "6 minutes"
    rounded = summarize_register([], [], [
        {"rework_minutes": 1},
        {"rework_minutes": 1},
        {"rework_minutes": 2},
    ], [])["rework_time"]
    assert rounded["recorded_count"] == 3
    assert rounded["median_minutes"] == 1
    assert rounded["mean_minutes"] == 1.33
    assert rounded["mean_label"] == "1.33 minutes"
    assert rounded["median_label"] == "1 minute"


def test_dashboard_shows_rework_apart_from_handling_and_the_cost_panel(client, app):
    from app.db import get_db
    from app.services.cost_model import calculate_cost

    before = calculate_cost()
    with app.app_context():
        _save_intake(get_db(), handling_minutes=25, rework_minutes=12)
        _save_intake(get_db(), handling_minutes=5)
    body = client.get("/").data.decode()
    observed = _observed_section(body)
    assert "SELF-REPORTED HANDLING TIME" in observed
    assert "SELF-REPORTED REWORK TIME" in observed
    assert "15 minutes" in observed
    assert "12 minutes" in observed
    assert "Self-reported human handling time." in observed
    assert "Self-reported rework time." in observed
    assert "Not handling minutes." in observed
    assert "Not used by the cost model." in observed
    assert "1 saved decision has no rework minutes." in observed
    assert "$" not in observed
    assert "180.00" in body
    assert "600.00" in body
    assert calculate_cost() == before
    methods = client.get("/methodology").data.decode()
    methods_observed = _observed_section(methods)
    assert "12 minutes" in methods_observed
    assert "15 minutes" in methods_observed
    assert "180.00" not in methods_observed


def test_manual_touches_ignore_nulls_and_leave_the_cost_formula_unchanged():
    from app.services.cost_model import calculate_cost

    db = _db()
    before = calculate_cost()
    _save_intake(db, handling_minutes=10, rework_minutes=40, manual_touches=2)
    _save_intake(db, handling_minutes=30, rework_minutes=8)
    _save_intake(db, manual_touches=0)
    metrics = observed_metrics(db)
    handling = metrics["handling_time"]
    rework = metrics["rework_time"]
    touches = metrics["manual_touches"]
    assert handling["recorded_count"] == 2
    assert handling["median_minutes"] == 20
    assert rework["recorded_count"] == 2
    assert rework["median_minutes"] == 24
    assert touches["recorded_count"] == 2
    assert touches["unmeasured_decisions"] == 1
    assert touches["median_touches"] == 1
    assert touches["mean_touches"] == 1
    assert touches["minimum_touches"] == 0
    assert touches["maximum_touches"] == 2
    assert touches["total_touches"] == 2
    assert touches["median_label"] == "1 touch"
    assert touches["feeds_cost_model"] is False
    assert "not handling minutes" in touches["definition"]
    assert "not rework minutes" in touches["definition"]
    assert calculate_cost() == before
    assert "manual_touches" not in before["assumptions"]
    assert "rework_minutes" not in before["assumptions"]
    assert "handling_minutes" not in before["assumptions"]
    db.close()


def test_manual_touches_summary_uses_the_median_of_reported_rows_only():
    decisions = [
        {"risk_id": "R-1", "disposition": "approve", "handling_minutes": 10, "manual_touches": 1},
        {"risk_id": "R-2", "disposition": "reject", "handling_minutes": None, "manual_touches": None},
        {"risk_id": "R-3", "disposition": "escalate", "handling_minutes": 20, "manual_touches": 3},
        {"risk_id": "R-4", "disposition": "approve", "handling_minutes": "25", "manual_touches": "9"},
    ]
    summary = summarize_register([], [], decisions, [])
    touches = summary["manual_touches"]
    handling = summary["handling_time"]
    assert handling["recorded_count"] == 2
    assert handling["median_minutes"] == 15
    assert touches["recorded_count"] == 2
    assert touches["unmeasured_decisions"] == 2
    assert touches["median_touches"] == 2
    assert touches["mean_touches"] == 2
    assert touches["median_label"] == "2 touches"
    rounded = summarize_register([], [], [
        {"manual_touches": 1},
        {"manual_touches": 1},
        {"manual_touches": 2},
    ], [])["manual_touches"]
    assert rounded["recorded_count"] == 3
    assert rounded["median_touches"] == 1
    assert rounded["mean_touches"] == 1.33
    assert rounded["mean_label"] == "1.33 touches"
    assert rounded["median_label"] == "1 touch"


def test_dashboard_shows_manual_touches_apart_from_minutes_and_the_cost_panel(client, app):
    from app.db import get_db
    from app.services.cost_model import calculate_cost

    before = calculate_cost()
    with app.app_context():
        _save_intake(get_db(), handling_minutes=25, rework_minutes=12, manual_touches=4)
        _save_intake(get_db(), handling_minutes=5, manual_touches=2)
    body = client.get("/").data.decode()
    observed = _observed_section(body)
    assert "SELF-REPORTED HANDLING TIME" in observed
    assert "SELF-REPORTED REWORK TIME" in observed
    assert "SELF-REPORTED MANUAL TOUCHES" in observed
    assert "15 minutes" in observed
    assert "12 minutes" in observed
    assert "3 touches" in observed
    assert "Self-reported manual touches." in observed
    assert "Not handling minutes." in observed
    assert "Not rework minutes." in observed
    assert "Not used by the cost model." in observed
    assert "$" not in observed
    assert "180.00" in body
    assert "600.00" in body
    assert calculate_cost() == before
    methods = client.get("/methodology").data.decode()
    methods_observed = _observed_section(methods)
    assert "3 touches" in methods_observed
    assert "12 minutes" in methods_observed
    assert "180.00" not in methods_observed


def test_handoffs_ignore_nulls_and_leave_the_cost_formula_unchanged():
    from app.services.cost_model import calculate_cost

    db = _db()
    before = calculate_cost()
    _save_intake(db, handling_minutes=10, rework_minutes=40, manual_touches=2, handoffs=4)
    _save_intake(db, handling_minutes=30, rework_minutes=8, manual_touches=1)
    _save_intake(db, handoffs=0)
    metrics = observed_metrics(db)
    handling = metrics["handling_time"]
    rework = metrics["rework_time"]
    touches = metrics["manual_touches"]
    handoffs = metrics["handoffs"]
    assert handling["recorded_count"] == 2
    assert handling["median_minutes"] == 20
    assert rework["recorded_count"] == 2
    assert rework["median_minutes"] == 24
    assert touches["recorded_count"] == 2
    assert touches["median_touches"] == 1.5
    assert handoffs["recorded_count"] == 2
    assert handoffs["unmeasured_decisions"] == 1
    assert handoffs["median_handoffs"] == 2
    assert handoffs["mean_handoffs"] == 2
    assert handoffs["minimum_handoffs"] == 0
    assert handoffs["maximum_handoffs"] == 4
    assert handoffs["total_handoffs"] == 4
    assert handoffs["median_label"] == "2 handoffs"
    assert handoffs["feeds_cost_model"] is False
    assert "not handling minutes" in handoffs["definition"]
    assert "not rework minutes" in handoffs["definition"]
    assert "not a manual-touch count" in handoffs["definition"]
    assert calculate_cost() == before
    assert "handoffs" not in before["assumptions"]
    assert "manual_touches" not in before["assumptions"]
    assert "rework_minutes" not in before["assumptions"]
    assert "handling_minutes" not in before["assumptions"]
    db.close()


def test_handoffs_summary_uses_the_median_of_reported_rows_only():
    decisions = [
        {"risk_id": "R-1", "disposition": "approve", "manual_touches": 1, "handoffs": 1},
        {"risk_id": "R-2", "disposition": "reject", "manual_touches": None, "handoffs": None},
        {"risk_id": "R-3", "disposition": "escalate", "manual_touches": 3, "handoffs": 3},
        {"risk_id": "R-4", "disposition": "approve", "manual_touches": "9", "handoffs": "9"},
    ]
    summary = summarize_register([], [], decisions, [])
    touches = summary["manual_touches"]
    handoffs = summary["handoffs"]
    assert touches["recorded_count"] == 2
    assert touches["median_touches"] == 2
    assert handoffs["recorded_count"] == 2
    assert handoffs["unmeasured_decisions"] == 2
    assert handoffs["median_handoffs"] == 2
    assert handoffs["mean_handoffs"] == 2
    assert handoffs["median_label"] == "2 handoffs"
    rounded = summarize_register([], [], [
        {"handoffs": 1},
        {"handoffs": 1},
        {"handoffs": 2},
    ], [])["handoffs"]
    assert rounded["recorded_count"] == 3
    assert rounded["median_handoffs"] == 1
    assert rounded["mean_handoffs"] == 1.33
    assert rounded["mean_label"] == "1.33 handoffs"
    assert rounded["median_label"] == "1 handoff"


def test_dashboard_shows_handoffs_apart_from_touches_and_the_cost_panel(client, app):
    from app.db import get_db
    from app.services.cost_model import calculate_cost

    before = calculate_cost()
    with app.app_context():
        _save_intake(get_db(), handling_minutes=25, rework_minutes=12, manual_touches=4, handoffs=6)
        _save_intake(get_db(), handling_minutes=5, manual_touches=2, handoffs=2)
        _save_intake(get_db())
    body = client.get("/").data.decode()
    observed = _observed_section(body)
    assert "SELF-REPORTED HANDLING TIME" in observed
    assert "SELF-REPORTED REWORK TIME" in observed
    assert "SELF-REPORTED MANUAL TOUCHES" in observed
    assert "SELF-REPORTED HANDOFFS" in observed
    assert "15 minutes" in observed
    assert "12 minutes" in observed
    assert "3 touches" in observed
    assert "4 handoffs" in observed
    assert "Self-reported handoffs." in observed
    assert "Not authenticated." in observed
    assert "Not elapsed cycle time." in observed
    assert "Not handling minutes." in observed
    assert "Not rework minutes." in observed
    assert "Not manual touches." in observed
    assert "Not used by the cost model." in observed
    assert "1 saved decision has no handoffs." in observed
    assert "$" not in observed
    assert "180.00" in body
    assert "600.00" in body
    assert calculate_cost() == before
    methods = client.get("/methodology").data.decode()
    methods_observed = _observed_section(methods)
    assert "4 handoffs" in methods_observed
    assert "3 touches" in methods_observed
    assert "MONTHLY ASSESSMENT RATE" in methods_observed
    assert "Not measured" in methods_observed
    assert "span less than 30 days" in methods_observed
    assert "<strong>Monthly assessment rate.</strong>" not in methods
    assert "Authenticated effort." in methods
    assert "Cash savings." in methods
    assert "180.00" not in methods_observed


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
    assert "MONTHLY ASSESSMENT RATE" in observed
    assert "No current decision is stored." in observed


def test_monthly_rate_stays_unmeasured_when_history_does_not_cover_30_days():
    from app.services.cost_model import calculate_cost

    before = calculate_cost()
    empty = summarize_register([], [], [], [])["monthly_assessment_rate"]
    assert empty["measured"] is False
    assert empty["reason"] == "no_decisions"
    assert empty["rate"] is None

    unreadable = summarize_register([], [], [
        {"risk_id": "R-1", "disposition": "approve", "decided_at": "yesterday", "handling_minutes": 10},
        {"risk_id": "R-2", "disposition": "reject", "decided_at": "", "handoffs": 2},
        {"risk_id": "R-3", "disposition": "escalate"},
    ], [])["monthly_assessment_rate"]
    assert unreadable["measured"] is False
    assert unreadable["reason"] == "no_readable_timestamp"
    assert unreadable["unreadable_count"] == 3
    assert unreadable["rate"] is None
    assert "no readable decided_at" in unreadable["detail"]

    one = summarize_register([], [], [
        {"risk_id": "R-1", "decided_at": "2026-10-01T00:00:00+00:00", "handling_minutes": 25},
    ], [
        {"risk_id": "R-1", "event_type": "decision_recorded", "occurred_at": "2026-01-01T00:00:00+00:00"},
        {"risk_id": "R-1", "event_type": "decision_recorded", "occurred_at": "2026-10-01T00:00:00+00:00"},
    ])
    assert one["decision_event_count"] == 2
    assert one["handling_time"]["median_minutes"] == 25
    rate = one["monthly_assessment_rate"]
    assert rate["measured"] is False
    assert rate["reason"] == "insufficient_history"
    assert rate["readable_count"] == 1
    assert rate["rate"] is None
    assert rate["rate_label"] is None
    assert "not scaled up" in rate["detail"]
    assert "per 30 days" not in rate["detail"]

    short = summarize_register([], [], [
        {"risk_id": "R-1", "decided_at": "2026-09-21T00:00:00+00:00", "rework_minutes": 4, "manual_touches": 1},
        {"risk_id": "R-2", "decided_at": "2026-10-01T00:00:00+00:00", "rework_minutes": 8, "manual_touches": 3},
    ], [])
    assert short["rework_time"]["median_minutes"] == 6
    assert short["manual_touches"]["median_touches"] == 2
    assert short["monthly_assessment_rate"]["measured"] is False
    assert short["monthly_assessment_rate"]["rate"] is None
    assert "span less than 30 days" in short["monthly_assessment_rate"]["detail"]
    assert "6 assessments" not in short["monthly_assessment_rate"]["detail"]

    boundary = summarize_register([], [], [
        {"risk_id": "R-1", "decided_at": "2026-09-01T00:00:01+00:00"},
        {"risk_id": "R-2", "decided_at": "2026-10-01T00:00:00+00:00"},
    ], [])["monthly_assessment_rate"]
    assert boundary["measured"] is False
    assert boundary["rate"] is None
    assert calculate_cost() == before


def test_monthly_rate_counts_current_decisions_in_a_covered_30_day_window():
    from app.services.cost_model import calculate_cost

    before = calculate_cost()
    decisions = [
        {"risk_id": "R-1", "disposition": "approve", "decided_at": "2026-08-01T00:00:00+00:00",
         "handling_minutes": 10, "rework_minutes": 4, "manual_touches": 1, "handoffs": 1},
        {"risk_id": "R-2", "disposition": "reject", "decided_at": "2026-09-15T00:00:00+00:00",
         "handling_minutes": 30, "rework_minutes": 8, "manual_touches": 3, "handoffs": 3},
        {"risk_id": "R-3", "disposition": "escalate", "decided_at": "2026-10-01T00:00:00+00:00",
         "handling_minutes": None, "rework_minutes": None, "manual_touches": None, "handoffs": None},
        {"risk_id": "R-4", "disposition": "approve", "decided_at": "not-a-timestamp",
         "handling_minutes": "25", "handoffs": 9},
    ]
    events = [
        {"risk_id": "R-1", "event_type": "decision_recorded", "occurred_at": "2026-01-01T00:00:00+00:00"},
        {"risk_id": "R-1", "event_type": "decision_recorded", "occurred_at": "2026-08-01T00:00:00+00:00"},
        {"risk_id": "R-2", "event_type": "decision_recorded", "occurred_at": "2026-09-15T00:00:00+00:00"},
        {"risk_id": "R-3", "event_type": "decision_recorded", "occurred_at": "2026-10-01T00:00:00+00:00"},
    ]
    summary = summarize_register([], [], decisions, events)
    rate = summary["monthly_assessment_rate"]
    assert rate["measured"] is True
    assert rate["rate"] == 2
    assert rate["counted"] == 2
    assert rate["rate_label"] == "2 assessments per 30 days"
    assert rate["outside_window_count"] == 1
    assert rate["unreadable_count"] == 1
    assert rate["readable_count"] == 3
    assert rate["earliest"] == "2026-08-01T00:00:00+00:00"
    assert rate["latest"] == "2026-10-01T00:00:00+00:00"
    assert rate["feeds_cost_model"] is False
    assert rate["reason"] is None
    assert "not the modeled assessments-per-month assumption" in rate["detail"]
    assert "An older decision event is not counted." in rate["detail"]
    assert summary["decision_event_count"] == 4
    assert summary["handling_time"]["recorded_count"] == 2
    assert summary["handling_time"]["median_minutes"] == 20
    assert summary["rework_time"]["median_minutes"] == 6
    assert summary["manual_touches"]["median_touches"] == 2
    assert summary["handoffs"]["recorded_count"] == 3
    assert summary["handoffs"]["unmeasured_decisions"] == 1
    assert summary["handoffs"]["median_handoffs"] == 3
    assert summary["feeds_cost_model"] is False
    assert calculate_cost() == before
    assert "monthly_assessment_rate" not in before["assumptions"]
    assert before["assumptions"]["assessments_per_month"] == 20

    exact = summarize_register([], [], [
        {"risk_id": "R-1", "decided_at": "2026-09-01T00:00:00"},
        {"risk_id": "R-2", "decided_at": "2026-10-01T00:00:00Z"},
    ], [])["monthly_assessment_rate"]
    assert exact["measured"] is True
    assert exact["rate"] == 2
    assert exact["outside_window_count"] == 0

    lone = summarize_register([], [], [
        {"risk_id": "R-1", "decided_at": "2026-08-22T00:00:00+00:00"},
        {"risk_id": "R-2", "decided_at": "2026-10-01T00:00:00+00:00"},
    ], [])["monthly_assessment_rate"]
    assert lone["measured"] is True
    assert lone["rate"] == 1
    assert lone["rate_label"] == "1 assessment per 30 days"
    assert lone["outside_window_count"] == 1


def test_monthly_rate_from_saved_rows_ignores_a_replaced_decision_event():
    from app.services.cost_model import calculate_cost

    db = _db()
    before = calculate_cost()
    first = _save_intake(db, handling_minutes=10, rework_minutes=4, manual_touches=1, handoffs=1)
    second = _save_intake(db, handling_minutes=30, rework_minutes=8, manual_touches=3, handoffs=3)
    third = _save_intake(db)
    _stamp_decision(db, first, "2026-08-01T00:00:00+00:00")
    _stamp_decision(db, second, "2026-09-15T00:00:00+00:00")
    _stamp_decision(db, third, "2026-10-01T00:00:00+00:00")
    _stamp(db, first, "decision_recorded", "2026-01-01T00:00:00+00:00")
    metrics = observed_metrics(db)
    rate = metrics["monthly_assessment_rate"]
    assert metrics["decision_event_count"] == 3
    assert metrics["dispositions"]["recorded"] == 3
    assert rate["measured"] is True
    assert rate["rate"] == 2
    assert rate["latest"] == "2026-10-01T00:00:00+00:00"
    assert rate["outside_window_count"] == 1
    assert metrics["handling_time"]["median_minutes"] == 20
    assert metrics["rework_time"]["median_minutes"] == 6
    assert metrics["manual_touches"]["median_touches"] == 2
    assert metrics["handoffs"]["recorded_count"] == 2
    assert metrics["handoffs"]["median_handoffs"] == 2
    assert metrics["handoffs"]["unmeasured_decisions"] == 1
    assert calculate_cost() == before
    assert observed_metrics(db)["monthly_assessment_rate"] == rate
    db.close()

    db = _db()
    replaced = _save_intake(db, handling_minutes=12, handoffs=4)
    _stamp_decision(db, replaced, "2026-08-01T00:00:00+00:00")
    _stamp(db, replaced, "decision_recorded", "2026-08-01T00:00:00+00:00")
    record_decision(
        db, replaced, "reject", "A later decision.", "GRC analyst",
        handling_minutes=12, handoffs=4,
    )
    replaced_metrics = observed_metrics(db)
    replaced_rate = replaced_metrics["monthly_assessment_rate"]
    stored = get_risk(db, replaced)["decision"]
    assert replaced_metrics["decision_event_count"] == 2
    assert replaced_metrics["dispositions"]["recorded"] == 1
    assert stored["decided_at"] != "2026-08-01T00:00:00+00:00"
    assert stored["handling_minutes"] == 12
    assert stored["handoffs"] == 4
    assert replaced_rate["measured"] is False
    assert replaced_rate["readable_count"] == 1
    assert replaced_rate["reason"] == "insufficient_history"
    assert replaced_rate["rate"] is None
    assert replaced_rate["latest"] == stored["decided_at"]
    assert "2026-08-01" not in replaced_rate["latest"]
    assert replaced_metrics["handling_time"]["median_minutes"] == 12
    assert replaced_metrics["handoffs"]["median_handoffs"] == 4
    assert calculate_cost() == before
    db.close()


def test_dashboard_shows_the_monthly_rate_apart_from_self_reported_cards_and_cost(client, app):
    from app.db import get_db
    from app.services.cost_model import calculate_cost

    before = calculate_cost()
    with app.app_context():
        db = get_db()
        thin = _save_intake(db, handling_minutes=25, rework_minutes=12, manual_touches=4, handoffs=6)
        _stamp_decision(db, thin, "2026-10-20T00:00:00+00:00")
    thin_body = client.get("/").data.decode()
    thin_observed = _observed_section(thin_body)
    assert "MONTHLY ASSESSMENT RATE" in thin_observed
    assert "SELF-REPORTED HANDLING TIME" in thin_observed
    assert "SELF-REPORTED REWORK TIME" in thin_observed
    assert "SELF-REPORTED MANUAL TOUCHES" in thin_observed
    assert "SELF-REPORTED HANDOFFS" in thin_observed
    assert "25 minutes" in thin_observed
    assert "12 minutes" in thin_observed
    assert "4 touches" in thin_observed
    assert "6 handoffs" in thin_observed
    assert "One timestamp does not cover 30 days" in thin_observed
    assert "not scaled up" in thin_observed
    assert "assessments per 30 days" not in thin_observed
    assert "$" not in thin_observed
    assert "180.00" in thin_body
    assert "600.00" in thin_body
    assert "not the observed monthly assessment rate" in thin_body.split("observed-metrics-end", 1)[1]

    with app.app_context():
        db = get_db()
        earlier = _save_intake(db, handling_minutes=5, rework_minutes=4, manual_touches=2, handoffs=2)
        middle = _save_intake(db)
        _stamp_decision(db, earlier, "2026-08-01T00:00:00+00:00")
        _stamp_decision(db, middle, "2026-09-20T00:00:00+00:00")
    body = client.get("/").data.decode()
    observed = _observed_section(body)
    assert "2 assessments per 30 days" in observed
    assert "1 earlier current decision falls outside that window" in observed
    assert "15 minutes" in observed
    assert "8 minutes" in observed
    assert "3 touches" in observed
    assert "4 handoffs" in observed
    assert "1 saved decision has no handoffs." in observed
    assert "not an input to the cost model" in observed
    assert "$" not in observed
    assert "180.00" in body
    assert "600.00" in body
    assert calculate_cost() == before
    methods = client.get("/methodology").data.decode()
    methods_observed = _observed_section(methods)
    assert "definition 6" in methods
    assert "2 assessments per 30 days" in methods_observed
    assert "closed 30 days ending at the latest readable timestamp" in methods
    assert "Otherwise the card says Not measured." in methods
    assert "<strong>Authenticated effort.</strong>" in methods
    assert "<strong>Cash savings.</strong>" in methods
    assert "<strong>Monthly assessment rate.</strong>" not in methods
    assert "The observed monthly assessment rate is not an input to this formula." in methods
    assert "180.00" not in methods_observed
