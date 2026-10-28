"""Observed counts, elapsed cycle time, and self-reported decision fields.

The figures come from persisted rows and workflow-event timestamps. They are
separate from the illustrative cost assumptions in ``cost_model.py``.

Elapsed cycle time is the clock span from the earliest ``intake_received``
event to the earliest ``decision_recorded`` event on the same risk. A shared
timestamp is a measured span of zero seconds. That span is the time between
writes.

The monthly assessment rate counts current decision rows by ``decided_at``.
It is a number only when those timestamps cover a full 30-day window. A
shorter history stays unmeasured. The count is not scaled up, and it is not
passed to the cost formula.

Self-reported human handling time is the optional ``handling_minutes`` value
on the current decision row. Self-reported rework time is the optional
``rework_minutes`` value on that same row. Self-reported manual touches are
the optional ``manual_touches`` count on that same row. Self-reported
handoffs are the optional ``handoffs`` count on that same row. Null stays
out of each average. The four figures are not each other, they are not
elapsed cycle time, they are not the monthly rate, and this module does not
pass any of them to the cost formula.
"""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.services.workflow_service import DISPOSITIONS


DEFINITION_VERSION = "6"
MONTH_WINDOW_DAYS = 30

RESIDUAL_TIERS = ("low", "moderate", "high", "critical", "undetermined")
EVIDENCE_STATUSES = (
    "verified", "self_attested", "missing", "conflicting", "expired", "not_reviewed",
)
REMEDIATION_STATUSES = ("open", "in_progress", "completed")
INTAKE_EVENT = "intake_received"
DISPOSITION_EVENT = "decision_recorded"

