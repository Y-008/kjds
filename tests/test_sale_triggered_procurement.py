from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.batch_opportunity import BatchOpportunityWorkspace
from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceService,
)
from apps.control_plane.facts import FactRecordRow
from apps.control_plane.sale_triggered_procurement import (
    PROCUREMENT_POLICY_VERSION,
    SaleTriggeredProcurementPolicy,
)
from apps.control_plane.sql_repository import Base, ProductRow
from scripts.seed_bas140_agent_graph import (
    EDGE_SPECS,
    NODE_SPECS,
    POLICY_VERSION,
    TASK_SPECS,
)

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


class LegacyFacts:
    def __init__(self, rows=None) -> None:
        self.rows = list(rows or [])

    def list(self, *, fact_type=None, limit=100):
        return [
            row
            for row in self.rows
            if fact_type is None or row.fact_type == fact_type
        ][:limit]


class TaskLedger:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ensure_internal_task(self, **values):
        self.calls.append(values)
        return {
            "id": f"tsk-{len(self.calls)}",
            "status": "open",
            "owner": values["owner"],
        }


def database():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def add_product(
    engine,
    *,
    product_id: str,
    sku: str,
    scope: dict[str, str],
    at: datetime,
) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            ProductRow(
                id=product_id,
                sku=sku,
                name=f"Product {sku}",
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
                created_by="operator",
            )
        )


def add_order_fact(
    engine,
    evidence: EvidenceService,
    *,
    fact_id: str,
    product_id: str,
    external_id: str,
    status: str,
    quantity: str,
    scope: dict[str, str],
    effective_at: datetime,
    recorded_at: datetime | None = None,
    gross_revenue: str = "1000.00",
    currency: str = "RUB",
    sku: str = "SKU-A",
    scope_as_of: datetime | None = None,
) -> str:
    record = evidence.capture(
        content=f"{fact_id}:{status}:{quantity}".encode(),
        filename=f"{fact_id}.json",
        content_type="application/json",
        source="ozon_official_export",
        source_ref=f"ozon-order://{fact_id}",
        grade=EvidenceGrade.A,
        effective_at=effective_at.isoformat(),
        effective_until=None,
        created_by="independent-reviewer",
        metadata={"retention_class": "financial"},
    )
    payload = {
        "external_id": external_id,
        "store_ref": scope["store_ref"],
        "sku": sku,
        "status": status,
        "quantity": quantity,
        "gross_revenue": gross_revenue,
        "currency": currency,
        "effective_at": effective_at.isoformat(),
    }
    with Session(engine) as session, session.begin():
        session.add(
            FactRecordRow(
                id=fact_id,
                source="ozon_official_export",
                fact_type="ozon_order",
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
                effective_at=effective_at,
                recorded_at=recorded_at or effective_at,
                evidence_id=record.id,
                import_row_id=f"import-row-{fact_id}",
                product_id=product_id,
                resolution_status="resolved",
                created_by="operator",
                tenant_ref=scope["tenant_ref"],
                entity_ref=scope["entity_ref"],
                store_ref=scope["store_ref"],
                scope_grant_authority_sha256=scope[
                    "scope_grant_authority_sha256"
                ],
                source_evidence_sha256=record.sha256,
                scope_as_of=scope_as_of or effective_at,
            )
        )
    return record.id


def policy(engine, evidence):
    return SaleTriggeredProcurementPolicy(
        facts=LegacyFacts(),
        evidence=evidence,
        repository=SimpleNamespace(),
        engine=engine,
    )


def evaluate(
    policy_value,
    *,
    product_id="prd-a",
    scope=SCOPE_A,
    as_of: datetime,
    supply_ready=True,
    economics_ready=True,
):
    return policy_value.evaluate(
        store_ref="ozon-primary",
        product_id=product_id,
        scope_authority=scope,
        supply={
            "checkout_verified": supply_ready,
            "purchase_available": supply_ready,
        },
        economics={
            "cost_evidence_complete": economics_ready,
            "downside": {
                "cm3_cny": "12.34" if economics_ready else None
            },
        },
        fresh=True,
        as_of=as_of,
    )


