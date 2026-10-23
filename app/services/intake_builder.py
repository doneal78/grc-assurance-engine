"""Turn the public demo intake form into synthetic assessment inputs.

The public "Try it" pages let a visitor describe a fictional vendor or AI
tool. This module converts that form into the same claims and evidence
records the evidence validator and risk engine already use, so every result
comes from the tested application logic rather than demo-only scoring.
Nothing here writes to the database.
"""

from datetime import timedelta

from app.services.control_mapper import map_claims
from app.services.evidence_validator import validate
from app.services.org_policy import load_org_policy
from app.services.risk_engine import evaluate, load_rules

MAX_VENDOR_NAME = 80

ASSESSMENT_FIELDS = (
    "data_sensitivity",
    "integration_permissions",
    "ai_use",
    "model_training_on_customer_data",
    "external_exposure",
    "retention_deletion",
)

# Claim topics are limited to the topics the control mapping library covers.
CLAIM_STATEMENTS = {
    "authentication": "Organizational users authenticate to the service.",
    "integration_permissions": "The integration is limited to the access requested.",
    "transmission_security": "Data is encrypted in transit.",
    "audit_logging": "Security-relevant events are logged and retained.",
}

EVIDENCE_OPTIONS = {
    "independent_verified": "Independent report, reviewed",
    "vendor_statement": "Vendor's own statement, reviewed",
    "not_reviewed": "Independent report, not reviewed yet",
    "expired": "Independent report, older than its freshness limit",
    "contradicts": "Configuration export that contradicts the claim",
    "none": "Nothing provided",
}

GAP_STATUSES = {"missing", "expired", "not_reviewed", "conflicting"}

PRIORITY_BY_RESIDUAL_TIER = {
    "critical": "1 - Critical",
    "high": "2 - High",
    "moderate": "3 - Moderate",
    "low": "4 - Low",
    "undetermined": "2 - High (result undetermined)",
}


