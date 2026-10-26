"""Health-check endpoint.

GET /health reports whether this process is up and the configured SQLite
file can be opened read-only so its catalog can be read. A failed read
returns HTTP 503. The JSON names the service and the database result. It
does not include the filesystem path, the SQL, or the driver error, and
it does not judge schema completeness, integrity, or backups.
"""

from flask import Blueprint, current_app, jsonify

from app.db import database_is_readable

bp = Blueprint("health", __name__)


def _payload(status, database):
    return {"status": status, "service": "grc-assurance-engine", "database": database}


@bp.get("/health")
def health():
    """Report process and database reachability."""
    path = current_app.config.get("DATABASE") or ""
    if path and database_is_readable(path):
        return jsonify(_payload("ok", "reachable"))
    return jsonify(_payload("unavailable", "unreachable")), 503