def test_scoped_current_orders_supersede_cancelled_and_sum_distinct_orders():
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
        sku="SKU-A",
        scope=SCOPE_B,
        at=base,
    )
    add_order_fact(
        engine,
        evidence,
        fact_id="fact-a1-old",
        product_id="prd-a",
        external_id="order-a1",
        status="awaiting_packaging",
        quantity="2",
        scope=SCOPE_A,
        effective_at=base + timedelta(minutes=10),
    )
    add_order_fact(
        engine,
        evidence,
        fact_id="fact-a1-current",
        product_id="prd-a",
        external_id="order-a1",
        status="cancelled",
        quantity="2",
        scope=SCOPE_A,
        effective_at=base + timedelta(minutes=20),
    )
    evidence_a2 = add_order_fact(
        engine,
        evidence,
        fact_id="fact-a2",
        product_id="prd-a",
        external_id="order-a2",
        status="awaiting_packaging",
        quantity="3",
        scope=SCOPE_A,
        effective_at=base + timedelta(minutes=15),
    )
    add_order_fact(
        engine,
        evidence,
        fact_id="fact-b1",
        product_id="prd-b",
        external_id="order-b1",
        status="awaiting_packaging",
        quantity="99",
        scope=SCOPE_B,
        effective_at=base + timedelta(minutes=15),
    )

    result = evaluate(
        policy(engine, evidence),
        as_of=base + timedelta(hours=1),
    )

    assert result["version"] == PROCUREMENT_POLICY_VERSION
    assert result["state"] == "eligible_for_procurement_review"
    assert result["scope_mode"] == "native_scoped"
    assert result["formal_order_fact_count"] == 3
    assert result["current_order_fact_count"] == 2
    assert result["triggering_order_count"] == 1
    assert result["trigger_fact_ids"] == ["fact-a2"]
    assert result["trigger_evidence_ids"] == [evidence_a2]
    assert result["trigger_order_external_ids"] == ["order-a2"]
    assert result["recommended_review_quantity"] == 3
    assert result["supplier_order_created"] is False
    assert result["payment_created"] is False
    assert result["automatic_procurement"] is False
    assert result["external_purchase_write"] is False
    assert len(result["snapshot_sha256"]) == 64


def test_distinct_current_orders_sum_units_without_replay_duplication():
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
    for fact_id, external_id, quantity, minute in (
        ("fact-a1-old", "order-a1", "1", 10),
        ("fact-a1-current", "order-a1", "2", 20),
        ("fact-a2", "order-a2", "3", 15),
    ):
        add_order_fact(
            engine,
            evidence,
            fact_id=fact_id,
            product_id="prd-a",
            external_id=external_id,
            status="awaiting_packaging",
            quantity=quantity,
            scope=SCOPE_A,
            effective_at=base + timedelta(minutes=minute),
        )

    result = evaluate(
        policy(engine, evidence),
        as_of=base + timedelta(hours=1),
    )

    assert result["trigger_order_external_ids"] == [
        "order-a1",
        "order-a2",
    ]
    assert result["triggering_order_count"] == 2
    assert result["recommended_review_quantity"] == 5


def test_scoped_evaluation_never_falls_back_to_legacy_or_another_grant():
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
    legacy = SimpleNamespace(
        id="legacy-fact",
        fact_type="ozon_order",
        product_id="prd-a",
        resolution_status="resolved",
        effective_at=(base + timedelta(minutes=10)).isoformat(),
        recorded_at=(base + timedelta(minutes=10)).isoformat(),
        evidence_id="legacy-evidence",
        payload={
            "external_id": "legacy-order",
            "store_ref": "ozon-primary",
            "sku": "SKU-A",
            "status": "awaiting_packaging",
            "quantity": "9",
            "gross_revenue": "9000",
            "currency": "RUB",
        },
    )
    service = SaleTriggeredProcurementPolicy(
        facts=LegacyFacts([legacy]),
        evidence=evidence,
        repository=SimpleNamespace(),
        engine=engine,
    )

    exact = evaluate(
        service,
        as_of=base + timedelta(hours=1),
    )
    wrong_grant = evaluate(
        service,
        scope={**SCOPE_A, "scope_grant_authority_sha256": "c" * 64},
        as_of=base + timedelta(hours=1),
    )

    assert exact["state"] == "waiting_for_ozon_order"
    assert exact["formal_order_fact_count"] == 0
    assert wrong_grant["state"] == "waiting_for_ozon_order"
    assert wrong_grant["source_gaps"] == [
        "scoped_canonical_product_missing"
    ]


def test_as_of_and_evidence_integrity_fail_closed():
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
    add_order_fact(
        engine,
        evidence,
        fact_id="future-fact",
        product_id="prd-a",
        external_id="future-order",
        status="awaiting_packaging",
        quantity="1",
        scope=SCOPE_A,
        effective_at=base + timedelta(hours=2),
    )
    evidence_id = add_order_fact(
        engine,
        evidence,
        fact_id="bad-evidence-fact",
        product_id="prd-a",
        external_id="bad-evidence-order",
        status="awaiting_packaging",
        quantity="1",
        scope=SCOPE_A,
        effective_at=base + timedelta(minutes=10),
    )
    with Session(engine) as session, session.begin():
        record = evidence.get(evidence_id)
        blob = session.get(EvidenceBlobRow, record.sha256)
        assert blob is not None
        blob.content_bytes = b"corrupt"

    at_cutoff = evaluate(
        policy(engine, evidence),
        as_of=base + timedelta(hours=1),
    )

    assert at_cutoff["formal_order_fact_count"] == 1
    assert at_cutoff["state"] == "blocked_order_authority"
    assert at_cutoff["blockers"] == ["order_evidence_invalid"]
    assert at_cutoff["recommended_review_quantity"] == 0


