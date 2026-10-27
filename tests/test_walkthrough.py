"""Guided portfolio walkthrough: stops, coaching, and cookie progress.

The guide points at live pages. It does not score, and a stop does not save
a risk unless the visitor uses the existing opt-in control.
"""

import io
import json

from app.services.intake_importer import sample_file
from app.services.risk_engine import evaluate
from app.services.scenario_runner import list_scenarios, run_scenario
from app.services.walkthrough import (
    WALKTHROUGH_VERSION, carried_walk_step, known_step_id, neighbors, page_matches,
    progress_step_id, scenario_card_step, scenario_stop_id, step_by_id, steps,
    submission_pending, submission_satisfied,
)

SAME_ORIGIN = {"Origin": "http://localhost"}

GUIDED_PAGES = (
    ("/try/?walk=intake", "intake", "custom"),
    ("/try/?walk=custom", "custom", "trust"),
    ("/try/?walk=trust", "trust", "evidence"),
    ("/try/scenario/evidence-supported?walk=evidence", "evidence", "clause"),
    ("/try/scenario/contract-clause-conflict?walk=clause", "clause", "conflict"),
    ("/try/scenario/conflicting-claims?walk=conflict", "conflict", "high-risk"),
    ("/try/scenario/high-risk-ai?walk=high-risk", "high-risk", "prohibited"),
    ("/try/scenario/prohibited-ai-decisions?walk=prohibited", "prohibited", "save"),
    ("/try/import?walk=import", "import", "dashboard"),
    ("/?walk=dashboard", "dashboard", "methods"),
    ("/methodology?walk=methods", "methods", None),
)

FREE_FORM_PAGES = (
    "/try/",
    "/try/scenario/evidence-supported",
    "/try/scenario/contract-clause-conflict",
    "/try/scenario/conflicting-claims",
    "/try/import",
    "/demo/",
    "/demo/evidence-supported",
    "/demo/prohibited-ai-decisions",
    "/",
    "/methodology",
    "/risks",
)


def _clause(result):
    return result["risk"]["policy"]["required_contract_clauses"][0]["evidence_status"]


def test_stops_are_unique_ordered_and_point_at_real_endpoints(app):
    ordered = steps()
    assert [item["step_id"] for item in ordered] == [
        "intake", "custom", "trust", "evidence", "clause", "conflict", "high-risk",
        "prohibited", "save", "decide", "import", "dashboard", "methods",
    ]
    assert len({item["step_id"] for item in ordered}) == len(ordered)
    assert [item["number"] for item in ordered] == list(range(1, 14))
    assert WALKTHROUGH_VERSION == "1.2.2"
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    scenario_ids = {item["scenario_id"] for item in list_scenarios()}
    for step in ordered:
        assert step["endpoint"] in endpoints
        scenario_id = step["view_args"].get("scenario_id")
        if scenario_id:
            assert scenario_id in scenario_ids
    assert step_by_id("methods")["number"] == 13
    previous, following = neighbors("clause")
    assert previous["step_id"] == "evidence"
    assert following["step_id"] == "conflict"
    assert neighbors("intake")[1]["step_id"] == "custom"
    assert neighbors("custom")[1]["step_id"] == "trust"
    assert neighbors("trust")[1]["step_id"] == "evidence"
    assert neighbors("import")[1]["step_id"] == "dashboard"
    assert neighbors("intake")[0] is None
    assert neighbors("methods")[1] is None


def test_coaching_facts_still_match_the_live_scenarios():
    evidence = run_scenario("evidence-supported")
    clause = run_scenario("contract-clause-conflict")
    high = run_scenario("high-risk-ai")
    prohibited = run_scenario("prohibited-ai-decisions")
    conflict = run_scenario("conflicting-claims")

    assert _clause(evidence) == "verified"
    assert evidence["risk"]["inherent"]["tier"] == "low"
    assert evidence["risk"]["residual"]["tier"] == "low"
    assert evidence["risk"]["evidence_confidence"]["level"] == "high"
    assert evidence["risk"]["policy_outcome"]["status"] == "not_prohibited"

    assert _clause(clause) == "conflicting"
    bare = evaluate({**clause["assessment_inputs"], "claims": clause["claims"]})
    assert bare["inherent"] == clause["risk"]["inherent"]
    assert bare["residual"] == clause["risk"]["residual"]
    assert bare["review_path"] == clause["risk"]["review_path"]
    assert clause["risk"]["escalations"] == []

    permission = next(item for item in conflict["claims"] if item["claim_id"] == "C-PERM")
    assert permission["evidence_status"] == "conflicting"
    assert conflict["risk"]["residual"]["tier"] == "high"
    assert conflict["risk"]["review_path"] == "escalated_review"
    assert [item["rule_id"] for item in conflict["risk"]["escalations"]] == ["ESC-003"]
    assert conflict["risk"]["policy_outcome"]["status"] == "not_prohibited"

    assert high["risk"]["inherent"]["provisional"] is True
    assert high["risk"]["inherent"]["tier"] == "undetermined"
    assert high["risk"]["review_path"] == "escalated_review"
    assert {item["evidence_status"] for item in high["claims"]} == {"missing"}

    assert prohibited["risk"]["inherent"]["tier"] == "moderate"
    assert prohibited["risk"]["residual"]["tier"] == "low"
    assert prohibited["risk"]["policy_outcome"]["status"] == "prohibited"
    assert prohibited["risk"]["policy_outcome"]["restrictions"][0]["restriction_id"] == "HR-001"


