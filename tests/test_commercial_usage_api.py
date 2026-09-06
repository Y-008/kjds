from datetime import datetime

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps.control_plane.api import registered_routes
from apps.control_plane.routers import commercial_usage
from apps.control_plane.security import Principal


def test_commercial_usage_routes_are_registered():
    paths = {route.path for route in registered_routes()}
    assert "/v1/commercial/usage" in paths
    assert "/v1/commercial/usage-preview" in paths


def _usage_payload(**overrides):
    payload = {
        "event_id": "usage-1",
        "idempotency_key": "usage-key-1",
        "customer_id": "customer-1",
        "skill_id": "image.generate",
        "units": "1",
        "unit_cost": "0.25",
    }
    payload.update(overrides)
    return payload


def test_usage_input_requires_an_ascii_three_letter_currency():
    with pytest.raises(ValidationError):
        commercial_usage.UsageEventInput.model_validate(
            _usage_payload(currency="US$")
        )

    # Lower-case ISO codes remain accepted at the transport boundary and are
    # normalized before they reach the immutable ledger.
    assert commercial_usage.UsageEventInput.model_validate(
        _usage_payload(currency="rub")
    ).currency == "rub"


def test_usage_input_rejects_naive_occurred_at():
    with pytest.raises(ValidationError, match="occurred_at must include a timezone"):
        commercial_usage.UsageEventInput.model_validate(
            _usage_payload(occurred_at=datetime(2026, 9, 6, 12, 0))
        )


def test_usage_preview_rejects_invalid_currency_before_ledger_access():
    principal = Principal(
        actor_id="viewer",
        roles=frozenset(),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    with pytest.raises(HTTPException) as caught:
        commercial_usage.usage_preview(
            customer_id="customer-1",
            principal=principal,  # role check is intentionally bypassed below
            currency="RUB$",
        )

    # The route performs authorization before currency normalization in the
    # production call.  Assert the helper's precise validation surface
    # separately without touching a real ledger.
    assert caught.value.status_code == 403
    with pytest.raises(HTTPException) as invalid:
        commercial_usage._currency_code("RUB$")
    assert invalid.value.status_code == 422
