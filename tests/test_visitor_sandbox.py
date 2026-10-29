"""Per-visitor sandbox register: isolation, shared examples, tamper, cleanup, chain."""

import json
import time
from datetime import datetime, timedelta, timezone

from app import create_app
from app.db import get_db
from app.services.event_chain import read_event_chain, verify_event_chain
from app.services.sandbox import (
    COOKIE_NAME,
    DEFAULT_MAX_RISKS,
    DEFAULT_TTL_SECONDS,
    read_sandbox_cookie,
    sign_sandbox_cookie,
)
from app.services.scenario_runner import run_scenario
from app.services.workflow_service import register_scenario
from tests.test_api_intake import payload
from tests.test_workflow_metrics import _observed_section

SAME_ORIGIN = {"Origin": "http://localhost"}


def _save(client, scenario_id):
    response = client.post(
        f"/demo/{scenario_id}/register",
        headers=SAME_ORIGIN,
    )
    assert response.status_code == 302, response.get_data(as_text=True)
    return response, response.headers["Location"].rsplit("/", 1)[-1].split("?", 1)[0]


def _cookie_headers(response):
    return response.headers.getlist("Set-Cookie")


def test_defaults_are_fourteen_days_and_twenty_five_rows():
    assert DEFAULT_TTL_SECONDS == 14 * 24 * 60 * 60
    assert DEFAULT_MAX_RISKS == 25


def test_visitor_cannot_see_another_visitors_rows_pages_or_api(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "sandbox.sqlite3"),
        "SECRET_KEY": "sandbox-test-secret",
        "REQUIRE_AUTH": False,
    })
    visitor_a = app.test_client()
    visitor_b = app.test_client()

    saved, risk_id = _save(visitor_a, "high-risk-ai")
    cookie = _cookie_headers(saved)
    assert any(item.startswith(f"{COOKIE_NAME}=") for item in cookie)
    issued = next(item for item in cookie if item.startswith(f"{COOKIE_NAME}="))
    assert "HttpOnly" in issued
    assert "SameSite=Lax" in issued
    assert "Path=/" in issued
    assert "Secure" not in issued

    own = visitor_a.get(f"/risks/{risk_id}")
    assert own.status_code == 200
    assert risk_id.encode() in own.data
    assert b"AI service with sensitive data" in visitor_a.get("/risks").data
    assert "Saved assessments: 1." in _observed_section(visitor_a.get("/").data)
    assert "Saved assessments: 1." in _observed_section(visitor_a.get("/methodology").data)
    export = visitor_a.get(f"/risks/{risk_id}/export/json")
    assert export.status_code == 200
    assert risk_id.encode() in export.data

    assert visitor_b.get("/risks").status_code == 200
    assert risk_id.encode() not in visitor_b.get("/risks").data
    assert b"AI service with sensitive data" not in visitor_b.get("/risks").data
    hidden = visitor_b.get(f"/risks/{risk_id}")
    assert hidden.status_code == 404
    assert visitor_b.get(f"/risks/{risk_id}/export/json").status_code == 404
    assert visitor_b.get(f"/risks/{risk_id}/export/markdown").status_code == 404
    refused = visitor_b.post(f"/risks/{risk_id}/decision", data={
        "disposition": "reject",
        "rationale": "Visitor B must not record this.",
        "decider": "Other visitor",
    }, headers=SAME_ORIGIN)
    assert refused.status_code == 404
    with app.app_context():
        action_id = get_db().execute(
            "SELECT action_id FROM remediation_actions WHERE risk_id = ?",
            (risk_id,),
        ).fetchone()["action_id"]
    blocked = visitor_b.post(f"/remediation/{action_id}", data={
        "status": "completed",
        "owner": "Other visitor",
        "due_date": "",
        "completion_notes": "Must not update",
    }, headers=SAME_ORIGIN)
    assert blocked.status_code == 404
    assert "Saved assessments: 0." in _observed_section(visitor_b.get("/").data)
    assert "Not measured" in _observed_section(visitor_b.get("/").data)
    assert "Saved assessments: 0." in _observed_section(visitor_b.get("/methodology").data)
    with app.app_context():
        decision = get_db().execute(
            "SELECT disposition FROM decisions WHERE risk_id = ?",
            (risk_id,),
        ).fetchone()
        action = get_db().execute(
            "SELECT status FROM remediation_actions WHERE action_id = ?",
            (action_id,),
        ).fetchone()
    assert decision is None
    assert action["status"] == "open"

    persisted = visitor_a.post("/api/v1/intake/assess", json=payload(
        persist=True,
        form={**payload()["form"], "vendor_name": "Alpha Sandbox Co"},
        decision={
            "disposition": "escalate",
            "rationale": "Private to this cookie.",
            "decider": "GRC analyst",
        },
    ))
    assert persisted.status_code == 200
    body = persisted.get_json()
    assert body["persisted"] is True
    api_risk = body["risk_id"]
    assert b"Alpha Sandbox Co" in visitor_a.get(f"/risks/{api_risk}").data
    assert visitor_b.get(f"/risks/{api_risk}").status_code == 404
    assert b"Alpha Sandbox Co" not in visitor_b.get("/risks").data
    assert b"Alpha Sandbox Co" not in visitor_b.get("/").data

    assessed = visitor_b.post("/api/v1/intake/assess", json=payload())
    assert assessed.status_code == 200
    assert assessed.get_json()["persisted"] is False
    assert not any(item.startswith(f"{COOKIE_NAME}=") for item in _cookie_headers(assessed))


