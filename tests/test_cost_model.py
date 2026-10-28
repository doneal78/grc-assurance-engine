"""Tests for reproducible cost-of-assurance calculations."""

import copy

import pytest

from app.services.cost_model import CostInputError, calculate_cost, load_assumptions


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
    result = calculate_cost()
    assert result["net_capacity_value"] == 180
    assert result["gross_capacity_value"] == 600
    assert result["cash_savings"] is None
    assert "handling_minutes" not in result
    assert "rework_minutes" not in result
    assert "manual_touches" not in result
    assert "handoffs" not in result
    assumptions = load_assumptions()
    assert "rework_minutes" not in assumptions
    assert "handling_minutes" not in assumptions
    assert "manual_touches" not in assumptions
    assert "handoffs" not in assumptions


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
