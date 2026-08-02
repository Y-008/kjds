from __future__ import annotations

from copy import deepcopy

import pytest

from apps.control_plane.ozon_finance_allocation import (
    OzonFinanceAllocationConflict,
    OzonFinanceAllocationInvariantError,
    OzonFinanceAllocationWorkspace,
)

SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": "a" * 64,
}


def envelope(key: str, items: list[dict], *, scope: dict | None = None, **extra) -> dict:
    return {"scope": scope or SCOPE, key: items, **extra}


def mapping(platform_sku: str, sku: str, *, mapping_id: str | None = None) -> dict:
    return {
        "mapping_id": mapping_id or f"map-{platform_sku}",
        "platform_sku": platform_sku,
        "canonical_sku": sku,
        "evidence_id": f"ev-map-{platform_sku}",
    }


def operation(
    operation_id: str,
    amount: str,
    *,
    posting_number: str,
    item_skus: list[str] | None = None,
    operation_type: str = "sale",
) -> dict:
    return {
        "operation_id": operation_id,
        "operation_type": operation_type,
        "operation_date": "2026-07-16T10:00:00+03:00",
        "amount": amount,
        "posting": {
            "posting_number": posting_number,
            "items": [{"sku": sku, "name": f"item-{sku}"} for sku in (item_skus or [])],
        },
        "source_evidence_id": f"ev-operation-{operation_id}",
    }


def currencies(*operation_ids: str, currency: str = "RUB") -> dict:
    return envelope(
        "records",
        [
            {
                "evidence_id": "ev-currency-rub",
                "currency": currency,
                "operation_ids": list(operation_ids),
                "effective_at": "2026-07-01T00:00:00Z",
            }
        ],
    )


def project(operations: list[dict], mappings: list[dict], currency_evidence: dict | None):
    return OzonFinanceAllocationWorkspace().project(
        scope=SCOPE,
        operations=envelope("operations", operations, evidence_ids=["ev-finance-export"]),
        listing_mappings=envelope("mappings", mappings),
        currency_evidence=currency_evidence,
    )


def test_direct_item_and_itemless_fee_allocate_only_to_one_exact_posting_sku() -> None:
    result = project(
        [
            operation("op-sale", "1000.00", posting_number="post-1", item_skus=["2078100418"]),
            operation(
                "op-fee",
                "-125.50",
                posting_number="post-1",
                operation_type="platform_fee",
            ),
        ],
        [mapping("2078100418", "KJDS-001")],
        currencies("op-sale", "op-fee"),
    )

    assert result["status"] == "ready"
    assert result["summary"] == {
        "source_total": 2,
        "accepted": 2,
        "quarantined": 0,
        "unallocated": 0,
        "finance_entry_proposals": 2,
        "posting_groups": 1,
        "exact_listing_mappings": 1,
        "duplicate_operation_inputs": 0,
        "duplicate_mapping_inputs": 0,
        "duplicate_currency_evidence_inputs": 0,
    }
    by_id = {item["operation_id"]: item for item in result["operations"]}
    assert by_id["op-sale"]["allocation_basis"] == "direct_exact_platform_sku"
    assert by_id["op-fee"]["allocation_basis"] == ("itemless_fee_inherited_from_single_exact_posting_sku")
    assert by_id["op-fee"]["amount_raw"] == "-125.50"
    assert by_id["op-fee"]["occurred_at_raw"] == "2026-07-16T10:00:00+03:00"
    assert by_id["op-fee"]["sku"] == "KJDS-001"
    assert by_id["op-fee"]["currency"] == "RUB"
    assert by_id["op-fee"]["finance_entry_proposal"]["formal_fact"] is False
    assert result["control_envelope"]["finance_entry_persisted"] is False
    assert result["control_envelope"]["proportional_allocation_performed"] is False

    reconciliation = result["reconciliation"]
    assert reconciliation["accepted_plus_quarantined_plus_unallocated"] == 2
    assert reconciliation["count_conservation_passed"] is True
    assert reconciliation["known_currency_amount_conservation"] == [
        {
            "currency": "RUB",
            "source_amount": "874.50",
            "accepted_amount": "874.50",
            "quarantined_amount": "0",
            "unallocated_amount": "0",
            "retained_amount": "874.50",
            "conservation_passed": True,
        }
    ]


def test_multi_sku_posting_never_pro_rata_allocates_itemless_fee() -> None:
    result = project(
        [
            operation("op-a", "600", posting_number="post-multi", item_skus=["100"]),
            operation("op-b", "400", posting_number="post-multi", item_skus=["200"]),
            operation(
                "op-fee",
                "-90",
                posting_number="post-multi",
                operation_type="fee",
            ),
        ],
        [mapping("100", "SKU-A"), mapping("200", "SKU-B")],
        currencies("op-a", "op-b", "op-fee"),
    )

    fee = next(item for item in result["operations"] if item["operation_id"] == "op-fee")
    assert fee["disposition"] == "unallocated"
    assert fee["platform_sku"] is None
    assert fee["finance_entry_proposal"] is None
    assert "posting_contains_multiple_exact_skus" in fee["reason_codes"]
    assert result["summary"]["accepted"] == 2
    assert result["summary"]["unallocated"] == 1
    assert result["control_envelope"]["proportional_allocation_performed"] is False
    rub = result["reconciliation"]["known_currency_amount_conservation"][0]
    assert rub["source_amount"] == "910"
    assert rub["accepted_amount"] == "1000"
    assert rub["unallocated_amount"] == "-90"
    assert rub["conservation_passed"] is True


