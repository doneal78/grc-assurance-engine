"""A reviewer package for one vendor assessment.

JSON for a ticket or a handoff, and a plain-text summary that can be read or
printed. The package copies the assessment result. It does not score, fetch,
or approve the vendor.
"""

import json

from app.services.intake_questionnaire import load_questionnaire
from app.services.org_policy import load_org_policy

EXPORT_VERSION = "1.0.0"
AUTOMATIC_APPROVAL_NOTE = (
    "Nothing in this package approves the vendor. A trust-center URL cannot approve it. "
    "The decision, when present, was recorded by a person."
)
NOT_SUPPLIED = {
    "url": None,
    "fetched": False,
    "collection": "not_supplied",
    "note": "This assessment did not include a trust-center URL or artifact choices.",
    "pointers": [],
}


def _handling_time_note(minutes):
    if minutes is None:
        return "Not reported. Handling time for this decision is unmeasured."
    return (
        "Self-reported minutes spent reviewing. Optional. Not authenticated, "
        "not elapsed cycle time, not rework time, and not an input to the cost model."
    )


def _handling_time_line(minutes):
    if minutes is None:
        return "not reported (unmeasured)."
    unit = "minute" if minutes == 1 else "minutes"
    return f"{minutes} self-reported {unit}. Not authenticated effort tracking."


def _rework_time_note(minutes):
    if minutes is None:
        return "Rework time was not reported."
    return (
        "Self-reported minutes spent redoing work after a first pass. Optional. "
        "Not authenticated, not elapsed cycle time, not handling minutes, "
        "and not an input to the cost model."
    )


def _rework_time_line(minutes):
    if minutes is None:
        return "was not reported."
    unit = "minute" if minutes == 1 else "minutes"
    return (
        f"{minutes} self-reported {unit}. Not authenticated effort tracking. Not handling time."
    )


def _decision_view(decision):
    if not decision:
        return None
    return {
        "disposition": decision["disposition"],
        "decider": decision["decider"],
        "rationale": decision["rationale"],
        "conditions": decision["conditions"],
        "exception_rationale": decision["exception_rationale"],
        "decided_at": decision["decided_at"],
        "policy_id": decision["policy_id"],
        "policy_version": decision["policy_version"],
        "rule_set_version": decision["rule_set_version"],
        "prohibited_at_decision": decision["prohibited_at_decision"],
        "handling_minutes": decision.get("handling_minutes"),
        "handling_time_note": _handling_time_note(decision.get("handling_minutes")),
        "rework_minutes": decision.get("rework_minutes"),
        "rework_time_note": _rework_time_note(decision.get("rework_minutes")),
    }


