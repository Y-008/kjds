from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.causal_policies import CausalPolicyRow
from apps.control_plane.channel_account_runtime_identity import (
    SignedManagedCredentialLeaseResolver,
)
from apps.control_plane.managed_credential_leases import (
    ManagedCredentialLeaseProvision,
    SqlManagedCredentialLeaseStore,
    SqlManagedStoreRuntimeIdentityVerifier,
)
from apps.control_plane.policy_shadow import PolicyActivationHandoffRow
from apps.control_plane.sql_repository import Base

assert CausalPolicyRow.__tablename__ == "causal_policies"
assert PolicyActivationHandoffRow.__tablename__ == "causal_policy_activation_handoffs"


def engine():
    database = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(database)
    return database


def provision(now=None):
    now = now or datetime.now(UTC)
    return ManagedCredentialLeaseProvision(
        lease_id="lease-runtime-1",
        tenant_ref="tenant-1",
        entity_ref="entity-1",
        store_ref="store-1",
        platform="ozon",
        account_ref="account-1",
        adapter_id="ozon-seller-api-read",
        adapter_version="v1",
        capabilities={"catalog.read", "finance.read"},
        authorization_epoch=1,
        secret_reference="msl_9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e",
        client_id="client-1",
        api_key="api-key-1",
        issued_at=now - timedelta(minutes=30),
        expires_at=now + timedelta(hours=2),
        provider_readback_sha256="f" * 64,
        provider_readback_verified_at=now - timedelta(seconds=30),
        external_verifier_observation_sha256="9" * 64,
        external_verifier_verified_at=now - timedelta(seconds=30),
    )


def scope(**changes):
    value = {
        "tenant_ref": "tenant-1",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
        "scope_grant_authority_sha256": "e" * 64,
    }
    value.update(changes)
    return value


def probe(now=None):
    now = now or datetime.now(UTC)
    return {
        "scope": scope(),
        "platform": "ozon",
        "account_ref": "account-1",
        "adapter_id": "ozon-seller-api-read",
        "adapter_version": "v1",
        "capabilities": ["catalog.read"],
        "secret_reference_sha256": "x" * 64,
        "credential_fingerprint_sha256": "y" * 64,
        "as_of": now,
    }


def fingerprint_for_lease(provision_value):
    return SignedManagedCredentialLeaseResolver.credential_fingerprint(
        client_id=provision_value.client_id,
        api_key=provision_value.api_key,
        platform=provision_value.platform,
        account_ref=provision_value.account_ref,
    )


def test_empty_store_projects_no_data_without_secret_reads():
    database = engine()
    verifier = SqlManagedStoreRuntimeIdentityVerifier(engine=database)
    result = verifier.verify(**probe())
    assert result["status"] == "no_data"
    assert result["managed_store_bound"] is False
    assert "channel_account_managed_store_lease_missing" in result["source_gaps"]
    assert result["secret_values_returned"] is False


def test_current_lease_with_fresh_verifier_passes_runtime_probe():
    database = engine()
    now = datetime.now(UTC)
    lease_store = SqlManagedCredentialLeaseStore(
        engine=database,
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
    )
    record = lease_store.upsert_authoritative(
        provision(now),
        created_by="lease-provisioner",
    )
    values = probe(now)
    values["secret_reference_sha256"] = record.secret_reference_sha256
    values["credential_fingerprint_sha256"] = record.credential_fingerprint_sha256
    result = SqlManagedStoreRuntimeIdentityVerifier(engine=database).verify(**values)
    assert result["status"] == "fresh_passed"
    assert result["managed_store_bound"] is True
    assert result["lease_fresh"] is True
    assert result["fingerprint_match"] is True
    assert result["scope_match"] is True
    assert result["capabilities_match"] is True
    assert result["provider_readback_fresh_passed"] is True
    assert result["external_verifier_fresh_passed"] is True
    assert result["source_gaps"] == []


def test_stale_provider_readback_projects_stale():
    database = engine()
    now = datetime.now(UTC)
    lease_store = SqlManagedCredentialLeaseStore(
        engine=database,
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
    )
    record = lease_store.upsert_authoritative(
        provision(now),
        created_by="lease-provisioner",
    )
    with database.begin() as connection:
        connection.execute(
            __import__("sqlalchemy").text(
                "UPDATE channel_managed_credential_leases "
                "SET provider_readback_verified_at = :stale WHERE lease_id = :lease_id"
            ),
            {
                "stale": now - timedelta(hours=2),
                "lease_id": "lease-runtime-1",
            },
        )
    values = probe(now)
    values["secret_reference_sha256"] = record.secret_reference_sha256
    values["credential_fingerprint_sha256"] = record.credential_fingerprint_sha256
    result = SqlManagedStoreRuntimeIdentityVerifier(engine=database).verify(**values)
    assert result["status"] == "stale"
    assert result["provider_readback_fresh_passed"] is False
    assert "channel_account_managed_store_lease_stale" in result["source_gaps"]


def test_revoked_or_expired_lease_projects_no_data():
    database = engine()
    now = datetime.now(UTC)
    lease_store = SqlManagedCredentialLeaseStore(
        engine=database,
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
    )
    lease_store.upsert_authoritative(provision(now), created_by="lease-provisioner")
    lease_store.revoke("lease-runtime-1", revoked_at=now, revoked_by="lease-admin")
    result = SqlManagedStoreRuntimeIdentityVerifier(engine=database).verify(**probe(now))
    assert result["status"] == "no_data"
    assert result["managed_store_bound"] is False


def test_fingerprint_and_capability_drift_project_blocked():
    database = engine()
    now = datetime.now(UTC)
    lease_store = SqlManagedCredentialLeaseStore(
        engine=database,
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
    )
    record = lease_store.upsert_authoritative(
        provision(now),
        created_by="lease-provisioner",
    )
    values = probe(now)
    values["secret_reference_sha256"] = record.secret_reference_sha256
    values["credential_fingerprint_sha256"] = "0" * 64
    result = SqlManagedStoreRuntimeIdentityVerifier(engine=database).verify(**values)
    assert result["status"] == "blocked"
    assert result["fingerprint_match"] is False
    assert "channel_account_managed_store_fingerprint_drift" in result["source_gaps"]

    values["credential_fingerprint_sha256"] = record.credential_fingerprint_sha256
    values["capabilities"] = ["catalog.write"]
    result = SqlManagedStoreRuntimeIdentityVerifier(engine=database).verify(**values)
    assert result["status"] == "blocked"
    assert result["capabilities_match"] is False
    assert "channel_account_managed_store_capability_drift" in result["source_gaps"]
