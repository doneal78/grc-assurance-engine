"""Local SQLite connection and schema initialization."""

import sqlite3
from pathlib import Path

from flask import current_app, g


def _connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_db():
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE"])
    return g.db


def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def migrate(connection):
    """Add columns introduced after the first risk-register schema.

    CREATE TABLE IF NOT EXISTS does not alter a table that already exists.
    Existing local and hosted databases keep their rows; new columns stay
    empty until a scenario is saved again.
    """
    columns = {row[1] for row in connection.execute("PRAGMA table_info(risks)")}
    for name in ("policy_id", "policy_version", "policy_outcome"):
        if name not in columns:
            connection.execute(f"ALTER TABLE risks ADD COLUMN {name} TEXT")
    _allow_escalate_disposition(connection)
    connection.commit()


def _allow_escalate_disposition(connection):
    """Let an existing decisions table store the escalate disposition.

    CREATE TABLE IF NOT EXISTS does not change a CHECK constraint that was
    created before escalate existed. Rows already stored are copied across.
    """
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='decisions'"
    ).fetchone()
    if row is None or "escalate" in row[0]:
        return
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("ALTER TABLE decisions RENAME TO decisions_legacy")
        connection.execute(
            """CREATE TABLE decisions (
                decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                risk_id TEXT NOT NULL UNIQUE REFERENCES risks(risk_id) ON DELETE CASCADE,
                disposition TEXT NOT NULL CHECK (disposition IN ('approve', 'approve_with_conditions', 'escalate', 'reject')),
                conditions TEXT NOT NULL DEFAULT '',
                rationale TEXT NOT NULL,
                exception_rationale TEXT NOT NULL DEFAULT '',
                decider TEXT NOT NULL,
                policy_id TEXT NOT NULL,
                policy_version TEXT NOT NULL,
                rule_set_version TEXT NOT NULL,
                prohibited_at_decision TEXT NOT NULL CHECK (prohibited_at_decision IN ('prohibited', 'not_prohibited')),
                decided_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """INSERT INTO decisions (
                decision_id, risk_id, disposition, conditions, rationale, exception_rationale,
                decider, policy_id, policy_version, rule_set_version, prohibited_at_decision, decided_at
            )
            SELECT decision_id, risk_id, disposition, conditions, rationale, exception_rationale,
                   decider, policy_id, policy_version, rule_set_version, prohibited_at_decision, decided_at
            FROM decisions_legacy"""
        )
        connection.execute("DROP TABLE decisions_legacy")
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def init_app(app):
    """Create the local schema if needed and release request connections."""
    app.teardown_appcontext(close_db)
    with app.app_context():
        connection = _connect(app.config["DATABASE"])
        try:
            schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            connection.executescript(schema)
            migrate(connection)
        finally:
            connection.close()
