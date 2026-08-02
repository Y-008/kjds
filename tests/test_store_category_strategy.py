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
