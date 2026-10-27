"""Persistence and input validation for the local risk/remediation workflow."""

import json
from datetime import date, datetime, timezone
from uuid import uuid4


class WorkflowInputError(ValueError):
    """Raised when a workflow update contains invalid values."""


ACTION_STATUSES = {"open", "in_progress", "completed"}
DISPOSITIONS = ("approve", "approve_with_conditions", "escalate", "reject")
APPROVAL_DISPOSITIONS = {"approve", "approve_with_conditions"}
DISPOSITION_RULE = "disposition must be approve, approve with conditions, escalate, or reject"
MAX_DECISION_TEXT = 1000
MAX_DECIDER = 100


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dict(row):
    return dict(row) if row is not None else None


def list_risks(db):
    rows = db.execute(
        """SELECT r.*,
           (SELECT COUNT(*) FROM remediation_actions a WHERE a.risk_id = r.risk_id) AS action_count,
           (SELECT COUNT(*) FROM remediation_actions a
            WHERE a.risk_id = r.risk_id AND a.status != 'completed') AS open_action_count,
           (SELECT d.disposition FROM decisions d WHERE d.risk_id = r.risk_id) AS decision_disposition
           FROM risks r ORDER BY r.created_at DESC"""
    ).fetchall()
    return [_dict(row) for row in rows]


def get_risk(db, risk_id):
    row = db.execute("SELECT * FROM risks WHERE risk_id = ?", (risk_id,)).fetchone()
    if row is None:
        return None
    risk = _dict(row)
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


def risk_for_scenario(db, scenario_id):
    row = db.execute("SELECT risk_id FROM risks WHERE scenario_id = ?", (scenario_id,)).fetchone()
    return _dict(row)


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


def register_scenario(db, result):
    """Persist one scenario as a local risk record and create a follow-up action."""
    if not result.get("synthetic_data"):
        raise WorkflowInputError("Only synthetic demonstration scenarios may be saved by this workflow.")
    scenario_id = result.get("scenario_id")
    existing = risk_for_scenario(db, scenario_id)
    if existing:
        return existing["risk_id"]
    risk_id = _persist_assessment(
        db, result, scenario_id, result["summary"],
        "Synthetic scenario result added to the local risk register.",
    )
    db.commit()
    return risk_id


def register_intake(db, result, decision, *, commit=True):
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
    )
    if problems:
        raise WorkflowInputError("; ".join(problems))
    risk_id = _persist_assessment(
        db, result, f"intake-{uuid4().hex[:12]}", _intake_statement(result),
        "Synthetic general intake added to the local risk register. Demonstration data.",
        opening_event=(
            "intake_received",
            "Synthetic general intake confirmed for save. Demonstration data. "
            "The engine score is not a disposition.",
        ),
    )
    _save_decision_row(db, risk_id, normalized, existing=None)
    if commit:
        db.commit()
    return risk_id


