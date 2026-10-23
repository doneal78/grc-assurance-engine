"""Phase 3 tests for the evidence validator (see docs/evidence-model.md)."""

import copy
from datetime import date

import pytest

from app.services.evidence_validator import (
    EvidenceInputError, validate, validate_assessment, validate_contract_clauses,
)
from app.services.org_policy import load_org_policy
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
    assert v["evidence_policy_version"] == "0.2.0" and v["as_of"] == "2026-10-14"


def test_derived_status_changes_engine_confidence():
    base = {"data_sensitivity": "internal", "integration_permissions": "read_only", "ai_use": "none",
            "model_training_on_customer_data": "no", "external_exposure": "internal_only",
            "retention_deletion": "documented", "decisions_affecting_people": "no"}
    verified = validate(CLAIMS, [ev()], AS_OF)["claims"]
    vendor = validate(CLAIMS, [ev(source="vendor", artifact_type="vendor_statement")], AS_OF)["claims"]
    assert evaluate({**base, "claims": verified})["evidence_confidence"]["level"] == "high"
    assert evaluate({**base, "claims": vendor})["evidence_confidence"]["level"] == "medium"


CC001 = load_org_policy()["required_contract_clauses"][0]


def clause_ev(**overrides):
    base = {"evidence_id": "E-CC-001", "claim_id": "CC-001",
            "artifact_name": "Contract excerpt", "artifact_type": "contract_clause",
            "source": "internal_observation", "collection_date": "2026-04-02", "review": review()}
    base.update(overrides)
    return base


def clause_status(evidence):
    return validate_contract_clauses([CC001], evidence, AS_OF)["clauses"][0]


def test_contract_clause_type_is_in_the_evidence_policy():
    from app.services.evidence_validator import load_policy
    policy = load_policy()
    assert policy["evidence_policy_version"] == "0.2.0"
    assert policy["max_age_days"]["contract_clause"] == 365


def test_clause_without_evidence_is_missing():
    clause = clause_status([])
    assert clause["clause_id"] == "CC-001"
    assert clause["enforced"] is True
    assert clause["evidence_status"] == "missing"
    assert clause["status_reason"] == "No evidence provided."
    assert clause["evidence"] == []
    assert "company or customer data" in clause["text"]


def test_reviewed_contract_excerpt_is_verified():
    clause = clause_status([clause_ev()])
    assert clause["evidence_status"] == "verified"
    assert clause["evidence"][0]["evidence_id"] == "E-CC-001"
    assert "Independent" in clause["evidence"][0]["reason"] or "supporting" in clause["evidence"][0]["reason"]


def test_vendor_contract_statement_is_self_attested():
    clause = clause_status([clause_ev(source="vendor", artifact_type="vendor_statement")])
    assert clause["evidence_status"] == "self_attested"


def test_contract_clause_expires_on_its_own_limit():
    current = clause_status([clause_ev(collection_date="2025-10-14")])
    expired = clause_status([clause_ev(collection_date="2025-10-13")])
    assert current["evidence_status"] == "verified"
    assert expired["evidence_status"] == "expired"
    assert "limit for contract_clause is 365" in expired["evidence"][0]["reason"]


def test_contradicting_contract_excerpt_is_conflicting():
    supporting = clause_ev()
    contradicting = clause_ev(evidence_id="E-CC-001-B", collection_date="2026-09-01",
                              review=review(contradicts_claim=True))
    clause = clause_status([supporting, contradicting])
    assert clause["evidence_status"] == "conflicting"
    assert {item["status"] for item in clause["evidence"]} == {"verified", "conflicting"}


def test_clause_status_does_not_change_the_score_or_review_path():
    base = {"data_sensitivity": "internal", "integration_permissions": "read_only", "ai_use": "assistive",
            "model_training_on_customer_data": "no", "external_exposure": "internal_only",
            "retention_deletion": "documented", "decisions_affecting_people": "no",
            "claims": [{"claim_id": "C1", "statement": "MFA is enforced", "evidence_status": "verified"}]}
    missing = evaluate(base)
    verified = evaluate(base, clause_check=validate_contract_clauses([CC001], [clause_ev()], AS_OF))
    conflicting = evaluate(base, clause_check=validate_contract_clauses(
        [CC001], [clause_ev(), clause_ev(evidence_id="E2", review=review(contradicts_claim=True))], AS_OF))
    assert missing["inherent"] == verified["inherent"] == conflicting["inherent"]
    assert missing["residual"] == verified["residual"] == conflicting["residual"]
    assert missing["escalations"] == verified["escalations"] == conflicting["escalations"] == []
    assert missing["review_path"] == verified["review_path"] == conflicting["review_path"] == "standard_review"
    assert missing["evidence_confidence"] == verified["evidence_confidence"]
    assert [item["evidence_status"] for item in missing["policy"]["required_contract_clauses"]] == ["missing"]
    assert verified["policy"]["required_contract_clauses"][0]["evidence_status"] == "verified"
    assert conflicting["policy"]["required_contract_clauses"][0]["evidence_status"] == "conflicting"
    assert verified["policy"]["clause_evidence_policy_version"] == "0.2.0"
    assert verified["policy"]["required_contract_clauses"][0]["enforced"] is True


def test_claim_evidence_is_not_treated_as_clause_evidence():
    checked = validate_assessment(CLAIMS, [ev()], AS_OF, [CC001])
    assert checked["claims"][0]["evidence_status"] == "verified"
    assert checked["clause_check"]["clauses"][0]["evidence_status"] == "missing"


def test_clause_evidence_is_not_rejected_as_an_unknown_claim():
    checked = validate_assessment(CLAIMS, [ev(), clause_ev()], AS_OF, [CC001])
    assert checked["claims"][0]["evidence_status"] == "verified"
    assert checked["clause_check"]["clauses"][0]["evidence_status"] == "verified"
    assert checked["evidence_policy_version"] == "0.2.0"


def test_trust_center_reference_is_copied_and_does_not_change_status():
    plain = claim_result([ev()])
    cited = claim_result([ev(pointer_id="soc2", trust_center_url="https://trust.example.test/acme")])
    assert plain["evidence_status"] == cited["evidence_status"] == "verified"
    assert cited["evidence"][0]["pointer_id"] == "soc2"
    assert cited["evidence"][0]["trust_center_url"] == "https://trust.example.test/acme"
    assert cited["evidence"][0]["artifact_type"] == "soc2_type2_report"
    assert "pointer_id" not in plain["evidence"][0]
    assert "trust_center_url" not in plain["evidence"][0]


def test_clause_id_cannot_collide_with_a_claim_id():
    with pytest.raises(EvidenceInputError, match="collides"):
        validate_assessment([{"claim_id": "CC-001", "statement": "Same id"}], [], AS_OF, [CC001])
    