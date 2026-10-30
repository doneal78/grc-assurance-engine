"""Plain-language explanations of an assessment result.

The risk engine remains the source of scores, tiers, evidence statuses, and
which rules fired. This module only restates those facts in reviewer language.
It does not rescore, lower a tier, or treat a low residual tier as approval.
"""

from app.services.risk_engine import load_rules

FIELD_LABELS = {
    "data_sensitivity": "Data sensitivity",
    "integration_permissions": "Integration permissions",
    "ai_use": "AI use",
    "model_training_on_customer_data": "Model training on customer data",
    "external_exposure": "External exposure",
    "retention_deletion": "Retention and deletion",
    "decisions_affecting_people": "Decisions affecting people",
}

# What the submitted answer means for the business, before safeguards.
# Point values stay on the factor the engine already computed.
FACTOR_MEANING = {
    "data_sensitivity": {
        "public": "Public data is the lowest sensitivity in this illustrative model.",
        "internal": "Internal data would be in the vendor's hands. That exposure exists before any safeguard is counted.",
        "confidential": "Confidential data would be in the vendor's hands. Treat that as material exposure before looking at evidence.",
        "restricted": "Restricted data would be in the vendor's hands. That is the highest data-sensitivity contribution in this illustrative model.",
    },
    "integration_permissions": {
        "none": "The integration would have no access to organizational systems.",
        "read_only": "The integration could read organizational data and could not change it.",
        "read_write": "The integration could read and change organizational data.",
        "admin": "The integration would have administrative access. That is broad control, not a limited job.",
    },
    "ai_use": {
        "none": "The service would not use AI. Model training is not scored while AI use is none.",
        "assistive": "The service would use AI to assist a person, not to act on its own.",
        "autonomous": "The service would use AI that acts on its own. That is more exposure than assistive use.",
    },
    "model_training_on_customer_data": {
        "no": "The intake says the vendor would not train on customer data. That answer is separate from the contract-clause check.",
        "yes": "The intake says the vendor would train or improve models on customer data.",
    },
    "external_exposure": {
        "internal_only": "Only people inside the organization would reach the service.",
        "customer_facing": "People outside the organization could reach the service.",
    },
}

TOPIC_QUESTION = {
    "integration_permissions": "whether the business can rely on access being limited to what the service needs",
    "authentication": "whether the business can rely on organizational users being identified and authenticated",
    "audit_logging": "whether the business could reconstruct security-relevant activity later",
    "transmission_security": "whether the business can rely on protection for information in transit",
    "privacy": "whether the business can rely on the stated collection, use, and retention of customer data",
}

STATUS_EFFECT = {
    "verified": (
        "A reviewer can treat the claim as supported for this demo. Support is one input. "
        "It does not approve the vendor, and it does not by itself lower residual risk."
    ),
    "self_attested": (
        "Only the vendor's own statement is behind the claim. Do not treat that as independently confirmed."
    ),
    "missing": (
        "Nothing supports the claim. That is an evidence gap, not a confirmed control failure, "
        "and it must not be counted as a safeguard."
    ),
    "conflicting": (
        "The sources disagree, so the business cannot rely on the claim until a person resolves which source to use. "
        "A conflicting claim also keeps residual risk from dropping."
    ),
    "expired": "The artifact is older than the freshness limit for its type. It is not current assurance.",
    "not_reviewed": (
        "An artifact is on file and has not been reviewed. Until someone reviews it, do not count it as support."
    ),
}

CONTROL_EFFECT = {
    "AC-6": "If access is broader than the job, the vendor can read or change more than the service needs.",
    "AU-2": "If logging is missing or unreviewed, the business may not be able to tell what the vendor did.",
    "IA-2": "If authentication is weak or unreviewed, the business cannot be confident that only the intended people reach the service.",
    "SC-8": "If transmission protection is weak or unreviewed, information can be exposed while it moves.",
    "A.5.15": "If access rules are missing or unreviewed, the integration may reach more information than the service needs.",
    "A.5.14": "If transfer safeguards are missing or unreviewed, information can be exposed while it moves to or from the service.",
    "A.8.5": "If authentication is weak or unreviewed, the business cannot be confident that only the intended people reach the service.",
    "A.8.15": "If logging is missing or unreviewed, the business may not be able to tell what happened on the service.",
    "A.6.2.6": "If operation and monitoring of an AI system are unreviewed, the business may not see how that system behaves in use.",
    "A.6.2.8": "If an AI system does not keep event logs, the business may not be able to reconstruct what the system did.",
    "A.7.2": "If use of customer data to develop or enhance an AI system is unreviewed, the business cannot tell whether its data is training material.",
    "A.7.3": "If acquisition of data for an AI system is unreviewed, the business cannot tell where that data came from.",
}


