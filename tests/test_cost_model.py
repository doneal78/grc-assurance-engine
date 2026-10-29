"""Tests for reproducible cost-of-assurance calculations."""

import copy

import pytest

from app.services.cost_model import CostInputError, calculate_cost, load_assumptions


def test_cost_model_doc_keeps_authenticated_effort_beside_cash_savings():
    from pathlib import Path

    text = Path("docs/cost-model.md").read_text(encoding="utf-8")
    assert "| Authenticated effort | `decisions.authenticated_effort_minutes`" in text
    assert "| Cash savings | `decisions.cash_savings_dollars`" in text
    assert "The formula reports no cash savings." in text
    assert "The model reports no cash savings." not in text


def test_documented_assumptions_reproduce_capacity_value():
    result = calculate_cost()
    assert result["gross_capacity_hours"] == 10
    assert result["review_effort_hours"] == 5
    assert result["maintenance_hours"] == 2
    assert result["net_capacity_hours"] == 3
    assert result["gross_capacity_value"] == 600
    assert result["net_capacity_value"] == 180
    assert result["cash_savings"] is None
    assert result["one_time_development_cost"] is None


def test_calculation_is_repeatable_and_does_not_mutate_assumptions():
    assumptions = load_assumptions()
    before = copy.deepcopy(assumptions)
    assert calculate_cost(assumptions) == calculate_cost(assumptions)
    assert assumptions == before


def test_cost_formula_does_not_read_handling_minutes():
    from app.services.cost_model import REQUIRED_NUMERIC

    assert "handling_minutes" not in REQUIRED_NUMERIC
    assert "rework_minutes" not in REQUIRED_NUMERIC
    assert "manual_touches" not in REQUIRED_NUMERIC
    assert "handoffs" not in REQUIRED_NUMERIC
    assert "monthly_assessment_rate" not in REQUIRED_NUMERIC
    assert "authenticated_effort_minutes" not in REQUIRED_NUMERIC
    assert "cash_savings_dollars" not in REQUIRED_NUMERIC
    assert "incident_cost" not in REQUIRED_NUMERIC
    assert "avoided_incident_count" not in REQUIRED_NUMERIC
    assert "avoided_incident_value" not in REQUIRED_NUMERIC
    assert "decided_at" not in REQUIRED_NUMERIC
    result = calculate_cost()
    assert result["net_capacity_value"] == 180
    assert result["gross_capacity_value"] == 600
    assert result["cash_savings"] is None
    assert "handling_minutes" not in result
    assert "rework_minutes" not in result
    assert "manual_touches" not in result
    assert "handoffs" not in result
    assert "monthly_assessment_rate" not in result
    assert "authenticated_effort_minutes" not in result
    assert "cash_savings_dollars" not in result
    assert "incident_cost" not in result
    assert "avoided_incident_count" not in result
    assert "avoided_incident_value" not in result
    assumptions = load_assumptions()
    assert assumptions["assessments_per_month"] == 20
    assert "rework_minutes" not in assumptions
    assert "handling_minutes" not in assumptions
    assert "manual_touches" not in assumptions
    assert "handoffs" not in assumptions
    assert "monthly_assessment_rate" not in assumptions
    assert "authenticated_effort_minutes" not in assumptions
    assert "cash_savings_dollars" not in assumptions
    assert assumptions["cash_savings"] is None
    assert assumptions["incident_cost"] is None
    assert assumptions["avoided_incident_count"] is None
    assert "decided_at" not in assumptions


def test_negative_net_capacity_is_reported_when_assisted_effort_is_higher():
    assumptions = load_assumptions()
    assumptions["assisted_handling_hours_per_assessment"] = 3
    assert calculate_cost(assumptions)["net_capacity_hours"] < 0


@pytest.mark.parametrize("field, value", [
    ("assessments_per_month", -1),
    ("assessments_per_month", 1.5),
    ("baseline_handling_hours_per_assessment", "many"),
    ("loaded_hourly_labor_rate", -10),
])
def test_invalid_assumptions_are_rejected(field, value):
    assumptions = load_assumptions()
    assumptions[field] = value
    with pytest.raises(CostInputError):
        calculate_cost(assumptions)


