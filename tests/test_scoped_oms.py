from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import OrderStatus
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceService,
)
from apps.control_plane.facts import FactRecordRow
from apps.control_plane.scoped_oms import ScopedOmsWorkspace
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base, OrderRow, ProductRow

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
        "authority_sha256": scope["scope_grant_authority_sha256"],
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
    external_id,
    product_id,
    sku,
    status,
    quantity,
    scope,
    at,
    order_external_id=None,
):
    content = f"{fact_id}:{status}:{quantity}".encode()
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
    payload = {
        "external_id": external_id,
        "store_ref": scope["store_ref"],
        "sku": sku,
        "status": status,
        "quantity": str(quantity),
        "effective_at": at.isoformat(),
    }
    if fact_type == "ozon_order":
        payload.update({"currency": "RUB", "gross_revenue": "1000.00"})
    else:
        payload.update(
            {
                "order_external_id": order_external_id,
                "currency": "RUB",
                "amount": "100.00",
                "return_reason": "buyer_return",
            }
        )
    with Session(engine) as session, session.begin():
        session.add(
            FactRecordRow(
                id=fact_id,
                source="ozon_official_export",
                fact_type=fact_type,
                natural_key=external_id,
                contract_version="ozon-v1",
                payload_json=payload,
                payload_hash=hashlib.sha256(
                    json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
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


def test_missing_entity_scope_and_legacy_order_remain_no_data():
    engine = database()
    evidence = EvidenceService(engine)
    base = datetime(2026, 7, 29, 1, tzinfo=UTC)
    add_product(
        engine,
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base,
    )
    with Session(engine) as session, session.begin():
        session.add(
            OrderRow(
                id="legacy-order",
                external_id="legacy-external",
                product_id="prd-a",
                quantity=99,
                currency="RUB",
                gross_revenue_decimal="99999",
                booked_fx_rate_decimal="0.08",
                status=OrderStatus.CREATED.value,
                created_at=base,
            )
        )

    result = ScopedOmsWorkspace(
        engine=engine,
        evidence=evidence,
    ).workspace(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "reason": "entity_scope_authority_missing",
        },
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
    )

    assert result["status"] == "no_data"
    assert result["scope"]["entity_ref"] is None
    assert result["counts"]["legacy_orders_read"] == 0
    assert result["orders"] == []
    assert result["control_envelope"]["scoped_input_read"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_current_state_timeline_return_link_and_cross_tenant_isolation():
    engine = database()
    evidence = EvidenceService(engine)
    base = datetime(2026, 7, 29, 1, tzinfo=UTC)
    add_product(
        engine,
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base,
    )
    add_product(
        engine,
        product_id="prd-b",
        sku="SKU-B",
        scope=SCOPE_B,
        at=base,
    )
    add_fact(
        engine,
        evidence,
        fact_id="fact-order-created",
        fact_type="ozon_order",
        external_id="order-a",
        product_id="prd-a",
        sku="SKU-A",
        status="awaiting_packaging",
        quantity=2,
        scope=SCOPE_A,
        at=base + timedelta(minutes=10),
    )
    add_fact(
        engine,
        evidence,
        fact_id="fact-order-delivered",
        fact_type="ozon_order",
        external_id="order-a",
        product_id="prd-a",
        sku="SKU-A",
        status="delivered",
        quantity=2,
        scope=SCOPE_A,
        at=base + timedelta(minutes=20),
    )
    add_fact(
        engine,
        evidence,
        fact_id="fact-return",
        fact_type="ozon_return",
        external_id="return-a",
        order_external_id="order-a",
        product_id="prd-a",
        sku="SKU-A",
        status="returned",
        quantity=1,
        scope=SCOPE_A,
        at=base + timedelta(minutes=30),
    )
    add_fact(
        engine,
        evidence,
        fact_id="fact-other-tenant",
        fact_type="ozon_order",
        external_id="order-b",
        product_id="prd-b",
        sku="SKU-B",
        status="awaiting_packaging",
        quantity=99,
        scope=SCOPE_B,
        at=base + timedelta(minutes=15),
    )

    result = ScopedOmsWorkspace(
        engine=engine,
        evidence=evidence,
    ).workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
    )

    assert result["status"] == "ready"
    assert result["counts"] == {
        "raw_order_facts": 2,
        "raw_return_facts": 1,
        "valid_timeline_events": 3,
        "total_current_orders": 1,
        "page_current_orders": 1,
        "blocked_current_orders": 0,
        "invalid_facts": 0,
        "legacy_orders_read": 0,
    }
    order = result["orders"][0]
    assert order["external_id"] == "order-a"
    assert order["current_state"] == "returned"
    assert order["fact_ids"] == [
        "fact-order-created",
        "fact-order-delivered",
        "fact-return",
    ]
    assert [item["canonical_status"] for item in order["timeline"]] == [
        "awaiting_packaging",
        "delivered",
        "returned",
    ]
    assert result["agent_support"]["authority"] == (
        "decision_support_only"
    )
    assert result["agent_support"]["automatic_actions"] == []
    assert result["control_envelope"]["supplier_order_created"] is False
    assert result["control_envelope"]["customer_message_sent"] is False


def test_as_of_is_deterministic_and_excludes_future_return():
    engine = database()
    evidence = EvidenceService(engine)
    base = datetime(2026, 7, 29, 1, tzinfo=UTC)
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
        fact_id="fact-order",
        fact_type="ozon_order",
        external_id="order-a",
        product_id="prd-a",
        sku="SKU-A",
        status="delivered",
        quantity=1,
        scope=SCOPE_A,
        at=base + timedelta(minutes=10),
    )
    add_fact(
        engine,
        evidence,
        fact_id="future-return",
        fact_type="ozon_return",
        external_id="return-a",
        order_external_id="order-a",
        product_id="prd-a",
        sku="SKU-A",
        status="returned",
        quantity=1,
        scope=SCOPE_A,
        at=base + timedelta(hours=2),
    )
    workspace = ScopedOmsWorkspace(engine=engine, evidence=evidence)
    cutoff = base + timedelta(hours=1)

    first = workspace.workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=cutoff,
    )
    replay = workspace.workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=cutoff,
    )

    assert first["orders"][0]["current_state"] == "delivered"
    assert first["counts"]["raw_return_facts"] == 0
    assert first["snapshot_sha256"] == replay["snapshot_sha256"]
    assert first["agent_support"]["input_snapshot_sha256"] == (
        replay["agent_support"]["input_snapshot_sha256"]
    )


