"""Load the versioned public intake questionnaire.

The file describes prompts, when a question is asked, and which trust-center
citation becomes which evidence record. Allowed answers still come from the
risk rule set and the org policy. This module does not score or approve.
"""

import json
from pathlib import Path

from app.services.evidence_validator import load_policy
from app.services.org_policy import load_org_policy

DEFAULT_QUESTIONNAIRE_PATH = Path(__file__).resolve().parent.parent / "data" / "intake_questionnaire.json"

EVIDENCE_OPTION_KEYS = (
    "independent_verified",
    "vendor_statement",
    "not_reviewed",
    "expired",
    "contradicts",
    "none",
)
SOURCE_OPTION_KEYS = tuple(key for key in EVIDENCE_OPTION_KEYS if key != "none")
ASK_ALWAYS = "always"
ASK_WHEN_AI = "when_ai_use_is_not_none"


class QuestionnaireError(ValueError):
    """Raised when the questionnaire file cannot be applied as written."""


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_questionnaire(data, choices, policy, evidence_policy):
    """Reject a questionnaire that would drift from the rule set or the evidence policy."""
    if not isinstance(data, dict):
        raise QuestionnaireError("questionnaire must be an object")
    if not _text(data.get("questionnaire_version")):
        raise QuestionnaireError("questionnaire_version is required")
    if not _text(data.get("policy_question_help")):
        raise QuestionnaireError("policy_question_help is required")

    questions = data.get("context_questions")
    if not isinstance(questions, list) or not questions:
        raise QuestionnaireError("context_questions must be a non-empty list")
    seen_fields = set()
    saw_ai_use = False
    for spec in questions:
        if not isinstance(spec, dict):
            raise QuestionnaireError("context question must be an object")
        field = spec.get("field")
        if not _text(field) or field not in choices:
            raise QuestionnaireError(f"{field}: context question must use a rule-set or policy field")
        if field in seen_fields:
            raise QuestionnaireError(f"{field}: duplicate context question")
        seen_fields.add(field)
        if spec.get("ask") not in {ASK_ALWAYS, ASK_WHEN_AI}:
            raise QuestionnaireError(f"{field}: ask must be always or when_ai_use_is_not_none")
        if spec["ask"] == ASK_WHEN_AI and not saw_ai_use:
            raise QuestionnaireError(f"{field}: a conditional question must follow ai_use")
        if spec["ask"] == ASK_WHEN_AI and "no" not in choices[field]:
            raise QuestionnaireError(f"{field}: an omitted conditional answer is stored as no")
        if not _text(spec.get("prompt")) or not _text(spec.get("help")):
            raise QuestionnaireError(f"{field}: prompt and help are required")
        if field == "ai_use":
            if spec["ask"] != ASK_ALWAYS:
                raise QuestionnaireError("ai_use must always be asked")
            saw_ai_use = True
    if not saw_ai_use:
        raise QuestionnaireError("ai_use must be a context question")

    access = data.get("access_evidence")
    if not isinstance(access, dict):
        raise QuestionnaireError("access_evidence is required")
    access_topic = access.get("topic")
    if not _text(access.get("field")) or not _text(access_topic) or not _text(access.get("statement")):
        raise QuestionnaireError("access_evidence needs a field, topic, and statement")
    if not _text(access.get("prompt")) or not _text(access.get("help")):
        raise QuestionnaireError("access_evidence needs a prompt and help")
    if access["field"] in seen_fields:
        raise QuestionnaireError("access evidence field collides with a context question")

    trust = data.get("trust_center")
    if not isinstance(trust, dict):
        raise QuestionnaireError("trust_center is required")
    if not _text(trust.get("url_field")) or not _text(trust.get("prompt")) or not _text(trust.get("help")):
        raise QuestionnaireError("trust_center needs a url field, prompt, and help")
    if not _text(trust.get("note")):
        raise QuestionnaireError("trust_center note is required")
    if not isinstance(trust.get("url_max_length"), int) or trust["url_max_length"] < 1:
        raise QuestionnaireError("trust_center url_max_length must be a positive integer")
    fetch_field = trust.get("fetch_field")
    if not _text(fetch_field) or not _text(trust.get("fetch_prompt")) or not _text(trust.get("fetch_help")):
        raise QuestionnaireError("trust_center needs a fetch field, prompt, and help")
    fetch_options = trust.get("fetch_options")
    if not isinstance(fetch_options, dict) or tuple(fetch_options) != ("no", "yes"):
        raise QuestionnaireError("trust_center fetch_options must be no, then yes")
    if any(not _text(label) for label in fetch_options.values()):
        raise QuestionnaireError("trust_center fetch option labels are required")
    result_notes = trust.get("result_notes")
    if not isinstance(result_notes, dict) or set(result_notes) != {"not_requested", "retrieved", "failed"}:
        raise QuestionnaireError("trust_center result_notes must cover not_requested, retrieved, and failed")
    if any(not _text(text) for text in result_notes.values()):
        raise QuestionnaireError("trust_center result notes are required")
    if fetch_field in {access["field"], trust["url_field"], "vendor_name"} or fetch_field in seen_fields:
        raise QuestionnaireError("trust_center fetch field collides with another intake field")
    options = trust.get("evidence_options")
    if not isinstance(options, dict) or tuple(options) != EVIDENCE_OPTION_KEYS:
        raise QuestionnaireError("trust_center evidence_options must use the evidence option keys, in order")
    if any(not _text(label) for label in options.values()):
        raise QuestionnaireError("trust_center evidence option labels are required")

    known_types = evidence_policy["max_age_days"]
    known_sources = set(evidence_policy["sources"])
    clause_fields = set()
    for clause in policy["required_contract_clauses"]:
        clause_fields.add(f"evidence_clause_{clause['clause_id']}")
    reserved = set(seen_fields) | clause_fields | {access["field"], trust["url_field"], fetch_field, "vendor_name"}
    topics = {access_topic}
    pointer_ids = set()
    for pointer in trust.get("pointers") or []:
        if not isinstance(pointer, dict):
            raise QuestionnaireError("trust-center pointer must be an object")
        pointer_id = pointer.get("pointer_id")
        field = pointer.get("field")
        if not _text(pointer_id) or pointer_id in pointer_ids:
            raise QuestionnaireError(f"{pointer_id}: pointer id must be unique")
        pointer_ids.add(pointer_id)
        if not _text(field) or field in reserved:
            raise QuestionnaireError(f"{pointer_id}: field must be a new form field")
        reserved.add(field)
        if pointer.get("artifact_type") not in known_types:
            raise QuestionnaireError(f"{pointer_id}: artifact_type is not in the evidence policy")
        if not _text(pointer.get("artifact_name")) or not _text(pointer.get("prompt")) or not _text(pointer.get("help")):
            raise QuestionnaireError(f"{pointer_id}: artifact name, prompt, and help are required")
        sources = pointer.get("source_by_option")
        if not isinstance(sources, dict) or set(sources) != set(SOURCE_OPTION_KEYS):
            raise QuestionnaireError(f"{pointer_id}: source_by_option must cover every evidence option except none")
        if any(source not in known_sources for source in sources.values()):
            raise QuestionnaireError(f"{pointer_id}: source is not in the evidence policy")
        pointer_topics = pointer.get("topics")
        if not isinstance(pointer_topics, list) or not pointer_topics:
            raise QuestionnaireError(f"{pointer_id}: at least one claim topic is required")
        for topic_spec in pointer_topics:
            topic = topic_spec.get("topic") if isinstance(topic_spec, dict) else None
            if not _text(topic) or topic in topics or not _text(topic_spec.get("statement")):
                raise QuestionnaireError(f"{pointer_id}: each claim topic must be unique and have a statement")
            topics.add(topic)
    if not pointer_ids:
        raise QuestionnaireError("trust_center needs at least one artifact pointer")


def load_questionnaire(path=DEFAULT_QUESTIONNAIRE_PATH):
    """Load and check the questionnaire against the current rule set and evidence policy."""
    # Imported here so this module can be loaded while intake_builder is loading.
    from app.services.intake_builder import field_choices

    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    validate_questionnaire(data, field_choices(), load_org_policy(), load_policy())
    return data
