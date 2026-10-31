"""Prospect-style regressions: evidence defaults, plain results, and sample data."""

import csv
import io
import json
import re
from datetime import date

import pytest

from app import create_app
from app.db import get_db
from app.services.cost_model import calculate_cost
from app.services.event_chain import verify_event_chain
from app.services.intake_builder import IntakeError, build_intake, run_intake
from app.services.intake_importer import (
    assess_import, can_import, confirmation_document, evidence_column_names, parse_upload,
    questionnaire_columns, sample_file,
)
from app.services.result_explain import owner_summary, withheld_tier_line
from app.services.sample_register import SAMPLE_SCENARIO_IDS, seed_sample_risks
from app.services.scenario_runner import run_scenario
from app.services.workflow_service import WorkflowInputError
from tests.test_try_demo import form
from tests.test_workflow_metrics import _observed_section

AS_OF = date(2026, 10, 14)
SAME_ORIGIN = {"Origin": "http://localhost"}
RULE_CODE = re.compile(r"\b(?:HR|ESC|INH|CC)-\d+\b|calculate_cost\(|Definition 9")


def _drop_evidence(values):
    kept = dict(values)
    for field in evidence_column_names():
        kept.pop(field, None)
    return kept


def test_public_form_selects_nothing_provided_for_every_evidence_field(client):
    body = client.get("/try/").get_data(as_text=True)
    assert body.count('value="none" selected') == len(evidence_column_names())
    assert "Evidence choices start at Nothing provided." in body
    assert 'value="independent_verified" selected' not in body


def test_omitted_evidence_is_missing_and_not_verified():
    intake = build_intake(_drop_evidence(form(
        vendor_name="Critical Empty",
        data_sensitivity="restricted",
        integration_permissions="admin",
        ai_use="autonomous",
        model_training_on_customer_data="yes",
        external_exposure="customer_facing",
        retention_deletion="undocumented",
    )), AS_OF)
    result = run_intake(intake, AS_OF)
    counts = result["risk"]["evidence_confidence"]["counts"]
    assert counts["verified"] == 0
    assert result["risk"]["evidence_confidence"]["level"] in {"low", "none"}
    assert {claim["evidence_status"] for claim in result["claims"]} == {"missing"}
    clause = result["risk"]["policy"]["required_contract_clauses"][0]
    assert clause["evidence_status"] == "missing"


def test_blank_evidence_strings_are_not_verified():
    blanked = form()
    for field in evidence_column_names():
        blanked[field] = "   "
    result = run_intake(build_intake(blanked, AS_OF), AS_OF)
    assert result["risk"]["evidence_confidence"]["counts"]["verified"] == 0
    assert result["risk"]["evidence_confidence"]["level"] in {"low", "none"}


def test_unknown_evidence_choice_is_rejected_and_not_rewritten_to_verified():
    with pytest.raises(IntakeError):
        build_intake(form(trust_soc2="reviewed"), AS_OF)


def test_public_post_with_no_evidence_fields_is_not_five_verified(client):
    posted = _drop_evidence(form(
        vendor_name="Critical Empty",
        data_sensitivity="restricted",
        integration_permissions="admin",
        ai_use="autonomous",
        model_training_on_customer_data="yes",
        external_exposure="customer_facing",
        retention_deletion="undocumented",
    ))
    response = client.post("/try/assess", data=posted, headers=SAME_ORIGIN)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "0 verified" in body
    assert "5 verified" not in body
    assert ">Low<" in body or ">None<" in body


def test_api_omitted_or_blank_evidence_is_not_verified(client):
    omitted = {"as_of": "2026-10-14", "form": _drop_evidence(form(vendor_name="Api Empty"))}
    blank = {"as_of": "2026-10-14", "form": form(vendor_name="Api Blank", **{
        field: "" for field in evidence_column_names()
    })}
    for payload in (omitted, blank):
        response = client.post("/api/v1/intake/assess", json=payload)
        assert response.status_code == 200, response.get_data(as_text=True)
        body = response.get_json()
        assert body["evidence_confidence"]["counts"]["verified"] == 0
        assert body["evidence_confidence"]["level"] in {"low", "none"}
        assert body["automatic_approval"] is None


def test_import_blank_evidence_cells_are_not_verified():
    row = {column: "" for column in questionnaire_columns()}
    row.update({
        "vendor_name": "Blank Harbor",
        "data_sensitivity": "confidential",
        "integration_permissions": "read_write",
        "ai_use": "assistive",
        "model_training_on_customer_data": "no",
        "external_exposure": "customer_facing",
        "retention_deletion": "documented",
        "decisions_affecting_people": "no",
    })
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=questionnaire_columns())
    writer.writeheader()
    writer.writerow(row)
    preview = parse_upload("blank-evidence.csv", buffer.getvalue().encode(), AS_OF)
    assert can_import(preview), preview
    result = assess_import(confirmation_document(preview), AS_OF)[0]
    assert result["risk"]["evidence_confidence"]["counts"]["verified"] == 0
    assert result["risk"]["evidence_confidence"]["level"] in {"low", "none"}