def test_guide_copy_states_the_portfolio_limits():
    blob = "\n".join(f"{step['title']} {step['summary']} {step['notice']}" for step in steps()).lower()
    assert "production-ready" not in blob
    assert "certifies a vendor" in blob
    assert "not cash savings" in blob
    assert "opt-in" in blob
    assert "not verified evidence" in blob
    assert "not an approval" in blob
    assert "exception rationale" in blob
    assert "service now" not in blob
    assert "servicenow" in blob


def test_step_matching_and_carried_ids_reject_unknown_values():
    evidence = step_by_id("evidence")
    decide = step_by_id("decide")
    assert page_matches(evidence, "try_demo.scenario", {"scenario_id": "evidence-supported"})
    assert not page_matches(evidence, "try_demo.scenario", {"scenario_id": "high-risk-ai"})
    assert not page_matches(evidence, "try_demo.index", {})
    assert page_matches(decide, "risks.detail", {"risk_id": "R-1"})
    assert page_matches(decide, "risks.record_risk_decision", {"risk_id": "R-1"})
    assert not page_matches(decide, "demos.detail", {"scenario_id": "prohibited-ai-decisions"})
    custom = step_by_id("custom")
    trust = step_by_id("trust")
    intake = step_by_id("intake")
    assert page_matches(custom, "try_demo.index", {})
    assert page_matches(custom, "try_demo.assess", {})
    assert page_matches(trust, "try_demo.index", {})
    assert page_matches(trust, "try_demo.assess", {})
    assert page_matches(intake, "try_demo.index", {})
    assert page_matches(intake, "try_demo.assess", {})
    assert not page_matches(custom, "try_demo.scenario", {"scenario_id": "evidence-supported"})
    imported = step_by_id("import")
    assert page_matches(imported, "try_demo.import_form", {})
    assert page_matches(imported, "try_demo.import_preview", {})
    assert page_matches(imported, "try_demo.import_confirm", {})
    assert not page_matches(imported, "try_demo.index", {})
    assert carried_walk_step("import", advance_from="import") == "dashboard"
    assert known_step_id(" intake ") == "intake"
    assert known_step_id("nope") is None
    assert known_step_id(None) is None
    assert carried_walk_step("save", advance_from="save") == "decide"
    assert carried_walk_step("evidence", advance_from="save") == "evidence"
    assert carried_walk_step("methods", advance_from="methods") is None
    assert carried_walk_step("<script>") is None
    assert progress_step_id("evidence", "try_demo.scenario", {"scenario_id": "evidence-supported"}) == "evidence"
    assert progress_step_id("evidence", "try_demo.index", {}) is None
    assert progress_step_id("nope", "try_demo.index", {}) is None
    for step_id in ("intake", "custom", "trust", "import"):
        step = step_by_id(step_id)
        assert step["await_kind"] == "assessment"
        assert step["await_submission"] is True
        assert submission_pending(step, False) is True
        assert submission_pending(step, True) is False
        assert submission_satisfied(step, assessed=False) is False
        assert submission_satisfied(step, assessed=True) is True
        assert submission_satisfied(step, saved=True) is False
    save = step_by_id("save")
    decide = step_by_id("decide")
    assert save["await_kind"] == "register"
    assert decide["await_kind"] == "decision"
    assert submission_satisfied(save, saved=False) is False
    assert submission_satisfied(save, saved=True) is True
    assert submission_satisfied(save, assessed=True) is False
    assert submission_satisfied(decide, decided=False) is False
    assert submission_satisfied(decide, decided=True) is True
    assert submission_pending(save, False) is True
    assert submission_pending(decide, True) is False
    for step_id in ("evidence", "clause", "conflict", "high-risk", "prohibited", "dashboard", "methods"):
        step = step_by_id(step_id)
        assert step.get("await_submission") is not True
        assert submission_pending(step, False) is False
        assert submission_pending(step, True) is False
        assert submission_satisfied(step, assessed=True, saved=True, decided=True) is False
    assert scenario_stop_id("evidence-supported", "try_demo.scenario") == "evidence"
    assert scenario_stop_id("prohibited-ai-decisions", "try_demo.scenario") == "prohibited"
    assert scenario_stop_id("prohibited-ai-decisions", "demos.detail") == "save"
    assert scenario_stop_id("evidence-supported", "demos.detail") == "evidence"
    assert scenario_stop_id("missing", "try_demo.scenario") is None
    assert scenario_card_step("evidence-supported", "try_demo.scenario", None, True) is None
    assert scenario_card_step("evidence-supported", "try_demo.scenario", "nope", True) is None
    assert scenario_card_step("evidence-supported", "try_demo.scenario", "intake", True) == "intake"
    assert scenario_card_step("evidence-supported", "try_demo.scenario", "custom", True) == "custom"
    assert scenario_card_step("evidence-supported", "try_demo.scenario", "trust", True) == "trust"
    assert scenario_card_step("high-risk-ai", "try_demo.scenario", "evidence", False) == "high-risk"
    assert scenario_card_step("prohibited-ai-decisions", "demos.detail", "dashboard", True) == "save"
    assert scenario_card_step("evidence-supported", "demos.detail", "dashboard", True) == "evidence"
    assert scenario_card_step("evidence-supported", "demos.detail", "save", False) == "evidence"


