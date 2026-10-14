"""Reproducible modeled labor-capacity calculations."""

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

DEFAULT_ASSUMPTIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "cost_assumptions.json"
REQUIRED_NUMERIC = (
    "assessments_per_month", "baseline_handling_hours_per_assessment",
    "assisted_handling_hours_per_assessment", "review_hours_per_assessment",
    "monthly_maintenance_hours", "loaded_hourly_labor_rate",
)


class CostInputError(ValueError):
    """Raised when modeled cost assumptions are invalid."""


def load_assumptions(path=DEFAULT_ASSUMPTIONS_PATH):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def calculate_cost(assumptions=None):
    """Calculate gross/net labor capacity; never characterize it as cash savings."""
    assumptions = assumptions if assumptions is not None else load_assumptions()
    problems = []
    values = {}
    for field in REQUIRED_NUMERIC:
        try:
            value = Decimal(str(assumptions[field]))
        except (KeyError, InvalidOperation, TypeError, ValueError):
            problems.append(f"{field}: must be a non-negative number")
            continue
        if not value.is_finite() or value < 0:
            problems.append(f"{field}: must be a non-negative number")
        else:
            values[field] = value
    if "assessments_per_month" in values and values["assessments_per_month"] != values["assessments_per_month"].to_integral_value():
        problems.append("assessments_per_month: must be a whole number")
    if problems:
        raise CostInputError("; ".join(problems))

    volume = values["assessments_per_month"]
    avoided_per_assessment = (values["baseline_handling_hours_per_assessment"]
                              - values["assisted_handling_hours_per_assessment"])
    gross_hours = volume * avoided_per_assessment
    review_hours = volume * values["review_hours_per_assessment"]
    maintenance_hours = values["monthly_maintenance_hours"]
    net_hours = gross_hours - review_hours - maintenance_hours
    rate = values["loaded_hourly_labor_rate"]

    def rounded(value):
        return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    return {
        "model_version": assumptions.get("model_version", "unspecified"),
        "status": assumptions.get("status", "modeled"),
        "source_note": assumptions.get("source_note", ""),
        "assumptions": {key: float(value) for key, value in values.items()},
        "gross_capacity_hours": rounded(gross_hours),
        "review_effort_hours": rounded(review_hours),
        "maintenance_hours": rounded(maintenance_hours),
        "net_capacity_hours": rounded(net_hours),
        "gross_capacity_value": rounded(gross_hours * rate),
        "net_capacity_value": rounded(net_hours * rate),
        "cash_savings": None,
        "one_time_development_cost": assumptions.get("one_time_development_cost"),
    }