COST_MAPPING = (
    "Observed assessment volume is a count of saved rows. It stays out of the "
    "assessments-per-month assumption. The observed monthly assessment rate "
    "counts current decisions in a covered 30-day window. It stays out of that "
    "assumption too. Elapsed cycle time is a clock span between workflow events. "
    "It stays out of the baseline and assisted handling-hour assumptions. "
    "Self-reported handling minutes, self-reported rework minutes, "
    "self-reported manual touches, and self-reported handoffs stay out of that "
    "formula. The illustrative formula is unchanged."
)
UNMEASURED_SUMMARY = (
    "Authenticated effort, cash savings, and avoided-incident value stay "
    "unmeasured. Self-reported handling minutes, self-reported rework minutes, "
    "self-reported manual touches, and self-reported handoffs are optional and "
    "are not cash savings. The monthly assessment rate is a separate count of "
    "current decisions. It is not those fields."
)
CYCLE_DEFINITION = (
    "Elapsed seconds from the earliest intake_received event to the earliest "
    "decision_recorded event on the same saved risk. The mean uses half-up rounding "
    "to two decimal places. A shared timestamp counts as zero elapsed seconds. "
    "Scenario rows without intake_received, rows without a disposition event, and "
    "rows with reversed or unreadable timestamps stay outside the average. "
    "Self-reported handling minutes, self-reported rework minutes, "
    "self-reported manual touches, and self-reported handoffs are separate figures."
)
HANDLING_DEFINITION = (
    "Self-reported whole minutes on the current decision row. Blank and null stay "
    "out of the average. The headline figure is the median. For an even count, the "
    "median is the mean of the two middle values. The mean is rounded half up to "
    "two decimal places. These minutes are not elapsed cycle time, they are not "
    "rework minutes, they are not a manual-touch count, they are not a handoff "
    "count, they are not the monthly assessment rate, they are not authenticated, "
    "and they are not copied into the cost formula."
)
REWORK_DEFINITION = (
    "Self-reported whole minutes of rework on the current decision row. Rework is "
    "time spent redoing work after a first pass. Blank and null stay out of the "
    "average. The headline figure is the median. For an even count, the median is "
    "the mean of the two middle values. The mean is rounded half up to two decimal "
    "places. These minutes are not elapsed cycle time, they are not handling minutes, "
    "they are not a manual-touch count, they are not a handoff count, they are not "
    "the monthly assessment rate, they are not authenticated, and they are not "
    "copied into the cost formula."
)
MANUAL_TOUCHES_DEFINITION = (
    "Self-reported whole-number count of human touchpoints on the current decision "
    "row. A touchpoint is a person's contact with that assessment, as the person "
    "reports it. Blank and null stay out of the average. The headline figure is the "
    "median. For an even count, the median is the mean of the two middle values. The "
    "mean is rounded half up to two decimal places. This count is not elapsed cycle "
    "time, it is not handling minutes, it is not rework minutes, it is not a "
    "handoff count, it is not the monthly assessment rate, it is not authenticated, "
    "and it is not copied into the cost formula."
)
HANDOFFS_DEFINITION = (
    "Self-reported whole-number count of times the assessment was handed between "
    "people or queues before disposition, on the current decision row. Blank and "
    "null stay out of the average. The headline figure is the median. For an even "
    "count, the median is the mean of the two middle values. The mean is rounded "
    "half up to two decimal places. This count is not elapsed cycle time, it is "
    "not handling minutes, it is not rework minutes, it is not a manual-touch "
    "count, it is not the monthly assessment rate, it is not authenticated, and "
    "it is not copied into the cost formula."
)
RATE_DEFINITION = (
    "Monthly assessment rate is the count of current decision rows whose decided_at "
    "timestamp falls in the closed 30-day window ending at the latest readable "
    "decided_at. The register shows a number only when the earliest readable "
    "decided_at is at least 30 days before that latest timestamp, so the window is "
    "covered. An empty register, a decision with no readable timestamp, a single "
    "timestamp, and any shorter span stay Not measured. The count is not divided "
    "into a partial month and is not scaled up. One current row per saved risk is "
    "counted. An older decision_recorded event is not counted. An unsaved public "
    "try is not counted. Saved assessments with no decision row are not counted. "
    "A timestamp with no offset is read as UTC. The window is anchored to the "
    "stored timestamps, not to the clock when the page is opened. This rate is not "
    "handling minutes, not rework minutes, not a manual-touch count, not a handoff "
    "count, not elapsed cycle time, and it is not copied into the cost formula."
)
NOT_MEASURED = (
    {
        "id": "authenticated_effort",
        "label": "Authenticated effort",
        "detail": (
            "Self-reported minutes, self-reported manual touches, and self-reported "
            "handoffs are not checked against an identity system or a timesheet. "
            "The monthly assessment rate is a count of stored decision timestamps. "
            "It is not authenticated effort."
        ),
    },
    {
        "id": "cash_savings",
        "label": "Cash savings",
        "detail": (
            "The register stores no spending reduction. Elapsed time and the monthly "
            "assessment rate are not converted into money."
        ),
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
        """SELECT risk_id, disposition, decided_at, handling_minutes, rework_minutes,
                  manual_touches, handoffs
           FROM decisions"""
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
    a risk has more than one event of the same type. The monthly assessment
    rate uses ``decided_at`` on the current decision rows. It does not read
    the event log.
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
        "handling_time": _self_reported_block(
            decisions, "handling_minutes",
            "Self-reported human handling time", HANDLING_DEFINITION,
        ),
        "rework_time": _self_reported_block(
            decisions, "rework_minutes",
            "Self-reported rework time", REWORK_DEFINITION,
        ),
        "manual_touches": _self_reported_block(
            decisions, "manual_touches",
            "Self-reported manual touches", MANUAL_TOUCHES_DEFINITION,
            singular="touch", plural="touches",
        ),
        "handoffs": _self_reported_block(
            decisions, "handoffs",
            "Self-reported handoffs", HANDOFFS_DEFINITION,
            singular="handoff", plural="handoffs",
        ),
        "monthly_assessment_rate": _monthly_assessment_rate(decisions),
    }


def format_whole_count(value, singular, plural):
    """Render a count with its unit. ``None`` stays ``None``."""
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    if number == number.to_integral_value():
        rendered = str(int(number))
        unit = singular if number == 1 else plural
    else:
        rendered = format(number.normalize(), "f")
        unit = plural
    return f"{rendered} {unit}"


def format_handling_minutes(minutes):
    """Render a minute count with its unit. ``None`` stays ``None``."""
    return format_whole_count(minutes, "minute", "minutes")


def format_monthly_rate(count):
    """Render a covered-window count. ``None`` stays ``None``."""
    if count is None:
        return None
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return None
    unit = "assessment per 30 days" if count == 1 else "assessments per 30 days"
    return f"{count} {unit}"


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


def _as_utc(moment):
    """Return ``moment`` in UTC. A naive value is read as UTC. ``None`` stays ``None``."""
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


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


def _self_reported_block(decisions, field, label, definition, singular="minute", plural="minutes"):
    """Median of current decision rows that store a non-negative whole number.

    Null, a missing key, and any value that is not a non-negative int stay
    out of the average. A stored zero is a reported zero and is included.
    Handling minutes, rework minutes, manual touches, and handoffs each use
    this rule on their own field. ``plural`` names the statistic keys, such
    as minutes, touches, or handoffs.
    """
    values = []
    unmeasured = 0
    for decision in decisions:
        raw = decision.get(field) if isinstance(decision, dict) else None
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            unmeasured += 1
            continue
        values.append(raw)
    stats = _count_statistics(values)
    labeled = {
        "recorded_count": stats["recorded_count"],
        "unmeasured_decisions": unmeasured,
        f"minimum_{plural}": _number(stats["minimum"]),
        f"maximum_{plural}": _number(stats["maximum"]),
        f"median_{plural}": _number(stats["median"]),
        f"mean_{plural}": _number(stats["mean"]),
        f"total_{plural}": _number(stats["total"]),
        "minimum_label": format_whole_count(stats["minimum"], singular, plural),
        "maximum_label": format_whole_count(stats["maximum"], singular, plural),
        "median_label": format_whole_count(stats["median"], singular, plural),
        "mean_label": format_whole_count(stats["mean"], singular, plural),
        "total_label": format_whole_count(stats["total"], singular, plural) or f"0 {plural}",
    }
    return {
        "kind": "self_reported",
        "label": label,
        "unit": plural,
        "definition": definition,
        "feeds_cost_model": False,
        "authenticated": False,
        **labeled,
    }


def _monthly_assessment_rate(decisions):
    """Count current decisions in a covered 30-day window.

    The window ends at the latest readable ``decided_at`` and includes that
    instant and the instant 30 days earlier. The rate is that count only when
    the earliest readable timestamp is at least 30 days earlier. A shorter
    span stays unmeasured. The count is not scaled up. Workflow events are
    not an input.
    """
    readable = []
    unreadable = 0
    for decision in decisions:
        raw = decision.get("decided_at") if isinstance(decision, dict) else None
        moment = _as_utc(_parse_timestamp(raw))
        if moment is None:
            unreadable += 1
            continue
        readable.append((moment, raw.strip()))
    base = {
        "kind": "observed_rate",
        "label": "Monthly assessment rate",
        "definition": RATE_DEFINITION,
        "feeds_cost_model": False,
        "window_days": MONTH_WINDOW_DAYS,
        "measured": False,
        "rate": None,
        "rate_label": None,
        "counted": None,
        "readable_count": len(readable),
        "unreadable_count": unreadable,
        "outside_window_count": None,
        "earliest": None,
        "latest": None,
        "reason": None,
        "detail": "",
    }
    if not decisions:
        base["reason"] = "no_decisions"
        base["detail"] = _rate_unmeasured_detail(base)
        return base
    if not readable:
        base["reason"] = "no_readable_timestamp"
        base["detail"] = _rate_unmeasured_detail(base)
        return base
    readable.sort(key=lambda item: item[0])
    earliest_moment, earliest = readable[0]
    latest_moment, latest = readable[-1]
    base["earliest"] = earliest
    base["latest"] = latest
    window = timedelta(days=MONTH_WINDOW_DAYS)
    start = latest_moment - window
    if earliest_moment > start:
        base["reason"] = "insufficient_history"
        base["detail"] = _rate_unmeasured_detail(base)
        return base
    counted = sum(1 for moment, _stored in readable if start <= moment <= latest_moment)
    outside = sum(1 for moment, _stored in readable if moment < start)
    if counted < 1:
        base["reason"] = "insufficient_history"
        base["detail"] = _rate_unmeasured_detail(base)
        return base
    base.update({
        "measured": True,
        "rate": counted,
        "rate_label": format_monthly_rate(counted),
        "counted": counted,
        "outside_window_count": outside,
        "reason": None,
    })
    base["detail"] = _rate_measured_detail(base)
    return base


def _rate_closer():
    return (
        "This is not handling minutes, not rework minutes, not manual touches, "
        "not handoffs, not elapsed cycle time, and not an input to the cost model."
    )


def _rate_unmeasured_detail(rate):
    reason = rate["reason"]
    if reason == "no_decisions":
        lead = (
            "No current decision is stored. Saved assessments without a decision "
            "are not a monthly rate."
        )
    elif reason == "no_readable_timestamp":
        count = rate["unreadable_count"]
        noun = "current decision has" if count == 1 else "current decisions have"
        lead = (
            f"{count} {noun} no readable decided_at timestamp. "
            "The monthly rate is not measured."
        )
    else:
        count = rate["readable_count"]
        if count == 1:
            lead = (
                f"1 current decision has a readable timestamp ({rate['latest']}). "
                "One timestamp does not cover 30 days, so the monthly rate is not measured. "
                "The count is not scaled up to a month."
            )
        else:
            lead = (
                f"{count} current decisions have a readable timestamp. "
                f"The earliest is {rate['earliest']} and the latest is {rate['latest']}. "
                "Those timestamps span less than 30 days, so the monthly rate is not measured. "
                "The count is not scaled up to a month."
            )
    return f"{lead} {_rate_closer()}"


def _rate_measured_detail(rate):
    count = rate["rate"]
    noun = "current decision" if count == 1 else "current decisions"
    parts = [
        (
            f"{rate['rate_label']} from {count} {noun} whose decided_at falls in the "
            f"30 days ending at {rate['latest']}."
        ),
        (
            f"The earliest readable timestamp is {rate['earliest']}, so this register "
            "covers that window."
        ),
    ]
    outside = rate["outside_window_count"]
    if outside == 1:
        parts.append("1 earlier current decision falls outside that window and is not in this rate.")
    elif outside:
        parts.append(
            f"{outside} earlier current decisions fall outside that window and are not in this rate."
        )
    else:
        parts.append("No readable current decision falls outside that window.")
    unreadable = rate["unreadable_count"]
    if unreadable == 1:
        parts.append("1 current decision has no readable timestamp and is not in this rate.")
    elif unreadable:
        parts.append(
            f"{unreadable} current decisions have no readable timestamp and are not in this rate."
        )
    parts.append(
        "This count uses the current decision row. An older decision event is not counted. "
        "It is not handling minutes, not rework minutes, not manual touches, not handoffs, "
        "not elapsed cycle time, and not an input to the cost model. "
        "It is not the modeled assessments-per-month assumption."
    )
    return " ".join(parts)


def _count_statistics(values):
    if not values:
        return {
            "recorded_count": 0,
            "minimum": None,
            "maximum": None,
            "median": None,
            "mean": None,
            "total": Decimal(0),
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
        "minimum": ordered[0],
        "maximum": ordered[-1],
        "median": median,
        "mean": mean,
        "total": total,
    }

