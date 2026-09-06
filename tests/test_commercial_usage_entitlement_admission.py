from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.control_plane.commercial_entitlement_authority import (
    CommercialEntitlementAdmissionError,
    canonical_entitlement_id,
)
from apps.control_plane.routers import commercial_usage
from apps.control_plane.security import Principal


def _principal() -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )


def _body(**overrides):
    payload = {
        "event_id": "usage-entitlement-1",
        "idempotency_key": "usage-entitlement-key-1",
        "customer_id": "customer-a",
        "skill_id": "image.generate",
        "units": "1",
        "unit_cost": "0.25",
        "occurred_at": datetime.now(UTC),
        "entitlement_id": canonical_entitlement_id(
            tenant_id="tenant-a",
            customer_id="customer-a",
            deployment_ref="deployment-a",
            entity_ref="entity-a",
            store_ref="store-a",
        ),
        "deployment_ref": "deployment-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "metric": "requests",
    }
    payload.update(overrides)
    return commercial_usage.UsageEventInput.model_validate(payload)


class FakeAuthority:
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return {"receipt_sha256": "a" * 64, "entitlement_id": kwargs["entitlement_id"]}


class RejectingAuthority(FakeAuthority):
    def resolve(self, **kwargs):
        raise CommercialEntitlementAdmissionError("entitlement is stale")


class FakeLedger:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)
        return event


def test_explicit_entitlement_is_resolved_before_usage_write(monkeypatch):
    authority = FakeAuthority()
    ledger = FakeLedger()
    monkeypatch.setattr(
        commercial_usage,
        "runtime",
        SimpleNamespace(
            commercial_entitlement_authority=authority,
            skill_usage_ledger=ledger,
        ),
    )

    response = commercial_usage.record_usage(_body(), _principal())

    assert len(authority.calls) == 1
    assert authority.calls[0]["tenant_id"] == "tenant-a"
    assert authority.calls[0]["customer_id"] == "customer-a"
    assert authority.calls[0]["store_ref"] == "store-a"
    assert len(ledger.events) == 1
    assert response["entitlement_admission"]["receipt_sha256"] == "a" * 64


def test_partial_entitlement_declaration_fails_before_ledger_write(monkeypatch):
    ledger = FakeLedger()
    monkeypatch.setattr(
        commercial_usage,
        "runtime",
        SimpleNamespace(skill_usage_ledger=ledger),
    )

    with pytest.raises(ValueError, match="entitlement scope requires"):
        commercial_usage.record_usage(
            _body(entity_ref=None),
            _principal(),
        )
    assert ledger.events == []


def test_legacy_usage_request_remains_compatible_without_entitlement_fields(monkeypatch):
    ledger = FakeLedger()
    monkeypatch.setattr(
        commercial_usage,
        "runtime",
        SimpleNamespace(skill_usage_ledger=ledger),
    )
    body = commercial_usage.UsageEventInput.model_validate(
        {
            "event_id": "legacy-usage-1",
            "idempotency_key": "legacy-usage-key-1",
            "customer_id": "customer-a",
            "skill_id": "image.generate",
            "units": "1",
            "unit_cost": "0.25",
        }
    )

    response = commercial_usage.record_usage(body, _principal())

    assert response["event_id"] == "legacy-usage-1"
    assert len(ledger.events) == 1


def test_authority_rejection_is_a_forbidden_http_error_before_write(monkeypatch):
    authority = RejectingAuthority()
    ledger = FakeLedger()
    monkeypatch.setattr(
        commercial_usage,
        "runtime",
        SimpleNamespace(
            commercial_entitlement_authority=authority,
            skill_usage_ledger=ledger,
        ),
    )

    with pytest.raises(HTTPException) as caught:
        commercial_usage.record_usage(_body(), _principal())
    assert caught.value.status_code == 403
    assert caught.value.detail == "entitlement is stale"
    assert ledger.events == []
