from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from apps.control_plane.profit_data_remediation import (
    ProfitDataRemediationConflict,
    ProfitDataRemediationInvariantError,
    ProfitDataRemediationWorkspace,
)

AS_OF = datetime(2026, 8, 2, 8, tzinfo=UTC)
SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "store-a",
    "scope_grant_authority_sha256": "a" * 64,
}


def bundle(*, accepted: int = 1, quarantined: int = 2) -> dict:
    return {
        "bundle_id": "mrb-a",
        "bundle_sha256": "b" * 64,
        "archive_evidence_id": "ev-archive",
        "scope": SCOPE,
        "status": "partial",
        "counts": {
            "source_total": accepted + quarantined,
            "accepted": accepted,
            "quarantined": quarantined,
        },
        "quality": {"complete_source_retention": True},
    }


def sources() -> list[dict]:
    return [
        {
            "id": "src-product",
            "bundle_id": "mrb-a",
            **SCOPE,
            "artifact_path": "full_product_info.json",
            "artifact_kind": "ozon_product_info",
            "record_index": 0,
            "record_key": "SKU-1",
            "source_sha256": "1" * 64,
            "artifact_evidence_id": "ev-product",
            "disposition": "accepted",
            "highest_stage": "normalized_observation",
            "reason_codes_json": [],
            "payload_json": {"offer_id": "SKU-1", "price": "199.00", "currency_code": "CNY"},
        },
        {
            "id": "src-finance",
            "bundle_id": "mrb-a",
            **SCOPE,
            "artifact_path": "finance_by_month.json",
            "artifact_kind": "ozon_finance",
            "record_index": 0,
            "record_key": "2026-07",
            "source_sha256": "2" * 64,
            "artifact_evidence_id": "ev-finance",
            "disposition": "quarantined",
            "highest_stage": "raw_evidence",
            "reason_codes_json": ["money_currency_missing"],
            "payload_json": {"month": "2026-07", "operations": [{"amount": "12.3"}]},
        },
        {
            "id": "src-supplier",
            "bundle_id": "mrb-a",
            **SCOPE,
            "artifact_path": "supply_1688/supply_crawl.json",
            "artifact_kind": "supplier_catalog",
            "record_index": 7,
            "record_key": "SKU-1",
            "source_sha256": "3" * 64,
            "artifact_evidence_id": "ev-supplier",
            "disposition": "quarantined",
            "highest_stage": "raw_evidence",
            "reason_codes_json": ["variant_identity_unresolved"],
            "payload_json": {"sku": "SKU-1", "supplier_cards": []},
        },
    ]


def candidate(*, candidate_id: str = "ozon:SKU-1", sku: str = "SKU-1") -> dict:
    return {
        "candidate_id": candidate_id,
        "offer_id": sku,
        "decision_class": "needs_data",
        "reason_codes": [
            "fx_basis_missing",
            "fifteen_component_cost_evidence_incomplete",
            "settlement_profit_missing",
            "cash_profit_missing",
        ],
        "raw_money": {
            "display_currency": "CNY",
            "own_price": {"amount": "199", "currency": "CNY"},
            "market_reference_price": {"amount": "2100", "currency": "RUB"},
            "fx_basis": None,
        },
        "profit": {
            "risk_adjusted_profit": {
                "status": "available",
                "downside_cm3": "-42.50",
                "currency": "CNY",
            },
            "cash_profit": {
                "status": "no_data",
                "amount": None,
                "currency": None,
                "reason": "bank_cash_profit_not_bound_to_sku",
            },
        },
        "cost_coverage": {"required": 15, "evidenced": 0},
        "evidence_ids": ["ev-product"],
        "input_sha256": "c" * 64,
    }


def project(*, source_records=None, candidate_records=None, bundle_record=None):
    return ProfitDataRemediationWorkspace().project(
        scope=SCOPE,
        bundle=bundle_record or bundle(),
        source_items=source_records if source_records is not None else sources(),
        candidates={
            "scope": SCOPE,
            "candidates": candidate_records if candidate_records is not None else [candidate()],
        },
        as_of=AS_OF,
    )


def test_workspace_reconciles_all_sources_and_never_guesses_missing_evidence() -> None:
    result = project()

    assert result["reconciliation"] == {
        "source_total": 3,
        "accepted": 1,
        "quarantined": 2,
        "accepted_plus_quarantined": 3,
        "conservation_passed": True,
        "declared_counts_match": True,
        "all_source_items_retained": True,
        "duplicate_input_occurrences": 0,
    }
    assert {item["source_item_id"] for item in result["source_inventory"]} == {
        "src-product",
        "src-finance",
        "src-supplier",
    }
    assert result["control_envelope"]["missing_values_guessed"] is False
    assert result["control_envelope"]["cross_currency_aggregation_performed"] is False
    assert all(item["missing_value_guessed"] is False for item in result["remediation_queue"])
    money_issue = next(
        item for item in result["remediation_queue"] if item["error_code"] == "money_currency_missing"
    )
    assert money_issue["estimated_loss_exposure"]["status"] == "no_data"
    assert money_issue["lineage"]["source_item_id"] == "src-finance"
    assert money_issue["evidence_ids"] == ["ev-finance"]


