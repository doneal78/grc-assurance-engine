"""End-to-end business logic checks for synthetic demo scenarios."""

import copy

import pytest

from app.services.scenario_runner import ScenarioNotFoundError, list_scenarios, run_scenario


def test_scenarios_are_labeled_synthetic_and_have_expected_count():
    scenarios = list_scenarios()
    assert len(scenarios) == 5
    assert all(item["synthetic_data"] for item in scenarios)


def test_evidence_supported_scenario_has_verified_evidence_and_draft_mappings():
    result = run_scenario("evidence-supported")
    assert result["risk"]["inherent"]["tier"] == "low"
    assert result["risk"]["evidence_confidence"]["level"] == "high"
    assert all(claim["evidence_status"] == "verified" for claim in result["claims"])
    assert {item["control_id"] for item in result["mappings"]} == {"AC-6", "IA-2", "SC-8"}
    assert all(item["review_status"] == "draft" for item in result["mappings"])
    assert result["risk"]["review_path"] == "standard_review"
    clause = result["risk"]["policy"]["required_contract_clauses"][0]
    assert clause["clause_id"] == "CC-001" and clause["evidence_status"] == "verified"
    assert clause["evidence"][0]["evidence_id"] == "E-CC-001"
    assert result["evidence_policy_version"] == "0.2.0"
    assert result["risk"]["policy"]["clause_evidence_policy_version"] == "0.2.0"


def test_high_risk_ai_scenario_is_escalated_and_missing_is_not_failure():
    result = run_scenario("high-risk-ai")
    assert result["risk"]["inherent"]["tier"] == "undetermined"
    assert result["risk"]["inherent"]["provisional"] is True
    assert result["risk"]["inherent"]["score"] == 90
    assert result["risk"]["review_path"] == "escalated_review"
    assert {claim["evidence_status"] for claim in result["claims"]} == {"missing"}
    fired = result["risk"]["escalations"]
    assert [item["rule_id"] for item in fired] == ["ESC-001", "ESC-002", "ESC-004", "ESC-006"]
    assert all(item["assessment_type"] and item["owner_role"] and item["required_output"] and item["next_step"]
               for item in fired)
    assert all(not claim["evidence"] for claim in result["claims"])
    clause = result["risk"]["policy"]["required_contract_clauses"][0]
    assert clause["evidence_status"] == "missing"
    assert clause["status_reason"] == "No evidence provided."


def test_conflicting_scenario_retains_conflict_and_escalates():
    result = run_scenario("conflicting-claims")
    permission_claim = next(item for item in result["claims"] if item["claim_id"] == "C-PERM")
    assert permission_claim["evidence_status"] == "conflicting"
    assert {item["status"] for item in permission_claim["evidence"]} == {"self_attested", "conflicting"}
    assert result["risk"]["review_path"] == "escalated_review"
    assert any(item["rule_id"] == "ESC-003" for item in result["risk"]["escalations"])


def test_contract_clause_conflict_is_visible_and_does_not_change_the_score():
    from app.services.risk_engine import evaluate

    result = run_scenario("contract-clause-conflict")
    clause = result["risk"]["policy"]["required_contract_clauses"][0]
    assert clause["enforced"] is True
    assert clause["evidence_status"] == "conflicting"
    assert {item["status"] for item in clause["evidence"]} == {"self_attested", "conflicting"}
    assert result["risk"]["inherent"]["score"] == 30
    assert result["risk"]["inherent"]["tier"] == "moderate"
    assert result["risk"]["residual"]["tier"] == "low"
    assert result["risk"]["escalations"] == []
    assert result["risk"]["review_path"] == "standard_review"
    assert result["risk"]["policy_outcome"]["status"] == "not_prohibited"
    bare = evaluate({**result["assessment_inputs"], "claims": result["claims"]})
    assert bare["inherent"] == result["risk"]["inherent"]
    assert bare["residual"] == result["risk"]["residual"]
    assert bare["escalations"] == result["risk"]["escalations"]
    assert bare["review_path"] == result["risk"]["review_path"]


def test_scenario_results_are_repeatable_and_fixtures_are_not_mutated():
    from app.services.scenario_runner import load_scenarios

    fixtures = load_scenarios()
    before = copy.deepcopy(fixtures)
    assert run_scenario("conflicting-claims", fixtures) == run_scenario("conflicting-claims", fixtures)
    assert fixtures == before


def test_unknown_scenario_raises_domain_error():
    with pytest.raises(ScenarioNotFoundError):
        run_scenario("not-a-scenario")
