from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceService
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base
from apps.control_plane.store_category_strategy import (
    StoreCategoryStrategyConflict,
    StoreCategoryStrategyRegistry,
    StoreCategoryStrategyWorkspace,
    StoreOperatingPlanSnapshotRow,
    StoreOperatingProfileRow,
)

AS_OF = datetime(2026, 8, 2, 9, tzinfo=UTC)


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    return engine


def principal(*, tenant_ref: str = "tenant-a") -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=frozenset({"store-a", "store-b"}),
    )


def scope(*, entity_ref: str = "entity-a") -> dict:
    return {
        "status": "ready",
        "entity_ref": entity_ref,
        "authority_sha256": "a" * 64,
    }


def profile_request(**overrides) -> dict:
    value = {
        "idempotency_key": "store-a-profile-v1",
        "confirmed": True,
        "store_positioning": "category_specialist",
        "assortment_mode": "hybrid",
        "price_band": "mid",
        "target_regions": ["RU"],
        "fulfillment_models": ["FBS"],
        "planned_growth_channels": ["ozon", "vk", "telegram"],
        "customer_segments": ["home-garden"],
        "operational_capabilities": ["russian-content", "returns-review"],
        "supporting_evidence_ids": [],
        "category_paths": [
            {
                "path_id": "garden-tools-chain-saws",
                "role": "core",
                "level_1": {"id": "home-garden", "name": "Home and garden"},
                "level_2": {"id": "garden-tools", "name": "Garden tools"},
                "level_3": {"id": "power-saws", "name": "Power saws"},
                "leaf_category_id": "17028946",
                "product_type_ids": ["94715"],
                "derived_tags": ["heavy", "content_led"],
                "target_regions": ["RU"],
            }
        ],
    }
    value.update(overrides)
    return value


def candidate(**overrides) -> dict:
    value = {
        "candidate_id": "ozon:1982483707WZ",
        "offer_id": "1982483707WZ",
        "name": "Cordless garden saw",
        "decision_class": "needs_data",
        "category_identity": {
            "source_category_id": "17028946",
            "product_type_id": "94715",
            "hierarchy": {
                "level_1_id": None,
                "level_2_id": None,
                "level_3_id": None,
            },
            "derived_tags": [],
        },
        "profit": {
            "risk_adjusted_profit": {
                "status": "no_data",
                "downside_cm3": None,
            },
            "cash_profit": {"status": "no_data", "amount": None},
        },
        "reason_codes": ["fx_basis_missing"],
        "next_action": "Add FX and exact costs.",
        "budget_limit": None,
        "stop_loss_condition": None,
        "evidence_ids": ["evd-source"],
    }
    value.update(overrides)
    return value


def service():
    engine = database()
    return (
        StoreCategoryStrategyWorkspace(
            engine=engine,
            evidence=EvidenceService(engine),
        ),
        engine,
    )


