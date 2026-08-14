from __future__ import annotations

from copy import deepcopy

import pytest

from apps.control_plane.variant_identity_resolution import (
    VariantIdentityConflict,
    VariantIdentityResolutionWorkspace,
)

SCOPE = {
    "tenant_ref": "tenant-a",
    "legal_entity_ref": "entity-a",
    "store_ref": "store-a",
}


def source(
    source_ref: str,
    source_kind: str,
    payload: dict,
    *,
    evidence_ref: str | None = None,
    scope: dict | None = None,
) -> dict:
    return {
        "source_ref": source_ref,
        "source_kind": source_kind,
        "scope": scope or SCOPE,
        "artifact_evidence_id": evidence_ref or f"ev-{source_ref}",
        "payload": payload,
    }


def project(records: list[dict], **kwargs) -> dict:
    return VariantIdentityResolutionWorkspace().project(
        scope=SCOPE,
        sources=records,
        **kwargs,
    )


def exact_records() -> list[dict]:
    return [
        source(
            "product-info",
            "ozon_product_info",
            {
                "offer_id": "1982483707WZ",
                "sku": 2078100418,
                "sources": [{"sku": 2078100418, "source": "sds"}],
                "barcodes": ["OZN2078100418"],
                "model_info": {"model_id": 557449904},
                "attributes": [
                    {
                        "id": 10096,
                        "complex_id": 0,
                        "values": [{"dictionary_value_id": 61576, "value": "grey"}],
                    }
                ],
                "name": "Cordless garden saw",
                "description_category_id": 17028946,
            },
        ),
        source(
            "catalog",
            "ozon_catalog",
            {
                "offer_id": "1982483707WZ",
                "sku": "2078100418",
                "barcode": "OZN2078100418",
                "model_id": "557449904",
                "controlled_attributes": {"color-id": "61576"},
                "name": "Cordless garden saw",
                "description_category_id": 17028946,
            },
        ),
        source(
            "finance-item",
            "ozon_finance_item",
            {
                "items": [{"name": "Cordless garden saw", "sku": 2078100418}],
            },
        ),
    ]


def test_exact_offer_platform_sku_barcode_and_finance_item_are_linked_read_only() -> None:
    result = project(exact_records())

    assert result["summary"] == {
        "source_total": 3,
        "accepted": 3,
        "quarantined": 0,
        "unresolved": 0,
        "exact_resolution_count": 1,
        "candidate_proposal_count": 0,
        "quarantine_group_count": 0,
        "duplicate_input_occurrences": 0,
    }
    resolution = result["exact_resolutions"][0]
    assert resolution["status"] == "exact"
    assert resolution["source_refs"] == ["catalog", "finance-item", "product-info"]
    assert resolution["matched_on"] == {
        "offer_id": ["1982483707WZ"],
        "platform_sku": ["2078100418"],
        "barcode": ["OZN2078100418"],
    }
    assert resolution["identity"]["platform_sku"] == "2078100418"
    assert resolution["identity"]["model_group_id"] == "557449904"
    assert resolution["model_id_used_as_exact_anchor"] is False
    assert resolution["automatic_merge_allowed"] is False
    assert resolution["formal_fact_promoted"] is False
    assert result["control_envelope"]["external_write_allowed"] is False
    assert result["reconciliation"]["conservation_passed"] is True


def test_model_id_is_only_a_group_candidate_even_when_title_and_category_agree() -> None:
    records = [
        source(
            "variant-red",
            "ozon_product_info",
            {
                "offer_id": "CHAIR-RED",
                "sku": 2021922992,
                "model_info": {"model_id": 497634578},
                "name": "Folding chair red 178 cm",
                "description_category_id": 170111,
            },
        ),
        source(
            "variant-blue",
            "ozon_product_info",
            {
                "offer_id": "CHAIR-BLUE",
                "sku": 2021923794,
                "model_info": {"model_id": 497634578},
                "name": "Folding chair blue 178 cm",
                "description_category_id": 170111,
            },
        ),
    ]

    result = project(records)

    assert result["summary"]["accepted"] == 0
    assert result["summary"]["unresolved"] == 2
    assert result["exact_resolutions"] == []
    assert len(result["candidate_proposals"]) == 1
    proposal = result["candidate_proposals"][0]
    assert proposal["relationship"] == "model_group_sibling_candidate"
    assert proposal["model_group_ids"] == ["497634578"]
    assert "model_id_is_group_not_variant" in proposal["reason_codes"]
    assert proposal["exact_variant"] is False
    assert proposal["formal_fact_promoted"] is False


