from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

from apps.control_plane.scoped_returns_aftersales import (
    ScopedReturnsAfterSalesWorkspace,
)
from apps.control_plane.security import Principal

SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": "a" * 64,
}
AS_OF = "2026-07-29T00:00:00+00:00"


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def frozen(value):
    payload = deepcopy(value)
    payload["snapshot_sha256"] = digest(payload)
    return payload


class FakeUpstream:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def workspace(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.value)

    def project(self, **kwargs):
        self.calls.append(kwargs)
        return deepcopy(self.value)


class MustNotRead:
    calls = 0

    def workspace(self, **_kwargs):
        self.calls += 1
        raise AssertionError("upstream must not be read")

    def project(self, **_kwargs):
        self.calls += 1
        raise AssertionError("upstream must not be read")


def principal():
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"ozon-primary"}),
    )


def entity_scope():
    return {
        "status": "ready",
        "entity_ref": "entity-a",
        "authority_sha256": "a" * 64,
    }


def event(
    *,
    fact_type,
    fact_id,
    external_id,
    quantity,
    effective_at,
    amount,
):
    return {
        "fact_id": fact_id,
        "fact_type": fact_type,
        "external_id": external_id,
        "order_external_id": "order-a",
        "product_id": "prd-a",
        "sku": "SKU-A",
        "quantity": quantity,
        "currency": "RUB",
        "amount": amount,
        "raw_status": (
            "delivered" if fact_type == "ozon_order" else "returned"
        ),
        "canonical_status": (
            "delivered" if fact_type == "ozon_order" else "returned"
        ),
        "return_reason": (
            None if fact_type == "ozon_order" else "buyer_return"
        ),
        "effective_at": effective_at,
        "recorded_at": effective_at,
        "evidence_id": f"evidence-{fact_id}",
        "source_evidence_sha256": "b" * 64,
    }


def oms(*, returned_quantity=1, include_return=True):
    order_event = event(
        fact_type="ozon_order",
        fact_id="fact-order",
        external_id="order-a",
        quantity=2,
        effective_at="2026-07-28T10:00:00+00:00",
        amount="1000",
    )
    timeline = [order_event]
    if include_return:
        timeline.append(
            event(
                fact_type="ozon_return",
                fact_id="fact-return",
                external_id="return-a",
                quantity=returned_quantity,
                effective_at="2026-07-28T11:00:00+00:00",
                amount="100",
            )
        )
    return frozen(
        {
            "contract_id": "kjds-native-scoped-oms-v1",
            "status": "ready",
            "as_of": AS_OF,
            "scope": SCOPE,
            "query": {"next_cursor": None},
            "counts": {},
            "orders": [
                {
                    "external_id": "order-a",
                    "product_id": "prd-a",
                    "sku": "SKU-A",
                    "current_state": (
                        "returned" if include_return else "delivered"
                    ),
                    "current_event": timeline[-1],
                    "projection_status": "ready",
                    "timeline": timeline,
                    "blocked_events": [],
                    "timeline_event_count": len(timeline),
                    "evidence_ids": [
                        item["evidence_id"] for item in timeline
                    ],
                    "fact_ids": [item["fact_id"] for item in timeline],
                }
            ],
            "source_gaps": [],
            "control_envelope": {
                "scoped_input_read": True,
                "external_write_allowed": False,
            },
        }
    )


def finance(*, stage="reconciled"):
    return frozen(
        {
            "contract_id": (
                "kjds-native-exact-scope-settlement-cash-control-v1"
            ),
            "status": "ready",
            "as_of": AS_OF,
            "scope": SCOPE,
            "filters": {},
            "counts": {},
            "pagination": {"page_size": 100, "next_cursor": None},
            "cycles": [
                {
                    "reconciliation_key": "order-a",
                    "stage": stage,
                    "latest_effective_at": "2026-07-28T12:00:00+00:00",
                    "currency": "RUB",
                    "books": {},
                    "actual_cash_cm3": {"status": "unavailable"},
                }
            ],
            "source_gaps": [],
            "control_envelope": {
                "scoped_input_read": True,
                "external_write_allowed": False,
            },
        }
    )


