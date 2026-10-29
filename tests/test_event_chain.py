"""SHA-256 workflow-event chain: intact, edited, deleted, and reordered."""

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from app.services.event_chain import (
    CHAIN_ORIGIN_APPENDED,
    CHAIN_ORIGIN_BACKFILLED,
    GENESIS_PREV_HASH,
    canonical_json,
    describe_event_chain,
    event_digest,
    read_event_chain,
    verify_event_chain,
)
from app.services.scenario_runner import run_scenario
from app.services.workflow_service import get_risk, record_decision, register_scenario

SAME_ORIGIN = {"Origin": "http://localhost"}


def _row(event_id, detail, prev_hash, chain_origin=CHAIN_ORIGIN_APPENDED):
    event = {
        "event_id": event_id,
        "risk_id": "R-SYNTH",
        "event_type": "risk_created",
        "detail": detail,
        "occurred_at": "2026-10-29T12:00:00+00:00",
        "prev_hash": prev_hash,
        "chain_origin": chain_origin,
    }
    event["hash"] = event_digest(event)
    return event


def _chain():
    first = _row(1, "Synthetic event one.", GENESIS_PREV_HASH)
    second = _row(2, "Synthetic event two.", first["hash"])
    third = _row(3, "Synthetic event three.", second["hash"])
    return [first, second, third]


def _memory_db():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(Path("app/schema.sql").read_text(encoding="utf-8"))
    return connection


def _load(db):
    return [dict(row) for row in db.execute(
        """SELECT event_id, risk_id, event_type, detail, occurred_at,
                  prev_hash, hash, chain_origin
           FROM workflow_events ORDER BY event_id"""
    ).fetchall()]


def _save_three(db):
    risk_id = register_scenario(db, run_scenario("conflicting-claims"))
    record_decision(db, risk_id, "reject", "Synthetic disposition for the chain.", "GRC analyst")
    rows = _load(db)
    assert [row["event_type"] for row in rows] == [
        "risk_created", "remediation_created", "decision_recorded",
    ]
    assert all(row["chain_origin"] == CHAIN_ORIGIN_APPENDED for row in rows)
    described = read_event_chain(db)
    assert described["status"] == "intact"
    assert described["event_id"] is None
    return risk_id, rows


