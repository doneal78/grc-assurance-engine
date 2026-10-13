"""Phase 2 tests for the rules-based risk engine (see docs/risk-model.md)."""

import copy
import json

import pytest

from app.services.risk_engine import RiskInputError, _tier_for, evaluate, load_rules

RULES = load_rules()


def make(**overrides):
    """A lower-risk baseline assessment. Tests override only what they need."""
    assessment = {
        "data_sensitivity": "internal",
        "integration_permissions": "read_only",
        "ai_use": "none",
        "model_training_on_customer_data": "no",
        "external_exposure": "internal_only",
        "retention_deletion": "documented",
        "claims": [
            {"claim_id": "C1", "statement": "MFA is enforced", "evidence_status": "verified"},
            {"claim_id": "C2", "statement": "Data is encrypted at rest", "evidence_status": "verified"},
        ],
    }
    assessment.update(overrides)
    return assessment


def rule_ids(result):
    return [e["rule_id"] for e in result["escalations"]]


def test_lower_risk_case():
    r = evaluate(make())
    assert r["inherent"]["score"] == 20 and r["inherent"]["tier"] == "low"
    assert r["inherent"]["provisional"] is False
    assert r["evidence_confidence"]["level"] == "high"
    assert r["residual"]["tier"] == "low"
    assert r["escalations"] == [] and r["review_path"] == "standard_review"


def test_high_risk_case_escalates():
    r = evaluate(make(data_sensitivity="restricted", integration_permissions="admin",
                      ai_use="assistive", external_exposure="customer_facing"))
    assert r["inherent"]["score"] == 80 and r["inherent"]["tier"] == "critical"
    assert rule_ids(r) == ["ESC-001"]
    assert r["residual"]["tier"] == "critical"
    assert r["review_path"] == "escalated_review"


def test_all_unknown_is_undetermined_not_low():
    r = evaluate(make(data_sensitivity="unknown", integration_permissions="unknown", ai_use="unknown",
                      model_training_on_customer_data="unknown", external_exposure="unknown",
                      retention_deletion="unknown", claims=[]))
    assert r["inherent"]["score"] == 0
    assert r["inherent"]["tier"] == "undetermined" and r["inherent"]["provisional"] is True
    assert r["residual"]["tier"] == "undetermined"
    assert r["evidence_confidence"]["level"] == "none"
    assert rule_ids(r) == ["ESC-005"] and r["review_path"] == "escalated_review"
    assert len(r["missing_information"]) == 6


def test_single_unknown_adds_no_points_and_is_listed():
    r = evaluate(make(external_exposure="unknown"))
    assert r["inherent"]["score"] == 20
    assert r["inherent"]["provisional"] is True and r["inherent"]["tier"] == "undetermined"
    assert r["missing_information"] == ["external_exposure"]


def test_conflicting_claim_escalates_and_is_preserved():
    claim = {"claim_id": "C1", "statement": "Integration access is read-only", "evidence_status": "conflicting"}
    r = evaluate(make(data_sensitivity="confidential", integration_permissions="admin", claims=[claim]))
    assert r["inherent"]["score"] == 55 and r["inherent"]["tier"] == "high"
    assert r["evidence_confidence"]["level"] == "low"
    assert r["residual"]["tier"] == "high"
    assert rule_ids(r) == ["ESC-003"]
    assert r["conflicts"][0]["statement"] == "Integration access is read-only"


def test_low_score_cannot_bypass_mandatory_escalation():
    r = evaluate(make(data_sensitivity="confidential", integration_permissions="none",
                      retention_deletion="undocumented"))
    assert r["inherent"]["tier"] == "low"
    assert rule_ids(r) == ["ESC-006"]
    assert r["review_path"] == "escalated_review"
    assert r["residual"]["reason"].startswith("Not lowered")


def test_residual_lowered_by_one_tier_at_most():
    r = evaluate(make(data_sensitivity="restricted", ai_use="assistive", external_exposure="customer_facing"))
    assert r["inherent"]["score"] == 60 and r["inherent"]["tier"] == "high"
    assert r["escalations"] == []
    assert r["residual"]["tier"] == "moderate"


def test_moderate_lowered_to_low_with_high_confidence():
    r = evaluate(make(data_sensitivity="confidential", integration_permissions="read_write",
                      external_exposure="customer_facing"))
    assert r["inherent"]["tier"] == "moderate"
    assert r["residual"]["tier"] == "low"


def test_self_attestation_is_not_high_confidence():
    claims = [{"claim_id": f"C{i}", "statement": "Vendor says so", "evidence_status": "self_attested"} for i in (1, 2)]
    r = evaluate(make(data_sensitivity="confidential", integration_permissions="read_write", claims=claims))
    assert r["evidence_confidence"]["level"] == "medium"
    assert r["residual"]["tier"] == r["inherent"]["tier"] == "moderate"


def test_tier_boundaries():
    for score, expected in [(0, "low"), (29, "low"), (30, "moderate"), (54, "moderate"),
                            (55, "high"), (74, "high"), (75, "critical"), (100, "critical")]:
        assert _tier_for(score, RULES) == expected
    with pytest.raises(ValueError):
        _tier_for(101, RULES)


def test_input_at_exact_boundary_scores_moderate():
    r = evaluate(make(integration_permissions="read_write"))
    assert r["inherent"]["score"] == 30 and r["inherent"]["tier"] == "moderate"


def test_invalid_value_rejected():
    with pytest.raises(RiskInputError) as exc:
        evaluate(make(data_sensitivity="secret"))
    assert any(p.startswith("data_sensitivity") for p in exc.value.problems)


def test_missing_field_rejected():
    a = make()
    del a["ai_use"]
    with pytest.raises(RiskInputError) as exc:
        evaluate(a)
    assert "ai_use: required field is missing" in exc.value.problems


def test_invalid_claim_status_rejected():
    claim = {"claim_id": "C1", "statement": "Trust us", "evidence_status": "trust_me"}
    with pytest.raises(RiskInputError):
        evaluate(make(claims=[claim]))


def test_same_input_same_output_and_input_unchanged():
    a = make(data_sensitivity="restricted", integration_permissions="admin")
    snapshot = copy.deepcopy(a)
    assert evaluate(a) == evaluate(a)
    assert a == snapshot


def test_result_records_rule_set_version():
    assert evaluate(make())["rule_set_version"] == "0.1.0"


def test_engine_never_returns_an_approval():
    for a in (make(), make(data_sensitivity="restricted", integration_permissions="admin")):
        r = evaluate(a)
        assert r["review_path"] in {"standard_review", "escalated_review"}
        assert "approv" not in json.dumps(r).lower()
        