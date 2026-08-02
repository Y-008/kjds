from contextlib import nullcontext
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session

from apps.control_plane.causal_policies import CausalPolicyRow
from apps.control_plane.channel_account_runtime_identity import (
    SignedManagedCredentialLeaseResolver,
    SignedWorkerCredentialGrantAuthority,
    register_server_bound_worker_resolver,
)
from apps.control_plane.channel_credential_grants import (
    SqlWorkerCredentialGrantStore,
    WorkerCredentialGrantRow,
)
from apps.control_plane.channel_worker_runtime import (
    ManagedWorkerCredentialClientFactory,
)
from apps.control_plane.managed_credential_leases import (
    ManagedCredentialLeaseProvision,
    ManagedCredentialLeaseRow,
    SqlManagedCredentialLeaseBindingSource,
    SqlManagedCredentialLeaseStore,
)
from apps.control_plane.pilot_readiness import ReadOnlyPilotRow
from apps.control_plane.policy_shadow import PolicyActivationHandoffRow
from apps.control_plane.scoped_worker_credential_grants import (
    CanonicalWorkerCredentialGrantIssuer,
)
from apps.control_plane.sql_repository import Base

assert CausalPolicyRow.__tablename__ == "causal_policies"
assert PolicyActivationHandoffRow.__tablename__ == "causal_policy_activation_handoffs"


