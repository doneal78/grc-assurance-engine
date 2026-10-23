"""Rules-based risk evaluation engine.

Plain Python with no Flask, database, or network access. It reads a versioned
rule set and the single org policy, and returns a structured, explainable
result. It never approves or rejects a vendor. The review path is
standard_review or escalated_review. A prohibited policy outcome is separate
from the score tiers. Required contract clause statuses come from the evidence
validator and are not scored. See docs/risk-model.md.
"""

import json
from pathlib import Path

from app.services.org_policy import load_org_policy, validate_policy

DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "data" / "risk_rules.json"

REQUIRED_FIELDS = (
    "data_sensitivity",
    "integration_permissions",
    "ai_use",
    "model_training_on_customer_data",
    "external_exposure",
    "retention_deletion",
    "claims",
)


class RiskInputError(ValueError):
    """Raised when an assessment has missing fields or invalid values."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(problems))


def load_rules(path=DEFAULT_RULES_PATH):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate(assessment, rules, policy):
    problems = []
    unknown = rules["unknown_value"]
    for field in REQUIRED_FIELDS:
        if field not in assessment:
            problems.append(f"{field}: required field is missing")
    for spec in policy["intake_fields"]:
        field = spec["field"]
        if field not in assessment:
            problems.append(f"{field}: required field is missing")
        elif assessment[field] not in spec["allowed"]:
            allowed = sorted(spec["allowed"])
            problems.append(f"{field}: {assessment[field]!r} is not one of {allowed}")
    for field, factor in rules["inherent_factors"].items():
        if field in assessment:
            allowed = sorted(set(factor["points"]) | {unknown})
            if assessment[field] not in allowed:
                problems.append(f"{field}: {assessment[field]!r} is not one of {allowed}")
    retention_values = rules["retention_deletion_values"]
    if "retention_deletion" in assessment and assessment["retention_deletion"] not in retention_values:
        problems.append(f"retention_deletion: {assessment['retention_deletion']!r} is not one of {retention_values}")
    if "claims" in assessment:
        claims = assessment["claims"]
        if not isinstance(claims, list):
            problems.append("claims: must be a list")
        else:
            statuses = sorted(rules["evidence_weights"])
            for index, claim in enumerate(claims):
                status = claim.get("evidence_status") if isinstance(claim, dict) else None
                if status not in rules["evidence_weights"]:
                    problems.append(f"claims[{index}].evidence_status: {status!r} is not one of {statuses}")
    if problems:
        raise RiskInputError(problems)


def _inherent(assessment, rules):
    unknown = rules["unknown_value"]
    score, factors, missing = 0, [], []
    for field, factor in rules["inherent_factors"].items():
        skip_value = factor.get("applies_when_ai_use_is_not")
        if skip_value is not None and assessment["ai_use"] == skip_value:
            continue
        value = assessment[field]
        if value == unknown:
            missing.append(field)
            continue
        points = factor["points"][value]
        score += points
        factors.append({"rule_id": factor["rule_id"], "factor": field, "value": value, "points": points})
    if assessment["retention_deletion"] == unknown:
        missing.append("retention_deletion")
    return score, factors, missing


def _tier_for(score, rules):
    for tier in rules["tiers"]:
        if tier["min"] <= score <= tier["max"]:
            return tier["name"]
    raise ValueError(f"score {score} is outside the configured tiers")


def _confidence(claims, rules):
    weights = rules["evidence_weights"]
    counts = {status: 0 for status in weights}
    for claim in claims:
        counts[claim["evidence_status"]] += 1
    if not claims:
        return {"level": "none", "ratio": None, "counts": counts}
    ratio = round(sum(weights[c["evidence_status"]] for c in claims) / len(claims), 4)
    thresholds = rules["confidence_thresholds"]
    if ratio >= thresholds["high"]:
        level = "high"
    elif ratio >= thresholds["medium"]:
        level = "medium"
    else:
        level = "low"
    return {"level": level, "ratio": ratio, "counts": counts}


def _condition_met(condition, assessment):
    if "field" in condition:
        return assessment[condition["field"]] in condition["in"]
    if "claim_status" in condition:
        return any(c["evidence_status"] == condition["claim_status"] for c in assessment["claims"])
    raise ValueError(f"unsupported condition: {condition}")


# Copied onto every fired escalation so the review path names the assessment,
# who performs it, what it must produce, and what happens after it.
ESCALATION_DETAIL_FIELDS = ("assessment_type", "owner_role", "required_output", "next_step")


def _escalation_details(rule):
    rule_id = rule.get("rule_id", "<missing rule_id>")
    details = {}
    for field in ESCALATION_DETAIL_FIELDS:
        value = rule.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{rule_id}: {field} must be a non-empty string")
        details[field] = value
    return details


def _require_escalation_definitions(rules):
    for rule in rules["escalation_rules"]:
        _escalation_details(rule)


def _escalations(assessment, rules):
    fired = []
    for rule in rules["escalation_rules"]:
        if "all" in rule:
            met = all(_condition_met(c, assessment) for c in rule["all"])
        else:
            met = any(_condition_met(c, assessment) for c in rule["any"])
        if met:
            fired.append({
                "rule_id": rule["rule_id"],
                "reason": rule["description"],
                **_escalation_details(rule),
            })
    return fired


CLAUSE_EVIDENCE_STATUSES = (
    "verified", "self_attested", "expired", "not_reviewed", "missing", "conflicting",
)


def _missing_clause(clause):
    """The validator's result when a clause has no evidence records."""
    return {
        "clause_id": clause["clause_id"],
        "title": clause["title"],
        "text": clause["text"],
        "enforced": True,
        "evidence_status": "missing",
        "status_reason": "No evidence provided.",
        "evidence": [],
    }