def _words(value):
    return str(value).replace("_", " ")


def _label(field):
    return FIELD_LABELS.get(field, str(field).replace("_", " "))


def factor_lines(risk, assessment=None):
    """One reviewer sentence per inherent factor the engine already scored."""
    if not isinstance(risk, dict):
        return []
    assessment = assessment if isinstance(assessment, dict) else {}
    inherent = risk.get("inherent") or {}
    lines = []
    for factor in inherent.get("factors") or []:
        if not isinstance(factor, dict):
            continue
        field = factor.get("factor", "")
        value = factor.get("value", "")
        points = factor.get("points", 0)
        meaning = FACTOR_MEANING.get(field, {}).get(value)
        if meaning is None:
            meaning = f"The answer for {_label(field)} is {_words(value)}."
        stored = assessment.get(field, value)
        if stored != value:
            meaning += f" The stored intake answer was {_words(stored)}."
        rule_id = factor.get("rule_id", "")
        lines.append({
            **factor,
            "label": _label(field),
            "rationale": (
                f"{meaning} This line uses the submitted answer {_words(value)}. "
                f"{rule_id} adds {points} to the inherent score. "
                "The points are exposure before safeguards. They are not an approval."
            ),
        })
    return lines


def missing_plain(risk):
    """Explain unknown inputs without treating them as safe or as verified controls."""
    if not isinstance(risk, dict):
        return ""
    fields = [field for field in (risk.get("missing_information") or []) if isinstance(field, str)]
    if not fields:
        return ""
    listed = "; ".join(f"{_label(field)} is unknown" for field in fields)
    return (
        f"Unknown inputs: {listed}. The result stays provisional. "
        "Unknown is not a safe default, and it is not a verified safeguard."
    )


def residual_plain(risk):
    """Restate the engine's residual reason. The tier is not recomputed."""
    if not isinstance(risk, dict):
        return "This result has no residual explanation."
    residual = risk.get("residual") or {}
    reason = residual.get("reason") or "The rule set did not record a residual reason."
    tier = _words(residual.get("tier") or "unrecorded")
    if reason.startswith("Result is provisional"):
        extra = missing_plain(risk)
        detail = f" {extra}" if extra else ""
        closing = " The tier stays undetermined until those answers are known."
    elif reason.startswith("Not lowered"):
        detail = ""
        closing = (
            f" Residual risk stays {tier}, the same tier as inherent risk. "
            "This model drops a tier only when evidence confidence is high, no claim is conflicting, "
            "and no escalation rule fired. Staying at this tier is not an approval."
        )
    elif reason.startswith("Already at the lowest"):
        detail = ""
        closing = (
            " Residual risk stays low because inherent risk is already at the lowest tier. "
            "Low residual risk is not an approval. Human review is still required."
        )
    elif reason.startswith("Lowered one tier"):
        detail = ""
        closing = (
            f" Residual risk is {tier}, one tier below inherent risk, because evidence confidence is high, "
            "no claim is conflicting, and no escalation rule fired. "
            "The model never drops more than one tier. The lower tier is not an approval, "
            "and a hard restriction can still prohibit the use."
        )
    else:
        detail = ""
        closing = " The tier comes from the rule set. It is not an approval."
    if "conflict" in reason:
        closing += " In that sentence, conflicts means claim evidence, not a contract-clause status."
    return reason + detail + closing