@pytest.mark.parametrize(
    ("fact_overrides", "expected_blocker"),
    [
        ({"sku": "SKU-WRONG"}, "order_sku_mismatch"),
        ({"quantity": "1.5"}, "order_quantity_invalid"),
        ({"gross_revenue": "0"}, "order_revenue_not_positive"),
        ({"currency": "rub"}, "order_currency_missing_or_invalid"),
    ],
)
def test_order_semantics_fail_closed(
    fact_overrides,
    expected_blocker,
):
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
    fact_values = {
        "quantity": "1",
        "gross_revenue": "1000.00",
        "currency": "RUB",
        "sku": "SKU-A",
        **fact_overrides,
    }
    add_order_fact(
        engine,
        evidence,
        fact_id="invalid-order-fact",
        product_id="prd-a",
        external_id="invalid-order",
        status="awaiting_packaging",
        scope=SCOPE_A,
        effective_at=base + timedelta(minutes=10),
        **fact_values,
    )

    result = evaluate(
        policy(engine, evidence),
        as_of=base + timedelta(hours=1),
    )

    assert result["state"] == "blocked_order_authority"
    assert result["blockers"] == [expected_blocker]
    assert result["recommended_review_quantity"] == 0
    assert result["supplier_order_created"] is False
    assert result["payment_created"] is False
    assert result["external_purchase_write"] is False


def test_order_task_handoff_reuses_existing_internal_task_ledger():
    tasks = TaskLedger()
    workspace = object.__new__(BatchOpportunityWorkspace)
    workspace.operating_tasks = tasks
    candidate = {
        "canonical_product_id": "prd-a",
        "sale_triggered_procurement": {
            "state": "eligible_for_procurement_review",
            "trigger_order_external_ids": ["order-2", "order-1"],
            "trigger_fact_ids": ["fact-2", "fact-1"],
            "trigger_evidence_ids": ["evd-2", "evd-1"],
            "recommended_review_quantity": 2,
            "blockers": [],
            "next_action": "独立采购复核",
        },
    }

    projected = workspace._project_procurement_tasks(
        candidates=[candidate],
        scope_authority=SCOPE_A,
        store_ref="ozon-primary",
        actor_id="operator-a",
        as_of=datetime(2026, 7, 29, 2, tzinfo=UTC),
    )

    assert len(projected) == 1
    assert projected[0]["task_kind"] == (
        "sale_triggered_procurement_review"
    )
    assert tasks.calls[0]["scope"]["tenant_ref"] == "tenant-a"
    assert tasks.calls[0]["scope"]["order_set_sha256"] == hashlib.sha256(
        json.dumps(
            ["order-1", "order-2"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    snapshot = tasks.calls[0]["snapshot"]
    assert snapshot["supplier_order_created"] is False
    assert snapshot["payment_created"] is False
    assert snapshot["approval_created"] is False
    assert snapshot["permit_created"] is False
    assert snapshot["external_purchase_write"] is False
    assert candidate["sale_triggered_procurement"]["operating_task"]["id"] == (
        "tsk-1"
    )


def test_bas140_graph_contract_is_verifier_owned_and_dependency_ordered():
    task_ids = [item[0] for item in TASK_SPECS]
    node_keys = [item[1] for item in NODE_SPECS]
    bound_tasks = {item[5] for item in NODE_SPECS}

    assert POLICY_VERSION == PROCUREMENT_POLICY_VERSION
    assert task_ids == [
        "task-bas140-pytest",
        "task-bas140-database",
        "task-bas140-runtime",
        "task-bas140-evidence",
    ]
    assert TASK_SPECS[0][3] == ("task-bas124-evidence",)
    assert all(
        task[3] == (task_ids[index - 1],)
        for index, task in enumerate(TASK_SPECS[1:], start=1)
    )
    assert len(node_keys) == len(set(node_keys))
    assert bound_tasks == set(task_ids)
    assert EDGE_SPECS[0][:3] == (
        "requirement:BR-114@master-8.42",
        "specified_by",
        "adr:ADR-0060",
    )
    assert EDGE_SPECS[-1][:3] == (
        "evidence:BAS-140",
        "closes",
        "plan:BAS-140@plan-9.32",
    )