def test_shared_seeded_examples_stay_visible_and_read_only(client):
    other = client.application.test_client()
    for visitor in (client, other):
        home = visitor.get("/")
        assert home.status_code == 200
        assert b"Evidence-supported collaboration tool" in home.data
        example = visitor.get("/demo/evidence-supported")
        assert example.status_code == 200
        text = example.get_data(as_text=True)
        assert "shared and read-only" in text
        assert "Add to risk register" in text
    _save(client, "evidence-supported")
    still = other.get("/demo/evidence-supported")
    assert still.status_code == 200
    assert "shared and read-only" in still.get_data(as_text=True)
    assert "Add to risk register" in still.get_data(as_text=True)


def test_public_try_and_import_confirm_do_not_open_a_sandbox(client):
    from datetime import date

    from app.services.intake_importer import confirmation_document, parse_upload, sample_file
    from tests.test_try_demo import form

    assessed = client.post("/try/assess", data=form(), headers=SAME_ORIGIN)
    assert assessed.status_code == 200
    assert not any(item.startswith(f"{COOKIE_NAME}=") for item in _cookie_headers(assessed))
    preview = parse_upload("vendor_intake.csv", sample_file("csv"), date(2026, 10, 29))
    confirmed = client.post(
        "/try/import/confirm",
        data={"confirmation": json.dumps(confirmation_document(preview))},
        headers=SAME_ORIGIN,
    )
    assert confirmed.status_code == 200
    assert not any(item.startswith(f"{COOKIE_NAME}=") for item in _cookie_headers(confirmed))
    with client.application.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) AS n FROM risks").fetchone()["n"] == 0
        assert db.execute("SELECT COUNT(*) AS n FROM sandboxes").fetchone()["n"] == 0
        assert db.execute("SELECT COUNT(*) AS n FROM workflow_events").fetchone()["n"] == 0


def test_cookie_tampering_is_rejected_and_a_copied_cookie_is_not_a_login(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "tamper.sqlite3"),
        "SECRET_KEY": "sandbox-test-secret",
        "REQUIRE_AUTH": False,
    })
    owner = app.test_client()
    _response, risk_id = _save(owner, "conflicting-claims")
    stored = owner.get_cookie(COOKIE_NAME)
    assert stored
    assert stored.value != risk_id
    assert read_sandbox_cookie(stored.value, "sandbox-test-secret", DEFAULT_TTL_SECONDS)

    stranger = app.test_client()
    stranger.set_cookie(COOKIE_NAME, stored.value[:-1] + ("a" if stored.value[-1] != "a" else "b"))
    assert stranger.get(f"/risks/{risk_id}").status_code == 404
    assert risk_id.encode() not in stranger.get("/risks").data

    wrong_key = sign_sandbox_cookie("a" * 32, "different-secret")
    forged = app.test_client()
    forged.set_cookie(COOKIE_NAME, wrong_key)
    assert forged.get(f"/risks/{risk_id}").status_code == 404

    holder = app.test_client()
    holder.set_cookie(COOKIE_NAME, stored.value)
    assert holder.get(f"/risks/{risk_id}").status_code == 200
    assert risk_id.encode() in holder.get("/risks").data

    time.sleep(1.1)
    assert read_sandbox_cookie(stored.value, "sandbox-test-secret", max_age=0) is None


def test_sandbox_cap_stops_another_row_and_leaves_the_other_browser_alone(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "cap.sqlite3"),
        "SECRET_KEY": "sandbox-test-secret",
        "SANDBOX_MAX_RISKS": 1,
        "REQUIRE_AUTH": False,
    })
    visitor = app.test_client()
    _save(visitor, "high-risk-ai")
    again = visitor.post("/demo/high-risk-ai/register", headers=SAME_ORIGIN)
    assert again.status_code == 302
    blocked = visitor.post("/demo/conflicting-claims/register", headers=SAME_ORIGIN)
    assert blocked.status_code == 400
    assert b"Nothing new was saved" in blocked.data
    other = app.test_client()
    _save(other, "conflicting-claims")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) AS n FROM risks").fetchone()["n"] == 2
        assert get_db().execute(
            "SELECT COUNT(DISTINCT sandbox_id) AS n FROM risks"
        ).fetchone()["n"] == 2