def confidence_plain(confidence, rules=None):
    """Describe the evidence-confidence level using the configured weights."""
    if not isinstance(confidence, dict):
        return "Evidence confidence was not recorded. That is not a verified safeguard."
    rules = rules if rules is not None else load_rules()
    weights = rules.get("evidence_weights") or {}
    level = _words(confidence.get("level") or "unrecorded")
    counts = confidence.get("counts") or {}

    def count(status):
        value = counts.get(status, 0)
        return value if isinstance(value, int) else 0

    if confidence.get("level") == "none":
        return "No claims were scored, so evidence confidence is none. That is not a verified safeguard."
    return (
        f"Evidence confidence is {level}. "
        f"Verified counts as {weights.get('verified', 0)}, "
        f"self-attested as {weights.get('self_attested', 0)}, "
        f"and expired as {weights.get('expired', 0)}. "
        "Not reviewed, missing, and conflicting count as 0. "
        f"This result has {count('verified')} verified, {count('self_attested')} self-attested, "
        f"{count('not_reviewed')} not reviewed, {count('expired')} expired, "
        f"{count('missing')} missing, and {count('conflicting')} conflicting. "
        "Confidence describes the evidence. It is not the residual risk, and it is not an approval."
    )


def review_path_plain(risk):
    """Say why the review route is standard or escalated. The route is not an approval."""
    if not isinstance(risk, dict):
        return "Human review is still required."
    reasons = []
    if risk.get("escalations"):
        reasons.append("an escalation rule fired")
    outcome = (risk.get("policy_outcome") or {}).get("status")
    if outcome == "prohibited":
        reasons.append("a hard restriction matched")
    if risk.get("review_path") == "escalated_review" or reasons:
        why = " and ".join(reasons) if reasons else "the engine marked the route escalated"
        return (
            f"Escalated review because {why}. A person has to complete that review. "
            "The numerical score cannot skip it, and it cannot approve the vendor."
        )
    return (
        "Standard review because no escalation rule fired and no hard restriction matched. "
        "Human review is still required. Standard review is not an approval."
    )


def _rules_by_id(rules=None):
    rules = rules if rules is not None else load_rules()
    return {rule.get("rule_id"): rule for rule in rules.get("escalation_rules") or []}


def escalation_rationale(item, assessment=None, claims=None, rules=None):
    """Tie a fired escalation to the answers and claim statuses that matched it."""
    if not isinstance(item, dict):
        return "An escalation fired. A person still has to review it. The score does not clear it."
    assessment = assessment if isinstance(assessment, dict) else {}
    claims = claims if isinstance(claims, list) else []
    rule = _rules_by_id(rules).get(item.get("rule_id"))
    conditions = []
    if isinstance(rule, dict):
        conditions = rule.get("all") or rule.get("any") or []
        joiner = " and " if rule.get("all") is not None else " or "
    else:
        joiner = " and "
    bits = []
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if "field" in condition:
            field = condition["field"]
            value = assessment.get(field)
            if value is None:
                bits.append(f"{_label(field)} matched this rule")
            else:
                bits.append(f"{_label(field)} is {_words(value)}")
        elif "claim_status" in condition:
            status = condition["claim_status"]
            matched = [claim for claim in claims if isinstance(claim, dict) and claim.get("evidence_status") == status]
            if matched:
                names = "; ".join(
                    claim.get("statement") or claim.get("claim_id") or "a claim" for claim in matched
                )
                bits.append(f"claim evidence is {status} ({names})")
            else:
                bits.append(f"a claim status is {status}")
    if bits:
        observed = f"Fired because {joiner.join(bits)}. "
    else:
        observed = "Fired on this assessment. "
    reason = item.get("reason") or "A configured escalation rule matched."
    assessment_type = item.get("assessment_type") or "review"
    owner = item.get("owner_role") or "reviewer"
    return (
        f"{observed}{reason}. The follow-up is a {assessment_type}, owned by the {owner}. "
        "The score does not clear this rule. A low residual tier is not an approval."
    )


def restriction_so_what(item):
    """Say which answer tripped a hard restriction. The score is unchanged."""
    if not isinstance(item, dict):
        return (
            "So what: a hard restriction matched. The score is not changed. "
            "A low residual tier does not clear it, and the engine does not approve the vendor."
        )
    field = _label(item.get("field") or "the policy answer")
    value = _words(item.get("observed_value") or "the prohibited value")
    restriction_id = item.get("restriction_id") or "the restriction"
    reason = item.get("reason") or "The organization marked that answer prohibited."
    return (
        f"So what: {field} is {value}, which is a prohibited answer under {restriction_id}. {reason} "
        "The score is not changed. A low residual tier does not clear the restriction, "
        "and the engine does not approve or reject the vendor."
    )


