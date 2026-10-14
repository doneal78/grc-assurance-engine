"""End-to-end business logic checks for synthetic demo scenarios."""

import copy

import pytest

from app.services.scenario_runner import ScenarioNotFoundError, list_scenarios, run_scenario


def test_scenarios_are_labeled_synthetic_and_have_expected_count():
    scenarios = list_scenarios()
    assert len(scenarios) == 3
    assert all(item["synthetic_data"] for item in scenarios)


def test_evidence_supported_scenario_has_verified_evidence_and_draft_mappings():
    result = run_scenario("evidence-supported")
    assert result["risk"]["inherent"]["tier"] == "low"
    assert result["risk"]["evidence_confidence"]["level"] == "high"
    assert all(claim["evidence_status"] == "verified" for claim in result["claims"])
    assert {item["control_id"] for item in result["mappings"]} == {"AC-6", "IA-2", "SC-8"}
    assert all(item["review_status"] == "draft" for item in result["mappings"])
    assert result["risk"]["review_path"] == "standard_review"


def test_high_risk_ai_scenario_is_escalated_and_missing_is_not_failure():
    result = run_scenario("high-risk-ai")
    assert result["risk"]["inherent"]["tier"] == "undetermined"
    assert result["risk"]["inherent"]["provisional"] is True
    assert result["risk"]["inherent"]["score"] == 90
    assert result["risk"]["review_path"] == "escalated_review"
    assert {claim["evidence_status"] for claim in result["claims"]} == {"missing"}
    assert any("ESC-001" == item["rule_id"] for item in result["risk"]["escalations"])
    assert all(not claim["evidence"] for claim in result["claims"])


def test_conflicting_scenario_retains_conflict_and_escalates():
    result = run_scenario("conflicting-claims")
    permission_claim = next(item for item in result["claims"] if item["claim_id"] == "C-PERM")
    assert permission_claim["evidence_status"] == "conflicting"
    assert {item["status"] for item in permission_claim["evidence"]} == {"self_attested", "conflicting"}
    assert result["risk"]["review_path"] == "escalated_review"
    assert any(item["rule_id"] == "ESC-003" for item in result["risk"]["escalations"])


def test_scenario_results_are_repeatable_and_fixtures_are_not_mutated():
    from app.services.scenario_runner import load_scenarios

    fixtures = load_scenarios()
    before = copy.deepcopy(fixtures)
    assert run_scenario("conflicting-claims", fixtures) == run_scenario("conflicting-claims", fixtures)
    assert fixtures == before


def test_unknown_scenario_raises_domain_error():
    with pytest.raises(ScenarioNotFoundError):
        run_scenario("not-a-scenario")