def test_order_ids_hashes_and_groups_are_deterministic_under_input_reordering() -> None:
    first = project()
    second = project(
        source_records=list(reversed(sources())),
        candidate_records=[deepcopy(candidate())],
    )

    assert second["workspace_id"] == first["workspace_id"]
    assert second["input_sha256"] == first["input_sha256"]
    assert [item["remediation_item_id"] for item in second["remediation_queue"]] == [
        item["remediation_item_id"] for item in first["remediation_queue"]
    ]
    assert set(first["groups"]) == {
        "by_sku",
        "by_source",
        "by_error_code",
        "by_evidence_requirement",
    }
    fx_issue = next(item for item in first["remediation_queue"] if item["error_code"] == "fx_basis_missing")
    variant_issue = next(
        item
        for item in first["remediation_queue"]
        if item["error_code"] == "variant_identity_unresolved"
    )
    assert fx_issue["priority_rank"] < variant_issue["priority_rank"]
    assert fx_issue["value_at_risk"] == {
        "status": "derived_from_reported_negative_profit",
        "amount": "42.5",
        "currency": "CNY",
        "basis": "negative_risk_adjusted_downside_cm3",
        "evidence_ids": ["ev-product"],
    }
    assert fx_issue["action"]["owner_role"] == "finance-control"
    assert fx_issue["action"]["deadline_class"] == "before_any_financial_action"


def test_exact_duplicate_inputs_are_idempotent_but_content_drift_conflicts() -> None:
    duplicated_sources = sources() + [deepcopy(sources()[0])]
    result = project(
        source_records=duplicated_sources,
        candidate_records=[candidate(), deepcopy(candidate())],
    )

    assert result["reconciliation"]["source_total"] == 3
    assert result["summary"]["duplicate_source_inputs"] == 1
    assert result["summary"]["duplicate_candidate_inputs"] == 1

    conflicting = sources() + [deepcopy(sources()[0])]
    conflicting[-1]["payload_json"]["price"] = "999"
    with pytest.raises(ProfitDataRemediationConflict, match="conflicting immutable content"):
        project(source_records=conflicting)


def test_stale_and_blocked_items_remain_visible_with_explicit_non_automatic_actions() -> None:
    stale_sources = sources()
    stale_sources[0]["effective_until"] = (AS_OF - timedelta(seconds=1)).isoformat()
    blocked_candidate = candidate()
    blocked_candidate["status"] = "blocked"
    blocked_candidate["reason_codes"] = []

    result = project(source_records=stale_sources, candidate_records=[blocked_candidate])

    stale_issue = next(
        item
        for item in result["remediation_queue"]
        if item["origin_id"] == "src-product" and item["error_code"] == "source_evidence_stale"
    )
    blocked_issue = next(
        item for item in result["remediation_queue"] if item["error_code"] == "candidate_blocked"
    )
    assert stale_issue["status"] == "stale"
    assert stale_issue["action"]["action_code"] == "refresh_source_evidence"
    assert blocked_issue["status"] == "blocked"
    assert blocked_issue["action"]["automatic_execution_allowed"] is False
    assert result["status"] == "blocked"


@pytest.mark.parametrize("location", ["bundle", "source", "candidate"])
def test_cross_scope_records_are_rejected_before_projection(location: str) -> None:
    wrong_scope = {**SCOPE, "tenant_ref": "tenant-b"}
    bundle_record = bundle()
    source_records = sources()
    candidate_workspace = {"scope": SCOPE, "candidates": [candidate()]}
    if location == "bundle":
        bundle_record["scope"] = wrong_scope
    elif location == "source":
        source_records[0]["tenant_ref"] = "tenant-b"
    else:
        candidate_workspace["scope"] = wrong_scope

    with pytest.raises(PermissionError, match="outside the authorized remediation scope"):
        ProfitDataRemediationWorkspace().project(
            scope=SCOPE,
            bundle=bundle_record,
            source_items=source_records,
            candidates=candidate_workspace,
            as_of=AS_OF,
        )


def test_declared_and_observed_reconciliation_invariants_fail_closed() -> None:
    invalid_bundle = bundle()
    invalid_bundle["counts"]["source_total"] = 99
    with pytest.raises(
        ProfitDataRemediationInvariantError,
        match=r"accepted \+ quarantined = source_total",
    ):
        project(bundle_record=invalid_bundle)

    with pytest.raises(
        ProfitDataRemediationInvariantError,
        match="does not reconcile",
    ):
        project(source_records=sources()[:-1])


def test_finite_source_json_float_is_retained_as_decimal_text() -> None:
    records = sources()
    records[0]["payload_json"]["observed_ratio"] = 806.9782608695652

    result = project(source_records=records)

    retained = next(
        item for item in result["source_inventory"] if item["source_item_id"] == "src-product"
    )
    assert retained["payload"]["observed_ratio"] == "806.9782608695652"
