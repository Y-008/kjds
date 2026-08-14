from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.control_plane.evidence import EvidenceService
from apps.control_plane.finance import FinanceService
from apps.control_plane.market_recon_bundle import MarketReconBundleIngestion
from apps.control_plane.profit_truth_readiness import (
    ProfitTruthReadinessWorkspace,
)
from scripts.extract_ru002_logistics_evidence import EvidenceHit, structured_records
from scripts.package_market_recon_bundle import SOURCE_ROOT, package_bundle
from tests.test_finance import capture_evidence, make_services
from tests.test_profit_command import (
    AS_OF,
    database,
    entity_scope,
    principal,
    workspace_with_bundle,
)

pytestmark = pytest.mark.skipif(
    not all(
        (SOURCE_ROOT / name).is_file()
        for name in (
            "full_catalog.json",
            "full_product_info.json",
            "analytics_by_window.json",
            "finance_by_month.json",
            "supply_1688/supply_crawl.json",
        )
    ),
    reason="market-recon business fixtures are not committed",
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


def test_unbound_logistics_projection_cannot_improve_profit_gate_or_cross_scope(
    tmp_path: Path,
) -> None:
    _, baseline_engine = workspace_with_bundle()
    baseline = ProfitTruthReadinessWorkspace(engine=baseline_engine).project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    record = structured_records(
        [
            EvidenceHit(
                source_relpath="wuliu/provider.xlsx",
                sha256="c" * 64,
                kind="xlsx",
                location="Rates!A12:F12",
                excerpt="OZON 运费 50元/kg",
                currency="CNY",
            )
        ]
    )[0]
    quarantined_record = dict(record)
    quarantined_record["fee_amount"] = "50"
    unhashed_quarantine = dict(quarantined_record)
    unhashed_quarantine.pop("observation_sha256")
    quarantined_record["observation_sha256"] = hashlib.sha256(
        json.dumps(
            unhashed_quarantine,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    observations_path = tmp_path / "logistics-observations.json"
    observations_path.write_text(
        json.dumps([record, quarantined_record], ensure_ascii=False),
        encoding="utf-8",
    )
    bundle = package_bundle(
        tmp_path / "market-recon-with-logistics.zip",
        logistics_observations_path=observations_path,
    ).read_bytes()
    engine = database()
    evidence = EvidenceService(engine)
    MarketReconBundleIngestion(engine=engine, evidence=evidence).ingest(
        bundle,
        filename="market-recon-with-logistics.zip",
        idempotency_key="profit-truth-with-unbound-logistics",
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    result = ProfitTruthReadinessWorkspace(engine=engine).project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["status"] == "blocked"
    assert result["data_chain"]["source_total"] == (
        baseline["data_chain"]["source_total"] + 2
    )
    assert result["unbound_cost_evidence"]["status"] == "needs_binding"
    assert result["unbound_cost_evidence"]["summary"] == {
        "source_total": 2,
        "accepted": 1,
        "quarantined": 1,
        "cost_leg_counts": {"international_logistics": 1},
    }
    projected = next(
        item
        for item in result["unbound_cost_evidence"]["records"]
        if item["disposition"] == "accepted"
    )
    assert projected["observation_id"] == record["observation_id"]
    assert projected["sku_binding"] is None
    assert projected["variant_binding"] is None
    assert projected["quantity_binding"] is None
    assert projected["shipment_profile_binding"] is None
    assert projected["effective_period"] is None
    assert projected["decision_eligible"] is False
    assert "excerpt" not in projected
    assert "amount" not in projected
    assert result["unbound_cost_evidence"]["control_envelope"] == {
        "source_excerpts_exposed": False,
        "sku_cost_coverage_incremented": False,
        "reviewed_cost_created": False,
        "actual_cost_created": False,
        "profit_calculation_performed": False,
        "external_write_allowed": False,
    }
    assert result["cost_evidence"]["summary"] == baseline[
        "cost_evidence"
    ]["summary"]
    result_skus = {
        item["sku"]: item for item in result["cost_evidence"]["skus"]
    }
    baseline_skus = {
        item["sku"]: item for item in baseline["cost_evidence"]["skus"]
    }
    assert result_skus.keys() == baseline_skus.keys()
    for sku, result_sku in result_skus.items():
        baseline_sku = baseline_skus[sku]
        assert result_sku["cost_coverage"] == baseline_sku[
            "cost_coverage"
        ]
        assert result_sku["profit_book_readiness"] == baseline_sku[
            "profit_book_readiness"
        ]
        assert result_sku["pilot_gate"] == baseline_sku["pilot_gate"]
    assert result["summary"]["formal_fact_count"] == 0
    assert result["summary"]["finance_entry_count"] == 0
    assert result["summary"]["decision_snapshot_count"] == 0
    assert result["control_envelope"][
        "unbound_cost_evidence_counted_as_sku_cost"
    ] is False
    blocker = next(
        item
        for item in result["blockers"]
        if item["code"]
        == "logistics_cost_evidence_sku_binding_missing"
    )
    assert blocker["affected_count"] == 1
    quarantine_blocker = next(
        item
        for item in result["blockers"]
        if item["code"] == "logistics_cost_evidence_quarantined"
    )
    assert quarantine_blocker["affected_count"] == 1
    assert result["summary"]["blocker_count"] == (
        baseline["summary"]["blocker_count"] + 2
    )

    other_scope = ProfitTruthReadinessWorkspace(engine=engine).project(
        principal=principal(tenant_ref="tenant-b"),
        entity_scope=entity_scope(entity_ref="entity-b", authority="b"),
        store_ref="store-a",
        as_of=AS_OF,
    )
    assert other_scope["summary"][
        "unbound_logistics_observation_count"
    ] == 0
    assert other_scope["unbound_cost_evidence"]["records"] == []


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
