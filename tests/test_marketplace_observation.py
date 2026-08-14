from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.marketplace_observation import (
    MarketplaceObservationWorkspace,
    PortfolioPilotWorkspace,
)
from apps.control_plane.sql_repository import Base


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


def observation_request(
    *,
    idempotency_key: str = "browser-jiuping-1",
    price: str = "500",
    specifications: dict[str, str] | None = None,
) -> dict:
    return {
        "source_profile": "browser_observation",
        "marketplace": "1688",
        "store_ref": "external",
        "source_url": "https://detail.1688.com/offer/1067394114846.html",
        "observed_at": "2026-07-26T15:03:14+00:00",
        "idempotency_key": idempotency_key,
        "capture_note": "Operator-confirmed public detail page",
        "confirmed": True,
        "items": [
            {
                "external_item_id": "1067394114846",
                "supplier_ref": "河北九鸣起重机械制造有限公司",
                "title": "电动葫芦220V无线遥控家用小吊机",
                "variant_key": "500KG7.6米绳无线+线控+手动",
                "currency": "CNY",
                "displayed_price": price,
                "price_kind": "public_display_price",
                "min_order_quantity": 1,
                "availability": "in_stock",
                "specifications": specifications
                or {
                    "rated_load_kg": "500",
                    "voltage_v": "220",
                    "lifting_height_m": "7.6",
                    "control_mode": "wireless+wired+manual",
                },
                "target_product_id": (
                    "prd_2215304aca03f42ab0921102a2d58de9"
                ),
                "target_offer_id": "2105343364UB",
            }
        ],
    }


def test_capture_is_evidence_backed_idempotent_and_never_promotes_price() -> None:
    database = engine()
    evidence = EvidenceService(database)
    workspace = MarketplaceObservationWorkspace(
        engine=database, evidence=evidence
    )

    first = workspace.capture(
        observation_request(),
        actor_id="operator-1",
    )
    replay = workspace.capture(
        observation_request(),
        actor_id="operator-1",
    )

    assert replay["id"] == first["id"]
    assert replay["snapshot_sha256"] == first["snapshot_sha256"]
    assert first["formal_fact_promoted"] is False
    assert first["supplier_offer_created"] is False
    assert first["actual_cost_created"] is False
    assert first["external_write_allowed"] is False
    record = evidence.get(first["evidence_id"])
    assert record.grade == EvidenceGrade.C
    assert record.metadata["price_authority"] == "research_only"
    latest = workspace.latest(
        marketplace="1688",
        target_product_id="prd_2215304aca03f42ab0921102a2d58de9",
    )
    assert len(latest) == 1
    assert latest[0]["displayed_price"] == "500.00"
    assert latest[0]["price_basis"] == "observed"


def test_capture_rejects_changed_payload_and_duplicate_natural_keys() -> None:
    database = engine()
    workspace = MarketplaceObservationWorkspace(
        engine=database,
        evidence=EvidenceService(database),
    )
    request = observation_request()
    workspace.capture(request, actor_id="operator-1")

    with pytest.raises(ValueError, match="different immutable content"):
        workspace.capture(
            observation_request(price="501"),
            actor_id="operator-1",
        )

    duplicate = observation_request(idempotency_key="duplicate-natural-key")
    duplicate["items"] = [duplicate["items"][0], dict(duplicate["items"][0])]
    with pytest.raises(ValueError, match="duplicate natural keys"):
        workspace.capture(duplicate, actor_id="operator-1")


def test_contract_only_supplier_marketplace_is_readable_but_not_capturable() -> None:
    database = engine()
    workspace = MarketplaceObservationWorkspace(
        engine=database,
        evidence=EvidenceService(database),
    )

    assert workspace.page(marketplace="tvcmall")["items"] == []
    request = observation_request(idempotency_key="contract-only-tvcmall")
    request["marketplace"] = "tvcmall"
    request["source_url"] = "https://www.tvcmall.com/details/item-1.html"
    with pytest.raises(
        ValueError,
        match="Unsupported marketplace observation marketplace",
    ):
        workspace.capture(request, actor_id="operator-1")


