"""Phase 3 tests for the evidence validator (see docs/evidence-model.md)."""

import copy
from datetime import date

import pytest

from app.services.evidence_validator import EvidenceInputError, validate
from app.services.risk_engine import evaluate

AS_OF = date(2026, 10, 14)
CLAIMS = [{"claim_id": "C1", "statement": "MFA is enforced"}]


def review(**overrides):
    base = {"reviewer": "Reviewer A", "reviewed_on": "2026-10-01", "relevant": True,
            "in_scope": True, "supports_claim": True, "contradicts_claim": False}
    base.update(overrides)
    return base


def ev(**overrides):
    """An independent SOC 2 report, 200 days old, reviewed, all checks pass."""
    base = {"evidence_id": "E1", "claim_id": "C1", "artifact_name": "SOC 2 Type II",
            "artifact_type": "soc2_type2_report", "source": "independent_auditor",
            "collection_date": "2026-03-28", "review": review()}
    base.update(overrides)
    return base


def claim_result(evidence):
    return validate(CLAIMS, evidence, AS_OF)["claims"][0]


def test_no_evidence_is_missing():
    c = claim_result([])
    assert c["evidence_status"] == "missing" and c["status_reason"] == "No evidence provided."


def test_current_independent_reviewed_evidence_is_verified():
    assert claim_result([ev()])["evidence_status"] == "verified"


def test_exactly_at_freshness_limit_is_still_current():
    assert claim_result([ev(collection_date="2025-10-14")])["evidence_status"] == "verified"


def test_one_day_past_limit_is_expired():
    assert claim_result([ev(collection_date="2025-10-13")])["evidence_status"] == "expired"


def test_freshness_limit_depends_on_artifact_type():
    c = claim_result([ev(artifact_type="configuration_export", collection_date="2026-07-15")])
    assert c["evidence_status"] == "expired"
    assert "limit for configuration_export is 90" in c["evidence"][0]["reason"]


def test_vendor_source_is_self_attested_even_after_review():
    c = claim_result([ev(source="vendor", artifact_type="vendor_statement")])
    assert c["evidence_status"] == "self_attested"


def test_unreviewed_evidence_is_not_reviewed():
    assert claim_result([ev(review=None)])["evidence_status"] == "not_reviewed"


def test_evidence_that_does_not_support_claim_is_excluded():
    c = claim_result([ev(review=review(supports_claim=False))])
    assert c["evidence_status"] == "missing"
    assert c["status_reason"] == "Evidence was provided, but none supports the claim."
    assert c["evidence"][0]["status"] == "unusable"


def test_contradiction_outweighs_verified_evidence():
    contradicting = ev(evidence_id="E2", artifact_type="configuration_export",
                       collection_date="2026-09-01", review=review(contradicts_claim=True))
    assert claim_result([ev(), contradicting])["evidence_status"] == "conflicting"


def test_contradiction_counts_even_when_evidence_is_old():
    old = ev(collection_date="2024-01-01", review=review(contradicts_claim=True))
    assert claim_result([old])["evidence_status"] == "conflicting"


def test_best_usable_status_wins():
    expired_report = ev(collection_date="2025-10-13")
    statement = ev(evidence_id="E2", source="vendor", artifact_type="vendor_statement")
    assert claim_result([expired_report, statement])["evidence_status"] == "self_attested"


def test_hash_is_recorded_but_never_changes_status():
    c = claim_result([ev(file_sha256="a" * 64)])
    assert c["evidence_status"] == "verified"
    assert c["evidence"][0]["file_sha256"] == "a" * 64


@pytest.mark.parametrize("bad, expected", [
    (ev(artifact_type="screenshot"), "artifact_type"),
    (ev(source="a_friend"), "source"),
    (ev(collection_date="2026-12-01"), "collection_date: is after"),
    (ev(collection_date="2026-10-05"), "reviewed_on: is before"),
    (ev(review={"reviewer": "A", "reviewed_on": "2026-10-01", "relevant": True}), "in_scope"),
    (ev(claim_id="C9"), "does not match any claim"),
    (ev(collection_date="last spring"), "not a YYYY-MM-DD date"),
])
def test_invalid_evidence_rejected(bad, expected):
    with pytest.raises(EvidenceInputError) as exc:
        validate(CLAIMS, [bad], AS_OF)
    assert any(expected in p for p in exc.value.problems)


def test_duplicate_evidence_id_rejected():
    with pytest.raises(EvidenceInputError):
        validate(CLAIMS, [ev(), ev()], AS_OF)


def test_evaluation_date_must_be_a_date():
    with pytest.raises(EvidenceInputError):
        validate(CLAIMS, [ev()], "2026-10-14")


def test_same_input_same_output_and_input_unchanged():
    evidence = [ev(), ev(evidence_id="E2", review=None)]
    snapshot = copy.deepcopy(evidence)
    assert validate(CLAIMS, evidence, AS_OF) == validate(CLAIMS, evidence, AS_OF)
    assert evidence == snapshot


def test_result_records_policy_version_and_date():
    v = validate(CLAIMS, [ev()], AS_OF)
    assert v["evidence_policy_version"] == "0.1.0" and v["as_of"] == "2026-10-14"


def test_derived_status_changes_engine_confidence():
    base = {"data_sensitivity": "internal", "integration_permissions": "read_only", "ai_use": "none",
            "model_training_on_customer_data": "no", "external_exposure": "internal_only",
            "retention_deletion": "documented"}
    verified = validate(CLAIMS, [ev()], AS_OF)["claims"]
    vendor = validate(CLAIMS, [ev(source="vendor", artifact_type="vendor_statement")], AS_OF)["claims"]
    assert evaluate({**base, "claims": verified})["evidence_confidence"]["level"] == "high"
    assert evaluate({**base, "claims": vendor})["evidence_confidence"]["level"] == "medium"
    