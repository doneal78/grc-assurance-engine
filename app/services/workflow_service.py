"""Persistence and input validation for the local risk/remediation workflow."""

import json
from datetime import date, datetime, timezone
from uuid import uuid4


class WorkflowInputError(ValueError):
    """Raised when a workflow update contains invalid values."""


ACTION_STATUSES = {"open", "in_progress", "completed"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dict(row):
    return dict(row) if row is not None else None


def list_risks(db):
    rows = db.execute(
        """SELECT r.*, COUNT(a.action_id) AS action_count,
           SUM(CASE WHEN a.status != 'completed' THEN 1 ELSE 0 END) AS open_action_count
           FROM risks r LEFT JOIN remediation_actions a ON a.risk_id = r.risk_id
           GROUP BY r.risk_id ORDER BY r.created_at DESC"""
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
    return risk


def risk_for_scenario(db, scenario_id):
    row = db.execute("SELECT risk_id FROM risks WHERE scenario_id = ?", (scenario_id,)).fetchone()
    return _dict(row)


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
    db.execute(
        """INSERT INTO risks
        (risk_id, scenario_id, scenario_name, risk_statement, inherent_tier, residual_tier, rationale_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (risk_id, scenario_id, result["name"], statement, risk["inherent"]["tier"],
         risk["residual"]["tier"], json.dumps({"risk": risk, "claims": result["claims"],
         "mappings": result["mappings"], "scenario_set_version": result["scenario_set_version"]}), now),
    )
    db.execute(
        "INSERT INTO workflow_events (risk_id, event_type, detail, occurred_at) VALUES (?, ?, ?, ?)",
        (risk_id, "risk_created", "Synthetic scenario result added to the local risk register.", now),
    )

    statuses = {claim["evidence_status"] for claim in result["claims"]}
    needs_action = bool(risk["escalations"] or statuses & {"missing", "conflicting", "expired", "not_reviewed"})
    if needs_action:
        priority = "critical" if risk["inherent"]["tier"] == "critical" else "high"
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
