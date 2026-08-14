from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.facts import FactRecordRow
from apps.control_plane.ozon_contracts import (
    OzonRecordType,
    natural_key,
)
from apps.control_plane.scoped_inventory import (
    ScopedInventoryFulfillmentWorkspace,
)
from apps.control_plane.scoped_oms import ScopedOmsWorkspace
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base, ProductRow

SCOPE_A = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": "a" * 64,
}
SCOPE_B = {
    "tenant_ref": "tenant-b",
    "entity_ref": "entity-b",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": "b" * 64,
}


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def principal(scope=SCOPE_A):
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref=scope["tenant_ref"],
        store_refs=frozenset({scope["store_ref"]}),
    )


def entity_scope(scope=SCOPE_A):
    return {
        "status": "ready",
        "entity_ref": scope["entity_ref"],
        "authority_sha256": scope[
            "scope_grant_authority_sha256"
        ],
    }


def add_product(engine, *, product_id, sku, scope, at):
    with Session(engine) as session, session.begin():
        session.add(
            ProductRow(
                id=product_id,
                sku=sku,
                name=sku,
                market="RU",
                channel="OZON",
                status="active",
                created_at=at,
                tenant_ref=scope["tenant_ref"],
                entity_ref=scope["entity_ref"],
                store_ref=scope["store_ref"],
                scope_grant_authority_sha256=scope[
                    "scope_grant_authority_sha256"
                ],
                scope_as_of=at,
                created_by="operator-a",
            )
        )


def add_fact(
    engine,
    evidence,
    *,
    fact_id,
    fact_type,
    product_id,
    sku,
    scope,
    at,
    payload,
    corrupt_hash=False,
):
    content = f"{fact_id}:{fact_type}".encode()
    record = evidence.capture(
        content=content,
        filename=f"{fact_id}.json",
        content_type="application/json",
        source="ozon_official_export",
        source_ref=f"ozon-fact://{fact_id}",
        grade=EvidenceGrade.A,
        effective_at=at.isoformat(),
        effective_until=None,
        created_by="independent-reviewer",
        metadata={"retention_class": "financial"},
    )
    normalized = {
        **payload,
        "sku": sku,
        "store_ref": scope["store_ref"],
        "effective_at": at.isoformat(),
    }
    record_type = OzonRecordType(fact_type)
    key = natural_key(record_type, normalized)
    payload_hash = hashlib.sha256(
        json.dumps(
            normalized,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with Session(engine) as session, session.begin():
        session.add(
            FactRecordRow(
                id=fact_id,
                source="ozon_official_export",
                fact_type=fact_type,
                natural_key=key,
                contract_version="ozon-v1",
                payload_json=normalized,
                payload_hash=(
                    "f" * 64 if corrupt_hash else payload_hash
                ),
                effective_at=at,
                recorded_at=at,
                evidence_id=record.id,
                import_row_id=f"import-{fact_id}",
                product_id=product_id,
                resolution_status="resolved",
                created_by="operator-a",
                tenant_ref=scope["tenant_ref"],
                entity_ref=scope["entity_ref"],
                store_ref=scope["store_ref"],
                scope_grant_authority_sha256=scope[
                    "scope_grant_authority_sha256"
                ],
                source_evidence_sha256=record.sha256,
                scope_as_of=at,
            )
        )
    return record.id


def inventory_payload(
    *,
    external_id,
    warehouse_ref="warehouse-cn-1",
    fulfillment_mode="realFBS",
    available=5,
    reserved=1,
    cluster_ref="cn-east",
):
    return {
        "external_id": external_id,
        "warehouse_ref": warehouse_ref,
        "cluster_ref": cluster_ref,
        "fulfillment_mode": fulfillment_mode,
        "available_quantity": str(available),
        "reserved_quantity": str(reserved),
        "in_transit_quantity": "0",
        "damaged_quantity": "0",
        "quarantine_quantity": "0",
    }


def order_payload(*, external_id, status, quantity):
    return {
        "external_id": external_id,
        "status": status,
        "quantity": str(quantity),
        "currency": "RUB",
        "gross_revenue": "1000.00",
    }


def workspace(engine, evidence):
    oms = ScopedOmsWorkspace(engine=engine, evidence=evidence)
    return ScopedInventoryFulfillmentWorkspace(
        engine=engine,
        evidence=evidence,
        oms=oms,
    )


def test_missing_entity_scope_is_no_data_and_never_infers_inventory():
    engine = database()
    evidence = EvidenceService(engine)
    cutoff = datetime.now(UTC) - timedelta(hours=1)

    result = workspace(engine, evidence).workspace(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "reason": "entity_scope_authority_missing",
        },
        store_ref="ozon-primary",
        as_of=cutoff,
    )

    assert result["status"] == "no_data"
    assert result["scope"]["entity_ref"] is None
    assert result["counts"]["legacy_inventory_rows_read"] == 0
    assert result["counts"]["marketplace_observations_inferred"] == 0
    assert result["control_envelope"]["external_write_allowed"] is False
    assert result["blockers"][0]["next_workspace"] == "/scope-authority"


def test_exact_inventory_and_oms_demand_produce_server_coverage():
    engine = database()
    evidence = EvidenceService(engine)
    base = datetime.now(UTC) - timedelta(days=1)
    add_product(
        engine,
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base,
    )
    add_fact(
        engine,
        evidence,
        fact_id="fact-inventory-a",
        fact_type="ozon_inventory",
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base + timedelta(minutes=1),
        payload=inventory_payload(
            external_id="inventory-a",
            available=5,
        ),
    )
    add_fact(
        engine,
        evidence,
        fact_id="fact-order-a",
        fact_type="ozon_order",
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base + timedelta(minutes=2),
        payload=order_payload(
            external_id="order-a",
            status="awaiting_packaging",
            quantity=3,
        ),
    )

    result = workspace(engine, evidence).workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
    )

    assert result["status"] == "ready"
    assert result["counts"]["total_current_cells"] == 1
    assert result["order_demand"]["demand_by_sku"] == {"SKU-A": 3}
    summary = result["sku_summaries"][0]
    assert summary["available_quantity"] == 5
    assert summary["open_order_demand_quantity"] == 3
    assert summary["shortage_quantity"] == 0
    assert summary["coverage_status"] == "covered"
    assert result["control_envelope"]["reservation_created"] is False
    assert result["agent_support"]["automatic_actions"] == []


