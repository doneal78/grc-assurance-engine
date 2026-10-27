"""Observed counts, elapsed cycle time, and self-reported handling minutes.

The figures come from persisted rows and workflow-event timestamps. They are
separate from the illustrative cost assumptions in ``cost_model.py``.

Elapsed cycle time is the clock span from the earliest ``intake_received``
event to the earliest ``decision_recorded`` event on the same risk. A shared
timestamp is a measured span of zero seconds. That span is the time between
writes.

Self-reported human handling time is the optional ``handling_minutes`` value
on the current decision row. Null stays out of that average. The minutes are
not elapsed cycle time, and this module does not pass them to the cost formula.
"""

import json
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.services.workflow_service import DISPOSITIONS


DEFINITION_VERSION = "2"

RESIDUAL_TIERS = ("low", "moderate", "high", "critical", "undetermined")
EVIDENCE_STATUSES = (
    "verified", "self_attested", "missing", "conflicting", "expired", "not_reviewed",
)
REMEDIATION_STATUSES = ("open", "in_progress", "completed")
INTAKE_EVENT = "intake_received"
DISPOSITION_EVENT = "decision_recorded"

COST_MAPPING = (
    "Observed assessment volume is a count of saved rows. It stays out of the "
    "assessments-per-month assumption. Elapsed cycle time is a clock span between "
    "workflow events. It stays out of the baseline and assisted handling-hour "
    "assumptions. Self-reported handling minutes stay out of that formula. "
    "The illustrative formula is unchanged."
)
UNMEASURED_SUMMARY = (
    "Manual touches, handoffs, rework duration, a monthly assessment rate, "
    "cash savings, and avoided-incident value stay unmeasured. Self-reported "
    "handling minutes are optional and are not cash savings."
)
CYCLE_DEFINITION = (
    "Elapsed seconds from the earliest intake_received event to the earliest "
    "decision_recorded event on the same saved risk. The mean uses half-up rounding "
    "to two decimal places. A shared timestamp counts as zero elapsed seconds. "
    "Scenario rows without intake_received, rows without a disposition event, and "
    "rows with reversed or unreadable timestamps stay outside the average. "
    "Self-reported handling minutes are a separate figure."
)
HANDLING_DEFINITION = (
    "Self-reported whole minutes on the current decision row. Blank and null stay "
    "out of the average. The headline figure is the median. For an even count, the "
    "median is the mean of the two middle values. The mean is rounded half up to "
    "two decimal places. These minutes are not elapsed cycle time, they are not "
    "authenticated, and they are not copied into the cost formula."
)
NOT_MEASURED = (
    {
        "id": "manual_touches",
        "label": "Manual touches",
        "detail": "The event log does not count distinct manual touches.",
    },
    {
        "id": "handoffs",
        "label": "Handoffs",
        "detail": "The event log does not record a handoff as its own measurement.",
    },
    {
        "id": "rework_time",
        "label": "Rework duration",
        "detail": "A remediation update stores a new status. It does not store a duration.",
    },
    {
        "id": "monthly_assessment_rate",
        "label": "Monthly assessment rate",
        "detail": "Saved rows are a count. The register does not assign them to a reporting month.",
    },
    {
        "id": "cash_savings",
        "label": "Cash savings",
        "detail": "The register stores no spending reduction. Elapsed time is not converted into money.",
    },
    {
        "id": "avoided_incident_value",
        "label": "Avoided-incident value",
        "detail": "Hypothetical avoided incidents are left unmonetized.",
    },
)


def observed_metrics(db):
    """Read the register and return observed metrics. Performs no writes."""
    risks = [dict(row) for row in db.execute(
        "SELECT risk_id, scenario_id, residual_tier, rationale_json FROM risks"
    ).fetchall()]
    actions = [dict(row) for row in db.execute(
        "SELECT status FROM remediation_actions"
    ).fetchall()]
    decisions = [dict(row) for row in db.execute(
        "SELECT risk_id, disposition, handling_minutes FROM decisions"
    ).fetchall()]
    events = [dict(row) for row in db.execute(
        """SELECT risk_id, event_type, occurred_at
           FROM workflow_events
           WHERE event_type IN (?, ?)
           ORDER BY event_id""",
        (INTAKE_EVENT, DISPOSITION_EVENT),
    ).fetchall()]
    return summarize_register(risks, actions, decisions, events)


