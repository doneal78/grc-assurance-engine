"""Turn the public demo intake form into synthetic assessment inputs.

The public "Try it" pages let a visitor describe a fictional vendor or AI
tool. This module converts that form into the same claims and evidence
records the evidence validator and risk engine already use, so every result
comes from the tested application logic rather than demo-only scoring.
A trust-center URL is stored with those records. Fetching it is optional.
A fetch is one HTTP GET of vendor-published material. It is not a separate
score, and it is not verified evidence. Nothing here writes to the database.
"""

from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlparse

from app.services.control_mapper import map_claims
from app.services.evidence_validator import validate, validate_assessment
from app.services.org_policy import load_org_policy
from app.services.risk_engine import evaluate, load_rules
from app.services.trust_center_fetch import fetch_trust_center

MAX_VENDOR_NAME = 80

ASSESSMENT_FIELDS = (
    "data_sensitivity",
    "integration_permissions",
    "ai_use",
    "model_training_on_customer_data",
    "external_exposure",
    "retention_deletion",
)

EVIDENCE_OPTIONS = {
    "independent_verified": "Independent report, reviewed",
    "vendor_statement": "Vendor's own statement, reviewed",
    "not_reviewed": "Independent report, not reviewed yet",
    "expired": "Independent report, older than its freshness limit",
    "contradicts": "Configuration export that contradicts the claim",
    "none": "Nothing provided",
}

CLAUSE_EVIDENCE_OPTIONS = {
    "independent_verified": "Reviewed contract excerpt, not from the vendor",
    "vendor_statement": "Vendor's own contract statement, reviewed",
    "not_reviewed": "Contract excerpt, not reviewed yet",
    "expired": "Contract excerpt, older than its freshness limit",
    "contradicts": "Contract excerpt that contradicts the clause",
    "none": "Nothing provided",
}

GAP_STATUSES = {"missing", "expired", "not_reviewed", "conflicting"}
FETCH_CLAIM_ID = "C-TRUST-CENTER-PAGE"
FETCH_EVIDENCE_ID = "E-TRUST-CENTER-PAGE"
FETCH_TOPIC = "trust_center_page"

PRIORITY_BY_RESIDUAL_TIER = {
    "critical": "1 - Critical",
    "high": "2 - High",
    "moderate": "3 - Moderate",
    "low": "4 - Low",
    "undetermined": "2 - High (result undetermined)",
}


class IntakeError(ValueError):
    """Raised when the public intake form has missing or invalid values."""

    def __init__(self, problems):
        self.problems = problems
        super().__init__("; ".join(problems))


def assessment_fields():
    """Scoring fields plus the org-policy intake fields, without duplicates."""
    policy_fields = [spec["field"] for spec in load_org_policy()["intake_fields"]]
    return tuple(dict.fromkeys((*ASSESSMENT_FIELDS, *policy_fields)))


def field_choices():
    """Allowed values for each assessment field, read from the rule set and org policy."""
    rules = load_rules()
    choices = {field: list(factor["points"]) + [rules["unknown_value"]]
               for field, factor in rules["inherent_factors"].items()}
    choices["retention_deletion"] = list(rules["retention_deletion_values"])
    for spec in load_org_policy()["intake_fields"]:
        choices[spec["field"]] = list(spec["allowed"])
    return choices


def clause_evidence_field(clause_id):
    return f"evidence_clause_{clause_id}"


def _ids(topic):
    suffix = topic.upper().replace("_", "-")
    return f"C-{suffix}", f"E-{suffix}"


def _days_ago(as_of, days):
    return (as_of - timedelta(days=days)).isoformat()


def _supporting_review(as_of, contradicts=False):
    return {"reviewer": "Demo reviewer", "reviewed_on": _days_ago(as_of, 5), "relevant": True,
            "in_scope": True, "supports_claim": True, "contradicts_claim": contradicts}


