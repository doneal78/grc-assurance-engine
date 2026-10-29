"""JSON contract for running vendor intake without the web UI.

A script or agent submits the same fields as the public intake form, or an
intake file the importer already accepts. The assessment document copies the
risk-engine result. It does not calculate a score, approve a vendor, or call
ServiceNow. A trust-center fetch runs only when the form asks for it, and
that page is not verified evidence.

Nothing is written unless the caller sets persist to true and supplies a
human disposition and rationale. That disposition is stored separately from
the residual tier.
"""

import json
import re
from datetime import date

from app.services.intake_builder import IntakeError, build_intake, direction_column_names, run_intake
from app.services.intake_importer import (
    can_import, column_guide, confirmation_document, parse_upload, questionnaire_columns,
)
from app.services.intake_questionnaire import load_questionnaire
from app.services.org_policy import load_org_policy
from app.services.risk_engine import load_rules
from app.services.workflow_service import (
    AUTHENTICATED_EFFORT_GATE, CASH_SAVINGS_GATE, DISPOSITION_RULE, DISPOSITIONS,
    WorkflowInputError, decision_problems, get_risk, parse_authenticated_effort_minutes,
    parse_cash_savings_dollars, parse_handling_minutes, parse_handoffs, parse_manual_touches,
    parse_rework_minutes, register_intake,
)

CONTRACT_VERSION = "1.0.0"
CONTRACT_ASSESSMENT = "grc.intake.assessment"
CONTRACT_BATCH = "grc.intake.assessment_batch"
CONTRACT_PREVIEW = "grc.intake.import_preview"
CONTRACT_ERROR = "grc.intake.error"
CONTRACT_DESCRIPTION = "grc.intake.contract"

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REQUEST_KEYS = {"form", "as_of", "contract_version", "persist", "decision"}
_DECISION_KEYS = {
    "disposition", "rationale", "decider", "conditions", "exception_rationale",
    "handling_minutes", "rework_minutes", "manual_touches", "handoffs",
    "authenticated_effort_minutes", "cash_savings_dollars",
}

LIMITATIONS = (
    "Portfolio demo. Not a production GRC API and not a certification.",
    "The risk model is an illustrative portfolio model. Identical inputs and the same rule-set version produce the same result.",
    "A residual tier does not approve the vendor. Human review is required, and a configured restriction can block automatic approval.",
    "An assessment is not written to the risk register unless persist is true and a person supplies a disposition, rationale, and decider. The residual tier is not that disposition.",
    "handling_minutes on a decision is optional and self-reported. It is not a timer, not authenticated effort, not elapsed cycle time, and not an input to the cost model.",
    "rework_minutes on a decision is optional and self-reported. It is time spent redoing work after a first pass. It is not handling minutes, not a timer, not authenticated effort, not elapsed cycle time, and not an input to the cost model.",
    "manual_touches on a decision is optional and self-reported. It is a count of human touchpoints on that assessment. It is not handling minutes, not rework minutes, not a timer, not authenticated effort, not elapsed cycle time, and not an input to the cost model.",
    "handoffs on a decision is optional and self-reported. It is a count of times the assessment was handed between people or queues before disposition. It is not handling minutes, not rework minutes, not manual touches, not a timer, not authenticated effort, not elapsed cycle time, and not an input to the cost model.",
    "authenticated_effort_minutes on a decision is optional minutes a signed-in reviewer entered. The HTTP API stores a number only when the request passed the demo password gate. The CLI has no signed-in session and does not store it. Omit, null, or blank leaves it unmeasured. It is not a session timer, not handling minutes, not rework minutes, not manual touches, not handoffs, not elapsed cycle time, not cash savings, and not an input to the cost model.",
    "cash_savings_dollars on a decision is optional whole dollars a signed-in reviewer entered when a spending reduction was known. The HTTP API stores a number only when the request passed the demo password gate. The CLI has no signed-in session and does not store it. Omit, null, or blank leaves it unmeasured. Zero is a reported zero. The application does not multiply minutes or counts by a wage. It is not handling minutes, not rework minutes, not manual touches, not handoffs, not authenticated effort, not elapsed cycle time, and not an input to the cost model.",
    "incident_cost, avoided_incident_count, and avoided_incident_value are not decision fields. A request that includes them is rejected and nothing is saved. Avoided-incident value is a modeled assumption in the versioned cost file. The shipped file leaves both inputs null, so the figure is Not measured. It is not cash savings and it is not an input to the cost formula.",
    "A trust-center URL is stored as pasted text unless fetch_trust_center is yes. A fetch is one HTTP GET of vendor-published material for human review. It is not verified evidence and it does not approve the vendor. File import does not fetch.",
    "A ServiceNow-shaped file is simulated input. This contract does not call ServiceNow.",
    "No external AI model scores or approves the vendor.",
    "vendor_direction, residual_direction, and direction_note are optional intake context for a person. They are not scored. They do not change inherent risk, residual risk, evidence confidence, escalations, the policy outcome, dispositions, or control mappings.",
)


