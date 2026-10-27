"""Vendor direction is intake context. It does not change residual risk."""

import csv
import io
import json
from datetime import date

import pytest

from app.services.bot_intake import BotRequestError, assess_request, contract_document
from app.services.intake_builder import IntakeError, build_intake, clause_evidence_field, run_intake
from app.services.intake_export import build_package, render_markdown
from app.services.intake_importer import (
    assess_import, can_import, confirmation_document, parse_upload, questionnaire_columns,
    render_questionnaire_csv, sample_file, sample_forms,
)
from app.services.intake_questionnaire import load_questionnaire
from app.services.intake_replay import replay_plan
from app.services.org_policy import load_org_policy
from app.services.workflow_service import get_risk, register_intake

AS_OF = date(2026, 10, 14)
SAME_ORIGIN = {"Origin": "http://localhost"}
SCORED_KEYS = (
    "inherent", "evidence_confidence", "residual", "escalations", "missing_information",
    "conflicts", "review_path", "policy_outcome",
)


def form(**overrides):
    base = {
        "vendor_name": "Northwind Notes",
        "data_sensitivity": "confidential",
        "integration_permissions": "read_only",
        "ai_use": "none",
        "model_training_on_customer_data": "no",
        "external_exposure": "internal_only",
        "retention_deletion": "documented",
        "decisions_affecting_people": "no",
        "evidence_integration_permissions": "independent_verified",
        "trust_center_url": "",
        "trust_soc2": "independent_verified",
        "trust_security": "independent_verified",
        "trust_privacy": "independent_verified",
    }
    for clause in load_org_policy()["required_contract_clauses"]:
        base[clause_evidence_field(clause["clause_id"])] = "independent_verified"
    base.update(overrides)
    return base


def run(**overrides):
    return run_intake(build_intake(form(**overrides), AS_OF), AS_OF)


def _scored(result):
    return {key: result["risk"][key] for key in SCORED_KEYS}


def test_direction_context_round_trips_and_stays_out_of_the_score():
    note = "Synthetic context: the requester expects the relationship to grow."
    result = run(vendor_direction="expanding", residual_direction="worsening", direction_note=note)
    direction = result["direction_context"]
    assert direction["scored"] is False
    assert "not scored" in direction["note"].lower()
    values = {item["field"]: item for item in direction["fields"]}
    assert values["vendor_direction"]["value"] == "expanding"
    assert values["vendor_direction"]["display"] == "Expanding scope"
    assert values["vendor_direction"]["scored"] is False
    assert values["residual_direction"]["value"] == "worsening"
    assert values["residual_direction"]["display"] == "Expected to rise"
    assert direction["direction_note"] == note
    assert "vendor_direction" not in result["assessment_inputs"]
    assert "residual_direction" not in result["assessment_inputs"]
    assert "direction_note" not in result["assessment_inputs"]

    package = build_package(result)
    assert package["direction_context"]["scored"] is False
    assert package["direction_context"]["provided"] is True
    assert package["direction_context"]["direction_note"] == note
    answer_fields = {item["field"] for item in package["intake_answers"]}
    assert "vendor_direction" not in answer_fields
    text = render_markdown(package)
    assert "## Direction context" in text
    assert "Scored: no" in text
    assert "Expanding scope" in text
    assert note in text

    plan = replay_plan(result)
    assert plan["fields"]["vendor_direction"] == "expanding"
    assert plan["fields"]["residual_direction"] == "worsening"
    assert plan["fields"]["direction_note"] == note
    replayed = run_intake(build_intake(plan["fields"], AS_OF), AS_OF)
    assert replayed["direction_context"]["direction_note"] == note
    assert _scored(replayed) == _scored(result)
    assert replayed["mappings"] == result["mappings"]