def _evidence_record(topic, option, as_of):
    """Build one synthetic evidence record dated relative to the evaluation date."""
    claim_id, evidence_id = _ids(topic)

    def days_ago(days):
        return (as_of - timedelta(days=days)).isoformat()

    review = {"reviewer": "Demo reviewer", "reviewed_on": days_ago(5), "relevant": True,
              "in_scope": True, "supports_claim": True, "contradicts_claim": False}
    report = {"evidence_id": evidence_id, "claim_id": claim_id,
              "artifact_name": "Independent SOC 2 Type II report",
              "artifact_type": "soc2_type2_report", "source": "independent_auditor"}
    if option == "independent_verified":
        return {**report, "collection_date": days_ago(120), "review": review}
    if option == "not_reviewed":
        return {**report, "collection_date": days_ago(60)}
    if option == "expired":
        return {**report, "collection_date": days_ago(500), "review": review}
    if option == "vendor_statement":
        return {"evidence_id": evidence_id, "claim_id": claim_id,
                "artifact_name": "Vendor security statement", "artifact_type": "vendor_statement",
                "source": "vendor", "collection_date": days_ago(30), "review": review}
    if option == "contradicts":
        return {"evidence_id": evidence_id, "claim_id": claim_id,
                "artifact_name": "Integration configuration export",
                "artifact_type": "configuration_export", "source": "internal_observation",
                "collection_date": days_ago(7), "review": {**review, "contradicts_claim": True}}
    return None  # "none": the claim has no evidence records


def _clause_evidence_record(clause, option, as_of):
    """Build one synthetic contract-clause record dated relative to the evaluation date."""
    evidence_id = f"E-{clause['clause_id']}"
    claim_id = clause["clause_id"]

    def days_ago(days):
        return (as_of - timedelta(days=days)).isoformat()

    review = {"reviewer": "Demo reviewer", "reviewed_on": days_ago(5), "relevant": True,
              "in_scope": True, "supports_claim": True, "contradicts_claim": False}
    base = {"evidence_id": evidence_id, "claim_id": claim_id,
            "artifact_name": f"Contract excerpt for {clause['clause_id']}",
            "artifact_type": "contract_clause"}
    if option == "independent_verified":
        return {**base, "source": "internal_observation", "collection_date": days_ago(120), "review": review}
    if option == "not_reviewed":
        return {**base, "source": "internal_observation", "collection_date": days_ago(60)}
    if option == "expired":
        return {**base, "source": "internal_observation", "collection_date": days_ago(500), "review": review}
    if option == "vendor_statement":
        return {**base, "artifact_name": f"Vendor contract statement for {clause['clause_id']}",
                "source": "vendor", "collection_date": days_ago(30), "review": review}
    if option == "contradicts":
        return {**base, "artifact_name": f"Contract excerpt contradicting {clause['clause_id']}",
                "source": "internal_observation", "collection_date": days_ago(7),
                "review": {**review, "contradicts_claim": True}}
    return None  # "none": the clause has no evidence records


def _trust_center_url(value, trust):
    """Accept an empty URL, or one http(s) URL. Do not fetch it here."""
    url = (value or "").strip()
    if not url:
        return None, []
    limit = trust["url_max_length"]
    if len(url) > limit:
        return None, [f"Trust center URL must be {limit} characters or fewer."]
    if not url.isprintable() or any(character.isspace() for character in url):
        return None, ["Trust center URL contains unsupported characters."]
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None, ["Trust center URL must start with http:// or https:// and include a host."]
    if parsed.username or parsed.password:
        return None, ["Trust center URL must not include a username or password."]
    return url, []


def _trust_record(pointer, topic, option, as_of, url):
    """One pasted trust-center citation, dated relative to the evaluation date."""
    if option == "none":
        return None
    claim_id, _ = _ids(topic)
    evidence_id = f"E-{pointer['pointer_id'].upper()}-{topic.upper().replace('_', '-')}"
    record = {
        "evidence_id": evidence_id,
        "claim_id": claim_id,
        "artifact_name": pointer["artifact_name"],
        "artifact_type": pointer["artifact_type"],
        "source": pointer["source_by_option"][option],
        "pointer_id": pointer["pointer_id"],
    }
    if url:
        record["trust_center_url"] = url
    if option == "independent_verified":
        record["collection_date"] = _days_ago(as_of, 120)
        record["review"] = _supporting_review(as_of)
    elif option == "not_reviewed":
        record["collection_date"] = _days_ago(as_of, 60)
    elif option == "expired":
        record["collection_date"] = _days_ago(as_of, 500)
        record["review"] = _supporting_review(as_of)
    elif option == "vendor_statement":
        record["collection_date"] = _days_ago(as_of, 30)
        record["review"] = _supporting_review(as_of)
    elif option == "contradicts":
        record["collection_date"] = _days_ago(as_of, 7)
        record["review"] = _supporting_review(as_of, contradicts=True)
    return record