class BotRequestError(ValueError):
    """Raised when a bot request or intake file fails validation."""

    def __init__(self, problems, preview=None):
        self.problems = list(problems)
        self.preview = preview
        super().__init__("; ".join(self.problems) if self.problems else "Request rejected.")


class _DuplicateKey(Exception):
    def __init__(self, key):
        self.key = key


def error_document(kind, problems):
    """A JSON error that carries no assessment and records nothing."""
    return {
        "contract": CONTRACT_ERROR,
        "contract_version": CONTRACT_VERSION,
        "error": kind,
        "persisted": False,
        "assessed": False,
        "problems": list(problems),
    }


def contract_document():
    """Field list and routes, read from the live questionnaire and rule set."""
    questionnaire = load_questionnaire()
    policy = load_org_policy()
    rules = load_rules()
    return {
        "contract": CONTRACT_DESCRIPTION,
        "contract_version": CONTRACT_VERSION,
        "persisted": False,
        "illustrative": True,
        "human_review_required": True,
        "automatic_approval": None,
        "rule_set_version": rules["rule_set_version"],
        "rule_set_status": rules["status"],
        "questionnaire_version": questionnaire["questionnaire_version"],
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "policy_status": policy["status"],
        "endpoints": {
            "contract": {"method": "GET", "path": "/api/v1/intake/contract"},
            "assess": {
                "method": "POST",
                "path": "/api/v1/intake/assess",
                "content_type": "application/json",
            },
        },
        "cli": {
            "assess": "python -m app.cli assess REQUEST.json",
            "assess_stdin": "python -m app.cli assess -",
            "persist": (
                "python -m app.cli assess REQUEST.json --persist "
                "--disposition escalate --rationale TEXT --decider TEXT"
            ),
            "preview": "python -m app.cli preview FILE",
            "assess_file": "python -m app.cli assess-file FILE",
            "assess_file_persist": (
                "python -m app.cli assess-file FILE --persist "
                "--disposition escalate --rationale TEXT --decider TEXT"
            ),
        },
        "request": {
            "contract_version": f"Optional. When present, must be {CONTRACT_VERSION}.",
            "as_of": "Optional YYYY-MM-DD. Omitted means the server or process date. Evidence ages are calculated from this date.",
            "form": (
                "Required object. Keys are the intake fields listed below. "
                "fetch_trust_center is optional: omitted or no does not fetch; yes performs one HTTP GET. "
                "Direction context fields are optional and are not scored. Omitting one means not provided."
            ),
            "persist": "Optional boolean. Omitted or false assesses only. True saves a synthetic risk and requires decision.",
            "decision": (
                "Required object when persist is true. disposition is approve, "
                "approve_with_conditions, escalate, or reject. rationale and decider are required. "
                "conditions and exception_rationale follow the saved-risk rules. "
                "handling_minutes is optional. Omit it, null, or a blank string to leave "
                "human handling time unmeasured. A value must be a non-negative whole number "
                "of minutes. Fractions and negative numbers are rejected and are not rewritten. "
                "rework_minutes is optional and separate. Omit it, null, or a blank string to leave "
                "rework time unmeasured. The same whole-number rules apply. It is not handling time. "
                "manual_touches is optional and separate. Omit it, null, or a blank string to leave "
                "the touchpoint count unmeasured. The same whole-number rules apply. It is not "
                "handling time and it is not rework time. "
                "handoffs is optional and separate. Omit it, null, or a blank string to leave "
                "the handoff count unmeasured. The same whole-number rules apply. It is not "
                "handling time, rework time, or a manual-touch count. "
                "authenticated_effort_minutes is optional and separate. Omit it, null, or a "
                "blank string to leave it unmeasured. A number is stored only when this HTTP "
                "request passed the demo password gate. The CLI does not store it. It is not "
                "handling time, rework time, a manual-touch count, or a handoff count. "
                "cash_savings_dollars is optional and separate. Omit it, null, or a blank "
                "string to leave cash savings unmeasured. A number is stored only when this "
                "HTTP request passed the demo password gate. The CLI does not store it. It is "
                "whole dollars the person typed, not a wage times minutes or counts. "
                "incident_cost, avoided_incident_count, and avoided_incident_value "
                "are not decision fields. A request that includes them is rejected. "
                "Avoided-incident value is a modeled assumption. It is not an "
                "observed register figure."
            ),
        },
        "dispositions": list(DISPOSITIONS),
        "fields": column_guide(),
        "direction_context": _direction_contract(questionnaire),
        "optional_form_fields": [
            {
                "field": questionnaire["trust_center"]["fetch_field"],
                "accepted": (
                    "no or yes. Omitted or no stores the URL and does not fetch it. "
                    "yes performs one HTTP GET. The page is not verified evidence. "
                    "File import does not have this column and does not fetch."
                ),
            }
        ],
        "conditional_fields": [
            {
                "field": spec["field"],
                "omit_when": "ai_use is none",
                "reason": "The public form does not submit this field when AI use is none.",
            }
            for spec in questionnaire["context_questions"]
            if spec.get("ask") == "when_ai_use_is_not_none"
        ],
        "exit_codes": {
            "0": "An assessment was produced, or a file preview can be assessed.",
            "2": "The request or file failed validation. No assessment was produced.",
            "1": "The engine raised an unexpected error. No assessment was produced.",
        },
        "limitations": list(LIMITATIONS),
    }


