from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.control_plane.runtime import build_runtime
from apps.control_plane.scoped_growth_experiments import (
    ScopedGrowthExperimentWorkspace,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base, ProductRow

AS_OF = datetime(2026, 7, 29, 12, tzinfo=UTC)
SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
}


def principal():
    return Principal(
        actor_id="growth-integration",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"ozon-primary"}),
    )


def projection(contract_id, **values):
    return {
        "contract_id": contract_id,
        "status": "ready",
        "as_of": AS_OF.isoformat(),
        "scope": SCOPE,
        "source_gaps": [],
        "snapshot_sha256": "a" * 64,
        **values,
    }


def production_root(monkeypatch, tmp_path):
    database = tmp_path / "growth-composition.sqlite3"
    monkeypatch.setenv("KJDS_REPOSITORY", "memory")
    monkeypatch.setenv(
        "KJDS_DATABASE_URL",
        f"sqlite+pysqlite:///{database.as_posix()}",
    )
    services = build_runtime()
    engine = services.scoped_oms.engine
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            ProductRow(
                id="product-a",
                sku="SKU-A",
                name="Product A",
                market="RU",
                channel="ozon",
                status="active",
                created_at=datetime(2026, 7, 20, tzinfo=UTC),
                tenant_ref="tenant-a",
                entity_ref="entity-a",
                store_ref="ozon-primary",
                scope_grant_authority_sha256="f" * 64,
                scope_as_of=datetime(2026, 7, 20, tzinfo=UTC),
                created_by="integration",
            )
        )
    with Session(engine) as session:
        assert session.scalar(
            select(ProductRow).where(ProductRow.id == "product-a")
        ) is not None
    root = services.scoped_growth_experiments
    assert isinstance(root, ScopedGrowthExperimentWorkspace)
    for dependency in (
        root.pim,
        root.listing,
        root.inventory,
        root.oms,
        root.profit,
        root.market,
        root.customer_service,
    ):
        assert dependency.__class__.__module__.startswith(
            "apps.control_plane."
        )
    return root


def bind_ready_projections(monkeypatch, root):
    product = {"id": "product-a", "sku": "SKU-A", "name": "Product A"}
    row = {"product": product, "product_id": "product-a", "sku": "SKU-A"}
    values = {
        "pim": projection(
            "kjds-native-exact-scope-pim-workspace-v1",
            product_groups=[
                {
                    "product": product,
                    "listings": [{"offer_id": "offer-a"}],
                    "readiness": {"status": "ready"},
                }
            ],
        ),
        "listing": projection(
            "kjds-native-exact-scope-listing-lifecycle-v1",
            items=[row],
        ),
        "inventory": projection(
            "kjds-native-scoped-inventory-fulfillment-v1",
            sku_summaries=[row],
        ),
        "oms": projection(
            "kjds-native-scoped-oms-v1",
            orders=[row],
        ),
        "profit": projection(
            "kjds-native-exact-scope-actual-profit-ledger-v1",
            items=[row],
        ),
        "market": projection(
            "kjds-scoped-marketplace-observation-v1",
            items=[row],
        ),
        "customer_service": projection(
            "kjds-native-exact-scope-customer-service-v1",
            cases=[row],
        ),
    }
    methods = {
        "pim": "project",
        "listing": "project",
        "inventory": "workspace",
        "oms": "workspace",
        "profit": "snapshot",
        "market": "latest",
        "customer_service": "project",
    }
    for name, method in methods.items():
        monkeypatch.setattr(
            getattr(root, name),
            method,
            lambda _value=values[name], **_kwargs: copy.deepcopy(_value),
        )
    return values


def run(root):
    return root.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AS_OF,
    )


def test_production_composition_root_projects_ready_from_bound_services(
    monkeypatch,
    tmp_path,
):
    root = production_root(monkeypatch, tmp_path)
    bind_ready_projections(monkeypatch, root)

    result = run(root)

    assert result["status"] == "ready"
    assert result["counts"] == {
        "total": 1,
        "ready": 1,
        "partial": 0,
        "blocked": 0,
    }
    assert result["agent_artifact"]["external_write_allowed"] is False


def test_production_composition_root_blocks_latest_bad_authority(
    monkeypatch,
    tmp_path,
):
    root = production_root(monkeypatch, tmp_path)
    values = bind_ready_projections(monkeypatch, root)
    values["oms"]["status"] = "blocked"
    values["oms"]["source_gaps"] = ["oms_latest_fact_bad"]

    result = run(root)

    assert result["status"] == "blocked"
    assert result["experiments"] == []
    assert "growth_oms_blocked" in result["source_gaps"]


@pytest.mark.parametrize(
    ("mutation", "gap"),
    [
        (
            lambda value: value.update({"contract_id": "drifted"}),
            "growth_pim_contract_drift",
        ),
        (
            lambda value: value.update({"snapshot_sha256": "bad"}),
            "growth_pim_snapshot_invalid",
        ),
    ],
)
def test_production_composition_root_blocks_schema_or_snapshot_drift(
    monkeypatch,
    tmp_path,
    mutation,
    gap,
):
    root = production_root(monkeypatch, tmp_path)
    values = bind_ready_projections(monkeypatch, root)
    mutation(values["pim"])

    result = run(root)

    assert result["status"] == "blocked"
    assert result["experiments"] == []
    assert gap in result["source_gaps"]