def composition(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'negative.db'}")
    Base.metadata.create_all(engine)
    now = datetime.now(UTC)
    lease_store = SqlManagedCredentialLeaseStore(
        engine=engine,
        issuer="kjds-managed-store",
        key_id="lease-kid-1",
    )
    lease_store.upsert_authoritative(
        ManagedCredentialLeaseProvision(
            lease_id="lease-neg-1",
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
        ),
        created_by="lease-provisioner",
    )
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
    pilot = ReadOnlyPilotRow(
        id="pilot-neg-1",
        idempotency_key="pilot-neg-1",
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
    as_of = now
    with Session(engine) as session, session.begin():
        grant = issuer.issue_for_pilot_run(
            session=session,
            pilot=pilot,
            run_id="run-neg-1",
            operation="ozon.product.read",
            worker_id="reader-1",
            as_of=as_of,
        )
    with Session(engine) as session:
        row = session.get(WorkerCredentialGrantRow, grant["grant_id"])
        original_row = {
            column.name: getattr(row, column.name)
            for column in WorkerCredentialGrantRow.__table__.columns
        }
    return engine, lease_store, resolver, grant, as_of, original_row


def mutate_grant_row(engine, grant_id, **values):
    with Session(engine) as session, session.begin():
        session.execute(
            update(WorkerCredentialGrantRow)
            .where(WorkerCredentialGrantRow.grant_id == grant_id)
            .values(**values)
        )


def mutate_lease_row(engine, lease_id, **values):
    with Session(engine) as session, session.begin():
        session.execute(
            update(ManagedCredentialLeaseRow)
            .where(ManagedCredentialLeaseRow.lease_id == lease_id)
            .values(**values)
        )


def grant_consumed(engine, grant_id):
    with Session(engine) as session:
        return session.get(WorkerCredentialGrantRow, grant_id).consumed_at is not None


def resign_grant(engine, grant_id):
    """Re-sign the transport envelope after a server-side row mutation."""
    with Session(engine) as session:
        store = SqlWorkerCredentialGrantStore(session)
        record = store.get(grant_id)
        authority = SignedWorkerCredentialGrantAuthority(
            issuer="kjds-control-plane",
            key_id="grant-kid-1",
            signing_key=b"g" * 32,
            store=store,
        )
        return authority.issue(record).transport_envelope()


def test_negative_proofs_zero_builder_zero_client_zero_network(tmp_path, monkeypatch):
    engine, lease_store, resolver, grant, as_of, original_row = composition(tmp_path)
    constructed = []
    monkeypatch.setattr(
        "apps.control_plane.ozon_worker.httpx.Client",
        lambda *args, **kwargs: constructed.append((args, kwargs)),
    )
    opens = []

    def counting_builder(material, _resolver):
        opens.append(material)
        return nullcontext(object())

    def factory():
        return ManagedWorkerCredentialClientFactory(
            engine=engine,
            grant_issuer="kjds-control-plane",
            grant_key_id="grant-kid-1",
            signing_key=b"g" * 32,
            lease_resolver=resolver,
            client_builder=counting_builder,
        )

    cases = [
        (
            "forged_signature",
            {**grant, "signature": "0" * 64},
            "signature is invalid",
            None,
        ),
        (
            "forged_envelope",
            {**grant, "envelope_sha256": "1" * 64},
            "signature is invalid",
            None,
        ),
        (
            "unknown_issuer",
            {**grant, "issuer": "attacker"},
            "issuer is unknown",
            None,
        ),
        (
            "missing_grant",
            {**grant, "grant_id": "wcg_does_not_exist"},
            "does not exist",
            None,
        ),
        (
            "cross_scope_store",
            grant,
            "signature is invalid",
            lambda: mutate_grant_row(
                engine,
                grant["grant_id"],
                store_ref="other-store",
            ),
        ),
        (
            "capability_drift",
            {**grant, "required_capability": "catalog.write"},
            "capability drift",
            None,
        ),
        (
            "expired",
            None,
            "expired",
            lambda: (
                mutate_grant_row(
                    engine,
                    grant["grant_id"],
                    issued_at=as_of - timedelta(seconds=60),
                    expires_at=as_of - timedelta(seconds=1),
                ),
                resign_grant(engine, grant["grant_id"]),
            ),
        ),
        (
            "revoked",
            None,
            "revoked",
            lambda: (
                mutate_grant_row(
                    engine,
                    grant["grant_id"],
                    revoked_at=as_of,
                ),
                resign_grant(engine, grant["grant_id"]),
            ),
        ),
    ]
    for name, attempt, message, mutation in cases:
        opens.clear()
        constructed.clear()
        restore_values = {
            key: value for key, value in original_row.items() if key != "grant_id"
        }
        mutate_grant_row(engine, grant["grant_id"], **restore_values)
        if attempt is None:
            attempt = grant
        if mutation is not None:
            result = mutation()
            if isinstance(result, tuple):
                attempt = result[1]
        with pytest.raises(PermissionError, match=message):
            factory().open(grant=attempt, as_of=as_of)
        assert opens == [], f"{name}: builder must never run"
        assert constructed == [], f"{name}: no provider client may be constructed"
        assert grant_consumed(engine, grant["grant_id"]) is False, (
            f"{name}: failed grant must not be consumed"
        )


def test_replayed_grant_fails_before_second_builder_call(tmp_path):
    engine, lease_store, resolver, grant, as_of, _original_row = composition(tmp_path)
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
    with factory.open(grant=grant, as_of=as_of):
        pass
    assert len(opens) == 1
    with pytest.raises(PermissionError, match="already consumed"):
        factory.open(grant=grant, as_of=as_of)
    assert len(opens) == 1


def test_stale_lease_fails_after_consumption_before_builder(tmp_path):
    engine, lease_store, resolver, grant, as_of, _original_row = composition(tmp_path)
    opens = []

    def counting_builder(material, _resolver):
        opens.append(material)
        return nullcontext(object())

    mutate_lease_row(
        engine,
        "lease-neg-1",
        provider_readback_verified_at=as_of - timedelta(hours=2),
    )
    handle = lease_store.sign_handle(
        resolver=resolver,
        lease_id="lease-neg-1",
    )
    mutate_grant_row(
        engine,
        grant["grant_id"],
        lease_envelope_sha256=handle.envelope_sha256,
        lease_signature=handle.signature,
    )
    grant = resign_grant(engine, grant["grant_id"])
    factory = ManagedWorkerCredentialClientFactory(
        engine=engine,
        grant_issuer="kjds-control-plane",
        grant_key_id="grant-kid-1",
        signing_key=b"g" * 32,
        lease_resolver=resolver,
        client_builder=counting_builder,
    )
    with pytest.raises(PermissionError, match="verifier observation is stale"):
        factory.open(grant=grant, as_of=as_of)
    assert opens == []
    # Consumption and lease resolution share one transaction, so a stale lease
    # rolls the redemption back atomically: the grant is not burned and no
    # provider client or credential material ever leaves the boundary.
    assert grant_consumed(engine, grant["grant_id"]) is False
