"""Persistence and input validation for the local risk/remediation workflow."""

import json
from datetime import date, datetime, timezone
from uuid import uuid4


class WorkflowInputError(ValueError):
    """Raised when a workflow update contains invalid values."""


ACTION_STATUSES = {"open", "in_progress", "completed"}
DISPOSITIONS = ("approve", "approve_with_conditions", "reject")
APPROVAL_DISPOSITIONS = {"approve", "approve_with_conditions"}
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
    """
    return {
        "risk": result["risk"],
        "claims": result["claims"],
        "mappings": result["mappings"],
        "scenario_set_version": result.get("scenario_set_version"),
        "assessment_inputs": result.get("assessment_inputs"),
        "answer_applicability": result.get("answer_applicability") or {},
        "evidence_policy_version": result.get("evidence_policy_version"),
        "as_of": result.get("as_of"),
        "trust_center": result.get("trust_center"),
        "questionnaire_version": result.get("questionnaire_version"),
        "vendor_name": result.get("name"),
        "summary": result.get("summary"),
    }


def register_scenario(db, result):
    """Persist one scenario as a local risk record and create a follow-up action."""
    if not result.get("synthetic_data"):
        raise WorkflowInputError("Only synthetic demonstration scenarios may be saved by this workflow.")
    scenario_id = result.get("scenario_id")
    existing = risk_for_scenario(db, scenario_id)
    if existing:
        return existing["risk_id"]

    risk_id = f"R-{uuid4().hex[:8].upper()}"
    risk = result["risk"]
    now = _now()
    statement = result["summary"]
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
    db.execute(
        "INSERT INTO workflow_events (risk_id, event_type, detail, occurred_at) VALUES (?, ?, ?, ?)",
        (risk_id, "risk_created", "Synthetic scenario result added to the local risk register.", now),
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
    db.commit()
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


def record_decision(db, risk_id, disposition, rationale, decider, conditions="", exception_rationale=""):
    """Record the human disposition for one saved risk.

    A prohibited result can still be approved. The check cites the policy and
    stops an unrecorded override; it does not decide the case. Proceeding,
    with or without conditions, requires an exception rationale. Rejection
    does not. The exception does not clear the prohibited outcome. An
    exception rationale is rejected when the result is not prohibited, or
    when the disposition is reject, so the field means only "proceed despite
    the restriction."

    The policy id, policy version, and rule set version are copied from the
    saved assessment. The caller cannot supply a different reference.
    """
    risk = get_risk(db, risk_id)
    if risk is None:
        return None

    problems = []
    if disposition not in DISPOSITIONS:
        problems.append("disposition must be approve, approve with conditions, or reject")
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

    stored = risk["rationale"].get("risk", {})
    policy = stored.get("policy") or {}
    outcome = stored.get("policy_outcome") or {}
    policy_id = policy.get("policy_id")
    policy_version = policy.get("policy_version")
    rule_set_version = stored.get("rule_set_version")
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
        raise WorkflowInputError("; ".join(problems))

    now = _now()
    existing = risk["decision"]
    values = (disposition, conditions_text, rationale_text, exception_text, decider_text,
              policy_id, policy_version, rule_set_version, outcome_status, now, risk_id)
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
    detail = (f"{disposition} by {decider_text}. Policy {policy_id} {policy_version}. "
              f"Rule set {rule_set_version}. Policy outcome {outcome_status}.")
    if exception_text:
        detail += " Exception rationale recorded."
    if existing:
        detail += f" Replaces {existing['disposition']}."
    db.execute(
        "INSERT INTO workflow_events (risk_id, event_type, detail, occurred_at) VALUES (?, ?, ?, ?)",
        (risk_id, "decision_recorded", detail, now),
    )
    db.commit()
    return risk_id