def load_json_object(text):
    """Parse one JSON object. Duplicate keys are rejected."""
    if text is None or not str(text).strip():
        raise BotRequestError(["The request is empty."])
    try:
        payload = json.loads(text, object_pairs_hook=_object_pairs)
    except _DuplicateKey as exc:
        raise BotRequestError([f"Duplicate JSON key {exc.key!r}."]) from exc
    except json.JSONDecodeError as exc:
        raise BotRequestError([f"The request is not valid JSON ({exc.msg})."]) from exc
    return payload


def assess_request_text(text, db=None, *, open_url=None, resolver=None,
                        accept_authenticated_effort=False, accept_cash_savings=False,
                        bind_sandbox=False):
    """Parse a JSON request body and return one assessment document."""
    return assess_request(
        load_json_object(text), db=db, open_url=open_url, resolver=resolver,
        accept_authenticated_effort=accept_authenticated_effort,
        accept_cash_savings=accept_cash_savings,
        bind_sandbox=bind_sandbox,
    )


def assess_request(payload, db=None, *, open_url=None, resolver=None,
                   accept_authenticated_effort=False, accept_cash_savings=False,
                   bind_sandbox=False):
    """Validate one assess request and run it through intake.

    persist defaults to false. A true value writes the synthetic vendor and
    the human decision. A false value never writes, even if a decision object
    was sent by mistake: that combination is rejected so it cannot look saved.
    """
    form, as_of, persist, decision = parse_assess_request(
        payload, accept_authenticated_effort=accept_authenticated_effort,
        accept_cash_savings=accept_cash_savings,
    )
    try:
        intake = build_intake(form, as_of, open_url=open_url, resolver=resolver)
    except IntakeError as exc:
        raise BotRequestError(exc.problems) from exc
    result = run_intake(intake, as_of)
    if not persist:
        return assessment_from_result(result)
    if db is None:
        raise BotRequestError(["persist is true, but no database is available. Nothing was saved."])
    _require_decision(result, decision)
    sandbox_id = None
    if bind_sandbox:
        from app.services.sandbox_http import issue_sandbox
        sandbox_id = issue_sandbox()
    try:
        risk_id = register_intake(db, result, decision, sandbox_id=sandbox_id)
    except WorkflowInputError as exc:
        db.rollback()
        raise BotRequestError([str(exc)]) from exc
    return assessment_from_result(result, saved=get_risk(db, risk_id))


