"""Reviewer-authored findings on a saved assessment.

A finding is a note a person writes on one saved risk. It is not an engine
escalation. It does not change the inherent score, the residual tier,
evidence confidence, or the policy outcome. The risk engine does not read
this table.

The row is stored in the caller's browser sandbox. Another sandbox cannot
read or change it. The assessment it is written on must already be visible
to that caller. Creating one does not save an assessment. The public try
and import confirm paths do not call this module.

Linked mappings are ids from the versioned mapping set. Review status is
read from that set when the finding is shown. This module does not promote
a draft entry to reviewed. A missing library entry is shown as unverified
and is not given an invented title.

Observed metrics stay on definition 9. This module does not call
``calculate_cost()``.
"""

from flask import current_app, has_request_context

from app.services.control_mapper import list_library
from app.services.sandbox import DEFAULT_MAX_FINDINGS, SANDBOX_ID_RE
from app.services.workflow_service import (
    WorkflowInputError,
    _append_event,
    _now,
    get_risk,
    sandbox_visible,
)


FINDING_ORIGIN = "reviewer"
FINDING_ORIGIN_LABEL = "Reviewer-authored"
FINDING_SEVERITIES = ("low", "medium", "high", "critical")
FINDING_STATUSES = ("open", "closed")
MAX_FINDING_TITLE = 120
MAX_FINDING_DESCRIPTION = 2000
MAX_FINDING_OWNER = 100
MAX_FINDING_VENDOR = 80
MAX_FINDING_NOTE = 1000
MAX_FINDING_MAPPINGS = 20
SCORE_EFFECT = "none"
SCORE_EFFECT_NOTE = (
    "Reviewer-authored. This finding does not change the inherent score, "
    "the residual tier, evidence confidence, or the policy outcome."
)

SIGNED_IN_FINDING_FIELDS = (
    "authenticated_effort_minutes",
    "cash_savings_dollars",
)
AVOIDED_INCIDENT_FINDING_FIELDS = (
    "incident_cost",
    "avoided_incident_count",
    "avoided_incident_value",
)


def crafted_finding_metric_problem(source):
    """Reject signed-in disposition figures and avoided-incident inputs.

    A missing key and a blank string are not a crafted value. Any other
    value is rejected. A finding does not store those figures, including
    when the demo password gate is on.
    """
    if not hasattr(source, "get"):
        return None
    signed_in = _posted_names(source, SIGNED_IN_FINDING_FIELDS)
    avoided = _posted_names(source, AVOIDED_INCIDENT_FINDING_FIELDS)
    problems = []
    if signed_in:
        listed = ", ".join(signed_in)
        problems.append(
            f"{listed} cannot be saved on a finding. Authenticated effort and "
            "cash savings are recorded only for a signed-in reviewer on a "
            "disposition. A finding does not store them."
        )
    if avoided:
        listed = ", ".join(avoided)
        problems.append(
            f"{listed} cannot be saved on a finding. Avoided-incident value is "
            "a modeled assumption in the versioned cost file. It is not an "
            "observed register figure and it is not a finding field."
        )
    if not problems:
        return None
    return " ".join(problems)


def _posted_names(source, names):
    posted = []
    for name in names:
        if isinstance(source, dict) and name not in source:
            continue
        value = source.get(name)
        if value is None or value == "":
            continue
        posted.append(name)
    return posted


