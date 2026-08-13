from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.batch_opportunity import (
    BATCH_POLICY_ID,
    COMPONENT_ORDER,
    BatchOpportunityCandidateRow,
    BatchOpportunityRunRow,
    BatchOpportunityWorkspace,
)
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.marketplace_observation import (
    MarketplaceObservationWorkspace,
    exact_identity_complete,
)
from apps.control_plane.ozon_global_rules import OzonGlobalRuleRegistry
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.sale_triggered_procurement import (
    SaleTriggeredProcurementPolicy,
)
from apps.control_plane.seller_operating_system import SellerOperatingSystem
from apps.control_plane.sql_repository import Base

IDENTITY = {
    "category": "electric_hoist",
    "model_or_variant": "PA500-7.6M-3CTRL",
    "rated_load_kg": "500",
    "voltage_v": "220",
}


class FakeFinance:
    @staticmethod
    def list_fx_rates(*, base_currency: str):
        assert base_currency != "CNY"
        return []


class FakeRepository:
    @staticmethod
    def latest_passports(_product_id: str):
        return {}

    @staticmethod
    def content_assets_for_product(_product_id: str):
        return []


class FakeTasks:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ensure_internal_task(self, **values):
        self.calls.append(values)
        return {
            "id": "tsk-batch",
            "owner": values["owner"],
            "status": "open",
        }


class FakeFacts:
    def __init__(self, rows=None) -> None:
        self.rows = list(rows or [])

    def list(self, *, fact_type: str | None = None, limit: int = 100):
        rows = [
            row
            for row in self.rows
            if fact_type is None or row.fact_type == fact_type
        ]
        return rows[:limit]


def engine():
    database = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        database,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(database)
    return database


def cost_evidence(evidence: EvidenceService) -> dict[str, str]:
    keys = (
        "domestic_freight",
        "packaging",
        "international_logistics",
        "customs",
        "marketplace_commission",
        "fulfillment_last_mile",
        "warehousing",
        "advertising",
        "returns_refunds",
        "discounts_promotions",
        "taxes",
        "fx_reserve",
        "loss_damage",
    )
    result = {}
    for key in keys:
        record = evidence.capture(
            content=f"{key}-source".encode(),
            filename=f"{key}.txt",
            content_type="text/plain",
            source="test-cost-source",
            source_ref=f"test-cost-source:{key}",
            grade=EvidenceGrade.B,
            effective_at="2026-07-27T00:00:00+00:00",
            effective_until=None,
            created_by="reviewer-1",
            metadata={"retention_class": "operational"},
        )
        result[f"{key}_evidence_id"] = record.id
    return result


def capture_pair(
    observations: MarketplaceObservationWorkspace,
    evidence: EvidenceService,
    *,
    sale_price: str = "3000",
    purchase_price: str = "100",
    supplier_identity: dict[str, str] | None = None,
    sale_currency: str = "CNY",
    market_signal_overrides: dict | None = None,
    supply_signal_overrides: dict | None = None,
    supplier_price_kind: str = "observed_checkout_price",
    checkout_verified: bool = True,
    purchase_available: bool = True,
) -> None:
    evidence_ids = cost_evidence(evidence)
    market_signals = {
        "competitor_count": 12,
        "review_count": 180,
        "rating": "4.7",
        "stock": 8,
        "sales_proxy_type": "review_velocity_proxy",
        "sales_proxy_value": 20,
        "promotion": "none_observed",
        "seasonality_status": "in_season",
        "stockout_opportunity": False,
        "customs_rate": "0.03",
        "marketplace_commission_rate": "0.18",
        "fee_category": "electric_hoist",
        "fee_mode": "realFBS",
        "fee_price_band": "2000-5000",
        "fee_effective_from": "2025-12-01",
        "fee_order_date": "2026-07-27",
        "fulfillment_last_mile_rate": "0.08",
        "warehousing_rate": "0.02",
        "advertising_rate": "0.05",
        "returns_refunds_rate": "0.05",
        "discounts_promotions_rate": "0.02",
        "taxes_rate": "0.06",
        "fx_reserve_rate": "0.02",
        "loss_damage_rate": "0.01",
        **{
            key: value
            for key, value in evidence_ids.items()
            if key
            not in {
                "domestic_freight_evidence_id",
                "packaging_evidence_id",
                "international_logistics_evidence_id",
            }
        },
    }
    market_signals.update(market_signal_overrides or {})
    supply_signals = {
        "province": "河北省",
        "city": "保定市",
        "industry_belt": "清苑起重产业带",
        "longitude": "115.464",
        "latitude": "38.875",
        "lead_time_days": 5,
        "distance_to_consolidation_km": 180,
        "package_gross_weight_kg": "12",
        "domestic_freight_cny": "8",
        "domestic_freight_scope": "per_unit",
        "packaging_cny": "6",
        "international_logistics_cny": "90",
        **{
            key: value
            for key, value in evidence_ids.items()
            if key
            in {
                "domestic_freight_evidence_id",
                "packaging_evidence_id",
                "international_logistics_evidence_id",
            }
        },
    }
    supply_signals.update(supply_signal_overrides or {})
    observations.capture(
        {
            "source_profile": "manual_verified_public_page",
            "marketplace": "ozon",
            "store_ref": "ozon-primary",
            "source_url": "https://www.ozon.ru/product/market-1/",
            "observed_at": "2026-07-27T01:00:00+00:00",
            "idempotency_key": f"ozon-{sale_price}-{sale_currency}",
            "confirmed": True,
            "items": [
                {
                    "external_item_id": "ozon-market-1",
                    "supplier_ref": "ozon-market",
                    "title": "Электрическая таль 500 кг 7,6 м",
                    "variant_key": "PA500-7.6M-3CTRL",
                    "currency": sale_currency,
                    "displayed_price": sale_price,
                    "price_kind": "marketplace_listing_price",
                    "availability": "in_stock",
                    "specifications": IDENTITY,
                    "product_identity": IDENTITY,
                    "confidence": "0.90",
                    "market_signals": market_signals,
                    "media_rights_status": "unverified_external_reference",
                }
            ],
        },
        actor_id="operator-1",
    )
    observations.capture(
        {
            "source_profile": "browser_observation",
            "marketplace": "1688",
            "store_ref": "external",
            "source_url": "https://detail.1688.com/offer/market-1.html",
            "observed_at": "2026-07-27T01:05:00+00:00",
            "idempotency_key": f"supplier-{purchase_price}",
            "confirmed": True,
            "items": [
                {
                    "external_item_id": "supplier-market-1",
                    "supplier_ref": "河北标准供应商",
                    "title": "PA500电动葫芦",
                    "variant_key": "PA500-7.6M-3CTRL",
                    "currency": "CNY",
                    "displayed_price": purchase_price,
                    "price_scope": "unit_price",
                    "price_kind": supplier_price_kind,
                    "min_order_quantity": 1,
                    "observed_quantity": 3,
                    "checkout_verified": checkout_verified,
                    "tax_included": True,
                    "domestic_freight_included": False,
                    "purchase_available": purchase_available,
                    "availability": "checkout_available",
                    "specifications": supplier_identity or IDENTITY,
                    "product_identity": supplier_identity or IDENTITY,
                    "confidence": "0.85",
                    "supply_signals": supply_signals,
                    "media_rights_status": "unverified_external_reference",
                }
            ],
        },
        actor_id="operator-1",
    )