def _merge_clauses(policy, clause_check):
    """Attach validator statuses. The policy text stays the source of the clause."""
    required = policy["required_contract_clauses"]
    if clause_check is None:
        return [_missing_clause(clause) for clause in required], None, None
    if not isinstance(clause_check, dict) or not isinstance(clause_check.get("clauses"), list):
        raise ValueError("clause check must include a clauses list")
    by_id = {}
    for item in clause_check["clauses"]:
        if not isinstance(item, dict):
            raise ValueError("clause result must be an object")
        clause_id = item.get("clause_id", "<missing clause_id>")
        if clause_id in by_id:
            raise ValueError(f"{clause_id}: duplicate clause result")
        status = item.get("evidence_status")
        if status not in CLAUSE_EVIDENCE_STATUSES:
            raise ValueError(f"{clause_id}: evidence_status {status!r} is not a clause evidence status")
        reason = item.get("status_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{clause_id}: status_reason is required")
        if not isinstance(item.get("evidence", []), list):
            raise ValueError(f"{clause_id}: evidence must be a list")
        by_id[clause_id] = item
    required_ids = [clause["clause_id"] for clause in required]
    missing_ids = [clause_id for clause_id in required_ids if clause_id not in by_id]
    if missing_ids:
        raise ValueError("clause check missing " + ", ".join(missing_ids))
    extra_ids = [clause_id for clause_id in by_id if clause_id not in required_ids]
    if extra_ids:
        raise ValueError("clause check has unknown clause " + ", ".join(extra_ids))
    merged = []
    for clause in required:
        item = by_id[clause["clause_id"]]
        merged.append({
            "clause_id": clause["clause_id"],
            "title": clause["title"],
            "text": clause["text"],
            "enforced": True,
            "evidence_status": item["evidence_status"],
            "status_reason": item["status_reason"],
            "evidence": item.get("evidence", []),
        })
    return merged, clause_check.get("evidence_policy_version"), clause_check.get("as_of")


