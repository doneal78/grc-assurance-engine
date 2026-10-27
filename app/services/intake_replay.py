"""Copy an assessment back onto the public intake form.

The form is the same questionnaire the visitor already used. Filling it in
does not rescore by itself. Running the assessment still calls the intake
builder and the risk engine. A ready-made scenario's evidence files are not
reproduced byte for byte: each form choice is the closest evidence option for
the status the validator already assigned.
"""

from app.services.intake_builder import (
    CLAUSE_EVIDENCE_OPTIONS,
    EVIDENCE_OPTIONS,
    clause_evidence_field,
    field_choices,
)
from app.services.intake_questionnaire import load_questionnaire
from app.services.org_policy import load_org_policy

STATUS_TO_OPTION = {
    "verified": "independent_verified",
    "self_attested": "vendor_statement",
    "not_reviewed": "not_reviewed",
    "expired": "expired",
    "conflicting": "contradicts",
    "missing": "none",
}

EXACT_NOTE = (
    "The public form opens with these answers selected. Change any of them and run the assessment again. "
    "The new run uses the same rules, is not saved, and is not a disposition. "
    "A low residual tier is not an approval."
)
APPROX_NOTE = (
    "The public form opens with the scoring answers from this result. "
    "Evidence choices are the closest form option for each status, not a copy of a scenario's original files. "
    "Fetch stays at no, so this re-run does not open a trust-center page until you choose fetch again. "
    "Re-running uses the same rules. It does not edit a saved register row. "
    "An unsaved public run is not a disposition. A low residual tier is not an approval."
)
UNAVAILABLE_NOTE = (
    "This record has no intake answers to copy. Open the public form to enter them. "
    "A run there is not saved unless you later choose to save it, and it is not a disposition."
)


def intake_field_names():
    """Field names the public form posts. Unknown query keys are ignored."""
    questionnaire = load_questionnaire()
    policy = load_org_policy()
    trust = questionnaire["trust_center"]
    names = [
        "vendor_name",
        trust["url_field"],
        trust["fetch_field"],
        questionnaire["access_evidence"]["field"],
    ]
    names.extend(spec["field"] for spec in questionnaire["context_questions"])
    names.extend(spec["field"] for spec in policy["intake_fields"])
    names.extend(pointer["field"] for pointer in trust["pointers"])
    names.extend(
        clause_evidence_field(clause["clause_id"]) for clause in policy["required_contract_clauses"]
    )
    return names


def accept_field(key, value):
    """Return a form-safe value, or None when the value is not one this form can post."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    questionnaire = load_questionnaire()
    trust = questionnaire["trust_center"]
    if key == "vendor_name":
        if value and len(value) <= 80 and value.isprintable() and "\n" not in value and "\r" not in value:
            return value
        return None
    if key == trust["url_field"]:
        if value == "":
            return ""
        if (
            len(value) <= trust["url_max_length"]
            and value.startswith(("http://", "https://"))
            and " " not in value
            and value.isprintable()
        ):
            return value
        return None
    if key == trust["fetch_field"]:
        return value if value in trust["fetch_options"] else None
    choices = field_choices()
    if key in choices:
        return value if value in choices[key] else None
    access = questionnaire["access_evidence"]["field"]
    pointer_fields = {pointer["field"] for pointer in trust["pointers"]}
    if key == access:
        return value if value in EVIDENCE_OPTIONS else None
    if key in pointer_fields:
        return value if value in trust["evidence_options"] else None
    clause_fields = {
        clause_evidence_field(clause["clause_id"]) for clause in load_org_policy()["required_contract_clauses"]
    }
    if key in clause_fields:
        return value if value in CLAUSE_EVIDENCE_OPTIONS else None
    return None


def _accepted_posted(posted_form):
    fields = {}
    for key in intake_field_names():
        if key not in posted_form:
            continue
        accepted = accept_field(key, posted_form.get(key, ""))
        if accepted is not None:
            fields[key] = accepted
    return fields


def _vendor_name(source):
    for key in ("vendor_name", "name"):
        value = source.get(key)
        accepted = accept_field("vendor_name", value if isinstance(value, str) else "")
        if accepted:
            return accepted
    return ""


def _topic_status(claims, topic):
    matches = [claim for claim in claims if isinstance(claim, dict) and claim.get("topic") == topic]
    if not matches:
        return "missing"
    statuses = {claim.get("evidence_status") for claim in matches}
    if len(statuses) != 1:
        return None
    return statuses.pop()


def _option_for_status(status):
    if status is None:
        return None
    return STATUS_TO_OPTION.get(status)


def _evidence_fields(source, limits):
    """Map validator statuses onto the form's evidence choices. Never invent verified."""
    questionnaire = load_questionnaire()
    claims = source.get("claims") or []
    fields = {}
    access = questionnaire["access_evidence"]
    access_status = _topic_status(claims, access["topic"])
    access_option = _option_for_status(access_status)
    if access_option is None:
        fields[access["field"]] = "none"
        limits.append(
            f"{access['prompt']} is set to nothing provided because that claim does not have one evidence status."
        )
    else:
        fields[access["field"]] = access_option

    for pointer in questionnaire["trust_center"]["pointers"]:
        topics = [topic_spec["topic"] for topic_spec in pointer["topics"]]
        statuses = [_topic_status(claims, topic) for topic in topics]
        options = [_option_for_status(status) for status in statuses]
        if any(option is None for option in options) or len(set(options)) != 1:
            fields[pointer["field"]] = "none"
            limits.append(
                f"{pointer['prompt']} is set to not listed because those claims do not share one evidence status."
            )
        else:
            fields[pointer["field"]] = options[0]
    return fields


