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


def database_is_readable(path: str) -> bool:
    """Return whether the SQLite file can be opened read-only and its catalog read.

    A missing file is left uncreated. A constant query is not enough, because
    SQLite can answer that without reading the file. Callers must not surface
    the path, the SQL, or the driver error. This does not check integrity or
    backups.
    """
    if not isinstance(path, str) or not path:
        return False
    try:
        uri = f"{Path(path).expanduser().resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    except (OSError, sqlite3.Error, ValueError):
        return False
    try:
        row = connection.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error:
        return False
    finally:
        connection.close()
    return row is not None and isinstance(row[0], int)


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
    _add_handling_minutes(connection)
    _add_rework_minutes(connection)
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


def _add_handling_minutes(connection):
    """Add optional self-reported minutes to an existing decisions table.

    Null means the person did not report handling time. Rows already stored
    stay, with the new column empty.
    """
    _add_decision_minutes(connection, "handling_minutes")


def _add_rework_minutes(connection):
    """Add optional self-reported rework minutes to an existing decisions table.

    Null means the person did not report rework time. Rows already stored
    stay, with the new column empty. Rework is not handling time.
    """
    _add_decision_minutes(connection, "rework_minutes")


def _add_decision_minutes(connection, column):
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='decisions'"
    ).fetchone()
    if row is None:
        return
    columns = {item[1] for item in connection.execute("PRAGMA table_info(decisions)")}
    if column not in columns:
        connection.execute(f"ALTER TABLE decisions ADD COLUMN {column} INTEGER")


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