def workspace():
    database = engine()
    evidence = EvidenceService(database)
    observations = MarketplaceObservationWorkspace(
        engine=database, evidence=evidence
    )
    tasks = FakeTasks()
    rules = OzonGlobalRuleRegistry()
    return (
        BatchOpportunityWorkspace(
            engine=database,
            observations=observations,
            evidence=evidence,
            finance=FakeFinance(),
            repository=FakeRepository(),
            operating_tasks=tasks,
            facts=FakeFacts(),
            ozon_rules=rules,
            seller_os=SellerOperatingSystem(ozon_rules=rules),
        ),
        observations,
        evidence,
        tasks,
    )


def prepare(batch: BatchOpportunityWorkspace, *, key: str = "batch-1"):
    return batch.prepare(
        store_ref="ozon-primary",
        policy_id=BATCH_POLICY_ID,
        idempotency_key=key,
        candidate_limit=500,
        pilot_limit=20,
        max_age_hours=72,
        max_inventory_cash_cny=Decimal("5000"),
        cm3_floor_cny=Decimal("0"),
        actor_id="operator-1",
        as_of="2026-07-27T02:00:00+00:00",
    )


def test_observed_checkout_requires_exact_identity_and_checkout_boundary():
    database = engine()
    observations = MarketplaceObservationWorkspace(
        engine=database, evidence=EvidenceService(database)
    )
    request = {
        "source_profile": "browser_observation",
        "marketplace": "1688",
        "store_ref": "external",
        "source_url": "https://detail.1688.com/offer/1.html",
        "observed_at": "2026-07-27T01:00:00+00:00",
        "idempotency_key": "invalid-checkout",
        "confirmed": True,
        "items": [
            {
                "external_item_id": "1",
                "supplier_ref": "supplier",
                "title": "item",
                "variant_key": "variant",
                "currency": "CNY",
                "displayed_price": "10",
                "price_scope": "unit_price",
                "price_kind": "observed_checkout_price",
                "min_order_quantity": 10,
                "observed_quantity": 1,
                "availability": "unknown",
                "specifications": {},
            }
        ],
    }
    with pytest.raises(ValueError, match="exact identity"):
        observations.capture(request, actor_id="operator-1")


def test_candidate_key_includes_exact_variant_and_store_scope():
    database = engine()
    observations = MarketplaceObservationWorkspace(
        engine=database, evidence=EvidenceService(database)
    )

    def capture(variant: str, store_ref: str, key: str):
        return observations.capture(
            {
                "source_profile": "manual_verified_public_page",
                "marketplace": "ozon",
                "store_ref": store_ref,
                "source_url": f"https://www.ozon.ru/product/{key}/",
                "observed_at": "2026-07-27T00:00:00+00:00",
                "idempotency_key": key,
                "confirmed": True,
                "items": [
                    {
                        "external_item_id": "same-external",
                        "supplier_ref": "same-seller",
                        "title": variant,
                        "variant_key": variant,
                        "currency": "RUB",
                        "displayed_price": "1000",
                        "price_kind": "marketplace_listing_price",
                        "availability": "in_stock",
                        "specifications": IDENTITY,
                        "product_identity": IDENTITY,
                    }
                ],
            },
            actor_id="operator-1",
        )

    first = capture("variant-a", "store-a", "variant-a-store-a")
    second = capture("variant-b", "store-a", "variant-b-store-a")
    other_store = capture("variant-a", "store-b", "variant-a-store-b")

    assert (
        first["items"][0]["candidate_key"]
        != second["items"][0]["candidate_key"]
    )
    assert (
        first["items"][0]["fingerprint"]
        != other_store["items"][0]["fingerprint"]
    )
    page = observations.page(
        marketplace="ozon",
        store_refs={"store-a"},
        page_size=100,
    )
    assert {item["store_ref"] for item in page["items"]} == {"store-a"}
    assert len(page["items"]) == 2


def test_unresolved_identity_never_generates_or_reuses_exact_match_key():
    database = engine()
    observations = MarketplaceObservationWorkspace(
        engine=database, evidence=EvidenceService(database)
    )
    captured = observations.capture(
        {
            "source_profile": "browser_observation",
            "marketplace": "ozon",
            "store_ref": "external",
            "source_url": "https://www.ozon.ru/product/1776438646/",
            "observed_at": "2026-07-27T00:00:00+00:00",
            "idempotency_key": "unresolved-mounting",
            "confirmed": True,
            "items": [
                {
                    "external_item_id": "1776438646",
                    "supplier_ref": "ozon-market",
                    "title": "Cable tray 40 cm black",
                    "variant_key": (
                        "length=40cm;color=black;material=metal;"
                        "mounting=unknown"
                    ),
                    "currency": "RUB",
                    "displayed_price": "1760",
                    "price_kind": "marketplace_listing_price",
                    "availability": "visible_stock_2",
                    "specifications": {},
                    "product_identity": {
                        "product_type": "under_desk_cable_tray",
                        "length": "40cm",
                        "color": "black",
                        "material": "metal",
                        "mounting": "unknown",
                    },
                }
            ],
        },
        actor_id="operator-1",
    )

    assert captured["items"][0]["candidate_key"] is None
    assert captured["items"][0]["identity_resolution_status"] == "unresolved"

    batch, _, _, _ = workspace()
    legacy_key = "a" * 64
    with database.begin() as connection:
        connection.execute(
            text(
                "UPDATE marketplace_observation_items "
                "SET candidate_key = :legacy_key"
            ),
            {"legacy_key": legacy_key},
        )
    historical = observations.latest(marketplace="ozon", limit=10)[0]
    assert historical["candidate_key"] is None
    assert historical["identity_resolution_status"] == "unresolved"

    result = batch._scan(
        ozon=[
            {
                **captured["items"][0],
                "candidate_key": legacy_key,
            }
        ],
        suppliers=[
            {
                **captured["items"][0],
                "marketplace": "1688",
                "candidate_key": legacy_key,
                "price_kind": "public_display_price",
            }
        ],
        store_ref="ozon-primary",
        target_purchase_quantity=3,
        as_of=datetime.fromisoformat("2026-07-27T01:00:00+00:00"),
        max_age=timedelta(hours=72),
        shard_count=1,
        shard_index=0,
    )

    assert result["exact_identity_matched"] == 0
    assert result["matches"] == []


def test_under_desk_tray_requires_category_exact_dimensions():
    incomplete = {
        "product_type": "under_desk_cable_tray",
        "mounting": "dual_clamp",
        "material": "carbon_steel",
        "color": "black",
        "length": "400mm",
    }
    complete = {
        "product_type": "under_desk_cable_tray",
        "quantity": "1",
        "construction": "solid_steel_tray",
        "mounting": "dual_clamp",
        "length": "400mm",
        "width": "185mm",
        "height": "100mm",
        "color": "black",
    }

    assert exact_identity_complete(incomplete, "black-40cm-dual-clamp") is False
    assert exact_identity_complete(
        complete,
        "solid_steel|dual_clamp|400x185x100mm|black|1pc",
    ) is True