def _clause_fields(source, limits):
    fields = {}
    risk = source.get("risk") if isinstance(source.get("risk"), dict) else {}
    policy = risk.get("policy") if isinstance(risk.get("policy"), dict) else {}
    stored = {
        clause.get("clause_id"): clause
        for clause in (policy.get("required_contract_clauses") or [])
        if isinstance(clause, dict)
    }
    for clause in load_org_policy()["required_contract_clauses"]:
        field = clause_evidence_field(clause["clause_id"])
        item = stored.get(clause["clause_id"])
        option = _option_for_status(item.get("evidence_status") if isinstance(item, dict) else None)
        if option is None:
            fields[field] = "none"
            limits.append(
                f"{clause['clause_id']} is set to nothing provided because this result has no single clause status to copy."
            )
        else:
            fields[field] = option
    return fields


def _approximate_fields(source):
    limits = []
    inputs = source.get("assessment_inputs")
    if not isinstance(inputs, dict) or not inputs:
        return {}, limits
    fields = {}
    vendor = _vendor_name(source)
    if vendor:
        fields["vendor_name"] = vendor
    else:
        limits.append("The vendor name was not stored, so type one before running again.")
    for key, value in inputs.items():
        accepted = accept_field(key, value if isinstance(value, str) else "")
        if accepted is None:
            limits.append(f"{key.replace('_', ' ')} was not a form choice on this record, so check that question.")
            continue
        fields[key] = accepted
    fields.update(_evidence_fields(source, limits))
    fields.update(_clause_fields(source, limits))
    trust_spec = load_questionnaire()["trust_center"]
    trust = source.get("trust_center") if isinstance(source.get("trust_center"), dict) else {}
    url = accept_field(trust_spec["url_field"], trust.get("url") if isinstance(trust.get("url"), str) else "")
    if url:
        fields[trust_spec["url_field"]] = url
    fields[trust_spec["fetch_field"]] = "no"
    return fields, limits


def replay_plan(source=None, posted_form=None):
    """Describe how to reopen the public form for this result.

    ``kind`` is ``exact`` for a form that was just posted, ``approximate`` when
    answers are copied from an assessment, and ``unavailable`` when nothing
    was stored to copy.
    """
    source = source if isinstance(source, dict) else {}
    if isinstance(posted_form, dict) and posted_form:
        fields = _accepted_posted(posted_form)
        if fields:
            note = EXACT_NOTE
            if fields.get("fetch_trust_center") == "yes":
                note += (
                    " Fetch is still yes, so running again opens the trust-center URL. "
                    "Set fetch to no if you do not want that."
                )
            return {"fields": fields, "kind": "exact", "limits": [], "note": note}
    fields, limits = _approximate_fields(source)
    if fields:
        note = APPROX_NOTE
        if limits:
            note = note + " " + " ".join(limits)
        return {"fields": fields, "kind": "approximate", "limits": limits, "note": note}
    return {"fields": {}, "kind": "unavailable", "limits": [], "note": UNAVAILABLE_NOTE}


def query_form(args):
    """Copy allowlisted query values onto the public form. Ignore every other key."""
    fields = {}
    for key in intake_field_names():
        if key not in args:
            continue
        accepted = accept_field(key, args.get(key))
        if accepted is not None:
            fields[key] = accepted
    note = ""
    if fields:
        note = (
            "These answers were copied from a result link. Check them, especially the evidence choices, "
            "then run the assessment again. This run is not saved. It is not a disposition. "
            "A low residual tier is not an approval."
        )
    return fields, note