def test_cleanup_removes_a_stale_sandbox_and_leaves_the_chain_intact(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "cleanup.sqlite3"),
        "SECRET_KEY": "sandbox-test-secret",
        "SANDBOX_TTL_SECONDS": 60,
        "REQUIRE_AUTH": False,
    })
    visitor_a = app.test_client()
    visitor_b = app.test_client()
    _save_a, risk_a = _save(visitor_a, "high-risk-ai")
    _save_b, risk_b = _save(visitor_b, "conflicting-claims")
    with app.app_context():
        register_scenario(get_db(), run_scenario("evidence-supported"))
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
        db = get_db()
        db.execute(
            """UPDATE sandboxes SET last_seen_at = ?
               WHERE sandbox_id = (SELECT sandbox_id FROM risks WHERE risk_id = ?)""",
            (old, risk_a),
        )
        db.commit()

    assert b"Evidence-supported collaboration tool" in visitor_a.get("/risks").data
    assert visitor_a.get(f"/risks/{risk_a}").status_code == 404
    assert risk_a.encode() not in visitor_a.get("/risks").data
    assert visitor_b.get(f"/risks/{risk_b}").status_code == 200
    assert b"Evidence-supported collaboration tool" in visitor_b.get("/risks").data
    assert visitor_a.get("/demo/evidence-supported").status_code == 200
    assert visitor_b.get("/demo/high-risk-ai").status_code == 200

    with app.app_context():
        described = read_event_chain(get_db())
        assert described["status"] == "intact"
        rows = [dict(row) for row in get_db().execute(
            """SELECT event_id, risk_id, event_type, detail, occurred_at,
                      prev_hash, hash, chain_origin, sandbox_id
               FROM workflow_events ORDER BY event_id"""
        ).fetchall()]
    assert all(row["risk_id"] != risk_a for row in rows)
    assert any(row["risk_id"] == risk_b for row in rows)
    by_sandbox = {}
    for row in rows:
        by_sandbox.setdefault(row["sandbox_id"], []).append(row)
    assert None in by_sandbox
    for group in by_sandbox.values():
        tip = group[-1]
        assert verify_event_chain(group, tip_event_id=tip["event_id"], tip_hash=tip["hash"]) == "intact"


def test_two_sandbox_chains_do_not_link_and_still_verify(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "chains.sqlite3"),
        "SECRET_KEY": "sandbox-test-secret",
        "REQUIRE_AUTH": False,
    })
    visitor_a = app.test_client()
    visitor_b = app.test_client()
    _saved, risk_id = _save(visitor_a, "evidence-supported")
    _save(visitor_b, "conflicting-claims")
    decided = visitor_a.post(f"/risks/{risk_id}/decision", data={
        "disposition": "approve",
        "rationale": "No restriction matched.",
        "decider": "GRC analyst",
    }, headers=SAME_ORIGIN)
    assert decided.status_code == 302
    with app.app_context():
        rows = [dict(row) for row in get_db().execute(
            """SELECT event_id, risk_id, event_type, detail, occurred_at,
                      prev_hash, hash, chain_origin, sandbox_id
               FROM workflow_events ORDER BY event_id"""
        ).fetchall()]
        described = read_event_chain(get_db())
    assert described["status"] == "intact"
    assert "own chain" in described["summary"] or "own chain" in described["limit"]
    groups = {}
    for row in rows:
        groups.setdefault(row["sandbox_id"], []).append(row)
    assert len(groups) == 2
    flat = verify_event_chain(rows)
    assert flat != "intact"
    for group in groups.values():
        assert verify_event_chain(group) == "intact"
        assert group[0]["prev_hash"] == "0" * 64
        if len(group) > 1:
            assert group[1]["prev_hash"] == group[0]["hash"]


def test_old_database_keeps_shared_rows_and_can_store_two_sandbox_copies(tmp_path):
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
    connection.execute(
        """INSERT INTO risks
        (risk_id, scenario_id, scenario_name, risk_statement, inherent_tier, residual_tier,
         rationale_json, created_at)
        VALUES ('R-OLD', 'legacy-shared', 'Legacy shared', 'Synthetic statement', 'low', 'low',
                '{}', '2026-10-01T00:00:00+00:00')"""
    )
    connection.commit()
    connection.close()
    app = create_app({
        "TESTING": True,
        "DATABASE": str(path),
        "SECRET_KEY": "sandbox-test-secret",
        "REQUIRE_AUTH": False,
    })
    first = app.test_client()
    second = app.test_client()
    _save(first, "evidence-supported")
    _save(second, "evidence-supported")
    page = first.get("/risks")
    assert b"Legacy shared" in page.data
    assert b"Legacy shared" in second.get("/risks").data
    with app.app_context():
        copies = get_db().execute(
            "SELECT sandbox_id FROM risks WHERE scenario_id = 'evidence-supported'"
        ).fetchall()
    assert len(copies) == 2
    assert copies[0]["sandbox_id"] != copies[1]["sandbox_id"]