def summarize_register(risks, actions, decisions, events):
    """Calculate metrics from already loaded rows.

    ``events`` may include every workflow event. Only ``intake_received`` and
    ``decision_recorded`` affect cycle time. The earliest timestamp wins when
    a risk has more than one event of the same type.
    """
    rationale_by_risk = {}
    general_intake = 0
    residual = Counter()
    claim_counts = Counter()
    clause_counts = Counter()
    rationale_unreadable = 0
    claims_unreadable = 0
    claims_missing_status = 0
    clause_records_absent = 0
    clause_records_unreadable = 0
    clause_status_missing = 0

    for risk in risks:
        rationale = _load_rationale(risk.get("rationale_json"))
        rationale_by_risk[risk.get("risk_id")] = rationale
        if _is_general_intake(risk.get("scenario_id"), rationale):
            general_intake += 1
        tier = risk.get("residual_tier")
        if isinstance(tier, str) and tier.strip():
            residual[tier.strip()] += 1
        else:
            residual["(blank)"] += 1
        if rationale is None:
            rationale_unreadable += 1
            continue
        claim_result = _statuses_from_list(rationale.get("claims"))
        if claim_result is None:
            claims_unreadable += 1
        else:
            statuses, missing = claim_result
            claims_missing_status += missing
            claim_counts.update(statuses)
        clause_result = _clause_list(rationale)
        if clause_result is None:
            clause_records_absent += 1
        elif clause_result == "unreadable":
            clause_records_unreadable += 1
        else:
            statuses, missing = clause_result
            clause_status_missing += missing
            clause_counts.update(statuses)

    total = len(risks)
    disposition_counts = Counter()
    decided_risks = set()
    for decision in decisions:
        disposition_counts[decision.get("disposition") or "(blank)"] += 1
        decided_risks.add(decision.get("risk_id"))
    risks_without_decision = sum(1 for risk in risks if risk.get("risk_id") not in decided_risks)

    action_counts = Counter(action.get("status") or "(blank)" for action in actions)
    not_completed = sum(count for status, count in action_counts.items() if status != "completed")

    events_by_risk = {}
    decision_event_count = 0
    for event in events:
        kind = event.get("event_type")
        if kind not in (INTAKE_EVENT, DISPOSITION_EVENT):
            continue
        events_by_risk.setdefault(event.get("risk_id"), {INTAKE_EVENT: [], DISPOSITION_EVENT: []})
        events_by_risk[event["risk_id"]][kind].append(event.get("occurred_at"))
        if kind == DISPOSITION_EVENT:
            decision_event_count += 1

    spans = []
    excluded = {"no_intake_event": 0, "no_disposition_event": 0, "unusable_timestamps": 0}
    for risk in risks:
        grouped = events_by_risk.get(risk.get("risk_id"), {INTAKE_EVENT: [], DISPOSITION_EVENT: []})
        start_ok, start = _earliest(grouped[INTAKE_EVENT])
        end_ok, end = _earliest(grouped[DISPOSITION_EVENT])
        if start is None and start_ok:
            excluded["no_intake_event"] += 1
            continue
        if end is None and end_ok:
            excluded["no_disposition_event"] += 1
            continue
        if not start_ok or not end_ok:
            excluded["unusable_timestamps"] += 1
            continue
        elapsed = _elapsed_seconds(start, end)
        if elapsed is None or elapsed < 0:
            excluded["unusable_timestamps"] += 1
            continue
        spans.append(elapsed)

    cycle = _with_labels(_cycle_statistics(spans))
    cycle["excluded"] = excluded
    cycle["definition"] = CYCLE_DEFINITION

    return {
        "kind": "observed",
        "definition_version": DEFINITION_VERSION,
        "feeds_cost_model": False,
        "cost_mapping": COST_MAPPING,
        "unmeasured_summary": UNMEASURED_SUMMARY,
        "not_measured": [dict(item) for item in NOT_MEASURED],
        "assessment_volume": {
            "total": total,
            "general_intake": general_intake,
            "scenario_fixture": total - general_intake,
        },
        "remediation": {
            "by_status": _distribution(REMEDIATION_STATUSES, action_counts),
            "not_completed": not_completed,
            "total": len(actions),
        },
        "residual_tiers": _distribution(RESIDUAL_TIERS, residual),
        "evidence_statuses": _distribution(EVIDENCE_STATUSES, claim_counts),
        "claim_count": sum(claim_counts.values()),
        "claims_missing_status": claims_missing_status,
        "rationale_unreadable": rationale_unreadable,
        "claims_unreadable": claims_unreadable,
        "clause_evidence_statuses": _distribution(EVIDENCE_STATUSES, clause_counts),
        "clause_count": sum(clause_counts.values()),
        "clause_records_absent": clause_records_absent,
        "clause_records_unreadable": clause_records_unreadable,
        "clause_status_missing": clause_status_missing,
        "dispositions": {
            "by_disposition": _distribution(DISPOSITIONS, disposition_counts),
            "recorded": len(decisions),
            "risks_without_decision": risks_without_decision,
        },
        "decision_event_count": decision_event_count,
        "cycle_time": cycle,
        "handling_time": _handling_block(decisions),
    }


