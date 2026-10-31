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