def test_checkout_total_derives_unit_price_and_db_rejects_conflict():
    database = engine()
    observations = MarketplaceObservationWorkspace(
        engine=database, evidence=EvidenceService(database)
    )
    result = observations.capture(
        {
            "source_profile": "browser_observation",
            "marketplace": "1688",
            "store_ref": "external",
            "source_url": "https://detail.1688.com/offer/total.html",
            "observed_at": "2026-07-27T01:00:00+00:00",
            "idempotency_key": "checkout-total",
            "confirmed": True,
            "items": [
                {
                    "external_item_id": "checkout-total",
                    "supplier_ref": "supplier",
                    "title": "exact variant",
                    "variant_key": "PA500-7.6M-3CTRL",
                    "currency": "CNY",
                    "displayed_price": "300",
                    "price_scope": "checkout_total",
                    "price_kind": "observed_checkout_price",
                    "min_order_quantity": 1,
                    "observed_quantity": 3,
                    "checkout_verified": True,
                    "tax_included": True,
                    "domestic_freight_included": True,
                    "purchase_available": True,
                    "product_identity": IDENTITY,
                    "specifications": IDENTITY,
                }
            ],
        },
        actor_id="operator-1",
    )
    item = result["items"][0]
    assert item["price_scope"] == "checkout_total"
    assert item["unit_price"] == "100.00"

    with pytest.raises(IntegrityError), database.begin() as connection:
        connection.execute(
            text(
                "UPDATE marketplace_observation_items "
                "SET unit_price_decimal = 1 "
                "WHERE id = :item_id"
            ),
            {"item_id": item["id"]},
        )


def test_supplier_unknown_freight_is_excluded_not_ranked_as_zero():
    option = {
        "candidate_key": "c" * 64,
        "variant_key": "PA500-7.6M-3CTRL",
        "currency": "CNY",
        "price_scope": "unit_price",
        "unit_price": "80",
        "displayed_price": "80",
        "observed_quantity": 3,
        "min_order_quantity": 1,
        "domestic_freight_included": False,
        "tax_included": True,
        "evidence_id": "evd",
        "external_item_id": "missing-freight",
        "supplier_ref": "missing-freight",
        "confidence": "0.95",
        "fingerprint": "3" * 64,
        "observed_at": "2026-07-27T01:00:00+00:00",
        "supply_signals": {},
    }
    _, selection = BatchOpportunityWorkspace._supplier_selection(
        [option],
        comparison_quantity=3,
        as_of=datetime.fromisoformat("2026-07-27T02:00:00+00:00"),
        max_age=timedelta(hours=72),
    )
    assert selection["status"] == "no_data"
    assert selection["selected"] is None
    assert selection["pareto_frontier"] == []
    assert "domestic_freight_amount_missing" in (
        selection["excluded"][0]["reasons"]
    )


def test_own_listing_price_is_not_replaced_by_external_competitor():
    batch, observations, evidence, _ = workspace()
    capture_pair(observations, evidence, sale_price="3000")
    observations.capture(
        {
            "source_profile": "manual_verified_public_page",
            "marketplace": "ozon",
            "store_ref": "external",
            "source_url": "https://www.ozon.ru/product/competitor/",
            "observed_at": "2026-07-27T01:10:00+00:00",
            "idempotency_key": "external-competitor",
            "confirmed": True,
            "items": [
                {
                    "external_item_id": "competitor",
                    "supplier_ref": "competitor-seller",
                    "title": "competitor title",
                    "variant_key": "PA500-7.6M-3CTRL",
                    "currency": "CNY",
                    "displayed_price": "999",
                    "price_scope": "unit_price",
                    "price_kind": "marketplace_listing_price",
                    "availability": "in_stock",
                    "specifications": IDENTITY,
                    "product_identity": IDENTITY,
                    "confidence": "0.9",
                }
            ],
        },
        actor_id="operator-1",
    )

    result = prepare(batch, key="own-versus-competitor")
    market = result["candidates"][0]["market"]
    assert market["revenue_scenario"]["kind"] == (
        "own_listing_current_fact"
    )
    assert market["revenue_scenario"]["unit_price"] == "3000.00"
    assert market["cohort"]["price_distribution"]["median"] == "999.00"
    assert result["counts"]["own_listings"] == 1
    assert result["counts"]["competitor_listings"] == 1


def test_batch_exact_match_scores_fifteen_components_without_promotion():
    batch, observations, evidence, tasks = workspace()
    capture_pair(observations, evidence)

    result = prepare(batch)

    assert result["counts"]["observed"] == 2
    assert result["counts"]["exact_identity_matched"] == 1
    assert result["counts"]["checkout_cost_eligible"] == 1
    assert result["counts"]["exact_matched"] == 1
    assert result["counts"]["downside_positive"] == 1
    assert result["counts"]["content_ready"] == 0
    assert result["counts"]["pilot_ready"] == 0
    row = result["candidates"][0]
    downside = row["economics"]["downside"]
    assert [item["name"] for item in downside["components"]] == list(
        COMPONENT_ORDER
    )
    assert downside["conservation_delta_cny"] == "0.00"
    assert Decimal(downside["cm3_cny"]) > 0
    assert row["economics"]["cost_evidence_complete"] is True
    risk_adjusted = row["economics"]["risk_adjusted"]
    assert risk_adjusted["contract_id"] == (
        "kjds-risk-adjusted-profit-simulation-v1"
    )
    assert risk_adjusted["deterministic"] is True
    assert risk_adjusted["scenarios"] == 2000
    assert Decimal(risk_adjusted["cvar_loss_cny"]) >= 0
    assert Decimal(risk_adjusted["decision_utility_cny"]) <= Decimal(
        risk_adjusted["expected_profit_cny"]
    )
    assert downside["components"][0]["authority"] == (
        "evidence_backed_observation"
    )
    assert row["economics"]["actual_profit"] is None
    assert row["economics"]["formal_cm3"] is None
    assert row["supply"]["counts_as_supplier_offer"] is False
    assert row["pilot_ready"] is False
    assert row["ozon_global_cn"]["state"] == "ready_with_constraints"
    assert (
        row["ozon_global_cn"]["actions"]["observe_research"]["status"]
        == "ready"
    )
    assert (
        row["ozon_global_cn"]["actions"]["external_publish"]["status"]
        == "blocked"
    )
    assert "ozon_global_cn_rule_gate_blocked" in row["blockers"]
    assert len(result["ozon_global_cn_rule_registry"]["registry_hash"]) == 64
    assert result["counts"]["official_rule_ready"] == 0
    assert row["seller_os"]["same_candidate_facts"] is True
    assert len(row["seller_os"]["rows"]) == 5
    assert row["seller_os"]["automatic_listing_count_is_success_metric"] is (
        False
    )
    assert "passport_incomplete" in row["blockers"]
    assert "media_rights_or_qa_incomplete" in row["blockers"]
    assert "independent_approval_missing" in row["blockers"]
    assert result["authority"]["permit_created"] is False
    assert result["authority"]["ozon_write_performed"] is False
    assert result["supply_map"][0]["longitude"] == "115.464000"
    assert result["supply_map"][0]["latitude"] == "38.875000"
    assert result["supply_map"][0]["position_status"] == "observed"
    assert result["market_summary"]["sales_status"] == "proxy"
    assert row["automation"]["current_state"] == "evaluate"
    assert row["automation"]["new_workflow_engine_created"] is False
    assert row["automation"]["external_side_effect"] is False
    assert row["sale_triggered_procurement"]["state"] == (
        "waiting_for_ozon_order"
    )
    assert row["sale_triggered_procurement"][
        "recommended_review_quantity"
    ] == 0
    assert row["sale_triggered_procurement"][
        "external_purchase_write"
    ] is False
    assert all(
        stage["owner"] and stage["sla_hours"] > 0 and stage["fingerprint"]
        for stage in row["automation"]["stages"]
    )
    assert tasks.calls[0]["owner"] == "commerce"
    assert evidence.verify(result["evidence_id"]).valid is True


