"""Guided portfolio walkthrough: stops, coaching, and cookie progress.

The guide points at live pages. It does not score, and a stop does not save
a risk unless the visitor uses the existing opt-in control.
"""

from app.services.risk_engine import evaluate
from app.services.scenario_runner import list_scenarios, run_scenario
from app.services.walkthrough import (
    WALKTHROUGH_VERSION, carried_walk_step, known_step_id, neighbors, page_matches,
    progress_step_id, step_by_id, steps,
)

SAME_ORIGIN = {"Origin": "http://localhost"}

GUIDED_PAGES = (
    ("/try/?walk=intake", "intake", "evidence"),
    ("/try/scenario/evidence-supported?walk=evidence", "evidence", "clause"),
    ("/try/scenario/contract-clause-conflict?walk=clause", "clause", "high-risk"),
    ("/try/scenario/high-risk-ai?walk=high-risk", "high-risk", "prohibited"),
    ("/try/scenario/prohibited-ai-decisions?walk=prohibited", "prohibited", "save"),
    ("/?walk=dashboard", "dashboard", "methods"),
    ("/methodology?walk=methods", "methods", None),
)

FREE_FORM_PAGES = (
    "/try/",
    "/try/scenario/evidence-supported",
    "/try/scenario/contract-clause-conflict",
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
        "intake", "evidence", "clause", "high-risk", "prohibited",
        "save", "decide", "dashboard", "methods",
    ]
    assert len({item["step_id"] for item in ordered}) == len(ordered)
    assert [item["number"] for item in ordered] == list(range(1, 10))
    assert WALKTHROUGH_VERSION == "1.0.0"
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    scenario_ids = {item["scenario_id"] for item in list_scenarios()}
    for step in ordered:
        assert step["endpoint"] in endpoints
        scenario_id = step["view_args"].get("scenario_id")
        if scenario_id:
            assert scenario_id in scenario_ids
    assert step_by_id("methods")["number"] == 9
    previous, following = neighbors("clause")
    assert previous["step_id"] == "evidence"
    assert following["step_id"] == "high-risk"
    assert neighbors("intake")[0] is None
    assert neighbors("methods")[1] is None


def test_coaching_facts_still_match_the_live_scenarios():
    evidence = run_scenario("evidence-supported")
    clause = run_scenario("contract-clause-conflict")
    high = run_scenario("high-risk-ai")
    prohibited = run_scenario("prohibited-ai-decisions")

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
    assert not page_matches(decide, "demos.detail", {"scenario_id": "prohibited-ai-decisions"})
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


def test_index_lists_every_stop_and_links_into_the_live_pages(client):
    assert client.get("/walkthrough").status_code == 200
    response = client.get("/walkthrough/")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "VERSION 1.0.0" in body
    assert "Start at intake" in body
    assert 'href="/try/?walk=intake"' in body
    assert 'href="/try/scenario/evidence-supported?walk=evidence"' in body
    assert 'href="/try/scenario/contract-clause-conflict?walk=clause"' in body
    assert 'href="/try/scenario/high-risk-ai?walk=high-risk"' in body
    assert 'href="/try/scenario/prohibited-ai-decisions?walk=prohibited"' in body
    assert 'href="/demo/prohibited-ai-decisions?walk=save"' in body
    assert "Save the eligibility case first." in body
    assert 'href="/?walk=dashboard"' in body
    assert 'href="/methodology?walk=methods"' in body
    for step in steps():
        assert step["title"] in body
        assert step["summary"] in body
    assert 'action="/walkthrough/reset"' in body
    assert "conflicting-permissions" in body
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
        assert f"STEP {steps()[next(i for i, item in enumerate(steps()) if item['step_id'] == step_id)]['number']} OF 9" in body
        assert "walk_step=" + step_id in response.headers.get("Set-Cookie", "")
        if following:
            assert f"walk={following}" in body
            assert "Finish" not in body
        else:
            assert ">Finish</a>" in body
            assert 'class="button-link walk-next" href="/walkthrough/"' in body
    intake = client.get("/try/?walk=intake").get_data(as_text=True)
    assert "walk-back" not in intake
    assert "not verified evidence" in intake
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
    assert f'action="{location.split("?")[0]}/decision?walk=decide"' in body
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


def test_reset_clears_the_cookie_and_leaves_the_register_alone(client):
    client.post("/demo/prohibited-ai-decisions/register?walk=save", headers=SAME_ORIGIN)
    client.get("/risks?walk=decide")
    assert b"AI tool that decides eligibility" in client.get("/risks").data
    client.post("/walkthrough/reset", headers=SAME_ORIGIN)
    assert b"AI tool that decides eligibility" in client.get("/risks").data
    assert "Continue ·" not in client.get("/walkthrough/").get_data(as_text=True)
