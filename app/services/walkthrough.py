"""Ordered stops for the portfolio walkthrough.

The guide names live pages and the facts a visitor should notice. It does
not score, validate evidence, map controls, or decide a disposition. Those
results stay in the existing services. Progress is a step id in a browser
cookie, not a database row.

Stops that set ``await_submission`` withhold Next until that stop's action
has succeeded. Intake, custom vendor, trust center, and file import succeed
only when the current response is a successful assessment. The cookie does
not store that assessment, so a later visit to the form holds Next again.
The save stop succeeds when the eligibility case is already in the register.
The decision stop succeeds when that saved risk has a recorded decision.
"""

from copy import deepcopy

WALKTHROUGH_VERSION = "1.2.2"
WALK_COOKIE = "walk_step"
WALK_QUERY = "walk"
COOKIE_MAX_AGE = 12 * 60 * 60
PROHIBITED_SCENARIO_ID = "prohibited-ai-decisions"
# Set on the request context only for a successful public assessment page.
# A validation error and the form itself leave it unset.
SUBMISSION_COMPLETE_ATTR = "walk_submission_complete"

# Static coaching. Tests lock the scenario facts these sentences rely on.
_STEPS = (
    {
        "step_id": "intake",
        "title": "Intake",
        "summary": "Run a synthetic vendor. Nothing is saved.",
        "notice": (
            "These cards are finished questionnaires. Opening one runs the same "
            "intake path as the form and does not save a risk. The next two stops "
            "stay on this page: one for a vendor you type, and one for the "
            "optional trust-center choice."
        ),
        "endpoint": "try_demo.index",
        "endpoints": ("try_demo.index", "try_demo.assess"),
        "view_args": {},
        "await_submission": True,
        "await_kind": "assessment",
        "pending_notice": "Run assessment on this page before Next.",
    },
    {
        "step_id": "custom",
        "title": "Your own vendor",
        "summary": "Fill the form with a made-up name. Run assessment does not save.",
        "notice": (
            "Use a made-up vendor name. Model training is asked only when AI use "
            "is not none. Run assessment uses the same engine as the ready-made "
            "vendors and does not save. The four results stay separate. A low "
            "residual tier is not an approval."
        ),
        "endpoint": "try_demo.index",
        "endpoints": ("try_demo.index", "try_demo.assess"),
        "view_args": {},
        "anchor": "intake",
        "await_submission": True,
        "await_kind": "assessment",
        "pending_notice": "Run assessment on this page before Next.",
    },
    {
        "step_id": "trust",
        "title": "Trust center is optional",
        "summary": "A URL can be stored. A fetch is an excerpt for review, not verified evidence.",
        "notice": (
            "A trust-center URL is optional. Leave fetch at no and the page is "
            "not opened. Choosing fetch performs one HTTP GET and stores an "
            "excerpt for review. That excerpt is not yet reviewed. It is not "
            "verified evidence, it does not change evidence confidence, and it "
            "does not approve the vendor."
        ),
        "endpoint": "try_demo.index",
        "endpoints": ("try_demo.index", "try_demo.assess"),
        "view_args": {},
        "anchor": "trust-center",
        "await_submission": True,
        "await_kind": "assessment",
        "pending_notice": "Run assessment on this page before Next.",
    },
    {
        "step_id": "evidence",
        "title": "Four separate results",
        "summary": "Inherent risk, evidence confidence, residual risk, and policy stay apart.",
        "notice": (
            "The four cards are separate facts: inherent risk low, evidence "
            "confidence high, residual risk low, and a policy outcome that is not "
            "prohibited. CC-001 is verified. Neither the low residual tier nor "
            "not prohibited is an approval."
        ),
        "endpoint": "try_demo.scenario",
        "view_args": {"scenario_id": "evidence-supported"},
    },
    {
        "step_id": "clause",
        "title": "CC-001 contradicted",
        "summary": "The clause status changes. The score does not.",
        "notice": (
            "CC-001 is conflicting here and verified on the previous vendor. That "
            "status does not change the inherent score, the residual tier, or the "
            "review path. If the residual reason says there are no conflicts, it "
            "means claim evidence, not this clause."
        ),
        "endpoint": "try_demo.scenario",
        "view_args": {"scenario_id": "contract-clause-conflict"},
    },
    {
        "step_id": "conflict",
        "title": "Claim conflict",
        "summary": "A permissions claim is conflicting, so the review escalates.",
        "notice": (
            "The permissions claim is conflicting: the vendor statement and an "
            "internal export disagree. That is a claim conflict, so the residual "
            "tier stays high and ESC-003 escalates the review. The previous stop's "
            "clause conflict did not do that. A residual tier does not approve the "
            "vendor."
        ),
        "endpoint": "try_demo.scenario",
        "view_args": {"scenario_id": "conflicting-claims"},
    },
    {
        "step_id": "high-risk",
        "title": "Review a score cannot skip",
        "summary": "Escalation fires. Missing evidence is not a failed control.",
        "notice": (
            "The score is provisional, the tier is undetermined, and the review "
            "route is escalated. Missing evidence is a gap, not a confirmed "
            "control failure. A residual tier does not turn these rules off or "
            "approve the vendor."
        ),
        "endpoint": "try_demo.scenario",
        "view_args": {"scenario_id": "high-risk-ai"},
    },
    {
        "step_id": "prohibited",
        "title": "Prohibited, and still scored",
        "summary": "HR-001 is a policy outcome. The low residual tier does not clear it.",
        "notice": (
            "Inherent risk is moderate and residual risk is low, and the policy "
            "outcome is prohibited under HR-001. The low tier does not clear the "
            "restriction and is not an approval. This page did not save a decision."
        ),
        "endpoint": "try_demo.scenario",
        "view_args": {"scenario_id": "prohibited-ai-decisions"},
    },
    {
        "step_id": "save",
        "title": "Save is opt-in",
        "summary": "Add the eligibility case to the register when you want a record.",
        "notice": (
            "Saving is opt-in. Add to risk register writes this synthetic case and "
            "a follow-up action. The try page did not. If the case is already "
            "there, this guide opens that shared record. The save is not an "
            "approval, and the prohibited outcome stays."
        ),
        "endpoint": "demos.detail",
        "view_args": {"scenario_id": "prohibited-ai-decisions"},
        "await_submission": True,
        "await_kind": "register",
        "pending_notice": "Add to risk register continues the guide on the saved record.",
    },
    {
        "step_id": "decide",
        "title": "Decision and export",
        "summary": "Record a disposition, then download the package that includes it.",
        "notice": (
            "Record escalate or reject without an exception rationale, or approve "
            "a prohibited result only with one. The prohibited flag stays. Minutes "
            "spent reviewing are optional, and rework minutes are optional. Then "
            "download the package: it includes the decision, and nothing is sent "
            "to ServiceNow."
        ),
        "endpoint": "risks.detail",
        "endpoints": ("risks.detail", "risks.record_risk_decision"),
        "view_args": {},
        "match": "endpoint",
        "await_submission": True,
        "await_kind": "decision",
        "pending_notice": "Record a decision on this page before Next.",
    },
    {
        "step_id": "import",
        "title": "File import",
        "summary": "A file is previewed before the engine runs. Confirm does not save.",
        "notice": (
            "Preview a sample file. The preview has no score, and ticket priority "
            "does not set residual risk. Confirm runs the same engine and does not "
            "save. Saving is a checkbox on the result. The disposition is separate "
            "from the residual tier. ServiceNow is not called."
        ),
        "endpoint": "try_demo.import_form",
        "endpoints": (
            "try_demo.import_form",
            "try_demo.import_preview",
            "try_demo.import_confirm",
            "try_demo.import_save",
        ),
        "view_args": {},
        "await_submission": True,
        "await_kind": "assessment",
        "pending_notice": "Confirm the file on this page before Next.",
    },
    {
        "step_id": "dashboard",
        "title": "Measured and modeled",
        "summary": "Register counts and the cost panel are different numbers.",
        "notice": (
            "The observed panel counts saved records. Cycle time stays empty on a "
            "scenario save, which does not store both an intake event and a "
            "disposition event. Self-reported handling minutes appear only when "
            "a decision includes them. Self-reported rework minutes are a separate "
            "figure and appear only when a decision includes them. The cost panel "
            "is modeled labor capacity, not cash savings."
        ),
        "endpoint": "dashboard.index",
        "view_args": {},
    },
    {
        "step_id": "methods",
        "title": "Methods",
        "summary": "The rules, the policy, and the formula are on one page.",
        "notice": (
            "The rule set, the org policy, the clause check, and the cost formula "
            "are here. Mappings stay draft. Nothing here certifies a vendor or "
            "turns modeled hours into cash savings."
        ),
        "endpoint": "methodology.index",
        "view_args": {},
    },
)

