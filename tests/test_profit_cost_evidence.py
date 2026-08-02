from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from apps.control_plane.finance import ACTUAL_PROFIT_COST_TYPES
from apps.control_plane.profit_cost_evidence import (
    COST_REQUIREMENTS,
    ProfitCostEvidenceConflict,
    ProfitCostEvidenceWorkspace,
)
from apps.control_plane.scoped_profit_ledger import COST_ORDER, ScopedProfitLedgerAuthority

AS_OF = datetime(2026, 8, 2, 8, tzinfo=UTC)
SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "store-a",
}


def scoped(payload: dict) -> dict:
    return {**payload, "scope": SCOPE}


def variant(*, exact: bool = True) -> dict:
    return scoped(
        {
            "status": "exact" if exact else "candidate",
            "variant_ref": "variant-1" if exact else "",
            "evidence_id": "ev-variant" if exact else "",
        }
    )


def quantity(*, exact: bool = True) -> dict:
    return scoped(
        {
            "value": "10" if exact else None,
            "basis": "exact" if exact else "estimated",
            "evidence_id": "ev-quantity" if exact else "",
        }
    )


def cost_record(cost_type: str, level: str = "reviewed", *, currency: str = "CNY") -> dict:
    requirement = next(item for item in COST_REQUIREMENTS if item.cost_type == cost_type)
    record = scoped(
        {
            "cost_type": cost_type,
            "evidence_id": f"ev-{cost_type}",
            "evidence_level": level,
            "effective_at": "2026-08-01T00:00:00+00:00",
            "effective_until": "2026-08-05T00:00:00+00:00",
            "amount": "10.00",
            "currency": currency,
            "variant_ref": "variant-1",
            "quantity": "10",
            "quantity_basis": "exact",
            "formula_inputs": {name: "1" for name in requirement.required_formula_inputs},
        }
    )
    if level == "actual":
        record["authority_contract_id"] = ScopedProfitLedgerAuthority.CONTRACT_ID
        record["authority_status"] = "reconciled"
    return record


def fx_basis(*, rate: str = "0.08", effective_at: str = "2026-08-01T00:00:00+00:00") -> dict:
    return scoped(
        {
            "fx_basis_id": "fx-rub-cny",
            "evidence_id": "ev-fx-rub-cny",
            "evidence_level": "reviewed",
            "source_currency": "RUB",
            "quote_currency": "CNY",
            "rate": rate,
            "effective_at": effective_at,
            "effective_until": "2026-08-05T00:00:00+00:00",
            "purposes": ["scenario_profit"],
        }
    )


def book_record(book: str, *, authority: str | None = None) -> dict:
    return scoped(
        {
            "book": book,
            "evidence_id": f"ev-book-{book}",
            "authority_contract_id": authority
            or (
                "kjds-profit-ledger-v1"
                if book == "accrual"
                else ScopedProfitLedgerAuthority.CONTRACT_ID
            ),
            "authority_status": "reconciled",
            "effective_at": "2026-08-01T00:00:00+00:00",
            "effective_until": "2026-08-05T00:00:00+00:00",
        }
    )


def sku_input(
    *,
    costs: list[dict] | None = None,
    currencies: list[str] | None = None,
    fx: list[dict] | None = None,
    books: list[dict] | None = None,
    exact_variant: bool = True,
    exact_quantity: bool = True,
) -> dict:
    return scoped(
        {
            "sku": "SKU-1",
            "quote_currency": "CNY",
            "source_currencies": currencies or ["CNY"],
            "variant_identity": variant(exact=exact_variant),
            "quantity": quantity(exact=exact_quantity),
            "cost_evidence": costs or [],
            "fx_bases": fx or [],
            "book_evidence": books or [],
        }
    )


def project(item: dict) -> dict:
    return ProfitCostEvidenceWorkspace().project(
        scope=SCOPE,
        sku_inputs=[item],
        as_of=AS_OF,
    )


def test_registry_is_exactly_the_existing_fifteen_actual_profit_legs() -> None:
    assert [item.cost_type for item in COST_REQUIREMENTS] == [item.value for item in COST_ORDER]
    assert {item.cost_type for item in COST_REQUIREMENTS} == {
        item.value for item in ACTUAL_PROFIT_COST_TYPES
    }
    assert len(COST_REQUIREMENTS) == 15
    assert [item.profit_stage for item in COST_REQUIREMENTS].count("cm1") == 1


def test_missing_evidence_generates_complete_queue_without_guessing_costs() -> None:
    result = project(sku_input())
    sku = result["skus"][0]

    assert sku["cost_coverage"]["required"] == 15
    assert sku["cost_coverage"]["missing"] == 15
    assert len(sku["cost_coverage"]["legs"]) == 15
    assert {item["status"] for item in sku["cost_coverage"]["legs"]} == {"missing"}
    assert sku["cost_coverage"]["scenario_coverage_ratio"] == "0"
    assert sku["pilot_gate"]["status"] == "blocked"
    assert sku["pilot_gate"]["decision_class"] == "needs_data"
    assert sku["pilot_gate"]["pilot_proposal_allowed"] is False
    assert result["control_envelope"]["missing_costs_imputed"] is False
    cost_requests = [
        item for item in result["evidence_request_queue"] if item["request_type"] == "cost_leg"
    ]
    assert len(cost_requests) == 15
    assert all(item["required_document"] for item in cost_requests)
    assert all(item["required_formula_inputs"] for item in cost_requests)
    assert all(item["missing_value_guessed"] is False for item in cost_requests)