def test_servicenow_missing_attachment_is_not_scored_as_verified():
    document = json.loads(sample_file("json"))
    document["result"][0]["attachments"] = [
        item for item in document["result"][0]["attachments"]
        if item.get("u_intake_field") != "trust_soc2"
    ]
    preview = parse_upload("missing-soc.json", json.dumps(document).encode(), AS_OF)
    assert not can_import(preview)
    problems = " ".join(preview["rows"][0]["problems"])
    assert "trust_soc2" in problems


def test_servicenow_blank_evidence_option_is_missing():
    document = json.loads(sample_file("json"))
    for item in document["result"][0]["attachments"]:
        if item.get("u_intake_field") == "trust_soc2":
            item["u_evidence_option"] = ""
    preview = parse_upload("blank-soc.json", json.dumps(document).encode(), AS_OF)
    assert can_import(preview), preview["rows"][0]["problems"]
    result = assess_import(confirmation_document(preview), AS_OF)[0]
    assert next(claim["evidence_status"] for claim in result["claims"] if claim["topic"] == "authentication") == "missing"
    assert result["risk"]["evidence_confidence"]["counts"]["verified"] < 5


def test_withheld_tier_names_the_questions_above_the_scores(client):
    result = run_scenario("high-risk-ai")
    line = withheld_tier_line(result["risk"])
    assert line.startswith("Risk level not set yet: 2 required answers are unknown (")
    assert "Will the vendor train or improve models on your data" in line
    assert "Is retention and deletion documented" in line
    assert "Answer them to get a tier." in line
    assert RULE_CODE.search(line) is None
    assert withheld_tier_line(run_scenario("evidence-supported")["risk"]) == ""
    body = client.get("/try/scenario/high-risk-ai").get_data(as_text=True)
    assert body.index(line) < body.index("INHERENT RISK")
    assert "Tier withheld because" not in body


def test_plain_summary_leads_and_technical_detail_keeps_the_rule_codes(client):
    result = run_scenario("prohibited-ai-decisions")
    sentences = owner_summary(result)
    assert len(sentences) == 3
    assert all(RULE_CODE.search(sentence) is None for sentence in sentences)
    assert "synthetic review" in sentences[0].lower() or "synthetic" in sentences[0].lower()
    joined = " ".join(sentences)
    assert "not an approval" in joined or "do not allow" in joined
    body = client.get("/try/scenario/prohibited-ai-decisions").get_data(as_text=True)
    assert body.index("In plain language") < body.index("INHERENT RISK")
    assert body.index("In plain language") < body.index("Technical detail")
    assert "HR-001" in body
    assert body.index("Technical detail") < body.index("HR-001")
    saved = client.post("/demo/prohibited-ai-decisions/register", headers=SAME_ORIGIN)
    detail = client.get(saved.headers["Location"]).get_data(as_text=True)
    assert detail.index("In plain language") < detail.index("Technical detail")
    assert "HR-001" in detail
    saved_sentences = owner_summary({"scenario_name": result["name"], "rationale": {
        "risk": result["risk"],
        "claims": result["claims"],
        "assessment_inputs": result["assessment_inputs"],
        "vendor_name": result["name"],
    }})
    assert len(saved_sentences) == 3
    assert all(RULE_CODE.search(sentence) is None for sentence in saved_sentences)


def test_saved_risk_toc_is_anchor_links_without_a_script(client):
    saved = client.post("/demo/evidence-supported/register", headers=SAME_ORIGIN)
    detail = client.get(saved.headers["Location"])
    body = detail.get_data(as_text=True)
    assert detail.status_code == 200
    assert 'class="page-toc"' in body
    for href in ("#summary", "#scores", "#evidence", "#decision", "#controls", "#history", "#export"):
        assert f'href="{href}"' in body
        assert f'id="{href[1:]}"' in body
    assert "<script" not in body
    css = client.get("/static/css/styles.css").get_data(as_text=True)
    assert ".page-toc { position:sticky;" in css


def test_empty_dashboard_and_register_offer_sample_data(client):
    home = client.get("/").get_data(as_text=True)
    register = client.get("/risks").get_data(as_text=True)
    assert "Load sample data" in home
    assert "Load sample data" in register
    assert 'action="/risks/sample-data"' in home
    assert 'name="next" value="dashboard"' in home
    assert 'name="next" value="risks"' in register