def test_different_direction_context_keeps_the_same_residual_and_disposition(client):
    improving = run(
        vendor_direction="exiting",
        residual_direction="improving",
        direction_note="Synthetic: winding down next quarter.",
    )
    worsening = run(
        vendor_direction="expanding",
        residual_direction="worsening",
        direction_note="Synthetic: scope is growing.",
    )
    omitted = run()
    unknown = run(vendor_direction="unknown", residual_direction="unknown", direction_note="")
    assert improving["risk"]["inherent"]["score"] == 35
    assert improving["risk"]["residual"] == {
        "tier": "low",
        "reason": "Lowered one tier: high confidence, no conflicts, no escalations.",
    }
    assert improving["risk"]["inherent"]["provisional"] is False
    assert _scored(improving) == _scored(worsening) == _scored(omitted) == _scored(unknown)
    assert improving["mappings"] == worsening["mappings"] == omitted["mappings"]
    assert unknown["risk"]["missing_information"] == []
    assert "ESC-009" not in [item["rule_id"] for item in unknown["risk"]["escalations"]]
    assert {item["value"] for item in improving["direction_context"]["fields"]} != {
        item["value"] for item in worsening["direction_context"]["fields"]
    }

    decision = {
        "disposition": "escalate",
        "rationale": "A person decides. Direction context is not the disposition.",
        "decider": "GRC analyst",
        "conditions": "",
        "exception_rationale": "",
    }
    with client.application.app_context():
        from app.db import get_db

        db = get_db()
        left_id = register_intake(db, improving, decision)
        right_id = register_intake(db, worsening, decision)
        left = get_risk(db, left_id)
        right = get_risk(db, right_id)
    assert left["residual_tier"] == right["residual_tier"] == "low"
    assert left["inherent_tier"] == right["inherent_tier"]
    assert left["decision"]["disposition"] == right["decision"]["disposition"] == "escalate"
    assert left["decision"]["prohibited_at_decision"] == right["decision"]["prohibited_at_decision"]
    assert left["decision"]["disposition"] != left["residual_tier"]

    page = client.get(f"/risks/{right_id}")
    assert page.status_code == 200
    assert b"Expanding scope" in page.data
    assert b"Expected to rise" in page.data
    assert b"not scored" in page.data
    package = client.get(f"/risks/{right_id}/export/json").get_json()
    assert package["direction_context"]["scored"] is False
    assert package["evaluation"]["residual_tier"] == "low"
    assert package["decision"]["disposition"] == "escalate"
    summary = client.get(f"/risks/{right_id}/export/markdown").data
    assert b"Direction context" in summary
    assert b"Scored: no" in summary
    assert b"Synthetic: scope is growing." in summary


def test_unknown_direction_does_not_soften_a_blocked_residual():
    blocked = run(evidence_integration_permissions="contradicts", vendor_direction="exiting",
                  residual_direction="improving", direction_note="Synthetic: leaving would not clear the conflict.")
    same = run(evidence_integration_permissions="contradicts")
    assert blocked["risk"]["residual"]["tier"] == same["risk"]["residual"]["tier"] == "moderate"
    assert blocked["risk"]["residual"]["reason"].startswith("Not lowered:")
    assert _scored(blocked) == _scored(same)
    assert blocked["mappings"] == same["mappings"]


def test_blank_direction_is_not_provided_and_invalid_values_are_rejected():
    result = run(vendor_direction="", residual_direction="", direction_note="  ")
    assert [item["value"] for item in result["direction_context"]["fields"]] == ["", ""]
    assert [item["display"] for item in result["direction_context"]["fields"]] == ["Not provided", "Not provided"]
    assert result["direction_context"]["direction_note"] == ""

    with pytest.raises(IntakeError) as exc:
        build_intake(form(vendor_direction="softer"), AS_OF)
    assert any("not scored" in problem for problem in exc.value.problems)
    with pytest.raises(IntakeError):
        build_intake(form(direction_note="x" * 301), AS_OF)
    with pytest.raises(IntakeError) as line_error:
        build_intake(form(direction_note="first line\nsecond line"), AS_OF)
    assert any("unsupported characters" in problem for problem in line_error.value.problems)
    with pytest.raises(BotRequestError) as bot_error:
        assess_request({"as_of": AS_OF.isoformat(), "form": form(residual_direction="lower")})
    assert any("not scored" in problem for problem in bot_error.value.problems)
    numbered = {"as_of": AS_OF.isoformat(), "form": form(vendor_direction="stable")}
    numbered["form"]["direction_note"] = 12
    with pytest.raises(BotRequestError) as type_error:
        assess_request(numbered)
    assert any("expected text" in problem for problem in type_error.value.problems)


def test_bot_contract_keeps_direction_optional_and_unscored():
    contract = contract_document()
    assert contract["direction_context"]["scored"] is False
    assert contract["direction_context"]["optional"] is True
    names = [item["field"] for item in contract["direction_context"]["fields"]]
    assert names == ["vendor_direction", "residual_direction", "direction_note"]
    assert "vendor_direction" not in [item["column"] for item in contract["fields"]]

    plain = assess_request({"as_of": AS_OF.isoformat(), "form": form()})
    marked = assess_request({"as_of": AS_OF.isoformat(), "form": form(
        vendor_direction="stable", residual_direction="unchanged", direction_note="Synthetic note.",
    )})
    assert plain["residual"] == marked["residual"]
    assert plain["inherent"] == marked["inherent"]
    assert plain["escalations"] == marked["escalations"]
    assert plain["policy_outcome"] == marked["policy_outcome"]
    assert plain["mappings"] == marked["mappings"]
    assert plain["review_path"] == marked["review_path"]
    assert marked["direction_context"]["scored"] is False
    assert marked["direction_context"]["fields"][0]["value"] == "stable"
    assert plain["direction_context"]["fields"][0]["value"] == ""
    assert any("not scored" in item.lower() for item in marked["limitations"])


