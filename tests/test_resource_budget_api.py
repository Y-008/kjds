from __future__ import annotations

from decimal import Decimal

from apps.control_plane.routers import control_plane_observability
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

