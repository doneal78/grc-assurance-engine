"""Reviewer-authored findings: validation, sandbox isolation, chain, and export."""

import json
from datetime import datetime, timedelta, timezone

from app import create_app
from app.db import get_db
from app.services.cost_model import calculate_cost
from app.services.event_chain import read_event_chain, verify_event_chain
from app.services.findings import FINDING_ORIGIN
from app.services.sandbox import DEFAULT_MAX_FINDINGS
from app.services.scenario_runner import run_scenario
from app.services.workflow_metrics import DEFINITION_VERSION, observed_metrics
from app.services.workflow_service import get_risk, register_scenario

SAME_ORIGIN = {"Origin": "http://localhost"}
ISO_27001 = "iso-27001-a-5-15-access-control"
ISO_42001 = "iso-42001-a-6-2-6-operation-monitoring"
TITLE = "Access wider than the questionnaire"
SCRIPT_TITLE = "<script>alert(1)</script>"


def _app(tmp_path, **config):
    settings = {
        "TESTING": True,
        "DATABASE": str(tmp_path / "findings.sqlite3"),
        "SECRET_KEY": "findings-test-secret",
        "REQUIRE_AUTH": False,
    }
    settings.update(config)
    return create_app(settings)


def _save(client, scenario_id="high-risk-ai"):
    response = client.post(f"/demo/{scenario_id}/register", headers=SAME_ORIGIN)
    assert response.status_code == 302, response.get_data(as_text=True)
    return response.headers["Location"].rsplit("/", 1)[-1].split("?", 1)[0]


def _form(**overrides):
    data = {
        "title": TITLE,
        "description": "The integration scope is broader than the questionnaire states.",
        "severity": "high",
        "owner": "GRC reviewer",
        "vendor_name": "",
        "mapping_id": [ISO_27001, ISO_42001],
    }
    data.update(overrides)
    return data


def _create(client, risk_id, **overrides):
    return client.post(
        f"/risks/{risk_id}/findings",
        data=_form(**overrides),
        headers=SAME_ORIGIN,
    )


def _finding_count(app):
    with app.app_context():
        return get_db().execute("SELECT COUNT(*) AS n FROM findings").fetchone()["n"]


def _event_types(app, risk_id):
    with app.app_context():
        rows = get_db().execute(
            """SELECT event_type FROM workflow_events
               WHERE risk_id = ? ORDER BY event_id""",
            (risk_id,),
        ).fetchall()
    return [row["event_type"] for row in rows]


def test_default_findings_cap_is_fifty():
    assert DEFAULT_MAX_FINDINGS == 50
    assert DEFINITION_VERSION == "9"


