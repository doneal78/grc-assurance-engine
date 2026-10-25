"""JSON contract for running vendor intake without the web UI.

A script or agent submits the same fields as the public intake form, or an
intake file the importer already accepts. The assessment document copies the
risk-engine result. It does not calculate a score, approve a vendor, fetch a
trust center, call ServiceNow, or write to the risk register.
"""

import json
import re
from datetime import date

from app.services.intake_builder import IntakeError, build_intake, run_intake
from app.services.intake_importer import (
    can_import, column_guide, confirmation_document, parse_upload, questionnaire_columns,
)
from app.services.intake_questionnaire import load_questionnaire
from app.services.org_policy import load_org_policy
from app.services.risk_engine import load_rules

CONTRACT_VERSION = "1.0.0"
CONTRACT_ASSESSMENT = "grc.intake.assessment"
CONTRACT_BATCH = "grc.intake.assessment_batch"
CONTRACT_PREVIEW = "grc.intake.import_preview"
CONTRACT_ERROR = "grc.intake.error"
CONTRACT_DESCRIPTION = "grc.intake.contract"

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REQUEST_KEYS = {"form", "as_of", "contract_version"}

LIMITATIONS = (
    "Portfolio demo. Not a production GRC API and not a certification.",
    "The risk model is an illustrative portfolio model. Identical inputs and the same rule-set version produce the same result.",
    "A residual tier does not approve the vendor. Human review is required, and a configured restriction can block automatic approval.",
    "Nothing from this contract is written to the risk register.",
    "A trust-center URL is stored only as pasted text and is not fetched.",
    "A ServiceNow-shaped file is simulated input. This contract does not call ServiceNow.",
    "No external AI model scores or approves the vendor.",
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
            "preview": "python -m app.cli preview FILE",
            "assess_file": "python -m app.cli assess-file FILE",
        },
        "request": {
            "contract_version": f"Optional. When present, must be {CONTRACT_VERSION}.",
            "as_of": "Optional YYYY-MM-DD. Omitted means the server or process date. Evidence ages are calculated from this date.",
            "form": "Required object. Keys are the intake fields listed below.",
        },
        "fields": column_guide(),
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


def assess_request_text(text):
    """Parse a JSON request body and return one assessment document."""
    if text is None or not str(text).strip():
        raise BotRequestError(["The request is empty."])
    try:
        payload = json.loads(text, object_pairs_hook=_object_pairs)
    except _DuplicateKey as exc:
        raise BotRequestError([f"Duplicate JSON key {exc.key!r}."]) from exc
    except json.JSONDecodeError as exc:
        raise BotRequestError([f"The request is not valid JSON ({exc.msg})."]) from exc
    return assess_request(payload)


def assess_request(payload):
    """Validate one assess request and run it through intake."""
    form, as_of = parse_assess_request(payload)
    try:
        intake = build_intake(form, as_of)
    except IntakeError as exc:
        raise BotRequestError(exc.problems) from exc
    return assessment_from_result(run_intake(intake, as_of))


def parse_assess_request(payload):
    """Return (form, as_of). Structural problems are raised before scoring."""
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
    known = set(columns)
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
    for column in columns:
        if column not in form:
            continue
        value = form[column]
        if not isinstance(value, str):
            problems.append(f"form.{column}: expected text, got {_type_name(value)}.")
            continue
        cleaned[column] = value
    if problems:
        raise BotRequestError(problems)
    return cleaned, as_of


def assessment_from_result(result):
    """Copy one run_intake result into the bot assessment document."""
    risk = result["risk"]
    policy = risk["policy"]
    document = {
        "contract": CONTRACT_ASSESSMENT,
        "contract_version": CONTRACT_VERSION,
        "persisted": False,
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


def assess_file(filename, data, as_of):
    """Assess every row when the whole file is valid. Otherwise raise with the preview."""
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
    assessments = [assessment_from_result(result) for result in results]
    return {
        "contract": CONTRACT_BATCH,
        "contract_version": CONTRACT_VERSION,
        "persisted": False,
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
            "They do not set the residual tier or the evaluation date. "
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
    return {
        "url": trust.get("url"),
        "fetched": trust.get("fetched", False),
        "collection": trust.get("collection"),
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