def _fetch_choice(form, trust, problems):
    """Return whether this intake asked for a GET. Omitted or no does not fetch."""
    raw = (form.get(trust["fetch_field"]) or "").strip()
    if raw == "" or raw == "no":
        return False
    if raw != "yes":
        prompt = trust["fetch_prompt"].rstrip("?")
        problems.append(f"{prompt}: choose yes or no.")
        return False
    return True


def _empty_fetch():
    return {
        "requested": False,
        "outcome": "not_requested",
        "http_status": None,
        "fetched_at": None,
        "content_type": None,
        "summary": None,
        "excerpt": None,
        "error": None,
        "byte_length": None,
        "final_url": None,
        "source": None,
        "evidence_status": None,
        "status_reason": None,
        "evidence_id": None,
    }


def _fetch_inputs(url, outcome, as_of):
    """Claim and evidence for the validator. A failed GET has no evidence record."""
    claim = {
        "claim_id": FETCH_CLAIM_ID,
        "topic": FETCH_TOPIC,
        "statement": (
            "The fetched trust-center page is vendor-published material for human review. "
            "It does not show that a control is in place."
        ),
    }
    if not outcome["ok"]:
        return claim, []
    record = {
        "evidence_id": FETCH_EVIDENCE_ID,
        "claim_id": FETCH_CLAIM_ID,
        "artifact_name": "Trust center page fetched for human review",
        "artifact_type": "vendor_statement",
        "source": "vendor",
        "collection_date": as_of.isoformat(),
        "trust_center_url": outcome.get("final_url") or url,
        "fetched_at": outcome.get("fetched_at") or "",
        "content_summary": outcome.get("summary") or "",
        "excerpt": outcome.get("excerpt") or "",
    }
    return claim, [record]


def _apply_fetch(url, trust, as_of, open_url, resolver, problems):
    """GET the URL when requested. A refusal is a form error. A transport failure is a gap."""
    notes = trust["result_notes"]
    base = _empty_fetch()
    if not url:
        problems.append("A trust center URL is required when fetch is yes.")
        return None, "fetch_failed", notes["failed"], base, None, []
    clock = datetime.combine(as_of, time.min, tzinfo=timezone.utc)
    outcome = fetch_trust_center(url, open_url=open_url, resolver=resolver, clock=clock)
    recorded = {
        **base,
        "requested": True,
        "outcome": "retrieved" if outcome["ok"] else "failed",
        "http_status": outcome["http_status"],
        "fetched_at": outcome["fetched_at"],
        "content_type": outcome["content_type"],
        "summary": outcome["summary"],
        "excerpt": outcome["excerpt"],
        "error": outcome["error"],
        "byte_length": outcome["byte_length"],
        "final_url": outcome["final_url"],
        "source": "vendor" if outcome["ok"] else None,
    }
    if outcome["refused"]:
        problems.append(outcome["error"])
        return False, "fetch_failed", notes["failed"], recorded, None, []
    claim, evidence = _fetch_inputs(url, outcome, as_of)
    if outcome["ok"]:
        return True, "http_get", notes["retrieved"], recorded, claim, evidence
    return False, "fetch_failed", notes["failed"], recorded, claim, evidence


