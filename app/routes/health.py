"""Health-check endpoint.

GET /health returns 200 with a small JSON body when the application
process is running. It does not check the database or any other
dependency yet; that check is added once persistence exists.
"""

from flask import Blueprint, jsonify

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    """Report that the application is running."""
    return jsonify(status="ok", service="grc-assurance-engine")
