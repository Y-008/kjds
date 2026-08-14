from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from .channel_account_runtime_identity import (
    ManagedCredentialLeaseHandle,
    SignedManagedCredentialLeaseResolver,
    SignedWorkerCredentialGrantAuthority,
    _WorkerCredentialGrantRecord,
)
from .channel_credential_grants import (
    SqlWorkerCredentialGrantStore,
    WorkerCredentialGrantRow,
)
from .domain import new_id
from .pilot_readiness import ReadOnlyPilotRow
from .sql_repository import Session

WORKER_GRANT_TTL_SECONDS = 900
MAX_AUTHORIZATION_EPOCH = 2**31 - 1

READ_CAPABILITY_BY_OPERATION = {
    "ozon.product.read": "catalog.read",
    "ozon.finance.read": "finance.read",
}

ADAPTER_BY_CAPABILITY = {
    "catalog.read": ("ozon-seller-api-read", "v1"),
    "finance.read": ("ozon-seller-api-read", "v1"),
    "catalog.write": ("ozon-product-import-v3", "v1"),
}

PURPOSE_BY_CAPABILITY = {
    "catalog.read": "pilot-read",
    "finance.read": "pilot-finance-read",
    "catalog.write": "listing-write",
}


@dataclass(frozen=True)
class CanonicalLeaseBinding:
    """Server-derived, non-secret lease facts for one exact scope/capability."""

    tenant_ref: str
    entity_ref: str
    store_ref: str
    platform: str
    account_ref: str
    adapter_id: str
    adapter_version: str
    required_capability: str
    authorization_epoch: int
    lease_handle: ManagedCredentialLeaseHandle
    secret_reference_sha256: str
    credential_fingerprint_sha256: str
    expires_at: datetime


class CanonicalLeaseBindingSource(Protocol):
    """Server-owned authority that maps an exact scope/adapter/capability to a
    canonical managed-store lease.  It never accepts client-selected fields."""

    def resolve(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        platform: str,
        adapter_id: str,
        adapter_version: str,
        required_capability: str,
        purpose: str,
        as_of: datetime,
    ) -> CanonicalLeaseBinding: ...


class UnboundCanonicalLeaseBindingSource:
    """Production default until an authoritative managed store is bound.

    No grant can be derived, signed or returned without the managed-store
    adapter/workload identity; this source fails closed before any write.
    """

    def resolve(self, **_values: Any) -> CanonicalLeaseBinding:
        raise PermissionError(
            "Canonical worker credential lease source is not bound; "
            "no grant can be derived without an authoritative managed store"
        )


