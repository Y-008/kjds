from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.causal_policies import CausalPolicyRow
from apps.control_plane.channel_account_runtime_identity import (
    SignedManagedCredentialLeaseResolver,
)
from apps.control_plane.managed_credential_leases import (
    ManagedCredentialLeaseProvision,
    ManagedCredentialLeaseRow,
    SqlManagedCredentialLeaseStore,
)
from apps.control_plane.policy_shadow import PolicyActivationHandoffRow
from apps.control_plane.sql_repository import Base

NOW = datetime(2026, 8, 1, 8, tzinfo=UTC)

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


def provision(**changes):
    now = datetime.now(UTC)
    values = {
        "lease_id": "lease-1",
        "tenant_ref": "tenant-1",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
        "platform": "ozon",
        "account_ref": "account-1",
        "adapter_id": "ozon-seller-api-read",
        "adapter_version": "v1",
        "capabilities": {"catalog.read", "finance.read"},
        "authorization_epoch": 1,
        "secret_reference": "msl_9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f4a3b2c1d0e",
        "client_id": "client-1",
        "api_key": "api-key-1",
        "issued_at": now - timedelta(minutes=30),
        "expires_at": now + timedelta(hours=2),
        "provider_readback_sha256": "f" * 64,
        "provider_readback_verified_at": now - timedelta(seconds=30),
        "external_verifier_observation_sha256": "9" * 64,
        "external_verifier_verified_at": now - timedelta(seconds=30),
    }
    values.update(changes)
    return ManagedCredentialLeaseProvision(**values)


def make_store(database):
    return SqlManagedCredentialLeaseStore(
        engine=database,
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
    )


def resolver(database):
    return SignedManagedCredentialLeaseResolver(
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
        signing_key=b"h" * 32,
        store=make_store(database),
    )


def test_upsert_is_idempotent_and_derives_fingerprint_server_side():
    database = engine()
    lease_store = make_store(database)
    initial = provision()
    record = lease_store.upsert_authoritative(
        initial,
        created_by="lease-provisioner",
    )
    expected_fingerprint = SignedManagedCredentialLeaseResolver.credential_fingerprint(
        client_id="client-1",
        api_key="api-key-1",
        platform="ozon",
        account_ref="account-1",
    )
    assert record.credential_fingerprint_sha256 == expected_fingerprint
    assert record.client_id == "client-1"
    assert record.api_key == "api-key-1"

    replay = lease_store.upsert_authoritative(
        initial,
        created_by="lease-provisioner",
    )
    assert replay == record
    with Session(database) as session:
        assert session.query(ManagedCredentialLeaseRow).count() == 1

    loaded = lease_store.get("lease-1")
    assert loaded == record


def test_provision_rejects_invalid_reference_hashes_and_epochs():
    with pytest.raises(ValueError, match="msl namespace"):
        provision(secret_reference="not-an-msl-locator")
    with pytest.raises(ValueError, match="SHA-256"):
        provision(provider_readback_sha256="short")
    with pytest.raises(ValueError, match="positive integer"):
        provision(authorization_epoch=0)
    with pytest.raises(ValueError, match="after issued_at"):
        provision(expires_at=NOW - timedelta(hours=1))
    with pytest.raises(ValueError, match="at least one capability"):
        provision(capabilities=set())


def test_rotation_epoch_drift_fails_closed():
    database = engine()
    lease_store = make_store(database)
    lease_store.upsert_authoritative(
        provision(authorization_epoch=1),
        created_by="lease-provisioner",
    )
    with pytest.raises(ValueError, match="epoch drifted"):
        lease_store.upsert_authoritative(
            provision(
                lease_id="lease-2",
                authorization_epoch=2,
            ),
            created_by="lease-provisioner",
            expected_previous_epoch=3,
        )
    assert lease_store.get("lease-2") is None


def test_revoke_is_single_use_and_bounded_by_issuance():
    database = engine()
    lease_store = make_store(database)
    now = datetime.now(UTC)
    lease_store.upsert_authoritative(provision(), created_by="lease-provisioner")
    lease_store.revoke("lease-1", revoked_at=now, revoked_by="lease-admin")
    assert lease_store.get("lease-1").revoked_at is not None
    with pytest.raises(ValueError, match="already revoked"):
        lease_store.revoke("lease-1", revoked_at=now, revoked_by="lease-admin")


def test_revoke_before_issuance_is_rejected():
    database = engine()
    lease_store = make_store(database)
    now = datetime.now(UTC)
    lease_store.upsert_authoritative(
        provision(
            lease_id="lease-2",
            authorization_epoch=2,
            issued_at=now + timedelta(hours=1),
            expires_at=now + timedelta(hours=2),
        ),
        created_by="lease-provisioner",
    )
    with pytest.raises(ValueError, match="before issuance"):
        lease_store.revoke("lease-2", revoked_at=now, revoked_by="lease-admin")


def test_signed_handle_and_resolution_work_against_sql_store():
    database = engine()
    lease_store = make_store(database)
    record = lease_store.upsert_authoritative(
        provision(),
        created_by="lease-provisioner",
    )
    lease_resolver = resolver(database)
    handle = lease_store.sign_handle(resolver=lease_resolver, lease_id="lease-1")
    as_of = datetime.now(UTC)
    lease_resolver.require_current_handle(handle=handle, as_of=as_of)

    material = lease_resolver.resolve(
        handle=handle,
        scope={
            "tenant_ref": "tenant-1",
            "entity_ref": "entity-1",
            "store_ref": "store-1",
        },
        platform="ozon",
        account_ref="account-1",
        adapter_id="ozon-seller-api-read",
        adapter_version="v1",
        required_capability="catalog.read",
        secret_reference_sha256=record.secret_reference_sha256,
        credential_fingerprint_sha256=record.credential_fingerprint_sha256,
        as_of=as_of,
    )
    assert material.client_id == "client-1"
    assert material.api_key == "api-key-1"
    assert lease_resolver.accepts(material) is True


def test_identity_drift_between_store_and_resolver_is_rejected():
    database = engine()
    lease_store = make_store(database)
    record = lease_store.upsert_authoritative(
        provision(),
        created_by="lease-provisioner",
    )
    other = SqlManagedCredentialLeaseStore(
        engine=database,
        issuer="other-issuer",
        key_id="other-kid",
    )
    other_resolver = SignedManagedCredentialLeaseResolver(
        issuer="other-issuer",
        key_id="other-kid",
        signing_key=b"i" * 32,
        store=other,
    )
    with pytest.raises(PermissionError, match="issuer is unknown"):
        other_resolver.require_current_handle(
            handle=lease_store.sign_handle(
                resolver=resolver(database),
                lease_id="lease-1",
            ),
            as_of=NOW,
        )
    assert record is not None