def test_digest_is_sha256_of_sorted_canonical_json():
    event = _row(1, 'Synthetic "quoted" detail.', GENESIS_PREV_HASH)
    payload = {
        "chain_origin": CHAIN_ORIGIN_APPENDED,
        "detail": 'Synthetic "quoted" detail.',
        "event_id": 1,
        "event_type": "risk_created",
        "occurred_at": "2026-10-29T12:00:00+00:00",
        "prev_hash": GENESIS_PREV_HASH,
        "risk_id": "R-SYNTH",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert canonical_json(event) == encoded
    assert event["hash"] == hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    assert "hash" not in json.loads(encoded)
    assert len(GENESIS_PREV_HASH) == 64


def test_intact_chain_verifies_twice():
    events = _chain()
    assert verify_event_chain(events) == "intact"
    assert verify_event_chain(events) == "intact"
    tip = describe_event_chain(events, tip_event_id=3, tip_hash=events[-1]["hash"])
    assert tip["status"] == "intact"
    assert tip["label"] == "tamper-evident, not tamper-proof"
    assert tip["backfilled_count"] == 0


def test_edited_row_is_the_first_break():
    events = _chain()
    events[1]["detail"] = "Synthetic event two, edited."
    assert verify_event_chain(events) == 2
    events[0]["occurred_at"] = "2026-10-29T13:00:00+00:00"
    assert verify_event_chain(events) == 1


def test_deleted_middle_row_breaks_the_next_link():
    events = _chain()
    remaining = [events[0], events[2]]
    assert verify_event_chain(remaining) == 3
    assert verify_event_chain(
        remaining, tip_event_id=3, tip_hash=events[2]["hash"],
    ) == 3


def test_deleted_last_row_breaks_at_the_stored_tip():
    events = _chain()
    assert verify_event_chain(
        events[:-1], tip_event_id=events[-1]["event_id"], tip_hash=events[-1]["hash"],
    ) == 3
    assert verify_event_chain([]) == "intact"
    assert verify_event_chain(
        [], tip_event_id=3, tip_hash=events[-1]["hash"],
    ) == 3


def test_reordered_rows_break_the_link():
    events = _chain()
    reordered = [events[0], events[2], events[1]]
    assert verify_event_chain(reordered) == 3
    swapped = [events[2], events[1], events[0]]
    assert verify_event_chain(swapped) == 3


def test_saved_events_form_an_appended_chain():
    db = _memory_db()
    risk_id, rows = _save_three(db)
    assert get_risk(db, risk_id)["events"][0]["hash"] == rows[0]["hash"]
    assert rows[0]["prev_hash"] == GENESIS_PREV_HASH
    assert rows[1]["prev_hash"] == rows[0]["hash"]
    assert rows[2]["prev_hash"] == rows[1]["hash"]
    assert verify_event_chain(rows) == "intact"
    db.close()


def test_database_edit_is_detected():
    db = _memory_db()
    _risk_id, rows = _save_three(db)
    target = rows[1]["event_id"]
    db.execute(
        "UPDATE workflow_events SET detail = ? WHERE event_id = ?",
        ("Synthetic detail edited after the hash was stored.", target),
    )
    db.commit()
    described = read_event_chain(db)
    assert described["status"] == "broken"
    assert described["event_id"] == target
    assert verify_event_chain(_load(db)) == target
    db.close()


def test_database_delete_is_detected():
    db = _memory_db()
    _risk_id, rows = _save_three(db)
    middle = rows[1]["event_id"]
    successor = rows[2]["event_id"]
    db.execute("DELETE FROM workflow_events WHERE event_id = ?", (middle,))
    db.commit()
    assert read_event_chain(db)["event_id"] == successor

    db = _memory_db()
    _risk_id, rows = _save_three(db)
    last = rows[-1]["event_id"]
    db.execute("DELETE FROM workflow_events WHERE event_id = ?", (last,))
    db.commit()
    assert read_event_chain(db)["event_id"] == last
    assert read_event_chain(db)["status"] == "broken"
    db.close()


def test_database_reorder_is_detected():
    db = _memory_db()
    _risk_id, rows = _save_three(db)
    left = rows[1]["event_id"]
    right = rows[2]["event_id"]
    db.execute("UPDATE workflow_events SET event_id = -1 WHERE event_id = ?", (left,))
    db.execute("UPDATE workflow_events SET event_id = ? WHERE event_id = ?", (left, right))
    db.execute("UPDATE workflow_events SET event_id = ? WHERE event_id = ?", (right, -1))
    db.commit()
    described = read_event_chain(db)
    assert described["status"] == "broken"
    assert described["event_id"] == left
    db.close()


def test_legacy_rows_are_chained_once_and_left_alone(tmp_path):
    from app import create_app

    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE risks (
            risk_id TEXT PRIMARY KEY,
            scenario_id TEXT NOT NULL UNIQUE,
            scenario_name TEXT NOT NULL,
            risk_statement TEXT NOT NULL,
            inherent_tier TEXT NOT NULL,
            residual_tier TEXT NOT NULL,
            rationale_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE workflow_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            risk_id TEXT NOT NULL REFERENCES risks(risk_id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            detail TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        );
        """
    )
    rationale = json.dumps({
        "risk": {
            "review_path": "standard_review",
            "evidence_confidence": {"level": "none", "counts": {}},
            "residual": {"tier": "low", "reason": "Synthetic legacy residual reason."},
            "inherent": {"factors": []},
            "escalations": [],
        },
        "claims": [],
        "mappings": [],
    })
    connection.execute(
        """INSERT INTO risks
        (risk_id, scenario_id, scenario_name, risk_statement, inherent_tier, residual_tier,
         rationale_json, created_at)
        VALUES ('R-OLD', 'legacy-chain', 'Legacy', 'Synthetic statement', 'low', 'low', ?,
                '2026-10-01T00:00:00+00:00')""",
        (rationale,),
    )
    connection.execute(
        """INSERT INTO workflow_events (risk_id, event_type, detail, occurred_at)
           VALUES ('R-OLD', 'risk_created', 'Synthetic legacy event one.', '2026-10-01T00:00:00+00:00')"""
    )
    connection.execute(
        """INSERT INTO workflow_events (risk_id, event_type, detail, occurred_at)
           VALUES ('R-OLD', 'remediation_created', 'Synthetic legacy event two.', '2026-10-01T00:00:01+00:00')"""
    )
    connection.commit()
    connection.close()

    app = create_app({"TESTING": True, "DATABASE": str(path), "REQUIRE_AUTH": False})
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    rows = [dict(row) for row in connection.execute(
        "SELECT * FROM workflow_events ORDER BY event_id"
    )]
    assert [row["chain_origin"] for row in rows] == [
        CHAIN_ORIGIN_BACKFILLED, CHAIN_ORIGIN_BACKFILLED,
    ]
    assert verify_event_chain(rows) == "intact"
    stored_hash = rows[0]["hash"]
    connection.execute(
        "UPDATE workflow_events SET detail = ? WHERE event_id = ?",
        ("Synthetic legacy event one, edited.", rows[0]["event_id"]),
    )
    connection.commit()
    connection.close()

    create_app({"TESTING": True, "DATABASE": str(path), "REQUIRE_AUTH": False})
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    rows = [dict(row) for row in connection.execute(
        "SELECT * FROM workflow_events ORDER BY event_id"
    )]
    assert rows[0]["hash"] == stored_hash
    assert rows[0]["chain_origin"] == CHAIN_ORIGIN_BACKFILLED
    assert verify_event_chain(rows) == rows[0]["event_id"]
    connection.close()

    with app.app_context():
        from app.db import get_db
        register_scenario(get_db(), run_scenario("evidence-supported"))
        described = read_event_chain(get_db())
    assert described["status"] == "broken"
    assert described["backfilled_count"] == 2
    page = app.test_client().get("/methodology")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "tamper-evident, not tamper-proof" in body
    assert "2 events were chained after the fact" in body
    assert "Chained after the fact" in app.test_client().get("/risks/R-OLD").get_data(as_text=True)


def test_pages_show_the_check_outside_observed_metrics(client):
    from tests.test_workflow_metrics import _observed_section

    home = client.get("/").get_data(as_text=True)
    methods = client.get("/methodology").get_data(as_text=True)
    for body in (home, methods):
        assert "tamper-evident, not tamper-proof" in body
        assert "Chain check: intact (0 events)." in body
        assert "No stored event was chained after the fact." in body
        assert "not immutable storage, a production audit log, or a certification" in body
        observed = _observed_section(body)
        assert "tamper-evident, not tamper-proof" not in observed
        assert "Chain check" not in observed
    assert "verify_event_chain()" in methods
    assert "chained_after_the_fact" in methods

    saved = client.post("/demo/conflicting-claims/register", headers=SAME_ORIGIN)
    assert saved.status_code == 302
    methods = client.get("/methodology").get_data(as_text=True)
    assert "Chain check: intact (2 events)." in methods
    home = client.get("/").get_data(as_text=True)
    assert "Chain check: intact (2 events)." in home


def test_public_try_and_import_confirm_write_nothing(client):
    from app.db import get_db
    from app.services.intake_importer import confirmation_document, parse_upload, sample_file
    from tests.test_try_demo import form

    def counts():
        with client.application.app_context():
            db = get_db()
            risks = db.execute("SELECT COUNT(*) AS n FROM risks").fetchone()["n"]
            events = db.execute("SELECT COUNT(*) AS n FROM workflow_events").fetchone()["n"]
        return risks, events

    before = counts()
    assert before == (0, 0)
    assessed = client.post("/try/assess", data=form(
        authenticated_effort_minutes="15",
        cash_savings_dollars="40",
    ), headers=SAME_ORIGIN)
    assert assessed.status_code == 200
    assert b"Workflow event log" in assessed.data
    assert counts() == (0, 0)

    preview = parse_upload("vendor_intake.csv", sample_file("csv"), date(2026, 10, 29))
    document = confirmation_document(preview)
    confirmed = client.post(
        "/try/import/confirm",
        data={"confirmation": json.dumps(document)},
        headers=SAME_ORIGIN,
    )
    assert confirmed.status_code == 200
    assert b"not saved" in confirmed.data
    assert counts() == (0, 0)


def test_public_import_save_rejects_crafted_signed_in_fields(client):
    from app.db import get_db
    from app.services.intake_importer import confirmation_document, parse_upload, sample_file

    preview = parse_upload("vendor_intake.csv", sample_file("csv"), date(2026, 10, 29))
    document = confirmation_document(preview)
    row = document["rows"][0]
    rejected = client.post("/try/import/save", data={
        "confirmation": json.dumps(document),
        "source_row": row["row_number"],
        "persist": "yes",
        "disposition": "escalate",
        "rationale": "A crafted signed-in field must not be stored.",
        "decider": "GRC analyst",
        "authenticated_effort_minutes": "15",
        "cash_savings_dollars": "40",
    }, headers=SAME_ORIGIN)
    assert rejected.status_code == 400
    assert b"signed-in" in rejected.data
    with client.application.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) AS n FROM risks").fetchone()["n"] == 0
        assert db.execute("SELECT COUNT(*) AS n FROM workflow_events").fetchone()["n"] == 0


def test_missing_field_returns_that_event_id():
    events = _chain()
    del events[2]["detail"]
    assert verify_event_chain(events) == 3
