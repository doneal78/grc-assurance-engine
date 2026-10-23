"""Public, no-login demo pages.

Visitors run synthetic vendors through the real evidence validator, risk
engine, and control mapper. These routes never write to the database.
A reviewer package is generated for the page view and is not stored.
"""

from datetime import date

from flask import Blueprint, Response, abort, render_template, request

from app.services.intake_builder import (
    CLAUSE_EVIDENCE_OPTIONS, EVIDENCE_OPTIONS, IntakeError, build_intake,
    clause_evidence_field, field_choices, remediation_payload, run_intake, workflow_events,
)
from app.services.intake_export import build_package, render_export, render_markdown
from app.services.intake_questionnaire import load_questionnaire
from app.services.org_policy import load_org_policy
from app.services.scenario_runner import ScenarioNotFoundError, list_scenarios, run_scenario

bp = Blueprint("try_demo", __name__, url_prefix="/try")
EXPORT_FORMATS = {"json", "markdown"}


def _form_context(form=None, problems=None):
    policy = load_org_policy()
    questionnaire = load_questionnaire()
    return {"scenarios": list_scenarios(), "choices": field_choices(),
            "evidence_options": EVIDENCE_OPTIONS,
            "context_questions": questionnaire["context_questions"],
            "access_evidence": questionnaire["access_evidence"],
            "trust_center": questionnaire["trust_center"],
            "policy_question_help": questionnaire["policy_question_help"],
            "policy_fields": policy["intake_fields"],
            "contract_clauses": policy["required_contract_clauses"],
            "clause_evidence_options": CLAUSE_EVIDENCE_OPTIONS,
            "clause_evidence_field": clause_evidence_field,
            "form": form or {}, "problems": problems or []}


def _posted_fields(form):
    """Replay only the intake fields, so a download cannot echo unrelated input."""
    questionnaire = load_questionnaire()
    policy = load_org_policy()
    keys = ["vendor_name", questionnaire["trust_center"]["url_field"],
            questionnaire["access_evidence"]["field"]]
    keys.extend(spec["field"] for spec in questionnaire["context_questions"])
    keys.extend(spec["field"] for spec in policy["intake_fields"])
    keys.extend(pointer["field"] for pointer in questionnaire["trust_center"]["pointers"])
    keys.extend(clause_evidence_field(clause["clause_id"]) for clause in policy["required_contract_clauses"])
    return {key: form.get(key, "") for key in keys}


def _attachment(package, export_format):
    body, mimetype, filename = render_export(package, export_format)
    return Response(body, mimetype=mimetype, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    })


def _render_result(result, posted_form=None):
    package = build_package(result)
    return render_template("try_result.html", scenario=result,
                           events=workflow_events(result), payload=remediation_payload(result),
                           package_markdown=render_markdown(package), posted_form=posted_form)


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


@bp.get("/scenario/<scenario_id>/export/<export_format>")
def export_scenario(scenario_id, export_format):
    if export_format not in EXPORT_FORMATS:
        abort(404)
    try:
        result = run_scenario(scenario_id)
    except ScenarioNotFoundError:
        abort(404)
    return _attachment(build_package(result), export_format)


@bp.post("/assess")
def assess():
    as_of = date.today()
    export_format = (request.form.get("export_format") or "").strip()
    try:
        intake = build_intake(request.form, as_of)
    except IntakeError as exc:
        return render_template("try_index.html", **_form_context(request.form, exc.problems)), 400
    result = run_intake(intake, as_of)
    if export_format in EXPORT_FORMATS:
        return _attachment(build_package(result), export_format)
    if export_format:
        abort(400)
    return _render_result(result, posted_form=_posted_fields(request.form))
