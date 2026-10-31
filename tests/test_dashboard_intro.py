"""Empty-dashboard sample button, plain metrics line, and collapsed intake hints."""

import re

from app.services.intake_questionnaire import hint_parts, load_questionnaire
from app.services.org_policy import load_org_policy

RULE_CODE = re.compile(r"\b(?:INH|ESC|HR|CC)-[A-Z0-9]+\b")
HINT_CODE = re.compile(r"\b(?:INH|ESC|HR)-[A-Z0-9]+\b")


def _hint_texts():
    questionnaire = load_questionnaire()
    texts = [spec["help"] for spec in questionnaire["context_questions"]]
    texts.append(questionnaire["policy_question_help"])
    texts.append(questionnaire["access_evidence"]["help"])
    trust = questionnaire["trust_center"]
    texts.extend([trust["help"], trust["fetch_help"], trust["note"]])
    texts.extend(pointer["help"] for pointer in trust["pointers"])
    direction = questionnaire["direction_context"]
    texts.extend(spec["help"] for spec in direction["fields"])
    texts.append(direction["note_help"])
    texts.append(direction["note"])
    texts.extend(spec["help"] for spec in load_org_policy()["intake_fields"] if spec.get("help"))
    return texts


def test_hint_parts_keep_rule_codes_out_of_the_plain_sentence():
    coded = 0
    for text in _hint_texts():
        parts = hint_parts(text)
        assert RULE_CODE.search(parts["plain"]) is None
        if RULE_CODE.search(text):
            coded += 1
            assert parts["technical"]
            assert RULE_CODE.search(parts["technical"])
            for code in RULE_CODE.findall(text):
                assert code in parts["technical"]
        else:
            assert parts["technical"] == ""
            assert parts["plain"] == text.strip()
    assert coded >= 6


def test_try_form_hides_rule_codes_in_a_collapsed_details(client):
    body = client.get("/try/").get_data(as_text=True)
    assert "Show technical details" in body
    assert not re.search(r"<details\b[^>]*\bopen\b", body)
    outside = re.sub(r"<details\b.*?</details>", "", body, flags=re.S)
    assert HINT_CODE.search(outside) is None
    for code in ("INH-DATA", "INH-PERM", "HR-001", "ESC-001", "ESC-009", "CC-001"):
        assert code in body
    assert "It is not treated as public." in outside
    assert "Unknown stays unresolved and is not treated as no." in outside


def test_empty_dashboard_offers_sample_data_above_the_scenarios(client):
    body = client.get("/").get_data(as_text=True)
    assert 'id="load-samples"' in body
    assert "Load sample data" in body
    assert body.index("Load sample data") < body.index("What this demonstrates")
    assert body.index('id="load-samples"') < body.index("Repeatable scenarios")
    assert 'name="next" value="dashboard"' in body


def test_metrics_panel_leads_with_a_plain_sentence(client):
    body = client.get("/").get_data(as_text=True)
    plain = "measured from your own activity in this demo"
    definition = "These figures are not <code>calculate_cost()</code>"
    assert "how the risks you have assessed break down" in body
    assert "how long those reviews took" in body
    assert body.index(plain) < body.index(definition)
    assert "Definition 9" in body
    visible, technical = body.split('id="metrics-technical"', 1)
    assert "how the risks you have assessed break down" in visible
    assert definition not in visible
    assert technical.startswith('>') or 'class="technical-detail"' in body[body.index('id="metrics-technical"') - 40:]
    assert not technical.lstrip().startswith("open")
    assert definition in technical


UNMEASURED_NOTES = (
    "Save an intake and record a decision on it to see this.",
    "Record decisions dated at least 30 days apart to see this.",
    "Record review minutes on a decision to see this.",
    "Record rework minutes on a decision to see this.",
    "Record a manual-touch count on a decision to see this.",
    "Record a handoff count on a decision to see this.",
    "A signed-in reviewer records minutes on a decision to see this.",
    "A signed-in reviewer records whole dollars on a decision to see this.",
    "Needs an incident cost and an avoided-incident count in the cost assumptions.",
)


def test_not_measured_tiles_say_what_would_fill_them(client):
    body = client.get("/").get_data(as_text=True)
    for note in UNMEASURED_NOTES:
        assert note in body
    assert body.count("<strong>Not measured</strong>") >= len(UNMEASURED_NOTES)


def test_sample_rows_do_not_invent_unmeasured_figures(client):
    response = client.post("/risks/sample-data", data={"next": "dashboard"}, headers={"Origin": "http://localhost"})
    assert response.status_code == 302
    body = client.get("/").get_data(as_text=True)
    assert "Saved assessments: 3." in body
    for note in (
        "Record review minutes on a decision to see this.",
        "Save an intake and record a decision on it to see this.",
        "Needs an incident cost and an avoided-incident count in the cost assumptions.",
    ):
        assert note in body


def test_saved_risk_keeps_one_summary_and_a_sample_label(client):
    from tests.test_visitor_sandbox import SAME_ORIGIN

    saved = client.post("/demo/evidence-supported/register", headers=SAME_ORIGIN)
    assert saved.status_code == 302
    detail = client.get(saved.headers["Location"]).get_data(as_text=True)
    summary = detail.split('id="summary"', 1)[1].split('id="scores"', 1)[0]
    assert "In plain language" in summary
    assert "reviewed contract excerpt for the no-training clause" not in summary
    assert "not an approval" in summary
    loaded = client.post("/risks/sample-data", data={"next": "risks"}, headers=SAME_ORIGIN)
    assert loaded.status_code == 302
    register = client.get("/risks").get_data(as_text=True)
    assert "Sample:" in register
    sample_href = register.split("Sample:", 1)[0].rsplit('href="', 1)[-1].split('"', 1)[0]
    sample = client.get(sample_href).get_data(as_text=True)
    sample_summary = sample.split('id="summary"', 1)[1].split('id="scores"', 1)[0]
    assert "labeled sample data" in sample_summary
    assert "reviewed contract excerpt for the no-training clause" not in sample_summary