def parse_assess_request(payload, *, accept_authenticated_effort=False,
                         accept_cash_savings=False):
    """Return (form, as_of, persist, decision). Structural problems are raised before scoring."""
    problems = []
    if not isinstance(payload, dict):
        raise BotRequestError(["The request must be a JSON object."])
    if payload.get("kind") == "vendor_intake_package" or "import_kind" in payload or "_demo_note" in payload:
        problems.append(
            "This JSON is not an assess request. Use preview or assess-file for an intake file. "
            "A reviewer package or mock ticket is an export, not an intake."
        )
    unknown = sorted(set(payload) - _REQUEST_KEYS)
    if unknown and "form" in payload:
        problems.append("Unrecognized request fields: " + ", ".join(unknown) + ".")
    if "contract_version" in payload and payload["contract_version"] != CONTRACT_VERSION:
        problems.append(f"contract_version must be {CONTRACT_VERSION}.")

    persist, decision, persist_problems = _parse_persist(
        payload, accept_authenticated_effort=accept_authenticated_effort,
        accept_cash_savings=accept_cash_savings,
    )
    problems.extend(persist_problems)

    form = payload.get("form")
    if "form" not in payload:
        problems.append("The request needs a form object. Intake fields belong inside form.")
        form = None
    elif not isinstance(form, dict):
        problems.append("form must be a JSON object.")
        form = None

    as_of = None
    if "as_of" in payload:
        as_of, date_problem = _parse_date(payload["as_of"])
        if date_problem:
            problems.append(date_problem)
    else:
        as_of = date.today()

    if form is None:
        raise BotRequestError(problems)

    columns = questionnaire_columns()
    optional = [*_optional_form_fields(), *direction_column_names()]
    known = set(columns) | set(optional)
    unexpected = sorted(set(form) - known)
    if unexpected:
        problems.append(
            "Unrecognized form fields: " + ", ".join(unexpected) + ". They were not dropped."
        )
    required = _required_fields(form)
    missing = [column for column in required if column not in form]
    if missing:
        problems.append("Missing form fields: " + ", ".join(missing) + ".")
    cleaned = {}
    for column in [*columns, *optional]:
        if column not in form:
            continue
        value = form[column]
        if not isinstance(value, str):
            problems.append(f"form.{column}: expected text, got {_type_name(value)}.")
            continue
        cleaned[column] = value
    if problems:
        raise BotRequestError(problems)
    return cleaned, as_of, persist, decision


def assessment_from_result(result, saved=None):
    """Copy one run_intake result into the bot assessment document."""
    risk = result["risk"]
    policy = risk["policy"]
    document = {
        "contract": CONTRACT_ASSESSMENT,
        "contract_version": CONTRACT_VERSION,
        "persisted": saved is not None,
        "risk_id": saved["risk_id"] if saved else None,
        "decision": _decision_document(saved["decision"]) if saved else None,
        "synthetic_data": bool(result.get("synthetic_data", True)),
        "human_review_required": True,
        "automatic_approval": None,
        "vendor_name": result.get("name"),
        "as_of": result.get("as_of"),
        "rule_set_version": risk["rule_set_version"],
        "questionnaire_version": result.get("questionnaire_version"),
        "evidence_policy_version": result.get("evidence_policy_version"),
        "org_policy": {
            "policy_id": policy.get("policy_id"),
            "policy_version": policy.get("policy_version"),
            "status": policy.get("status"),
        },
        "residual": {
            "tier": risk["residual"]["tier"],
            "reason": risk["residual"]["reason"],
        },
        "inherent": risk["inherent"],
        "evidence_confidence": risk["evidence_confidence"],
        "escalations": risk["escalations"],
        "missing_information": risk["missing_information"],
        "conflicts": [
            {
                "claim_id": claim.get("claim_id"),
                "topic": claim.get("topic"),
                "evidence_status": claim.get("evidence_status"),
            }
            for claim in risk["conflicts"]
        ],
        "review_path": risk["review_path"],
        "policy_outcome": risk["policy_outcome"],
        "required_contract_clauses": [
            _clause_view(clause) for clause in policy.get("required_contract_clauses") or []
        ],
        "claims": [_claim_view(claim) for claim in result.get("claims") or []],
        "mappings": [_mapping_view(mapping) for mapping in result.get("mappings") or []],
        "direction_context": _direction_view(result.get("direction_context")),
        "trust_center": _trust_view(result.get("trust_center")),
        "limitations": list(LIMITATIONS),
    }
    if result.get("source_row") is not None:
        document["source_row"] = result["source_row"]
        document["ticket_number"] = result.get("ticket_number")
        document["import_format"] = result.get("import_format")
    return document


