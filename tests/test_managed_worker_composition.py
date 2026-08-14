from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from apps.control_plane.causal_policies import CausalPolicyRow
from apps.control_plane.channel_account_runtime_identity import (
    SignedManagedCredentialLeaseResolver,
    register_server_bound_worker_resolver,
)
from apps.control_plane.channel_worker_runtime import (
    ManagedWorkerCredentialClientFactory,
)
from apps.control_plane.managed_credential_leases import (
    ManagedCredentialLeaseProvision,
    SqlManagedCredentialLeaseBindingSource,
    SqlManagedCredentialLeaseStore,
)
from apps.control_plane.ozon_worker import (
    OzonSellerClient,
    ozon_client_builder,
)
from apps.control_plane.pilot_readiness import ReadOnlyPilotRow
from apps.control_plane.policy_shadow import PolicyActivationHandoffRow
from apps.control_plane.scoped_worker_credential_grants import (
    CanonicalWorkerCredentialGrantIssuer,
)
from apps.control_plane.sql_repository import Base

assert CausalPolicyRow.__tablename__ == "causal_policies"
assert PolicyActivationHandoffRow.__tablename__ == "causal_policy_activation_handoffs"


@pytest.fixture()
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'compose.db'}")
    Base.metadata.create_all(engine)
    return engine


def provision():
    now = datetime.now(UTC)
    return ManagedCredentialLeaseProvision(
        lease_id="lease-composed-1",
        tenant_ref="tenant-1",
        entity_ref="entity-1",
        store_ref="store-1",
        platform="ozon",
        account_ref="account-1",
        adapter_id="ozon-seller-api-read",
        adapter_version="v1",
        capabilities={"catalog.read"},
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


def native_pilot_row():
    now = datetime.now(UTC)
    return ReadOnlyPilotRow(
        id="pilot-composed-1",
        idempotency_key="pilot-composed-1",
        platform="ozon",
        account_alias="ozon-main",
        allowed_operations_json=["ozon.product.read"],
        max_daily_requests=5,
        max_targets=2,
        starts_at=now - timedelta(hours=1),
        ends_at=now + timedelta(days=1),
        evidence_json=["evd-test"],
        status="active",
        requested_by="owner",
        reviewed_by="reviewer",
        review_rationale="approved",
        activated_by="admin",
        created_at=now,
        updated_at=now,
        tenant_ref="tenant-1",
        entity_ref="entity-1",
        store_ref="store-1",
        scope_grant_authority_sha256="e" * 64,
        scope_evidence_authority_sha256="7" * 64,
        scope_as_of=now,
    )


def test_sql_store_to_signed_grant_to_worker_client_round_trip(database):
    engine = database
    lease_store = SqlManagedCredentialLeaseStore(
        engine=engine,
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
    )
    lease_store.upsert_authoritative(provision(), created_by="lease-provisioner")
    resolver = SignedManagedCredentialLeaseResolver(
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
        signing_key=b"h" * 32,
        store=lease_store,
    )
    register_server_bound_worker_resolver(resolver)
    binding_source = SqlManagedCredentialLeaseBindingSource(
        store=lease_store,
        resolver=resolver,
    )
    issuer = CanonicalWorkerCredentialGrantIssuer(
        grant_issuer="kjds-control-plane",
        grant_key_id="grant-kid-1",
        signing_key=b"g" * 32,
        lease_source=binding_source,
    )
    as_of = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        grant = issuer.issue_for_pilot_run(
            session=session,
            pilot=native_pilot_row(),
            run_id="run-composed-1",
            operation="ozon.product.read",
            worker_id="reader-1",
            as_of=as_of,
        )
    assert grant is not None
    assert grant["required_capability"] == "catalog.read"

    factory = ManagedWorkerCredentialClientFactory(
        engine=engine,
        grant_issuer="kjds-control-plane",
        grant_key_id="grant-kid-1",
        signing_key=b"g" * 32,
        lease_resolver=resolver,
        client_builder=ozon_client_builder,
    )
    with factory.open(grant=grant, as_of=as_of) as client:
        assert isinstance(client, OzonSellerClient)
        assert client._credentials.is_runtime_attested() is True

    with pytest.raises(PermissionError, match="consumed"):
        factory.open(grant=grant, as_of=as_of)


def test_forged_grant_never_reaches_worker_client_builder(database):
    engine = database
    lease_store = SqlManagedCredentialLeaseStore(
        engine=engine,
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
    )
    lease_store.upsert_authoritative(provision(), created_by="lease-provisioner")
    resolver = SignedManagedCredentialLeaseResolver(
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
        signing_key=b"h" * 32,
        store=lease_store,
    )
    register_server_bound_worker_resolver(resolver)
    binding_source = SqlManagedCredentialLeaseBindingSource(
        store=lease_store,
        resolver=resolver,
    )
    issuer = CanonicalWorkerCredentialGrantIssuer(
        grant_issuer="kjds-control-plane",
        grant_key_id="grant-kid-1",
        signing_key=b"g" * 32,
        lease_source=binding_source,
    )
    as_of = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        grant = issuer.issue_for_pilot_run(
            session=session,
            pilot=native_pilot_row(),
            run_id="run-forged-1",
            operation="ozon.product.read",
            worker_id="reader-1",
            as_of=as_of,
        )
    forged = {**grant, "signature": "0" * 64}

    opens = []

    def counting_builder(material, _resolver):
        opens.append(material)
        return nullcontext(object())

    factory = ManagedWorkerCredentialClientFactory(
        engine=engine,
        grant_issuer="kjds-control-plane",
        grant_key_id="grant-kid-1",
        signing_key=b"g" * 32,
        lease_resolver=resolver,
        client_builder=counting_builder,
    )
    with pytest.raises(PermissionError, match="signature is invalid"):
        factory.open(grant=forged, as_of=as_of)
    assert opens == []
