from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.control_plane import ozon_worker
from apps.control_plane.channel_account_runtime_identity import (
    SignedManagedCredentialLeaseResolver,
    _ManagedCredentialLeaseRecord,
    require_managed_channel_credential_resolution,
)
from apps.control_plane.ozon_worker import (
    ChannelCredentialAuthorizationError,
    OzonCredentials,
    OzonSellerClient,
    resolve_ozon_worker_credentials,
)

NOW = datetime.now(UTC)
SCOPE = {
    "tenant_ref": "tenant-a",
    "entity_ref": "entity-a",
    "store_ref": "ozon-primary",
}


class Store:
    def __init__(self, record):
        self.record = record

    def get(self, lease_id):
        if self.record is None or self.record.lease_id != lease_id:
            return None
        return self.record


class RecordingEnvironment(Mapping):
    def __init__(self, values):
        self.values = dict(values)
        self.accessed = []

    def __getitem__(self, key):
        self.accessed.append(key)
        return self.values[key]

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)


def setup_record(**changes):
    client_id = "client-private-a"
    api_key = "api-private-a"
    fingerprint = SignedManagedCredentialLeaseResolver.credential_fingerprint(
        client_id=client_id,
        api_key=api_key,
        platform="ozon",
        account_ref="account-a",
    )
    values = {
        "lease_id": "lease-a",
        "issuer": "kjds-managed-store",
        "key_id": "kid-a",
        **SCOPE,
        "platform": "ozon",
        "account_ref": "account-a",
        "adapter_id": "ozon-seller-api-read",
        "adapter_version": "v1",
        "capabilities": frozenset({"catalog.read"}),
        "secret_reference_sha256": "a" * 64,
        "credential_fingerprint_sha256": fingerprint,
        "issued_at": NOW - timedelta(minutes=2),
        "expires_at": NOW + timedelta(minutes=2),
        "revoked_at": None,
        "client_id": client_id,
        "api_key": api_key,
        "provider_readback_sha256": "b" * 64,
        "provider_readback_verified_at": NOW - timedelta(minutes=1),
        "external_verifier_observation_sha256": "c" * 64,
        "external_verifier_verified_at": NOW - timedelta(minutes=1),
    }
    values.update(changes)
    record = _ManagedCredentialLeaseRecord(**values)
    store = Store(record)
    resolver = SignedManagedCredentialLeaseResolver(
        issuer="kjds-managed-store",
        key_id="kid-a",
        signing_key=b"k" * 32,
        store=store,
    )
    handle = resolver.sign_authoritative_record(record)
    return record, store, resolver, handle


def resolve(resolver, handle, **changes):
    values = {
        "handle": handle,
        "scope": SCOPE,
        "platform": "ozon",
        "account_ref": "account-a",
        "adapter_id": "ozon-seller-api-read",
        "adapter_version": "v1",
        "required_capability": "catalog.read",
        "secret_reference_sha256": "a" * 64,
        "credential_fingerprint_sha256": (
            resolver.credential_fingerprint(
                client_id="client-private-a",
                api_key="api-private-a",
                platform="ozon",
                account_ref="account-a",
            )
        ),
        "as_of": NOW,
    }
    values.update(changes)
    return resolver.resolve(**values)


def test_signed_server_record_is_required_and_secrets_are_not_in_handle():
    _record, _store, resolver, handle = setup_record()
    material = resolve(resolver, handle)
    assert resolver.accepts(material) is True
    assert "private" not in repr(handle)
    assert "private" not in str(handle.safe_projection())
    with pytest.raises(
        ChannelCredentialAuthorizationError,
        match="server-bound",
    ):
        OzonCredentials.from_resolved_lease(
            resolver=resolver,
            handle=handle,
            tenant_ref=SCOPE["tenant_ref"],
            entity_ref=SCOPE["entity_ref"],
            store_ref=SCOPE["store_ref"],
            account_ref="account-a",
            adapter_id="ozon-seller-api-read",
            adapter_version="v1",
            required_capability="catalog.read",
            secret_reference_sha256="a" * 64,
            credential_fingerprint_sha256=(
                material.credential_fingerprint_sha256
            ),
            as_of=NOW,
        )


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("forged", "signature"),
        ("expired", "expired"),
        ("revoked", "revoked"),
        ("cross_scope", "exact-scope"),
        ("fingerprint", "fingerprint"),
        ("unknown_issuer", "issuer"),
    ],
)
def test_untrusted_or_stale_lease_fails_before_material_is_returned(
    kind,
    message,
):
    record, store, resolver, handle = setup_record()
    values = {}
    if kind == "forged":
        handle = replace(handle, signature="0" * 64)
    elif kind == "expired":
        store.record = replace(
            record,
            expires_at=NOW - timedelta(seconds=1),
        )
        handle = resolver.sign_authoritative_record(store.record)
    elif kind == "revoked":
        store.record = replace(
            record,
            revoked_at=NOW - timedelta(seconds=1),
        )
        handle = resolver.sign_authoritative_record(store.record)
    elif kind == "cross_scope":
        values["scope"] = {**SCOPE, "store_ref": "other-store"}
    elif kind == "fingerprint":
        values["credential_fingerprint_sha256"] = "f" * 64
    elif kind == "unknown_issuer":
        handle = replace(handle, issuer="attacker")
    with pytest.raises(PermissionError, match=message):
        resolve(resolver, handle, **values)