def test_title_and_category_similarity_can_only_create_a_review_proposal() -> None:
    records = [
        source(
            "market-a",
            "market_observation",
            {
                "name": "Naturehike Cloud Up lightweight camping tent grey",
                "category_id": "tent",
            },
        ),
        source(
            "supplier-b",
            "supplier_variant",
            {
                "title": "Naturehike Cloud Up lightweight camping tent yellow",
                "category_id": "tent",
            },
        ),
    ]

    result = project(records)

    assert result["exact_resolutions"] == []
    assert result["summary"]["unresolved"] == 2
    proposal = result["candidate_proposals"][0]
    assert proposal["relationship"] == "descriptive_similarity_candidate"
    assert proposal["signals"] == ["category_similarity", "title_similarity"]
    assert proposal["exact_variant"] is False
    assert proposal["automatic_merge_allowed"] is False


def test_same_offer_with_different_platform_skus_is_quarantined_with_full_lineage() -> None:
    records = [
        source(
            "catalog",
            "ozon_catalog",
            {"offer_id": "SKU-1", "sku": 1001, "barcodes": ["OZN1001"]},
            evidence_ref="ev-catalog",
        ),
        source(
            "product",
            "ozon_product_info",
            {"offer_id": "SKU-1", "sku": 1002, "barcodes": ["OZN1002"]},
            evidence_ref="ev-product",
        ),
    ]

    result = project(records)

    assert result["summary"]["accepted"] == 0
    assert result["summary"]["quarantined"] == 2
    assert result["summary"]["unresolved"] == 0
    quarantine = result["quarantine"][0]
    assert quarantine["source_refs"] == ["catalog", "product"]
    assert "platform_sku_conflict" in quarantine["reason_codes"]
    assert "transitive_platform_sku_conflict" in quarantine["reason_codes"]
    assert quarantine["evidence_refs"] == ["ev-catalog", "ev-product"]
    assert quarantine["sources"][0]["original_identifiers"]["sku"] == 1001
    assert quarantine["sources"][1]["original_identifiers"]["sku"] == 1002
    assert quarantine["automatic_merge_allowed"] is False


def test_controlled_attribute_conflict_on_same_sku_is_quarantined() -> None:
    records = [
        source(
            "attribute-a",
            "ozon_attributes",
            {
                "sku": 9001,
                "attributes": [
                    {
                        "id": 10096,
                        "complex_id": 0,
                        "values": [{"dictionary_value_id": 61576, "value": "grey"}],
                    }
                ],
            },
        ),
        source(
            "attribute-b",
            "ozon_product_info",
            {
                "sku": 9001,
                "attributes": [
                    {
                        "id": 10096,
                        "complex_id": 0,
                        "values": [{"dictionary_value_id": 61578, "value": "yellow"}],
                    }
                ],
            },
        ),
    ]

    result = project(records)

    assert result["summary"]["quarantined"] == 2
    reasons = result["quarantine"][0]["reason_codes"]
    assert "controlled_attribute_conflict:ozon:10096:0" in reasons
    assert "transitive_controlled_attribute_conflict:ozon:10096:0" in reasons


def test_transitive_identifier_conflict_quarantines_the_whole_connected_group() -> None:
    records = [
        source("a", "ozon_catalog", {"offer_id": "OFFER-1", "sku": 1001}),
        source("b", "ozon_product_info", {"offer_id": "OFFER-1", "barcode": "SHARED"}),
        source("c", "ozon_attributes", {"sku": 1002, "barcode": "SHARED"}),
    ]

    result = project(records)

    assert result["summary"]["quarantined"] == 3
    assert result["exact_resolutions"] == []
    quarantine = result["quarantine"][0]
    assert quarantine["source_refs"] == ["a", "b", "c"]
    assert "transitive_platform_sku_conflict" in quarantine["reason_codes"]


def test_unmatched_and_invalid_identifiers_remain_visible_and_conserve_source_total() -> None:
    records = [
        source("unmatched", "supplier_variant", {"source_sku": "not-an-ozon-sku"}),
        source("empty", "browser_capture", {"name": "Unknown item"}),
    ]

    result = project(records)

    assert result["reconciliation"] == {
        "source_total": 2,
        "accepted": 0,
        "quarantined": 0,
        "unresolved": 2,
        "accepted_plus_quarantined_plus_unresolved": 2,
        "conservation_passed": True,
        "all_source_refs_retained": True,
    }
    inventory = {item["source_ref"]: item for item in result["source_inventory"]}
    assert "invalid_source_sku" in inventory["unmatched"]["reason_codes"]
    assert "no_exact_controlled_identifier_match" in inventory["empty"]["reason_codes"]
    assert inventory["unmatched"]["original_identifiers"]["source_sku"] == "not-an-ozon-sku"