def test_multi_item_operation_and_unmapped_or_non_numeric_skus_remain_unallocated() -> None:
    result = project(
        [
            operation("op-multi", "100", posting_number="post-a", item_skus=["100", "200"]),
            operation("op-unmapped", "200", posting_number="post-b", item_skus=["999"]),
            operation("op-text", "300", posting_number="post-c", item_skus=["offer-not-sku"]),
        ],
        [mapping("100", "SKU-A"), mapping("200", "SKU-B")],
        currencies("op-multi", "op-unmapped", "op-text"),
    )

    assert result["status"] == "blocked"
    assert result["summary"]["unallocated"] == 3
    assert result["finance_entry_proposals"] == []
    reasons = {item["operation_id"]: item["reason_codes"] for item in result["operations"]}
    assert "multi_sku_operation_requires_explicit_line_allocation" in reasons["op-multi"]
    assert "operation_platform_sku_unmapped" in reasons["op-unmapped"]
    assert "operation_contains_invalid_item_sku" in reasons["op-text"]


def test_missing_currency_keeps_raw_operation_blocked_and_creates_no_entry_proposal() -> None:
    source = operation(
        "op-no-currency",
        "42.5000",
        posting_number="post-1",
        item_skus=["100"],
    )
    result = project([source], [mapping("100", "SKU-A")], None)

    item = result["operations"][0]
    assert result["status"] == "blocked"
    assert item["disposition"] == "quarantined"
    assert item["profit_eligibility"] == "blocked_raw"
    assert item["amount_raw"] == "42.5000"
    assert item["raw_operation"] == source
    assert item["finance_entry_proposal"] is None
    assert item["reason_codes"] == ["finance_currency_missing"]
    assert result["reconciliation"]["unknown_currency_operations"] == 1
    assert result["control_envelope"]["currency_inferred_from_marketplace"] is False


def test_currency_conflict_and_invalid_operation_are_quarantined_but_retained() -> None:
    invalid = operation("op-conflict", "not-money", posting_number="post-1", item_skus=["100"])
    evidence = envelope(
        "records",
        [
            {"evidence_id": "ev-rub", "currency": "RUB", "operation_id": "op-conflict"},
            {"evidence_id": "ev-cny", "currency": "CNY", "operation_id": "op-conflict"},
        ],
    )
    result = project([invalid], [mapping("100", "SKU-A")], evidence)

    item = result["operations"][0]
    assert item["disposition"] == "quarantined"
    assert item["amount_raw"] == "not-money"
    assert item["currency"] is None
    assert item["finance_entry_proposal"] is None
    assert "operation_amount_invalid" in item["reason_codes"]
    assert result["reconciliation"]["count_conservation_passed"] is True
    assert result["reconciliation"]["all_source_operations_retained"] is True


def test_exact_duplicates_are_idempotent_and_content_drift_conflicts() -> None:
    source = operation("op-1", "10.00", posting_number="post-1", item_skus=["100"])
    map_one = mapping("100", "SKU-A", mapping_id="stable-map")
    currency = currencies("op-1")
    first = project([source], [map_one], currency)
    replay = project([deepcopy(source), deepcopy(source)], [map_one, deepcopy(map_one)], currency)

    assert replay["proposal_id"] == first["proposal_id"]
    assert replay["input_sha256"] == first["input_sha256"]
    assert replay["summary"]["source_total"] == 1
    assert replay["summary"]["duplicate_operation_inputs"] == 1
    assert replay["summary"]["duplicate_mapping_inputs"] == 1

    changed = deepcopy(source)
    changed["amount"] = "11.00"
    with pytest.raises(OzonFinanceAllocationConflict, match="conflicting immutable content"):
        project([source, changed], [map_one], currency)

    changed_map = deepcopy(map_one)
    changed_map["canonical_sku"] = "SKU-B"
    with pytest.raises(OzonFinanceAllocationConflict, match="Listing mapping"):
        project([source], [map_one, changed_map], currency)


@pytest.mark.parametrize("source_kind", ["operations", "mappings", "currency"])
def test_cross_scope_inputs_are_rejected_before_projection(source_kind: str) -> None:
    other_scope = {**SCOPE, "store_ref": "other-store"}
    operations = envelope(
        "operations",
        [operation("op-1", "10", posting_number="post-1", item_skus=["100"])],
        scope=other_scope if source_kind == "operations" else SCOPE,
        evidence_ids=["ev-export"],
    )
    mappings = envelope(
        "mappings",
        [mapping("100", "SKU-A")],
        scope=other_scope if source_kind == "mappings" else SCOPE,
    )
    currency = currencies("op-1")
    if source_kind == "currency":
        currency["scope"] = other_scope

    with pytest.raises(OzonFinanceAllocationInvariantError, match="crosses tenant"):
        OzonFinanceAllocationWorkspace().project(
            scope=SCOPE,
            operations=operations,
            listing_mappings=mappings,
            currency_evidence=currency,
        )


def test_item_level_scope_drift_and_count_invariant_fail_closed() -> None:
    source = operation("op-1", "10", posting_number="post-1", item_skus=["100"])
    source["scope"] = {**SCOPE, "entity_ref": "other-entity"}
    with pytest.raises(OzonFinanceAllocationInvariantError, match="crosses tenant"):
        project([source], [mapping("100", "SKU-A")], currencies("op-1"))

    assert OzonFinanceAllocationWorkspace._status(source_total=0, accepted=0) == "no_data"