class CanonicalWorkerCredentialGrantIssuer:
    """Derives and signs single-use worker grants from canonical rows only.

    Callers (PilotRunService / LimitedExecutorService) pass only the canonical
    source ids; every grant field is derived server-side from persisted Pilot or
    Command rows plus the bound canonical lease authority.  A grant is persisted
    and signed inside the caller's transaction before it can reach a worker.
    """

    def __init__(
        self,
        *,
        grant_issuer: str,
        grant_key_id: str,
        signing_key: bytes,
        lease_source: CanonicalLeaseBindingSource,
    ) -> None:
        self._grant_issuer = SignedManagedCredentialLeaseResolver._required(
            grant_issuer,
            "grant issuer",
        )
        self._grant_key_id = SignedManagedCredentialLeaseResolver._required(
            grant_key_id,
            "grant key id",
        )
        if len(bytes(signing_key)) < 32:
            raise ValueError("Worker grant signing key must be at least 256 bits")
        self._signing_key = bytes(signing_key)
        self._lease_source = lease_source

    def issue_for_pilot_run(
        self,
        *,
        session: Session,
        pilot: ReadOnlyPilotRow,
        run_id: str,
        operation: str,
        worker_id: str,
        as_of: datetime,
    ) -> dict[str, Any] | None:
        """Derive the read-capability grant from one canonical Pilot Allocation.

        Legacy pilots (no complete native scope) receive no grant: they have no
        canonical tenant/entity/store authority to bind.
        """
        scope = self._pilot_scope(pilot)
        if scope is None:
            return None
        capability = self._capability_for_operation(operation)
        adapter_id, adapter_version = ADAPTER_BY_CAPABILITY[capability]
        purpose = PURPOSE_BY_CAPABILITY[capability]
        binding = self._lease_source.resolve(
            tenant_ref=scope["tenant_ref"],
            entity_ref=scope["entity_ref"],
            store_ref=scope["store_ref"],
            platform="ozon",
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            required_capability=capability,
            purpose=purpose,
            as_of=self._aware(as_of),
        )
        self._validate_binding(
            binding,
            scope=scope,
            platform="ozon",
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            required_capability=capability,
            purpose=purpose,
        )
        return self._persist_and_sign(
            session=session,
            binding=binding,
            purpose=purpose,
            as_of=as_of,
        )

    def issue_for_execution_command(
        self,
        *,
        session: Session,
        command: Any,
        scope: dict[str, str],
        worker_id: str,
        as_of: datetime,
    ) -> dict[str, Any] | None:
        """Derive the write-capability grant from one Execution Command.

        Only the Ozon product-import adapter can open a provider write lease
        today; other adapters remain internal plans with no provider grant.
        ``scope`` is derived server-side by the ExecutionPlanService from the
        canonical plan source (listing draft or channel-account Approval); the
        worker never supplies it.
        """
        adapter_id = str(getattr(command, "adapter_id", "") or "")
        if adapter_id != "ozon.product.import.v3":
            return None
        capability = "catalog.write"
        canonical_adapter_id, canonical_adapter_version = ADAPTER_BY_CAPABILITY[capability]
        purpose = PURPOSE_BY_CAPABILITY[capability]
        binding = self._lease_source.resolve(
            tenant_ref=scope["tenant_ref"],
            entity_ref=scope["entity_ref"],
            store_ref=scope["store_ref"],
            platform="ozon",
            adapter_id=canonical_adapter_id,
            adapter_version=canonical_adapter_version,
            required_capability=capability,
            purpose=purpose,
            as_of=self._aware(as_of),
        )
        self._validate_binding(
            binding,
            scope=scope,
            platform="ozon",
            adapter_id=canonical_adapter_id,
            adapter_version=canonical_adapter_version,
            required_capability=capability,
            purpose=purpose,
        )
        return self._persist_and_sign(
            session=session,
            binding=binding,
            purpose=purpose,
            as_of=as_of,
        )

    def _persist_and_sign(
        self,
        *,
        session: Session,
        binding: CanonicalLeaseBinding,
        purpose: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        issued_at = self._aware(as_of)
        expires_at = min(
            issued_at + timedelta(seconds=WORKER_GRANT_TTL_SECONDS),
            self._aware(binding.expires_at),
        )
        if expires_at <= issued_at:
            raise PermissionError("Canonical worker credential lease has no remaining validity")
        if (
            isinstance(binding.authorization_epoch, bool)
            or not isinstance(binding.authorization_epoch, int)
            or not 1 <= binding.authorization_epoch <= MAX_AUTHORIZATION_EPOCH
        ):
            raise PermissionError("Canonical worker credential authorization epoch is invalid")
        for name, value in (
            ("secret reference", binding.secret_reference_sha256),
            ("credential fingerprint", binding.credential_fingerprint_sha256),
        ):
            if not self._valid_sha256(value):
                raise PermissionError(f"Canonical worker credential {name} hash is invalid")
        store = SqlWorkerCredentialGrantStore(session)
        grant_authority = SignedWorkerCredentialGrantAuthority(
            issuer=self._grant_issuer,
            key_id=self._grant_key_id,
            signing_key=self._signing_key,
            store=store,
        )
        grant_id = new_id("wcg")
        row = WorkerCredentialGrantRow(
            grant_id=grant_id,
            issuer=self._grant_issuer,
            key_id=self._grant_key_id,
            tenant_ref=binding.tenant_ref,
            entity_ref=binding.entity_ref,
            store_ref=binding.store_ref,
            platform=binding.platform,
            account_ref=binding.account_ref,
            adapter_id=binding.adapter_id,
            adapter_version=binding.adapter_version,
            required_capability=binding.required_capability,
            purpose=purpose,
            authorization_epoch=binding.authorization_epoch,
            lease_issuer=binding.lease_handle.issuer,
            lease_key_id=binding.lease_handle.key_id,
            lease_id=binding.lease_handle.lease_id,
            lease_envelope_sha256=binding.lease_handle.envelope_sha256,
            lease_signature=binding.lease_handle.signature,
            secret_reference_sha256=binding.secret_reference_sha256,
            credential_fingerprint_sha256=binding.credential_fingerprint_sha256,
            issued_at=issued_at,
            expires_at=expires_at,
            revoked_at=None,
            consumed_at=None,
        )
        session.add(row)
        session.flush()
        record = _WorkerCredentialGrantRecord(
            grant_id=row.grant_id,
            issuer=row.issuer,
            key_id=row.key_id,
            tenant_ref=row.tenant_ref,
            entity_ref=row.entity_ref,
            store_ref=row.store_ref,
            platform=row.platform,
            account_ref=row.account_ref,
            adapter_id=row.adapter_id,
            adapter_version=row.adapter_version,
            required_capability=row.required_capability,
            purpose=row.purpose,
            authorization_epoch=row.authorization_epoch,
            lease_handle=ManagedCredentialLeaseHandle(
                issuer=row.lease_issuer,
                key_id=row.lease_key_id,
                lease_id=row.lease_id,
                envelope_sha256=row.lease_envelope_sha256,
                signature=row.lease_signature,
            ),
            secret_reference_sha256=row.secret_reference_sha256,
            credential_fingerprint_sha256=row.credential_fingerprint_sha256,
            issued_at=SignedManagedCredentialLeaseResolver._aware(row.issued_at),
            expires_at=SignedManagedCredentialLeaseResolver._aware(row.expires_at),
            revoked_at=None,
            consumed_at=None,
        )
        if store.get(grant_id) is None:
            raise PermissionError("Worker credential grant was not persisted")
        grant = grant_authority.issue(record)
        # The worker only ever receives the signed transport envelope; every
        # derivation field remains server-side in the grant ledger row.
        return grant.transport_envelope()

    @staticmethod
    def _pilot_scope(pilot: ReadOnlyPilotRow) -> dict[str, str] | None:
        tenant_ref = str(pilot.tenant_ref or "").strip()
        entity_ref = str(pilot.entity_ref or "").strip()
        store_ref = str(pilot.store_ref or "").strip()
        authority_sha256 = str(pilot.scope_grant_authority_sha256 or "").strip().lower()
        if not tenant_ref or not entity_ref or not store_ref:
            return None
        if (
            not authority_sha256
            or len(authority_sha256) != 64
            or any(char not in "0123456789abcdef" for char in authority_sha256)
        ):
            raise PermissionError("Native pilot scope grant authority hash is invalid")
        return {
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "scope_grant_authority_sha256": authority_sha256,
        }

    @staticmethod
    def _validate_binding(
        binding: CanonicalLeaseBinding,
        *,
        scope: dict[str, str],
        platform: str,
        adapter_id: str,
        adapter_version: str,
        required_capability: str,
        purpose: str,
    ) -> None:
        actual_scope = (
            binding.tenant_ref,
            binding.entity_ref,
            binding.store_ref,
        )
        expected_scope = (
            scope["tenant_ref"],
            scope["entity_ref"],
            scope["store_ref"],
        )
        if actual_scope != expected_scope:
            raise PermissionError("Canonical lease exact-scope binding is invalid")
        if (
            binding.platform != platform
            or binding.adapter_id != adapter_id
            or binding.adapter_version != adapter_version
            or binding.required_capability != required_capability
        ):
            raise PermissionError("Canonical lease adapter/capability binding drifted")
        for name, value in (
            ("secret reference", binding.secret_reference_sha256),
            ("credential fingerprint", binding.credential_fingerprint_sha256),
        ):
            if not CanonicalWorkerCredentialGrantIssuer._valid_sha256(value):
                raise PermissionError(f"Canonical lease {name} hash is invalid")
        if not str(binding.account_ref or "").strip():
            raise PermissionError("Canonical lease account binding is missing")
        if not purpose:
            raise PermissionError("Canonical lease purpose is missing")

    @classmethod
    def _capability_for_operation(cls, operation: str) -> str:
        capability = READ_CAPABILITY_BY_OPERATION.get(operation)
        if capability is None:
            raise PermissionError("Read operation has no canonical worker capability")
        if capability not in ADAPTER_BY_CAPABILITY:
            raise PermissionError("Read capability has no canonical worker adapter")
        return capability

    @staticmethod
    def _valid_sha256(value: Any) -> bool:
        normalized = str(value or "").strip().lower()
        return len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Worker credential as_of must include timezone")
        return value.astimezone(UTC)
