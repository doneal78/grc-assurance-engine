"""Dashboard routes."""

from flask import Blueprint, redirect, render_template, url_for

from app.db import get_db
from app.services.cost_model import avoided_incident_value, calculate_cost
from app.services.event_chain import read_event_chain
from app.services.sandbox_http import request_scope
from app.services.scenario_runner import list_scenarios
from app.services.workflow_metrics import observed_metrics

bp = Blueprint("dashboard", __name__)


@bp.get("/dashboard")
@bp.get("/metrics")
def home_alias():
    """Older names for the home page. The metrics panel lives on ``/``."""
    return redirect(url_for("dashboard.index"), code=302)


@bp.get("/")
def index():
    """Render the local portfolio demo landing page."""
    avoided = avoided_incident_value()
    return render_template(
        "dashboard.html",
        scenarios=list_scenarios(),
        cost=calculate_cost(),
        observed=observed_metrics(get_db(), avoided_incident=avoided, sandbox_id=request_scope()),
        avoided_incident=avoided,
        event_chain=read_event_chain(get_db()),
    )