def claim_so_what(claim):
    """What this claim's evidence status means for the risk decision."""
    if not isinstance(claim, dict):
        return "So what: the claim status is for a person to review. It is not an approval."
    topic = claim.get("topic") or "this claim"
    question = TOPIC_QUESTION.get(topic, "whether the business can rely on this statement")
    status = claim.get("evidence_status")
    effect = STATUS_EFFECT.get(
        status,
        "The evidence status is recorded for a person to review. It is not an approval.",
    )
    return f"So what: this speaks to {question}. {effect}"


def mapping_so_what(mapping):
    """What a matched control means for the business, using the claim status already stored."""
    if not isinstance(mapping, dict):
        return (
            "So what: a control identifier is a review prompt. It does not show that the control is in place, "
            "and it is not a certification."
        )
    control = mapping.get("control_id") or "This control"
    effect = CONTROL_EFFECT.get(
        control,
        "This is a review prompt for the related claim. The control identifier does not mean the control is in place.",
    )
    related = mapping.get("related_claims") or []
    if related:
        bits = []
        for claim in related:
            if not isinstance(claim, dict):
                continue
            status = _words(claim.get("evidence_status") or "unknown")
            bits.append(f"{claim.get('claim_id') or 'the related claim'} is {status}")
        evidence = " On this assessment, " + "; ".join(bits) + "." if bits else ""
        tail = " Use that status. Do not read the control identifier as proof the safeguard works."
    else:
        evidence = ""
        tail = " On an assessment, read it next to the claim's evidence status. The identifier is not proof the safeguard works."
    review = mapping.get("review_status") or "draft"
    return (
        f"So what: {effect}{evidence}{tail} "
        f"The mapping stays {review}. It is not a certification, and it does not change the score."
    )


def _subject_view(subject):
    """Normalize a scenario result or a saved risk into (view, name, risk)."""
    if not isinstance(subject, dict):
        return {}, "This vendor", {}
    rationale = subject.get("rationale")
    if isinstance(rationale, dict) and isinstance(rationale.get("risk"), dict):
        name = subject.get("scenario_name") or rationale.get("vendor_name") or "This vendor"
        return rationale, name, rationale["risk"]
    if isinstance(subject.get("risk"), dict):
        name = subject.get("name") or subject.get("vendor_name") or "This vendor"
        return subject, name, subject["risk"]
    return {}, "This vendor", {}


def _question_catalog():
    """Prompt text for scoring questions, without trailing question marks."""
    from app.services.intake_questionnaire import load_questionnaire
    from app.services.org_policy import load_org_policy

    catalog = {}
    for spec in load_questionnaire()["context_questions"]:
        catalog[spec["field"]] = spec["prompt"].strip().rstrip("?").strip()
    for spec in load_org_policy()["intake_fields"]:
        catalog[spec["field"]] = spec["prompt"].strip().rstrip("?").strip()
    return catalog


def _unknown_fields(risk):
    fields = []
    for field in (risk or {}).get("missing_information") or []:
        if isinstance(field, str) and field not in fields:
            fields.append(field)
    return fields


def withheld_tier_line(risk):
    """One plain line when the tier is withheld. Empty when a tier was set.

    The line names the questions. It does not use rule codes, and it does
    not treat an unknown answer as a safe default or a verified safeguard.
    """
    if not isinstance(risk, dict):
        return ""
    residual = risk.get("residual") or {}
    inherent = risk.get("inherent") or {}
    if residual.get("tier") != "undetermined" and not inherent.get("provisional"):
        return ""
    names = [_question_catalog().get(field) or _label(field) for field in _unknown_fields(risk)]
    count = len(names)
    if count == 0:
        return "Risk level not set yet: a required answer is unknown. Answer it to get a tier."
    listed = ", ".join(names)
    if count == 1:
        return (
            f"Risk level not set yet: 1 required answer is unknown ({listed}). "
            "Answer it to get a tier."
        )
    return (
        f"Risk level not set yet: {count} required answers are unknown ({listed}). "
        "Answer them to get a tier."
    )


