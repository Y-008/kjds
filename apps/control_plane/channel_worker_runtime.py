from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .channel_account_runtime_identity import (
    ResolvedChannelCredentialMaterial,
    ScopedChannelCredentialClientFactory,
    SignedManagedCredentialLeaseResolver,
    SignedWorkerCredentialGrantAuthority,
    UnboundScopedChannelCredentialClientFactory,
    register_server_bound_worker_resolver,
)
from .channel_credential_grants import SqlWorkerCredentialGrantStore
from .managed_credential_leases import SqlManagedCredentialLeaseStore


class ManagedWorkerCredentialClientFactory:
    """Worker-side seam: one atomic grant redemption per ``open()`` call.

    Each redemption opens its own transaction: grant signature verification,
    exact-scope lease resolution and the single conditional consumption update
    commit together before the provider client is returned.  Replays, forged,
    expired, revoked, cross-scope or drifted grants fail before any provider
    client is constructed.
    """

    def __init__(
        self,
        *,
        engine,
        grant_issuer: str,
        grant_key_id: str,
        signing_key: bytes,
        lease_resolver: SignedManagedCredentialLeaseResolver,
        client_builder: Callable[
            [ResolvedChannelCredentialMaterial, SignedManagedCredentialLeaseResolver],
            AbstractContextManager[Any],
        ],
    ) -> None:
        self._engine = engine
        self._grant_issuer = grant_issuer
        self._grant_key_id = grant_key_id
        self._signing_key = bytes(signing_key)
        if len(self._signing_key) < 32:
            raise ValueError("Worker grant signing key must be at least 256 bits")
        self._lease_resolver = lease_resolver
        self._client_builder = client_builder

    def open(
        self,
        *,
        grant: Any,
        as_of: datetime,
    ) -> AbstractContextManager[Any]:
        resolver = self._lease_resolver

        def builder(material: ResolvedChannelCredentialMaterial) -> AbstractContextManager[Any]:
            return self._client_builder(material, resolver)

        with Session(self._engine) as session, session.begin():
            store = SqlWorkerCredentialGrantStore(session)
            authority = SignedWorkerCredentialGrantAuthority(
                issuer=self._grant_issuer,
                key_id=self._grant_key_id,
                signing_key=self._signing_key,
                store=store,
            )
            factory = ScopedChannelCredentialClientFactory(
                grant_authority=authority,
                grant_store=store,
                lease_resolver=resolver,
                client_builder=builder,
            )
            return factory.open(grant=grant, as_of=as_of)


@dataclass(frozen=True)
class ChannelWorkerRuntime:
    """Single composition result shared by every channel worker process."""

    credential_client_factory: Any
    managed_store_bound: bool
    mode: str
    lease_resolver: Any | None = None
    engine: Any | None = None
    grant_issuer: str | None = None
    grant_key_id: str | None = None
    signing_key: bytes | None = None
    workload_identity_ref: str | None = None

    def require_execution_ready(self) -> None:
        if not self.managed_store_bound:
            raise RuntimeError(
                "Managed channel credential resolver is not bound; "
                "environment-only credentials cannot authorize a worker"
            )


def _configured_lease_value(environment: Mapping[str, str], name: str) -> str:
    value = str(environment.get(name, "")).strip()
    if not value or value.lower() in {
        "missing",
        "replace-me",
        "replace-with-a-key",
        "changeme",
    }:
        raise RuntimeError(f"{name} must be configured for the managed channel credential mode")
    return value


def build_channel_worker_runtime(
    environment: Mapping[str, str],
    *,
    client_builder: Callable[
        [ResolvedChannelCredentialMaterial, SignedManagedCredentialLeaseResolver],
        AbstractContextManager[Any],
    ]
    | None = None,
    lease_signing_key: bytes | None = None,
) -> ChannelWorkerRuntime:
    """Compose the worker trust boundary without reading provider credentials.

    ``managed`` mode binds the shared composition root to the authoritative
    SQL managed-store adapter and a workload identity, registers the resolver as
    server-bound, and hands the worker an atomic per-grant client factory.
    Partial or unknown configuration never falls back to environment secrets,
    and no Ozon/client credential key is ever read here.
    """

    mode = str(environment.get("KJDS_CHANNEL_CREDENTIAL_MODE", "unbound")).strip().lower()
    if mode not in {"", "unbound", "managed"}:
        raise ValueError("KJDS channel credential mode is invalid")
    if mode == "managed":
        if client_builder is None:
            raise RuntimeError(
                "Managed channel credential mode requires a worker client builder"
            )
        database_url = _configured_lease_value(environment, "KJDS_DATABASE_URL")
        issuer = _configured_lease_value(environment, "KJDS_CHANNEL_LEASE_ISSUER")
        key_id = _configured_lease_value(environment, "KJDS_CHANNEL_LEASE_KEY_ID")
        workload_identity_ref = _configured_lease_value(
            environment,
            "KJDS_CHANNEL_WORKLOAD_IDENTITY_REF",
        )
        signing_key = lease_signing_key
        if signing_key is None:
            raw = str(environment.get("KJDS_CHANNEL_LEASE_SIGNING_KEY", ""))
            signing_key = raw.encode("utf-8")
        if len(signing_key) < 32:
            raise RuntimeError("Managed channel lease signing key must be at least 256 bits")
        engine = create_engine(database_url)
        store = SqlManagedCredentialLeaseStore(
            engine=engine,
            issuer=issuer,
            key_id=key_id,
        )
        resolver = SignedManagedCredentialLeaseResolver(
            issuer=issuer,
            key_id=key_id,
            signing_key=signing_key,
            store=store,
        )
        register_server_bound_worker_resolver(resolver)
        factory = ManagedWorkerCredentialClientFactory(
            engine=engine,
            grant_issuer=issuer,
            grant_key_id=key_id,
            signing_key=signing_key,
            lease_resolver=resolver,
            client_builder=client_builder,
        )
        return ChannelWorkerRuntime(
            credential_client_factory=factory,
            managed_store_bound=True,
            mode="managed",
            lease_resolver=resolver,
            engine=engine,
            grant_issuer=issuer,
            grant_key_id=key_id,
            signing_key=signing_key,
            workload_identity_ref=workload_identity_ref,
        )
    return ChannelWorkerRuntime(
        credential_client_factory=UnboundScopedChannelCredentialClientFactory(),
        managed_store_bound=False,
        mode="unbound",
    )
