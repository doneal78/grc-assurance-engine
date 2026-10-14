"""Public, no-login demo pages.

Visitors run synthetic vendors through the real evidence validator, risk
engine, and control mapper. These routes never write to the database.
"""

from datetime import date

from flask import Blueprint, abort, render_template, request

from app.services.intake_builder import (
    CLAIM_STATEMENTS, EVIDENCE_OPTIONS, IntakeError, build_intake, field_choices,
    remediation_payload, run_intake, workflow_events,
)
from app.services.scenario_runner import ScenarioNotFoundError, list_scenarios, run_scenario

bp = Blueprint("try_demo", __name__, url_prefix="/try")


def _form_context(form=None, problems=None):
    return {"scenarios": list_scenarios(), "choices": field_choices(),
            "evidence_options": EVIDENCE_OPTIONS, "claim_topics": CLAIM_STATEMENTS,
            "form": form or {}, "problems": problems or []}


def _render_result(result):
    return render_template("try_result.html", scenario=result,
                           events=workflow_events(result), payload=remediation_payload(result))


@bp.get("/")
def index():
    return render_template("try_index.html", **_form_context())


@bp.get("/scenario/<scenario_id>")
def scenario(scenario_id):
    try:
        result = run_scenario(scenario_id)
    except ScenarioNotFoundError:
        abort(404)
    return _render_result(result)


@bp.post("/assess")
def assess():
    as_of = date.today()
    try:
        intake = build_intake(request.form, as_of)
    except IntakeError as exc:
        return render_template("try_index.html", **_form_context(request.form, exc.problems)), 400
    return _render_result(run_intake(intake, as_of))
