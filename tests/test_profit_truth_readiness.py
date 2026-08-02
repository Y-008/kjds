from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.control_plane.finance import FinanceService
from apps.control_plane.profit_truth_readiness import (
    ProfitTruthReadinessWorkspace,
)
from tests.test_finance import capture_evidence, make_services
from tests.test_profit_command import (
    AS_OF,
    entity_scope,
    principal,
    workspace_with_bundle,
)


def test_real_bundle_truth_gate_connects_all_retained_sources_without_guessing() -> None:
    _, engine = workspace_with_bundle()
    result = ProfitTruthReadinessWorkspace(engine=engine).project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["status"] == "blocked"
    assert result["data_chain"]["source_total"] >= 374
    assert result["data_chain"]["retained_total"] == result["data_chain"][
        "source_total"
    ]
    assert result["data_chain"]["source_total"] == sum(
        result["data_chain"]["stage_counts"][stage]
        for stage in ("raw_evidence", "normalized_observation")
    )
    assert result["data_chain"]["conservation_passed"] is True
    assert result["summary"]["sku_count"] == 18
    assert result["summary"]["identity_source_count"] == 99
    assert result["variant_identity"]["summary"]["accepted"] == 93
    assert result["variant_identity"]["summary"]["unresolved"] == 6
    assert result["variant_identity"]["reconciliation"][
        "conservation_passed"
    ] is True
    assert result["summary"]["finance_operation_count"] == 114
    assert result["summary"]["finance_entry_proposal_count"] == 0
    assert result["fx_readiness"]["required_pair"] == "RUB/CNY"
    assert result["fx_readiness"]["status"] == "blocked"
    assert result["finance_allocation"]["reconciliation"][
        "count_conservation_passed"
    ] is True
    assert result["cost_evidence"]["summary"]["sku_count"] == 18
    assert result["cost_evidence"]["summary"][
        "required_cost_legs_per_sku"
    ] == 15
    assert result["cost_evidence"]["summary"]["pilot_blocked_skus"] == 18
    assert result["summary"]["formal_fact_count"] == 0
    assert result["summary"]["finance_entry_count"] == 0
    assert result["summary"]["decision_snapshot_count"] == 0
    assert result["control_envelope"]["currency_inferred"] is False
    assert result["control_envelope"]["missing_values_guessed"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_truth_gate_does_not_read_another_tenant_bundle() -> None:
    _, engine = workspace_with_bundle()
    result = ProfitTruthReadinessWorkspace(engine=engine).project(
        principal=principal(tenant_ref="tenant-b"),
        entity_scope=entity_scope(entity_ref="entity-b", authority="b"),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["data_chain"]["source_total"] == 0
    assert result["summary"]["sku_count"] == 0
    assert result["summary"]["finance_operation_count"] == 0
    assert result["control_envelope"]["external_write_allowed"] is False


def test_complete_scoped_fx_metadata_is_immutable_and_expiry_is_enforced() -> None:
    evidence, _, _, finance = make_services()
    source = capture_evidence(evidence, b"reviewed central bank FX evidence")
    cutoff = datetime.now(UTC) + timedelta(hours=1)
    scope = {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "scope_grant_authority_sha256": "a" * 64,
        "scope_as_of": cutoff.isoformat(),
    }
    kwargs = {
        "base_currency": "RUB",
        "quote_currency": "CNY",
        "rate": Decimal("0.087"),
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-08-03T00:00:00+00:00",
        "source": "central_bank_reference:Bank of Russia",
        "source_type": "central_bank_reference",
        "authority": "Bank of Russia",
        "purposes": ["scenario_profit", "reconciliation"],
        "intake_content_sha256": "c" * 64,
        "idempotency_key": "fx-rub-cny-20260801",
        "evidence_id": source.id,
        "created_by": "reviewer-a",
        "scope_authority": scope,
    }

    first = finance.add_fx_rate(**kwargs)
    replay = finance.add_fx_rate(**kwargs)

    assert replay.id == first.id
    assert first.expires_at == "2026-08-03T00:00:00+00:00"
    assert first.purposes == ("reconciliation", "scenario_profit")
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        finance.add_fx_rate(**{**kwargs, "rate": Decimal("0.088")})


def test_fx_readiness_requires_the_active_direct_pair_for_the_bundle() -> None:
    command, engine = workspace_with_bundle()
    finance = FinanceService(engine)
    source = capture_evidence(command.evidence, b"pair-specific FX evidence")
    now = datetime.now(UTC)
    projection_as_of = now + timedelta(hours=1)
    common = {
        "rate": Decimal("0.087"),
        "effective_at": (now - timedelta(days=1)).isoformat(),
        "source": "reviewed FX reference",
        "source_type": "central_bank_reference",
        "authority": "reviewer-a",
        "purposes": ["scenario_profit"],
        "intake_content_sha256": source.sha256,
        "evidence_id": source.id,
        "created_by": "reviewer-a",
        "scope_authority": {
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
            "scope_grant_authority_sha256": "a" * 64,
            "scope_as_of": projection_as_of.isoformat(),
        },
    }
    finance.add_fx_rate(
        **common,
        base_currency="USD",
        quote_currency="CNY",
        expires_at=(now + timedelta(days=1)).isoformat(),
        idempotency_key="wrong-pair",
    )
    finance.add_fx_rate(
        **common,
        base_currency="RUB",
        quote_currency="CNY",
        expires_at=(now - timedelta(minutes=30)).isoformat(),
        idempotency_key="expired-required-pair",
    )

    result = ProfitTruthReadinessWorkspace(engine=engine).project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=projection_as_of,
    )

    assert result["fx_readiness"]["status"] == "blocked"
    assert result["fx_readiness"]["required_pair"] == "RUB/CNY"
    assert result["fx_readiness"]["required_pairs"] == [
        {
            "source_currency": "RUB",
            "quote_currency": "CNY",
            "status": "blocked",
        }
    ]
    assert result["summary"]["complete_scoped_fx_count"] == 0
    blocker = next(
        item
        for item in result["blockers"]
        if item["code"] == "complete_scoped_fx_missing"
    )
    assert blocker["affected_count"] == 1

    finance.add_fx_rate(
        **common,
        base_currency="RUB",
        quote_currency="CNY",
        expires_at=(now + timedelta(days=1)).isoformat(),
        idempotency_key="active-required-pair",
    )
    ready = ProfitTruthReadinessWorkspace(engine=engine).project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=projection_as_of,
    )
    assert ready["fx_readiness"]["status"] == "ready"
    assert ready["summary"]["complete_scoped_fx_count"] == 1
    assert not any(
        item["code"] == "complete_scoped_fx_missing"
        for item in ready["blockers"]
    )


def test_profit_books_only_use_profit_facts_and_bank_receipts() -> None:
    books = ProfitTruthReadinessWorkspace._profit_books(
        fact_counts=Counter(
            {
                "ozon_inventory": 9,
                "ozon_order": 1,
                "ozon_accrual": 1,
                "ozon_settlement": 1,
            }
        ),
        entry_counts=Counter(
            {
                "platform_settlement": 1,
                "bank_payment": 7,
                "bank_receipt": 1,
            }
        ),
        decision_snapshot_count=0,
        display_currency="CNY",
    )

    assert books["accrual_profit"]["record_count"] == 2
    assert books["settlement_profit"]["record_count"] == 2
    assert books["cash_profit"]["record_count"] == 1

    without_receipt = ProfitTruthReadinessWorkspace._profit_books(
        fact_counts=Counter({"ozon_inventory": 9}),
        entry_counts=Counter({"bank_payment": 7}),
        decision_snapshot_count=0,
        display_currency="CNY",
    )
    assert without_receipt["accrual_profit"]["status"] == "no_data"
    assert without_receipt["cash_profit"]["status"] == "no_data"
