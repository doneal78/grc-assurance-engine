"""Persistence and input validation for the local risk/remediation workflow."""

import json
import re
from datetime import date, datetime, timezone
from uuid import uuid4

from flask import current_app, has_request_context

from app.services.event_chain import (
    CHAIN_ORIGIN_APPENDED, GENESIS_PREV_HASH, event_digest, write_chain_tip,
)
from app.services.sandbox import DEFAULT_MAX_RISKS, UNSCOPED


class WorkflowInputError(ValueError):
    """Raised when a workflow update contains invalid values."""


ACTION_STATUSES = {"open", "in_progress", "completed"}
DISPOSITIONS = ("approve", "approve_with_conditions", "escalate", "reject")
APPROVAL_DISPOSITIONS = {"approve", "approve_with_conditions"}
DISPOSITION_RULE = "disposition must be approve, approve with conditions, escalate, or reject"
MAX_DECISION_TEXT = 1000
MAX_DECIDER = 100
MAX_STORED_MINUTES = 2**63 - 1
_WHOLE_MINUTES = re.compile(r"^(0|[1-9][0-9]*)$")
_NEGATIVE_MINUTES = re.compile(r"^-\d+$")


def _whole_number_rule(field, unit):
    return f"{field} must be a non-negative whole number of {unit}, or be left blank"


def _minutes_rule(field):
    return _whole_number_rule(field, "minutes")


HANDLING_MINUTES_RULE = _minutes_rule("handling_minutes")
REWORK_MINUTES_RULE = _minutes_rule("rework_minutes")
MANUAL_TOUCHES_RULE = _whole_number_rule("manual_touches", "touches")
HANDOFFS_RULE = _whole_number_rule("handoffs", "handoffs")
AUTHENTICATED_EFFORT_RULE = _minutes_rule("authenticated_effort_minutes")
AUTHENTICATED_EFFORT_GATE = (
    "authenticated_effort_minutes is recorded only for a signed-in reviewer"
)
CASH_SAVINGS_RULE = _whole_number_rule("cash_savings_dollars", "dollars")
CASH_SAVINGS_GATE = (
    "cash_savings_dollars is recorded only for a signed-in reviewer"
)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_event(db, risk_id, event_type, detail, occurred_at, sandbox_id=None):
    """Insert one workflow event and link it to the previous hash in its chain.

    Events with no sandbox id continue the shared chain. A browser sandbox
    continues only that sandbox's chain. The hash covers the canonical event
    fields plus ``prev_hash``. The sandbox id is stored and is not hashed.
    The row is marked appended, which means it was hashed when it was written.
    Does not commit.
    """
    if sandbox_id is None:
        previous = db.execute(
            """SELECT hash FROM workflow_events
               WHERE sandbox_id IS NULL
               ORDER BY event_id DESC LIMIT 1"""
        ).fetchone()
    else:
        previous = db.execute(
            """SELECT hash FROM workflow_events
               WHERE sandbox_id = ?
               ORDER BY event_id DESC LIMIT 1""",
            (sandbox_id,),
        ).fetchone()
    prev_hash = GENESIS_PREV_HASH if previous is None else previous["hash"]
    cursor = db.execute(
        """INSERT INTO workflow_events
           (risk_id, event_type, detail, occurred_at, prev_hash, hash, chain_origin, sandbox_id)
           VALUES (?, ?, ?, ?, ?, NULL, ?, ?)""",
        (risk_id, event_type, detail, occurred_at, prev_hash, CHAIN_ORIGIN_APPENDED, sandbox_id),
    )
    event_id = cursor.lastrowid
    payload = {
        "event_id": event_id,
        "risk_id": risk_id,
        "event_type": event_type,
        "detail": detail,
        "occurred_at": occurred_at,
        "prev_hash": prev_hash,
        "chain_origin": CHAIN_ORIGIN_APPENDED,
    }
    digest = event_digest(payload)
    db.execute(
        "UPDATE workflow_events SET hash = ? WHERE event_id = ?",
        (digest, event_id),
    )
    write_chain_tip(db, event_id, digest, sandbox_id)
    return event_id


