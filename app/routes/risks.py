"""Local risk register and remediation routes."""

from flask import Blueprint, Response, abort, redirect, render_template, request, url_for

from app.db import get_db
from app.services.intake_export import package_from_saved_risk, render_export
from app.services.workflow_service import (
    DISPOSITIONS, WorkflowInputError, get_risk, list_risks, record_decision, update_action,
)

bp = Blueprint("risks", __name__)


@bp.get("/risks")
def index():
    return render_template("risks.html", risks=list_risks(get_db()))


@bp.get("/risks/<risk_id>")
def detail(risk_id):
    risk = get_risk(get_db(), risk_id)
    if risk is None:
        abort(404)
    return render_template("risk_detail.html", risk=risk, dispositions=DISPOSITIONS)


@bp.get("/risks/<risk_id>/export/<export_format>")
def export_risk(risk_id, export_format):
    if export_format not in {"json", "markdown"}:
        abort(404)
    risk = get_risk(get_db(), risk_id)
    if risk is None:
        abort(404)
    body, mimetype, filename = render_export(package_from_saved_risk(risk), export_format)
    return Response(body, mimetype=mimetype, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
    })


@bp.post("/remediation/<int:action_id>")
def update_remediation(action_id):
    try:
        risk_id = update_action(get_db(), action_id, request.form.get("status", ""),
                                request.form.get("owner", ""), request.form.get("due_date", ""),
                                request.form.get("completion_notes", ""))
    except WorkflowInputError as exc:
        return render_template("workflow_error.html", error=str(exc)), 400
    if risk_id is None:
        abort(404)
    if not risk_id:
        abort(400)
    return redirect(url_for("risks.detail", risk_id=risk_id))


@bp.post("/risks/<risk_id>/decision")
def record_risk_decision(risk_id):
    try:
        saved = record_decision(
            get_db(), risk_id, request.form.get("disposition", ""),
            request.form.get("rationale", ""), request.form.get("decider", ""),
            request.form.get("conditions", ""), request.form.get("exception_rationale", ""),
        )
    except WorkflowInputError as exc:
        return render_template("workflow_error.html", error=str(exc)), 400
    if saved is None:
        abort(404)
    return redirect(url_for("risks.detail", risk_id=saved))