def format_handling_minutes(minutes):
    """Render a minute count with its unit. ``None`` stays ``None``."""
    if minutes is None:
        return None
    try:
        value = Decimal(str(minutes))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    if value == value.to_integral_value():
        rendered = str(int(value))
        unit = "minute" if value == 1 else "minutes"
    else:
        rendered = format(value.normalize(), "f")
        unit = "minutes"
    return f"{rendered} {unit}"


def format_elapsed_seconds(seconds):
    """Render a second count with its unit. ``None`` stays ``None``."""
    if seconds is None:
        return None
    try:
        value = Decimal(str(seconds))
    except (InvalidOperation, ValueError):
        return None
    if not value.is_finite():
        return None
    if value == value.to_integral_value():
        rendered = str(int(value))
        unit = "elapsed second" if value == 1 else "elapsed seconds"
    else:
        rendered = format(value.normalize(), "f")
        unit = "elapsed seconds"
    return f"{rendered} {unit}"


def _load_rationale(raw):
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return value


def _is_general_intake(scenario_id, rationale):
    if isinstance(scenario_id, str) and scenario_id.startswith("intake-"):
        return True
    return isinstance(rationale, dict) and rationale.get("intake_origin") == "general_intake"


def _statuses_from_list(items):
    if not isinstance(items, list):
        return None
    statuses = []
    missing = 0
    for item in items:
        if not isinstance(item, dict):
            missing += 1
            continue
        status = item.get("evidence_status")
        if not isinstance(status, str) or not status.strip():
            missing += 1
            continue
        statuses.append(status.strip())
    return statuses, missing


def _clause_list(rationale):
    risk = rationale.get("risk")
    policy = risk.get("policy") if isinstance(risk, dict) else None
    if not isinstance(policy, dict) or "required_contract_clauses" not in policy:
        return None
    clauses = policy.get("required_contract_clauses")
    if not isinstance(clauses, list):
        return "unreadable"
    return _statuses_from_list(clauses)


def _distribution(preferred, found):
    rows = [{"name": name, "count": int(found.get(name, 0))} for name in preferred]
    extras = sorted(name for name in found if name not in preferred)
    for name in extras:
        rows.append({"name": name, "count": int(found[name])})
    return rows


def _earliest(timestamps):
    """Return ``(parsed, moment)``.

    An empty list is a successful absence: ``(True, None)``. One unreadable
    timestamp makes the whole set unusable, so a later good value cannot hide
    an earlier value the clock could not read.
    """
    if not timestamps:
        return True, None
    moments = []
    for value in timestamps:
        moment = _parse_timestamp(value)
        if moment is None:
            return False, None
        moments.append(moment)
    return True, min(moments)