def test_each_coverage_level_is_fail_closed_and_actual_uses_existing_authority() -> None:
    observed = cost_record("domestic_logistics", "observed")
    reviewed = cost_record("international_logistics", "reviewed")
    actual = cost_record("product_cost", "actual")
    false_actual = cost_record("packaging", "actual")
    false_actual.pop("authority_contract_id")
    false_actual.pop("authority_status")

    result = project(sku_input(costs=[observed, reviewed, actual, false_actual]))
    legs = {item["cost_type"]: item for item in result["skus"][0]["cost_coverage"]["legs"]}

    assert legs["product_cost"]["status"] == "actual"
    assert legs["product_cost"]["selected_record"]["actual_authority_verified"] is True
    assert legs["domestic_logistics"]["status"] == "observed"
    assert legs["international_logistics"]["status"] == "reviewed"
    assert legs["packaging"]["status"] == "reviewed"
    assert "actual_cost_authority_missing:packaging" in legs["packaging"]["selected_record"][
        "quality_issues"
    ]
    assert legs["warehousing"]["status"] == "missing"


def test_stale_currency_quantity_and_variant_conditions_prevent_reviewed_coverage() -> None:
    record = cost_record("product_cost", "reviewed", currency="RUB")
    record["effective_until"] = "2026-08-02T07:59:59+00:00"
    record["quantity"] = "9"
    record["quantity_basis"] = "estimated"
    record["variant_ref"] = "other-variant"

    result = project(sku_input(costs=[record], currencies=["CNY", "RUB"]))
    leg = result["skus"][0]["cost_coverage"]["legs"][0]

    assert leg["status"] == "observed"
    assert any(code.endswith(":stale") for code in leg["blocker_codes"])
    assert "cost_quantity_basis_not_exact:product_cost" in leg["blocker_codes"]
    assert "cost_variant_binding_conflict:product_cost" in leg["blocker_codes"]
    assert "cost_fx_basis_missing:product_cost:RUB/CNY" in leg["blocker_codes"]
    assert result["skus"][0]["fx_readiness"]["status"] == "blocked"


def test_exact_quantity_basis_must_bind_to_the_sku_quantity() -> None:
    record = cost_record("product_cost", "reviewed")
    record["quantity"] = "9"

    result = project(sku_input(costs=[record]))
    leg = result["skus"][0]["cost_coverage"]["legs"][0]

    assert leg["status"] == "observed"
    assert "cost_quantity_binding_conflict:product_cost" in leg["blocker_codes"]


def test_unresolved_sku_quantity_degrades_cost_evidence_without_throwing() -> None:
    result = project(
        sku_input(costs=[cost_record("product_cost", "reviewed")], exact_quantity=False)
    )
    sku = result["skus"][0]
    leg = sku["cost_coverage"]["legs"][0]

    assert leg["status"] == "observed"
    assert "exact_quantity_missing:product_cost" in leg["blocker_codes"]
    assert sku["pilot_gate"]["status"] == "blocked"


def test_reviewed_fifteen_costs_and_explicit_fx_only_open_downside_validation_gate() -> None:
    costs = [cost_record(item.cost_type, "reviewed") for item in COST_REQUIREMENTS]
    result = project(
        sku_input(costs=costs, currencies=["RUB", "CNY"], fx=[fx_basis()])
    )
    sku = result["skus"][0]

    assert sku["cost_coverage"]["reviewed"] == 15
    assert sku["cost_coverage"]["scenario_coverage_ratio"] == "1"
    assert sku["fx_readiness"]["status"] == "ready"
    assert sku["profit_book_readiness"]["scenario"]["status"] == "ready"
    assert sku["pilot_gate"] == {
        "status": "ready_for_profit_validation",
        "decision_class": "hold",
        "cost_evidence_gate_passed": True,
        "pilot_proposal_allowed": False,
        "automatic_execution_allowed": False,
        "blocker_codes": [],
        "next_gate": "deterministic_downside_cm3_validation",
        "reason": "positive_downside_cm3_is_not_calculated_by_this_readiness_module",
    }
    assert all(
        sku["profit_book_readiness"][book]["status"] == "no_data"
        for book in ("accrual", "settlement", "cash")
    )


def test_scenario_accrual_settlement_and_cash_books_never_promote_each_other() -> None:
    costs = [cost_record(item.cost_type, "reviewed") for item in COST_REQUIREMENTS]
    result = project(
        sku_input(
            costs=costs,
            books=[book_record("settlement")],
        )
    )
    books = result["skus"][0]["profit_book_readiness"]

    assert books["scenario"]["status"] == "ready"
    assert books["accrual"]["status"] == "no_data"
    assert books["settlement"]["status"] == "available"
    assert books["cash"]["status"] == "no_data"
    assert books["strictly_separated"] is True
    assert all(books[book]["calculation_performed"] is False for book in ("scenario", "accrual", "settlement", "cash"))


