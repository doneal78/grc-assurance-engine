"""Evidence validator: derives each claim's evidence status from evidence records.

Plain Python with no Flask or database. The evaluation date is passed in,
never read from the system clock, so results are reproducible.
See docs/evidence-model.md.
"""

import json
from datetime import date
from pathlib import Path

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent.parent / "data" / "evidence_policy.json"
REVIEW_CHECKS = ("relevant", "in_scope", "supports_claim", "contradicts_claim")
RANK = ("verified", "self_attested", "expired", "not_reviewed")


class EvidenceInputError(ValueError):
    """Raised when claims or evidence records are invalid."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(problems))


def load_policy(path=DEFAULT_POLICY_PATH):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _parse_date(value, label, problems):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        problems.append(f"{label}: {value!r} is not a YYYY-MM-DD date")
        return None


def _validate(claims, evidence, as_of, policy):
    problems = []
    if not isinstance(as_of, date):
        raise EvidenceInputError(["as_of: must be a date"])
    claim_ids = [c.get("claim_id") for c in claims]
    if len(set(claim_ids)) != len(claim_ids):
        problems.append("claims: duplicate claim_id")
    seen = set()
    for i, ev in enumerate(evidence):
        label = f"evidence[{i}]"
        if ev.get("evidence_id") in seen:
            problems.append(f"{label}.evidence_id: duplicate {ev.get('evidence_id')!r}")
        seen.add(ev.get("evidence_id"))
        if ev.get("claim_id") not in claim_ids:
            problems.append(f"{label}.claim_id: {ev.get('claim_id')!r} does not match any claim")
        if ev.get("artifact_type") not in policy["max_age_days"]:
            problems.append(f"{label}.artifact_type: {ev.get('artifact_type')!r} is not a known type")
        if ev.get("source") not in policy["sources"]:
            problems.append(f"{label}.source: {ev.get('source')!r} is not one of {policy['sources']}")
        collected = _parse_date(ev.get("collection_date"), f"{label}.collection_date", problems)
        if collected and collected > as_of:
            problems.append(f"{label}.collection_date: is after the evaluation date")
        review = ev.get("review")
        if review is not None:
            reviewed = _parse_date(review.get("reviewed_on"), f"{label}.review.reviewed_on", problems)
            if reviewed and reviewed > as_of:
                problems.append(f"{label}.review.reviewed_on: is after the evaluation date")
            if reviewed and collected and reviewed < collected:
                problems.append(f"{label}.review.reviewed_on: is before the collection date")
            for check in REVIEW_CHECKS:
                if not isinstance(review.get(check), bool):
                    problems.append(f"{label}.review.{check}: must be true or false")
    if problems:
        raise EvidenceInputError(problems)


def _evidence_status(ev, as_of, policy):
    """Status of one evidence record. The first matching rule wins."""
    review = ev.get("review")
    if review and review["contradicts_claim"]:
        return "conflicting", "Reviewer recorded that it contradicts the claim."
    age = (as_of - date.fromisoformat(ev["collection_date"])).days
    limit = policy["max_age_days"][ev["artifact_type"]]
    if age > limit:
        return "expired", f"{age} days old; the limit for {ev['artifact_type']} is {limit}."
    if review is None:
        return "not_reviewed", "No review recorded."
    failed = [c for c in ("relevant", "in_scope", "supports_claim") if not review[c]]
    if failed:
        return "unusable", "Excluded because " + ", ".join(failed) + " is false."
    if ev["source"] == "vendor":
        return "self_attested", "Reviewed, but the source is the vendor."
    return "verified", "Independent, reviewed, current, relevant, in scope, and supporting."


def validate(claims, evidence, as_of, policy=None):
    """Derive an evidence status for every claim."""
    policy = policy if policy is not None else load_policy()
    _validate(claims, evidence, as_of, policy)
    results = []
    for claim in claims:
        records = []
        for ev in evidence:
            if ev["claim_id"] == claim["claim_id"]:
                status, reason = _evidence_status(ev, as_of, policy)
                records.append({"evidence_id": ev["evidence_id"], "status": status,
                                "reason": reason, "file_sha256": ev.get("file_sha256")})
        statuses = [r["status"] for r in records]
        usable = [s for s in statuses if s != "unusable"]
        if not records:
            status, reason = "missing", "No evidence provided."
        elif "conflicting" in statuses:
            status, reason = "conflicting", "At least one evidence record contradicts the claim."
        elif not usable:
            status, reason = "missing", "Evidence was provided, but none supports the claim."
        else:
            status = min(usable, key=RANK.index)
            reason = f"Best usable evidence status is {status}."
        results.append({**claim, "evidence_status": status, "status_reason": reason, "evidence": records})
    return {"evidence_policy_version": policy["evidence_policy_version"],
            "as_of": as_of.isoformat(), "claims": results}
            