def test_create_edit_and_close_record_chain_events_without_changing_the_score(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    risk_id = _save(client)
    with app.app_context():
        before = get_db().execute(
            "SELECT inherent_tier, residual_tier, rationale_json FROM risks WHERE risk_id = ?",
            (risk_id,),
        ).fetchone()
        sandbox_id = get_db().execute(
            "SELECT sandbox_id FROM risks WHERE risk_id = ?",
            (risk_id,),
        ).fetchone()["sandbox_id"]
        metrics_before = observed_metrics(get_db(), sandbox_id=sandbox_id)
        cost_before = calculate_cost()

    created = _create(client, risk_id)
    assert created.status_code == 302
    page = client.get(f"/risks/{risk_id}")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Reviewer-authored" in body
    assert TITLE in body
    assert "Engine-generated escalations" in body
    assert "A.5.15" in body
    assert "A.6.2.6" in body
    assert "Draft" in body
    assert "Not linked" in body
    with app.app_context():
        stored = get_risk(get_db(), risk_id)
        finding = stored["findings"][0]
        finding_id = finding["finding_id"]
        assert finding["origin"] == FINDING_ORIGIN
        assert finding["status"] == "open"
        assert finding["score_effect"] == "none"
        assert {item["mapping_id"] for item in finding["mappings"]} == {ISO_27001, ISO_42001}
        assert all(item["review_status"] == "draft" for item in finding["mappings"])
        assert "ISO/IEC" in finding["mappings"][0]["framework"] or any(
            "ISO/IEC" in item["framework"] for item in finding["mappings"]
        )

    edited = client.post(f"/risks/{risk_id}/findings/{finding_id}", data=_form(
        title="Access still wider than the questionnaire",
        severity="critical",
        vendor_name="Northwind Demo",
        status="open",
        closing_note="",
    ), headers=SAME_ORIGIN)
    assert edited.status_code == 302
    closed = client.post(f"/risks/{risk_id}/findings/{finding_id}", data=_form(
        title="Access still wider than the questionnaire",
        severity="critical",
        vendor_name="Northwind Demo",
        status="closed",
        closing_note="Access was narrowed on the synthetic ticket.",
    ), headers=SAME_ORIGIN)
    assert closed.status_code == 302
    closed_page = client.get(f"/risks/{risk_id}").get_data(as_text=True)
    assert "Access was narrowed on the synthetic ticket." in closed_page
    assert "Closed" in closed_page
    assert "Northwind Demo" in closed_page

    with app.app_context():
        after = get_db().execute(
            "SELECT inherent_tier, residual_tier, rationale_json FROM risks WHERE risk_id = ?",
            (risk_id,),
        ).fetchone()
        assert tuple(after) == tuple(before)
        metrics_after = observed_metrics(get_db(), sandbox_id=sandbox_id)
        assert metrics_after["definition_version"] == "9"
        assert metrics_after["feeds_cost_model"] is False
        assert metrics_after["assessment_volume"] == metrics_before["assessment_volume"]
        assert metrics_after["remediation"] == metrics_before["remediation"]
        assert calculate_cost() == cost_before
        types = _event_types(app, risk_id)
        assert types[-3:] == ["finding_created", "finding_updated", "finding_closed"]
        described = read_event_chain(get_db())
        assert described["status"] == "intact"
        rows = [dict(row) for row in get_db().execute(
            """SELECT event_id, risk_id, event_type, detail, occurred_at,
                      prev_hash, hash, chain_origin, sandbox_id
               FROM workflow_events WHERE sandbox_id = ? ORDER BY event_id""",
            (sandbox_id,),
        ).fetchall()]
        tip = rows[-1]
        assert verify_event_chain(
            rows, tip_event_id=tip["event_id"], tip_hash=tip["hash"],
        ) == "intact"
        get_db().execute(
            "UPDATE workflow_events SET detail = detail || ' tampered' WHERE event_id = ?",
            (tip["event_id"],),
        )
        get_db().commit()
        tampered = [dict(row) for row in get_db().execute(
            """SELECT event_id, risk_id, event_type, detail, occurred_at,
                      prev_hash, hash, chain_origin, sandbox_id
               FROM workflow_events WHERE sandbox_id = ? ORDER BY event_id""",
            (sandbox_id,),
        ).fetchall()]
        assert verify_event_chain(
            tampered, tip_event_id=tip["event_id"], tip_hash=tip["hash"],
        ) == tip["event_id"]


def test_validation_failures_do_not_write_a_finding(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    risk_id = _save(client)
    before_events = len(_event_types(app, risk_id))
    cases = [
        _form(title=""),
        _form(title="x" * 121),
        _form(description=""),
        _form(description="x" * 2001),
        _form(severity="urgent"),
        _form(owner=""),
        _form(vendor_name="x" * 81),
        _form(mapping_id=[]),
        _form(mapping_id=["not-a-control"]),
        _form(title="Bad\x00title"),
        _form(status="closed", closing_note="Too soon."),
        _form(status="in_progress"),
    ]
    for data in cases:
        response = client.post(f"/risks/{risk_id}/findings", data=data, headers=SAME_ORIGIN)
        assert response.status_code == 400, data
        assert b"Finding not saved" in response.data
    assert _finding_count(app) == 0
    assert len(_event_types(app, risk_id)) == before_events

    created = _create(client, risk_id)
    assert created.status_code == 302
    with app.app_context():
        finding_id = get_db().execute("SELECT finding_id FROM findings").fetchone()["finding_id"]
    events_after_create = len(_event_types(app, risk_id))
    rejected_close = client.post(
        f"/risks/{risk_id}/findings/{finding_id}",
        data=_form(status="closed", closing_note=""),
        headers=SAME_ORIGIN,
    )
    assert rejected_close.status_code == 400
    assert b"closing note" in rejected_close.data
    rejected_status = client.post(
        f"/risks/{risk_id}/findings/{finding_id}",
        data=_form(status="in_progress", closing_note=""),
        headers=SAME_ORIGIN,
    )
    assert rejected_status.status_code == 400
    assert _finding_count(app) == 1
    assert len(_event_types(app, risk_id)) == events_after_create
    with app.app_context():
        row = get_db().execute("SELECT status, closing_note FROM findings").fetchone()
    assert row["status"] == "open"
    assert row["closing_note"] == ""


def test_sandbox_isolation_hides_findings_events_and_exports(tmp_path):
    app = _app(tmp_path)
    visitor_a = app.test_client()
    visitor_b = app.test_client()
    risk_id = _save(visitor_a)
    created = _create(visitor_a, risk_id, title=SCRIPT_TITLE)
    assert created.status_code == 302
    own = visitor_a.get(f"/risks/{risk_id}")
    own_html = own.get_data(as_text=True)
    assert SCRIPT_TITLE not in own_html
    assert "&lt;script&gt;" in own_html
    assert visitor_b.get(f"/risks/{risk_id}").status_code == 404
    assert SCRIPT_TITLE not in visitor_b.get("/risks").get_data(as_text=True)
    with app.app_context():
        finding_id = get_db().execute("SELECT finding_id FROM findings").fetchone()["finding_id"]
    blocked = visitor_b.post(
        f"/risks/{risk_id}/findings/{finding_id}",
        data=_form(status="closed", closing_note="Must not close."),
        headers=SAME_ORIGIN,
    )
    assert blocked.status_code == 404
    assert visitor_b.get(f"/risks/{risk_id}/export/json").status_code == 404
    own_export = visitor_a.get(f"/risks/{risk_id}/export/json")
    assert own_export.status_code == 200
    package = own_export.get_json()
    assert package["reviewer_findings"][0]["title"] == SCRIPT_TITLE
    assert package["reviewer_findings"][0]["origin_label"] == "Reviewer-authored"
    assert package["reviewer_findings"][0]["score_effect"] == "none"
    assert package["automatic_approval"] is None
    draft = package["reviewer_findings"][0]["mappings"]
    assert {item["review_status"] for item in draft} == {"draft"}
    assert any(item["framework"] == "ISO/IEC 42001" for item in draft)
    summary = visitor_a.get(f"/risks/{risk_id}/export/markdown").get_data(as_text=True)
    assert "Reviewer-authored findings" in summary
    assert "Review status: draft" in summary
    assert SCRIPT_TITLE in summary
    with app.app_context():
        status = get_db().execute("SELECT status FROM findings").fetchone()["status"]
    assert status == "open"

    with app.app_context():
        shared_id = register_scenario(get_db(), run_scenario("evidence-supported"))
    shared_title = "Shared assessment, private finding"
    assert _create(visitor_a, shared_id, title=shared_title).status_code == 302
    assert shared_title in visitor_a.get(f"/risks/{shared_id}").get_data(as_text=True)
    other = visitor_b.get(f"/risks/{shared_id}")
    assert other.status_code == 200
    other_html = other.get_data(as_text=True)
    assert shared_title not in other_html
    assert "finding_created" not in other_html
    other_package = visitor_b.get(f"/risks/{shared_id}/export/json").get_json()
    assert other_package["reviewer_findings"] == []
    own_shared = visitor_a.get(f"/risks/{shared_id}/export/json").get_json()
    assert own_shared["reviewer_findings"][0]["title"] == shared_title
    assert own_shared["reviewer_findings"][0]["linked_risk_id"] == shared_id
    assert own_shared["reviewer_findings"][0]["linked_vendor"] is None


def test_public_paths_reject_crafted_signed_in_fields_and_do_not_save_on_assess(tmp_path):
    from tests.test_try_demo import form

    app = _app(tmp_path)
    client = app.test_client()
    assessed = client.post("/try/assess", data=form(), headers=SAME_ORIGIN)
    assert assessed.status_code == 200
    assert b"Add finding" not in assessed.data
    assert _finding_count(app) == 0

    risk_id = _save(client)
    crafted = _create(
        client,
        risk_id,
        authenticated_effort_minutes="15",
        cash_savings_dollars="40",
        incident_cost="10",
        avoided_incident_count="1",
        avoided_incident_value="10",
    )
    assert crafted.status_code == 400
    text = crafted.get_data(as_text=True)
    assert "cannot be saved on a finding" in text
    assert "signed-in" in text
    assert _finding_count(app) == 0
    cross_site = client.post(
        f"/risks/{risk_id}/findings",
        data=_form(),
        headers={"Origin": "https://evil.example"},
    )
    assert cross_site.status_code == 403
    assert _finding_count(app) == 0
    missing = client.post("/risks/R-MISSING/findings", data=_form(), headers=SAME_ORIGIN)
    assert missing.status_code == 404


def test_findings_cap_and_cleanup_leave_the_other_sandbox_intact(tmp_path):
    app = _app(tmp_path, SANDBOX_MAX_FINDINGS=2, SANDBOX_TTL_SECONDS=60)
    visitor = app.test_client()
    other = app.test_client()
    risk_id = _save(visitor, "high-risk-ai")
    other_risk = _save(other, "conflicting-claims")
    assert _create(visitor, risk_id, title="First finding").status_code == 302
    assert _create(visitor, risk_id, title="Second finding").status_code == 302
    blocked = _create(visitor, risk_id, title="Third finding")
    assert blocked.status_code == 400
    assert b"Nothing new was saved" in blocked.data
    assert b"Third finding" not in visitor.get(f"/risks/{risk_id}").data
    assert _create(other, other_risk, title="Other sandbox finding").status_code == 302
    with app.app_context():
        shared_id = register_scenario(get_db(), run_scenario("evidence-supported"))
    assert _create(other, shared_id, title="Other finding on a shared assessment").status_code == 302
    assert _finding_count(app) == 4

    with app.app_context():
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
        db = get_db()
        db.execute(
            """UPDATE sandboxes SET last_seen_at = ?
               WHERE sandbox_id = (SELECT sandbox_id FROM risks WHERE risk_id = ?)""",
            (old, risk_id),
        )
        db.commit()
    assert visitor.get(f"/risks/{risk_id}").status_code == 404
    assert other.get(f"/risks/{other_risk}").status_code == 200
    assert b"Other sandbox finding" in other.get(f"/risks/{other_risk}").data
    shared_page = other.get(f"/risks/{shared_id}")
    assert shared_page.status_code == 200
    assert b"Other finding on a shared assessment" in shared_page.data
    assert b"First finding" not in shared_page.data
    with app.app_context():
        db = get_db()
        assert db.execute(
            "SELECT risk_id FROM risks WHERE risk_id = ?",
            (shared_id,),
        ).fetchone()["risk_id"] == shared_id
        assert db.execute(
            "SELECT COUNT(*) AS n FROM findings WHERE risk_id = ?",
            (risk_id,),
        ).fetchone()["n"] == 0
        assert db.execute("SELECT COUNT(*) AS n FROM findings").fetchone()["n"] == 2
        described = read_event_chain(db)
        assert described["status"] == "intact"
        rows = [dict(row) for row in db.execute(
            """SELECT event_id, risk_id, event_type, detail, occurred_at,
                      prev_hash, hash, chain_origin, sandbox_id
               FROM workflow_events ORDER BY event_id"""
        ).fetchall()]
    by_sandbox = {}
    for row in rows:
        by_sandbox.setdefault(row["sandbox_id"], []).append(row)
    assert all(row["risk_id"] != risk_id for row in rows)
    for group in by_sandbox.values():
        tip = group[-1]
        assert verify_event_chain(
            group, tip_event_id=tip["event_id"], tip_hash=tip["hash"],
        ) == "intact"


def test_export_json_is_valid_and_keeps_engine_escalations_separate(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    risk_id = _save(client, "conflicting-claims")
    assert _create(client, risk_id).status_code == 302
    package = client.get(f"/risks/{risk_id}/export/json").get_json()
    json.dumps(package)
    assert package["evaluation"]["residual_tier"]
    assert package["reviewer_findings"][0]["linked_risk_id"] == risk_id
    assert "engine-generated" in package["engine_escalations_note"]
    assert package["reviewer_findings"][0]["origin"] == "reviewer"
    escalations = package["evaluation"]["escalations"]
    assert escalations
    assert package["reviewer_findings"][0]["title"] not in json.dumps(escalations)
