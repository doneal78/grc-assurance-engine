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
    connection.commit()


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
