"""First-impression copy, aliases, and scenario-fixture export labels."""

import json

from app.services.intake_export import build_package, render_markdown
from app.services.scenario_runner import run_scenario

def test_home_states_what_the_prototype_demonstrates(client):
    body = client.get("/").get_data(as_text=True)
    assert "PORTFOLIO PROTOTYPE · HOSTED DEMO · SYNTHETIC DATA" in body
    assert "What this demonstrates" in body
    assert "Evidence-first third-party and AI vendor risk review." in body
    assert "Explainable, versioned rules." in body
    assert "ISO/IEC 42001" in body
    assert "stay draft" in body
    assert "tamper-evident (SHA-256 hash chain)" in body
    assert "Definitions (v9)" in body
    assert "<details" in body
    start = body.index("Repeatable scenarios")
    demonstrates = body.index("What this demonstrates")
    assert demonstrates < start


def test_dashboard_and_metrics_redirect_to_the_home_page(client):
    for path in ("/dashboard", "/metrics"):
        response = client.get(path)
        assert response.status_code == 302
        location = response.headers["Location"]
        assert location.endswith("/")
        assert path not in location
    followed = client.get("/metrics", follow_redirects=True)
    assert followed.status_code == 200
    assert b"What this demonstrates" in followed.data


def test_empty_register_asks_the_visitor_to_save_a_scenario(client):
    body = client.get("/risks").get_data(as_text=True)
    assert "Save a scenario to see it here." in body
    assert "tamper-evident (SHA-256 hash chain), not tamper-proof" in body


def test_provisional_scenario_names_the_unknown_answer_count(client):
    result = run_scenario("high-risk-ai")
    unknown = list(dict.fromkeys(result["risk"]["missing_information"]))
    assert result["risk"]["inherent"]["provisional"] is True
    assert len(unknown) >= 1
    body = client.get("/demo/high-risk-ai").get_data(as_text=True)
    noun = "answer" if len(unknown) == 1 else "answers"
    verb = "is" if len(unknown) == 1 else "are"
    assert f"Risk level not set yet: {len(unknown)} required {noun} {verb} unknown" in body
    assert "Answer them to get a tier." in body or "Answer it to get a tier." in body
    assert body.index("Risk level not set yet:") < body.index("INHERENT RISK")
    assert 'href="/methodology#glossary-inh"' in body or "glossary-inh" in body


def test_methodology_glossary_defines_the_rule_families(client):
    body = client.get("/methodology").get_data(as_text=True)
    assert 'id="glossary"' in body
    for anchor in (
        "glossary-hr",
        "glossary-cc",
        "glossary-esc",
        "glossary-inh",
        "glossary-residual-tier",
        "glossary-disposition",
        "glossary-sandbox",
        "glossary-chained-after-the-fact",
    ):
        assert f'id="{anchor}"' in body
    assert "tamper-evident (SHA-256 hash chain), not tamper-proof" in body
    assert "draft portfolio review prompts" in body
    assert "ISO/IEC 27001" in body
    page = client.get("/demo/prohibited-ai-decisions").get_data(as_text=True)
    assert "/methodology#glossary-hr" in page
    assert "/methodology#glossary-cc" in page


def test_scenario_fixture_export_labels_a_null_questionnaire():
    package = build_package(run_scenario("evidence-supported"))
    assert package["export_version"] == "1.0.0"
    assert package["versions"]["questionnaire"] is None
    assert package["versions"]["questionnaire_note"] == "N/A (scenario fixture)"
    summary = render_markdown(package)
    assert "Questionnaire: N/A (scenario fixture)" in summary
    assert "Questionnaire: not on this result" not in summary


def test_public_intake_export_keeps_a_real_questionnaire_version():
    from tests.test_try_demo import run

    result = run(vendor_name="Northwind Notes")
    package = build_package(result)
    assert package["versions"]["questionnaire"] == "1.1.0"
    assert package["versions"]["questionnaire_note"] is None
    assert "Questionnaire: 1.1.0" in render_markdown(package)


def test_scenario_download_uses_the_fixture_questionnaire_label(client):
    response = client.get("/try/scenario/high-risk-ai/export/markdown")
    assert response.status_code == 200
    assert b"N/A (scenario fixture)" in response.data
    downloaded = client.get("/try/scenario/high-risk-ai/export/json")
    package = json.loads(downloaded.data)
    assert package["versions"]["questionnaire"] is None
    assert package["versions"]["questionnaire_note"] == "N/A (scenario fixture)"
    assert package["export_version"] == "1.0.0"


def test_register_page_keeps_a_null_sandbox_row_visible(client, app):
    """PR #32 leaves pre-sandbox rows visible. This page does not delete them."""
    import sqlite3

    path = app.config["DATABASE"]
    # The fixture database is already migrated. Insert a shared row directly.
    connection = sqlite3.connect(path)
    connection.execute(
        """INSERT INTO risks
        (risk_id, scenario_id, scenario_name, risk_statement, inherent_tier, residual_tier,
         rationale_json, created_at, sandbox_id)
        VALUES ('R-OLD', 'legacy-shared', 'Legacy shared', 'Synthetic statement', 'low', 'low',
                '{}', '2026-10-15T00:00:00+00:00', NULL)"""
    )
    connection.commit()
    connection.close()
    page = client.get("/risks")
    assert page.status_code == 200
    assert b"Legacy shared" in page.data
    assert b"R-OLD" in page.data