def test_manual_small_evidence_class_relaxes_passport_gate_to_basic_roles():
    batch, observations, evidence, tasks = workspace()
    capture_pair(observations, evidence)

    automated = prepare(batch, key="evidence-class-automated")
    automated_row = automated["candidates"][0]
    assert automated_row["content"]["evidence_class"] == "auto_scale"
    assert automated_row["content"]["passport_required"] is True
    assert "passport_incomplete" in automated_row["blockers"]

    manual = batch.prepare(
        store_ref="ozon-primary",
        policy_id=BATCH_POLICY_ID,
        idempotency_key="evidence-class-manual",
        candidate_limit=500,
        pilot_limit=20,
        max_age_hours=72,
        max_inventory_cash_cny=Decimal("5000"),
        cm3_floor_cny=Decimal("0"),
        actor_id="operator-1",
        as_of="2026-07-27T02:00:00+00:00",
        evidence_class="manual_small",
    )
    row = manual["candidates"][0]
    content = row["content"]
    assert content["evidence_class"] == "manual_small"
    assert content["passport_required"] is False
    assert content["basic_evidence_ready"] is False
    assert set(content["basic_evidence_status"]) == {
        "supplier_identity",
        "purchase_link",
        "product_certificate",
        "sku_mapping",
        "image_source",
        "basic_qc_result",
    }
    assert content["basic_evidence_status"]["supplier_identity"] is True
    assert content["basic_evidence_status"]["purchase_link"] is True
    assert content["basic_evidence_status"]["sku_mapping"] is True
    assert content["basic_evidence_status"]["product_certificate"] is False
    assert content["basic_evidence_status"]["basic_qc_result"] is False
    assert content["basic_evidence_status"]["image_source"] is True
    assert set(content["basic_media_checks"]) == {
        "image_matches_target_sku",
        "image_params_match_specs",
        "no_external_watermark_or_contact",
        "no_brand_logo",
        "no_unsubstantiated_claims",
        "accessories_in_image_included",
    }
    assert content["basic_media_checks"]["no_brand_logo"] == "unknown"
    assert content["basic_media_failed"] == []
    econ = row["economics"]
    assert econ["key_cost_evidence_complete"] is True
    assert econ["missing_key_cost_components"] == []
    assert econ["estimated_component_names"] == ["purchase_buffer"]
    assert Decimal(econ["landed_cost_interval_cny"]["low"]) <= Decimal(
        econ["landed_cost_interval_cny"]["high"]
    )
    assert Decimal(econ["profit_interval_cny"]["low"]) <= Decimal(
        econ["profit_interval_cny"]["high"]
    )
    card = row["sku_identity_card"]
    assert card["contract_id"] == "kjds-sku-identity-card-v1"
    assert card["confirmed_mismatches"] == []
    assert "rated_load_kg" not in card["missing_core_specs"]
    assert "passport_incomplete" not in row["blockers"]
    assert "basic_evidence_incomplete" in row["blockers"]
    assert "media_rights_or_qa_incomplete" not in row["blockers"]


def test_scan_excludes_core_spec_mismatched_suppliers():
    batch, observations, evidence, tasks = workspace()
    base = {
        "source_profile": "manual_verified_public_page",
        "observed_at": "2026-07-27T01:00:00+00:00",
        "confirmed": True,
    }
    observations.capture(
        {
            **base,
            "marketplace": "ozon",
            "store_ref": "ozon-primary",
            "source_url": "https://www.ozon.ru/product/market-1/",
            "idempotency_key": "mismatch-ozon",
            "items": [
                {
                    "external_item_id": "ozon-m1",
                    "supplier_ref": "ozon-market",
                    "title": "Электрическая таль 500 кг",
                    "variant_key": "PA500",
                    "currency": "CNY",
                    "displayed_price": "3000",
                    "price_kind": "marketplace_listing_price",
                    "availability": "in_stock",
                    "product_identity": {"model_or_variant": "PA500"},
                    "specifications": {
                        "额定载重": "1000kg",
                        "电压": "220V",
                    },
                    "confidence": "0.9",
                }
            ],
        },
        actor_id="operator-1",
    )
    observations.capture(
        {
            **base,
            "marketplace": "1688",
            "store_ref": "external",
            "source_url": "https://detail.1688.com/offer/9.html",
            "idempotency_key": "mismatch-1688",
            "items": [
                {
                    "external_item_id": "1688-9",
                    "supplier_ref": "supplier-a",
                    "title": "电动吊机",
                    "variant_key": "PA500",
                    "currency": "CNY",
                    "displayed_price": "100",
                    "price_scope": "unit_price",
                    "price_kind": "observed_checkout_price",
                    "min_order_quantity": 2,
                    "observed_quantity": 2,
                    "checkout_verified": True,
                    "purchase_available": True,
                    "tax_included": False,
                    "domestic_freight_included": False,
                    "product_identity": {"model_or_variant": "PA500"},
                    "specifications": {
                        "额定载重": "500kg",
                        "电压": "220V",
                    },
                    "confidence": "0.9",
                }
            ],
        },
        actor_id="operator-1",
    )
    result = batch.prepare(
        store_ref="ozon-primary",
        policy_id=BATCH_POLICY_ID,
        idempotency_key="mismatch-scan",
        candidate_limit=500,
        pilot_limit=20,
        max_age_hours=72,
        max_inventory_cash_cny=Decimal("5000"),
        cm3_floor_cny=Decimal("0"),
        actor_id="operator-1",
        as_of="2026-07-27T02:00:00+00:00",
    )
    assert result["counts"]["spec_mismatch_excluded"] == 1
    assert result["counts"]["exact_identity_matched"] == 1
    assert result["candidates"] == []


