"""Org-policy checks on the risk engine. Scoring stays separate from prohibition."""

import copy

import pytest

from app.services.org_policy import load_org_policy
from app.services.risk_engine import RiskInputError, evaluate


def make(**overrides):
    assessment = {
        "data_sensitivity": "internal",
        "integration_permissions": "read_only",
        "ai_use": "assistive",
        "model_training_on_customer_data": "no",
        "external_exposure": "internal_only",
        "retention_deletion": "documented",
        "decisions_affecting_people": "no",
        "claims": [{"claim_id": "C1", "statement": "MFA is enforced", "evidence_status": "verified"}],
    }
    assessment.update(overrides)
    return assessment


def test_starter_policy_is_one_restriction_and_one_clause():
    policy = load_org_policy()
    assert [item["restriction_id"] for item in policy["hard_restrictions"]] == ["HR-001"]
    assert [item["clause_id"] for item in policy["required_contract_clauses"]] == ["CC-001"]
    restriction = policy["hard_restrictions"][0]
    assert "fully automated" in restriction["description"]
    assert "no human reviews the decision" in restriction["description"]
    assert "eligibility" in restriction["description"] and "safety" in restriction["description"]
    clause = policy["required_contract_clauses"][0]
    assert clause["enforced"] is True
    assert "company or customer data" in clause["text"]
    assert len(policy["intake_fields"]) == 1


def test_every_result_carries_the_policy_reference_and_lists_clauses():
    result = evaluate(make())
    assert result["policy"]["policy_id"] == "ORG-AI-USE"
    assert result["policy"]["policy_version"] == "1.1.0"
    assert result["policy"]["status"] == "illustrative"
    clauses = result["policy"]["required_contract_clauses"]
    assert [clause["clause_id"] for clause in clauses] == ["CC-001"]
    assert all(clause["enforced"] is True for clause in clauses)
    assert all(clause["evidence_status"] == "missing" for clause in clauses)
    assert all(clause["status_reason"] == "No evidence provided." for clause in clauses)
    assert result["policy_outcome"]["status"] == "not_prohibited"
    assert result["policy_outcome"]["restrictions"] == []
    assert result["policy_outcome"]["answers"][0]["value"] == "no"


def test_prohibition_cites_the_restriction_and_does_not_change_the_score():
    allowed = evaluate(make(decisions_affecting_people="no"))
    blocked = evaluate(make(decisions_affecting_people="yes"))
    assert allowed["inherent"] == blocked["inherent"]
    assert allowed["residual"] == blocked["residual"]
    assert allowed["escalations"] == blocked["escalations"] == []
    assert allowed["inherent"]["score"] == 30 and allowed["inherent"]["tier"] == "moderate"
    assert allowed["residual"]["tier"] == "low"
    assert allowed["review_path"] == "standard_review"
    assert blocked["review_path"] == "escalated_review"
    assert blocked["policy_outcome"]["status"] == "prohibited"
    match = blocked["policy_outcome"]["restrictions"][0]
    assert match["restriction_id"] == "HR-001"
    assert match["policy_id"] == blocked["policy"]["policy_id"]
    assert match["policy_version"] == blocked["policy"]["policy_version"] == "1.1.0"
    assert match["observed_value"] == "yes"
    assert "approv" not in str(blocked).lower()


def test_yes_matches_even_when_ai_use_is_none():
    result = evaluate(make(ai_use="none", decisions_affecting_people="yes"))
    assert result["policy_outcome"]["status"] == "prohibited"
    assert all(factor["factor"] != "model_training_on_customer_data" for factor in result["inherent"]["factors"])


def test_unknown_is_not_prohibited_and_opens_esc_009():
    result = evaluate(make(decisions_affecting_people="unknown"))
    assert result["policy_outcome"]["status"] == "not_prohibited"
    assert result["policy_outcome"]["restrictions"] == []
    assert result["missing_information"] == ["decisions_affecting_people"]
    assert result["inherent"]["provisional"] is True
    assert result["inherent"]["tier"] == "undetermined"
    assert [item["rule_id"] for item in result["escalations"]] == ["ESC-009"]
    assert result["escalations"][0]["assessment_type"] == "Affected-decision determination"
    assert result["review_path"] == "escalated_review"


