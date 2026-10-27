"""Guided path across the existing demo pages.

The index lists the stops. A ``walk`` query on a live page renders the
coaching note for that stop. The guide does not write a risk.
"""

from flask import Blueprint, g, redirect, render_template, request, url_for

from app.db import get_db
from app.services.walkthrough import (
    PROHIBITED_SCENARIO_ID, SUBMISSION_COMPLETE_ATTR, WALK_COOKIE, WALK_QUERY,
    WALKTHROUGH_VERSION, known_step_id, neighbors, page_matches, step_by_id,
    steps, submission_pending,
)
from app.services.workflow_service import risk_for_scenario

bp = Blueprint("walkthrough", __name__, url_prefix="/walkthrough")

_SAVE_FIRST = "Save the eligibility case first."
_HOLD = "Add to risk register continues the guide on the saved record."
_FORM_HOLD = "Run assessment on this page before Next."


def _saved_prohibited():
    return risk_for_scenario(get_db(), PROHIBITED_SCENARIO_ID)


def destination(step, saved_risk):
    """Return the URL for a stop, and a note when it cannot open yet.

    The decision stop needs the saved eligibility risk. Until that row
    exists, the link opens the save stop instead of a missing record.
    """
    if step["step_id"] == "decide":
        if not saved_risk:
            save = step_by_id("save")
            return url_for(save["endpoint"], **save["view_args"], **{WALK_QUERY: "save"}), _SAVE_FIRST
        return url_for("risks.detail", risk_id=saved_risk["risk_id"], **{WALK_QUERY: "decide"}), None
    kwargs = {**step["view_args"], WALK_QUERY: step["step_id"]}
    if step.get("anchor"):
        kwargs["_anchor"] = step["anchor"]
    return url_for(step["endpoint"], **kwargs), None


def build_coach(step_id, endpoint, view_args, saved_risk, submission_complete=False):
    """Template data for the note on one request. URLs are absolute paths.

    ``submission_complete`` is true only for the successful assessment
    response. Form stops then offer Next. The form and a validation error
    pass false and withhold it.
    """
    step = step_by_id(step_id)
    on_page = page_matches(step, endpoint, view_args)
    previous, following = neighbors(step_id)
    target_href, blocked = destination(step, saved_risk)
    hold = None
    next_href = None
    next_title = None
    finish = False
    if on_page and submission_pending(step, submission_complete):
        hold = _FORM_HOLD
    elif on_page and step_id == "save" and not saved_risk:
        hold = _HOLD
    elif on_page and following is None:
        finish = True
        next_href = url_for("walkthrough.index")
    elif on_page and following is not None:
        next_href, next_blocked = destination(following, saved_risk)
        if next_blocked:
            hold = next_blocked
            next_href = None
        else:
            next_title = following["title"]
    prev_href = destination(previous, saved_risk)[0] if previous else None
    return {
        "step_id": step_id,
        "title": step["title"],
        "notice": step["notice"],
        "number": step["number"],
        "total": len(steps()),
        "on_page": on_page,
        "target_href": target_href,
        "blocked": blocked,
        "hold": hold,
        "prev_href": prev_href,
        "next_href": next_href,
        "next_title": next_title,
        "finish": finish,
    }


def coach_for_request():
    """The coaching note for this request, or None when the guide is off.

    Free-form pages omit the ``walk`` query and receive nothing. The guide
    index never embeds a second copy of the note.
    """
    step_id = known_step_id(request.args.get(WALK_QUERY))
    if step_id is None or (request.endpoint or "").startswith("walkthrough."):
        return None
    saved = None
    if step_id in {"save", "decide"}:
        saved = _saved_prohibited()
    complete = bool(getattr(g, SUBMISSION_COMPLETE_ATTR, False))
    return build_coach(step_id, request.endpoint, request.view_args, saved, complete)


def index_context(saved_risk, current_id):
    items = []
    current = None
    for step in steps():
        href, note = destination(step, saved_risk)
        item = {
            "step_id": step["step_id"],
            "title": step["title"],
            "summary": step["summary"],
            "href": href,
            "note": note,
            "is_current": step["step_id"] == current_id,
        }
        items.append(item)
        if item["is_current"]:
            current = item
    return {"version": WALKTHROUGH_VERSION, "steps": items, "current": current}


@bp.get("/", strict_slashes=False)
def index():
    current_id = known_step_id(request.cookies.get(WALK_COOKIE))
    return render_template("walkthrough.html", **index_context(_saved_prohibited(), current_id))


@bp.post("/reset")
def reset():
    response = redirect(url_for("walkthrough.index"))
    response.delete_cookie(WALK_COOKIE, path="/")
    return response