class IntakeError(ValueError):
    """Raised when the public intake form has missing or invalid values."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(problems))


def assessment_fields():
    """Scoring fields plus the org-policy intake fields, without duplicates."""
    policy_fields = [spec["field"] for spec in load_org_policy()["intake_fields"]]
    return tuple(dict.fromkeys((*ASSESSMENT_FIELDS, *policy_fields)))


def field_choices():
    """Allowed values for each assessment field, read from the rule set and org policy."""
    rules = load_rules()
    choices = {field: list(factor["points"]) + [rules["unknown_value"]]
               for field, factor in rules["inherent_factors"].items()}
    choices["retention_deletion"] = list(rules["retention_deletion_values"])
    for spec in load_org_policy()["intake_fields"]:
        choices[spec["field"]] = list(spec["allowed"])
    return choices


def _ids(topic):
    suffix = topic.upper().replace("_", "-")
    return f"C-{suffix}", f"E-{suffix}"


def _evidence_record(topic, option, as_of):
    """Build one synthetic evidence record dated relative to the evaluation date."""
    claim_id, evidence_id = _ids(topic)

    def days_ago(days):
        return (as_of - timedelta(days=days)).isoformat()

    review = {"reviewer": "Demo reviewer", "reviewed_on": days_ago(5), "relevant": True,
              "in_scope": True, "supports_claim": True, "contradicts_claim": False}
    report = {"evidence_id": evidence_id, "claim_id": claim_id,
              "artifact_name": "Independent SOC 2 Type II report",
              "artifact_type": "soc2_type2_report", "source": "independent_auditor"}
    if option == "independent_verified":
        return {**report, "collection_date": days_ago(120), "review": review}
    if option == "not_reviewed":
        return {**report, "collection_date": days_ago(60)}
    if option == "expired":
        return {**report, "collection_date": days_ago(500), "review": review}
    if option == "vendor_statement":
        return {"evidence_id": evidence_id, "claim_id": claim_id,
                "artifact_name": "Vendor security statement", "artifact_type": "vendor_statement",
                "source": "vendor", "collection_date": days_ago(30), "review": review}
    if option == "contradicts":
        return {"evidence_id": evidence_id, "claim_id": claim_id,
                "artifact_name": "Integration configuration export",
                "artifact_type": "configuration_export", "source": "internal_observation",
                "collection_date": days_ago(7), "review": {**review, "contradicts_claim": True}}
    return None  # "none": the claim has no evidence records


def build_intake(form, as_of):
    """Validate the intake form and return claims, evidence, and assessment inputs."""
    problems = []
    vendor_name = (form.get("vendor_name") or "").strip()
    if not vendor_name:
        problems.append("Vendor or tool name is required.")
    elif len(vendor_name) > MAX_VENDOR_NAME:
        problems.append(f"Vendor or tool name must be {MAX_VENDOR_NAME} characters or fewer.")
    elif not vendor_name.isprintable():
        problems.append("Vendor or tool name contains unsupported characters.")

    choices = field_choices()
    assessment = {}
    for field in assessment_fields():
        value = form.get(field, "")
        if value not in choices[field]:
            problems.append(f"{field.replace('_', ' ').capitalize()}: choose one of the listed options.")
        assessment[field] = value

    claims, evidence = [], []
    for topic, statement in CLAIM_STATEMENTS.items():
        option = form.get(f"evidence_{topic}", "")
        if option not in EVIDENCE_OPTIONS:
            problems.append(f"Evidence for {topic.replace('_', ' ')}: choose one of the listed options.")
            continue
        claim_id, _ = _ids(topic)
        claims.append({"claim_id": claim_id, "topic": topic, "statement": statement})
        record = _evidence_record(topic, option, as_of)
        if record is not None:
            evidence.append(record)

    if problems:
        raise IntakeError(problems)
    return {"vendor_name": vendor_name, "assessment": assessment, "claims": claims, "evidence": evidence}


def run_intake(intake, as_of):
    """Run a validated intake through the same services the full application uses."""
    evidence_result = validate(intake["claims"], intake["evidence"], as_of)
    risk = evaluate({**intake["assessment"], "claims": evidence_result["claims"]})
    return {
        "scenario_id": None,
        "name": intake["vendor_name"],
        "summary": "Submitted through the public demo intake form. Synthetic input, not saved.",
        "synthetic_data": True,
        "as_of": as_of.isoformat(),
        "scenario_set_version": None,
        "assessment_inputs": intake["assessment"],
        "evidence_policy_version": evidence_result["evidence_policy_version"],
        "claims": evidence_result["claims"],
        "risk": risk,
        "mappings": map_claims(evidence_result["claims"]),
    }


def remediation_payload(result):
    """A mock ServiceNow-style ticket payload, or None when no follow-up is needed."""
    risk = result["risk"]
    gaps = [c for c in result["claims"] if c["evidence_status"] in GAP_STATUSES]
    prohibited = risk["policy_outcome"]["status"] == "prohibited"
    if not risk["escalations"] and not gaps and not prohibited:
        return None
    if prohibited:
        priority = "Policy restriction — human decision required"
        summary = f"Policy restriction follow-up: {result['name']}"
    else:
        priority = PRIORITY_BY_RESIDUAL_TIER[risk["residual"]["tier"]]
        summary = f"Vendor risk review follow-up: {result['name']}"
    return {
        "_demo_note": "Mock ServiceNow-style payload. Not sent to any system.",
        "short_description": summary,
        "category": "vendor_risk",
        "priority": priority,
        "assignment_group": "GRC Review (demo)",
        "review_path": risk["review_path"],
        "escalation_rules": [e["rule_id"] for e in risk["escalations"]],
        "policy_id": risk["policy"]["policy_id"],
        "policy_version": risk["policy"]["policy_version"],
        "policy_outcome": risk["policy_outcome"]["status"],
        "restrictions": [item["restriction_id"] for item in risk["policy_outcome"]["restrictions"]],
        "evidence_requests": [
            {"claim_id": c["claim_id"], "status": c["evidence_status"],
             "request": f"Provide current, reviewable evidence for: {c['statement']}"}
            for c in gaps
        ],
        "related_controls": [m["control_id"] for m in result["mappings"]],
        "rule_set_version": risk["rule_set_version"],
        "evidence_policy_version": result["evidence_policy_version"],
        "evaluated_as_of": result["as_of"],
    }


def workflow_events(result):
    """The ordered workflow steps for one assessment, described from its results."""
    risk = result["risk"]
    counts = risk["evidence_confidence"]["counts"]
    summary = ", ".join(f"{n} {status.replace('_', ' ')}" for status, n in counts.items() if n)
    if risk["escalations"]:
        escalation = "Fired: " + ", ".join(e["rule_id"] for e in risk["escalations"]) + ". Escalated review required."
    else:
        escalation = "No escalation rule fired. Human review is still required."
    policy = risk["policy"]
    outcome = risk["policy_outcome"]
    if outcome["status"] == "prohibited":
        ids = ", ".join(item["restriction_id"] for item in outcome["restrictions"])
        policy_detail = (f"Prohibited under {policy['policy_id']} {policy['policy_version']}: {ids}. "
                         "The score and residual tier are unchanged by this outcome.")
    else:
        policy_detail = (f"No hard restriction matched ({policy['policy_id']} {policy['policy_version']}). "
                         "Listed contract clauses were not checked.")
    steps = [
        ("Intake received", f"{len(result['claims'])} claims recorded for {result['name']}."),
        ("Evidence validated", f"Evidence policy {result['evidence_policy_version']}, evaluated as of "
                               f"{result['as_of']}: {summary or 'no claims'}."),
        ("Risk evaluated", f"Rule set {risk['rule_set_version']}: inherent {risk['inherent']['tier']}, "
                           f"evidence confidence {risk['evidence_confidence']['level']}, "
                           f"residual {risk['residual']['tier']}."),
        ("Policy check", policy_detail),
        ("Escalation check", escalation),
        ("Controls mapped", f"{len(result['mappings'])} draft NIST SP 800-53 mapping prompts matched by claim topic."),
    ]
    if remediation_payload(result):
        steps.append(("Remediation ticket drafted", "Mock ServiceNow-style payload prepared. Not sent to any system."))
    else:
        steps.append(("No remediation ticket", "No escalation, policy restriction, or evidence gap required follow-up."))
    return [{"step": index, "title": title, "detail": detail}
            for index, (title, detail) in enumerate(steps, start=1)]
