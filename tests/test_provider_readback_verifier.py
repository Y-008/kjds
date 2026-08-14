import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from apps.control_plane.channel_account_runtime_identity import (
    SignedManagedCredentialLeaseResolver,
)
from apps.control_plane.provider_readback_verifier import (
    PROVIDER_READBACK_CONTRACT_ID,
    PROVIDER_READBACK_VERIFIER_VERSION,
    READBACK_PRODUCT_CONTRACT_VERSION,
    READBACK_SUMMARY_CONTRACT_ID,
    ProviderReadbackVerifier,
)

NOW = datetime(2026, 8, 1, 10, tzinfo=UTC)


def finance_bundle(operations=("op-1",)):
    encoded = json.dumps(
        {"result": {"operations": [{"operation_id": item} for item in operations], "page_count": 1}},
        separators=(",", ":"),
    ).encode()
    return json.dumps(
        {
            "schema_version": "ozon-response-bundle-v2",
            "contract_version": "ozon-finance-transactions-v1",
            "responses": [
                {
                    "path": "/v3/finance/transaction/list",
                    "status_code": 200,
                    "headers": {},
                    "body_sha256": hashlib.sha256(encoded).hexdigest(),
                    "body_base64": base64.b64encode(encoded).decode(),
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def product_bundle():
    bodies = [
        {"items": [{"offer_id": "offer-1", "name": "Storage box"}]},
        {"result": {"items": [{"offer_id": "offer-1", "name": "Storage box"}]}},
    ]
    responses = []
    for path, body in (
        ("/v3/product/info/list", bodies[0]),
        ("/v4/product/info/attributes", bodies[1]),
    ):
        encoded = json.dumps(body, separators=(",", ":")).encode()
        responses.append(
            {
                "path": path,
                "status_code": 200,
                "headers": {},
                "body_sha256": hashlib.sha256(encoded).hexdigest(),
                "body_base64": base64.b64encode(encoded).decode(),
            }
        )
    return json.dumps(
        {
            "schema_version": "ozon-response-bundle-v2",
            "contract_version": READBACK_PRODUCT_CONTRACT_VERSION,
            "responses": responses,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def fingerprint(account_ref="account-1"):
    return SignedManagedCredentialLeaseResolver.credential_fingerprint(
        client_id="client-1",
        api_key="api-key-1",
        platform="ozon",
        account_ref=account_ref,
    )


def summary(**changes):
    bundle = finance_bundle()
    value = {
        "contract_id": READBACK_SUMMARY_CONTRACT_ID,
        "schema_version": "1",
        "platform": "ozon",
        "account_ref": "account-1",
        "adapter_id": "ozon-seller-api-read",
        "adapter_version": "v1",
        "required_capability": "finance.read",
        "scope": {
            "tenant_ref": "tenant-1",
            "entity_ref": "entity-1",
            "store_ref": "store-1",
        },
        "client_id_sha256": hashlib.sha256(b"client-1").hexdigest(),
        "credential_fingerprint_sha256": fingerprint(),
        "secret_reference_sha256": "c" * 64,
        "observed_at": NOW.isoformat(),
        "operation": "ozon.finance.read",
        "query_window_sha256": "d" * 64,
        "response_bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "response_byte_size": len(bundle),
        "operation_count": 1,
        "page": 1,
        "page_size": 100,
        "page_count": 1,
        "captured_by": "kjds-readback-capturer",
        "official_origin_verified": True,
        "contract_version": "ozon-finance-transactions-v1",
    }
    value.update(changes)
    return value


def facts(**changes):
    value = {
        "tenant_ref": "tenant-1",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
        "platform": "ozon",
        "account_ref": "account-1",
        "adapter_id": "ozon-seller-api-read",
        "adapter_version": "v1",
        "required_capability": "finance.read",
        "credential_fingerprint_sha256": fingerprint(),
        "secret_reference_sha256": "c" * 64,
        "provider_readback_verified_at": NOW.isoformat(),
    }
    value.update(changes)
    return value


def verify(**changes):
    values = {
        "summary": summary(),
        "bundle_bytes": finance_bundle(),
        "facts": facts(),
        "verifier_actor": "kjds-external-verifier",
        "provisioner_actor": "kjds-lease-provisioner",
        "as_of": NOW,
    }
    values.update(changes)
    return ProviderReadbackVerifier().verify(**values)


def test_valid_official_readback_passes_all_checks():
    observation = verify()
    assert observation["contract_id"] == PROVIDER_READBACK_CONTRACT_ID
    assert observation["verifier_version"] == PROVIDER_READBACK_VERIFIER_VERSION
    assert observation["verdict"] == "passed"
    assert observation["blockers"] == []
    assert all(observation["checks"].values())
    assert len(observation["observation_sha256"]) == 64
    replay = verify()
    assert replay["observation_sha256"] == observation["observation_sha256"]


def test_valid_official_product_readback_passes_all_checks():
    bundle = product_bundle()
    value = summary(
        contract_version=READBACK_PRODUCT_CONTRACT_VERSION,
        operation="ozon.product.read",
        query_window_sha256=hashlib.sha256(b"offer-1").hexdigest(),
        operation_count=2,
        page_size=1,
        response_bundle_sha256=hashlib.sha256(bundle).hexdigest(),
        response_byte_size=len(bundle),
    )
    observation = ProviderReadbackVerifier().verify(
        summary=value,
        bundle_bytes=bundle,
        facts=facts(),
        verifier_actor="kjds-external-verifier",
        provisioner_actor="kjds-lease-provisioner",
        as_of=NOW,
    )
    assert observation["verdict"] == "passed"
    assert observation["blockers"] == []


def test_tampered_bundle_fails_integrity_and_contract():
    observation = verify(bundle_bytes=finance_bundle() + b" ")
    assert observation["verdict"] == "failed"
    assert "READBACK_BUNDLE_HASH_DRIFT" in observation["blockers"]


def test_identity_drift_fails():
    observation = verify(
        facts=facts(credential_fingerprint_sha256="0" * 64),
    )
    assert observation["verdict"] == "failed"
    assert "READBACK_IDENTITY_DRIFT" in observation["blockers"]


def test_cross_scope_facts_fail():
    observation = verify(
        facts=facts(store_ref="other-store"),
    )
    assert observation["verdict"] == "failed"
    assert "READBACK_SCOPE_DRIFT" in observation["blockers"]


def test_stale_observation_fails_freshness():
    observation = verify(
        summary=summary(
            observed_at=(NOW - timedelta(hours=2)).isoformat(),
        ),
        facts=facts(
            provider_readback_verified_at=(NOW - timedelta(hours=2)).isoformat(),
        ),
    )
    assert observation["verdict"] == "failed"
    assert "READBACK_OBSERVATION_STALE" in observation["blockers"]


def test_verifier_must_be_independent_from_capturer_and_provisioner():
    assert "READBACK_VERIFIER_NOT_INDEPENDENT" in verify(
        verifier_actor="kjds-lease-provisioner",
    )["blockers"]
    assert "READBACK_VERIFIER_NOT_INDEPENDENT" in verify(
        verifier_actor="kjds-readback-capturer",
    )["blockers"]
    assert "READBACK_VERIFIER_NOT_INDEPENDENT" in verify(
        summary=summary(captured_by="kjds-lease-provisioner"),
        verifier_actor="kjds-external-verifier",
    )["blockers"]


def test_missing_summary_fields_fail_closed():
    partial = summary()
    partial.pop("query_window_sha256")
    observation = verify(summary=partial)
    assert observation["verdict"] == "failed"
    assert any("READBACK_SUMMARY_MISSING_FIELDS" in item for item in observation["blockers"])


def test_probe_credentials_never_pass_managed_worker_admission():
    from apps.control_plane.ozon_worker import (
        ChannelCredentialAuthorizationError,
        OzonCredentials,
        OzonSellerClient,
    )

    probe = OzonCredentials.for_readback_probe(
        client_id="client-1",
        api_key="api-key-1",
    )
    assert probe.is_readback_probe() is True
    assert probe.is_runtime_attested() is False
    assert probe.is_test_fixture() is False
    with pytest.raises(ChannelCredentialAuthorizationError, match="resolver-attested"):
        OzonSellerClient(probe)
    # Explicit probe admission works but stays read-only by contract.
    client = OzonSellerClient(
        probe,
        readback_probe_allowed=True,
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    client.close()