def _review_fetch(trust, as_of):
    """Let the evidence validator status the fetch. Leave it off the scored claims."""
    trust = {**trust, "fetch": dict(trust.get("fetch") or _empty_fetch())}
    claim = trust.pop("fetch_claim", None)
    evidence = trust.pop("fetch_evidence", [])
    fetch = trust["fetch"]
    if claim is None:
        trust["artifact"] = None
        return trust
    checked = validate([claim], evidence, as_of)
    artifact = checked["claims"][0]
    if artifact["evidence_status"] == "verified" or any(item["status"] == "verified" for item in artifact["evidence"]):
        raise ValueError("A trust-center fetch cannot be verified evidence.")
    fetch["evidence_status"] = artifact["evidence_status"]
    fetch["status_reason"] = artifact["status_reason"]
    fetch["evidence_id"] = artifact["evidence"][0]["evidence_id"] if artifact["evidence"] else None
    trust["artifact"] = artifact
    return trust


def _context_answers(form, questionnaire, choices, problems):
    """Read scoring answers. Omit model training only when AI use is none."""
    assessment = {}
    applicability = {}
    ai_use = form.get("ai_use", "")
    for spec in questionnaire["context_questions"]:
        field = spec["field"]
        raw = form.get(field, "")
        if spec["ask"] == "when_ai_use_is_not_none" and ai_use == "none" and raw == "":
            assessment[field] = "no"
            applicability[field] = "not_applicable"
            continue
        if raw not in choices[field]:
            label = spec["prompt"].rstrip("?")
            problems.append(f"{label}: choose one of the listed options.")
            assessment[field] = raw
            continue
        assessment[field] = raw
    return assessment, applicability


def build_intake(form, as_of, *, open_url=None, resolver=None):
    """Validate the intake form and return claims, evidence, and assessment inputs.

    ``open_url`` and ``resolver`` are test hooks for a requested trust-center
    fetch. When they are omitted and fetch is yes, the standard library is used.
    """
    from app.services.intake_questionnaire import load_questionnaire

    questionnaire = load_questionnaire()
    problems = []
    vendor_name = (form.get("vendor_name") or "").strip()
    if not vendor_name:
        problems.append("Vendor or tool name is required.")
    elif len(vendor_name) > MAX_VENDOR_NAME:
        problems.append(f"Vendor or tool name must be {MAX_VENDOR_NAME} characters or fewer.")
    elif not vendor_name.isprintable():
        problems.append("Vendor or tool name contains unsupported characters.")

    choices = field_choices()
    assessment, applicability = _context_answers(form, questionnaire, choices, problems)
    for spec in load_org_policy()["intake_fields"]:
        field = spec["field"]
        value = form.get(field, "")
        if value not in choices[field]:
            problems.append(f"{spec['prompt']} Choose one of the listed options.")
        assessment[field] = value

    claims, evidence = [], []
    access = questionnaire["access_evidence"]
    access_option = form.get(access["field"], "")
    if access_option not in EVIDENCE_OPTIONS:
        problems.append("Evidence for the access claim: choose one of the listed options.")
    else:
        claim_id, _ = _ids(access["topic"])
        claims.append({"claim_id": claim_id, "topic": access["topic"],
                       "statement": access["statement"]})
        record = _evidence_record(access["topic"], access_option, as_of)
        if record is not None:
            evidence.append(record)

    trust = questionnaire["trust_center"]
    url, url_problems = _trust_center_url(form.get(trust["url_field"], ""), trust)
    problems.extend(url_problems)
    fetch_requested = _fetch_choice(form, trust, problems)
    pointers = []
    for pointer in trust["pointers"]:
        option = form.get(pointer["field"], "")
        if option not in trust["evidence_options"]:
            problems.append(f"{pointer['prompt']}: choose one of the listed options.")
            continue
        evidence_ids = []
        for topic_spec in pointer["topics"]:
            claim_id, _ = _ids(topic_spec["topic"])
            claims.append({"claim_id": claim_id, "topic": topic_spec["topic"],
                           "statement": topic_spec["statement"]})
            record = _trust_record(pointer, topic_spec["topic"], option, as_of, url)
            if record is not None:
                evidence.append(record)
                evidence_ids.append(record["evidence_id"])
        pointers.append({
            "pointer_id": pointer["pointer_id"],
            "prompt": pointer["prompt"],
            "option": option,
            "artifact_type": pointer["artifact_type"],
            "topics": [topic_spec["topic"] for topic_spec in pointer["topics"]],
            "evidence_ids": evidence_ids,
        })

    for clause in load_org_policy()["required_contract_clauses"]:
        field = clause_evidence_field(clause["clause_id"])
        option = form.get(field, "")
        if option not in CLAUSE_EVIDENCE_OPTIONS:
            problems.append(f"Evidence for {clause['clause_id']}: choose one of the listed options.")
            continue
        record = _clause_evidence_record(clause, option, as_of)
        if record is not None:
            evidence.append(record)

    fetched = False
    collection = "pasted_metadata"
    note = trust["result_notes"]["not_requested"]
    fetch = _empty_fetch()
    fetch_claim = None
    fetch_evidence = []
    if fetch_requested and not problems:
        fetched, collection, note, fetch, fetch_claim, fetch_evidence = _apply_fetch(
            url, trust, as_of, open_url, resolver, problems)

    if problems:
        raise IntakeError(problems)
    return {
        "vendor_name": vendor_name,
        "assessment": assessment,
        "answer_applicability": applicability,
        "claims": claims,
        "evidence": evidence,
        "questionnaire_version": questionnaire["questionnaire_version"],
        "trust_center": {
            "url": url,
            "fetched": bool(fetched),
            "collection": collection,
            "note": note,
            "pointers": pointers,
            "fetch": fetch,
            "fetch_claim": fetch_claim,
            "fetch_evidence": fetch_evidence,
        },
    }