def test_capture_rejects_bad_url_currency_timestamp_and_unconfirmed_input() -> None:
    database = engine()
    workspace = MarketplaceObservationWorkspace(
        engine=database,
        evidence=EvidenceService(database),
    )
    request = observation_request()
    request["source_url"] = "file:///private/browser-state"
    with pytest.raises(ValueError, match=r"HTTP\(S\)"):
        workspace.capture(request, actor_id="operator-1")

    request = observation_request()
    request["items"][0]["currency"] = "RUBX"
    with pytest.raises(ValueError, match="three-letter ISO"):
        workspace.capture(request, actor_id="operator-1")

    request = observation_request()
    request["observed_at"] = "2026-07-26"
    with pytest.raises(ValueError, match="timezone"):
        workspace.capture(request, actor_id="operator-1")

    request = observation_request()
    request["confirmed"] = False
    with pytest.raises(ValueError, match="explicit operator confirmation"):
        workspace.capture(request, actor_id="operator-1")


class FakeCatalog:
    @staticmethod
    def latest_items(*, store_ref: str, limit: int):
        assert store_ref == "ozon-primary"
        assert limit == 1000
        return [
            {
                "canonical_product_id": (
                    "prd_2215304aca03f42ab0921102a2d58de9"
                ),
                "offer_id": "2105343364UB",
                "marketplace_sku": "2216781923",
                "prices": {"price": "2291.00"},
                "currency_code": "CNY",
                "available_stock": 9,
                "item_hash": "a" * 64,
            }
        ]


class FakeRepository:
    @staticmethod
    def get_product(product_id: str):
        return SimpleNamespace(
            id=product_id,
            sku="ozon:ozon-primary:2105343364UB",
            name="500kg 7.6m hoist",
        )


class FakeSourcing:
    def __init__(self, *, release_ready: bool = False) -> None:
        self.ready = release_ready

    def compare_product_offers(self, product_id: str) -> dict:
        if not self.ready:
            return {
                "product": {"id": product_id},
                "supplier_count": 0,
                "offer_count": 0,
                "scenario_count": 0,
                "ready_for_procurement_review": False,
                "rows": [],
            }
        offer = SimpleNamespace(
            id="off-jiuming",
            supplier_ref="河北九鸣起重机械制造有限公司",
            external_id="1067394114846",
        )
        scenario = SimpleNamespace(id="scn-jiuming", cm3_cny=Decimal("88"))
        return {
            "product": {"id": product_id},
            "supplier_count": 1,
            "offer_count": 1,
            "scenario_count": 1,
            "ready_for_procurement_review": False,
            "rows": [{"offer": offer, "scenario": scenario}],
        }

    def release_ready(self, _scenario) -> bool:
        return self.ready


class FakeTasks:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ensure_internal_task(self, **values):
        self.calls.append(values)
        return {
            "id": "tsk-pilot",
            "metric_id": "internal:portfolio_pilot_blocked",
            "owner": values["owner"],
            "status": "open",
        }


def pilot_workspace(
    *,
    displayed_price: str,
    specifications: dict[str, str],
    release_ready: bool = False,
) -> tuple[PortfolioPilotWorkspace, FakeTasks]:
    database = engine()
    evidence = EvidenceService(database)
    observations = MarketplaceObservationWorkspace(
        engine=database, evidence=evidence
    )
    observations.capture(
        observation_request(
            price=displayed_price,
            specifications=specifications,
        ),
        actor_id="operator-1",
    )
    tasks = FakeTasks()
    return (
        PortfolioPilotWorkspace(
            observations=observations,
            marketplace_catalog=FakeCatalog(),
            sourcing=FakeSourcing(release_ready=release_ready),
            repository=FakeRepository(),
            operating_tasks=tasks,
        ),
        tasks,
    )


TARGET_SPECIFICATION = {
    "rated_load_kg": "500",
    "voltage_v": "220",
    "lifting_height_m": "7.6",
    "power_w": "1500",
    "wire_rope_mm": "6",
    "control_mode": "wireless+wired+manual",
    "plug": "russia",
    "duty_cycle": "continuous",
}