def test_sale_triggered_procurement_requires_formal_scoped_order_fact():
    fact = SimpleNamespace(
        id="fact-order-1",
        fact_type="ozon_order",
        product_id="prd-1",
        resolution_status="resolved",
        effective_at="2026-07-27T01:00:00+00:00",
        recorded_at="2026-07-27T01:01:00+00:00",
        evidence_id="evd-order-1",
        payload={
            "external_id": "ozon-order-1",
            "store_ref": "another-store",
            "sku": "SKU-1",
            "status": "awaiting_packaging",
            "quantity": "1",
            "gross_revenue": "1000",
            "currency": "RUB",
        },
    )
    policy = SaleTriggeredProcurementPolicy(
        facts=FakeFacts([fact]),
        evidence=SimpleNamespace(
            verify=lambda _evidence_id: SimpleNamespace(valid=True)
        ),
        repository=SimpleNamespace(
            get_product=lambda _product_id: SimpleNamespace(sku="SKU-1")
        ),
    )

    result = policy.evaluate(
        store_ref="ozon-primary",
        product_id="prd-1",
        supply={"checkout_verified": True, "purchase_available": True},
        economics={
            "cost_evidence_complete": True,
            "downside": {"cm3_cny": "10.00"},
        },
        fresh=True,
        as_of=datetime.fromisoformat("2026-07-27T02:00:00+00:00"),
    )

    assert result["state"] == "blocked_order_authority"
    assert "order_store_scope_missing_or_mismatch" in result["blockers"]
    assert result["recommended_review_quantity"] == 0
    assert result["supplier_order_created"] is False
    assert result["payment_created"] is False


def test_sale_triggered_procurement_opens_review_not_supplier_order():
    fact = SimpleNamespace(
        id="fact-order-2",
        fact_type="ozon_order",
        product_id="prd-1",
        resolution_status="resolved",
        effective_at="2026-07-27T01:00:00+00:00",
        recorded_at="2026-07-27T01:01:00+00:00",
        evidence_id="evd-order-2",
        payload={
            "external_id": "ozon-order-2",
            "store_ref": "ozon-primary",
            "sku": "SKU-1",
            "status": "awaiting_packaging",
            "quantity": "2",
            "gross_revenue": "2000",
            "currency": "RUB",
        },
    )
    policy = SaleTriggeredProcurementPolicy(
        facts=FakeFacts([fact]),
        evidence=SimpleNamespace(
            verify=lambda _evidence_id: SimpleNamespace(valid=True)
        ),
        repository=SimpleNamespace(
            get_product=lambda _product_id: SimpleNamespace(sku="SKU-1")
        ),
    )

    result = policy.evaluate(
        store_ref="ozon-primary",
        product_id="prd-1",
        supply={"checkout_verified": True, "purchase_available": True},
        economics={
            "cost_evidence_complete": True,
            "downside": {"cm3_cny": "10.00"},
        },
        fresh=True,
        as_of=datetime.fromisoformat("2026-07-27T02:00:00+00:00"),
    )

    assert result["state"] == "eligible_for_procurement_review"
    assert result["recommended_review_quantity"] == 2
    assert result["trigger_fact_id"] == "fact-order-2"
    assert result["supplier_order_created"] is False
    assert result["payment_created"] is False
    assert result["external_purchase_write"] is False


def test_batch_does_not_fuzzy_match_different_variants():
    batch, observations, evidence, _ = workspace()
    capture_pair(
        observations,
        evidence,
        supplier_identity={
            **IDENTITY,
            "model_or_variant": "PA500-12M-WIRELESS",
        },
    )

    result = prepare(batch)

    assert result["counts"]["observed"] == 2
    assert result["counts"]["exact_identity_matched"] == 0
    assert result["counts"]["checkout_cost_eligible"] == 0
    assert result["counts"]["exact_matched"] == 0
    assert result["counts"]["pilot_ready"] == 0
    assert result["candidates"] == []
    assert "exact_cross_market_match_gap" in result["bottlenecks"]


def test_exact_identity_is_not_hidden_by_missing_checkout_cost_evidence():
    batch, observations, evidence, tasks = workspace()
    capture_pair(
        observations,
        evidence,
        supplier_price_kind="public_display_price",
        checkout_verified=False,
        purchase_available=True,
    )

    result = prepare(batch, key="identity-before-checkout")

    assert result["counts"]["exact_identity_matched"] == 1
    assert result["counts"]["exact_matched"] == 1
    assert result["counts"]["checkout_cost_eligible"] == 0
    assert result["counts"]["fully_costed_candidates"] == 0
    assert result["candidates"] == []
    assert "observed_checkout_cost_evidence_missing" in result["blockers"]
    assert "exact_cross_market_match_missing" not in result["blockers"]
    assert "observed_checkout_cost_evidence_gap" in result["bottlenecks"]
    assert "不下单" in tasks.calls[0]["snapshot"]["next_action"]


def test_market_cohort_aggregates_exact_identity_before_candidate_creation():
    candidate_key = "a" * 64
    options = [
        {
            "candidate_key": candidate_key,
            "product_identity": IDENTITY,
            "variant_key": "PA500-7.6M-3CTRL",
            "currency": "RUB",
            "displayed_price": price,
            "fingerprint": f"{index:064x}",
            "confidence": "0.8",
            "supplier_ref": f"seller-{index}",
            "source_url": f"https://www.ozon.ru/product/{index}/",
            "evidence_id": f"evd-{index}",
            "market_signals": {},
        }
        for index, price in enumerate(("90", "100", "120"), start=1)
    ]

    representative, cohort = BatchOpportunityWorkspace._market_cohort(
        options
    )

    assert representative["displayed_price"] == "100"
    assert cohort["listing_count"] == 3
    assert cohort["competitor_count"] == 3
    assert cohort["price_distribution"] == {
        "minimum": "90.00",
        "p25": "100.00",
        "median": "100.00",
        "p75": "120.00",
        "maximum": "120.00",
    }


def test_supplier_selection_uses_risk_adjusted_landed_pareto_not_lowest_price():
    now = "2026-07-27T01:00:00+00:00"
    base = {
        "candidate_key": "b" * 64,
        "variant_key": "PA500-7.6M-3CTRL",
        "currency": "CNY",
        "price_scope": "unit_price",
        "unit_price": "80",
        "observed_quantity": 3,
        "min_order_quantity": 1,
        "domestic_freight_included": False,
        "tax_included": True,
        "evidence_id": "evd-supplier",
    }
    options = [
        {
            **base,
            "external_item_id": "cheap-risky",
            "supplier_ref": "cheap-risky",
            "displayed_price": "80",
            "unit_price": "80",
            "confidence": "0.20",
            "fingerprint": "1" * 64,
            "observed_at": "2026-07-20T01:00:00+00:00",
            "supply_signals": {
                "lead_time_days": 30,
                "domestic_freight_cny": "20",
                "domestic_freight_scope": "per_unit",
                "supplier_reliability": "0.2",
            },
        },
        {
            **base,
            "external_item_id": "reliable",
            "supplier_ref": "reliable",
            "displayed_price": "90",
            "unit_price": "90",
            "confidence": "0.95",
            "fingerprint": "2" * 64,
            "observed_at": now,
            "supply_signals": {
                "lead_time_days": 1,
                "domestic_freight_cny": "0",
                "domestic_freight_scope": "per_unit",
                "supplier_reliability": "0.98",
                "return_terms_verified": True,
            },
        },
    ]

    selected, explanation = (
        BatchOpportunityWorkspace._supplier_selection(
            options,
            comparison_quantity=3,
            as_of=datetime.fromisoformat(now),
            max_age=timedelta(hours=72),
        )
    )

    assert selected["external_item_id"] == "reliable"
    assert explanation["lowest_displayed_price_is_automatically_best"] is (
        False
    )
    assert explanation["supplier_count"] == 2
    assert explanation["pareto_frontier"]
    assert explanation["alternatives"][0]["external_item_id"] == (
        "cheap-risky"
    )


