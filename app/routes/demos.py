"""Routes for repeatable, synthetic scenario demonstrations."""

from flask import Blueprint, abort, redirect, render_template, request, url_for

from app.db import get_db
from app.services.scenario_runner import ScenarioNotFoundError, list_scenarios, run_scenario
from app.services.walkthrough import carried_walk_step
from app.services.workflow_service import register_scenario, risk_for_scenario

bp = Blueprint("demos", __name__, url_prefix="/demo")


@bp.get("/")
def index():
    return render_template("demos.html", scenarios=list_scenarios())


@bp.get("/<scenario_id>")
def detail(scenario_id):
    try:
        scenario = run_scenario(scenario_id)
    except ScenarioNotFoundError:
        abort(404)
    saved = risk_for_scenario(get_db(), scenario_id)
    return render_template("demo_detail.html", scenario=scenario, saved_risk=saved)


@bp.post("/<scenario_id>/register")
def add_to_risk_register(scenario_id):
    try:
        result = run_scenario(scenario_id)
    except ScenarioNotFoundError:
        abort(404)
    risk_id = register_scenario(get_db(), result)
    values = {"risk_id": risk_id}
    step = carried_walk_step(request.args.get("walk"), advance_from="save")
    if step:
        values["walk"] = step
    return redirect(url_for("risks.detail", **values))
