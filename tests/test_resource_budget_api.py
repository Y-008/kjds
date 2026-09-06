from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from apps.control_plane.routers import control_plane_observability, resource_budgets
from apps.control_plane.security import Principal


def _principal() -> Principal:
    return Principal(
        actor_id="operator-1",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )


class _Ledger:
    def snapshot(self, *, tenant_id: str, budget_id: str):
        assert tenant_id == "tenant-a"
        assert budget_id == "budget-1"
        return {
            "tenant_id": tenant_id,
            "budget_id": budget_id,
            "available": "-2",
            "currency": "USD",
            "external_write_allowed": False,
        }


class _RecordingLedger:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)
        return event


def test_guard_status_can_bind_exact_resource_budget(monkeypatch):
    monkeypatch.setattr(
        control_plane_observability.runtime,
        "resource_budget_ledger",
        _Ledger(),
    )
    response = control_plane_observability.economics_guard_status(
        principal=_principal(),
        cash_available=Decimal("100"),
        budget_id="budget-1",
    )
    assert response["status"] == "BLOCKED"
    assert "budget_remaining_negative" in response["reasons"]
    assert response["resource_budget"]["budget_id"] == "budget-1"


def test_budget_event_api_rejects_future_occurred_at(monkeypatch):
    ledger = _RecordingLedger()
    monkeypatch.setattr(resource_budgets.runtime, "resource_budget_ledger", ledger)
    body = resource_budgets.BudgetEventInput(
        event_id="future-event",
        idempotency_key="future-key",
        state="reserved",
        amount=Decimal("1"),
        occurred_at=datetime.now(UTC) + timedelta(minutes=5),
    )

    with pytest.raises(HTTPException) as caught:
        resource_budgets.record_budget_event(
            "budget-1", body, principal=_principal()
        )

    assert caught.value.status_code == 422
    assert "future" in str(caught.value.detail)
    assert ledger.events == []


def test_budget_event_api_accepts_late_occurred_at(monkeypatch):
    ledger = _RecordingLedger()
    monkeypatch.setattr(resource_budgets.runtime, "resource_budget_ledger", ledger)
    late = datetime.now(UTC) - timedelta(days=3)
    body = resource_budgets.BudgetEventInput(
        event_id="late-event",
        idempotency_key="late-key",
        state="reserved",
        amount=Decimal("1"),
        occurred_at=late,
    )

    response = resource_budgets.record_budget_event(
        "budget-1", body, principal=_principal()
    )

    assert response["event_id"] == "late-event"
    assert ledger.events[0].occurred_at == late.astimezone(UTC)


def test_budget_event_api_overrun_requires_governance_role(monkeypatch):
    ledger = _RecordingLedger()
    monkeypatch.setattr(resource_budgets.runtime, "resource_budget_ledger", ledger)
    body = resource_budgets.BudgetEventInput(
        event_id="overrun-event",
        idempotency_key="overrun-key",
        state="overrun",
        amount=Decimal("1"),
    )

    with pytest.raises(HTTPException) as caught:
        resource_budgets.record_budget_event(
            "budget-1", body, principal=_principal()
        )

    assert caught.value.status_code == 403
    assert ledger.events == []