def test_frozen_three_unit_pilot_does_not_use_hundred_unit_tier():
    def option(item_id: str, quantity: int, unit_price: str):
        return {
            "candidate_key": "d" * 64,
            "variant_key": "PA500-7.6M-3CTRL",
            "currency": "CNY",
            "price_scope": "unit_price",
            "unit_price": unit_price,
            "displayed_price": unit_price,
            "observed_quantity": quantity,
            "min_order_quantity": quantity,
            "domestic_freight_included": True,
            "tax_included": True,
            "evidence_id": f"evd-{item_id}",
            "external_item_id": item_id,
            "supplier_ref": item_id,
            "confidence": "0.9",
            "fingerprint": (item_id[0] * 64),
            "observed_at": "2026-07-27T01:00:00+00:00",
            "supply_signals": {
                "lead_time_days": 3,
                "supplier_reliability": "0.9",
                "return_terms_verified": True,
            },
        }

    options = [
        option("a-100", 100, "10"),
        option("b-100", 100, "11"),
        option("c-3", 3, "30"),
    ]
    selected, result = BatchOpportunityWorkspace._supplier_selection(
        options,
        comparison_quantity=3,
        as_of=datetime.fromisoformat("2026-07-27T02:00:00+00:00"),
        max_age=timedelta(hours=72),
    )

    assert selected["external_item_id"] == "c-3"
    assert result["comparison_quantity"] == 3
    assert {
        row["external_item_id"] for row in result["excluded"]
    } == {"a-100", "b-100"}
    assert all(
        "comparison_quantity_mismatch" in row["reasons"]
        for row in result["excluded"]
    )


def test_pilot_limit_and_batch_cash_create_selected_and_waitlist():
    candidates = [
        {
            "fingerprint": f"{index:064x}",
            "eligible_for_approval": True,
            "economics": {
                "downside": {"inventory_cash_cny": "100.00"}
            },
            "pilot_selection": {},
        }
        for index in range(3)
    ]

    result = BatchOpportunityWorkspace._select_pilots(
        candidates,
        pilot_limit=1,
        max_batch_inventory_cash_cny=Decimal("1000"),
    )

    assert result["eligible_for_approval"] == 3
    assert result["approval_allocation_selected"] == 1
    assert result["approval_waitlist"] == 2
    assert candidates[0]["pilot_selection"]["status"] == (
        "approval_allocation_selected"
    )
    assert candidates[1]["pilot_selection"]["status"] == (
        "approval_waitlist"
    )
    assert candidates[1]["pilot_selection"]["reason"] == (
        "pilot_limit_reached"
    )


def test_missing_versioned_fee_row_is_wide_screening_not_precise_cm3():
    batch, observations, evidence, _ = workspace()
    capture_pair(
        observations,
        evidence,
        market_signal_overrides={
            "fee_category": None,
            "fee_mode": None,
            "fee_price_band": None,
            "fee_effective_from": None,
            "fee_order_date": None,
        },
    )

    result = prepare(batch)
    downside = result["candidates"][0]["economics"]["downside"]

    assert downside["cm3_cny"] is None
    assert downside["screening_cm3_cny"] is not None
    assert downside["precision_status"] == "wide_policy_screening_only"
    assert "versioned_fee_row_evidence_missing" in (
        downside["precision_blockers"]
    )


def test_negative_downside_is_eliminated_and_never_creates_permit():
    batch, observations, evidence, _ = workspace()
    capture_pair(
        observations,
        evidence,
        sale_price="1000",
        purchase_price="500",
    )

    result = prepare(batch)
    row = result["candidates"][0]

    assert Decimal(row["economics"]["downside"]["cm3_cny"]) < 0
    assert row["state"] == "stop"
    assert row["strategy"]["classification"] == "eliminate"
    assert result["counts"]["downside_positive"] == 0
    assert result["authority"]["permit_created"] is False


def test_batch_run_is_idempotent_and_sales_remains_proxy():
    batch, observations, evidence, _ = workspace()
    capture_pair(observations, evidence)

    first = prepare(batch)
    replay = prepare(batch)

    assert replay["run_id"] == first["run_id"]
    assert replay["snapshot_sha256"] == first["snapshot_sha256"]
    row = replay["candidates"][0]
    assert row["market"]["sales_is_actual"] is False
    assert row["economics"]["turnover"]["status"] == "proxy"
    assert row["variant_plan"]["ready"] is False
    assert row["variant_plan"]["automatic_variant_creation"] is False


def test_batch_idempotency_rejects_changed_pilot_limit_or_budget():
    batch, observations, evidence, _ = workspace()
    capture_pair(observations, evidence)
    prepare(batch, key="same-key")

    with pytest.raises(ValueError, match="idempotency conflict"):
        batch.prepare(
            store_ref="ozon-primary",
            policy_id=BATCH_POLICY_ID,
            idempotency_key="same-key",
            candidate_limit=500,
            pilot_limit=1,
            max_age_hours=72,
            max_inventory_cash_cny=Decimal("5000"),
            cm3_floor_cny=Decimal("0"),
            actor_id="operator-1",
            as_of="2026-07-27T02:00:00+00:00",
        )


def test_run_replay_preserves_unmatched_market_summary_and_evidence_projection():
    batch, observations, evidence, _ = workspace()
    capture_pair(observations, evidence)
    observations.capture(
        {
            "source_profile": "manual_verified_public_page",
            "marketplace": "ozon",
            "store_ref": "ozon-primary",
            "source_url": "https://www.ozon.ru/product/unmatched-2/",
            "observed_at": "2026-07-27T01:10:00+00:00",
            "idempotency_key": "ozon-unmatched-2",
            "confirmed": True,
            "items": [
                {
                    "external_item_id": "ozon-unmatched-2",
                    "supplier_ref": "ozon-market",
                    "title": "Другой точный вариант",
                    "variant_key": "OTHER-2",
                    "currency": "CNY",
                    "displayed_price": "2200",
                    "price_kind": "marketplace_listing_price",
                    "availability": "in_stock",
                    "specifications": {"category": "other", "model": "2"},
                    "product_identity": {
                        "category": "other",
                        "model": "2",
                    },
                    "confidence": "0.8",
                    "market_signals": {
                        "sales_proxy_type": "no_data",
                        "sales_proxy_value": None,
                    },
                }
            ],
        },
        actor_id="operator-1",
    )

    first = prepare(batch)
    replay = prepare(batch)
    content, _ = evidence.content(first["evidence_id"])
    artifact = json.loads(content)

    assert first["counts"]["ozon_observed"] == 2
    assert first["counts"]["exact_matched"] == 1
    assert first["market_summary"]["observed_items"] == 2
    assert replay["market_summary"] == first["market_summary"]
    assert artifact["market_summary"] == first["market_summary"]
    assert artifact["counts"] == first["counts"]
    assert len(artifact["candidates"]) == len(first["candidates"]) == 1


