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
        "decisions_affecting_people": "no",
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
    assert r["escalations"][0]["assessment_type"] == "Data-classification review"
    assert len(r["missing_information"]) == 6


def test_single_unknown_adds_no_points_and_is_listed():
    r = evaluate(make(external_exposure="unknown"))
    assert r["inherent"]["score"] == 20
    assert r["inherent"]["provisional"] is True and r["inherent"]["tier"] == "undetermined"
    assert r["missing_information"] == ["external_exposure"]
    assert r["escalations"] == [] and r["review_path"] == "standard_review"


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
    assert r["escalations"][0]["assessment_type"] == "Retention and deletion review"
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
    assert evaluate(make())["rule_set_version"] == RULES["rule_set_version"] == "0.3.0"


ESCALATION_DETAIL_FIELDS = ("assessment_type", "owner_role", "required_output", "next_step")


def test_every_escalation_rule_defines_the_follow_up_assessment():
    seen = set()
    for rule in RULES["escalation_rules"]:
        assert rule["rule_id"] not in seen
        seen.add(rule["rule_id"])
        for field in ESCALATION_DETAIL_FIELDS:
            assert isinstance(rule[field], str) and rule[field].strip()


def test_fired_escalation_carries_the_configured_assessment():
    r = evaluate(make(data_sensitivity="restricted", integration_permissions="admin"))
    assert rule_ids(r) == ["ESC-001"]
    configured = next(rule for rule in RULES["escalation_rules"] if rule["rule_id"] == "ESC-001")
    fired = r["escalations"][0]
    assert fired["reason"] == configured["description"]
    for field in ESCALATION_DETAIL_FIELDS:
        assert fired[field] == configured[field]


def test_escalation_rule_without_required_output_is_rejected():
    rules = copy.deepcopy(RULES)
    del rules["escalation_rules"][0]["required_output"]
    with pytest.raises(ValueError, match="ESC-001: required_output"):
        evaluate(make(), rules)


def test_blank_escalation_owner_is_rejected():
    rules = copy.deepcopy(RULES)
    rules["escalation_rules"][1]["owner_role"] = "  "
    with pytest.raises(ValueError, match="ESC-002: owner_role"):
        evaluate(make(), rules)


def test_public_faq_with_blank_ai_use_does_not_escalate():
    """Public customer FAQ, no integration, AI use left blank. Provisional, not an AI impact assessment."""
    r = evaluate(make(data_sensitivity="public", integration_permissions="none", ai_use="unknown",
                      external_exposure="customer_facing"))
    assert r["inherent"]["score"] == 5
    assert r["inherent"]["provisional"] is True and r["inherent"]["tier"] == "undetermined"
    assert r["evidence_confidence"]["level"] == "high"
    assert r["escalations"] == [] and r["review_path"] == "standard_review"


def test_internal_tool_with_unknown_permissions_does_not_escalate():
    """Internal handbook, permissions not yet confirmed, no AI. The hidden worst case is still moderate."""
    r = evaluate(make(data_sensitivity="internal", integration_permissions="unknown", ai_use="none"))
    assert r["inherent"]["score"] == 10
    assert r["inherent"]["provisional"] is True and r["missing_information"] == ["integration_permissions"]
    assert r["escalations"] == [] and r["review_path"] == "standard_review"


def test_restricted_archive_with_read_only_access_does_not_escalate():
    r = evaluate(make(data_sensitivity="restricted", integration_permissions="read_only", ai_use="none"))
    assert r["inherent"]["score"] == 45 and r["inherent"]["tier"] == "moderate"
    assert r["residual"]["tier"] == "low"
    assert r["escalations"] == [] and r["review_path"] == "standard_review"


def test_restricted_data_with_no_integration_does_not_escalate():
    r = evaluate(make(data_sensitivity="restricted", integration_permissions="none", ai_use="none"))
    assert r["inherent"]["score"] == 35 and r["inherent"]["tier"] == "moderate"
    assert r["escalations"] == [] and r["review_path"] == "standard_review"


def test_assistive_ai_not_used_for_training_does_not_escalate():
    r = evaluate(make(data_sensitivity="confidential", integration_permissions="read_only",
                      ai_use="assistive", model_training_on_customer_data="no"))
    assert r["inherent"]["score"] == 45 and r["inherent"]["tier"] == "moderate"
    assert r["residual"]["tier"] == "low"
    assert r["escalations"] == [] and r["review_path"] == "standard_review"


def test_confidential_read_write_workspace_without_ai_does_not_escalate():
    r = evaluate(make(data_sensitivity="confidential", integration_permissions="read_write", ai_use="none"))
    assert r["inherent"]["score"] == 45 and r["inherent"]["tier"] == "moderate"
    assert r["escalations"] == [] and r["review_path"] == "standard_review"


def test_unknown_data_sensitivity_still_opens_classification():
    r = evaluate(make(data_sensitivity="unknown"))
    assert r["inherent"]["score"] == 10
    assert r["inherent"]["tier"] == "undetermined"
    assert rule_ids(r) == ["ESC-005"]
    assert r["escalations"][0]["owner_role"] == "Business owner"
    assert r["review_path"] == "escalated_review"


def test_unknown_training_on_sensitive_ai_use_still_escalates():
    r = evaluate(make(data_sensitivity="confidential", ai_use="assistive",
                      model_training_on_customer_data="unknown"))
    assert r["inherent"]["provisional"] is True
    assert rule_ids(r) == ["ESC-004"]
    assert r["escalations"][0]["assessment_type"] == "Model-training assessment"


def test_unknown_permissions_and_retention_open_separate_reviews():
    r = evaluate(make(data_sensitivity="restricted", integration_permissions="unknown",
                      retention_deletion="undocumented"))
    assert rule_ids(r) == ["ESC-006", "ESC-007"]
    assert [item["assessment_type"] for item in r["escalations"]] == [
        "Retention and deletion review", "Integration access review",
    ]


@pytest.mark.parametrize("data_sensitivity, field, expected", [
    ("public", "ai_use", []),
    ("internal", "ai_use", []),
    ("confidential", "ai_use", ["ESC-008"]),
    ("restricted", "ai_use", ["ESC-008"]),
    ("public", "integration_permissions", []),
    ("internal", "integration_permissions", []),
    ("confidential", "integration_permissions", ["ESC-007"]),
    ("restricted", "integration_permissions", ["ESC-007"]),
])
def test_unknown_permissions_or_ai_escalate_only_with_sensitive_data(data_sensitivity, field, expected):
    r = evaluate(make(**{field: "unknown", "data_sensitivity": data_sensitivity}))
    assert r["inherent"]["provisional"] is True and r["inherent"]["tier"] == "undetermined"
    assert rule_ids(r) == expected
    assert r["review_path"] == ("escalated_review" if expected else "standard_review")


def test_engine_never_returns_an_approval():
    for a in (make(), make(data_sensitivity="restricted", integration_permissions="admin")):
        r = evaluate(a)
        assert r["review_path"] in {"standard_review", "escalated_review"}
        assert "approv" not in json.dumps(r).lower()
        