def test_contract_clause_is_missing_without_evidence_and_training_still_scores():
    result = evaluate(make(model_training_on_customer_data="yes"))
    assert result["policy_outcome"]["status"] == "not_prohibited"
    clause = result["policy"]["required_contract_clauses"][0]
    assert clause["enforced"] is True
    assert clause["evidence_status"] == "missing"
    training = next(factor for factor in result["inherent"]["factors"] if factor["rule_id"] == "INH-TRAIN")
    assert training["points"] == 10
    assert [item["rule_id"] for item in result["escalations"]] == []


def test_same_policy_input_is_repeatable():
    assessment = make(decisions_affecting_people="yes")
    assert evaluate(assessment) == evaluate(assessment)


def test_invalid_and_missing_policy_answers_are_rejected():
    with pytest.raises(RiskInputError) as invalid:
        evaluate(make(decisions_affecting_people="sometimes"))
    assert any(problem.startswith("decisions_affecting_people") for problem in invalid.value.problems)
    assessment = make()
    del assessment["decisions_affecting_people"]
    with pytest.raises(RiskInputError) as missing:
        evaluate(assessment)
    assert "decisions_affecting_people: required field is missing" in missing.value.problems


def test_policy_cannot_treat_unknown_as_prohibited():
    policy = copy.deepcopy(load_org_policy())
    policy["hard_restrictions"][0]["prohibited_when"] = ["unknown"]
    with pytest.raises(ValueError, match="unknown cannot be a prohibited value"):
        evaluate(make(), policy=policy)


def test_clause_marked_not_enforced_is_rejected():
    policy = copy.deepcopy(load_org_policy())
    policy["required_contract_clauses"][0]["enforced"] = False
    with pytest.raises(ValueError, match="enforced must be true"):
        evaluate(make(), policy=policy)


def test_a_second_configured_restriction_is_cited_without_changing_points():
    policy = copy.deepcopy(load_org_policy())
    policy["hard_restrictions"].append({
        "restriction_id": "HR-002",
        "title": "Second illustrative restriction",
        "description": "Also matches a yes answer for this test.",
        "field": "decisions_affecting_people",
        "prohibited_when": ["yes"],
        "owner_role": "GRC analyst",
        "required_output": "A recorded disposition.",
        "next_step": "Record the disposition on the risk register.",
    })
    allowed = evaluate(make(), policy=policy)
    blocked = evaluate(make(decisions_affecting_people="yes"), policy=policy)
    assert allowed["inherent"] == blocked["inherent"]
    assert [item["restriction_id"] for item in blocked["policy_outcome"]["restrictions"]] == ["HR-001", "HR-002"]
    assert blocked["policy_outcome"]["status"] == "prohibited"


def test_a_second_required_clause_is_checked_without_changing_points():
    policy = copy.deepcopy(load_org_policy())
    policy["required_contract_clauses"].append({
        "clause_id": "CC-002",
        "title": "Second illustrative clause",
        "text": "The vendor must delete company data on request.",
        "enforced": True,
    })
    bare = evaluate(make(), policy=policy)
    checked = evaluate(make(), policy=policy, clause_check={
        "evidence_policy_version": "0.2.0",
        "as_of": "2026-10-14",
        "clauses": [
            {"clause_id": "CC-001", "evidence_status": "self_attested",
             "status_reason": "Best usable evidence status is self_attested.", "evidence": []},
            {"clause_id": "CC-002", "evidence_status": "missing",
             "status_reason": "No evidence provided.", "evidence": []},
        ],
    })
    assert bare["inherent"] == checked["inherent"]
    assert [item["clause_id"] for item in checked["policy"]["required_contract_clauses"]] == ["CC-001", "CC-002"]
    assert [item["evidence_status"] for item in checked["policy"]["required_contract_clauses"]] == [
        "self_attested", "missing"]
    assert checked["policy"]["required_contract_clauses"][1]["text"].startswith("The vendor must delete")


def test_duplicate_clause_id_is_rejected():
    policy = copy.deepcopy(load_org_policy())
    policy["required_contract_clauses"].append(dict(policy["required_contract_clauses"][0]))
    with pytest.raises(ValueError, match="CC-001 is duplicated"):
        evaluate(make(), policy=policy)


def test_clause_check_must_cover_every_required_clause():
    with pytest.raises(ValueError, match="unknown clause"):
        evaluate(make(), clause_check={"clauses": [
            {"clause_id": "CC-001", "evidence_status": "verified", "status_reason": "Checked.", "evidence": []},
            {"clause_id": "CC-009", "evidence_status": "missing", "status_reason": "No evidence provided.",
             "evidence": []},
        ]})