def test_missing_or_unknown_sales_proxy_remains_no_data_and_blocks_pilot():
    batch, observations, evidence, _ = workspace()
    capture_pair(
        observations,
        evidence,
        market_signal_overrides={
            "sales_proxy_type": "no_data",
            "sales_proxy_value": None,
        },
    )

    result = prepare(batch)
    row = result["candidates"][0]

    assert row["market"]["sales_semantics"] == "no_data"
    assert row["economics"]["turnover"]["status"] == "no_data"
    assert "market_demand_proxy_no_data" in row["blockers"]
    assert row["pilot_ready"] is False


def test_bad_component_evidence_and_stale_checkout_fail_closed():
    batch, observations, evidence, _ = workspace()
    capture_pair(
        observations,
        evidence,
        market_signal_overrides={
            "taxes_evidence_id": "evd_missing_component",
        },
    )

    result = batch.prepare(
        store_ref="ozon-primary",
        policy_id=BATCH_POLICY_ID,
        idempotency_key="stale-and-bad-evidence",
        candidate_limit=500,
        pilot_limit=20,
        max_age_hours=24,
        max_inventory_cash_cny=Decimal("5000"),
        cm3_floor_cny=Decimal("0"),
        actor_id="operator-1",
        as_of="2026-07-29T02:00:00+00:00",
    )
    row = result["candidates"][0]

    assert "observation_stale" in row["blockers"]
    assert "evidence_integrity_failed" in row["blockers"]
    assert "fifteen_component_cost_evidence_incomplete" in row["blockers"]
    assert row["pilot_ready"] is False


def test_variant_expansion_requires_real_attributes_readbacks_and_deduplicates():
    batch, _, evidence, _ = workspace()
    evidence_ids = []
    for name in ("parent", "dimensions", "24h", "72h", "7d", "settlement"):
        evidence_ids.append(
            evidence.capture(
                content=name.encode(),
                filename=f"{name}.txt",
                content_type="text/plain",
                source="test-variant-source",
                source_ref=f"test-variant-source:{name}",
                grade=EvidenceGrade.B,
                effective_at="2026-07-27T00:00:00+00:00",
                effective_until=None,
                created_by="reviewer-1",
                metadata={"retention_class": "operational"},
            ).id
        )
    parent, dimensions, read24, read72, read7d, settlement = evidence_ids
    existing_key = batch._variants(
        market={
            "target_product_id": "prd-parent",
            "product_identity": {
                "category": "electric_hoist",
                "model": "PA500",
            },
            "market_signals": {
                "parent_sku_verified": True,
                "parent_sku_evidence_id": parent,
                "verified_variant_dimensions": {"color": ["red"]},
                "verified_variant_dimensions_evidence_id": dimensions,
            },
            "experiment_readbacks": {
                "24h": {"decision": "scale", "evidence_id": read24},
                "72h": {"decision": "scale", "evidence_id": read72},
                "7d": {"decision": "scale", "evidence_id": read7d},
                "settlement_cycles": 2,
                "settlement_evidence_id": settlement,
            },
        },
        valid_evidence=set(evidence_ids),
    )["suggestions"][0]["candidate_key"]

    result = batch._variants(
        market={
            "target_product_id": "prd-parent",
            "product_identity": {
                "category": "electric_hoist",
                "model": "PA500",
            },
            "market_signals": {
                "parent_sku_verified": True,
                "parent_sku_evidence_id": parent,
                "verified_variant_dimensions": {
                    "color": ["red", "blue"],
                },
                "verified_variant_dimensions_evidence_id": dimensions,
                "existing_variant_candidate_keys": [existing_key],
            },
            "experiment_readbacks": {
                "24h": {"decision": "scale", "evidence_id": read24},
                "72h": {"decision": "scale", "evidence_id": read72},
                "7d": {"decision": "scale", "evidence_id": read7d},
                "settlement_cycles": 2,
                "settlement_evidence_id": settlement,
            },
        },
        valid_evidence=set(evidence_ids),
    )

    assert result["ready"] is True
    assert result["automatic_variant_creation"] is False
    assert result["category_pollution_allowed"] is False
    assert result["fake_attribute_allowed"] is False
    assert result["duplicate_candidate_keys"] == [existing_key]
    assert [item["value"] for item in result["suggestions"]] == ["blue"]


def test_cross_currency_without_dated_fx_is_blocked():
    batch, observations, evidence, _ = workspace()
    capture_pair(
        observations,
        evidence,
        sale_currency="RUB",
        sale_price="10000",
    )

    result = prepare(batch)
    row = result["candidates"][0]

    assert row["economics"]["downside"]["cm3_cny"] is None
    assert "fx_rate_or_date_missing" in row["blockers"]
    assert result["counts"]["pilot_ready"] == 0


def test_screening_profile_supports_governed_batch_targets_and_overrides():
    policy = BatchOpportunityWorkspace._screening_policy(
        {
            "profile_id": "lightweight_fast_mover_v1",
            "selection_target": 1000,
            "min_score": "60",
            "max_moq": 5,
            "excluded_category_flags": [
                "Liquid",
                "battery",
                "liquid",
            ],
        }
    )

    assert policy["contract_version"] == "kjds-batch-screening/1.0.0"
    assert policy["selection_target"] == 1000
    assert policy["min_score"] == "60"
    assert policy["max_moq"] == 5
    assert policy["excluded_category_flags"] == ["battery", "liquid"]
    assert policy["third_party_erp_target"] is False
    assert policy["external_write_allowed"] is False


def test_screen_candidate_returns_explainable_accept_and_reject_reasons():
    candidate = {
        "score": {"total": "70.00"},
        "market": {
            "signals": {
                "competitor_count": 8,
                "sales_proxy_value": 20,
                "stockout_opportunity": True,
                "category_flags": ["household"],
            }
        },
        "supply": {
            "supplier_density": 3,
            "moq": 2,
            "observed_checkout_price": "12.00",
            "signals": {},
        },
        "economics": {"downside": {"cm3_rate": "0.20"}},
        "content": {"content_ready": False},
        "identity_match": {
            "product_identity": {"category": "household"}
        },
    }
    policy = BatchOpportunityWorkspace._screening_policy(
        {
            "profile_id": "lightweight_fast_mover_v1",
            "selection_target": 50,
        }
    )

    accepted = BatchOpportunityWorkspace._screen_candidate(
        candidate,
        policy=policy,
    )
    assert accepted["accepted"] is True
    assert accepted["reasons"] == []
    assert accepted["kjds_item_master_created"] is False

    rejected_policy = BatchOpportunityWorkspace._screening_policy(
        {
            "profile_id": "custom_v1",
            "selection_target": 50,
            "min_score": "80",
            "max_moq": 1,
            "require_content_ready": True,
        }
    )
    rejected = BatchOpportunityWorkspace._screen_candidate(
        candidate,
        policy=rejected_policy,
    )
    assert rejected["accepted"] is False
    assert rejected["reasons"] == [
        "content_not_ready_for_profile",
        "moq_above_profile_ceiling",
        "score_below_profile_floor",
    ]


