"""Guided path across the existing demo pages.

The index lists the stops. A ``walk`` query on a live page renders the
coaching note for that stop. The guide does not write a risk.
"""

from flask import Blueprint, g, redirect, render_template, request, url_for

from app.db import get_db
from app.services.walkthrough import (
    PROHIBITED_SCENARIO_ID, SUBMISSION_COMPLETE_ATTR, WALK_COOKIE, WALK_QUERY,
    WALKTHROUGH_VERSION, known_step_id, neighbors, page_matches, scenario_card_step,
    step_by_id, steps, submission_pending, submission_satisfied,
)
from app.services.workflow_service import get_risk, risk_for_scenario

bp = Blueprint("walkthrough", __name__, url_prefix="/walkthrough")

_SAVE_FIRST = "Save the eligibility case first."


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

    ``submission_complete`` is true when this stop's awaited action has
    succeeded. The form, a validation error, and a file that is not yet
    confirmed pass false and withhold Next. A stop that is not waiting
    still offers Next on its own page.
    """
    step = step_by_id(step_id)
    on_page = page_matches(step, endpoint, view_args)
    previous, following = neighbors(step_id)
    target_href, blocked = destination(step, saved_risk)
    hold = None
    next_href = None
    next_title = None
    finish = False
    if submission_pending(step, submission_complete):
        hold = step.get("pending_notice")
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
    step = step_by_id(step_id)
    saved = None
    decided = False
    if step_id in {"save", "decide"}:
        saved = _saved_prohibited()
    if step.get("await_kind") == "decision" and saved:
        current = (request.view_args or {}).get("risk_id")
        if current == saved["risk_id"]:
            risk = get_risk(get_db(), saved["risk_id"])
            decided = bool(risk and risk.get("decision"))
    complete = submission_satisfied(
        step,
        assessed=bool(getattr(g, SUBMISSION_COMPLETE_ATTR, False)),
        saved=bool(saved),
        decided=decided,
    )
    return build_coach(step_id, request.endpoint, request.view_args, saved, complete)


def scenario_card_href(scenario_id, surface_endpoint):
    """Ready-made card URL.

    A free-form page has no walk query and keeps the plain scenario address.
    A stop that is waiting on its own page keeps that stop on the card.
    Any other known stop links to the guide page for that scenario.
    """
    active_id = known_step_id(request.args.get(WALK_QUERY))
    on_active = False
    if active_id is not None:
        on_active = page_matches(step_by_id(active_id), request.endpoint, request.view_args)
    step_id = scenario_card_step(scenario_id, surface_endpoint, active_id, on_active)
    if step_id is None:
        return url_for(surface_endpoint, scenario_id=scenario_id)
    if active_id is not None and step_id == active_id and on_active:
        return url_for(surface_endpoint, scenario_id=scenario_id, **{WALK_QUERY: step_id})
    step = step_by_id(step_id)
    if step["endpoint"] == surface_endpoint:
        return url_for(surface_endpoint, scenario_id=scenario_id, **{WALK_QUERY: step_id})
    return destination(step, None)[0]


def import_page_href():
    """Import link that does not drop a stop which is still waiting.

    On that stop the link keeps the current id, so Next stays withheld.
    Another known stop opens the import stop. A free-form page stays plain.
    """
    active_id = known_step_id(request.args.get(WALK_QUERY))
    if active_id is None:
        return url_for("try_demo.import_form")
    active = step_by_id(active_id)
    if page_matches(active, request.endpoint, request.view_args) and active.get("await_submission"):
        return url_for("try_demo.import_form", **{WALK_QUERY: active_id})
    return url_for("try_demo.import_form", **{WALK_QUERY: "import"})


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