def test_bad_evidence_and_unknown_status_are_partial_not_inferred():
    engine = database()
    evidence = EvidenceService(engine)
    base = datetime(2026, 7, 29, 1, tzinfo=UTC)
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
        fact_id="unknown-status",
        fact_type="ozon_order",
        external_id="order-unknown",
        product_id="prd-a",
        sku="SKU-A",
        status="platform_future_state",
        quantity=1,
        scope=SCOPE_A,
        at=base + timedelta(minutes=10),
    )
    evidence_id = add_fact(
        engine,
        evidence,
        fact_id="bad-evidence",
        fact_type="ozon_order",
        external_id="order-bad",
        product_id="prd-a",
        sku="SKU-A",
        status="awaiting_packaging",
        quantity=1,
        scope=SCOPE_A,
        at=base + timedelta(minutes=20),
    )
    with Session(engine) as session, session.begin():
        record = evidence.get(evidence_id)
        blob = session.get(EvidenceBlobRow, record.sha256)
        assert blob is not None
        blob.content_bytes = b"corrupt"

    result = ScopedOmsWorkspace(
        engine=engine,
        evidence=evidence,
    ).workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
    )

    assert result["status"] == "partial"
    assert result["orders"][0]["current_state"] == "unknown"
    assert result["invalid_fact_ids"] == ["bad-evidence"]
    assert result["source_gaps"] == [
        "oms_fact_evidence_invalid",
        "unknown_order_lifecycle_status",
    ]
    assert result["agent_support"]["suggestions"][0][
        "external_action_allowed"
    ] is False