def test_profile_capture_is_evidenced_idempotent_and_scope_isolated() -> None:
    workspace, engine = service()
    first = workspace.capture_profile(
        profile_request(),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    replay = workspace.capture_profile(
        profile_request(),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert first["status"] == "ready"
    assert first["formal_fact_promoted"] is False
    assert first["external_write_allowed"] is False
    assert replay["profile_id"] == first["profile_id"]
    assert replay["idempotent"] is True
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(StoreOperatingProfileRow)) == 1

    with pytest.raises(StoreCategoryStrategyConflict, match="different immutable content"):
        workspace.capture_profile(
            profile_request(price_band="premium"),
            principal=principal(),
            entity_scope=scope(),
            store_ref="store-a",
            as_of=AS_OF,
        )

    with pytest.raises(KeyError):
        workspace.get_plan_snapshot(
            "missing",
            principal=principal(tenant_ref="tenant-b"),
            entity_scope=scope(entity_ref="entity-b"),
            store_ref="store-a",
        )


def test_exact_official_category_routes_to_primary_store_without_guessing() -> None:
    workspace, _ = service()
    captured = workspace.capture_profile(
        profile_request(),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    result = workspace.compile_candidate(candidate(), profile=captured["profile"])
    route = result["store_category_route"]

    assert route["decision"] == "primary_store"
    assert route["confidence"] == "exact_leaf"
    assert route["target_store_ref"] == "store-a"
    assert route["target_category_path"]["level_1"]["id"] == "home-garden"
    assert route["derived_tags"] == ["content_led", "heavy"]
    assert route["derived_tags_are_official_taxonomy"] is False
    assert route["playbook"]["lifecycle"] == "research"
    assert route["playbook"]["listing"] == (
        "hold_until_official_category_and_profit_evidence"
    )
    assert route["external_write_allowed"] is False


def test_research_backed_playbook_registry_is_open_ended_and_source_bound() -> None:
    registry = StoreCategoryStrategyRegistry()

    assert len(registry.operating_playbooks) >= 10
    assert "evidence_first_micro_pilot" in registry.operating_playbooks
    assert "controlled_paid_growth" in registry.operating_playbooks
    assert "aging_stock_exit" in registry.operating_playbooks
    assert all(
        contract["source_refs"]
        for contract in registry.operating_playbooks.values()
    )
    assert registry.snapshot()["operating_playbook_semantics"].startswith(
        "open_ended_research_backed"
    )


def test_candidate_gets_stage_specific_playbooks_without_external_authority() -> None:
    workspace, _ = service()
    captured = workspace.capture_profile(
        profile_request(),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    result = workspace.compile_candidate(candidate(), profile=captured["profile"])
    portfolio = result["store_category_route"]["operating_portfolio"]
    items = {item["playbook_id"]: item for item in portfolio["items"]}

    assert portfolio["recommended_playbook_id"] == "supplier_evidence_sprint"
    assert items["supplier_evidence_sprint"]["status"] == "proposal_ready"
    assert items["supplier_evidence_sprint"]["action_status"] == (
        "pending_human_decision"
    )
    assert items["recursive_seller_store_discovery"]["status"] == "proposal_ready"
    assert items["controlled_paid_growth"]["status"] == "awaiting_inputs"
    assert items["controlled_paid_growth"]["action_status"] == "awaiting_evidence"
    assert items["price_and_margin_guard"]["proposal_type"] == (
        "price_change_proposal"
    )
    assert set(items["price_and_margin_guard"]["allowed_human_decisions"]) == {
        "approve_for_existing_gate_flow",
        "reject_with_reason",
        "defer_until",
        "request_more_evidence",
    }
    assert all(item["external_write_allowed"] is False for item in items.values())


def test_automation_master_off_keeps_requested_action_manual_and_ungranted() -> None:
    workspace, _ = service()
    captured = workspace.capture_profile(
        profile_request(
            automation_preferences=[
                {
                    "playbook_id": "media_readiness_and_conversion",
                    "enabled": True,
                    "mode": "policy_bound_autonomous",
                }
            ]
        ),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    result = workspace.compile_candidate(candidate(), profile=captured["profile"])
    items = {
        item["playbook_id"]: item
        for item in result["store_category_route"]["operating_portfolio"]["items"]
    }
    control = items["media_readiness_and_conversion"]["automation_control"]

    assert control["checkbox_visible"] is True
    assert control["master_enabled"] is False
    assert control["action_enabled"] is True
    assert control["requested_mode"] == "policy_bound_autonomous"
    assert control["effective_mode"] == "manual_each_action"
    assert control["effective_mode_reason"] == "automation_master_disabled"
    assert control["automatic_execution_requested"] is False
    assert control["runtime_state"] == "planned"
    assert control["runtime_execution_enabled"] is False
    assert control["grant_ready"] is False
    assert control["preference_is_grant"] is False
    assert items["media_readiness_and_conversion"]["external_write_allowed"] is False


def test_automation_master_and_action_record_bounded_request_without_grant() -> None:
    workspace, _ = service()
    captured = workspace.capture_profile(
        profile_request(
            automation_master_enabled=True,
            automation_default_mode="supervised_batch",
            automation_preferences=[
                {
                    "playbook_id": "media_readiness_and_conversion",
                    "enabled": True,
                    "mode": "policy_bound_autonomous",
                    "caps": {
                        "max_actions_per_day": 5,
                        "max_budget_cny": "800.00",
                        "max_price_change_percent": "8.5",
                        "max_quantity": 40,
                        "max_loss_cny": "100.00",
                        "valid_until": "2026-08-31T23:59:59+08:00",
                    },
                }
            ],
        ),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    result = workspace.compile_candidate(candidate(), profile=captured["profile"])
    items = {
        item["playbook_id"]: item
        for item in result["store_category_route"]["operating_portfolio"]["items"]
    }
    control = items["media_readiness_and_conversion"]["automation_control"]
    unconfigured = items["controlled_paid_growth"]["automation_control"]

    assert control["master_enabled"] is True
    assert control["action_enabled"] is True
    assert control["automatic_execution_requested"] is True
    assert control["requested_mode"] == "policy_bound_autonomous"
    assert control["effective_mode"] == "manual_each_action"
    assert control["effective_mode_reason"] == "requested_mode_not_runtime_enabled"
    assert control["caps"] == {
        "max_actions_per_day": 5,
        "max_budget_cny": "800.00",
        "max_price_change_percent": "8.5",
        "max_quantity": 40,
        "max_loss_cny": "100.00",
        "valid_until": "2026-08-31T15:59:59+00:00",
    }
    assert control["bounded_caps_configured"] is True
    assert control["grant_ready"] is False
    assert control["runtime_execution_enabled"] is False
    assert unconfigured["action_enabled"] is False
    assert unconfigured["requested_mode"] == "supervised_batch"
    assert unconfigured["automatic_execution_requested"] is False
    assert unconfigured["effective_mode_reason"] == "playbook_automation_disabled"


def test_automation_preference_defaults_action_off_and_rejects_invalid_caps() -> None:
    workspace, _ = service()
    captured = workspace.capture_profile(
        profile_request(
            automation_master_enabled=True,
            automation_preferences=[
                {"playbook_id": "price_and_margin_guard"}
            ],
        ),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    item = next(
        item
        for item in workspace.compile_candidate(
            candidate(), profile=captured["profile"]
        )["store_category_route"]["operating_portfolio"]["items"]
        if item["playbook_id"] == "price_and_margin_guard"
    )
    assert item["automation_control"]["action_enabled"] is False
    assert item["automation_control"]["automatic_execution_requested"] is False

    with pytest.raises(ValueError, match="max_price_change_percent"):
        workspace.capture_profile(
            profile_request(
                idempotency_key="bad-automation-cap",
                automation_master_enabled=True,
                automation_preferences=[
                    {
                        "playbook_id": "price_and_margin_guard",
                        "enabled": True,
                        "mode": "policy_bound_autonomous",
                        "caps": {"max_price_change_percent": "101"},
                    }
                ],
            ),
            principal=principal(),
            entity_scope=scope(),
            store_ref="store-a",
            as_of=AS_OF,
        )


def test_exclusion_wins_and_derived_tag_alone_cannot_create_platform_route() -> None:
    workspace, _ = service()
    excluded_profile = profile_request()["category_paths"][0]
    excluded_profile = {**excluded_profile, "role": "excluded"}
    captured = workspace.capture_profile(
        profile_request(category_paths=[excluded_profile]),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    blocked = workspace.compile_candidate(candidate(), profile=captured["profile"])
    assert blocked["store_category_route"]["decision"] == "blocked"
    assert "store_category_explicitly_excluded" in blocked["store_category_route"]["reason_codes"]

    derived_only_candidate = candidate(
        category_identity={
            "source_category_id": "different",
            "product_type_id": "different",
            "hierarchy": {},
            "derived_tags": ["heavy"],
        }
    )
    advisory = workspace.compile_candidate(
        derived_only_candidate,
        profile={
            **captured["profile"],
            "category_paths": [
                {
                    **captured["profile"]["category_paths"][0],
                    "role": "core",
                }
            ],
        },
    )
    assert advisory["store_category_route"]["decision"] == "needs_category_data"
    assert advisory["store_category_route"]["confidence"] == "derived_advisory_only"
    assert advisory["store_category_route"]["target_store_ref"] is None


def test_profit_state_drives_lifecycle_but_never_authorizes_execution() -> None:
    workspace, _ = service()
    captured = workspace.capture_profile(
        profile_request(),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    profitable = candidate(
        decision_class="hold",
        profit={
            "risk_adjusted_profit": {
                "status": "available",
                "downside_cm3": "18.00",
            },
            "cash_profit": {"status": "available", "amount": "25.00"},
        },
    )
    result = workspace.compile_candidate(profitable, profile=captured["profile"])
    playbook = result["store_category_route"]["playbook"]
    assert playbook["lifecycle"] == "growth"
    assert playbook["traffic"] == "scale_only_on_positive_incremental_cash_cm3"
    portfolio = result["store_category_route"]["operating_portfolio"]
    operating = {item["playbook_id"]: item for item in portfolio["items"]}
    assert portfolio["recommended_playbook_id"] == "portfolio_cash_compounding"
    assert operating["controlled_paid_growth"]["status"] == "proposal_ready"
    assert operating["controlled_paid_growth"]["action_status"] == (
        "pending_human_decision"
    )
    assert operating["aging_stock_exit"]["status"] == "awaiting_inputs"
    assert result["store_category_route"]["external_write_allowed"] is False


def test_plan_tree_and_snapshot_are_server_owned_and_immutable() -> None:
    workspace, engine = service()
    captured = workspace.capture_profile(
        profile_request(),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    profit_workspace = {
        "summary": {
            "highest_value_action": {"candidate_id": "ozon:1982483707WZ"},
            "actual_cash_profit": {"status": "no_data", "amount": None},
            "data_freshness": {"as_of": AS_OF.isoformat()},
        },
        "snapshot_sha256": "b" * 64,
        "candidates": [candidate()],
    }
    plan = workspace.compile_plan(
        profit_workspace,
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    frozen = workspace.freeze_plan(
        plan,
        idempotency_key="plan-v1",
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )
    replay = workspace.freeze_plan(
        plan,
        idempotency_key="plan-v1",
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert plan["profile_id"] == captured["profile_id"]
    assert plan["summary"]["route_counts"]["primary_store"] == 1
    assert plan["category_tree"][0]["candidate_count"] == 1
    assert plan["control_envelope"]["automatic_cross_store_publish"] is False
    assert replay["snapshot_id"] == frozen["snapshot_id"]
    assert replay["idempotent"] is True
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(StoreOperatingPlanSnapshotRow)) == 1


def test_cross_store_matrix_selects_exact_core_route_without_publishing() -> None:
    workspace, _ = service()
    store_a = workspace.capture_profile(
        profile_request(),
        principal=principal(),
        entity_scope=scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )["profile"]
    store_b = {
        **store_a,
        "store_ref": "store-b",
        "category_paths": [
            {
                **store_a["category_paths"][0],
                "path_id": "garden-tools-experiment",
                "role": "experimental",
            }
        ],
    }
    matrix = workspace.compile_store_matrix(
        [
            {
                "store_ref": "store-a",
                "scope_status": "ready",
                "profile_status": "ready",
                "profile": store_a,
                "workspace": {"candidates": [candidate()]},
            },
            {
                "store_ref": "store-b",
                "scope_status": "ready",
                "profile_status": "ready",
                "profile": store_b,
                "workspace": {"candidates": []},
            },
        ],
        tenant_ref="tenant-a",
        as_of=AS_OF,
    )

    assert matrix["routes"][0]["recommended_store_ref"] == "store-a"
    assert matrix["routes"][0]["recommended_route"]["decision"] == "primary_store"
    assert matrix["routes"][0]["cross_store_handoff_required"] is False
    assert matrix["control_envelope"]["automatic_cross_store_publish"] is False