def owner_summary(subject):
    """Two or three sentences for a non-specialist. No rule codes.

    Covers what was assessed, the overall outcome, and the next step.
    The sentences restate the engine result. They do not rescore it.
    """
    view, name, risk = _subject_view(subject)
    assessment = view.get("assessment_inputs") if isinstance(view.get("assessment_inputs"), dict) else {}
    if assessment:
        data = _words(assessment.get("data_sensitivity") or "unspecified")
        access = _words(assessment.get("integration_permissions") or "unspecified")
        ai = _words(assessment.get("ai_use") or "unspecified")
        first = (
            f"{name} is a synthetic review of a service that would handle {data} data, "
            f"with {access} access, and {ai} AI use."
        )
    else:
        first = (
            f"{name} is a synthetic vendor review. It looks at the data the service would handle, "
            "the access it would have, and whether it uses AI."
        )
    confidence = _words((risk.get("evidence_confidence") or {}).get("level") or "unrecorded")
    outcome = (risk.get("policy_outcome") or {}).get("status")
    provisional = bool((risk.get("inherent") or {}).get("provisional")) or (
        (risk.get("residual") or {}).get("tier") == "undetermined"
    )
    if outcome == "prohibited":
        policy_bit = "and the sample organization rules do not allow this use"
    elif outcome == "not_prohibited":
        policy_bit = "and no hard restriction matched, which is not an approval"
    else:
        policy_bit = "and a policy outcome was not stored on this record"
    if provisional:
        count = len(_unknown_fields(risk))
        if count == 1:
            unknown = "1 required answer is still unknown"
        elif count:
            unknown = f"{count} required answers are still unknown"
        else:
            unknown = "a required answer is still unknown"
        second = (
            f"The risk level is not set yet because {unknown}, with {confidence} evidence confidence, "
            f"{policy_bit}."
        )
        third = (
            "Answer the unknown questions to get a tier, then have a person record the decision, "
            "because the score is not an approval."
        )
    else:
        inherent = _words((risk.get("inherent") or {}).get("tier") or "unrecorded")
        residual = _words((risk.get("residual") or {}).get("tier") or "unrecorded")
        second = (
            f"Inherent risk is {inherent} and residual risk is {residual}, "
            f"with {confidence} evidence confidence, {policy_bit}."
        )
        claims = view.get("claims") if isinstance(view.get("claims"), list) else []
        gap = any(
            isinstance(claim, dict)
            and claim.get("evidence_status") in {"missing", "expired", "not_reviewed", "conflicting"}
            for claim in claims
        )
        if outcome == "prohibited":
            third = (
                "A person records the decision, and approving this use needs a written exception, "
                "because a low score does not clear the restriction."
            )
        elif gap:
            third = (
                "Collect or resolve the evidence gaps, then have a person record the decision, "
                "because the score is not an approval."
            )
        elif risk.get("review_path") == "escalated_review":
            third = (
                "A person completes the escalated review and records a decision, "
                "because the score cannot skip that review."
            )
        else:
            third = (
                "A person reviews this result and records a decision, "
                "because a low residual tier is not an approval."
            )
    return [first, second, third]


def clause_so_what(clause):
    """What a required-clause status means. Clause status is not a score."""
    if not isinstance(clause, dict):
        return (
            "So what: a required clause is a contract promise to check. "
            "Its status does not change the score and does not approve the vendor."
        )
    clause_id = clause.get("clause_id") or "This clause"
    status = clause.get("evidence_status")
    if not status:
        return (
            f"So what: {clause_id} is listed and was not checked against evidence on this result. "
            "A listed clause is not a verified promise, and it does not change the score."
        )
    effect = STATUS_EFFECT.get(status, "The evidence status is recorded for a person to review.")
    return (
        f"So what: {clause_id} asks whether that contract promise can be relied on. {effect} "
        "The clause status does not change the inherent score or the residual tier, and it does not approve the vendor."
    )