def findings_for_risk(db, risk_id, sandbox_id):
    """Return reviewer-authored findings on one risk that this caller may see."""
    present = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'findings'"
    ).fetchone()
    if present is None:
        return []
    if sandbox_id is None:
        rows = db.execute(
            """SELECT * FROM findings
               WHERE risk_id = ? AND sandbox_id IS NULL
               ORDER BY finding_id""",
            (risk_id,),
        ).fetchall()
    elif _unscoped(sandbox_id):
        rows = db.execute(
            "SELECT * FROM findings WHERE risk_id = ? ORDER BY finding_id",
            (risk_id,),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT * FROM findings
               WHERE risk_id = ? AND (sandbox_id IS NULL OR sandbox_id = ?)
               ORDER BY finding_id""",
            (risk_id, sandbox_id),
        ).fetchall()
    return [_view(db, row) for row in rows]


def parse_new_finding(title, description, severity, owner, vendor_name, mapping_ids,
                      status="open", closing_note=""):
    """Validate a new finding. A new finding is open and has no closing note."""
    problems, normalized = _parse(
        title, description, severity, owner, vendor_name, mapping_ids, status, closing_note,
    )
    if status not in (None, "", "open"):
        problems.append("A new finding is open. Close it after it is saved.")
    if isinstance(closing_note, str) and closing_note.strip():
        problems.append("A closing note is recorded when the finding is closed.")
    if problems:
        return problems, None
    if normalized is not None:
        normalized["status"] = "open"
        normalized["closing_note"] = ""
    return problems, normalized


def parse_finding_update(title, description, severity, owner, vendor_name, mapping_ids,
                         status, closing_note):
    """Validate an edit or a close. Closing requires a closing note."""
    return _parse(
        title, description, severity, owner, vendor_name, mapping_ids, status, closing_note,
    )


def create_finding(db, risk_id, fields, *, sandbox_id):
    """Insert one reviewer-authored finding and a ``finding_created`` event.

    Returns the new id, or ``None`` when the assessment is not visible in
    this sandbox. Does not change the risk score. Commits on success.
    """
    _require_sandbox(sandbox_id)
    if get_risk(db, risk_id, sandbox_id=sandbox_id) is None:
        return None
    _enforce_findings_cap(db, sandbox_id)
    now = _now()
    cursor = db.execute(
        """INSERT INTO findings
           (risk_id, sandbox_id, title, description, severity, vendor_name, owner,
            status, closing_note, origin, created_at, updated_at, closed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'open', '', ?, ?, ?, NULL)""",
        (risk_id, sandbox_id, fields["title"], fields["description"], fields["severity"],
         fields["vendor_name"], fields["owner"], FINDING_ORIGIN, now, now),
    )
    finding_id = cursor.lastrowid
    _replace_mappings(db, finding_id, fields["mapping_ids"])
    _append_event(
        db, risk_id, "finding_created",
        _event_detail("created", finding_id, fields),
        now, sandbox_id,
    )
    db.commit()
    return finding_id


def update_finding(db, risk_id, finding_id, fields, *, sandbox_id):
    """Edit one finding, or close it, and append one workflow event.

    Returns the risk id, or ``None`` when the finding is not visible.
    Closing an open finding writes ``finding_closed``. Any other save writes
    ``finding_updated``. Commits on success. Does not change the risk score.
    """
    row = db.execute(
        "SELECT * FROM findings WHERE finding_id = ?",
        (finding_id,),
    ).fetchone()
    if row is None or row["risk_id"] != risk_id:
        return None
    if not sandbox_visible(row["sandbox_id"], sandbox_id):
        return None
    if get_risk(db, risk_id, sandbox_id=sandbox_id) is None:
        return None
    closing = fields["status"] == "closed" and row["status"] != "closed"
    closed_at = row["closed_at"]
    now = _now()
    if fields["status"] == "closed":
        if closing or not closed_at:
            closed_at = now
    else:
        closed_at = None
    db.execute(
        """UPDATE findings
           SET title = ?, description = ?, severity = ?, vendor_name = ?, owner = ?,
               status = ?, closing_note = ?, updated_at = ?, closed_at = ?
           WHERE finding_id = ?""",
        (fields["title"], fields["description"], fields["severity"], fields["vendor_name"],
         fields["owner"], fields["status"], fields["closing_note"], now, closed_at, finding_id),
    )
    _replace_mappings(db, finding_id, fields["mapping_ids"])
    event_type = "finding_closed" if closing else "finding_updated"
    verb = "closed" if closing else "updated"
    _append_event(
        db, risk_id, event_type,
        _event_detail(verb, finding_id, fields),
        now, row["sandbox_id"],
    )
    db.commit()
    return risk_id


def _unscoped(sandbox_id):
    from app.services.sandbox import UNSCOPED
    return sandbox_id is UNSCOPED


def _require_sandbox(sandbox_id):
    if not isinstance(sandbox_id, str) or SANDBOX_ID_RE.fullmatch(sandbox_id) is None:
        raise WorkflowInputError("A finding is saved in the caller's sandbox.")


def _enforce_findings_cap(db, sandbox_id):
    """Reject a new finding when this browser sandbox is already at its cap.

    The cap counts reviewer-authored findings in that sandbox, including
    findings written on a shared assessment. It is a size limit, not a
    security boundary. Edit and close do not consume another slot.
    """
    maximum = DEFAULT_MAX_FINDINGS
    if has_request_context():
        configured = current_app.config.get("SANDBOX_MAX_FINDINGS", DEFAULT_MAX_FINDINGS)
        if isinstance(configured, int) and configured >= 1:
            maximum = configured
    count = db.execute(
        "SELECT COUNT(*) AS n FROM findings WHERE sandbox_id = ?",
        (sandbox_id,),
    ).fetchone()["n"]
    if count >= maximum:
        raise WorkflowInputError(
            f"This browser sandbox already holds the maximum of {maximum} reviewer-authored findings. "
            "Nothing new was saved."
        )


def _parse(title, description, severity, owner, vendor_name, mapping_ids, status, closing_note):
    problems = []
    title_text, title_problem = _text(
        title, "title", MAX_FINDING_TITLE, required=True, allow_newlines=False,
    )
    if title_problem:
        problems.append(title_problem)
    description_text, description_problem = _text(
        description, "description", MAX_FINDING_DESCRIPTION, required=True, allow_newlines=True,
    )
    if description_problem:
        problems.append(description_problem)
    if severity not in FINDING_SEVERITIES:
        problems.append("severity must be low, medium, high, or critical")
    owner_text, owner_problem = _text(
        owner, "owner", MAX_FINDING_OWNER, required=True, allow_newlines=False,
    )
    if owner_problem:
        problems.append(owner_problem)
    vendor_text, vendor_problem = _text(
        vendor_name, "linked vendor", MAX_FINDING_VENDOR, required=False, allow_newlines=False,
    )
    if vendor_problem:
        problems.append(vendor_problem)
    if status not in FINDING_STATUSES:
        problems.append("status must be open or closed")
    note_text, note_problem = _text(
        closing_note, "closing note", MAX_FINDING_NOTE, required=False, allow_newlines=True,
    )
    if note_problem:
        problems.append(note_problem)
    elif status == "closed" and not note_text:
        problems.append("a closing note is required to close a finding")
    elif status == "open" and note_text:
        problems.append("a closing note is stored only when the finding is closed")
    mapping_list, mapping_problem = _mapping_ids(mapping_ids)
    if mapping_problem:
        problems.append(mapping_problem)
    if problems:
        return problems, None
    return [], {
        "title": title_text,
        "description": description_text,
        "severity": severity,
        "owner": owner_text,
        "vendor_name": vendor_text,
        "status": status,
        "closing_note": note_text,
        "mapping_ids": mapping_list,
        "origin": FINDING_ORIGIN,
    }


def _text(value, label, limit, *, required, allow_newlines):
    if value is None:
        value = ""
    if not isinstance(value, str):
        if required:
            return "", f"{label} must contain 1 to {limit} characters"
        return "", f"{label} must be {limit} characters or fewer"
    text = value.strip()
    if required and not text:
        return "", f"{label} must contain 1 to {limit} characters"
    if len(text) > limit:
        if required:
            return "", f"{label} must contain 1 to {limit} characters"
        return "", f"{label} must be {limit} characters or fewer"
    if _unsupported(text, allow_newlines=allow_newlines):
        return "", f"{label} contains unsupported characters"
    return text, None


def _unsupported(text, *, allow_newlines):
    for char in text:
        if allow_newlines and char in "\n\t":
            continue
        if not char.isprintable():
            return True
    return False


def _mapping_ids(mapping_ids):
    if isinstance(mapping_ids, str):
        mapping_ids = [mapping_ids]
    if not isinstance(mapping_ids, (list, tuple)):
        return [], "at least one control mapping is required"
    cleaned = []
    seen = set()
    for item in mapping_ids:
        if not isinstance(item, str):
            return [], "control mapping ids must be chosen from the mapping set"
        mapping_id = item.strip()
        if not mapping_id or mapping_id in seen:
            continue
        seen.add(mapping_id)
        cleaned.append(mapping_id)
    if not cleaned:
        return [], "at least one control mapping is required"
    if len(cleaned) > MAX_FINDING_MAPPINGS:
        return [], f"a finding can link at most {MAX_FINDING_MAPPINGS} control mappings"
    index, _version = _library_index()
    unknown = [mapping_id for mapping_id in cleaned if mapping_id not in index]
    if unknown:
        listed = ", ".join(unknown)
        return [], f"control mapping ids must exist in the mapping set: {listed}"
    return cleaned, None


def _library_index():
    library = list_library()
    return {mapping["mapping_id"]: mapping for mapping in library["mappings"]}, library["mapping_set_version"]


def _replace_mappings(db, finding_id, mapping_ids):
    db.execute("DELETE FROM finding_mappings WHERE finding_id = ?", (finding_id,))
    for mapping_id in mapping_ids:
        db.execute(
            "INSERT INTO finding_mappings (finding_id, mapping_id) VALUES (?, ?)",
            (finding_id, mapping_id),
        )


def _event_detail(verb, finding_id, fields):
    vendor = fields["vendor_name"] or "not linked"
    note = ""
    if verb == "closed":
        note = " Closing note recorded."
    return (
        f"Reviewer-authored finding {finding_id} {verb}. "
        f"Title: {fields['title']}. Severity {fields['severity']}. "
        f"Status {fields['status']}. Linked vendor: {vendor}. "
        f"Mappings: {', '.join(fields['mapping_ids'])}.{note}"
    )


def _view(db, row):
    index, version = _library_index()
    mapping_rows = db.execute(
        """SELECT mapping_id FROM finding_mappings
           WHERE finding_id = ? ORDER BY mapping_id""",
        (row["finding_id"],),
    ).fetchall()
    mapping_ids = [item["mapping_id"] for item in mapping_rows]
    mappings = [_mapping_view(mapping_id, index, version) for mapping_id in mapping_ids]
    vendor = row["vendor_name"]
    return {
        "finding_id": row["finding_id"],
        "risk_id": row["risk_id"],
        "title": row["title"],
        "description": row["description"],
        "severity": row["severity"],
        "vendor_name": vendor,
        "linked_vendor": vendor or None,
        "linked_risk_id": row["risk_id"],
        "owner": row["owner"],
        "status": row["status"],
        "closing_note": row["closing_note"],
        "origin": row["origin"],
        "origin_label": FINDING_ORIGIN_LABEL,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "closed_at": row["closed_at"],
        "mapping_ids": mapping_ids,
        "mappings": mappings,
        "score_effect": SCORE_EFFECT,
        "score_effect_note": SCORE_EFFECT_NOTE,
    }


def _mapping_view(mapping_id, index, version):
    mapping = index.get(mapping_id)
    if mapping is None:
        return {
            "mapping_id": mapping_id,
            "framework": None,
            "framework_version": None,
            "control_id": None,
            "title": None,
            "review_status": "unverified",
            "mapping_set_version": version,
            "missing_from_library": True,
        }
    return {
        "mapping_id": mapping_id,
        "framework": mapping["framework"],
        "framework_version": mapping["framework_version"],
        "control_id": mapping["control_id"],
        "title": mapping["title"],
        "review_status": mapping["review_status"],
        "mapping_set_version": version,
        "missing_from_library": False,
    }
