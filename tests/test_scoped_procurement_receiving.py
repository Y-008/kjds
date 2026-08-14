from __future__ import annotations

import copy
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import ApprovalStatus
from apps.control_plane.procurement import (
    ProcurementService,
    SampleProcurementEventRow,
    SamplePurchaseOrderRow,
)
from apps.control_plane.scoped_procurement_receiving import (
    ScopedProcurementReceivingWorkspace,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base, ProductRow

AS_OF = "2026-07-29T12:00:00+00:00"
AUTHORITY = "a" * 64
EVIDENCE_SHA = "e" * 64
ENTITY_SCOPE = {
    "status": "ready",
    "entity_ref": "entity-cn-1",
    "authority_sha256": AUTHORITY,
}


def principal(
    *,
    tenant_ref: str = "tenant-cn-1",
    stores: frozenset[str] = frozenset({"store-cn-1"}),
) -> Principal:
    return Principal(
        actor_id="procurement-operator",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=stores,
    )


class FakeProcurement:
    def __init__(self, source: dict) -> None:
        self.source = source
        self.calls = 0

    def read_scoped_sources(self, **_values):
        self.calls += 1
        return copy.deepcopy(self.source)


class MustNotRead:
    calls = 0

    def read_scoped_sources(self, **_values):
        self.calls += 1
        raise AssertionError("procurement source must not be read")


class FakeRepository:
    def __init__(self, approvals: dict[str, object]) -> None:
        self.approvals = approvals

    def get_approval_at(self, approval_id: str, **_values):
        return self.approvals[approval_id]


class FakeSourcingStore:
    def __init__(
        self,
        *,
        offers: dict[str, object],
        scenarios: dict[str, object],
    ) -> None:
        self.offers = offers
        self.scenarios = scenarios

    def get_offer(self, offer_id: str):
        return self.offers[offer_id]

    def get_scenario(self, scenario_id: str):
        return self.scenarios[scenario_id]


class FakeEvidence:
    def __init__(self, *, invalid_ids: set[str] | None = None) -> None:
        self.invalid_ids = invalid_ids or set()

    def verify(self, evidence_id: str):
        return SimpleNamespace(
            valid=evidence_id not in self.invalid_ids,
            expected_sha256=EVIDENCE_SHA,
        )


class FakeScopedEvidence:
    def project_targets(self, *, evidence_ids: list[str], **_values):
        return {
            "status": "ready",
            "records": [
                {"id": evidence_id, "status": "ready"}
                for evidence_id in evidence_ids
            ],
        }


def approval(order_number: int = 1):
    return SimpleNamespace(
        id=f"approval-{order_number}",
        action="procurement.place_order",
        resource_type="profit_scenario",
        resource_id=f"scenario-{order_number}",
        requested_by="operator-a",
        payload={
            "product_id": "product-1",
            "offer_id": f"offer-{order_number}",
            "scenario_id": f"scenario-{order_number}",
            "quantity": 10,
        },
        status=ApprovalStatus.APPROVED,
        decided_by="approver-b",
        created_at="2026-07-20T00:00:00+00:00",
    )


def offer(order_number: int = 1):
    return SimpleNamespace(
        id=f"offer-{order_number}",
        product_id="product-1",
        supplier_ref=f"supplier-{order_number}",
        currency="CNY",
        unit_price=Decimal("12.50"),
        min_order_quantity=5,
        evidence_ref=f"offer-evidence-{order_number}",
        captured_at="2026-07-18T00:00:00+00:00",
    )


def scenario(order_number: int = 1):
    return SimpleNamespace(
        id=f"scenario-{order_number}",
        offer_id=f"offer-{order_number}",
        cm3_cny=Decimal("18.25"),
        cost_complete=True,
        evidence=[f"scenario-evidence-{order_number}"],
        cost_evidence={"purchase": f"cost-evidence-{order_number}"},
        created_at="2026-07-19T00:00:00+00:00",
    )


def scoped_order(order_number: int = 1) -> dict:
    return {
        "id": f"sample-order-{order_number}",
        "approval_id": f"approval-{order_number}",
        "product_id": "product-1",
        "offer_id": f"offer-{order_number}",
        "scenario_id": f"scenario-{order_number}",
        "supplier_ref": f"supplier-{order_number}",
        "quantity": 10,
        "currency": "CNY",
        "unit_price": "12.500000000000",
        "requested_by": "operator-a",
        "created_at": (
            f"2026-07-{20 + order_number:02d}T00:00:00+00:00"
        ),
        "authority_evidence_id": f"order-evidence-{order_number}",
        "source_evidence_sha256": EVIDENCE_SHA,
        "scope_as_of": "2026-07-20T00:00:00+00:00",
    }


def event(
    *,
    order_number: int = 1,
    sequence: int,
    event_type: str,
    facts: dict,
) -> dict:
    return {
        "id": f"event-{order_number}-{sequence}",
        "purchase_order_id": f"sample-order-{order_number}",
        "sequence": sequence,
        "event_type": event_type,
        "effective_at": (
            f"2026-07-{22 + sequence:02d}T00:00:00+00:00"
        ),
        "evidence_id": f"event-evidence-{order_number}-{sequence}",
        "facts": facts,
        "created_by": "receiving-operator",
        "recorded_at": (
            f"2026-07-{22 + sequence:02d}T01:00:00+00:00"
        ),
        "source_evidence_sha256": EVIDENCE_SHA,
        "scope_as_of": "2026-07-20T00:00:00+00:00",
    }


def full_timeline(order_number: int = 1) -> list[dict]:
    return [
        event(
            order_number=order_number,
            sequence=1,
            event_type="order_confirmed",
            facts={
                "supplier_order_ref": f"SUP-{order_number}",
                "promised_delivery_at": "2026-07-27T00:00:00+00:00",
            },
        ),
        event(
            order_number=order_number,
            sequence=2,
            event_type="shipped",
            facts={"tracking_ref": "TRACK-1", "carrier": "carrier-a"},
        ),
        event(
            order_number=order_number,
            sequence=3,
            event_type="received",
            facts={"received_quantity": 10, "damaged_quantity": 1},
        ),
        event(
            order_number=order_number,
            sequence=4,
            event_type="inspection_completed",
            facts={
                "inspected_quantity": 10,
                "passed_quantity": 9,
                "defect_count": 1,
                "result": "passed",
            },
        ),
    ]


def source(
    *,
    orders: list[dict] | None = None,
    events: list[dict] | None = None,
) -> dict:
    payload = {
        "contract_id": "kjds-scoped-procurement-read-source-v1",
        "as_of": AS_OF,
        "scope": {
            "tenant_ref": "tenant-cn-1",
            "entity_ref": "entity-cn-1",
            "store_ref": "store-cn-1",
            "scope_grant_authority_sha256": AUTHORITY,
            "as_of": AS_OF,
            "authority": "native",
        },
        "orders": orders if orders is not None else [scoped_order()],
        "events": events if events is not None else full_timeline(),
        "truncated": {"orders": False, "events": False},
    }
    payload["snapshot_sha256"] = (
        ScopedProcurementReceivingWorkspace._hash(payload)
    )
    return payload


def engine_with_product():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add(
            ProductRow(
                id="product-1",
                sku="SKU-1",
                name="Canonical sample",
                market="RU",
                channel="OZON",
                status="candidate",
                created_at=datetime(2026, 7, 17, tzinfo=UTC),
                tenant_ref="tenant-cn-1",
                entity_ref="entity-cn-1",
                store_ref="store-cn-1",
                scope_grant_authority_sha256=AUTHORITY,
                scope_as_of=datetime(2026, 7, 17, tzinfo=UTC),
                created_by="pim-operator",
            )
        )
    return engine


def workspace(
    *,
    procurement=None,
    invalid_evidence_ids: set[str] | None = None,
    order_numbers: tuple[int, ...] = (1,),
) -> ScopedProcurementReceivingWorkspace:
    return ScopedProcurementReceivingWorkspace(
        engine=engine_with_product(),
        procurement=procurement or FakeProcurement(source()),
        repository=FakeRepository(
            {
                f"approval-{number}": approval(number)
                for number in order_numbers
            }
        ),
        sourcing_store=FakeSourcingStore(
            offers={
                f"offer-{number}": offer(number)
                for number in order_numbers
            },
            scenarios={
                f"scenario-{number}": scenario(number)
                for number in order_numbers
            },
        ),
        evidence=FakeEvidence(invalid_ids=invalid_evidence_ids),
        scoped_evidence=FakeScopedEvidence(),
    )


def project(subject: ScopedProcurementReceivingWorkspace, **values):
    return subject.project(
        principal=principal(),
        entity_scope=ENTITY_SCOPE,
        store_ref="store-cn-1",
        as_of=AS_OF,
        **values,
    )


def test_missing_entity_scope_does_not_read_raw_procurement() -> None:
    source_reader = MustNotRead()
    subject = workspace(procurement=source_reader)
    result = subject.project(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref="store-cn-1",
        as_of=AS_OF,
    )
    assert result["status"] == "no_data"
    assert result["orders"] == []
    assert result["control_envelope"]["scoped_input_read"] is False
    assert source_reader.calls == 0


def test_projects_verified_timeline_and_server_order_value() -> None:
    subject = workspace()
    first = project(subject)
    second = project(subject)
    assert first == second
    assert first["status"] == "ready"
    assert first["counts"]["inspected"] == 1
    row = first["orders"][0]
    assert row["stage"] == "inspected"
    assert row["product"]["sku"] == "SKU-1"
    assert row["order_value"] == "125"
    assert row["receipt"] == {
        "ordered_quantity": 10,
        "received_quantity": 10,
        "damaged_quantity": 1,
        "inspected_quantity": 10,
        "passed_quantity": 9,
        "defect_count": 1,
        "quantity_conserved": True,
    }
    assert row["decision_basis"]["independent_approval"] is True
    assert (
        result := first["financial_authority"]
    )["supplier_payment_authority_available"] is False
    assert result["accounts_payable_invoice_authority_available"] is False
    assert first["control_envelope"]["external_write_allowed"] is False
    assert first["agent_artifact"]["self_approval_allowed"] is False
    assert first["agent_artifact"]["permit_issue_allowed"] is False


def test_latest_bad_event_evidence_fails_closed_without_values() -> None:
    invalid_id = "event-evidence-1-4"
    subject = workspace(invalid_evidence_ids={invalid_id})
    result = project(subject)
    assert result["status"] == "blocked"
    assert result["orders"] == []
    assert (
        result["excluded"]["reason_counts"][
            "procurement_event_evidence_invalid"
        ]
        == 1
    )
    assert result["excluded"]["business_values_exposed"] is False


def test_receiving_quantity_violation_fails_closed() -> None:
    timeline = full_timeline()
    timeline[-1]["facts"]["passed_quantity"] = 8
    reader = FakeProcurement(source(events=timeline))
    result = project(workspace(procurement=reader))
    assert result["status"] == "blocked"
    assert result["orders"] == []
    assert (
        result["excluded"]["reason_counts"][
            "procurement_inspection_quantity_not_conserved"
        ]
        == 1
    )


def test_cross_store_is_forbidden_before_source_read() -> None:
    source_reader = MustNotRead()
    subject = workspace(procurement=source_reader)
    with pytest.raises(PermissionError):
        subject.project(
            principal=principal(),
            entity_scope=ENTITY_SCOPE,
            store_ref="other-store",
            as_of=AS_OF,
        )
    assert source_reader.calls == 0


def test_cursor_and_filters_are_stable() -> None:
    orders = [scoped_order(1), scoped_order(2)]
    reader = FakeProcurement(
        source(
            orders=orders,
            events=[*full_timeline(1), *full_timeline(2)],
        )
    )
    subject = workspace(procurement=reader, order_numbers=(1, 2))
    first = project(subject, page_size=1)
    assert len(first["orders"]) == 1
    assert first["pagination"]["next_cursor"]
    second = project(
        subject,
        page_size=1,
        cursor=first["pagination"]["next_cursor"],
    )
    assert len(second["orders"]) == 1
    assert (
        first["orders"][0]["purchase_order_id"]
        != second["orders"][0]["purchase_order_id"]
    )
    filtered = project(subject, query="supplier-1", stage="inspected")
    assert filtered["counts"]["filtered"] == 1
    assert filtered["orders"][0]["supplier_ref"] == "supplier-1"


@pytest.mark.parametrize(
    "row",
    [
        SamplePurchaseOrderRow(
            id="partial-order",
            approval_id="approval-partial",
            product_id="product-1",
            offer_id="offer-partial",
            scenario_id="scenario-partial",
            supplier_ref="supplier-partial",
            quantity=1,
            currency="CNY",
            unit_price=Decimal("1"),
            requested_by="operator",
            created_at=datetime(2026, 7, 20, tzinfo=UTC),
            tenant_ref="tenant-cn-1",
        ),
        SampleProcurementEventRow(
            id="partial-event",
            purchase_order_id="partial-order",
            sequence=1,
            event_type="cancelled",
            effective_at=datetime(2026, 7, 20, tzinfo=UTC),
            evidence_id="event-evidence",
            facts_json={"reason": "test"},
            created_by="operator",
            recorded_at=datetime(2026, 7, 20, tzinfo=UTC),
            tenant_ref="tenant-cn-1",
        ),
    ],
)
def test_database_rejects_partial_native_scope(row) -> None:
    engine = engine_with_product()
    with (
        pytest.raises(IntegrityError),
        Session(engine) as session,
        session.begin(),
    ):
        session.add(row)
        session.flush()


def test_native_source_read_is_exact_scope_and_deterministic() -> None:
    engine = engine_with_product()
    base = {
        "product_id": "product-1",
        "quantity": 10,
        "currency": "CNY",
        "unit_price": Decimal("12.5"),
        "requested_by": "operator",
        "created_at": datetime(2026, 7, 20, tzinfo=UTC),
    }
    scoped = {
        "tenant_ref": "tenant-cn-1",
        "entity_ref": "entity-cn-1",
        "store_ref": "store-cn-1",
        "scope_grant_authority_sha256": AUTHORITY,
        "source_evidence_sha256": EVIDENCE_SHA,
        "scope_as_of": datetime(2026, 7, 20, tzinfo=UTC),
    }
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                SamplePurchaseOrderRow(
                    **base,
                    **scoped,
                    id="native-order",
                    approval_id="native-approval",
                    offer_id="native-offer",
                    scenario_id="native-scenario",
                    supplier_ref="native-supplier",
                    authority_evidence_id="native-order-evidence",
                ),
                SamplePurchaseOrderRow(
                    **base,
                    id="legacy-order",
                    approval_id="legacy-approval",
                    offer_id="legacy-offer",
                    scenario_id="legacy-scenario",
                    supplier_ref="legacy-supplier",
                ),
                SamplePurchaseOrderRow(
                    **base,
                    **{
                        **scoped,
                        "entity_ref": "entity-other",
                        "scope_grant_authority_sha256": "b" * 64,
                    },
                    id="other-order",
                    approval_id="other-approval",
                    offer_id="other-offer",
                    scenario_id="other-scenario",
                    supplier_ref="other-supplier",
                    authority_evidence_id="other-order-evidence",
                ),
                SampleProcurementEventRow(
                    **scoped,
                    id="native-event",
                    purchase_order_id="native-order",
                    sequence=1,
                    event_type="order_confirmed",
                    effective_at=datetime(2026, 7, 21, tzinfo=UTC),
                    evidence_id="native-event-evidence",
                    facts_json={
                        "supplier_order_ref": "SUP-1",
                        "promised_delivery_at": (
                            "2026-07-27T00:00:00+00:00"
                        ),
                    },
                    created_by="operator",
                    recorded_at=datetime(2026, 7, 21, 1, tzinfo=UTC),
                ),
            ]
        )
    service = ProcurementService(
        engine=engine,
        repository=None,
        sourcing_store=None,
        sourcing=None,
        evidence=None,
    )
    first = service.read_scoped_sources(
        tenant_ref="tenant-cn-1",
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        scope_grant_authority_sha256=AUTHORITY,
        as_of=AS_OF,
    )
    second = service.read_scoped_sources(
        tenant_ref="tenant-cn-1",
        entity_ref="entity-cn-1",
        store_ref="store-cn-1",
        scope_grant_authority_sha256=AUTHORITY,
        as_of=AS_OF,
    )
    assert first == second
    assert [item["id"] for item in first["orders"]] == ["native-order"]
    assert [item["id"] for item in first["events"]] == ["native-event"]
    assert (
        ScopedProcurementReceivingWorkspace._hash(
            {
                key: value
                for key, value in first.items()
                if key != "snapshot_sha256"
            }
        )
        == first["snapshot_sha256"]
    )