def _parse_timestamp(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _elapsed_seconds(start, end):
    try:
        delta = end - start
    except TypeError:
        return None
    return (Decimal(delta.days) * Decimal(86400)
            + Decimal(delta.seconds)
            + (Decimal(delta.microseconds) / Decimal(1_000_000)))


def _number(value):
    if value is None:
        return None
    integral = value.to_integral_value()
    if value == integral:
        return int(integral)
    return float(value)


def _with_labels(stats):
    """Add display labels, then convert Decimal values to plain numbers."""
    labeled = dict(stats)
    for key in ("minimum_seconds", "maximum_seconds", "median_seconds", "mean_seconds", "total_seconds"):
        labeled[key.replace("_seconds", "_label")] = format_elapsed_seconds(stats[key])
        if isinstance(stats[key], Decimal):
            labeled[key] = _number(stats[key])
    return labeled


def _cycle_statistics(spans):
    if not spans:
        return {
            "measured_count": 0,
            "zero_span_count": 0,
            "minimum_seconds": None,
            "maximum_seconds": None,
            "median_seconds": None,
            "mean_seconds": None,
            "total_seconds": 0,
        }
    ordered = sorted(spans)
    count = len(ordered)
    total = sum(ordered, Decimal(0))
    mid = count // 2
    if count % 2:
        median = ordered[mid]
    else:
        median = (ordered[mid - 1] + ordered[mid]) / Decimal(2)
    mean = (total / Decimal(count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "measured_count": count,
        "zero_span_count": sum(1 for span in ordered if span == 0),
        "minimum_seconds": ordered[0],
        "maximum_seconds": ordered[-1],
        "median_seconds": median,
        "mean_seconds": mean,
        "total_seconds": total,
    }


def _handling_block(decisions):
    """Median of current decision rows that store a whole number of minutes.

    Null, a missing key, and any value that is not a non-negative int stay
    out of the average. A stored zero is a reported zero and is included.
    """
    values = []
    unmeasured = 0
    for decision in decisions:
        raw = decision.get("handling_minutes") if isinstance(decision, dict) else None
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            unmeasured += 1
            continue
        values.append(raw)
    stats = _minute_statistics(values)
    labeled = {
        "recorded_count": stats["recorded_count"],
        "unmeasured_decisions": unmeasured,
        "minimum_minutes": _number(stats["minimum_minutes"]),
        "maximum_minutes": _number(stats["maximum_minutes"]),
        "median_minutes": _number(stats["median_minutes"]),
        "mean_minutes": _number(stats["mean_minutes"]),
        "total_minutes": _number(stats["total_minutes"]),
        "minimum_label": format_handling_minutes(stats["minimum_minutes"]),
        "maximum_label": format_handling_minutes(stats["maximum_minutes"]),
        "median_label": format_handling_minutes(stats["median_minutes"]),
        "mean_label": format_handling_minutes(stats["mean_minutes"]),
        "total_label": format_handling_minutes(stats["total_minutes"]) or "0 minutes",
    }
    return {
        "kind": "self_reported",
        "label": "Self-reported human handling time",
        "unit": "minutes",
        "definition": HANDLING_DEFINITION,
        "feeds_cost_model": False,
        "authenticated": False,
        **labeled,
    }


def _minute_statistics(values):
    if not values:
        return {
            "recorded_count": 0,
            "minimum_minutes": None,
            "maximum_minutes": None,
            "median_minutes": None,
            "mean_minutes": None,
            "total_minutes": Decimal(0),
        }
    ordered = sorted(Decimal(value) for value in values)
    count = len(ordered)
    total = sum(ordered, Decimal(0))
    mid = count // 2
    if count % 2:
        median = ordered[mid]
    else:
        median = (ordered[mid - 1] + ordered[mid]) / Decimal(2)
    mean = (total / Decimal(count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "recorded_count": count,
        "minimum_minutes": ordered[0],
        "maximum_minutes": ordered[-1],
        "median_minutes": median,
        "mean_minutes": mean,
        "total_minutes": total,
    }