def run_intake(intake, as_of):
    """Run a validated intake through the same services the full application uses."""
    policy = load_org_policy()
    checked = validate_assessment(intake["claims"], intake["evidence"], as_of,
                                  policy["required_contract_clauses"])
    risk = evaluate({**intake["assessment"], "claims": checked["claims"]},
                    clause_check=checked["clause_check"])
    trust_center = _review_fetch(intake["trust_center"], as_of)
    return {
        "scenario_id": None,
        "name": intake["vendor_name"],
        "summary": "Submitted through the public demo intake form. Synthetic input, not saved.",
        "synthetic_data": True,
        "as_of": as_of.isoformat(),
        "scenario_set_version": None,
        "questionnaire_version": intake["questionnaire_version"],
        "assessment_inputs": intake["assessment"],
        "answer_applicability": intake["answer_applicability"],
        "trust_center": trust_center,
        "evidence_policy_version": checked["evidence_policy_version"],
        "claims": checked["claims"],
        "risk": risk,
        "mappings": map_claims(checked["claims"]),
    }


def _clause_gaps(risk):
    clauses = risk["policy"]["required_contract_clauses"]
    return [clause for clause in clauses if clause.get("evidence_status") in GAP_STATUSES]


def remediation_payload(result):
    """A mock ServiceNow-style ticket payload, or None when no follow-up is needed."""
    risk = result["risk"]
    gaps = [c for c in result["claims"] if c["evidence_status"] in GAP_STATUSES]
    clause_gaps = _clause_gaps(risk)
    prohibited = risk["policy_outcome"]["status"] == "prohibited"
    fetch = (result.get("trust_center") or {}).get("fetch") or {}
    fetch_failed = fetch.get("outcome") == "failed"
    if not risk["escalations"] and not gaps and not prohibited and not clause_gaps and not fetch_failed:
        return None
    if prohibited:
        priority = "Policy restriction — human decision required"
        summary = f"Policy restriction follow-up: {result['name']}"
    else:
        priority = PRIORITY_BY_RESIDUAL_TIER[risk["residual"]["tier"]]
        summary = f"Vendor risk review follow-up: {result['name']}"
    return {
        "_demo_note": "Mock ServiceNow-style payload. Not sent to any system.",
        "short_description": summary,
        "category": "vendor_risk",
        "priority": priority,
        "assignment_group": "GRC Review (demo)",
        "review_path": risk["review_path"],
        "escalation_rules": [e["rule_id"] for e in risk["escalations"]],
        "policy_id": risk["policy"]["policy_id"],
        "policy_version": risk["policy"]["policy_version"],
        "policy_outcome": risk["policy_outcome"]["status"],
        "restrictions": [item["restriction_id"] for item in risk["policy_outcome"]["restrictions"]],
        "evidence_requests": [
            {"claim_id": c["claim_id"], "status": c["evidence_status"],
             "request": f"Provide current, reviewable evidence for: {c['statement']}"}
            for c in gaps
        ] + ([
            {"claim_id": FETCH_CLAIM_ID, "status": "missing",
             "request": (f"Trust center fetch failed: {fetch.get('error')} "
                         "This is an evidence gap, not a verified control.")}
        ] if fetch_failed else []),
        "contract_clauses": [
            {"clause_id": clause["clause_id"], "status": clause["evidence_status"],
             "request": (f"Provide current, reviewable evidence for required clause {clause['clause_id']}: "
                         f"{clause['text']}")}
            for clause in clause_gaps
        ],
        "related_controls": [m["control_id"] for m in result["mappings"]],
        "rule_set_version": risk["rule_set_version"],
        "evidence_policy_version": result["evidence_policy_version"],
        "evaluated_as_of": result["as_of"],
    }