def test_invalid_latest_fact_blocks_order_instead_of_reusing_prior_state():
    engine = database()
    evidence = EvidenceService(engine)
    base = datetime(2026, 7, 29, 1, tzinfo=UTC)
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
        fact_id="valid-prior",
        fact_type="ozon_order",
        external_id="order-a",
        product_id="prd-a",
        sku="SKU-A",
        status="awaiting_packaging",
        quantity=1,
        scope=SCOPE_A,
        at=base + timedelta(minutes=10),
    )
    evidence_id = add_fact(
        engine,
        evidence,
        fact_id="invalid-latest",
        fact_type="ozon_order",
        external_id="order-a",
        product_id="prd-a",
        sku="SKU-A",
        status="delivered",
        quantity=1,
        scope=SCOPE_A,
        at=base + timedelta(minutes=20),
    )
    with Session(engine) as session, session.begin():
        record = evidence.get(evidence_id)
        blob = session.get(EvidenceBlobRow, record.sha256)
        assert blob is not None
        blob.content_bytes = b"corrupt-latest"

    result = ScopedOmsWorkspace(
        engine=engine,
        evidence=evidence,
    ).workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
    )

    assert result["status"] == "blocked"
    assert result["counts"]["blocked_current_orders"] == 1
    order = result["orders"][0]
    assert order["current_state"] == "unknown"
    assert order["projection_status"] == "blocked"
    assert order["current_event"]["fact_id"] == "invalid-latest"
    assert order["current_event"]["validation_status"] == "blocked"
    assert order["timeline"][0]["canonical_status"] == (
        "awaiting_packaging"
    )
    assert order["owner"] == "evidence-governance"
    assert result["control_envelope"]["external_write_allowed"] is False


def test_cursor_uses_full_sort_key_without_skipping_equal_timestamps():
    engine = database()
    evidence = EvidenceService(engine)
    base = datetime(2026, 7, 29, 1, tzinfo=UTC)
    add_product(
        engine,
        product_id="prd-a",
        sku="SKU-A",
        scope=SCOPE_A,
        at=base,
    )
    for order_id in ("order-a", "order-b"):
        add_fact(
            engine,
            evidence,
            fact_id=f"fact-{order_id}",
            fact_type="ozon_order",
            external_id=order_id,
            product_id="prd-a",
            sku="SKU-A",
            status="awaiting_packaging",
            quantity=1,
            scope=SCOPE_A,
            at=base + timedelta(minutes=10),
        )
    workspace = ScopedOmsWorkspace(engine=engine, evidence=evidence)

    first = workspace.workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
        page_size=1,
    )
    second = workspace.workspace(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=base + timedelta(hours=1),
        page_size=1,
        cursor=first["query"]["next_cursor"],
    )

    assert first["counts"]["total_current_orders"] == 2
    assert first["counts"]["page_current_orders"] == 1
    assert first["query"]["next_cursor"]
    assert {
        first["orders"][0]["external_id"],
        second["orders"][0]["external_id"],
    } == {"order-a", "order-b"}
    assert second["query"]["next_cursor"] is None
    with pytest.raises(ValueError, match="cursor is invalid"):
        workspace.workspace(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="ozon-primary",
            as_of=base + timedelta(hours=1),
            cursor="not-a-valid-cursor",
        )


def test_store_scope_and_input_validation_fail_closed():
    engine = database()
    workspace = ScopedOmsWorkspace(
        engine=engine,
        evidence=EvidenceService(engine),
    )
    base = datetime(2026, 7, 29, 1, tzinfo=UTC)

    with pytest.raises(PermissionError, match="not authorized"):
        workspace.workspace(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="other-store",
            as_of=base,
        )
    with pytest.raises(ValueError, match="page_size"):
        workspace.workspace(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="ozon-primary",
            as_of=base,
            page_size=0,
        )
