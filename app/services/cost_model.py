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
    """Calculate gross/net labor capacity; never characterize it as cash savings.

    ``incident_cost`` and ``avoided_incident_count`` are not inputs. They
    belong to ``avoided_incident_value()``. This function still returns
    ``cash_savings`` as null.
    """
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


AVOIDED_INCIDENT_POST_FIELDS = (
    "incident_cost",
    "avoided_incident_count",
    "avoided_incident_value",
)


def disposition_avoided_incident_problem(source):
    """Reject a form or decision body that tries to supply this figure.

    A missing key and a blank string are not a crafted value. Any other
    value is rejected. The figure stays in the versioned assumptions file.
    It is not an observed register field.
    """
    if not hasattr(source, "get"):
        return None
    posted = []
    for name in AVOIDED_INCIDENT_POST_FIELDS:
        if isinstance(source, dict) and name not in source:
            continue
        value = source.get(name)
        if value is None or value == "":
            continue
        posted.append(name)
    if not posted:
        return None
    listed = ", ".join(posted)
    return (
        f"{listed} cannot be saved on a disposition, a public try, or an import. "
        "Avoided-incident value is a modeled assumption in the versioned cost file. "
        "It is not an observed register figure."
    )


def _classify_assumption(value, *, whole):
    """Return ``(state, number)`` for one optional assumption.

    ``absent`` is null. ``invalid`` is present but not a usable number.
    ``set`` is an explicit non-negative number. Booleans and strings are
    invalid. A count must be a whole number. Text is not coerced.
    """
    if value is None:
        return "absent", None
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return "invalid", None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "invalid", None
    if not number.is_finite() or number < 0:
        return "invalid", None
    if whole and number != number.to_integral_value():
        return "invalid", None
    return "set", number


def _plain_number(number):
    integral = number.to_integral_value()
    if number == integral:
        return int(integral)
    return float(number)


def _dollar_label(number):
    quantized = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if quantized < 0 else ""
    text = f"{abs(quantized):.2f}"
    whole, frac = text.split(".")
    return f"{sign}{int(whole):,}.{frac} dollars"


def _count_phrase(count):
    number = int(count)
    noun = "avoided incident" if number == 1 else "avoided incidents"
    return f"{number} {noun}"


def avoided_incident_value(assumptions=None):
    """Modeled avoided-incident dollars, or Not measured.

    A value exists only when both ``incident_cost`` and
    ``avoided_incident_count`` are explicit labeled assumptions. Null, a
    missing key, and any value that is not a usable number leave the figure
    Not measured. The product is not cash savings, and ``calculate_cost()``
    does not return it. Handling minutes, rework minutes, manual touches,
    handoffs, authenticated effort, the monthly assessment rate, elapsed
    cycle time, and the labor rate are not inputs.
    """
    if assumptions is None:
        assumptions = load_assumptions()
    model_version = "unspecified"
    if isinstance(assumptions, dict):
        model_version = assumptions.get("model_version", "unspecified")
        cost_state, cost = _classify_assumption(assumptions.get("incident_cost"), whole=False)
        count_state, count = _classify_assumption(
            assumptions.get("avoided_incident_count"), whole=True,
        )
    else:
        cost_state, cost = "invalid", None
        count_state, count = "invalid", None

    base = {
        "id": "avoided_incident_value",
        "label": "Avoided-incident value",
        "kind": "modeled_assumption",
        "measured": False,
        "value": None,
        "value_label": None,
        "incident_cost": _plain_number(cost) if cost_state == "set" else None,
        "avoided_incident_count": int(count) if count_state == "set" else None,
        "incident_cost_state": cost_state,
        "avoided_incident_count_state": count_state,
        "reason": None,
        "feeds_cost_model": False,
        "feeds_cash_savings": False,
        "separate_from_cash_savings": True,
        "separate_from_labor_capacity": True,
        "model_version": model_version,
        "source": "app/data/cost_assumptions.json",
        "detail": "",
        "list_detail": "",
    }
    closer = (
        "This is not an observed register figure. It is not cash savings. "
        "It is not labor-capacity dollars from calculate_cost(). "
        "It is not handling minutes, rework minutes, manual touches, handoffs, "
        "authenticated effort, the monthly assessment rate, or elapsed cycle time."
    )
    if cost_state == "invalid" or count_state == "invalid":
        base["reason"] = "invalid"
        detail = (
            "Modeled assumption. incident_cost and avoided_incident_count are not "
            "both explicit non-negative numbers, with a whole count and a dollar "
            "cost. This card says Not measured. No value was calculated. "
            f"{closer}"
        )
    elif cost_state == "set" and count_state == "set":
        product = (cost * count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        label = _dollar_label(product)
        base.update({
            "measured": True,
            "value": _plain_number(product),
            "value_label": label,
            "reason": None,
        })
        detail = (
            f"Modeled assumption. {_count_phrase(count)} times {_dollar_label(cost)} "
            f"incident cost = {label}. {closer} It is not proven risk reduction."
        )
    elif cost_state == "set" or count_state == "set":
        base["reason"] = "incomplete"
        detail = (
            "Modeled assumption. Both incident_cost and avoided_incident_count "
            "have to be set before a value is shown. One of them is null, so this "
            "card says Not measured. The number that is set is not used as the value. "
            f"{closer}"
        )
    else:
        base["reason"] = "not_set"
        detail = (
            "Modeled assumption. incident_cost and avoided_incident_count are null "
            "in app/data/cost_assumptions.json, so this card says Not measured. "
            f"{closer} A number appears only when both assumptions are set in that "
            "file. The public try form and file import cannot supply it."
        )
    base["detail"] = detail
    base["list_detail"] = detail
    return base