def sandbox_visible(owner, sandbox_id):
    """Whether one stored sandbox id may be shown for this caller.

    ``UNSCOPED`` is a service call and can see every row. A null owner is a
    shared row and stays visible. Any other owner matches only that sandbox.
    """
    if sandbox_id is UNSCOPED:
        return True
    if owner is None:
        return True
    return owner == sandbox_id


def _list_scope(sandbox_id):
    if sandbox_id is UNSCOPED:
        return "", []
    if sandbox_id is None:
        return "WHERE r.sandbox_id IS NULL", []
    return "WHERE r.sandbox_id IS NULL OR r.sandbox_id = ?", [sandbox_id]


def _dict(row):
    return dict(row) if row is not None else None


def list_risks(db, sandbox_id=UNSCOPED):
    where, args = _list_scope(sandbox_id)
    rows = db.execute(
        f"""SELECT r.*,
           (SELECT COUNT(*) FROM remediation_actions a WHERE a.risk_id = r.risk_id) AS action_count,
           (SELECT COUNT(*) FROM remediation_actions a
            WHERE a.risk_id = r.risk_id AND a.status != 'completed') AS open_action_count,
           (SELECT d.disposition FROM decisions d WHERE d.risk_id = r.risk_id) AS decision_disposition
           FROM risks r {where} ORDER BY r.created_at DESC""",
        args,
    ).fetchall()
    return [_dict(row) for row in rows]


def get_risk(db, risk_id, sandbox_id=UNSCOPED):
    row = db.execute("SELECT * FROM risks WHERE risk_id = ?", (risk_id,)).fetchone()
    if row is None:
        return None
    risk = _dict(row)
    if not sandbox_visible(risk.get("sandbox_id"), sandbox_id):
        return None
    risk["rationale"] = json.loads(risk.pop("rationale_json"))
    risk["actions"] = [_dict(item) for item in db.execute(
        "SELECT * FROM remediation_actions WHERE risk_id = ? ORDER BY action_id", (risk_id,)
    ).fetchall()]
    risk["events"] = [_dict(item) for item in db.execute(
        "SELECT * FROM workflow_events WHERE risk_id = ? ORDER BY event_id", (risk_id,)
    ).fetchall()]
    risk["decision"] = _dict(db.execute(
        "SELECT * FROM decisions WHERE risk_id = ?", (risk_id,)
    ).fetchone())
    return risk


def risk_for_scenario(db, scenario_id, sandbox_id=None):
    """Return the shared row, or the row in one browser sandbox.

    ``sandbox_id`` omitted or ``None`` selects the shared row, whose sandbox
    id is null. A browser id selects only that sandbox. Another browser's
    copy is not returned.
    """
    if sandbox_id is None:
        row = db.execute(
            "SELECT risk_id FROM risks WHERE scenario_id = ? AND sandbox_id IS NULL",
            (scenario_id,),
        ).fetchone()
    else:
        row = db.execute(
            "SELECT risk_id FROM risks WHERE scenario_id = ? AND sandbox_id = ?",
            (scenario_id, sandbox_id),
        ).fetchone()
    return _dict(row)


def _enforce_sandbox_cap(db, sandbox_id):
    """Reject a new row when this browser sandbox is already at its cap.

    Shared rows have no sandbox id and are not capped here. The cap is a
    size limit for one browser, not a security boundary.
    """
    if sandbox_id is None:
        return
    maximum = DEFAULT_MAX_RISKS
    if has_request_context():
        configured = current_app.config.get("SANDBOX_MAX_RISKS", DEFAULT_MAX_RISKS)
        if isinstance(configured, int) and configured >= 1:
            maximum = configured
    count = db.execute(
        "SELECT COUNT(*) AS n FROM risks WHERE sandbox_id = ?",
        (sandbox_id,),
    ).fetchone()["n"]
    if count >= maximum:
        raise WorkflowInputError(
            f"This browser sandbox already holds the maximum of {maximum} saved assessments. "
            "Nothing new was saved."
        )


def _sandbox_for_risk(db, risk_id):
    row = db.execute(
        "SELECT sandbox_id FROM risks WHERE risk_id = ?",
        (risk_id,),
    ).fetchone()
    if row is None:
        return None
    return row["sandbox_id"]


