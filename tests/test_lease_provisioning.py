import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.causal_policies import CausalPolicyRow
from apps.control_plane.channel_account_runtime_identity import (
    SignedManagedCredentialLeaseResolver,
)
from apps.control_plane.lease_provisioning import LeaseProvisioningSeam
from apps.control_plane.managed_credential_leases import (
    SqlManagedCredentialLeaseStore,
)
from apps.control_plane.policy_shadow import PolicyActivationHandoffRow
from apps.control_plane.provider_readback_verifier import (
    READBACK_SUMMARY_CONTRACT_ID,
    ProviderReadbackVerifier,
)
from apps.control_plane.sql_repository import Base

assert CausalPolicyRow.__tablename__ == "causal_policies"
assert PolicyActivationHandoffRow.__tablename__ == "causal_policy_activation_handoffs"


def database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def readback_dir(tmp_path: Path) -> Path:
    out = tmp_path / "readback"
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    body = json.dumps(
        {"result": {"operations": [{"operation_id": "op-1"}], "page_count": 1}},
        separators=(",", ":"),
    ).encode()
    bundle = json.dumps(
        {
            "schema_version": "ozon-response-bundle-v2",
            "contract_version": "ozon-finance-transactions-v1",
            "responses": [
                {
                    "path": "/v3/finance/transaction/list",
                    "status_code": 200,
                    "headers": {},
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "body_base64": base64.b64encode(body).decode(),
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    fingerprint = SignedManagedCredentialLeaseResolver.credential_fingerprint(
        client_id="client-1",
        api_key="api-key-1",
        platform="ozon",
        account_ref="account-1",
    )
    summary = {
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
        "credential_fingerprint_sha256": fingerprint,
        "secret_reference_sha256": hashlib.sha256(
            b"msl_9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e"
        ).hexdigest(),
        "observed_at": (now - timedelta(seconds=30)).isoformat(),
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
    facts = {
        "tenant_ref": "tenant-1",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
        "platform": "ozon",
        "account_ref": "account-1",
        "adapter_id": "ozon-seller-api-read",
        "adapter_version": "v1",
        "required_capability": "finance.read",
        "credential_fingerprint_sha256": fingerprint,
        "secret_reference_sha256": summary["secret_reference_sha256"],
        "provider_readback_verified_at": summary["observed_at"],
    }
    observation = ProviderReadbackVerifier().verify(
        summary=summary,
        bundle_bytes=bundle,
        facts=facts,
        verifier_actor="kjds-external-verifier",
        provisioner_actor="kjds-lease-provisioner",
        as_of=now,
    )
    (out / "readback-bundle.json").write_bytes(bundle)
    (out / "readback-summary.json").write_text(
        json.dumps(summary, sort_keys=True),
        encoding="utf-8",
    )
    (out / "readback-observation.json").write_text(
        json.dumps(observation, sort_keys=True),
        encoding="utf-8",
    )
    return out


def seam(engine):
    store = SqlManagedCredentialLeaseStore(
        engine=engine,
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
    )
    return LeaseProvisioningSeam(store=store, verifier=ProviderReadbackVerifier())


def inputs(readback_dir: Path, **changes):
    value = {
        "readback_dir": readback_dir,
        "lease_id": "lease-1",
        "tenant_ref": "tenant-1",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
        "platform": "ozon",
        "account_ref": "account-1",
        "adapter_id": "ozon-seller-api-read",
        "adapter_version": "v1",
        "capabilities": {"finance.read"},
        "authorization_epoch": 1,
        "secret_reference": "msl_9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e",
        "client_id": "client-1",
        "api_key": "api-key-1",
        "verifier_actor": "kjds-external-verifier",
        "provisioner_actor": "kjds-lease-provisioner",
        "as_of": datetime.now(UTC),
    }
    value.update(changes)
    return value


def test_preflight_passes_and_provision_creates_lease(tmp_path):
    engine = database()
    service = seam(engine)
    values = inputs(readback_dir(tmp_path))
    verdict = service.preflight(**values)
    assert verdict["provision_allowed"] is True
    assert verdict["blockers"] == []

    result = service.provision(**values, created_by="lease-provisioner")
    assert result["lease_id"] == "lease-1"
    assert result["credential_material_returned"] is False
    assert "client_id" not in result
    assert "api_key" not in result
    assert result["external_verifier_observation_sha256"] == verdict["observation_sha256"]

    second = service.preflight(**values)
    assert second["provision_allowed"] is False
    assert "MANAGED_LEASE_ALREADY_EXISTS" in second["blockers"]


def test_provision_rejects_material_fingerprint_drift(tmp_path):
    engine = database()
    service = seam(engine)
    values = inputs(readback_dir(tmp_path), client_id="attacker-client")
    with pytest.raises(PermissionError, match="blocked"):
        service.provision(**values, created_by="lease-provisioner")
    with engine.begin() as connection:
        count = connection.execute(
            __import__("sqlalchemy").text(
                "SELECT count(*) FROM channel_managed_credential_leases"
            )
        ).scalar()
    assert count == 0


def test_provision_rejects_stale_readback_observation(tmp_path):
    engine = database()
    service = seam(engine)
    out = readback_dir(tmp_path)
    summary = json.loads((out / "readback-summary.json").read_text(encoding="utf-8"))
    summary["observed_at"] = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    (out / "readback-summary.json").write_text(
        json.dumps(summary, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(PermissionError, match="blocked"):
        service.provision(**inputs(out), created_by="lease-provisioner")


def test_provision_requires_matching_stored_observation(tmp_path):
    engine = database()
    service = seam(engine)
    out = readback_dir(tmp_path)
    (out / "readback-observation.json").write_text(
        json.dumps({"verdict": "failed", "observation_sha256": "0" * 64}),
        encoding="utf-8",
    )
    with pytest.raises(PermissionError, match="blocked"):
        service.provision(**inputs(out), created_by="lease-provisioner")