def preview_file(filename, data, as_of):
    """Parse an intake file. The preview does not include a risk tier."""
    if isinstance(data, str):
        raise BotRequestError(["The intake file must be bytes."])
    preview = parse_upload(filename, data, as_of)
    return preview_document(preview)


def assess_file(filename, data, as_of, decision=None, db=None):
    """Assess every row when the whole file is valid. Otherwise raise with the preview.

    decision is omitted for an assess-only batch. When it is present, every
    row is saved with that same human disposition, or none of them are.
    """
    from app.services.intake_importer import ImportRejected, assess_import

    if isinstance(data, str):
        raise BotRequestError(["The intake file must be bytes."])
    preview = parse_upload(filename, data, as_of)
    if not can_import(preview):
        raise BotRequestError(_preview_problems(preview), preview=preview)
    try:
        results = assess_import(confirmation_document(preview), as_of)
    except ImportRejected as exc:
        raise BotRequestError(_preview_problems(exc.preview), preview=exc.preview) from exc
    saved_rows = _persist_results(results, decision, db)
    assessments = [
        assessment_from_result(result, saved=saved)
        for result, saved in zip(results, saved_rows)
    ]
    return {
        "contract": CONTRACT_BATCH,
        "contract_version": CONTRACT_VERSION,
        "persisted": decision is not None,
        "synthetic_data": True,
        "human_review_required": True,
        "automatic_approval": None,
        "format": preview["format"],
        "filename": preview["filename"],
        "as_of": as_of.isoformat(),
        "count": len(assessments),
        "results": assessments,
        "limitations": list(LIMITATIONS),
    }


def preview_document(preview):
    """A stable preview document. Ticket context is not a score."""
    return {
        "contract": CONTRACT_PREVIEW,
        "contract_version": CONTRACT_VERSION,
        "persisted": False,
        "scored": False,
        "can_assess": can_import(preview),
        "format": preview["format"],
        "filename": preview["filename"],
        "problems": list(preview["problems"]),
        "blank_rows_skipped": preview["blank_rows_skipped"],
        "context_note": (
            "Ticket priority, state, and opened_at are file context. "
            "vendor_direction, residual_direction, and direction_note are intake context. "
            "None of them set the residual tier or the evaluation date. "
            "This preview does not call the risk engine."
        ),
        "rows": [
            {
                "row_number": row["row_number"],
                "vendor_name": row["vendor_name"],
                "ticket_number": row["ticket_number"],
                "ticket_context": row.get("ticket_context") or {},
                "problems": list(row["problems"]),
                "conflicts": list(row["conflicts"]),
                "form": row["form"],
            }
            for row in preview["rows"]
        ],
    }


def parse_cli_date(value):
    """Parse an optional CLI --as-of value. None means today."""
    if value is None:
        return date.today()
    parsed, problem = _parse_date(value)
    if problem:
        raise BotRequestError([problem])
    return parsed