def _direction_package(result):
    """Copy direction context. A missing section is not inferred and is not scored."""
    stored = result.get("direction_context")
    if not stored:
        return {
            "scored": False,
            "provided": False,
            "label": "Context only. Not scored.",
            "note": "This result has no vendor-direction context. It is not inferred, and it is not scored.",
            "fields": [],
            "direction_note": "",
            "note_prompt": "",
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


def _intake_answers(result):
    inputs = result.get("assessment_inputs")
    if not inputs:
        return None
    applicability = result.get("answer_applicability") or {}
    prompts = {spec["field"]: spec["prompt"] for spec in load_questionnaire()["context_questions"]}
    for spec in load_org_policy()["intake_fields"]:
        prompts.setdefault(spec["field"], spec["prompt"])
    ordered = [spec["field"] for spec in load_questionnaire()["context_questions"]]
    for spec in load_org_policy()["intake_fields"]:
        if spec["field"] not in ordered:
            ordered.append(spec["field"])
    for field in inputs:
        if field not in ordered:
            ordered.append(field)
    return [
        {
            "field": field,
            "prompt": prompts.get(field, field.replace("_", " ")),
            "value": inputs[field],
            "applicability": applicability.get(field, "answered"),
        }
        for field in ordered if field in inputs
    ]


def _evidence_summary(claims):
    rows = []
    for claim in claims or []:
        records = []
        for item in claim.get("evidence") or []:
            record = {"evidence_id": item.get("evidence_id"), "status": item.get("status")}
            for key in ("reason", "artifact_name", "artifact_type", "source", "pointer_id", "trust_center_url"):
                if item.get(key):
                    record[key] = item[key]
            records.append(record)
        rows.append({
            "claim_id": claim.get("claim_id"),
            "topic": claim.get("topic"),
            "statement": claim.get("statement"),
            "evidence_status": claim.get("evidence_status"),
            "status_reason": claim.get("status_reason"),
            "records": records,
        })
    return rows


def _clauses(risk):
    clauses = (risk.get("policy") or {}).get("required_contract_clauses") or []
    return [
        {
            "clause_id": clause.get("clause_id"),
            "title": clause.get("title"),
            "text": clause.get("text"),
            "evidence_status": clause.get("evidence_status"),
            "status_reason": clause.get("status_reason"),
        }
        for clause in clauses
    ]


def build_package(result, decision=None, saved_risk_id=None):
    """Copy one assessment into a stable handoff document."""
    risk = result["risk"]
    policy = risk.get("policy") or {}
    outcome = risk.get("policy_outcome") or {}
    if saved_risk_id:
        source = "saved_risk"
    elif result.get("scenario_id"):
        source = "scenario"
    else:
        source = "public_intake"
    trust_center = result.get("trust_center") or {**NOT_SUPPLIED, "pointers": []}
    answers = _intake_answers(result)
    return {
        "export_version": EXPORT_VERSION,
        "kind": "vendor_intake_package",
        "source": source,
        "saved_risk_id": saved_risk_id,
        "synthetic_data": bool(result.get("synthetic_data", True)),
        "human_review_required": True,
        "automatic_approval": None,
        "automatic_approval_note": AUTOMATIC_APPROVAL_NOTE,
        "vendor_name": result.get("name"),
        "summary": result.get("summary"),
        "as_of": result.get("as_of"),
        "versions": {
            "questionnaire": result.get("questionnaire_version"),
            "rule_set": risk.get("rule_set_version"),
            "evidence_policy": result.get("evidence_policy_version") or policy.get("clause_evidence_policy_version"),
            "org_policy": f"{policy.get('policy_id')} {policy.get('policy_version')}".strip(),
            "scenario_set": result.get("scenario_set_version"),
        },
        "intake_answers": answers,
        "direction_context": _direction_package(result),
        "intake_answers_note": None if answers is not None else (
            "This saved result does not include the intake answers. It was stored before the reviewer package."
        ),
        "trust_center": trust_center,
        "evaluation": {
            "inherent_score": risk["inherent"]["score"],
            "inherent_tier": risk["inherent"]["tier"],
            "provisional": risk["inherent"]["provisional"],
            "factors": risk["inherent"]["factors"],
            "evidence_confidence": risk["evidence_confidence"]["level"],
            "evidence_counts": risk["evidence_confidence"]["counts"],
            "residual_tier": risk["residual"]["tier"],
            "residual_reason": risk["residual"]["reason"],
            "review_path": risk["review_path"],
            "missing_information": risk["missing_information"],
            "escalations": risk["escalations"],
        },
        "policy_outcome": {
            "status": outcome.get("status"),
            "policy_id": policy.get("policy_id"),
            "policy_version": policy.get("policy_version"),
            "restrictions": [
                {"restriction_id": item["restriction_id"], "title": item["title"]}
                for item in outcome.get("restrictions") or []
            ],
        },
        "required_clauses": _clauses(risk),
        "evidence_summary": _evidence_summary(result.get("claims")),
        "decision": _decision_view(decision),
    }


def package_from_saved_risk(risk):
    """Rebuild a package from a local risk row. Older rows may lack intake answers."""
    rationale = risk["rationale"]
    stored = rationale.get("risk") or {}
    result = {
        "name": rationale.get("vendor_name") or risk.get("scenario_name"),
        "summary": rationale.get("summary") or risk.get("risk_statement"),
        "synthetic_data": True,
        "as_of": rationale.get("as_of") or (stored.get("policy") or {}).get("clause_checked_as_of"),
        "scenario_id": risk.get("scenario_id"),
        "scenario_set_version": rationale.get("scenario_set_version"),
        "questionnaire_version": rationale.get("questionnaire_version"),
        "assessment_inputs": rationale.get("assessment_inputs"),
        "answer_applicability": rationale.get("answer_applicability") or {},
        "direction_context": rationale.get("direction_context"),
        "trust_center": rationale.get("trust_center"),
        "evidence_policy_version": rationale.get("evidence_policy_version"),
        "claims": rationale.get("claims") or [],
        "risk": stored,
    }
    return build_package(result, decision=risk.get("decision"), saved_risk_id=risk["risk_id"])


def export_basename(package):
    name = package.get("vendor_name") or "vendor"
    cleaned = "".join(character.lower() if character.isalnum() else "-" for character in name)
    parts = [part for part in cleaned.split("-") if part]
    slug = "-".join(parts)[:48] or "vendor"
    return f"{slug}-intake"


def render_markdown(package):
    """A readable summary. The same facts are in the JSON package."""
    versions = package["versions"]
    lines = [
        "# Vendor intake package",
        "",
        f"Vendor: {package['vendor_name']}",
        "",
        package["summary"] or "",
        "",
        "Synthetic demonstration data. This package is a handoff for a reviewer or a ticket. "
        "It is not an approval. A person decides.",
        "",
        package["automatic_approval_note"],
        "",
        "## Versions",
        "",
        f"- Questionnaire: {versions['questionnaire'] or 'not on this result'}",
        f"- Rule set: {versions['rule_set']}",
        f"- Evidence policy: {versions['evidence_policy']}",
        f"- Org policy: {versions['org_policy']}",
        f"- Scenario set: {versions['scenario_set'] or 'not a saved scenario'}",
        f"- Evaluation date: {package['as_of']}",
        "",
        "## Intake answers",
        "",
    ]
    if package["intake_answers"] is None:
        lines.append(package["intake_answers_note"])
    else:
        for answer in package["intake_answers"]:
            suffix = ""
            if answer["applicability"] == "not_applicable":
                suffix = " (not asked; AI use is none, so this answer is not scored)"
            lines.append(f"- {answer['prompt']} {answer['value']}{suffix}")
    direction = package["direction_context"]
    lines.extend([
        "",
        "## Direction context",
        "",
        direction["note"],
        "",
        "Scored: no. These answers do not change the residual tier, the disposition, or the control mappings.",
    ])
    if direction["provided"]:
        for item in direction["fields"]:
            lines.append(f"- {item['prompt']} {item['display'] or 'Not provided'}")
        if direction.get("note_prompt"):
            lines.append(f"- {direction['note_prompt']} {direction['direction_note'] or 'Not provided'}")
    lines.extend(["", "## Trust center", ""])
    trust = package["trust_center"]
    lines.append(f"- URL: {trust['url'] or 'none'}")
    lines.append(f"- Fetched: {'yes' if trust['fetched'] else 'no'}")
    lines.append(f"- Collection: {trust['collection'].replace('_', ' ')}")
    lines.append(f"- Note: {trust['note']}")
    fetch = trust.get("fetch") or {}
    if fetch.get("requested"):
        lines.append(f"- Fetch outcome: {fetch.get('outcome') or 'unknown'}")
        if fetch.get("fetched_at"):
            lines.append(f"- Fetched at: {fetch['fetched_at']}")
        if fetch.get("http_status"):
            lines.append(f"- HTTP status: {fetch['http_status']}")
        if fetch.get("evidence_status"):
            lines.append(f"- Fetch evidence status: {fetch['evidence_status']}. {fetch.get('status_reason') or ''}")
        if fetch.get("summary"):
            lines.append(f"- Summary: {fetch['summary']}")
        if fetch.get("excerpt"):
            lines.append(f"- Excerpt: {fetch['excerpt']}")
        if fetch.get("error"):
            lines.append(f"- Fetch error: {fetch['error']}")
        lines.append("- A fetch is vendor-published material for human review. It is not verified evidence.")
    if trust["pointers"]:
        for pointer in trust["pointers"]:
            topics = ", ".join(pointer["topics"])
            lines.extend(["", f"### {pointer['prompt']}", "",
                          f"- Choice: {pointer['option']}",
                          f"- Artifact type: {pointer['artifact_type']}",
                          f"- Claim topics: {topics}",
                          f"- Evidence ids: {', '.join(pointer['evidence_ids']) or 'none'}"])
    evaluation = package["evaluation"]
    lines.extend([
        "",
        "## Evaluation",
        "",
        f"- Inherent: {evaluation['inherent_score']} ({evaluation['inherent_tier']})",
        f"- Provisional: {'yes' if evaluation['provisional'] else 'no'}",
        f"- Evidence confidence: {evaluation['evidence_confidence']}",
        f"- Residual: {evaluation['residual_tier']}. {evaluation['residual_reason']}",
        f"- Review route: {evaluation['review_path'].replace('_', ' ')}",
        f"- Policy outcome: {(package['policy_outcome']['status'] or 'unknown').replace('_', ' ')}",
    ])
    if evaluation["factors"]:
        lines.append("- Factors:")
        for factor in evaluation["factors"]:
            lines.append(f"  - {factor['rule_id']} {factor['factor']} = {factor['value']} (+{factor['points']})")
    if evaluation["missing_information"]:
        lines.append("- Unknown inputs: " + ", ".join(evaluation["missing_information"]))
    if evaluation["escalations"]:
        lines.append("- Escalations:")
        for item in evaluation["escalations"]:
            lines.append(f"  - {item['rule_id']}: {item['reason']} ({item['owner_role']})")
    else:
        lines.append("- Escalations: none")
    lines.extend(["", "## Required contract clauses", ""])
    if package["required_clauses"]:
        for clause in package["required_clauses"]:
            status = clause["evidence_status"] or "not checked"
            lines.append(f"- {clause['clause_id']}: {status}. {clause['text']}")
            if clause["status_reason"]:
                lines.append(f"  - {clause['status_reason']}")
    else:
        lines.append("No required clauses on this result.")
    lines.extend(["", "## Evidence summary", ""])
    if package["evidence_summary"]:
        for claim in package["evidence_summary"]:
            lines.append(f"- {claim['claim_id']}: {claim['evidence_status']}. {claim['statement']}")
            for record in claim["records"]:
                source = record.get("source", "source not recorded")
                artifact = record.get("artifact_type", "artifact")
                lines.append(f"  - {record['evidence_id']}: {record['status']} ({artifact}, {source})")
    else:
        lines.append("No claims on this result.")
    lines.extend(["", "## Decision", ""])
    decision = package["decision"]
    if decision is None:
        lines.append("No decision recorded. The assessment result is not a disposition.")
    else:
        lines.append(f"- Disposition: {decision['disposition'].replace('_', ' ')}")
        lines.append(f"- Decider: {decision['decider']}")
        lines.append(f"- Decided at: {decision['decided_at']}")
        lines.append(f"- Rationale: {decision['rationale']}")
        if decision["conditions"]:
            lines.append(f"- Conditions: {decision['conditions']}")
        if decision["exception_rationale"]:
            lines.append(f"- Exception rationale: {decision['exception_rationale']}")
        lines.append(f"- Policy at decision: {decision['policy_id']} {decision['policy_version']}")
        lines.append(f"- Rule set at decision: {decision['rule_set_version']}")
        lines.append(f"- Policy outcome at decision: {decision['prohibited_at_decision'].replace('_', ' ')}")
        lines.append(f"- Human handling time: {_handling_time_line(decision.get('handling_minutes'))}")
        lines.append(f"- Rework time: {_rework_time_line(decision.get('rework_minutes'))}")
    lines.extend(["", "End of package.", ""])
    return "\n".join(lines)


def render_json(package):
    return json.dumps(package, indent=2) + "\n"


def render_export(package, export_format):
    """Return body, content type, and filename for one download."""
    basename = export_basename(package)
    if export_format == "json":
        return render_json(package), "application/json", f"{basename}.json"
    if export_format == "markdown":
        return render_markdown(package), "text/markdown", f"{basename}.md"
    raise ValueError(export_format)
