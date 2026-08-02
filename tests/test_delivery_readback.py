from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from apps.control_plane.delivery_readback import (
    AUTHORIZED_ADAPTER_CONTRACT_ID,
    AuthorizedDeliveryReadbackSource,
    DisabledDeliveryReadbackSource,
)
from apps.control_plane.security import Principal

AS_OF = datetime(2026, 7, 29, 18, tzinfo=UTC)
SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
}
EVIDENCE_SHA = "e" * 64


def stable_hash(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def principal():
    return Principal(
        actor_id="delivery-reader",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"ozon-primary"}),
    )


def readback():
    return {
        "readback_id": "readback-a",
        "readback_evidence_id": "evidence-readback",
        "readback_evidence_sha256": EVIDENCE_SHA,
        "shipment_id": "shipment-a",
        "order_external_id": "order-a",
        "product_id": "product-a",
        "sku": "SKU-A",
        "state": "transit",
        "package": {
            "package_id": "package-a",
            "quantity": 1,
            "physical_weight_kg": "1",
        },
        "chargeable_weight": {
            "value": "1",
            "unit": "kg",
            "calculation_sha256": "c" * 64,
        },
        "legs": [
            {
                "leg_id": "leg-a",
                "sequence": 1,
                "tracking_ref": "TRACK-A",
                "carrier": "official-carrier",
                "service": "standard",
                "state": "transit",
                "effective_at": "2026-07-29T17:00:00+00:00",
                "source_evidence_sha256": EVIDENCE_SHA,
            }
        ],
        "freight_authority": {
            "currency": "CNY",
            "quoted": "10",
            "actual": "11",
            "rate_card_id": "rate-a",
            "calculation_id": "calculation-a",
            "calculation_sha256": "f" * 64,
            "carrier_final_bill_evidence_id": "bill-a",
        },
    }


def envelope(*, readbacks=None, **overrides):
    value = {
        "contract_id": AUTHORIZED_ADAPTER_CONTRACT_ID,
        "schema_version": "1.0",
        "scope": SCOPE,
        "adapter_id": "official-delivery-reader",
        "adapter_version": "1.0.0",
        "source_kind": "authorized_formal_export",
        "observed_at": "2026-07-29T17:30:00+00:00",
        "revoked": False,
        "outcome": "succeeded",
        "readbacks": readbacks if readbacks is not None else [readback()],
    }
    value.update(overrides)
    value["payload_sha256"] = stable_hash(value)
    return value


class Evidence:
    def require_current(self, _ids, **_kwargs):
        return None

    def get(self, evidence_id):
        if evidence_id == "evidence-auth":
            return SimpleNamespace(
                source="delivery_readback_adapter_authorization",
                sha256=EVIDENCE_SHA,
                metadata={
                    "adapter_id": "official-delivery-reader",
                    "adapter_version": "1.0.0",
                    "source_kind": "authorized_formal_export",
                    "authorization_status": "active",
                    "revoked": False,
                },
            )
        if evidence_id == "evidence-readback":
            return SimpleNamespace(
                source="authorized_delivery_readback_export",
                sha256=EVIDENCE_SHA,
                metadata={
                    "adapter_id": "official-delivery-reader",
                    "readback_id": "readback-a",
                    "order_external_id": "order-a",
                    "shipment_id": "shipment-a",
                    "outcome": "succeeded",
                    "revoked": False,
                },
            )
        raise KeyError(evidence_id)


class ScopedEvidence:
    def project_targets(self, *, evidence_ids, **_kwargs):
        return {
            "status": "ready",
            "records": [
                {"evidence_id": item, "status": "ready"}
                for item in evidence_ids
            ],
        }


class Reader:
    def __init__(self, value=None, *, timeout=False):
        self.value = value
        self.timeout = timeout
        self.calls = 0

    def __call__(self, **_kwargs):
        self.calls += 1
        if self.timeout:
            raise TimeoutError("bounded official source timeout")
        return copy.deepcopy(self.value)


def source(reader):
    return AuthorizedDeliveryReadbackSource(
        reader=reader,
        evidence=Evidence(),
        scoped_evidence=ScopedEvidence(),
        adapter_id="official-delivery-reader",
        adapter_version="1.0.0",
        source_kind="authorized_formal_export",
        authorization_evidence_id="evidence-auth",
        authorization_evidence_sha256=EVIDENCE_SHA,
    )


def project(value):
    return value.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AS_OF,
    )


def test_authorized_source_is_exact_scope_and_idempotent_on_exact_replay():
    item = readback()
    reader = Reader(envelope(readbacks=[item, copy.deepcopy(item)]))

    result = project(source(reader))

    assert result["status"] == "ready"
    assert len(result["readbacks"]) == 1
    assert result["authority"]["adapter_id"] == "official-delivery-reader"
    assert result["readbacks"][0]["legs"][0]["evidence_status"] == "current"
    assert result["control_envelope"]["external_write_allowed"] is False


def test_production_composition_root_defaults_to_unbound_no_data_source():
    from apps.control_plane.runtime import runtime

    assert isinstance(
        runtime.scoped_delivery_exceptions.delivery_readbacks,
        DisabledDeliveryReadbackSource,
    )


def test_missing_entity_never_calls_authorized_reader():
    reader = Reader(envelope())
    service = source(reader)

    result = service.project(
        principal=principal(),
        entity_scope={**SCOPE, "entity_ref": None},
        store_ref="ozon-primary",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert reader.calls == 0


def test_authorized_source_timeout_fails_closed():
    result = project(source(Reader(timeout=True)))

    assert result["status"] == "blocked"
    assert result["source_gaps"] == ["formal_delivery_readback_timeout"]


@pytest.mark.parametrize(
    ("overrides", "gap"),
    [
        ({"schema_version": "2.0"}, "formal_delivery_readback_schema_drift"),
        ({"revoked": True}, "formal_delivery_readback_revoked"),
        ({"outcome": "maybe"}, "formal_delivery_readback_outcome_unknown"),
    ],
)
def test_schema_revocation_and_unknown_outcome_fail_closed(
    overrides,
    gap,
):
    result = project(source(Reader(envelope(**overrides))))

    assert result["status"] == "blocked"
    assert gap in result["source_gaps"]


def test_conflicting_duplicate_readback_is_not_an_idempotent_replay():
    first = readback()
    second = {**readback(), "shipment_id": "shipment-conflict"}
    result = project(source(Reader(envelope(readbacks=[first, second]))))

    assert result["status"] == "blocked"
    assert result["source_gaps"] == [
        "formal_delivery_readback_replay_conflict"
    ]
