from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.control_plane.channel_account_runtime_identity import (
    ManagedCredentialLeaseHandle,
    ScopedChannelCredentialClientFactory,
    SignedWorkerCredentialGrantAuthority,
    _WorkerCredentialGrantRecord,
)

NOW = datetime(2026, 8, 1, 8, tzinfo=UTC)


class GrantStore:
    def __init__(self, record):
        self.record = record
        self.consume_calls = []
        self.consumed = False

    def get(self, grant_id):
        return self.record if self.record and self.record.grant_id == grant_id else None

    def consume_once(self, *, grant_id, consumed_at, expected_envelope_sha256):
        self.consume_calls.append(
            (grant_id, consumed_at, expected_envelope_sha256)
        )
        if self.consumed or self.record is None or self.record.grant_id != grant_id:
            raise PermissionError("Worker credential grant replay was rejected")
        self.consumed = True
        self.record = replace(self.record, consumed_at=consumed_at)
        return self.record


class Resolver:
    def __init__(self):
        self.calls = []

    def resolve(self, **values):
        self.calls.append(values)
        return object()

    def accepts(self, _material):
        return True


class Builder:
    def __init__(self):
        self.calls = []
        self.closed = 0

    @contextmanager
    def __call__(self, material):
        self.calls.append(material)
        try:
            yield object()
        finally:
            self.closed += 1


def record(**changes):
    values = {
        "grant_id": "worker-grant-1",
        "issuer": "kjds-control-plane",
        "key_id": "grant-kid-1",
        "tenant_ref": "tenant-1",
        "entity_ref": "entity-1",
        "store_ref": "store-1",
        "platform": "ozon",
        "account_ref": "account-1",
        "adapter_id": "ozon-seller-api-read",
        "adapter_version": "v1",
        "required_capability": "catalog.read",
        "purpose": "pilot-read",
        "authorization_epoch": 1,
        "lease_handle": ManagedCredentialLeaseHandle(
            issuer="kjds-managed-store",
            key_id="lease-kid-1",
            lease_id="lease-1",
            envelope_sha256="a" * 64,
            signature="b" * 64,
        ),
        "secret_reference_sha256": "c" * 64,
        "credential_fingerprint_sha256": "d" * 64,
        "issued_at": NOW - timedelta(seconds=30),
        "expires_at": NOW + timedelta(seconds=30),
        "revoked_at": None,
        "consumed_at": None,
    }
    values.update(changes)
    return _WorkerCredentialGrantRecord(**values)


def setup(**record_changes):
    row = record(**record_changes)
    store = GrantStore(row)
    authority = SignedWorkerCredentialGrantAuthority(
        issuer="kjds-control-plane",
        key_id="grant-kid-1",
        signing_key=b"g" * 32,
        store=store,
    )
    grant = authority.issue(row)
    resolver = Resolver()
    builder = Builder()
    factory = ScopedChannelCredentialClientFactory(
        grant_authority=authority,
        grant_store=store,
        lease_resolver=resolver,
        client_builder=builder,
    )
    return row, store, authority, grant, resolver, builder, factory


def assert_rejected_before_builder(factory, builder, grant, *, message):
    with pytest.raises(PermissionError, match=message):
        factory.open(grant=grant, as_of=NOW)
    assert builder.calls == []
    assert builder.closed == 0


def test_valid_signed_grant_is_consumed_once_and_factory_closes_client():
    _row, store, _authority, grant, resolver, builder, factory = setup()

    with factory.open(grant=grant, as_of=NOW):
        assert len(builder.calls) == 1
        assert builder.closed == 0

    assert len(store.consume_calls) == 1
    assert len(resolver.calls) == 1
    assert builder.closed == 1


def test_transport_envelope_round_trips_across_worker_process_boundary():
    _row, store, _authority, grant, resolver, builder, factory = setup()

    with factory.open(grant=grant.transport_envelope(), as_of=NOW):
        pass

    assert len(store.consume_calls) == 1
    assert len(resolver.calls) == 1
    assert len(builder.calls) == 1


@pytest.mark.parametrize("mutation", ["extra", "missing", "contract"])
def test_transport_schema_confusion_is_rejected_before_authority_or_builder(mutation):
    _row, store, _authority, grant, resolver, builder, factory = setup()
    envelope = grant.transport_envelope()
    if mutation == "extra":
        envelope["tenant_ref"] = "attacker-selected"
    elif mutation == "missing":
        envelope.pop("signature")
    else:
        envelope["contract_id"] = "kjds-legacy-grant-v0"

    assert_rejected_before_builder(factory, builder, envelope, message="grant")
    assert store.consume_calls == []
    assert resolver.calls == []


@pytest.mark.parametrize(
    "grant_change",
    [
        {"signature": "0" * 64},
        {"envelope_sha256": "1" * 64},
        {"issuer": "attacker"},
        {"key_id": "attacker-kid"},
    ],
)
def test_forged_signed_grant_never_reaches_client_builder(grant_change):
    _row, _store, _authority, grant, _resolver, builder, factory = setup()
    forged = replace(grant, **grant_change)

    assert_rejected_before_builder(
        factory,
        builder,
        forged,
        message="grant",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_ref", "other-tenant"),
        ("entity_ref", "other-entity"),
        ("store_ref", "other-store"),
        ("platform", "other-platform"),
        ("account_ref", "other-account"),
        ("adapter_id", "other-adapter"),
        ("adapter_version", "v2"),
        ("required_capability", "catalog.write"),
        ("purpose", "listing-write"),
        ("authorization_epoch", 2),
    ],
)
def test_record_drift_after_issue_is_rejected_before_client_builder(field, value):
    row, store, _authority, grant, _resolver, builder, factory = setup()
    store.record = replace(row, **{field: value})

    assert_rejected_before_builder(factory, builder, grant, message="grant")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"expires_at": NOW}, "expired"),
        ({"revoked_at": NOW}, "revoked"),
        ({"issued_at": NOW + timedelta(seconds=1)}, "effective"),
    ],
)
def test_inactive_grant_never_reaches_client_builder(changes, message):
    _row, _store, _authority, grant, _resolver, builder, factory = setup(
        **changes
    )

    assert_rejected_before_builder(factory, builder, grant, message=message)


def test_single_use_grant_replay_fails_before_second_resolve_or_builder():
    _row, store, _authority, grant, resolver, builder, factory = setup()
    with factory.open(grant=grant, as_of=NOW):
        pass
    assert len(resolver.calls) == 1
    assert len(builder.calls) == 1

    with pytest.raises(PermissionError, match="consumed|replay|single-use"):
        factory.open(grant=grant, as_of=NOW)

    assert len(store.consume_calls) == 1
    assert len(resolver.calls) == 1
    assert len(builder.calls) == 1
    assert builder.closed == 1