def test_prepare_separates_observed_spread_from_cm3_and_projects_blocker() -> None:
    workspace, tasks = pilot_workspace(
        displayed_price="500",
        specifications={
            "rated_load_kg": "500",
            "voltage_v": "220",
            "lifting_height_m": "7.6",
            "power_w": "page_displays_150_under_kw_column",
            "control_mode": "wireless+wired+manual",
        },
    )

    result = workspace.prepare(
        store_ref="ozon-primary",
        product_id="prd_2215304aca03f42ab0921102a2d58de9",
        target_specification=TARGET_SPECIFICATION,
        policy_id="ozon-cny-research-screening-v1",
        candidate_target=100,
        pilot_limit=10,
        max_loss_cny=Decimal("500"),
        cm3_floor_cny=Decimal("0"),
        actor_id="operator-1",
        as_of="2026-07-26T16:00:00+00:00",
    )

    row = result["ranked_candidates"][0]
    assert row["economics"]["observed_spread"] == "1791.00"
    assert row["economics"]["screening_contribution_base"] == "543.33"
    assert row["economics"]["screening_contribution_downside"] == "-383.60"
    assert row["economics"]["scenario_cm3"] is None
    assert row["economics"]["actual_profit"] is None
    assert row["specification_match"]["status"] == "mismatch"
    assert row["pilot_ready"] is False
    assert result["counts"]["pilot_ready"] == 0
    assert result["actual_profit_available"] is False
    assert result["automatic_listing"] is False
    assert tasks.calls[0]["owner"] == "supply"
    assert tasks.calls[0]["evidence_ids"]


def test_exact_positive_screen_still_requires_release_ready_profit_scenario() -> None:
    workspace, _ = pilot_workspace(
        displayed_price="100",
        specifications=TARGET_SPECIFICATION,
    )
    result = workspace.prepare(
        store_ref="ozon-primary",
        product_id="prd_2215304aca03f42ab0921102a2d58de9",
        target_specification=TARGET_SPECIFICATION,
        policy_id="ozon-cny-research-screening-v1",
        candidate_target=100,
        pilot_limit=10,
        max_loss_cny=Decimal("500"),
        cm3_floor_cny=Decimal("0"),
        actor_id="operator-1",
        as_of="2026-07-26T16:00:00+00:00",
    )

    row = result["ranked_candidates"][0]
    assert row["specification_match"]["status"] == "exact"
    assert Decimal(
        row["economics"]["screening_contribution_downside"]
    ) > 0
    assert row["state"] == "partial"
    assert row["pilot_ready"] is False
    assert row["blockers"] == ["full_cost_profit_scenario_missing"]


def test_exact_positive_candidate_with_release_ready_scenario_is_pilot_ready() -> None:
    workspace, tasks = pilot_workspace(
        displayed_price="100",
        specifications=TARGET_SPECIFICATION,
        release_ready=True,
    )
    result = workspace.prepare(
        store_ref="ozon-primary",
        product_id="prd_2215304aca03f42ab0921102a2d58de9",
        target_specification=TARGET_SPECIFICATION,
        policy_id="ozon-cny-research-screening-v1",
        candidate_target=100,
        pilot_limit=10,
        max_loss_cny=Decimal("500"),
        cm3_floor_cny=Decimal("0"),
        actor_id="operator-1",
        as_of="2026-07-26T16:00:00+00:00",
    )

    row = result["ranked_candidates"][0]
    assert row["state"] == "ready"
    assert row["pilot_ready"] is True
    assert row["economics"]["scenario_cm3"] == "88"
    assert result["counts"]["pilot_ready"] == 1
    assert result["blockers"] == []
    assert tasks.calls == []


def test_cross_currency_observation_is_blocked_without_dated_fx() -> None:
    database = engine()
    evidence = EvidenceService(database)
    observations = MarketplaceObservationWorkspace(
        engine=database, evidence=evidence
    )
    request = observation_request(
        price="500", specifications=TARGET_SPECIFICATION
    )
    request["items"][0]["currency"] = "RUB"
    observations.capture(request, actor_id="operator-1")
    workspace = PortfolioPilotWorkspace(
        observations=observations,
        marketplace_catalog=FakeCatalog(),
        sourcing=FakeSourcing(),
        repository=FakeRepository(),
        operating_tasks=FakeTasks(),
    )

    result = workspace.prepare(
        store_ref="ozon-primary",
        product_id="prd_2215304aca03f42ab0921102a2d58de9",
        target_specification=TARGET_SPECIFICATION,
        policy_id="ozon-cny-research-screening-v1",
        candidate_target=100,
        pilot_limit=10,
        max_loss_cny=Decimal("500"),
        cm3_floor_cny=Decimal("0"),
        actor_id="operator-1",
    )

    row = result["ranked_candidates"][0]
    assert row["economics"]["observed_spread"] is None
    assert row["economics"]["screening_contribution_base"] is None
    assert "cross_currency_fx_missing" in row["blockers"]
    assert row["pilot_ready"] is False