def test_input_order_and_exact_duplicate_occurrences_are_deterministic() -> None:
    records = exact_records()
    first = project(records)
    reordered = project(list(reversed(records)))
    duplicated = project([*records, deepcopy(records[0])])

    assert reordered["input_sha256"] == first["input_sha256"]
    assert reordered["projection_sha256"] == first["projection_sha256"]
    assert reordered["exact_resolutions"] == first["exact_resolutions"]
    assert duplicated["input_sha256"] == first["input_sha256"]
    assert duplicated["summary"]["source_total"] == 3
    assert duplicated["summary"]["duplicate_input_occurrences"] == 1


def test_duplicate_source_ref_with_changed_identity_content_is_a_drift_conflict() -> None:
    first = source("stable", "ozon_product_info", {"offer_id": "A", "sku": 1001})
    changed = deepcopy(first)
    changed["payload"]["sku"] = 1002

    with pytest.raises(VariantIdentityConflict, match="conflicting immutable identity content"):
        project([first, changed])


def test_expected_input_hash_detects_stateless_replay_drift() -> None:
    records = exact_records()
    first = project(records)

    replay = project(records, expected_input_sha256=first["input_sha256"])
    assert replay["input_sha256"] == first["input_sha256"]

    changed = deepcopy(records)
    changed[0]["payload"]["offer_id"] = "CHANGED"
    with pytest.raises(VariantIdentityConflict, match="replay content drift"):
        project(changed, expected_input_sha256=first["input_sha256"])


@pytest.mark.parametrize("field", ["tenant_ref", "legal_entity_ref", "store_ref"])
def test_cross_tenant_legal_entity_or_store_source_is_rejected(field: str) -> None:
    wrong_scope = deepcopy(SCOPE)
    wrong_scope[field] = f"wrong-{field}"
    record = source("outside", "ozon_catalog", {"offer_id": "A"}, scope=wrong_scope)

    with pytest.raises(PermissionError, match="outside the authorized tenant/legal_entity/store scope"):
        project([record])


def test_entity_ref_alias_is_supported_but_conflicting_aliases_fail_closed() -> None:
    entity_scope = {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
    }
    record = source(
        "entity-alias",
        "ozon_catalog",
        {"offer_id": "A"},
        scope=entity_scope,
    )
    result = project([record])
    assert result["scope"]["entity_ref"] == "entity-a"

    conflicting = {
        **entity_scope,
        "legal_entity_ref": "different-entity",
    }
    with pytest.raises(ValueError, match="conflicting entity_ref and legal_entity_ref"):
        VariantIdentityResolutionWorkspace().project(scope=conflicting, sources=[])


def test_unscoped_supplier_source_sku_cannot_collide_into_an_ozon_exact_match() -> None:
    records = [
        source("ozon", "ozon_product_info", {"sku": 1001}),
        source("supplier", "supplier_variant", {"source_sku": 1001}),
    ]

    result = project(records)

    assert result["exact_resolutions"] == []
    assert result["summary"]["accepted"] == 0
    assert result["summary"]["unresolved"] == 2
    supplier = next(item for item in result["source_inventory"] if item["source_ref"] == "supplier")
    assert supplier["platform_namespace"] == "unverified"
    assert "source_sku_namespace_unverified" in supplier["reason_codes"]
    assert supplier["normalized_identifiers"]["source_skus"] == []


def test_declared_ozon_namespace_allows_generic_capture_source_sku_matching() -> None:
    records = [
        source("ozon", "ozon_product_info", {"sku": 1001}),
        source(
            "capture",
            "marketplace_capture",
            {"platform_namespace": "ozon", "source_sku": "1001"},
        ),
    ]

    result = project(records)

    assert result["summary"]["accepted"] == 2
    assert result["exact_resolutions"][0]["matched_on"] == {"platform_sku": ["1001"]}


def test_one_source_with_conflicting_controlled_attribute_claims_is_quarantined() -> None:
    record = source(
        "self-conflict",
        "ozon_attributes",
        {
            "sku": 1001,
            "controlled_attributes": {"color": "grey"},
            "product_identity": {
                "controlled_attributes": {"color": "yellow"},
            },
        },
    )

    result = project([record])

    assert result["summary"]["quarantined"] == 1
    assert result["quarantine"][0]["reason_codes"] == ["source_controlled_attribute_conflict:declared:color"]


def test_multiple_finance_item_skus_are_quarantined_not_allocated_or_merged() -> None:
    record = source(
        "finance-operation",
        "ozon_finance",
        {
            "items": [
                {"name": "Variant A", "sku": 1001},
                {"name": "Variant B", "sku": 1002},
            ]
        },
    )

    result = project([record])

    assert result["summary"]["quarantined"] == 1
    assert result["summary"]["accepted"] == 0
    assert result["quarantine"][0]["reason_codes"] == ["source_finance_item_sku_ambiguous"]
    assert result["quarantine"][0]["sources"][0]["original_identifiers"]["finance_items"] == [
        {"name": "Variant A", "sku": 1001},
        {"name": "Variant B", "sku": 1002},
    ]