def _parse_persist(payload, *, accept_authenticated_effort=False, accept_cash_savings=False):
    """Return (persist, decision, problems). Missing persist means assess only."""
    problems = []
    if "persist" not in payload:
        if "decision" in payload:
            problems.append("A decision is recorded only when persist is true. Nothing was saved.")
        return False, None, problems
    persist = payload["persist"]
    if not isinstance(persist, bool):
        problems.append("persist must be true or false.")
        return False, None, problems
    if not persist:
        if "decision" in payload:
            problems.append("A decision is recorded only when persist is true. Nothing was saved.")
        return False, None, problems
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        problems.append("persist true requires a decision object with a disposition, rationale, and decider.")
        return True, None, problems
    unknown = sorted(set(decision) - _DECISION_KEYS)
    if unknown:
        problems.append("Unrecognized decision fields: " + ", ".join(unknown) + ".")
    cleaned = {}
    if "handling_minutes" in decision:
        minute_problems, minutes = parse_handling_minutes(decision["handling_minutes"])
        problems.extend(minute_problems)
        cleaned["handling_minutes"] = minutes
    else:
        cleaned["handling_minutes"] = None
    if "rework_minutes" in decision:
        rework_problems, rework = parse_rework_minutes(decision["rework_minutes"])
        problems.extend(rework_problems)
        cleaned["rework_minutes"] = rework
    else:
        cleaned["rework_minutes"] = None
    if "manual_touches" in decision:
        touch_problems, touches = parse_manual_touches(decision["manual_touches"])
        problems.extend(touch_problems)
        cleaned["manual_touches"] = touches
    else:
        cleaned["manual_touches"] = None
    if "handoffs" in decision:
        handoff_problems, handoff_count = parse_handoffs(decision["handoffs"])
        problems.extend(handoff_problems)
        cleaned["handoffs"] = handoff_count
    else:
        cleaned["handoffs"] = None
    if "authenticated_effort_minutes" in decision:
        effort_problems, effort = parse_authenticated_effort_minutes(
            decision["authenticated_effort_minutes"],
        )
        problems.extend(effort_problems)
        if effort is not None and not accept_authenticated_effort:
            problems.append(AUTHENTICATED_EFFORT_GATE + ".")
        cleaned["authenticated_effort_minutes"] = effort
        cleaned["accept_authenticated_effort"] = bool(accept_authenticated_effort)
    else:
        cleaned["authenticated_effort_minutes"] = None
        cleaned["accept_authenticated_effort"] = False
    if "cash_savings_dollars" in decision:
        savings_problems, savings = parse_cash_savings_dollars(
            decision["cash_savings_dollars"],
        )
        problems.extend(savings_problems)
        if savings is not None and not accept_cash_savings:
            problems.append(CASH_SAVINGS_GATE + ".")
        cleaned["cash_savings_dollars"] = savings
        cleaned["accept_cash_savings"] = bool(accept_cash_savings)
    else:
        cleaned["cash_savings_dollars"] = None
        cleaned["accept_cash_savings"] = False
    for key in ("disposition", "rationale", "decider", "conditions", "exception_rationale"):
        if key not in decision:
            if key in {"disposition", "rationale", "decider"}:
                problems.append(f"decision.{key} is required when persist is true.")
            cleaned[key] = ""
            continue
        value = decision[key]
        if not isinstance(value, str):
            problems.append(f"decision.{key}: expected text, got {_type_name(value)}.")
            cleaned[key] = ""
            continue
        cleaned[key] = value
    if isinstance(decision.get("disposition"), str) and decision["disposition"] not in DISPOSITIONS:
        problems.append(DISPOSITION_RULE + ".")
    return True, cleaned, problems