def _stored_rationale(result):
    """Keep the inputs a reviewer package needs beside the evaluation.

    Rows saved before this shape have only risk, claims, mappings, and the
    scenario set version. The export says so instead of inventing answers.
    General intake has no scenario id. Those rows record that origin so a
    saved import is distinguishable from a scenario fixture.
    """
    stored = {
        "risk": result["risk"],
        "claims": result["claims"],
        "mappings": result["mappings"],
        "scenario_set_version": result.get("scenario_set_version"),
        "assessment_inputs": result.get("assessment_inputs"),
        "answer_applicability": result.get("answer_applicability") or {},
        "direction_context": result.get("direction_context"),
        "evidence_policy_version": result.get("evidence_policy_version"),
        "as_of": result.get("as_of"),
        "trust_center": result.get("trust_center"),
        "questionnaire_version": result.get("questionnaire_version"),
        "vendor_name": result.get("name"),
        "summary": result.get("summary"),
    }
    if result.get("scenario_id") is None:
        stored["intake_origin"] = "general_intake"
        for key in ("source_row", "ticket_number", "import_format"):
            if result.get(key) is not None:
                stored[key] = result[key]
    return stored


def _intake_statement(result):
    """Label a saved intake as synthetic, and keep the engine tier separate."""
    summary = result.get("summary") or ""
    summary = summary.replace(
        "Synthetic input, not saved.",
        "Synthetic demonstration data, saved after a person confirmed.",
    )
    note = "The residual tier is not an approval."
    if note not in summary:
        summary = f"{summary} {note}".strip()
    return summary


def register_scenario(db, result, sandbox_id=None):
    """Persist one scenario as a local risk record and create a follow-up action.

    ``sandbox_id`` omitted stores a shared row. A browser id stores a private
    copy in that sandbox. The same scenario can exist once per sandbox.
    """
    if not result.get("synthetic_data"):
        raise WorkflowInputError("Only synthetic demonstration scenarios may be saved by this workflow.")
    scenario_id = result.get("scenario_id")
    existing = risk_for_scenario(db, scenario_id, sandbox_id=sandbox_id)
    if existing:
        return existing["risk_id"]
    _enforce_sandbox_cap(db, sandbox_id)
    risk_id = _persist_assessment(
        db, result, scenario_id, result["summary"],
        "Synthetic scenario result added to the local risk register.",
        sandbox_id=sandbox_id,
    )
    db.commit()
    return risk_id


def register_intake(db, result, decision, *, commit=True, sandbox_id=None):
    """Save one synthetic intake and the human disposition in one transaction.

    The caller has already confirmed. Assess-only results never reach this
    function. The disposition is stored on the decision row. It is not copied
    into the residual tier, and a low tier is not treated as approval.
    """
    if not result.get("synthetic_data"):
        raise WorkflowInputError("Only synthetic demonstration data may be saved by this workflow.")
    if result.get("scenario_id"):
        raise WorkflowInputError("Scenario results are saved with the scenario register action.")
    if not isinstance(decision, dict):
        raise WorkflowInputError("A decision object is required to save an intake.")
    problems, normalized = decision_problems(
        result.get("risk") or {},
        decision.get("disposition", ""),
        decision.get("rationale", ""),
        decision.get("decider", ""),
        decision.get("conditions", ""),
        decision.get("exception_rationale", ""),
        decision.get("handling_minutes"),
        decision.get("rework_minutes"),
        decision.get("manual_touches"),
        decision.get("handoffs"),
        decision.get("authenticated_effort_minutes"),
        decision.get("cash_savings_dollars"),
        accept_authenticated_effort=bool(decision.get("accept_authenticated_effort")),
        accept_cash_savings=bool(decision.get("accept_cash_savings")),
    )
    if problems:
        raise WorkflowInputError("; ".join(problems))
    _enforce_sandbox_cap(db, sandbox_id)
    risk_id = _persist_assessment(
        db, result, f"intake-{uuid4().hex[:12]}", _intake_statement(result),
        "Synthetic general intake added to the local risk register. Demonstration data.",
        opening_event=(
            "intake_received",
            "Synthetic general intake confirmed for save. Demonstration data. "
            "The engine score is not a disposition.",
        ),
        sandbox_id=sandbox_id,
    )
    _save_decision_row(db, risk_id, normalized, existing=None)
    if commit:
        db.commit()
    return risk_id