def workspace(oms_value, finance_value):
    return ScopedReturnsAfterSalesWorkspace(
        oms=FakeUpstream(oms_value),
        finance=FakeUpstream(finance_value),
    )


def project(service, **kwargs):
    return service.project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=AS_OF,
        **kwargs,
    )


def test_missing_entity_reads_no_upstream():
    oms_source = MustNotRead()
    finance_source = MustNotRead()
    result = ScopedReturnsAfterSalesWorkspace(
        oms=oms_source,
        finance=finance_source,
    ).project(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "reason": "entity_scope_authority_missing",
        },
        store_ref="ozon-primary",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["returns"] == []
    assert result["control_envelope"]["scoped_input_read"] is False
    assert oms_source.calls == 0
    assert finance_source.calls == 0


def test_no_return_short_circuits_finance():
    oms_source = FakeUpstream(oms(include_return=False))
    finance_source = MustNotRead()
    result = ScopedReturnsAfterSalesWorkspace(
        oms=oms_source,
        finance=finance_source,
    ).project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert "return_fact_missing" in result["source_gaps"]
    assert len(oms_source.calls) == 1
    assert finance_source.calls == 0


def test_return_and_reconciled_finance_are_projected_with_gated_service():
    service = workspace(oms(), finance())
    first = project(service)
    second = project(service)

    assert first["status"] == "partial"
    assert first["counts"]["total_returns"] == 1
    assert first["counts"]["returned_units"] == 1
    item = first["returns"][0]
    assert item["stage"] == "refund_reconciled"
    assert item["ordered_quantity"] == 2
    assert item["remaining_quantity"] == 1
    assert item["customer_service"]["status"] == "gated"
    assert (
        first["customer_service_authority"][
            "customer_service_case_authority_available"
        ]
        is False
    )
    assert first["control_envelope"]["refund_created"] is False
    assert first["control_envelope"]["customer_message_sent"] is False
    assert first["control_envelope"]["external_write_allowed"] is False
    assert first["agent_artifact"]["self_approval_allowed"] is False
    assert first["agent_artifact"]["permit_issue_allowed"] is False
    assert first["snapshot_sha256"] == second["snapshot_sha256"]


def test_over_return_fails_closed_and_hides_business_values():
    result = project(workspace(oms(returned_quantity=3), finance()))

    assert result["status"] == "blocked"
    assert result["returns"] == []
    assert result["excluded"]["business_values_exposed"] is False
    assert result["excluded"]["reason_counts"] == {
        "returns_quantity_exceeds_order": 1
    }


def test_bad_oms_snapshot_fails_closed_before_finance():
    bad = oms()
    bad["orders"][0]["sku"] = "DRIFT"
    oms_source = FakeUpstream(bad)
    finance_source = MustNotRead()
    result = ScopedReturnsAfterSalesWorkspace(
        oms=oms_source,
        finance=finance_source,
    ).project(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="ozon-primary",
        as_of=AS_OF,
    )

    assert result["status"] == "blocked"
    assert result["returns"] == []
    assert "returns_oms_snapshot_hash_drift" in result["source_gaps"]
    assert finance_source.calls == 0


def test_bad_finance_snapshot_fails_closed():
    bad = finance()
    bad["cycles"][0]["stage"] = "variance"
    result = project(workspace(oms(), bad))

    assert result["status"] == "blocked"
    assert result["returns"] == []
    assert result["excluded"]["reason_counts"] == {
        "returns_finance_snapshot_hash_drift": 1
    }


def test_filters_cursor_and_cross_store_are_server_owned():
    service = workspace(oms(), finance(stage="cash_pending"))
    result = project(
        service,
        query="return-a",
        stage="refund_cash_pending",
        page_size=1,
    )

    assert result["counts"]["filtered"] == 1
    assert result["counts"]["page"] == 1
    assert result["returns"][0]["stage"] == "refund_cash_pending"
    with pytest.raises(PermissionError):
        service.project(
            principal=principal(),
            entity_scope=entity_scope(),
            store_ref="other-store",
            as_of=AS_OF,
        )
