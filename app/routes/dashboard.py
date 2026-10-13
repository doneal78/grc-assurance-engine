"""Dashboard routes."""

from flask import Blueprint, render_template

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    """Render the dashboard with an honest empty state."""
    # No storage exists yet, so there are no assessments to show.
    return render_template("dashboard.html", assessments=[])
