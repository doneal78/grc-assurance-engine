"""Reviewer-facing copy: so-what, rule rationale, dashboard labels, and re-run.

These checks lock the explanation and the form replay. They do not retune scores.
"""

import html

from app.services.intake_builder import build_intake, run_intake
from app.services.intake_replay import query_form, replay_plan
from app.services.result_explain import (
    claim_so_what, escalation_rationale, factor_lines, mapping_so_what, residual_plain,
)
from app.services.scenario_runner import run_scenario
from tests.test_try_demo import AS_OF, SAME_ORIGIN, form


def _href(body, marker="Change these answers"):
    """Return the link before the marker, with HTML escapes decoded."""
    anchor = body.split(marker, 1)[0]
    raw = anchor.rsplit('href="', 1)[-1].split('"', 1)[0]
    return html.unescape(raw)


def test_explanations_restate_the_engine_without_changing_it():
    supported = run_scenario("evidence-supported")
    conflict = run_scenario("conflicting-claims")
    prohibited = run_scenario("prohibited-ai-decisions")
    before = conflict["risk"]["residual"]["tier"], conflict["risk"]["residual"]["reason"], conflict["risk"]["inherent"]["score"]

    low = residual_plain(supported["risk"])
    assert supported["risk"]["residual"]["reason"] in low
    assert "not an approval" in low
    assert "one tier below" not in low

    stayed = residual_plain(conflict["risk"])
    assert conflict["risk"]["residual"]["tier"] == "high"
    assert "Not lowered" in stayed
    assert "stays high" in stayed
    assert "one tier below" not in stayed
    assert "claim evidence, not a contract-clause status" in stayed

    blocked = residual_plain(prohibited["risk"])
    assert prohibited["risk"]["residual"]["tier"] == "low"
    assert prohibited["risk"]["residual"]["reason"] in blocked
    assert "not an approval" in blocked
    assert "hard restriction can still prohibit" in blocked

    lines = factor_lines(conflict["risk"], conflict["assessment_inputs"])
    data = next(line for line in lines if line["rule_id"] == "INH-DATA")
    assert "confidential" in data["rationale"]
    assert f"adds {data['points']}" in data["rationale"]
    perm = next(line for line in lines if line["rule_id"] == "INH-PERM")
    assert "admin" in perm["rationale"]

    fired = next(item for item in conflict["risk"]["escalations"] if item["rule_id"] == "ESC-003")
    rationale = escalation_rationale(fired, conflict["assessment_inputs"], conflict["claims"])
    assert "Fired because" in rationale
    assert "conflicting" in rationale
    assert "read-only access" in rationale
    assert "not an approval" in rationale

    missing = next(claim for claim in run_scenario("high-risk-ai")["claims"] if claim["evidence_status"] == "missing")
    assert "not a confirmed control failure" in claim_so_what(missing)
    conflicting = next(claim for claim in conflict["claims"] if claim["evidence_status"] == "conflicting")
    assert "cannot rely" in claim_so_what(conflicting)
    mapped = next(item for item in conflict["mappings"] if item["control_id"] == "AC-6")
    meaning = mapping_so_what(mapped)
    assert "broader than the job" in meaning
    assert "conflicting" in meaning
    assert "not a certification" in meaning

    assert (conflict["risk"]["residual"]["tier"], conflict["risk"]["residual"]["reason"], conflict["risk"]["inherent"]["score"]) == before


def test_exact_replay_preserves_the_score_and_drops_unknown_fields():
    payload = form(
        data_sensitivity="restricted", integration_permissions="admin", ai_use="autonomous",
        model_training_on_customer_data="yes", decisions_affecting_people="yes",
        evidence_integration_permissions="contradicts",
    )
    payload["not_a_field"] = "ignore-me"
    plan = replay_plan({"name": "Ignored"}, payload)
    assert plan["kind"] == "exact"
    assert "not_a_field" not in plan["fields"]
    assert plan["fields"]["data_sensitivity"] == "restricted"
    assert plan["fields"]["decisions_affecting_people"] == "yes"
    original = run_intake(build_intake(payload, AS_OF), AS_OF)
    replayed = run_intake(build_intake(plan["fields"], AS_OF), AS_OF)
    assert replayed["risk"]["inherent"] == original["risk"]["inherent"]
    assert replayed["risk"]["residual"] == original["risk"]["residual"]
    assert [item["rule_id"] for item in replayed["risk"]["escalations"]] == [
        item["rule_id"] for item in original["risk"]["escalations"]
    ]
    assert replayed["risk"]["policy_outcome"]["status"] == "prohibited"


def test_scenario_replay_copies_answers_and_does_not_invent_verified_evidence():
    result = run_scenario("evidence-supported")
    plan = replay_plan(result)
    assert plan["kind"] == "approximate"
    assert plan["fields"]["data_sensitivity"] == "internal"
    assert plan["fields"]["ai_use"] == "none"
    assert plan["fields"]["decisions_affecting_people"] == "no"
    assert plan["fields"]["fetch_trust_center"] == "no"
    assert plan["fields"]["evidence_integration_permissions"] == "independent_verified"
    # Authentication is verified and logging is absent, so one SOC choice cannot be verified.
    assert plan["fields"]["trust_soc2"] == "none"
    assert "do not share one evidence status" in plan["note"]
    assert "not an approval" in plan["note"]

    high = replay_plan(run_scenario("high-risk-ai"))
    assert high["fields"]["data_sensitivity"] == "restricted"
    assert high["fields"]["integration_permissions"] == "admin"
    assert high["fields"]["model_training_on_customer_data"] == "unknown"
    assert high["fields"]["evidence_integration_permissions"] == "none"
    assert high["fields"]["fetch_trust_center"] == "no"

    empty = replay_plan({"risk": {}, "claims": []})
    assert empty["kind"] == "unavailable"
    assert empty["fields"] == {}