def test_index_lists_every_stop_and_links_into_the_live_pages(client):
    assert client.get("/walkthrough").status_code == 200
    response = client.get("/walkthrough/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "VERSION 1.2.2" in body
    assert "13 stops" in body
    assert "Start at intake" in body
    assert 'href="/try/?walk=intake"' in body
    assert 'href="/try/?walk=custom#intake"' in body
    assert 'href="/try/?walk=trust#trust-center"' in body
    assert 'href="/try/scenario/evidence-supported?walk=evidence"' in body
    assert 'href="/try/scenario/contract-clause-conflict?walk=clause"' in body
    assert 'href="/try/scenario/conflicting-claims?walk=conflict"' in body
    assert 'href="/try/scenario/high-risk-ai?walk=high-risk"' in body
    assert 'href="/try/import?walk=import"' in body
    assert 'href="/try/scenario/prohibited-ai-decisions?walk=prohibited"' in body
    assert 'href="/demo/prohibited-ai-decisions?walk=save"' in body
    assert "Save the eligibility case first." in body
    assert 'href="/?walk=dashboard"' in body
    assert 'href="/methodology?walk=methods"' in body
    for step in steps():
        assert step["title"] in body
        assert step["summary"] in body
    assert 'action="/walkthrough/reset"' in body
    assert "not a stop here" not in body
    assert 'id="walkthrough-coach"' not in body


def test_home_and_public_demo_link_to_the_guide(client):
    home = client.get("/").get_data(as_text=True)
    public = client.get("/try/").get_data(as_text=True)
    assert 'href="/walkthrough/"' in home
    assert "Start the walkthrough" in home
    assert "Repeatable scenarios" in home
    assert 'href="/walkthrough/"' in public
    assert "start the guided walkthrough" in public


def test_free_form_pages_omit_the_coach(client):
    for path in FREE_FORM_PAGES:
        body = client.get(path).get_data(as_text=True)
        assert 'id="walkthrough-coach"' not in body, path
        assert "walk=" not in body, path


def test_each_guided_page_shows_its_note_and_the_next_stop(client):
    for path, step_id, following in GUIDED_PAGES:
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.get_data(as_text=True)
        assert f'data-step="{step_id}"' in body
        assert "This note is on another page" not in body
        number = next(item["number"] for item in steps() if item["step_id"] == step_id)
        assert f"STEP {number} OF {len(steps())}" in body
        assert "walk_step=" + step_id in response.headers.get("Set-Cookie", "")
        if step_id in {"intake", "custom", "trust", "import"}:
            notice = step_by_id(step_id)["pending_notice"]
            assert notice in body
            assert body.count('class="button-link walk-next"') == 0
            assert f"walk={following}" not in body
            assert "Finish" not in body
        elif following:
            assert f"walk={following}" in body
            assert "Finish" not in body
        else:
            assert ">Finish</a>" in body
            assert 'class="button-link walk-next" href="/walkthrough/"' in body
    intake = client.get("/try/?walk=intake").get_data(as_text=True)
    assert "walk-back" not in intake
    assert 'action="/try/assess?walk=intake"' in intake
    trust = client.get("/try/?walk=trust").get_data(as_text=True)
    assert "not verified evidence" in trust
    assert 'id="trust-center"' in trust
    clause = client.get("/try/scenario/contract-clause-conflict?walk=clause").get_data(as_text=True)
    assert "CC-001 is conflicting" in clause
    assert 'class="text-link walk-back" href="/try/scenario/evidence-supported?walk=evidence"' in clause


def test_unknown_or_mismatched_walk_does_not_move_progress_or_echo_the_value(client):
    junk = client.get("/try/?walk=%3Cscript%3Ealert(1)%3C/script%3E")
    junk_body = junk.get_data(as_text=True)
    assert junk.status_code == 200
    assert "walkthrough-coach" not in junk_body
    assert "alert(1)" not in junk_body
    assert "walk_step" not in junk.headers.get("Set-Cookie", "")

    mismatch = client.get("/try/?walk=evidence")
    body = mismatch.get_data(as_text=True)
    assert 'data-step="evidence"' in body
    assert "This note is on another page" in body
    assert "CC-001 is verified" not in body
    assert 'href="/try/scenario/evidence-supported?walk=evidence"' in body
    assert "walk_step" not in mismatch.headers.get("Set-Cookie", "")
    assert "Run assessment" in body


def test_ready_made_cards_keep_the_active_stop_or_the_scenario_stop(client):
    """A waiting stop keeps its query on the cards. Other guided pages use the scenario's stop.

    Free-form /try/ and /demo/ do not gain a walk query.
    """
    intake = client.get("/try/?walk=intake").get_data(as_text=True)
    assert 'href="/try/scenario/evidence-supported?walk=intake"' in intake
    assert 'href="/try/scenario/contract-clause-conflict?walk=intake"' in intake
    assert 'href="/try/scenario/conflicting-claims?walk=intake"' in intake
    assert 'href="/try/scenario/high-risk-ai?walk=intake"' in intake
    assert 'href="/try/scenario/prohibited-ai-decisions?walk=intake"' in intake
    assert 'href="/try/scenario/evidence-supported?walk=evidence"' not in intake
    assert 'href="/try/import?walk=intake"' in intake
    assert 'action="/try/assess?walk=intake"' in intake

    custom = client.get("/try/?walk=custom").get_data(as_text=True)
    assert 'href="/try/scenario/high-risk-ai?walk=custom"' in custom
    assert 'href="/try/scenario/evidence-supported?walk=intake"' not in custom
    assert "walk=trust" not in custom
    trust = client.get("/try/?walk=trust").get_data(as_text=True)
    assert 'href="/try/scenario/evidence-supported?walk=trust"' in trust
    assert "walk=evidence" not in trust

    opened = client.get("/try/scenario/evidence-supported?walk=intake")
    opened_body = opened.get_data(as_text=True)
    assert 'data-step="intake"' in opened_body
    assert "This note is on another page" in opened_body
    assert "Run assessment on this page before Next." in opened_body
    assert "walk=custom" not in opened_body
    assert 'href="/try/?walk=intake"' in opened_body
    assert "walk_step" not in opened.headers.get("Set-Cookie", "")

    parked = client.get("/try/import?walk=custom")
    parked_body = parked.get_data(as_text=True)
    assert 'data-step="custom"' in parked_body
    assert "Run assessment on this page before Next." in parked_body
    assert parked_body.count('class="button-link walk-next"') == 1
    assert 'href="/try/?walk=custom#intake"' in parked_body
    assert "walk=trust" not in parked_body

    mismatch = client.get("/try/?walk=evidence").get_data(as_text=True)
    assert 'href="/try/scenario/evidence-supported?walk=evidence"' in mismatch
    assert 'href="/try/scenario/conflicting-claims?walk=conflict"' in mismatch
    assert 'href="/try/import?walk=import"' in mismatch
    assert 'href="/try/scenario/evidence-supported?walk=intake"' not in mismatch

    home = client.get("/?walk=dashboard").get_data(as_text=True)
    assert 'href="/try/scenario/evidence-supported?walk=evidence"' in home
    assert 'href="/try/scenario/contract-clause-conflict?walk=clause"' in home
    assert 'href="/try/scenario/conflicting-claims?walk=conflict"' in home
    assert 'href="/try/scenario/high-risk-ai?walk=high-risk"' in home
    assert 'href="/demo/prohibited-ai-decisions?walk=save"' in home
    assert 'href="/demo/evidence-supported"' not in home
    assert 'data-step="dashboard"' in home
    assert "walk=methods" in home

    demo = client.get("/demo/?walk=save").get_data(as_text=True)
    assert 'href="/demo/prohibited-ai-decisions?walk=save"' in demo
    assert 'href="/try/scenario/evidence-supported?walk=evidence"' in demo
    assert 'data-step="save"' in demo
    assert "Add to risk register continues the guide" in demo

    free_try = client.get("/try/").get_data(as_text=True)
    free_demo = client.get("/demo/").get_data(as_text=True)
    free_home = client.get("/").get_data(as_text=True)
    assert 'href="/try/scenario/evidence-supported"' in free_try
    assert 'href="/try/import"' in free_try
    assert "walk=" not in free_try
    assert 'href="/demo/prohibited-ai-decisions"' in free_demo
    assert 'href="/demo/evidence-supported"' in free_demo
    assert "walk=" not in free_demo
    assert 'href="/demo/evidence-supported"' in free_home
    assert "walk=" not in free_home


def test_cookie_remembers_the_last_opened_stop_until_reset(client):
    opened = client.get("/try/scenario/high-risk-ai?walk=high-risk")
    assert "walk_step=high-risk" in opened.headers.get("Set-Cookie", "")
    assert "HttpOnly" in opened.headers.get("Set-Cookie", "")
    assert "SameSite=Lax" in opened.headers.get("Set-Cookie", "")
    index = client.get("/walkthrough/")
    body = index.get_data(as_text=True)
    assert "Continue · Review a score cannot skip" in body
    assert 'aria-current="step"' in body
    assert client.get("/walkthrough/reset").status_code == 405
    rejected = client.post("/walkthrough/reset")
    assert rejected.status_code == 403
    still = client.get("/walkthrough/").get_data(as_text=True)
    assert "Continue · Review a score cannot skip" in still
    reset = client.post("/walkthrough/reset", headers=SAME_ORIGIN)
    assert reset.status_code == 302
    assert reset.headers["Location"].endswith("/walkthrough/")
    cleared = client.get("/walkthrough/")
    assert "Start at intake" in cleared.get_data(as_text=True)
    assert "Continue ·" not in cleared.get_data(as_text=True)


def test_save_stop_holds_until_the_existing_register_action(client):
    before = client.get("/demo/prohibited-ai-decisions?walk=save")
    body = before.get_data(as_text=True)
    assert before.status_code == 200
    assert "Saving is opt-in" in body
    assert "Add to risk register continues the guide" in body
    assert 'action="/demo/prohibited-ai-decisions/register?walk=save"' in body
    assert "walk=decide" not in body
    plain = client.get("/demo/prohibited-ai-decisions").get_data(as_text=True)
    assert 'action="/demo/prohibited-ai-decisions/register"' in plain
    assert "walk=" not in plain


def test_register_advances_the_guide_and_a_plain_save_does_not(client):
    plain = client.post("/demo/evidence-supported/register", headers=SAME_ORIGIN)
    assert plain.status_code == 302
    assert "walk=" not in plain.headers["Location"]

    crafted = client.post("/demo/high-risk-ai/register?walk=not-a-step", headers=SAME_ORIGIN)
    assert crafted.status_code == 302
    assert "walk=" not in crafted.headers["Location"]

    kept = client.post(
        "/demo/contract-clause-conflict/register?walk=clause", headers=SAME_ORIGIN,
    )
    assert kept.status_code == 302
    assert kept.headers["Location"].endswith("?walk=clause")

    guided = client.post(
        "/demo/prohibited-ai-decisions/register?walk=save", headers=SAME_ORIGIN,
    )
    assert guided.status_code == 302
    location = guided.headers["Location"]
    assert "/risks/" in location
    assert location.endswith("?walk=decide")
    page = client.get(location)
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert 'data-step="decide"' in body
    assert "exception rationale" in body
    assert "nothing is sent to ServiceNow" in body
    assert "Record a decision on this page before Next." in body
    assert 'name="handling_minutes"' in body
    assert "minutes spent reviewing" in body
    assert 'name="handling_minutes" required' not in body
    assert body.count('class="button-link walk-next"') == 0
    assert "walk=import" not in body
    assert f'action="{location.split("?")[0]}/decision?walk=decide"' in body
    risk_url = location.split("?", 1)[0]
    refused = client.post(f"{risk_url}/decision?walk=decide", data={
        "disposition": "approve",
        "rationale": "The score is not the decision.",
        "decider": "Portfolio reviewer",
        "conditions": "",
        "exception_rationale": "",
    }, headers=SAME_ORIGIN)
    assert refused.status_code == 400
    refused_body = refused.get_data(as_text=True)
    assert 'data-step="decide"' in refused_body
    assert "This note is on another page" not in refused_body
    assert "Decision not recorded." in refused_body
    assert "exception rationale" in refused_body
    assert "Record a decision on this page before Next." in refused_body
    assert refused_body.count('class="button-link walk-next"') == 0
    assert f'action="{risk_url}/decision?walk=decide"' in refused_body
    assert "walk_step" not in refused.headers.get("Set-Cookie", "")
    recorded = client.post(f"{risk_url}/decision?walk=decide", data={
        "disposition": "escalate",
        "rationale": "The score is not the decision.",
        "decider": "Portfolio reviewer",
        "conditions": "",
        "exception_rationale": "",
    }, headers=SAME_ORIGIN)
    assert recorded.status_code == 302
    assert recorded.headers["Location"].endswith("?walk=decide")
    done = client.get(recorded.headers["Location"])
    done_body = done.get_data(as_text=True)
    assert "Record a decision on this page before Next." not in done_body
    assert done_body.count('class="button-link walk-next"') == 2
    assert "walk=import" in done_body
    assert "Next · File import" in done_body
    resumed = client.get("/demo/prohibited-ai-decisions?walk=save")
    assert "walk=decide" in resumed.get_data(as_text=True)
    home = client.get("/walkthrough/").get_data(as_text=True)
    assert "Save the eligibility case first." not in home
    assert "?walk=decide" in home


def test_decision_and_remediation_redirects_keep_only_a_known_stop(client, app):
    guided = client.post(
        "/demo/prohibited-ai-decisions/register?walk=save", headers=SAME_ORIGIN,
    )
    risk_url = guided.headers["Location"].split("?", 1)[0]
    risk_id = risk_url.rsplit("/", 1)[-1]
    saved = client.post(f"{risk_url}/decision?walk=decide", data={
        "disposition": "escalate",
        "rationale": "The score is not the decision.",
        "decider": "Portfolio reviewer",
        "conditions": "",
        "exception_rationale": "",
    }, headers=SAME_ORIGIN)
    assert saved.status_code == 302
    assert saved.headers["Location"].endswith(f"/risks/{risk_id}?walk=decide")
    dropped = client.post(f"{risk_url}/decision?walk=nope", data={
        "disposition": "reject",
        "rationale": "Outside the illustrated policy.",
        "decider": "Portfolio reviewer",
        "conditions": "",
        "exception_rationale": "",
    }, headers=SAME_ORIGIN)
    assert dropped.status_code == 302
    assert "walk=" not in dropped.headers["Location"]

    from app.db import get_db
    from app.services.workflow_service import get_risk
    with app.app_context():
        action_id = get_risk(get_db(), risk_id)["actions"][0]["action_id"]
    detail = client.get(f"{risk_url}?walk=decide").get_data(as_text=True)
    assert f'action="/remediation/{action_id}?walk=decide"' in detail
    updated = client.post(f"/remediation/{action_id}?walk=decide", data={
        "risk_id": risk_id, "status": "in_progress", "owner": "Portfolio reviewer",
        "due_date": "2026-11-01", "completion_notes": "",
    }, headers=SAME_ORIGIN)
    assert updated.status_code == 302
    assert updated.headers["Location"].endswith(f"/risks/{risk_id}?walk=decide")
    untouched = client.post(f"/remediation/{action_id}", data={
        "risk_id": risk_id, "status": "in_progress", "owner": "Portfolio reviewer",
        "due_date": "2026-11-02", "completion_notes": "",
    }, headers=SAME_ORIGIN)
    assert untouched.status_code == 302
    assert "walk=" not in untouched.headers["Location"]


def _low_form(**overrides):
    from app.services.intake_builder import clause_evidence_field
    from app.services.org_policy import load_org_policy

    base = {
        "vendor_name": "Harbor Notes",
        "data_sensitivity": "internal",
        "integration_permissions": "read_only",
        "ai_use": "none",
        "model_training_on_customer_data": "no",
        "external_exposure": "internal_only",
        "retention_deletion": "documented",
        "decisions_affecting_people": "no",
        "evidence_integration_permissions": "independent_verified",
        "trust_center_url": "",
        "fetch_trust_center": "no",
        "trust_soc2": "independent_verified",
        "trust_security": "independent_verified",
        "trust_privacy": "independent_verified",
    }
    for clause in load_org_policy()["required_contract_clauses"]:
        base[clause_evidence_field(clause["clause_id"])] = "independent_verified"
    base.update(overrides)
    return base


def test_form_stops_hold_next_until_the_assessment_succeeds(client):
    """Next stays off until this response is a successful assessment.

    The intake submit used to render the other-page note because that stop
    did not treat ``POST /try/assess`` as its own page. A validation error
    stays on the stop and still withholds Next. The cookie keeps the stop
    id and does not move to the following stop.
    """
    guided = (
        ("intake", "custom", "Your own vendor", "/try/?walk=custom#intake"),
        ("custom", "trust", "Trust center is optional", "/try/?walk=trust#trust-center"),
        ("trust", "evidence", "Four separate results",
         "/try/scenario/evidence-supported?walk=evidence"),
    )
    for step_id, following, next_title, next_href in guided:
        opened = client.get(f"/try/?walk={step_id}")
        assert f"walk_step={step_id}" in opened.headers.get("Set-Cookie", "")
        refused = client.post(
            f"/try/assess?walk={step_id}",
            data=_low_form(vendor_name=""),
            headers=SAME_ORIGIN,
        )
        assert refused.status_code == 400
        refused_body = refused.get_data(as_text=True)
        assert f'data-step="{step_id}"' in refused_body
        assert "This note is on another page" not in refused_body
        assert "Vendor or tool name is required." in refused_body
        assert refused_body.count('class="button-link walk-next"') == 0
        assert f'action="/try/assess?walk={step_id}"' in refused_body
        assert "walk_step" not in refused.headers.get("Set-Cookie", "")

        vendor = f"Harbor {step_id}"
        posted = client.post(
            f"/try/assess?walk={step_id}",
            data=_low_form(vendor_name=vendor),
            headers=SAME_ORIGIN,
        )
        assert posted.status_code == 200, step_id
        result = posted.get_data(as_text=True)
        assert f'data-step="{step_id}"' in result
        assert "This note is on another page" not in result
        assert "Run assessment on this page before Next." not in result
        assert result.count('class="button-link walk-next"') == 2
        assert f'href="{next_href}"' in result
        assert f"Next · {next_title}" in result
        assert f"walk={following}" in result
        assert "INHERENT RISK" in result
        assert "walk_step" not in posted.headers.get("Set-Cookie", "")
        assert vendor not in client.get("/risks").get_data(as_text=True)
        home = client.get("/walkthrough/").get_data(as_text=True)
        title = next(item["title"] for item in steps() if item["step_id"] == step_id)
        assert f"Continue · {title}" in home


def test_custom_vendor_keeps_the_coach_and_does_not_save(client):
    page = client.get("/try/?walk=custom")
    body = page.get_data(as_text=True)
    assert 'data-step="custom"' in body
    assert 'id="intake"' in body
    assert 'action="/try/assess?walk=custom"' in body
    assert "Use a made-up vendor name." in body
    assert "does not save" in body
    assert "not an approval" in body
    posted = client.post("/try/assess?walk=custom", data=_low_form(), headers=SAME_ORIGIN)
    assert posted.status_code == 200
    result = posted.get_data(as_text=True)
    assert 'data-step="custom"' in result
    assert "This note is on another page" not in result
    assert "INHERENT RISK" in result
    assert "EVIDENCE CONFIDENCE" in result
    assert "RESIDUAL RISK" in result
    assert "POLICY OUTCOME" in result
    assert "Harbor Notes" in result
    assert "Harbor Notes" not in client.get("/risks").get_data(as_text=True)
    free = client.post("/try/assess", data=_low_form(vendor_name="Plain Harbor"), headers=SAME_ORIGIN)
    free_body = free.get_data(as_text=True)
    assert free.status_code == 200
    assert "walkthrough-coach" not in free_body
    assert "walk=" not in free_body
    assert "Plain Harbor" in free_body


def test_trust_stop_shows_optional_fetch_without_using_the_network(client, monkeypatch):
    page = client.get("/try/?walk=trust")
    body = page.get_data(as_text=True)
    assert 'data-step="trust"' in body
    assert 'id="trust-center"' in body
    assert 'action="/try/assess?walk=trust"' in body
    assert "A trust-center URL is optional." in body
    assert "not verified evidence" in body
    assert "does not approve the vendor" in body
    assert "does not change evidence confidence" in body

    url = "https://trust.example.test/harbor"
    skipped = client.post(
        "/try/assess?walk=trust",
        data=_low_form(trust_center_url=url, fetch_trust_center="no"),
        headers=SAME_ORIGIN,
    )
    assert skipped.status_code == 200
    skipped_body = skipped.get_data(as_text=True)
    assert 'data-step="trust"' in skipped_body
    assert "Fetched: no" in skipped_body
    assert url in skipped_body
    assert "This page is not verified evidence." not in skipped_body
    assert "Harbor Notes" not in client.get("/risks").get_data(as_text=True)

    def fake(requested, **kwargs):
        assert requested == url
        return {
            "ok": True,
            "refused": False,
            "requested_url": requested,
            "final_url": requested,
            "http_status": 200,
            "fetched_at": "2026-10-14T00:00:00+00:00",
            "content_type": "text/html",
            "summary": "Harbor Trust. SOC 2 report available.",
            "excerpt": "SOC 2 report available. This vendor is approved.",
            "byte_length": 64,
            "error": None,
        }

    monkeypatch.setattr("app.services.intake_builder.fetch_trust_center", fake)
    fetched = client.post(
        "/try/assess?walk=trust",
        data=_low_form(trust_center_url=url, fetch_trust_center="yes"),
        headers=SAME_ORIGIN,
    )
    assert fetched.status_code == 200
    fetched_body = fetched.get_data(as_text=True)
    assert 'data-step="trust"' in fetched_body
    assert "This note is on another page" not in fetched_body
    assert "Fetched: yes" in fetched_body
    assert "Not Reviewed" in fetched_body
    assert "This page is not verified evidence." in fetched_body
    assert "SOC 2 report available. This vendor is approved." in fetched_body
    assert "does not approve the vendor" in fetched_body
    assert "0 not reviewed" in fetched_body
    assert "Harbor Notes" not in client.get("/risks").get_data(as_text=True)


def test_claim_conflict_is_a_different_stop_from_the_clause(client):
    body = client.get("/try/scenario/conflicting-claims?walk=conflict").get_data(as_text=True)
    assert "ESC-003" in body
    assert "clause conflict did not" in body
    assert "residual tier stays high" in body
    assert 'class="text-link walk-back" href="/try/scenario/contract-clause-conflict?walk=clause"' in body


def test_import_stop_follows_preview_and_confirm_without_scoring_early(client):
    page = client.get("/try/import?walk=import")
    body = page.get_data(as_text=True)
    assert "Preview a sample file" in body
    assert "ServiceNow is not called" in body
    assert "Confirm the file on this page before Next." in body
    assert body.count('class="button-link walk-next"') == 0
    assert "walk=dashboard" not in body
    assert 'action="/try/import/preview?walk=import"' in body
    assert 'href="/try/import/sample/json"' in body
    plain = client.get("/try/import").get_data(as_text=True)
    assert 'action="/try/import/preview"' in plain
    assert "walk=" not in plain

    rejected = client.post(
        "/try/import/preview?walk=import",
        data={"intake_file": (io.BytesIO(b""), "")},
        headers=SAME_ORIGIN,
    )
    assert rejected.status_code == 400
    rejected_body = rejected.get_data(as_text=True)
    assert 'data-step="import"' in rejected_body
    assert "This note is on another page" not in rejected_body
    assert "Choose a CSV" in rejected_body
    assert "Confirm the file on this page before Next." in rejected_body
    assert rejected_body.count('class="button-link walk-next"') == 0
    assert "walk_step" not in rejected.headers.get("Set-Cookie", "")

    preview = client.post(
        "/try/import/preview?walk=import",
        data={"intake_file": (io.BytesIO(sample_file("json")), "servicenow-intake.json")},
        headers=SAME_ORIGIN,
    )
    assert preview.status_code == 200
    preview_body = preview.get_data(as_text=True)
    assert 'data-step="import"' in preview_body
    assert "This note is on another page" not in preview_body
    assert "INHERENT RISK" not in preview_body
    assert "do not set residual risk" in preview_body
    assert "Confirm the file on this page before Next." in preview_body
    assert preview_body.count('class="button-link walk-next"') == 0
    assert "walk=dashboard" not in preview_body
    assert 'action="/try/import/confirm?walk=import"' in preview_body

    start = preview.data.index(b"<textarea")
    snippet = preview.data[start:preview.data.index(b"</textarea>", start)]
    document = json.loads(snippet.split(b">", 1)[1])
    confirmed = client.post(
        "/try/import/confirm?walk=import",
        data={"confirmation": json.dumps(document)},
        headers=SAME_ORIGIN,
    )
    assert confirmed.status_code == 200
    confirmed_body = confirmed.get_data(as_text=True)
    assert 'data-step="import"' in confirmed_body
    assert "This note is on another page" not in confirmed_body
    assert "INHERENT RISK" in confirmed_body
    assert "does not save" in confirmed_body
    assert "Confirm the file on this page before Next." not in confirmed_body
    assert confirmed_body.count('class="button-link walk-next"') == 2
    assert 'href="/?walk=dashboard"' in confirmed_body
    assert "Next · Measured and modeled" in confirmed_body
    assert 'action="/try/import/save?walk=import"' in confirmed_body
    assert 'href="/try/import?walk=import"' in confirmed_body
    again = client.get("/try/import?walk=import")
    assert "Confirm the file on this page before Next." in again.get_data(as_text=True)
    assert again.get_data(as_text=True).count('class="button-link walk-next"') == 0
    row = document["rows"][0]
    saved = client.post("/try/import/save?walk=import", data={
        "confirmation": json.dumps(document),
        "source_row": row["row_number"],
        "persist": "yes",
        "disposition": "escalate",
        "rationale": "The file is not an approval.",
        "decider": "Portfolio reviewer",
    }, headers=SAME_ORIGIN)
    assert saved.status_code == 302
    assert saved.headers["Location"].endswith("?walk=dashboard")
    unsaved = client.post("/try/import/save?walk=import", data={
        "confirmation": json.dumps(document),
        "source_row": row["row_number"],
        "disposition": "escalate",
        "rationale": "The checkbox was not checked.",
        "decider": "Portfolio reviewer",
    }, headers=SAME_ORIGIN)
    assert unsaved.status_code == 400
    unsaved_body = unsaved.get_data(as_text=True)
    assert 'data-step="import"' in unsaved_body
    assert "Nothing was saved" in unsaved_body
    assert "Confirm the file on this page before Next." not in unsaved_body
    assert "walk=dashboard" in unsaved_body
    plain_saved = client.post("/try/import/save", data={
        "confirmation": json.dumps(document),
        "source_row": row["row_number"],
        "persist": "yes",
        "disposition": "escalate",
        "rationale": "Still not an approval.",
        "decider": "Portfolio reviewer",
    }, headers=SAME_ORIGIN)
    assert plain_saved.status_code == 302
    assert "walk=" not in plain_saved.headers["Location"]


def test_reset_clears_the_cookie_and_leaves_the_register_alone(client):
    client.post("/demo/prohibited-ai-decisions/register?walk=save", headers=SAME_ORIGIN)
    client.get("/risks?walk=decide")
    assert b"AI tool that decides eligibility" in client.get("/risks").data
    client.post("/walkthrough/reset", headers=SAME_ORIGIN)
    assert b"AI tool that decides eligibility" in client.get("/risks").data
    assert "Continue ·" not in client.get("/walkthrough/").get_data(as_text=True)