def test_shortage_is_internal_advice_and_cross_tenant_stock_is_excluded():
    engine = database()
    evidence = EvidenceService(engine)
    base = datetime.now(UTC) - timedelta(days=1)
    for product_id, sku, scope in (
        ("prd-a", "SKU-A", SCOPE_A),
        ("prd-b", "SKU-B", SCOPE_B),
    ):
        add_product(
            engine,
            product_id=product_id,
            sku=sku,
            scope=scope,
            at=base,
        )
        add_fact(
            engine,
            evidence,
            fact_id=f"fact-inventory-{product_id}",
            fact_type="ozon_inventory",
            product_id=product_id,
            sku=sku,
            scope=scope,
            at=base + timedelta(minutes=1),
            payload=inventory_payload(
                external_id=f"inventory-{product_id}",
                available=1,
            ),
        )
    add_fact(
        engine,
        evidence,
        fact_id="fact-order-a",
        fact_type="ozon_order",
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base + timedelta(minutes=2),
        payload=order_payload(
            external_id="order-a",
            status="paid",
            quantity=3,
        ),
    )

    result = workspace(engine, evidence).workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
    )

    assert {item["sku"] for item in result["sku_summaries"]} == {
        "SKU-A"
    }
    assert result["sku_summaries"][0]["shortage_quantity"] == 2
    suggestion = result["agent_support"]["suggestions"][0]
    assert suggestion["supplier_order_allowed"] is False
    assert suggestion["external_action_allowed"] is False


def test_bad_latest_inventory_fact_blocks_cell_without_reusing_old_stock():
    engine = database()
    evidence = EvidenceService(engine)
    base = datetime.now(UTC) - timedelta(days=1)
    add_product(
        engine,
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base,
    )
    add_fact(
        engine,
        evidence,
        fact_id="fact-inventory-valid",
        fact_type="ozon_inventory",
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base + timedelta(minutes=1),
        payload=inventory_payload(
            external_id="inventory-old",
            available=8,
        ),
    )
    add_fact(
        engine,
        evidence,
        fact_id="fact-inventory-bad",
        fact_type="ozon_inventory",
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base + timedelta(minutes=2),
        payload=inventory_payload(
            external_id="inventory-new",
            available=99,
        ),
        corrupt_hash=True,
    )

    result = workspace(engine, evidence).workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
    )

    assert result["status"] == "blocked"
    cell = result["inventory_cells"][0]
    assert cell["projection_status"] == "blocked"
    assert cell["last_valid_snapshot"]["quantities"][
        "available_quantity"
    ] == 8
    assert cell["current_snapshot"]["fact_id"] == "fact-inventory-bad"
    assert result["sku_summaries"] == []


def test_as_of_cursor_and_bad_scope_fail_closed():
    engine = database()
    evidence = EvidenceService(engine)
    base = datetime.now(UTC) - timedelta(days=1)
    add_product(
        engine,
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base,
    )
    for offset, warehouse in enumerate(
        ("warehouse-1", "warehouse-2", "warehouse-3"),
        start=1,
    ):
        add_fact(
            engine,
            evidence,
            fact_id=f"fact-{offset}",
            fact_type="ozon_inventory",
            product_id="prd-a",
            sku="SKU-A",
            scope=SCOPE_A,
            at=base + timedelta(minutes=offset),
            payload=inventory_payload(
                external_id=f"inventory-{offset}",
                warehouse_ref=warehouse,
            ),
        )
    authority = workspace(engine, evidence)
    first = authority.workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
        page_size=2,
    )
    second = authority.workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
        page_size=2,
        cursor=first["query"]["next_cursor"],
    )

    assert len(first["inventory_cells"]) == 2
    assert len(second["inventory_cells"]) == 1
    assert {
        item["cell_key"]
        for item in first["inventory_cells"]
    }.isdisjoint(
        {
            item["cell_key"]
            for item in second["inventory_cells"]
        }
    )
    with pytest.raises(PermissionError):
        authority.workspace(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="not-authorized",
            as_of=base + timedelta(hours=1),
        )