def _persist_assessment(db, result, scenario_id, statement, created_detail, opening_event=None):
    """Insert the risk, its follow-up action, and the creation events. Does not commit."""
    risk_id = f"R-{uuid4().hex[:8].upper()}"
    risk = result["risk"]
    now = _now()
    policy = risk.get("policy") or {}
    policy_outcome = (risk.get("policy_outcome") or {}).get("status")
    db.execute(
        """INSERT INTO risks
        (risk_id, scenario_id, scenario_name, risk_statement, inherent_tier, residual_tier,
         rationale_json, created_at, policy_id, policy_version, policy_outcome)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (risk_id, scenario_id, result["name"], statement, risk["inherent"]["tier"],
         risk["residual"]["tier"], json.dumps(_stored_rationale(result)), now,
         policy.get("policy_id"), policy.get("policy_version"), policy_outcome),
    )
    if opening_event:
        db.execute(
            "INSERT INTO workflow_events (risk_id, event_type, detail, occurred_at) VALUES (?, ?, ?, ?)",
            (risk_id, opening_event[0], opening_event[1], now),
        )
    db.execute(
        "INSERT INTO workflow_events (risk_id, event_type, detail, occurred_at) VALUES (?, ?, ?, ?)",
        (risk_id, "risk_created", created_detail, now),
    )

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
        db.execute(
            "INSERT INTO workflow_events (risk_id, event_type, detail, occurred_at) VALUES (?, ?, ?, ?)",
            (risk_id, "remediation_created", description, now),
        )
    return risk_id


def update_action(db, action_id, status, owner, due_date, completion_notes):
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

    row = db.execute("SELECT risk_id FROM remediation_actions WHERE action_id = ?", (action_id,)).fetchone()
    if row is None:
        return None
    risk_id = row["risk_id"]
    now = _now()
    db.execute(
        """UPDATE remediation_actions SET status = ?, owner = ?, due_date = ?,
           completion_notes = ?, updated_at = ? WHERE action_id = ?""",
        (status, owner.strip(), due_date or None, completion_notes.strip(), now, action_id),
    )
    db.execute(
        "INSERT INTO workflow_events (risk_id, event_type, detail, occurred_at) VALUES (?, ?, ?, ?)",
        (risk_id, "remediation_updated", f"Action {action_id} status changed to {status}.", now),
    )
    db.commit()
    return risk_id


def _required_text(value, label, limit):
    if not isinstance(value, str):
        return None, f"{label} must contain 1 to {limit} characters"
    text = value.strip()
    if not text or len(text) > limit:
        return None, f"{label} must contain 1 to {limit} characters"
    return text, None


def decision_problems(evaluation, disposition, rationale, decider, conditions="", exception_rationale=""):
    """Validate a human disposition against one engine result.

    Returns (problems, normalized). An empty problem list means normalized is
    ready to store. The residual tier is not an input. Escalate is a human
    choice to send the case on. It is not an approval, so a prohibited result
    does not require an exception rationale for it.
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
    }


def record_decision(db, risk_id, disposition, rationale, decider, conditions="", exception_rationale=""):
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
    """
    risk = get_risk(db, risk_id)
    if risk is None:
        return None
    stored = risk["rationale"].get("risk", {})
    problems, normalized = decision_problems(
        stored, disposition, rationale, decider, conditions, exception_rationale,
    )
    if problems:
        raise WorkflowInputError("; ".join(problems))
    _save_decision_row(db, risk_id, normalized, existing=risk["decision"])
    db.commit()
    return risk_id


def _save_decision_row(db, risk_id, normalized, existing):
    """Write one decision row and its workflow event. Does not commit."""
    now = _now()
    values = (
        normalized["disposition"], normalized["conditions"], normalized["rationale"],
        normalized["exception_rationale"], normalized["decider"], normalized["policy_id"],
        normalized["policy_version"], normalized["rule_set_version"],
        normalized["prohibited_at_decision"], now, risk_id,
    )
    if existing:
        db.execute(
            """UPDATE decisions SET disposition = ?, conditions = ?, rationale = ?,
               exception_rationale = ?, decider = ?, policy_id = ?, policy_version = ?,
               rule_set_version = ?, prohibited_at_decision = ?, decided_at = ?
               WHERE risk_id = ?""",
            values,
        )
    else:
        db.execute(
            """INSERT INTO decisions
            (disposition, conditions, rationale, exception_rationale, decider, policy_id,
             policy_version, rule_set_version, prohibited_at_decision, decided_at, risk_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
    detail = (f"{normalized['disposition']} by {normalized['decider']}. "
              f"Policy {normalized['policy_id']} {normalized['policy_version']}. "
              f"Rule set {normalized['rule_set_version']}. "
              f"Policy outcome {normalized['prohibited_at_decision']}.")
    if normalized["exception_rationale"]:
        detail += " Exception rationale recorded."
    if existing:
        detail += f" Replaces {existing['disposition']}."
    db.execute(
        "INSERT INTO workflow_events (risk_id, event_type, detail, occurred_at) VALUES (?, ?, ?, ?)",
        (risk_id, "decision_recorded", detail, now),
    )