def test_fx_conflicts_at_same_effective_time_fail_closed() -> None:
    first = fx_basis(rate="0.08")
    second = fx_basis(rate="0.09")
    second["fx_basis_id"] = "fx-rub-cny-2"
    second["evidence_id"] = "ev-fx-rub-cny-2"

    result = project(sku_input(currencies=["RUB", "CNY"], fx=[first, second]))
    fx = result["skus"][0]["fx_readiness"]

    assert fx["status"] == "blocked"
    assert fx["required_pairs"][0]["blocker_codes"] == ["fx_basis_conflict:RUB/CNY"]
    assert fx["inverse_or_implicit_rates_used"] is False


def test_fx_reporting_purpose_cannot_open_scenario_profit_gate() -> None:
    reporting_only = fx_basis()
    reporting_only["purposes"] = ["reporting"]

    result = project(
        sku_input(currencies=["RUB", "CNY"], fx=[reporting_only])
    )
    fx = result["skus"][0]["fx_readiness"]

    assert fx["status"] == "blocked"
    assert (
        "fx_purpose_not_authorized:RUB/CNY:scenario_profit"
        in fx["required_pairs"][0]["blocker_codes"]
    )


def test_reordering_and_exact_duplicates_preserve_content_identity() -> None:
    costs = [cost_record(item.cost_type, "reviewed") for item in COST_REQUIREMENTS]
    item = sku_input(costs=costs, currencies=["RUB", "CNY"], fx=[fx_basis()])
    first = ProfitCostEvidenceWorkspace().project(scope=SCOPE, sku_inputs=[item], as_of=AS_OF)
    reordered = deepcopy(item)
    reordered["cost_evidence"] = list(reversed(reordered["cost_evidence"]))
    reordered["source_currencies"] = list(reversed(reordered["source_currencies"]))
    second = ProfitCostEvidenceWorkspace().project(
        scope=SCOPE,
        sku_inputs=[reordered, deepcopy(reordered)],
        as_of=AS_OF,
    )

    assert second["input_sha256"] == first["input_sha256"]
    assert second["workspace_id"] == first["workspace_id"]
    assert second["skus"][0]["snapshot_sha256"] == first["skus"][0]["snapshot_sha256"]
    assert second["summary"]["duplicate_sku_inputs"] == 1
    assert [item["request_id"] for item in second["evidence_request_queue"]] == [
        item["request_id"] for item in first["evidence_request_queue"]
    ]


def test_conflicting_immutable_sku_or_evidence_identity_is_rejected() -> None:
    item = sku_input(costs=[cost_record("product_cost")])
    drifted_item = deepcopy(item)
    drifted_item["quote_currency"] = "RUB"
    with pytest.raises(ProfitCostEvidenceConflict, match="conflicting immutable content"):
        ProfitCostEvidenceWorkspace().project(
            scope=SCOPE,
            sku_inputs=[item, drifted_item],
            as_of=AS_OF,
        )

    drifted_evidence = deepcopy(item["cost_evidence"][0])
    drifted_evidence["amount"] = "99"
    item["cost_evidence"].append(drifted_evidence)
    with pytest.raises(ProfitCostEvidenceConflict, match="cost evidence identity"):
        project(item)


@pytest.mark.parametrize("location", ["sku", "variant", "quantity", "cost", "fx", "book"])
def test_every_nested_authority_is_rejected_when_it_crosses_scope(location: str) -> None:
    item = sku_input(
        costs=[cost_record("product_cost")],
        currencies=["RUB", "CNY"],
        fx=[fx_basis()],
        books=[book_record("cash")],
    )
    targets = {
        "sku": item,
        "variant": item["variant_identity"],
        "quantity": item["quantity"],
        "cost": item["cost_evidence"][0],
        "fx": item["fx_bases"][0],
        "book": item["book_evidence"][0],
    }
    targets[location]["scope"] = {**SCOPE, "tenant_ref": "tenant-b"}

    with pytest.raises(PermissionError, match="outside the authorized profit evidence scope"):
        project(item)


def test_unknown_cost_evidence_is_retained_but_never_enters_fifteen_leg_coverage() -> None:
    unknown = scoped(
        {
            "cost_type": "unclaimed",
            "evidence_id": "ev-unclaimed",
            "evidence_level": "actual",
        }
    )
    result = project(sku_input(costs=[unknown]))
    sku = result["skus"][0]

    assert sku["cost_coverage"]["missing"] == 15
    assert sku["unclassified_evidence"] == [
        {
            "evidence_id": "ev-unclaimed",
            "declared_cost_type": "unclaimed",
            "reason_code": "cost_type_outside_actual_profit_registry",
            "record_sha256": sku["unclassified_evidence"][0]["record_sha256"],
        }
    ]
    assert sku["pilot_gate"]["status"] == "blocked"
