"""Load the single organization AI-use policy.

Plain Python. One profile is intentional: multi-tenant policy storage is out of
scope. Required contract clauses are checked against evidence by the evidence
validator. This module only checks that the policy document is well formed.
"""

import json
from pathlib import Path

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "data" / "org_policy.json"

_POLICY_KEYS = (
    "policy_id",
    "policy_version",
    "hard_restrictions",
    "required_contract_clauses",
    "intake_fields",
)
_RESTRICTION_TEXT = (
    "restriction_id",
    "title",
    "description",
    "owner_role",
    "required_output",
    "next_step",
)


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate_policy(policy, unknown_value):
    """Reject a policy document that this prototype cannot apply honestly."""
    if not isinstance(policy, dict):
        raise ValueError("org policy must be an object")
    for key in _POLICY_KEYS:
        if key not in policy:
            raise ValueError(f"org policy missing {key}")
    if not _nonempty(policy["policy_id"]) or not _nonempty(policy["policy_version"]):
        raise ValueError("org policy needs a policy id and version")

    fields = policy["intake_fields"]
    if not isinstance(fields, list) or not fields:
        raise ValueError("org policy needs at least one intake field")
    field_names = set()
    for spec in fields:
        name = spec.get("field") if isinstance(spec, dict) else None
        allowed = spec.get("allowed") if isinstance(spec, dict) else None
        if not _nonempty(name) or not isinstance(allowed, list) or unknown_value not in allowed:
            raise ValueError(f"intake field {name}: allowed values must include {unknown_value!r}")
        if name in field_names:
            raise ValueError(f"intake field {name} is duplicated")
        if not _nonempty(spec.get("prompt")):
            raise ValueError(f"{name}: prompt is required")
        field_names.add(name)

    restrictions = policy["hard_restrictions"]
    if not isinstance(restrictions, list) or not restrictions:
        raise ValueError("org policy needs at least one hard restriction")
    seen_ids = set()
    for restriction in restrictions:
        if not isinstance(restriction, dict):
            raise ValueError("hard restriction must be an object")
        restriction_id = restriction.get("restriction_id", "<missing restriction_id>")
        if restriction_id in seen_ids:
            raise ValueError(f"{restriction_id} is duplicated")
        seen_ids.add(restriction_id)
        for key in _RESTRICTION_TEXT:
            if not _nonempty(restriction.get(key)):
                raise ValueError(f"{restriction_id}: {key} must be a non-empty string")
        field = restriction.get("field")
        if field not in field_names:
            raise ValueError(f"{restriction_id}: field is not an intake field")
        prohibited_when = restriction.get("prohibited_when")
        if not isinstance(prohibited_when, list) or not prohibited_when:
            raise ValueError(f"{restriction_id}: prohibited_when must list at least one value")
        if unknown_value in prohibited_when:
            raise ValueError(f"{restriction_id}: {unknown_value} cannot be a prohibited value")
        allowed = next(spec["allowed"] for spec in fields if spec["field"] == field)
        for value in prohibited_when:
            if value not in allowed:
                raise ValueError(f"{restriction_id}: {value!r} is not an allowed answer")

    clauses = policy["required_contract_clauses"]
    if not isinstance(clauses, list):
        raise ValueError("required_contract_clauses must be a list")
    seen_clauses = set()
    for clause in clauses:
        if not isinstance(clause, dict):
            raise ValueError("contract clause must be an object")
        clause_id = clause.get("clause_id", "<missing clause_id>")
        for key in ("clause_id", "title", "text"):
            if not _nonempty(clause.get(key)):
                raise ValueError(f"{clause_id}: {key} must be a non-empty string")
        if clause_id in seen_clauses:
            raise ValueError(f"{clause_id} is duplicated")
        seen_clauses.add(clause_id)
        if clause.get("enforced") is not True:
            raise ValueError(
                f"{clause_id}: required clauses are checked against evidence, so enforced must be true"
            )


def load_org_policy(path=DEFAULT_POLICY_PATH):
    with open(path, encoding="utf-8") as handle:
        policy = json.load(handle)
    validate_policy(policy, unknown_value="unknown")
    return policy
