"""Tests for traceable, draft control mappings."""

import copy

import pytest

from app.services.control_mapper import MappingInputError, load_mappings, map_claims


def test_claim_topic_maps_to_catalog_item_and_preserves_trace_links():
    claims = [{"claim_id": "C-auth", "topic": "authentication", "evidence_status": "verified",
               "evidence": [{"evidence_id": "E1", "status": "verified"}]}]
    mapped = map_claims(claims)
    assert len(mapped) == 1
    item = mapped[0]
    assert item["control_id"] == "IA-2"
    assert item["framework_version"] == "Revision 5, Release 5.2.0"
    assert item["review_status"] == "draft"
    assert item["related_claims"] == [{"claim_id": "C-auth", "evidence_status": "verified"}]
    assert item["related_evidence"] == [{"evidence_id": "E1", "status": "verified"}]


def test_unmatched_or_untagged_claims_do_not_get_invented_mappings():
    assert map_claims([{"claim_id": "C-other", "statement": "Unknown topic"}]) == []
    assert map_claims([{"claim_id": "C-other", "topic": "unknown"}]) == []


def test_multiple_claims_for_topic_are_all_retained():
    mapped = map_claims([
        {"claim_id": "C1", "topic": "integration_permissions", "evidence_status": "missing", "evidence": []},
        {"claim_id": "C2", "topic": "integration_permissions", "evidence_status": "self_attested", "evidence": []},
    ])
    assert mapped[0]["control_id"] == "AC-6"
    assert [c["claim_id"] for c in mapped[0]["related_claims"]] == ["C1", "C2"]


def test_mapping_is_deterministic_and_does_not_mutate_claims():
    claims = [{"claim_id": "C1", "topic": "audit_logging", "evidence_status": "missing", "evidence": []}]
    before = copy.deepcopy(claims)
    assert map_claims(claims) == map_claims(claims)
    assert claims == before


@pytest.mark.parametrize("claims", [None, ["bad"], [{"topic": "authentication"}],
                                    [{"claim_id": "C1"}, {"claim_id": "C1"}],
                                    [{"claim_id": "C1", "topic": 12}]])
def test_invalid_claims_are_rejected(claims):
    with pytest.raises(MappingInputError):
        map_claims(claims)


def test_invalid_mapping_review_status_is_rejected():
    mapping_set = load_mappings()
    mapping_set["mappings"][0]["review_status"] = "approved"
    with pytest.raises(MappingInputError):
        map_claims([], mapping_set)
