from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext

import pytest

from apps.control_plane.channel_account_runtime_identity import (
    UnboundScopedChannelCredentialClientFactory,
    _is_server_bound_worker_resolver,
    register_server_bound_worker_resolver,
)
from apps.control_plane.channel_worker_runtime import (
    ManagedWorkerCredentialClientFactory,
    build_channel_worker_runtime,
)


class RecordingEnvironment(Mapping):
    def __init__(self, values):
        self.values = dict(values)
        self.accessed = []

    def __getitem__(self, key):
        self.accessed.append(key)
        return self.values[key]

    def get(self, key, default=None):
        self.accessed.append(key)
        return self.values.get(key, default)

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)


def test_default_worker_composition_is_unbound_and_reads_no_provider_secret():
    environment = RecordingEnvironment(
        {
            "OZON_CLIENT_ID": "must-not-read",
            "OZON_API_KEY": "must-not-read",
            "KJDS_CHANNEL_TENANT_REF": "must-not-read",
        }
    )

    runtime = build_channel_worker_runtime(environment)

    assert runtime.managed_store_bound is False
    assert runtime.mode == "unbound"
    assert type(runtime.credential_client_factory) is UnboundScopedChannelCredentialClientFactory
    assert environment.accessed == ["KJDS_CHANNEL_CREDENTIAL_MODE"]
    with pytest.raises(RuntimeError, match="resolver is not bound"):
        runtime.require_execution_ready()


def test_partial_managed_mode_fails_without_fallback_or_secret_reads():
    environment = RecordingEnvironment(
        {
            "KJDS_CHANNEL_CREDENTIAL_MODE": "managed",
            "OZON_CLIENT_ID": "must-not-read",
            "OZON_API_KEY": "must-not-read",
        }
    )

    with pytest.raises(RuntimeError, match="client builder"):
        build_channel_worker_runtime(environment)

    assert environment.accessed == ["KJDS_CHANNEL_CREDENTIAL_MODE"]


def test_managed_mode_without_database_or_lease_config_fails_closed():
    environment = RecordingEnvironment(
        {
            "KJDS_CHANNEL_CREDENTIAL_MODE": "managed",
            "OZON_CLIENT_ID": "must-not-read",
            "OZON_API_KEY": "must-not-read",
            "KJDS_CHANNEL_TENANT_REF": "must-not-read",
            "KJDS_CHANNEL_ACCOUNT_REF": "must-not-read",
        }
    )

    with pytest.raises(RuntimeError, match="KJDS_DATABASE_URL"):
        build_channel_worker_runtime(
            environment,
            client_builder=lambda material, resolver: nullcontext(object()),
        )

    assert set(environment.accessed) <= {
        "KJDS_CHANNEL_CREDENTIAL_MODE",
        "KJDS_DATABASE_URL",
    }
    assert "OZON_CLIENT_ID" not in environment.accessed
    assert "OZON_API_KEY" not in environment.accessed


def test_managed_mode_composes_authoritative_store_and_workload_identity():
    environment = RecordingEnvironment(
        {
            "KJDS_CHANNEL_CREDENTIAL_MODE": "managed",
            "KJDS_DATABASE_URL": "sqlite://",
            "KJDS_CHANNEL_LEASE_ISSUER": "kjds-managed-store",
            "KJDS_CHANNEL_LEASE_KEY_ID": "lease-kid-1",
            "KJDS_CHANNEL_WORKLOAD_IDENTITY_REF": "ozon-worker-1",
            "OZON_CLIENT_ID": "must-not-read",
            "OZON_API_KEY": "must-not-read",
            "KJDS_CHANNEL_SECRET_REFERENCE_SHA256": "must-not-read",
        }
    )

    runtime = build_channel_worker_runtime(
        environment,
        client_builder=lambda material, resolver: nullcontext(object()),
        lease_signing_key=b"k" * 32,
    )

    assert runtime.managed_store_bound is True
    assert runtime.mode == "managed"
    assert runtime.workload_identity_ref == "ozon-worker-1"
    assert isinstance(runtime.credential_client_factory, ManagedWorkerCredentialClientFactory)
    assert _is_server_bound_worker_resolver(runtime.lease_resolver) is True
    runtime.require_execution_ready()
    assert set(environment.accessed) == {
        "KJDS_CHANNEL_CREDENTIAL_MODE",
        "KJDS_DATABASE_URL",
        "KJDS_CHANNEL_LEASE_ISSUER",
        "KJDS_CHANNEL_LEASE_KEY_ID",
        "KJDS_CHANNEL_WORKLOAD_IDENTITY_REF",
    }
    assert "OZON_CLIENT_ID" not in environment.accessed
    assert "OZON_API_KEY" not in environment.accessed


def test_managed_mode_rejects_short_signing_key_before_any_binding():
    environment = RecordingEnvironment(
        {
            "KJDS_CHANNEL_CREDENTIAL_MODE": "managed",
            "KJDS_DATABASE_URL": "sqlite://",
            "KJDS_CHANNEL_LEASE_ISSUER": "kjds-managed-store",
            "KJDS_CHANNEL_LEASE_KEY_ID": "lease-kid-1",
            "KJDS_CHANNEL_WORKLOAD_IDENTITY_REF": "ozon-worker-1",
        }
    )

    with pytest.raises(RuntimeError, match="256 bits"):
        build_channel_worker_runtime(
            environment,
            client_builder=lambda material, resolver: nullcontext(object()),
            lease_signing_key=b"short",
        )


def test_server_bound_registry_rejects_forged_or_duck_typed_resolver():
    with pytest.raises(TypeError, match="exact"):
        register_server_bound_worker_resolver(object())


def test_unknown_worker_credential_mode_fails_closed():
    with pytest.raises(ValueError, match="mode is invalid"):
        build_channel_worker_runtime({"KJDS_CHANNEL_CREDENTIAL_MODE": "legacy-env"})