def test_default_worker_path_and_env_only_credentials_fail_before_client(
    monkeypatch,
):
    constructed = []
    monkeypatch.setattr(
        ozon_worker.httpx,
        "Client",
        lambda *args, **kwargs: constructed.append((args, kwargs)),
    )
    with pytest.raises(RuntimeError, match="Environment-only channel credential resolution is closed"):
        require_managed_channel_credential_resolution()
    with pytest.raises(RuntimeError, match="Environment-only"):
        OzonCredentials.from_environment()
    with pytest.raises(
        ChannelCredentialAuthorizationError,
        match="cannot be constructed directly",
    ):
        OzonCredentials("env-client", "env-key")
    with pytest.raises(
        ChannelCredentialAuthorizationError,
        match="resolver-attested",
    ):
        OzonSellerClient(
            OzonCredentials.for_test_fixture(
                client_id="env-client",
                api_key="env-key",
            ),
        )
    assert constructed == []


def test_unbound_worker_admission_reads_no_sensitive_environment(
    monkeypatch,
):
    environment = RecordingEnvironment(
        {
            "KJDS_EXECUTOR_API_KEY": "must-not-read",
            "KJDS_CHANNEL_SECRET_REFERENCE_SHA256": "a" * 64,
            "KJDS_CHANNEL_CREDENTIAL_FINGERPRINT_SHA256": "b" * 64,
        }
    )
    monkeypatch.setattr(
        ozon_worker,
        "require_managed_channel_credential_resolution",
        lambda: (_ for _ in ()).throw(RuntimeError("resolver is not bound")),
    )
    with pytest.raises(RuntimeError, match="resolver is not bound"):
        resolve_ozon_worker_credentials(
            required_capability="catalog.read",
            environment=environment,
            as_of=NOW,
        )
    assert environment.accessed == []


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": NOW - timedelta(seconds=1)},
        {"revoked_at": NOW - timedelta(seconds=1)},
    ],
)
def test_stale_handle_fails_before_sensitive_environment_or_client(
    monkeypatch,
    changes,
):
    _record, _store, resolver, handle = setup_record(**changes)
    environment = RecordingEnvironment(
        {
            "KJDS_PILOT_READER_API_KEY": "must-not-read",
            "KJDS_CHANNEL_SECRET_REFERENCE_SHA256": "a" * 64,
            "KJDS_CHANNEL_CREDENTIAL_FINGERPRINT_SHA256": "b" * 64,
        }
    )
    constructed = []
    monkeypatch.setattr(
        ozon_worker,
        "require_managed_channel_credential_resolution",
        lambda: (resolver, handle),
    )
    monkeypatch.setattr(
        ozon_worker,
        "_is_server_bound_worker_resolver",
        lambda candidate: candidate is resolver,
    )
    monkeypatch.setattr(
        ozon_worker.httpx,
        "Client",
        lambda *args, **kwargs: constructed.append((args, kwargs)),
    )
    with pytest.raises(PermissionError, match="expired|revoked"):
        resolve_ozon_worker_credentials(
            required_capability="catalog.read",
            environment=environment,
            as_of=NOW,
        )
    assert environment.accessed == []
    assert constructed == []


def test_unattested_fixture_cannot_use_a_real_transport_or_construct_client(
    monkeypatch,
):
    constructed = []
    monkeypatch.setattr(
        ozon_worker.httpx,
        "Client",
        lambda *args, **kwargs: constructed.append((args, kwargs)),
    )
    transport = ozon_worker.httpx.HTTPTransport()
    try:
        with pytest.raises(
            ChannelCredentialAuthorizationError,
            match="resolver-attested",
        ):
            OzonSellerClient(
                OzonCredentials.for_test_fixture(
                    client_id="forged-client",
                    api_key="forged-key",
                ),
                transport=transport,
            )
    finally:
        transport.close()
    assert constructed == []