def _persist_assessment(db, result, scenario_id, statement, created_detail, opening_event=None,
                        sandbox_id=None):
    """Insert the risk, its follow-up action, and the creation events. Does not commit."""
    risk_id = f"R-{uuid4().hex[:8].upper()}"
    risk = result["risk"]
    now = _now()
    policy = risk.get("policy") or {}
    policy_outcome = (risk.get("policy_outcome") or {}).get("status")
    db.execute(
        """INSERT INTO risks
        (risk_id, scenario_id, scenario_name, risk_statement, inherent_tier, residual_tier,
         rationale_json, created_at, policy_id, policy_version, policy_outcome, sandbox_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (risk_id, scenario_id, result["name"], statement, risk["inherent"]["tier"],
         risk["residual"]["tier"], json.dumps(_stored_rationale(result)), now,
         policy.get("policy_id"), policy.get("policy_version"), policy_outcome, sandbox_id),
    )
    if opening_event:
        _append_event(db, risk_id, opening_event[0], opening_event[1], now, sandbox_id)
    _append_event(db, risk_id, "risk_created", created_detail, now, sandbox_id)

    statuses = {claim["evidence_status"] for claim in result["claims"]}
    prohibited = policy_outcome == "prohibited"
    gap_statuses = {"missing", "conflicting", "expired", "not_reviewed"}
    evidence_gap = bool(statuses & gap_statuses)
    clause_gaps = [clause for clause in (policy.get("required_contract_clauses") or [])
                   if clause.get("evidence_status") in gap_statuses]
    needs_action = bool(risk["escalations"] or prohibited or evidence_gap or clause_gaps)
    if needs_action:
        priority = "critical" if risk["inherent"]["tier"] == "critical" else "high"
        if prohibited and (risk["escalations"] or evidence_gap or clause_gaps):
            description = ("Review escalations or evidence gaps, and record a human decision on the "
                           "policy restriction. Proceeding requires an exception rationale.")
        elif prohibited:
            description = ("Policy restriction matched. Record a human decision. "
                           "Proceeding requires an exception rationale.")
        elif clause_gaps and not risk["escalations"] and not evidence_gap:
            ids = ", ".join(clause["clause_id"] for clause in clause_gaps)
            description = (f"Required contract clause evidence needs review ({ids}). "
                           "The score is unchanged. A person records the disposition.")
        else:
            description = "Review escalations and resolve evidence gaps or conflicts."
        db.execute(
            """INSERT INTO remediation_actions
            (risk_id, description, priority, owner, due_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (risk_id, description, priority, "Unassigned", None, "open", now, now),
        )
        _append_event(db, risk_id, "remediation_created", description, now, sandbox_id)
    return risk_id


def update_action(db, action_id, status, owner, due_date, completion_notes, sandbox_id=UNSCOPED):
    problems = []
    if status not in ACTION_STATUSES:
        problems.append("status must be open, in_progress, or completed")
    if not isinstance(owner, str) or not owner.strip() or len(owner.strip()) > 100:
        problems.append("owner must contain 1 to 100 characters")
    if due_date:
        try:
            date.fromisoformat(due_date)
        except (TypeError, ValueError):
            problems.append("due date must use YYYY-MM-DD")
    if not isinstance(completion_notes, str) or len(completion_notes) > 1000:
        problems.append("completion notes must be 1000 characters or fewer")
    elif status == "completed" and not completion_notes.strip():
        problems.append("completion notes are required to mark an action completed")
    if problems:
        raise WorkflowInputError("; ".join(problems))

    row = db.execute(
        """SELECT a.risk_id, r.sandbox_id
           FROM remediation_actions a
           JOIN risks r ON r.risk_id = a.risk_id
           WHERE a.action_id = ?""",
        (action_id,),
    ).fetchone()
    if row is None or not sandbox_visible(row["sandbox_id"], sandbox_id):
        return None
    risk_id = row["risk_id"]
    now = _now()
    db.execute(
        """UPDATE remediation_actions SET status = ?, owner = ?, due_date = ?,
           completion_notes = ?, updated_at = ? WHERE action_id = ?""",
        (status, owner.strip(), due_date or None, completion_notes.strip(), now, action_id),
    )
    _append_event(
        db, risk_id, "remediation_updated", f"Action {action_id} status changed to {status}.", now,
        row["sandbox_id"],
    )
    db.commit()
    return risk_id


def parse_optional_whole_number(value, field, unit):
    """Return ``(problems, number)`` for one optional self-reported whole number.

    ``None`` and blank text mean the person did not report a number, so the
    stored value is null. A non-negative whole number is kept as an int.
    Zero is a reported zero. Negatives, fractions, booleans, and other text
    are rejected. They are not rounded, truncated, or turned into zero.
    ``unit`` is the word in the rejection message, such as minutes or touches.
    """
    rule = _whole_number_rule(field, unit)
    if value is None:
        return [], None
    if isinstance(value, bool):
        return [f"{rule}. A boolean was not stored."], None
    if isinstance(value, int):
        if value < 0:
            return [f"{field} cannot be negative."], None
        if value > MAX_STORED_MINUTES:
            return [f"{field} is too large to store."], None
        return [], value
    if isinstance(value, float):
        return [f"{rule}. A fractional value was not stored."], None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return [], None
        if _NEGATIVE_MINUTES.fullmatch(text):
            return [f"{field} cannot be negative."], None
        if not _WHOLE_MINUTES.fullmatch(text):
            return [f"{rule}."], None
        number = int(text)
        if number > MAX_STORED_MINUTES:
            return [f"{field} is too large to store."], None
        return [], number
    return [f"{rule}."], None


def parse_optional_minutes(value, field):
    """Return ``(problems, minutes)`` for one optional self-reported minute field."""
    return parse_optional_whole_number(value, field, "minutes")


def parse_handling_minutes(value):
    """Return ``(problems, minutes)`` for optional self-reported handling time."""
    return parse_optional_minutes(value, "handling_minutes")


def parse_rework_minutes(value):
    """Return ``(problems, minutes)`` for optional self-reported rework time.

    Rework is time spent redoing work after a first pass. It is not handling
    time, not elapsed cycle time, and not an input to the cost formula.
    """
    return parse_optional_minutes(value, "rework_minutes")


def parse_manual_touches(value):
    """Return ``(problems, count)`` for optional self-reported manual touches.

    The count is human touchpoints on that assessment, as the person reports
    them. It is not handling minutes, not rework minutes, not elapsed cycle
    time, and not an input to the cost formula.
    """
    return parse_optional_whole_number(value, "manual_touches", "touches")


def parse_handoffs(value):
    """Return ``(problems, count)`` for optional self-reported handoffs.

    The count is how many times the assessment was handed between people or
    queues before disposition, as the person reports it. It is not handling
    minutes, not rework minutes, not a manual-touch count, not elapsed cycle
    time, and not an input to the cost formula.
    """
    return parse_optional_whole_number(value, "handoffs", "handoffs")


def parse_authenticated_effort_minutes(value):
    """Return ``(problems, minutes)`` for optional signed-in effort minutes.

    The number is what a signed-in reviewer entered for time spent on this
    disposition. Blank and null mean it was not reported. It is not a session
    timer, not self-reported handling time, not elapsed cycle time, and not
    an input to the cost formula. This parser does not check the password
    gate. The caller does.
    """
    return parse_optional_minutes(value, "authenticated_effort_minutes")


def parse_cash_savings_dollars(value):
    """Return ``(problems, dollars)`` for optional reported cash savings.

    The number is whole dollars a signed-in reviewer entered when a spending
    reduction was known. Blank and null mean it was not reported. Zero is a
    reported zero. This parser does not multiply minutes by a wage, does not
    read the cost assumptions, and does not check the password gate. The
    caller does.
    """
    return parse_optional_whole_number(value, "cash_savings_dollars", "dollars")


def _required_text(value, label, limit):
    if not isinstance(value, str):
        return None, f"{label} must contain 1 to {limit} characters"
    text = value.strip()
    if not text or len(text) > limit:
        return None, f"{label} must contain 1 to {limit} characters"
    return text, None


def decision_problems(evaluation, disposition, rationale, decider, conditions="",
                      exception_rationale="", handling_minutes=None, rework_minutes=None,
                      manual_touches=None, handoffs=None, authenticated_effort_minutes=None,
                      cash_savings_dollars=None, *, accept_authenticated_effort=False,
                      accept_cash_savings=False):
    """Validate a human disposition against one engine result.

    Returns (problems, normalized). An empty problem list means normalized is
    ready to store. The residual tier is not an input. Escalate is a human
    choice to send the case on. It is not an approval, so a prohibited result
    does not require an exception rationale for it.

    ``handling_minutes`` is optional. Omitted, null, and blank mean the
    person did not report how long the review took. A reported value is a
    non-negative whole number of minutes. It is not elapsed cycle time and
    it is not an input to the cost formula.

    ``rework_minutes`` is optional and separate. Omitted, null, and blank
    mean rework time was not reported. A reported value is a non-negative
    whole number of minutes spent redoing work after a first pass. It is not
    handling time, not elapsed cycle time, and not an input to the cost formula.

    ``manual_touches`` is optional and separate. Omitted, null, and blank
    mean a touchpoint count was not reported. A reported value is a
    non-negative whole number of human touchpoints on that assessment. It is
    not handling minutes, not rework minutes, not elapsed cycle time, and not
    an input to the cost formula.

    ``handoffs`` is optional and separate. Omitted, null, and blank mean a
    handoff count was not reported. A reported value is a non-negative whole
    number of times the assessment was handed between people or queues before
    disposition. It is not handling minutes, not rework minutes, not a
    manual-touch count, not elapsed cycle time, and not an input to the cost
    formula.

    ``authenticated_effort_minutes`` is optional and separate. It is stored
    only when ``accept_authenticated_effort`` is true, which the signed-in
    disposition route sets after the demo password gate. Omitted, null, and
    blank then mean the reviewer did not report minutes. A reported value is
    a non-negative whole number. A public try, an import save, and any other
    caller that leaves the flag false cannot store a number. A blank from
    those callers does not clear a number already stored. The minutes are not
    a session timer, not handling minutes, not rework minutes, not a touch
    count, not a handoff count, not elapsed cycle time, not cash savings, and
    not an input to the cost formula.

    ``cash_savings_dollars`` is optional and separate. It is stored only when
    ``accept_cash_savings`` is true, which the same signed-in disposition
    route sets. Omitted, null, and blank then mean the reviewer did not report
    a spending reduction. A reported value is a non-negative whole number of
    dollars the person typed. Zero is a reported zero. A public try, an import
    save, and any other caller that leaves the flag false cannot store a
    number. A blank from those callers does not clear a number already stored.
    The dollars are not handling minutes, not rework minutes, not a touch
    count, not a handoff count, not authenticated effort, not a wage times any
    of those figures, not the illustrative labor rate, and not an input to
    the cost formula.
    """
    problems = []
    if disposition not in DISPOSITIONS:
        problems.append(DISPOSITION_RULE)
    rationale_text, rationale_problem = _required_text(rationale, "rationale", MAX_DECISION_TEXT)
    if rationale_problem:
        problems.append(rationale_problem)
    decider_text, decider_problem = _required_text(decider, "decider", MAX_DECIDER)
    if decider_problem:
        problems.append(decider_problem)
    if not isinstance(conditions, str) or len(conditions) > MAX_DECISION_TEXT:
        conditions_text = ""
        problems.append(f"conditions must be {MAX_DECISION_TEXT} characters or fewer")
    else:
        conditions_text = conditions.strip()
    if disposition == "approve_with_conditions":
        if not conditions_text:
            problems.append("conditions are required when approving with conditions")
    elif conditions_text:
        problems.append("conditions are stored only for approve with conditions")
    if not isinstance(exception_rationale, str) or len(exception_rationale) > MAX_DECISION_TEXT:
        exception_text = ""
        problems.append(f"exception rationale must be {MAX_DECISION_TEXT} characters or fewer")
    else:
        exception_text = exception_rationale.strip()
    minute_problems, minutes = parse_handling_minutes(handling_minutes)
    problems.extend(minute_problems)
    rework_problems, rework = parse_rework_minutes(rework_minutes)
    problems.extend(rework_problems)
    touch_problems, touches = parse_manual_touches(manual_touches)
    problems.extend(touch_problems)
    handoff_problems, handoff_count = parse_handoffs(handoffs)
    problems.extend(handoff_problems)
    effort_problems, effort = parse_authenticated_effort_minutes(authenticated_effort_minutes)
    problems.extend(effort_problems)
    if accept_authenticated_effort:
        keep_effort = False
    elif effort is not None:
        problems.append(AUTHENTICATED_EFFORT_GATE + ".")
        keep_effort = True
        effort = None
    else:
        keep_effort = True
        effort = None
    savings_problems, savings = parse_cash_savings_dollars(cash_savings_dollars)
    problems.extend(savings_problems)
    if accept_cash_savings:
        keep_savings = False
    elif savings is not None:
        problems.append(CASH_SAVINGS_GATE + ".")
        keep_savings = True
        savings = None
    else:
        keep_savings = True
        savings = None

    evaluation = evaluation or {}
    policy = evaluation.get("policy") or {}
    outcome = evaluation.get("policy_outcome") or {}
    policy_id = policy.get("policy_id")
    policy_version = policy.get("policy_version")
    rule_set_version = evaluation.get("rule_set_version")
    outcome_status = outcome.get("status")
    if (not policy_id or not policy_version or not rule_set_version
            or outcome_status not in {"prohibited", "not_prohibited"}):
        problems.append("this saved result has no policy reference, so a decision cannot be recorded against it")
        prohibited = False
    else:
        prohibited = outcome_status == "prohibited"
    proceeding = prohibited and disposition in APPROVAL_DISPOSITIONS
    if proceeding and not exception_text:
        problems.append("a prohibited result cannot be approved without an exception rationale")
    if exception_text and not proceeding:
        problems.append("an exception rationale is only recorded when approving a prohibited result")
    if problems:
        return problems, None
    return [], {
        "disposition": disposition,
        "conditions": conditions_text,
        "rationale": rationale_text,
        "exception_rationale": exception_text,
        "decider": decider_text,
        "policy_id": policy_id,
        "policy_version": policy_version,
        "rule_set_version": rule_set_version,
        "prohibited_at_decision": outcome_status,
        "handling_minutes": minutes,
        "rework_minutes": rework,
        "manual_touches": touches,
        "handoffs": handoff_count,
        "authenticated_effort_minutes": effort,
        "keep_authenticated_effort": keep_effort,
        "cash_savings_dollars": savings,
        "keep_cash_savings": keep_savings,
    }


def record_decision(db, risk_id, disposition, rationale, decider, conditions="",
                    exception_rationale="", handling_minutes=None, rework_minutes=None,
                    manual_touches=None, handoffs=None, authenticated_effort_minutes=None,
                    cash_savings_dollars=None, *, accept_authenticated_effort=False,
                    accept_cash_savings=False, sandbox_id=UNSCOPED):
    """Record the human disposition for one saved risk.

    A prohibited result can still be approved. The check cites the policy and
    stops an unrecorded override; it does not decide the case. Proceeding,
    with or without conditions, requires an exception rationale. Rejection
    and escalation do not. The exception does not clear the prohibited
    outcome. An exception rationale is rejected when the result is not
    prohibited, or when the disposition is reject or escalate, so the field
    means only "proceed despite the restriction."

    The policy id, policy version, and rule set version are copied from the
    saved assessment. The caller cannot supply a different reference.

    ``handling_minutes`` is optional self-reported review time. Blank and
    null leave the column null. A later save with a blank field clears a
    number that was stored before.

    ``rework_minutes`` follows the same rule on its own column. Blank and
    null leave rework unmeasured. A later save with a blank rework field
    clears a number that was stored before. An invalid value rejects the
    save and leaves the current row unchanged.

    ``manual_touches`` follows the same rule on its own column. Blank and
    null leave the touchpoint count unmeasured. A later save with a blank
    manual-touches field clears a number that was stored before. An invalid
    value rejects the save and leaves the current row unchanged.

    ``handoffs`` follows the same rule on its own column. Blank and null
    leave the handoff count unmeasured. A later save with a blank handoffs
    field clears a number that was stored before. An invalid value rejects
    the save and leaves the current row unchanged.

    ``authenticated_effort_minutes`` is stored only when
    ``accept_authenticated_effort`` is true. A signed-in save with a blank
    field clears a number stored earlier. A save that is not signed in leaves
    the column as it was. A number sent without that flag rejects the save
    and leaves the current row unchanged.

    ``cash_savings_dollars`` is stored only when ``accept_cash_savings`` is
    true. A signed-in save with a blank field clears a number stored earlier.
    A save that is not signed in leaves the column as it was. A number sent
    without that flag rejects the save and leaves the current row unchanged.
    The stored integer is the dollars the person typed. It is not a wage
    times handling minutes, rework minutes, touches, handoffs, or
    authenticated effort.
    """
    risk = get_risk(db, risk_id, sandbox_id=sandbox_id)
    if risk is None:
        return None
    stored = risk["rationale"].get("risk", {})
    problems, normalized = decision_problems(
        stored, disposition, rationale, decider, conditions, exception_rationale,
        handling_minutes, rework_minutes, manual_touches, handoffs,
        authenticated_effort_minutes, cash_savings_dollars,
        accept_authenticated_effort=accept_authenticated_effort,
        accept_cash_savings=accept_cash_savings,
    )
    if problems:
        raise WorkflowInputError("; ".join(problems))
    _save_decision_row(db, risk_id, normalized, existing=risk["decision"])
    db.commit()
    return risk_id


def _save_decision_row(db, risk_id, normalized, existing):
    """Write one decision row and its workflow event. Does not commit."""
    now = _now()
    if normalized["keep_authenticated_effort"] and existing:
        effort = existing.get("authenticated_effort_minutes")
    else:
        effort = normalized["authenticated_effort_minutes"]
    if normalized["keep_cash_savings"] and existing:
        savings = existing.get("cash_savings_dollars")
    else:
        savings = normalized["cash_savings_dollars"]
    values = (
        normalized["disposition"], normalized["conditions"], normalized["rationale"],
        normalized["exception_rationale"], normalized["decider"], normalized["policy_id"],
        normalized["policy_version"], normalized["rule_set_version"],
        normalized["prohibited_at_decision"], now, normalized["handling_minutes"],
        normalized["rework_minutes"], normalized["manual_touches"],
        normalized["handoffs"], effort, savings, risk_id,
    )
    if existing:
        db.execute(
            """UPDATE decisions SET disposition = ?, conditions = ?, rationale = ?,
               exception_rationale = ?, decider = ?, policy_id = ?, policy_version = ?,
               rule_set_version = ?, prohibited_at_decision = ?, decided_at = ?,
               handling_minutes = ?, rework_minutes = ?, manual_touches = ?,
               handoffs = ?, authenticated_effort_minutes = ?, cash_savings_dollars = ?
               WHERE risk_id = ?""",
            values,
        )
    else:
        db.execute(
            """INSERT INTO decisions
            (disposition, conditions, rationale, exception_rationale, decider, policy_id,
             policy_version, rule_set_version, prohibited_at_decision, decided_at,
             handling_minutes, rework_minutes, manual_touches, handoffs,
             authenticated_effort_minutes, cash_savings_dollars, risk_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
    detail = (f"{normalized['disposition']} by {normalized['decider']}. "
              f"Policy {normalized['policy_id']} {normalized['policy_version']}. "
              f"Rule set {normalized['rule_set_version']}. "
              f"Policy outcome {normalized['prohibited_at_decision']}.")
    if normalized["handling_minutes"] is not None:
        detail += f" Self-reported handling minutes: {normalized['handling_minutes']}."
    if normalized["rework_minutes"] is not None:
        detail += f" Self-reported rework minutes: {normalized['rework_minutes']}."
    if normalized["manual_touches"] is not None:
        detail += f" Self-reported manual touches: {normalized['manual_touches']}."
    if normalized["handoffs"] is not None:
        detail += f" Self-reported handoffs: {normalized['handoffs']}."
    if not normalized["keep_authenticated_effort"] and effort is not None:
        detail += f" Authenticated effort minutes: {effort}."
    if not normalized["keep_cash_savings"] and savings is not None:
        detail += f" Cash savings dollars: {savings}."
    if normalized["exception_rationale"]:
        detail += " Exception rationale recorded."
    if existing:
        detail += f" Replaces {existing['disposition']}."
    _append_event(db, risk_id, "decision_recorded", detail, now, _sandbox_for_risk(db, risk_id))