@pytest.mark.parametrize("target", [49, 51, 999, 1001])
def test_screening_profile_rejects_non_governed_batch_target(target: int):
    with pytest.raises(ValueError, match="selection_target"):
        BatchOpportunityWorkspace._screening_policy(
            {"profile_id": "custom_v1", "selection_target": target}
        )


def test_selected_batch_candidates_create_idempotent_kjds_item_master_only():
    database = engine()
    evidence = EvidenceService(database)
    repository = InMemoryRepository()
    batch = BatchOpportunityWorkspace(
        engine=database,
        observations=object(),
        evidence=evidence,
        finance=FakeFinance(),
        repository=repository,
        operating_tasks=FakeTasks(),
    )
    run_id = "bor-item-master-test"
    fingerprint = "c" * 64
    candidate_payload = {
        "fingerprint": fingerprint,
        "market": {"title": "Cable organizer"},
        "screening": {
            "accepted": True,
            "selection_status": (
                "selected_for_kjds_item_master_review"
            ),
        },
    }
    artifact = {
        "run_id": run_id,
        "store_ref": "ozon-primary",
        "scope": {
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "scope_grant_authority_sha256": "a" * 64,
        },
        "screening": {"selection_target": 50},
        "candidates": [candidate_payload],
    }
    record = evidence.capture(
        content=json.dumps(
            artifact,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        filename="batch-item-master.json",
        content_type="application/json",
        source="batch-opportunity-run",
        source_ref=(
            "batch-opportunity://ozon-primary/item-master-test"
        ),
        grade=EvidenceGrade.C,
        effective_at="2026-07-27T02:00:00+00:00",
        effective_until=None,
        created_by="operator-a",
        metadata={"retention_class": "operational"},
    )
    created_at = datetime.fromisoformat("2026-07-27T02:00:00+00:00")
    with Session(database) as session, session.begin():
        session.add(
            BatchOpportunityRunRow(
                id=run_id,
                store_ref="ozon-primary",
                tenant_ref="tenant-a",
                entity_ref="entity-a",
                scope_grant_authority_sha256="a" * 64,
                scope_evidence_authority_sha256="b" * 64,
                idempotency_key="item-master-source",
                policy_id=BATCH_POLICY_ID,
                contract_version="batch-opportunity/1.3.0",
                snapshot_sha256="d" * 64,
                evidence_id=record.id,
                as_of=created_at,
                created_by="operator-a",
                created_at=created_at,
                counts_json={},
                policy_json={},
                blockers_json=[],
                payload_json=artifact,
                task_id=None,
            )
        )
        session.flush()
        session.add(
            BatchOpportunityCandidateRow(
                id="boc-item-master-test",
                run_id=run_id,
                candidate_key="e" * 64,
                fingerprint=fingerprint,
                rank=1,
                state="evaluate",
                strategy="exploration",
                pilot_ready=False,
                payload_json=candidate_payload,
                evidence_id=record.id,
            )
        )

    values = {
        "run_id": run_id,
        "store_ref": "ozon-primary",
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "scope_grant_authority_sha256": "a" * 64,
        "idempotency_key": "kjds-item-master-1",
        "actor_id": "operator-a",
        "as_of": datetime.fromisoformat("2026-07-27T03:00:00+00:00"),
    }
    created = batch.create_kjds_item_master_candidates(**values)
    replay = batch.create_kjds_item_master_candidates(**values)

    assert created["created"] == 1
    assert replay["created"] == 0
    assert replay["already_exists"] == 1
    products = repository.list_products()
    assert len(products) == 1
    assert products[0].status.value == "candidate"
    assert products[0].sku.startswith("KJDS-")
    assert created["authority"] == {
        "system_of_record": "kjds_canonical_product_pim",
        "product_status": "candidate",
        "third_party_erp_called": False,
        "supplier_offer_created": False,
        "inventory_created": False,
        "purchase_created": False,
        "listing_created": False,
        "ozon_write_performed": False,
        "external_write_allowed": False,
    }


def test_item_master_rejects_candidate_payload_not_in_evidence():
    database = engine()
    evidence = EvidenceService(database)
    repository = InMemoryRepository()
    batch = BatchOpportunityWorkspace(
        engine=database,
        observations=object(),
        evidence=evidence,
        finance=FakeFinance(),
        repository=repository,
        operating_tasks=FakeTasks(),
    )
    run_id = "bor-item-master-tampered"
    fingerprint = "f" * 64
    artifact_candidate = {
        "fingerprint": fingerprint,
        "market": {"title": "Original title"},
        "screening": {
            "accepted": True,
            "selection_status": (
                "selected_for_kjds_item_master_review"
            ),
        },
    }
    artifact = {
        "run_id": run_id,
        "store_ref": "ozon-primary",
        "scope": {
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "scope_grant_authority_sha256": "a" * 64,
        },
        "screening": {"selection_target": 50},
        "candidates": [artifact_candidate],
    }
    record = evidence.capture(
        content=json.dumps(
            artifact,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        filename="batch-item-master-tampered.json",
        content_type="application/json",
        source="batch-opportunity-run",
        source_ref="batch-opportunity://ozon-primary/tampered",
        grade=EvidenceGrade.C,
        effective_at="2026-07-27T02:00:00+00:00",
        effective_until=None,
        created_by="operator-a",
        metadata={"retention_class": "operational"},
    )
    created_at = datetime.fromisoformat("2026-07-27T02:00:00+00:00")
    with Session(database) as session, session.begin():
        session.add(
            BatchOpportunityRunRow(
                id=run_id,
                store_ref="ozon-primary",
                tenant_ref="tenant-a",
                entity_ref="entity-a",
                scope_grant_authority_sha256="a" * 64,
                scope_evidence_authority_sha256="b" * 64,
                idempotency_key="tampered-source",
                policy_id=BATCH_POLICY_ID,
                contract_version="batch-opportunity/1.3.0",
                snapshot_sha256="d" * 64,
                evidence_id=record.id,
                as_of=created_at,
                created_by="operator-a",
                created_at=created_at,
                counts_json={},
                policy_json={},
                blockers_json=[],
                payload_json=artifact,
                task_id=None,
            )
        )
        session.flush()
        session.add(
            BatchOpportunityCandidateRow(
                id="boc-item-master-tampered",
                run_id=run_id,
                candidate_key="e" * 64,
                fingerprint=fingerprint,
                rank=1,
                state="evaluate",
                strategy="exploration",
                pilot_ready=False,
                payload_json={
                    **artifact_candidate,
                    "market": {"title": "Changed after Evidence"},
                },
                evidence_id=record.id,
            )
        )

    with pytest.raises(ValueError, match="does not match storage"):
        batch.create_kjds_item_master_candidates(
            run_id=run_id,
            store_ref="ozon-primary",
            tenant_ref="tenant-a",
            entity_ref="entity-a",
            scope_grant_authority_sha256="a" * 64,
            idempotency_key="kjds-item-master-tampered",
            actor_id="operator-a",
            as_of=datetime.fromisoformat(
                "2026-07-27T03:00:00+00:00"
            ),
        )
    assert repository.list_products() == []