def test_sample_load_is_idempotent_scoped_and_keeps_the_chain(client, app):
    before_cost = calculate_cost()
    first = client.post("/risks/sample-data", data={"next": "dashboard"}, headers=SAME_ORIGIN)
    assert first.status_code == 302
    assert first.headers["Location"].endswith("/")
    home = client.get("/").get_data(as_text=True)
    assert "Sample:" in home
    assert "Sample data loaded" in home
    assert "Load sample data" not in home
    assert "Saved assessments: 3." in _observed_section(home.encode())
    assert "MODELED EXAMPLE" in home
    assert calculate_cost() == before_cost
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) AS n FROM risks WHERE sandbox_id IS NULL").fetchone()["n"] == 0
        rows = db.execute("SELECT risk_id, sandbox_id, scenario_id, scenario_name, risk_statement FROM risks").fetchall()
        assert len(rows) == 3
        sandbox_ids = {row["sandbox_id"] for row in rows}
        assert len(sandbox_ids) == 1
        assert None not in sandbox_ids
        assert {row["scenario_id"] for row in rows} == set(SAMPLE_SCENARIO_IDS)
        assert all(row["scenario_name"].startswith("Sample:") for row in rows)
        assert all(row["risk_statement"].startswith("Sample data · synthetic.") for row in rows)
        sandbox_id = rows[0]["sandbox_id"]
        events = [dict(row) for row in db.execute(
            """SELECT event_id, risk_id, event_type, detail, occurred_at, prev_hash, hash, chain_origin
               FROM workflow_events WHERE sandbox_id = ? ORDER BY event_id""",
            (sandbox_id,),
        ).fetchall()]
        assert events
        assert verify_event_chain(events) == "intact"
        assert db.execute(
            "SELECT COUNT(*) AS n FROM workflow_events WHERE sandbox_id IS NULL"
        ).fetchone()["n"] == 0
        event_count = len(events)
    other = app.test_client()
    assert b"Sample:" not in other.get("/risks").data
    assert b"Sample:" not in other.get("/").data
    second = client.post("/risks/sample-data", data={"next": "risks"}, headers=SAME_ORIGIN)
    assert second.status_code == 302
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) AS n FROM risks").fetchone()["n"] == 3
        assert db.execute(
            "SELECT COUNT(*) AS n FROM workflow_events WHERE sandbox_id IS NOT NULL"
        ).fetchone()["n"] == event_count
        events = [dict(row) for row in db.execute(
            """SELECT event_id, risk_id, event_type, detail, occurred_at, prev_hash, hash, chain_origin
               FROM workflow_events WHERE sandbox_id = ? ORDER BY event_id""",
            (sandbox_id,),
        ).fetchall()]
        assert verify_event_chain(events) == "intact"


def test_sample_load_rejects_a_cross_site_post_and_a_missing_sandbox(client, app):
    blocked = client.post(
        "/risks/sample-data", data={"next": "risks"}, headers={"Origin": "https://evil.example"},
    )
    assert blocked.status_code == 403
    assert client.post("/risks/sample-data", data={"next": "risks"}).status_code == 403
    assert client.get("/risks/sample-data").status_code == 405
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) AS n FROM risks").fetchone()["n"] == 0
        try:
            seed_sample_risks(get_db(), None)
        except WorkflowInputError as exc:
            assert "shared register" in str(exc)
        else:
            raise AssertionError("a missing sandbox id was accepted")
        assert get_db().execute("SELECT COUNT(*) AS n FROM risks").fetchone()["n"] == 0


def test_sample_load_does_not_pass_the_sandbox_cap(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": str(tmp_path / "cap.sqlite3"),
        "SECRET_KEY": "sample-cap",
        "SANDBOX_MAX_RISKS": 2,
    })
    visitor = app.test_client()
    response = visitor.post("/risks/sample-data", data={"next": "risks"}, headers=SAME_ORIGIN)
    assert response.status_code == 302
    assert "sample=cap" in response.headers["Location"]
    page = visitor.get("/risks?sample=cap")
    assert page.status_code == 200
    assert b"Nothing new was saved" in page.data
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) AS n FROM risks").fetchone()["n"] == 0
        assert get_db().execute(
            "SELECT COUNT(*) AS n FROM risks WHERE sandbox_id IS NULL"
        ).fetchone()["n"] == 0


def test_sample_load_does_not_duplicate_a_scenario_already_in_the_sandbox(client, app):
    saved = client.post("/demo/high-risk-ai/register", headers=SAME_ORIGIN)
    assert saved.status_code == 302
    loaded = client.post("/risks/sample-data", data={"next": "risks"}, headers=SAME_ORIGIN)
    assert loaded.status_code == 302
    with app.app_context():
        rows = get_db().execute(
            "SELECT scenario_id FROM risks WHERE scenario_id = 'high-risk-ai'"
        ).fetchall()
        assert len(rows) == 1
        assert get_db().execute("SELECT COUNT(*) AS n FROM risks").fetchone()["n"] == 3