def test_public_or_forged_resolver_never_enters_client_factory(
    monkeypatch,
):
    _record, _store, resolver, handle = setup_record()
    constructed = []
    monkeypatch.setattr(
        ozon_worker.httpx,
        "Client",
        lambda *args, **kwargs: constructed.append((args, kwargs)),
    )
    with pytest.raises(
        ChannelCredentialAuthorizationError,
        match="server-bound",
    ):
        OzonCredentials.from_resolved_lease(
            resolver=resolver,
            handle=handle,
            tenant_ref=SCOPE["tenant_ref"],
            entity_ref=SCOPE["entity_ref"],
            store_ref=SCOPE["store_ref"],
            account_ref="account-a",
            adapter_id="ozon-seller-api-read",
            adapter_version="v1",
            required_capability="catalog.read",
            secret_reference_sha256="a" * 64,
            credential_fingerprint_sha256=(
                resolver.credential_fingerprint(
                    client_id="client-private-a",
                    api_key="api-private-a",
                    platform="ozon",
                    account_ref="account-a",
                )
            ),
            as_of=NOW,
        )
    assert constructed == []


def test_resolver_material_attestation_rejects_single_field_tamper():
    _record, _store, resolver, handle = setup_record()
    material = resolve(resolver, handle)
    assert resolver.accepts(material) is True
    assert resolver.accepts(replace(material, api_key="attacker-secret")) is False


def test_resolver_is_final_and_duck_type_cannot_override_production_trust(
    monkeypatch,
):
    with pytest.raises(TypeError, match="final"):

        class MaliciousResolver(SignedManagedCredentialLeaseResolver):
            pass

    class DuckResolver:
        def resolve(self, **_values):
            raise AssertionError("duck resolver must not resolve credential material")

        def accepts(self, _material):
            return True

        def is_worker_admission_trusted(self):
            return True

    constructed = []
    monkeypatch.setattr(
        ozon_worker.httpx,
        "Client",
        lambda *args, **kwargs: constructed.append((args, kwargs)),
    )
    _record, _store, _resolver, handle = setup_record()
    with pytest.raises(
        ChannelCredentialAuthorizationError,
        match="server-bound",
    ):
        OzonCredentials.from_resolved_lease(
            resolver=DuckResolver(),
            handle=handle,
            tenant_ref=SCOPE["tenant_ref"],
            entity_ref=SCOPE["entity_ref"],
            store_ref=SCOPE["store_ref"],
            account_ref="account-a",
            adapter_id="ozon-seller-api-read",
            adapter_version="v1",
            required_capability="catalog.read",
            secret_reference_sha256="a" * 64,
            credential_fingerprint_sha256="b" * 64,
            as_of=NOW,
        )
    assert constructed == []


@pytest.mark.parametrize(
    "changes",
    [
        {"revoked_at": NOW - timedelta(seconds=1)},
        {"expires_at": NOW - timedelta(seconds=1)},
        {"capabilities": frozenset({"finance.read"})},
        {"credential_fingerprint_sha256": "f" * 64},
    ],
)
def test_material_rechecks_current_authoritative_store_row(changes):
    record, store, resolver, handle = setup_record()
    material = resolve(resolver, handle)
    assert resolver.accepts(material) is True
    store.record = replace(record, **changes)
    assert resolver.accepts(material) is False


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
    ],
)
def test_resolver_rejects_each_exact_scope_axis_deterministically(field, value):
    _record, _store, resolver, handle = setup_record()
    changes = {}
    if field in SCOPE:
        changes["scope"] = {**SCOPE, field: value}
    else:
        changes[field] = value

    with pytest.raises(PermissionError, match="exact-scope"):
        resolve(resolver, handle, **changes)


@pytest.mark.parametrize("capability", ["finance.read", "catalog.write", ""])
def test_resolver_rejects_capability_drift_without_returning_material(capability):
    _record, _store, resolver, handle = setup_record()

    with pytest.raises(PermissionError, match="capability"):
        resolve(
            resolver,
            handle,
            required_capability=capability,
        )


@pytest.mark.parametrize(
    ("record_change", "message"),
    [
        ({"expires_at": NOW}, "expired"),
        ({"revoked_at": NOW}, "revoked"),
    ],
)
def test_lease_expiry_and_revocation_are_inclusive_at_exact_as_of_boundary(
    record_change,
    message,
):
    record, store, resolver, _handle = setup_record()
    store.record = replace(record, **record_change)
    handle = resolver.sign_authoritative_record(store.record)

    with pytest.raises(PermissionError, match=message):
        resolve(resolver, handle, as_of=NOW)


def test_forged_grant_handle_cannot_be_repaired_by_valid_scope_or_capability():
    _record, _store, resolver, handle = setup_record()
    forged = replace(
        handle,
        envelope_sha256="0" * 64,
        signature="1" * 64,
    )

    with pytest.raises(PermissionError, match="signature"):
        resolve(
            resolver,
            forged,
            scope=dict(SCOPE),
            required_capability="catalog.read",
        )