def test_default_avoided_incident_value_is_not_measured():
    from app.services.cost_model import avoided_incident_value

    assumptions = load_assumptions()
    before = copy.deepcopy(assumptions)
    result = avoided_incident_value()
    again = avoided_incident_value(assumptions)
    assert assumptions == before
    assert result == again
    assert result["kind"] == "modeled_assumption"
    assert result["measured"] is False
    assert result["value"] is None
    assert result["value_label"] is None
    assert result["reason"] == "not_set"
    assert result["incident_cost"] is None
    assert result["avoided_incident_count"] is None
    assert result["feeds_cost_model"] is False
    assert result["feeds_cash_savings"] is False
    assert result["separate_from_cash_savings"] is True
    assert result["separate_from_labor_capacity"] is True
    assert "Not measured" in result["detail"]
    assert "Modeled assumption" in result["detail"]
    assert "not an observed register figure" in result["detail"]
    assert "not cash savings" in result["detail"]
    assert "calculate_cost()" in result["detail"]
    cost = calculate_cost()
    assert cost["cash_savings"] is None
    assert cost["net_capacity_value"] == 180
    assert cost["gross_capacity_value"] == 600
    assert "avoided_incident_value" not in cost


def test_avoided_incident_value_appears_only_when_both_assumptions_are_set():
    from decimal import Decimal

    from app.services.cost_model import avoided_incident_value

    assumptions = load_assumptions()
    assumptions["incident_cost"] = 25000
    assumptions["avoided_incident_count"] = 2
    result = avoided_incident_value(assumptions)
    assert result["measured"] is True
    assert result["value"] == 50000
    assert result["value_label"] == "50,000.00 dollars"
    assert result["reason"] is None
    assert "Modeled assumption" in result["detail"]
    assert "not an observed register figure" in result["detail"]
    assert "not cash savings" in result["detail"]
    assert "not proven risk reduction" in result["detail"]
    cost = calculate_cost(assumptions)
    plain = calculate_cost(load_assumptions())
    assert cost["cash_savings"] is None
    assert cost["net_capacity_value"] == plain["net_capacity_value"] == 180
    assert cost["gross_capacity_value"] == plain["gross_capacity_value"] == 600
    assert cost["assumptions"] == plain["assumptions"]
    assert result["value"] != cost["net_capacity_value"]
    assert result["value"] != cost["gross_capacity_value"]
    assert result["value"] != assumptions["loaded_hourly_labor_rate"] * 60

    partial = load_assumptions()
    partial["incident_cost"] = 100000
    assert avoided_incident_value(partial)["measured"] is False
    assert avoided_incident_value(partial)["value"] is None
    assert avoided_incident_value(partial)["reason"] == "incomplete"
    count_only = load_assumptions()
    count_only["avoided_incident_count"] = 4
    assert avoided_incident_value(count_only)["value"] is None

    zeros = load_assumptions()
    zeros["incident_cost"] = 0
    zeros["avoided_incident_count"] = 0
    zero_result = avoided_incident_value(zeros)
    assert zero_result["measured"] is True
    assert zero_result["value"] == 0
    assert zero_result["value_label"] == "0.00 dollars"

    rounded = load_assumptions()
    rounded["incident_cost"] = Decimal("0.015")
    rounded["avoided_incident_count"] = 2
    assert avoided_incident_value(rounded)["value"] == 0.03
    assert avoided_incident_value(rounded)["value_label"] == "0.03 dollars"


@pytest.mark.parametrize("cost, count", [
    (True, 2),
    ("25000", 2),
    (-1, 2),
    (10, 1.5),
    (10, True),
    (10, "2"),
    (10, -3),
])
def test_unusable_avoided_incident_assumptions_stay_not_measured(cost, count):
    from app.services.cost_model import avoided_incident_value

    assumptions = load_assumptions()
    assumptions["incident_cost"] = cost
    assumptions["avoided_incident_count"] = count
    result = avoided_incident_value(assumptions)
    assert result["measured"] is False
    assert result["value"] is None
    assert result["reason"] == "invalid"
    assert "No value was calculated." in result["detail"]
    assert calculate_cost(assumptions)["cash_savings"] is None
    assert calculate_cost(assumptions)["net_capacity_value"] == 180