def test_query_prefill_keeps_only_real_form_choices():
    fields, note = query_form({
        "data_sensitivity": "restricted",
        "vendor_name": "Northwind Notes",
        "walk": "custom",
        "not_a_field": "nope",
        "integration_permissions": "not-a-level",
    })
    assert fields["data_sensitivity"] == "restricted"
    assert fields["vendor_name"] == "Northwind Notes"
    assert "walk" not in fields
    assert "not_a_field" not in fields
    assert "integration_permissions" not in fields
    assert "not saved" in note

    ignored, quiet = query_form({"walk": "intake", "data_sensitivity": "not-a-tier"})
    assert ignored == {}
    assert quiet == ""


def test_result_page_explains_rules_and_offers_a_prefilled_rerun(client):
    supported = run_scenario("evidence-supported")
    page = client.get("/try/scenario/evidence-supported")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert f"Score {supported['risk']['inherent']['score']}" in body
    assert supported["risk"]["residual"]["reason"] in body
    assert 'id="why-this-result"' in body
    assert 'id="claims-and-evidence"' in body
    assert 'id="control-mappings"' in body
    assert "So what:" in body
    assert "broader than the job" in body
    assert "walk=" not in body
    href = _href(body)
    assert "data_sensitivity=internal" in href
    assert href.startswith("/try/?")
    assert href.endswith("#intake")

    opened = client.get(href.split("#", 1)[0])
    opened_body = opened.get_data(as_text=True)
    assert 'value="internal" selected' in opened_body
    assert "Answers filled in from a previous result" in opened_body
    assert "walk=" not in opened_body

    conflict = client.get("/try/scenario/conflicting-claims").get_data(as_text=True)
    assert "ESC-003" in conflict
    assert "Fired because" in conflict
    assert "read-only access" in conflict
    assert "stays high" in conflict

    clause = client.get("/try/scenario/contract-clause-conflict").get_data(as_text=True)
    assert "claim evidence, not a contract-clause status" in clause
    assert "does not change the inherent score" in clause

    prohibited = client.get("/try/scenario/prohibited-ai-decisions").get_data(as_text=True)
    assert "does not clear the restriction" in prohibited
    assert "not an approval" in prohibited
    assert "HR-001" in prohibited


def test_posted_rerun_keeps_a_form_walk_stop_and_refills_the_form(client):
    posted = client.post("/try/assess?walk=custom", data=form(vendor_name="Harbor Notes"), headers=SAME_ORIGIN)
    body = posted.get_data(as_text=True)
    assert posted.status_code == 200
    assert 'data-step="custom"' in body
    href = _href(body)
    assert "walk=custom" in href
    assert "vendor_name=Harbor" in href
    assert "data_sensitivity=internal" in href
    assert "walk=trust" not in href
    reopened = client.get(href.split("#", 1)[0])
    reopened_body = reopened.get_data(as_text=True)
    assert 'action="/try/assess?walk=custom"' in reopened_body
    assert 'value="Harbor Notes"' in reopened_body
    assert "walk=trust" not in reopened_body
    assert reopened_body.count('class="button-link walk-next"') == 0


def test_saved_risk_rerun_prefills_without_a_walk_query(client):
    saved = client.post("/demo/evidence-supported/register", headers=SAME_ORIGIN)
    assert saved.status_code == 302
    detail = client.get(saved.headers["Location"]).get_data(as_text=True)
    assert "Why this result" in detail
    assert "So what:" in detail
    assert "Change these answers" in detail
    href = _href(detail)
    assert "walk=" not in href
    assert "data_sensitivity=internal" in href
    assert "walk=" not in detail
    opened = client.get(href.split("#", 1)[0])
    assert 'value="internal" selected' in opened.get_data(as_text=True)


def test_dashboard_distinguishes_volume_from_saved_decisions(client):
    body = client.get("/").get_data(as_text=True)
    assert "SAVED ASSESSMENT VOLUME" in body
    assert "SAVED DECISIONS" in body
    assert "Saved assessments: 0." in body
    assert "Persisted dispositions: 0." in body
    assert "not the assessment volume" in body
    assert "A public <code>/try/</code> run that is not saved is in neither number" in body
    assert "modeled assessments/month (an assumption, not the saved assessment volume" in body
    methods = client.get("/methodology").get_data(as_text=True)
    assert "A public <code>/try/</code> run that is not saved is in neither count" in methods
    assert "modeled assessments per month (an assumption, not the saved assessment volume)" in methods


def test_prefill_escapes_a_vendor_name_and_ignores_a_bogus_choice(client):
    page = client.get("/try/?vendor_name=%3Cscript%3Ealert(1)%3C/script%3E&data_sensitivity=not-a-tier")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert 'value="&lt;script&gt;alert(1)&lt;/script&gt;"' in body
    assert 'value="<script>' not in body
    assert "not-a-tier" not in body
