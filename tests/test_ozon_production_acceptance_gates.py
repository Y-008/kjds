"""Focused admission tests for the read-only Ozon production gate."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from apps.control_plane.ozon_production_acceptance import OzonProductionAcceptanceService
from apps.control_plane.security import Principal

AS_OF = datetime(2026, 9, 6, tzinfo=UTC)


def _principal() -> Principal:
    return Principal(
        actor_id="reviewer",
        roles=frozenset({"reviewer"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )


def _bundle() -> bytes:
    responses = []
    for path in ("/v3/product/info/list", "/v4/product/info/attributes"):
        body = json.dumps({}, separators=(",", ":")).encode()
        responses.append(
            {
                "path": path,
                "status_code": 200,
                "headers": {},
                "body_base64": base64.b64encode(body).decode(),
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return json.dumps(
        {
            "schema_version": "ozon-response-bundle-v2",
            "contract_version": "ozon-product-read-v1",
            "responses": responses,
            "request_context": {
                "operation": "ozon.product.read",
                "offer_id_sha256": "a" * 64,
            },
        },
        separators=(",", ":"),
    ).encode()


class _Evidence:
    def __init__(self, bundle: bytes) -> None:
        digest = hashlib.sha256(bundle).hexdigest()
        self.record = SimpleNamespace(
            source="ozon-isolated-read-worker",
            source_ref="run-1",
            content_type="application/json",
            grade="A",
            metadata={
                "raw_response_stored": True,
                "response_sha256": digest,
                "observed_at": AS_OF.isoformat(),
            },
            effective_at=AS_OF,
            effective_until=None,
            recorded_at=AS_OF,
        )
        self.verification = SimpleNamespace(
            valid=True,
            actual_sha256=digest,
            byte_size=len(bundle),
        )
        self.bundle = bundle

    def target_evidence_ids(self, **_kwargs):
        return ["evidence-1"]

    def inspect_integrity(self, _evidence_id):
        return self.record, self.verification

    def content(self, _evidence_id):
        return self.bundle, self.record


class _ChannelAccounts:
    def project(self, **_kwargs):
        return {
            "items": [
                {
                    "platform": "ozon",
                    "account_ref": "account-1",
                    "adapter": {
                        "adapter_id": "ozon-read",
                        "adapter_version": "1",
                        "read_only": True,
                    },
                    "state": "ready",
                    "capabilities": ["catalog.read"],
                    "runtime_identity": {
                        "status": "fresh_passed",
                        "managed_store_bound": True,
                        "lease_fresh": True,
                        "fingerprint_match": True,
                        "scope_match": True,
                        "capabilities_match": True,
                        "provider_readback_fresh_passed": True,
                        "external_verifier_fresh_passed": True,
                    },
                }
            ]
        }


def _run(bundle: bytes | None, *, error_code: str | None = None):
    digest = hashlib.sha256(bundle).hexdigest() if bundle is not None else None
    return {
        "id": "run-1",
        "pilot_id": "pilot-1",
        "scope": {
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
        },
        "operation": "ozon.product.read",
        "target_hash": "a" * 64,
        "status": "completed",
        "outcome": "succeeded" if error_code is None else "failed",
        "error_code": error_code,
        "immutable_after_completion": True,
        "raw_response_evidence_id": "evidence-1" if bundle is not None else None,
        "raw_response_stored": bundle is not None,
        "raw_response_verified": bundle is not None,
        "raw_response_integrity_code": None,
        "response_sha256": digest,
        "response_byte_size": len(bundle) if bundle is not None else None,
        "summary": {},
        "record_count": 1,
    }


class _Pilots:
    def __init__(self, run):
        self.run = run

    def require_run(self, _run_id, **_kwargs):
        return self.run


def _service(run, evidence=None):
    return OzonProductionAcceptanceService(
        scoped_pilots=_Pilots(run),
        evidence=evidence or _Evidence(_bundle()),
        channel_account_reader=_ChannelAccounts(),
        clock=lambda: AS_OF,
    )


def _evaluate(service):
    return service.evaluate(
        principal=_principal(),
        entity_scope={
            "status": "ready",
            "entity_ref": "entity-a",
            "authority_sha256": "b" * 64,
        },
        store_ref="store-a",
        run_id="run-1",
        as_of=AS_OF,
    )


def test_fresh_product_readback_is_admitted_without_granting_write_or_fact_promotion():
    bundle = _bundle()
    result = _evaluate(_service(_run(bundle), _Evidence(bundle)))

    assert result["status"] == "accepted"
    assert result["gate_status"] == "PASS"
    assert result["accepted"] is True
    assert result["external_write_allowed"] is False
    assert result["formal_fact_promotion_allowed"] is False
    assert result["production_release_allowed"] is False
    assert result["credential_values_returned"] is False


def test_missing_readback_artifact_is_blocked_and_never_reported_as_no_data():
    result = _evaluate(_service(_run(None)))

    assert result["status"] == "blocked"
    assert result["gate_status"] == "BLOCKED_EVIDENCE"
    assert result["accepted"] is False
    assert "OZON_READBACK_ARTIFACT_MISSING" in result["blockers"]
    assert result["gate_status"] != "NO_DATA"


def test_transport_failed_run_is_blocked_even_when_scope_exists():
    result = _evaluate(_service(_run(None, error_code="OZON_READ_TRANSPORT")))

    assert result["status"] == "blocked"
    assert result["gate_status"] == "BLOCKED_EVIDENCE"
    assert "OZON_READ_TRANSPORT_FAILED" in result["blockers"]
    assert "OZON_READBACK_ARTIFACT_MISSING" in result["blockers"]


def test_scoped_authority_failure_is_blocked_and_does_not_become_no_data():
    class _BrokenPilots:
        def require_run(self, **_kwargs):
            raise RuntimeError("readback evidence is stale")

    service = OzonProductionAcceptanceService(
        scoped_pilots=_BrokenPilots(),
        evidence=object(),
        clock=lambda: AS_OF,
    )
    result = _evaluate(service)

    assert result["status"] == "blocked"
    assert result["gate_status"] == "BLOCKED_EVIDENCE"
    assert "scoped_read_run_not_admissible" in result["blockers"]
    assert result["gate_status"] != "NO_DATA"