_BY_ID = {item["step_id"]: item for item in _STEPS}


def steps():
    """Return a copy of the ordered stops, numbered from 1."""
    materialized = []
    for number, source in enumerate(_STEPS, start=1):
        item = deepcopy(source)
        item["number"] = number
        materialized.append(item)
    return materialized


def step_by_id(step_id):
    """Return one stop, or raise KeyError when the id is not in the guide."""
    found = _BY_ID[step_id]
    item = deepcopy(found)
    item["number"] = next(index for index, source in enumerate(_STEPS, start=1)
                          if source["step_id"] == step_id)
    return item


def known_step_id(value):
    """Return a step id from a query value or cookie, or None when it is not one."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if candidate in _BY_ID:
        return candidate
    return None


def neighbors(step_id):
    """Return the previous and next stops, either of which may be missing."""
    ordered = steps()
    index = next(position for position, item in enumerate(ordered) if item["step_id"] == step_id)
    previous = ordered[index - 1] if index else None
    following = ordered[index + 1] if index + 1 < len(ordered) else None
    return previous, following


def page_matches(step, endpoint, view_args):
    """Whether this request is the page the stop is coaching."""
    if not endpoint:
        return False
    allowed = step.get("endpoints") or (step["endpoint"],)
    if endpoint not in allowed:
        return False
    if step.get("match") == "endpoint":
        return True
    view_args = view_args or {}
    return all(view_args.get(key) == value for key, value in step["view_args"].items())


def submission_satisfied(step, *, assessed=False, saved=False, decided=False):
    """Whether an ``await_submission`` stop has succeeded for this response.

    ``assessment`` is the current response only: a successful public
    assessment or a confirmed file import. A validation error leaves it
    false. The cookie does not store it.

    ``register`` is true when the eligibility case is already in the
    register. ``decision`` is true when that saved risk has a recorded
    decision. Stops that do not wait are never satisfied by this check.
    """
    if not step.get("await_submission"):
        return False
    kind = step.get("await_kind", "assessment")
    if kind == "assessment":
        return bool(assessed)
    if kind == "register":
        return bool(saved)
    if kind == "decision":
        return bool(decided)
    return False


def submission_pending(step, submission_complete):
    """Whether this stop must withhold Next.

    A stop marked ``await_submission`` is complete only when
    ``submission_complete`` is true. ``submission_satisfied`` is how a
    caller decides that flag. Other stops are never pending.
    """
    if not step.get("await_submission"):
        return False
    return not submission_complete


def scenario_stop_id(scenario_id, surface_endpoint):
    """Return the guide stop for a ready-made scenario on one surface.

    The eligibility case on the demo surface is the save stop. Each public
    scenario is that scenario's try-page stop. None when the guide has no
    stop for the scenario.
    """
    if not isinstance(scenario_id, str):
        return None
    fallback = None
    for source in _STEPS:
        if source["view_args"].get("scenario_id") != scenario_id:
            continue
        if source["endpoint"] == surface_endpoint:
            return source["step_id"]
        if source["endpoint"] == "try_demo.scenario":
            fallback = source["step_id"]
    return fallback


def scenario_card_step(scenario_id, surface_endpoint, active_walk, on_active_page):
    """Walk query for one ready-made card, or None on a free-form page.

    A stop that is waiting on its own page keeps that id, so opening the
    card does not advance Next. Any other known stop uses the guide stop
    for this scenario. Unknown walk values stay coach-free.
    """
    if known_step_id(active_walk) is None:
        return None
    active = step_by_id(active_walk)
    if on_active_page and active.get("await_submission"):
        return active["step_id"]
    return scenario_stop_id(scenario_id, surface_endpoint)


def carried_walk_step(raw, *, advance_from=None):
    """Return the step id to keep on a redirect.

    ``advance_from`` moves that one stop forward. Saving the guided case
    opens the decision stop. Any other known id is preserved. Unknown
    values are dropped so a crafted query cannot be echoed into a page.
    """
    step_id = known_step_id(raw)
    if step_id is None:
        return None
    if advance_from and step_id == advance_from:
        _previous, following = neighbors(step_id)
        return following["step_id"] if following else None
    return step_id


def progress_step_id(raw, endpoint, view_args):
    """Return the step id to store when this response is that stop's own page."""
    step_id = known_step_id(raw)
    if step_id is None:
        return None
    if page_matches(step_by_id(step_id), endpoint, view_args):
        return step_id
    return None