def _require_decision(result, decision):
    """Reject a decision the saved-risk rules would refuse. Does not write."""
    if not isinstance(decision, dict):
        raise BotRequestError(["persist true requires a decision object with a disposition, rationale, and decider."])
    problems, _normalized = decision_problems(
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
        raise BotRequestError(problems)


def _persist_results(results, decision, db):
    """Save every result with one disposition, or leave the register unchanged."""
    if decision is None:
        return [None] * len(results)
    if db is None:
        raise BotRequestError(["persist is true, but no database is available. Nothing was saved."])
    for result in results:
        _require_decision(result, decision)
    risk_ids = []
    try:
        for result in results:
            risk_ids.append(register_intake(db, result, decision, commit=False))
        db.commit()
    except WorkflowInputError as exc:
        db.rollback()
        raise BotRequestError([str(exc)]) from exc
    except Exception:
        db.rollback()
        raise
    return [get_risk(db, risk_id) for risk_id in risk_ids]


def _decision_document(decision):
    """The human disposition, copied from the saved row and kept off the score."""
    return {
        "disposition": decision["disposition"],
        "rationale": decision["rationale"],
        "decider": decision["decider"],
        "conditions": decision["conditions"],
        "exception_rationale": decision["exception_rationale"],
        "policy_id": decision["policy_id"],
        "policy_version": decision["policy_version"],
        "rule_set_version": decision["rule_set_version"],
        "prohibited_at_decision": decision["prohibited_at_decision"],
        "handling_minutes": decision.get("handling_minutes"),
        "rework_minutes": decision.get("rework_minutes"),
        "manual_touches": decision.get("manual_touches"),
        "handoffs": decision.get("handoffs"),
        "authenticated_effort_minutes": decision.get("authenticated_effort_minutes"),
        "cash_savings_dollars": decision.get("cash_savings_dollars"),
        "separate_from_score": True,
    }


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _parse_date(value):
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None, "as_of must be a date in YYYY-MM-DD form."
    try:
        return date.fromisoformat(value), None
    except ValueError:
        return None, "as_of is not a real calendar date."


def _direction_contract(questionnaire):
    """Tell a caller that direction fields are optional and not scored."""
    spec = questionnaire["direction_context"]
    return {
        "scored": False,
        "optional": True,
        "omit_means": "Not provided. The residual tier is unchanged.",
        "label": spec["label"],
        "note": spec["note"],
        "fields": [
            {
                "field": item["field"],
                "prompt": item["prompt"],
                "accepted": "Omitted, blank, or one of: " + ", ".join(key for key in item["options"] if key) + ".",
                "scored": False,
            }
            for item in spec["fields"]
        ] + [{
            "field": spec["note_field"],
            "prompt": spec["note_prompt"],
            "accepted": f"Omitted, blank, or one line of text up to {spec['note_max_length']} characters.",
            "scored": False,
        }],
    }


def _direction_view(stored):
    """Copy direction context onto the assessment document. Do not score it."""
    if not stored:
        return {
            "scored": False,
            "provided": False,
            "label": "Context only. Not scored.",
            "note": "This result has no vendor-direction context. It is not inferred, and it is not scored.",
            "fields": [],
            "direction_note": "",
        }
    return {
        "scored": False,
        "provided": True,
        "label": stored.get("label") or "Context only. Not scored.",
        "note": stored.get("note") or "",
        "fields": [
            {
                "field": item.get("field"),
                "prompt": item.get("prompt"),
                "value": item.get("value") or "",
                "display": item.get("display") or "Not provided",
                "scored": False,
            }
            for item in stored.get("fields") or []
        ],
        "note_prompt": stored.get("note_prompt") or "",
        "direction_note": stored.get("direction_note") or "",
    }


def _optional_form_fields():
    """Form keys the public page can send and a file import does not have."""
    field = load_questionnaire()["trust_center"]["fetch_field"]
    if field in questionnaire_columns():
        return []
    return [field]


def _required_fields(form):
    """Columns the public form submits. Model training is omitted when AI use is none."""
    questionnaire = load_questionnaire()
    optional = {
        spec["field"]
        for spec in questionnaire["context_questions"]
        if spec.get("ask") == "when_ai_use_is_not_none"
    }
    columns = questionnaire_columns()
    if form.get("ai_use") == "none":
        return [column for column in columns if column not in optional]
    return list(columns)


def _preview_problems(preview):
    problems = list(preview["problems"])
    for row in preview["rows"]:
        problems.extend(row["problems"])
        problems.extend(row["conflicts"])
    if not problems:
        problems.append("The file cannot be assessed.")
    return problems


def _type_name(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "an object"
    return type(value).__name__


def _trust_view(trust):
    trust = trust or {}
    fetch = trust.get("fetch") or {}
    return {
        "url": trust.get("url"),
        "fetched": trust.get("fetched", False),
        "collection": trust.get("collection"),
        "fetch": {
            "requested": bool(fetch.get("requested")),
            "outcome": fetch.get("outcome") or "not_requested",
            "http_status": fetch.get("http_status"),
            "fetched_at": fetch.get("fetched_at"),
            "final_url": fetch.get("final_url"),
            "source": fetch.get("source"),
            "summary": fetch.get("summary"),
            "excerpt": fetch.get("excerpt"),
            "error": fetch.get("error"),
            "evidence_status": fetch.get("evidence_status"),
            "status_reason": fetch.get("status_reason"),
            "evidence_id": fetch.get("evidence_id"),
        },
    }


def _claim_view(claim):
    return {
        "claim_id": claim.get("claim_id"),
        "topic": claim.get("topic"),
        "statement": claim.get("statement"),
        "evidence_status": claim.get("evidence_status"),
        "status_reason": claim.get("status_reason"),
        "evidence": [
            {
                "evidence_id": item.get("evidence_id"),
                "status": item.get("status"),
                "reason": item.get("reason"),
            }
            for item in claim.get("evidence") or []
        ],
    }


def _clause_view(clause):
    return {
        "clause_id": clause.get("clause_id"),
        "title": clause.get("title"),
        "text": clause.get("text"),
        "evidence_status": clause.get("evidence_status"),
        "status_reason": clause.get("status_reason"),
    }


def _mapping_view(mapping):
    return {
        "mapping_id": mapping.get("mapping_id"),
        "framework": mapping.get("framework"),
        "framework_version": mapping.get("framework_version"),
        "control_id": mapping.get("control_id"),
        "title": mapping.get("title"),
        "applicability": mapping.get("applicability"),
        "rationale": mapping.get("rationale"),
        "review_status": mapping.get("review_status"),
        "mapping_set_version": mapping.get("mapping_set_version"),
        "related_claims": mapping.get("related_claims") or [],
    }
