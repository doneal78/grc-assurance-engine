"""Trace claim topics to a small, versioned control mapping library.

This module is framework-independent. Catalog references are source-checked;
mapping applicability and rationale remain draft pending human review.
"""

import json
from pathlib import Path

DEFAULT_MAPPING_PATH = Path(__file__).resolve().parent.parent / "data" / "control_mappings.json"
REQUIRED_FIELDS = (
    "mapping_id", "framework", "framework_version", "control_id", "title",
    "applicability", "applicability_note", "rationale", "claim_topics",
    "source_reference", "review_status",
)


class MappingInputError(ValueError):
    """Raised when mapping data or claim records are malformed."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(problems))


def load_mappings(path=DEFAULT_MAPPING_PATH):
    """Load the versioned mapping data from JSON."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate(claims, mapping_set):
    problems = []
    if not isinstance(claims, list):
        raise MappingInputError(["claims: must be a list"])
    seen_claims = set()
    for index, claim in enumerate(claims):
        label = f"claims[{index}]"
        if not isinstance(claim, dict):
            problems.append(f"{label}: must be an object")
            continue
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id.strip():
            problems.append(f"{label}.claim_id: must be a non-empty string")
        elif claim_id in seen_claims:
            problems.append(f"{label}.claim_id: duplicate {claim_id!r}")
        seen_claims.add(claim_id)
        if "topic" in claim and not isinstance(claim["topic"], str):
            problems.append(f"{label}.topic: must be a string")

    mappings = mapping_set.get("mappings") if isinstance(mapping_set, dict) else None
    if not isinstance(mappings, list):
        problems.append("mappings: must be a list")
    else:
        seen_mappings = set()
        for index, mapping in enumerate(mappings):
            label = f"mappings[{index}]"
            if not isinstance(mapping, dict):
                problems.append(f"{label}: must be an object")
                continue
            for field in REQUIRED_FIELDS:
                if field not in mapping:
                    problems.append(f"{label}.{field}: required field is missing")
            mapping_id = mapping.get("mapping_id")
            if mapping_id in seen_mappings:
                problems.append(f"{label}.mapping_id: duplicate {mapping_id!r}")
            seen_mappings.add(mapping_id)
            if mapping.get("review_status") not in {"draft", "unverified", "reviewed"}:
                problems.append(f"{label}.review_status: unsupported value")
            if not isinstance(mapping.get("claim_topics"), list):
                problems.append(f"{label}.claim_topics: must be a list")
    if problems:
        raise MappingInputError(problems)


def map_claims(claims, mapping_set=None):
    """Return mappings matched by explicit claim topic, with trace links.

    Claims without a topic are intentionally left unmapped. Evidence statuses
    are copied through as references; a mapping never changes evidence status.
    """
    mapping_set = mapping_set if mapping_set is not None else load_mappings()
    _validate(claims, mapping_set)
    results = []
    for mapping in mapping_set["mappings"]:
        related = [claim for claim in claims if claim.get("topic") in mapping["claim_topics"]]
        if not related:
            continue
        evidence_refs = [
            {"evidence_id": item["evidence_id"], "status": item["status"]}
            for claim in related for item in claim.get("evidence", [])
        ]
        results.append({
            **mapping,
            "related_claims": [
                {"claim_id": claim["claim_id"], "evidence_status": claim.get("evidence_status", "unknown")}
                for claim in related
            ],
            "related_evidence": evidence_refs,
            "mapping_set_version": mapping_set["mapping_set_version"],
        })
    return results