def workflow_events(result):
    """The ordered workflow steps for one assessment, described from its results."""
    risk = result["risk"]
    counts = risk["evidence_confidence"]["counts"]
    summary = ", ".join(f"{n} {status.replace('_', ' ')}" for status, n in counts.items() if n)
    if risk["escalations"]:
        escalation = "Fired: " + ", ".join(e["rule_id"] for e in risk["escalations"]) + ". Escalated review required."
    else:
        escalation = "No escalation rule fired. Human review is still required."
    policy = risk["policy"]
    outcome = risk["policy_outcome"]
    clause_summary = ", ".join(
        f"{clause['clause_id']} {clause['evidence_status'].replace('_', ' ')}"
        for clause in policy["required_contract_clauses"]
    ) or "none listed"
    if outcome["status"] == "prohibited":
        ids = ", ".join(item["restriction_id"] for item in outcome["restrictions"])
        policy_detail = (f"Prohibited under {policy['policy_id']} {policy['policy_version']}: {ids}. "
                         f"Required contract clauses: {clause_summary}. "
                         "The score and residual tier are unchanged by this outcome.")
    else:
        policy_detail = (f"No hard restriction matched ({policy['policy_id']} {policy['policy_version']}). "
                         f"Required contract clauses: {clause_summary}.")
    evidence_detail = (f"Evidence policy {result['evidence_policy_version']}, evaluated as of "
                       f"{result['as_of']}: {summary or 'no claims'}.")
    trust_center = result.get("trust_center")
    fetch = (trust_center or {}).get("fetch") or {}
    if fetch.get("outcome") == "retrieved":
        evidence_detail += (" Trust center page fetched for review and marked not yet reviewed. "
                            "It is not verified evidence.")
    elif fetch.get("outcome") == "failed":
        evidence_detail += (f" Trust center fetch failed: {fetch.get('error')} "
                            "This is an evidence gap, not a successful collection.")
    elif trust_center and trust_center.get("url"):
        evidence_detail += " Trust center URL stored and not fetched."
    elif trust_center:
        evidence_detail += " Trust center artifact choices are pasted metadata and were not fetched."
    steps = [
        ("Intake received", f"{len(result['claims'])} claims recorded for {result['name']}."),
        ("Evidence validated", evidence_detail),
        ("Risk evaluated", f"Rule set {risk['rule_set_version']}: inherent {risk['inherent']['tier']}, "
                           f"evidence confidence {risk['evidence_confidence']['level']}, "
                           f"residual {risk['residual']['tier']}."),
        ("Policy check", policy_detail),
        ("Escalation check", escalation),
        ("Controls mapped", f"{len(result['mappings'])} draft NIST SP 800-53 mapping prompts matched by claim topic."),
    ]
    if remediation_payload(result):
        steps.append(("Remediation ticket drafted", "Mock ServiceNow-style payload prepared. Not sent to any system."))
    else:
        steps.append(("No remediation ticket", "No escalation, policy restriction, or evidence gap required follow-up."))
    return [{"step": index, "title": title, "detail": detail}
            for index, (title, detail) in enumerate(steps, start=1)]
