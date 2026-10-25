"""Bot JSON contract and CLI: same intake path, no saved risk."""

import io
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from app.cli import EXIT_ENGINE, EXIT_OK, EXIT_VALIDATION, main
from app.services.bot_intake import (
    BotRequestError, assess_file, assess_request, assess_request_text, preview_file,
)
from app.services.intake_builder import build_intake, clause_evidence_field, run_intake
from app.services.intake_importer import render_questionnaire_csv, sample_file, sample_forms
from app.services.org_policy import load_org_policy
from app.services.risk_engine import load_rules

AS_OF = date(2026, 10, 14)
ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "imports"


def form(**overrides):
    """A low-risk vendor with reviewed evidence, matching the public form fields."""
    base = {
        "vendor_name": "Northwind Notes",
        "data_sensitivity": "internal",
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


def request(**overrides):
    payload = {"contract_version": "1.0.0", "as_of": AS_OF.isoformat(), "form": form()}
    payload.update(overrides)
    return payload


def engine_result(**overrides):
    return run_intake(build_intake(form(**overrides), AS_OF), AS_OF)


def test_assessment_copies_the_engine_result():
    document = assess_request(request())
    result = engine_result()
    risk = result["risk"]
    assert document["contract"] == "grc.intake.assessment"
    assert document["persisted"] is False
    assert document["automatic_approval"] is None
    assert document["human_review_required"] is True
    assert document["residual"] == {"tier": risk["residual"]["tier"], "reason": risk["residual"]["reason"]}
    assert document["residual"]["tier"] == "low"
    assert document["inherent"] == risk["inherent"]
    assert document["evidence_confidence"] == risk["evidence_confidence"]
    assert document["escalations"] == risk["escalations"]
    assert document["rule_set_version"] == risk["rule_set_version"] == load_rules()["rule_set_version"]
    assert document["review_path"] == "standard_review"
    assert document["policy_outcome"]["status"] == "not_prohibited"
    clause = document["required_contract_clauses"][0]
    assert clause["clause_id"] == "CC-001"
    assert clause["evidence_status"] == "verified"
    assert {item["control_id"] for item in document["mappings"]} == {"IA-2", "AC-6", "SC-8", "AU-2"}
    assert all(item["review_status"] == "draft" for item in document["mappings"])
    assert document["trust_center"]["fetched"] is False
    assert assess_request(request()) == document


def test_omitted_model_training_matches_the_public_form_when_ai_use_is_none():
    posted = form()
    del posted["model_training_on_customer_data"]
    omitted = assess_request({"as_of": AS_OF.isoformat(), "form": posted})
    explicit = assess_request(request())
    assert omitted["inherent"] == explicit["inherent"]
    assert omitted["residual"] == explicit["residual"]
    assert omitted["escalations"] == explicit["escalations"]


def test_policy_restriction_is_separate_from_the_score():
    allowed = assess_request(request(form=form(ai_use="assistive", decisions_affecting_people="no")))
    blocked = assess_request(request(form=form(ai_use="assistive", decisions_affecting_people="yes")))
    engine = engine_result(ai_use="assistive", decisions_affecting_people="yes")
    assert blocked["policy_outcome"]["status"] == "prohibited"
    assert blocked["policy_outcome"]["restrictions"][0]["restriction_id"] == "HR-001"
    assert blocked["policy_outcome"]["restrictions"][0]["policy_id"] == "ORG-AI-USE"
    assert blocked["review_path"] == "escalated_review"
    assert blocked["inherent"]["score"] == allowed["inherent"]["score"]
    assert blocked["residual"] == {
        "tier": engine["risk"]["residual"]["tier"],
        "reason": engine["risk"]["residual"]["reason"],
    }
    assert blocked["automatic_approval"] is None
    assert blocked["persisted"] is False


def test_unknown_policy_answer_escalates_and_stays_undetermined():
    document = assess_request(request(form=form(decisions_affecting_people="unknown")))
    engine = engine_result(decisions_affecting_people="unknown")
    assert [item["rule_id"] for item in document["escalations"]] == [
        item["rule_id"] for item in engine["risk"]["escalations"]
    ]
    assert "ESC-009" in [item["rule_id"] for item in document["escalations"]]
    assert document["policy_outcome"]["status"] == "not_prohibited"
    assert document["residual"]["tier"] == "undetermined"
    assert "decisions_affecting_people" in document["missing_information"]


def test_conflicting_evidence_copies_the_escalation():
    document = assess_request(request(form=form(evidence_integration_permissions="contradicts")))
    engine = engine_result(evidence_integration_permissions="contradicts")
    assert document["escalations"] == engine["risk"]["escalations"]
    assert "ESC-003" in [item["rule_id"] for item in document["escalations"]]
    assert document["conflicts"][0]["evidence_status"] == "conflicting"
    assert document["review_path"] == "escalated_review"


def test_request_must_be_an_object_and_rejects_unknown_or_injected_fields():
    with pytest.raises(BotRequestError) as exc:
        assess_request(["vendor"])
    assert "JSON object" in exc.value.problems[0]

    with pytest.raises(BotRequestError) as exc:
        assess_request({"form": form(), "residual_tier": "low"})
    assert any("residual_tier" in problem for problem in exc.value.problems)

    posted = form()
    posted["residual_tier"] = "low"
    with pytest.raises(BotRequestError) as exc:
        assess_request({"as_of": AS_OF.isoformat(), "form": posted})
    assert any("not dropped" in problem for problem in exc.value.problems)


def test_missing_required_fields_are_named():
    posted = form()
    del posted["vendor_name"]
    del posted["data_sensitivity"]
    with pytest.raises(BotRequestError) as exc:
        assess_request({"as_of": AS_OF.isoformat(), "form": posted})
    message = " ".join(exc.value.problems)
    assert "vendor_name" in message
    assert "data_sensitivity" in message


def test_model_training_is_required_when_ai_use_is_not_none():
    posted = form(ai_use="assistive")
    del posted["model_training_on_customer_data"]
    with pytest.raises(BotRequestError) as exc:
        assess_request({"as_of": AS_OF.isoformat(), "form": posted})
    assert "model_training_on_customer_data" in " ".join(exc.value.problems)


def test_non_text_values_are_not_coerced():
    posted = form()
    posted["data_sensitivity"] = 10
    posted["decisions_affecting_people"] = True
    with pytest.raises(BotRequestError) as exc:
        assess_request({"as_of": AS_OF.isoformat(), "form": posted})
    message = " ".join(exc.value.problems)
    assert "data_sensitivity" in message and "a number" in message
    assert "decisions_affecting_people" in message and "a boolean" in message


def test_invalid_choice_invalid_date_and_bad_json_are_validation_errors():
    posted = form(data_sensitivity="super-secret")
    with pytest.raises(BotRequestError) as exc:
        assess_request({"as_of": AS_OF.isoformat(), "form": posted})
    assert any("choose one of the listed options" in problem for problem in exc.value.problems)

    with pytest.raises(BotRequestError) as exc:
        assess_request({"as_of": "2026-02-31", "form": form()})
    assert "calendar date" in exc.value.problems[0]

    with pytest.raises(BotRequestError) as exc:
        assess_request({"as_of": AS_OF.isoformat(), "form": form(), "contract_version": "9.0.0"})
    assert "1.0.0" in exc.value.problems[0]

    with pytest.raises(BotRequestError) as exc:
        assess_request_text('{"form": {"vendor_name": "A", "vendor_name": "B"}}')
    assert "Duplicate" in exc.value.problems[0]

    with pytest.raises(BotRequestError) as exc:
        assess_request_text("{")
    assert "not valid JSON" in exc.value.problems[0]


def test_export_documents_are_not_accepted_as_intake():
    package = {"kind": "vendor_intake_package", "evaluation": {"residual_tier": "low"}}
    with pytest.raises(BotRequestError) as exc:
        assess_request(package)
    assert "not an assess request" in exc.value.problems[0]


def test_file_assessment_matches_the_engine_and_ignores_ticket_priority():
    data = sample_file("json")
    batch = assess_file("servicenow-intake.json", data, AS_OF)
    preview = preview_file("servicenow-intake.json", data, AS_OF)
    assert preview["scored"] is False and preview["can_assess"] is True
    assert "residual" not in preview
    assert preview["rows"][0]["ticket_context"]["priority"] == "4"
    assert batch["persisted"] is False
    assert batch["count"] == 2
    first = batch["results"][0]
    engine = run_intake(build_intake(preview["rows"][0]["form"], AS_OF), AS_OF)
    assert first["residual"]["tier"] == engine["risk"]["residual"]["tier"]
    assert first["residual"]["tier"] != "4"
    assert first["rule_set_version"] == engine["risk"]["rule_set_version"]
    assert first["ticket_number"] == "VEND0010001"
    assert first["escalations"] == engine["risk"]["escalations"]
    assert "priority" not in first


def test_invalid_import_file_is_not_partially_assessed():
    forms = sample_forms()
    forms[1]["data_sensitivity"] = "super-secret"
    data = render_questionnaire_csv(forms)
    preview = preview_file("vendors.csv", data, AS_OF)
    assert preview["can_assess"] is False
    assert preview["scored"] is False
    with pytest.raises(BotRequestError) as exc:
        assess_file("vendors.csv", data, AS_OF)
    assert exc.value.preview is not None
    assert exc.value.preview["rows"][0]["problems"] == []
    assert exc.value.preview["rows"][1]["problems"]


def _cli(argv, stdin=""):
    held = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        code = main(argv)
    finally:
        sys.stdin = held
    return code


def test_cli_assess_stdin_and_validation_exit_codes(tmp_path, capsys):
    code = _cli(["assess", "-"], json.dumps(request()))
    captured = capsys.readouterr()
    assert code == EXIT_OK
    body = json.loads(captured.out)
    assert body["residual"]["tier"] == "low"
    assert body["rule_set_version"] == load_rules()["rule_set_version"]
    assert body["persisted"] is False

    bad = tmp_path / "bad.json"
    bad.write_text('{"form": {}}', encoding="utf-8")
    code = _cli(["assess", str(bad)])
    captured = capsys.readouterr()
    assert code == EXIT_VALIDATION
    error = json.loads(captured.out)
    assert error["contract"] == "grc.intake.error"
    assert error["error"] == "validation"
    assert error["assessed"] is False
    assert error["persisted"] is False
    assert any("vendor_name" in problem for problem in error["problems"])


def test_cli_preview_and_assess_file(tmp_path, capsys):
    source = FIXTURES / "vendor_intake.csv"
    code = _cli(["preview", str(source), "--as-of", AS_OF.isoformat()])
    captured = capsys.readouterr()
    assert code == EXIT_OK
    preview = json.loads(captured.out)
    assert preview["scored"] is False
    assert preview["can_assess"] is True
    assert "residual" not in preview

    code = _cli(["assess-file", str(FIXTURES / "vendor_intake.xlsx"), "--as-of", AS_OF.isoformat()])
    captured = capsys.readouterr()
    assert code == EXIT_OK
    batch = json.loads(captured.out)
    assert batch["count"] == 2
    assert batch["persisted"] is False
    assert batch["results"][0]["rule_set_version"]

    broken = tmp_path / "broken.csv"
    broken.write_bytes(render_questionnaire_csv([{**sample_forms()[0], "vendor_name": ""}]))
    code = _cli(["assess-file", str(broken), "--as-of", AS_OF.isoformat()])
    captured = capsys.readouterr()
    assert code == EXIT_VALIDATION
    rejected = json.loads(captured.out)
    assert rejected["contract"] == "grc.intake.import_preview"
    assert rejected["can_assess"] is False
    assert rejected["scored"] is False
    assert "results" not in rejected

    code = _cli(["preview", str(source), "--as-of", "2026-02-31"])
    captured = capsys.readouterr()
    assert code == EXIT_VALIDATION
    assert json.loads(captured.out)["error"] == "validation"


def test_cli_engine_error_is_a_distinct_exit_code(monkeypatch, capsys):
    def boom(_intake, _as_of):
        raise RuntimeError("rules failed")

    monkeypatch.setattr("app.services.bot_intake.run_intake", boom)
    code = _cli(["assess", "-"], json.dumps(request()))
    captured = capsys.readouterr()
    assert code == EXIT_ENGINE
    body = json.loads(captured.out)
    assert body["error"] == "engine"
    assert body["assessed"] is False
    assert "rules failed" in body["problems"][0]


def test_cli_usage_and_missing_file(capsys, monkeypatch):
    assert main([]) == EXIT_VALIDATION
    capsys.readouterr()
    code = _cli(["preview", "missing-intake.csv"])
    captured = capsys.readouterr()
    assert code == EXIT_VALIDATION
    assert json.loads(captured.out)["error"] == "validation"

    class _Tty:
        def isatty(self):
            return True

        def read(self):
            raise AssertionError("stdin should not be read")

    monkeypatch.setattr(sys, "stdin", _Tty())
    code = main(["assess"])
    captured = capsys.readouterr()
    assert code == EXIT_VALIDATION
    assert "stdin" in json.loads(captured.out)["problems"][0]


def test_module_entrypoint_assesses_and_rejects(tmp_path):
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request()), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, "-m", "app.cli", "assess", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == EXIT_OK
    body = json.loads(completed.stdout)
    assert body["residual"]["tier"] == engine_result()["risk"]["residual"]["tier"]
    assert body["persisted"] is False

    path.write_text("{}", encoding="utf-8")
    failed = subprocess.run(
        [sys.executable, "-m", "app.cli", "assess", str(path)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert failed.returncode == EXIT_VALIDATION
    assert json.loads(failed.stdout)["assessed"] is False