def _policy_outcome(assessment, policy):
    """Match hard restrictions. Unknown is never a match. Clause evidence is separate."""
    matched = []
    for restriction in policy["hard_restrictions"]:
        field = restriction["field"]
        value = assessment[field]
        if value not in restriction["prohibited_when"]:
            continue
        matched.append({
            "restriction_id": restriction["restriction_id"],
            "title": restriction["title"],
            "reason": restriction["description"],
            "field": field,
            "observed_value": value,
            "policy_id": policy["policy_id"],
            "policy_version": policy["policy_version"],
            "owner_role": restriction["owner_role"],
            "required_output": restriction["required_output"],
            "next_step": restriction["next_step"],
        })
    return {
        "status": "prohibited" if matched else "not_prohibited",
        "restrictions": matched,
        "answers": [
            {"field": spec["field"], "prompt": spec["prompt"], "value": assessment[spec["field"]]}
            for spec in policy["intake_fields"]
        ],
    }


def _policy_reference(policy, clauses, clause_evidence_policy_version, clause_checked_as_of):
    return {
        "policy_id": policy["policy_id"],
        "policy_version": policy["policy_version"],
        "status": policy.get("status", ""),
        "clause_evidence_policy_version": clause_evidence_policy_version,
        "clause_checked_as_of": clause_checked_as_of,
        "required_contract_clauses": clauses,
    }


def evaluate(assessment, rules=None, policy=None, clause_check=None):
    """Evaluate one assessment and return a structured, explainable result.

    clause_check is the evidence validator's contract-clause result. When it
    is omitted, no clause evidence was supplied and each required clause is
    missing. This function does not derive a clause status from raw evidence.
    """
    rules = rules if rules is not None else load_rules()
    policy = policy if policy is not None else load_org_policy()
    _require_escalation_definitions(rules)
    validate_policy(policy, rules["unknown_value"])
    _validate(assessment, rules, policy)
    clauses, clause_version, clause_as_of = _merge_clauses(policy, clause_check)

    score, factors, missing = _inherent(assessment, rules)
    unknown = rules["unknown_value"]
    for spec in policy["intake_fields"]:
        if assessment[spec["field"]] == unknown:
            missing.append(spec["field"])
    provisional = bool(missing)
    confidence = _confidence(assessment["claims"], rules)
    escalations = _escalations(assessment, rules)
    conflicts = [c for c in assessment["claims"] if c["evidence_status"] == "conflicting"]
    policy_outcome = _policy_outcome(assessment, policy)

    if provisional:
        inherent_tier = residual_tier = "undetermined"
        residual_reason = "Result is provisional because required information is unknown."
    else:
        inherent_tier = _tier_for(score, rules)
        tier_names = [t["name"] for t in rules["tiers"]]
        blockers = []
        if confidence["level"] != "high":
            blockers.append("evidence confidence is not high")
        if conflicts:
            blockers.append("a claim is conflicting")
        if escalations:
            blockers.append("an escalation rule fired")
        index = tier_names.index(inherent_tier)
        if blockers:
            residual_tier = inherent_tier
            residual_reason = "Not lowered: " + "; ".join(blockers) + "."
        elif index == 0:
            residual_tier = inherent_tier
            residual_reason = "Already at the lowest tier."
        else:
            step = rules["residual"]["max_tier_reduction"]
            residual_tier = tier_names[max(0, index - step)]
            residual_reason = "Lowered one tier: high confidence, no conflicts, no escalations."

    return {
        "rule_set_version": rules["rule_set_version"],
        "inherent": {"score": score, "tier": inherent_tier, "provisional": provisional, "factors": factors},
        "evidence_confidence": confidence,
        "residual": {"tier": residual_tier, "reason": residual_reason},
        "escalations": escalations,
        "missing_information": missing,
        "conflicts": conflicts,
        "policy": _policy_reference(policy, clauses, clause_version, clause_as_of),
        "policy_outcome": policy_outcome,
        "review_path": "escalated_review" if escalations or policy_outcome["status"] == "prohibited" else "standard_review",
    }
    