def test_file_import_round_trips_direction_and_accepts_omitted_columns():
    preview = parse_upload("vendor_intake.csv", sample_file("csv"), AS_OF)
    assert can_import(preview)
    imported = assess_import(confirmation_document(preview), AS_OF)
    assert imported[0]["direction_context"]["fields"][0]["value"] == "stable"
    assert imported[0]["direction_context"]["fields"][1]["value"] == "unchanged"
    assert imported[1]["direction_context"]["fields"][0]["value"] == "expanding"
    assert "Not a score." in imported[1]["direction_context"]["direction_note"]
    assert imported[0]["risk"]["residual"] == run_intake(
        build_intake(preview["rows"][0]["form"], AS_OF), AS_OF
    )["risk"]["residual"]

    columns = questionnaire_columns()
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for sample in sample_forms():
        writer.writerow({column: sample[column] for column in columns})
    omitted = parse_upload("legacy.csv", buffer.getvalue().encode(), AS_OF)
    assert can_import(omitted)
    legacy = assess_import(confirmation_document(omitted), AS_OF)
    assert legacy[0]["direction_context"]["fields"][0]["value"] == ""
    assert legacy[0]["risk"]["residual"] == imported[0]["risk"]["residual"]
    assert legacy[1]["risk"]["residual"] == imported[1]["risk"]["residual"]
    assert legacy[0]["mappings"] == imported[0]["mappings"]

    document = json.loads(sample_file("json"))
    for ticket in document["result"]:
        ticket.pop("u_vendor_direction")
        ticket.pop("u_residual_direction")
        ticket.pop("u_direction_note")
    without = parse_upload("servicenow.json", (json.dumps(document) + "\n").encode(), AS_OF)
    assert can_import(without)
    assert without["rows"][0]["form"]["vendor_direction"] == ""
    with_direction = parse_upload("servicenow.json", sample_file("json"), AS_OF)
    assert with_direction["rows"][0]["form"]["vendor_direction"] == "stable"
    assert _scored(assess_import(confirmation_document(without), AS_OF)[0]) == _scored(
        assess_import(confirmation_document(with_direction), AS_OF)[0]
    )


def test_public_pages_show_direction_context_beside_the_result(client):
    form_page = client.get("/try/")
    assert form_page.status_code == 200
    assert b"Reviewer context" in form_page.data
    assert b"not scored" in form_page.data
    assert b'name="vendor_direction"' in form_page.data
    assert b'name="residual_direction"' in form_page.data
    assert b'name="direction_note"' in form_page.data
    assert b"Not provided" in form_page.data

    posted = {
        "vendor_name": "Northwind Notes",
        "data_sensitivity": "internal",
        "integration_permissions": "read_only",
        "ai_use": "none",
        "external_exposure": "internal_only",
        "retention_deletion": "documented",
        "decisions_affecting_people": "no",
        "evidence_integration_permissions": "independent_verified",
        "trust_center_url": "",
        "fetch_trust_center": "no",
        "trust_soc2": "independent_verified",
        "trust_security": "independent_verified",
        "trust_privacy": "independent_verified",
        "evidence_clause_CC-001": "independent_verified",
    }
    plain = client.post("/try/assess", data=posted, headers=SAME_ORIGIN)
    marked = client.post("/try/assess", data={
        **posted,
        "vendor_direction": "reducing",
        "residual_direction": "improving",
        "direction_note": "Synthetic context for the reviewer.",
    }, headers=SAME_ORIGIN)
    assert plain.status_code == 200
    assert marked.status_code == 200
    assert b"Already at the lowest tier." in plain.data
    assert b"Already at the lowest tier." in marked.data
    assert b"Reducing scope" in marked.data
    assert b"Expected to fall" in marked.data
    assert b"Synthetic context for the reviewer." in marked.data
    assert b"Scored: no" in marked.data
    assert b"Low" in plain.data and b"Low" in marked.data

    upload = client.get("/try/import")
    assert b"vendor_direction" in upload.data
    assert b"Not scored" in upload.data
    assert load_questionnaire()["questionnaire_version"] == "1.1.0"


def test_questionnaire_refuses_a_scored_direction_section():
    from app.services.evidence_validator import load_policy
    from app.services.intake_builder import field_choices
    from app.services.intake_questionnaire import QuestionnaireError, validate_questionnaire

    broken = load_questionnaire()
    broken["direction_context"]["scored"] = True
    with pytest.raises(QuestionnaireError, match="scored"):
        validate_questionnaire(broken, field_choices(), load_org_policy(), load_policy())
