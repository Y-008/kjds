from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    String,
    UniqueConstraint,
    desc,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .channel_account_runtime_identity import (
    ManagedCredentialLeaseHandle,
    SignedManagedCredentialLeaseResolver,
    _ManagedCredentialLeaseRecord,
)
from .scoped_worker_credential_grants import CanonicalLeaseBinding
from .sql_repository import Base

SECRET_REFERENCE_NAMESPACE = "msl"


class ManagedCredentialLeaseRow(Base):
    """Authoritative managed-store lease authority.

    This table is the designated managed secret holder for channel workers:
    client_id/api_key material lives only here (never in grants, Evidence,
    Graph, logs or API responses).  Rows are written exclusively through the
    server-owned ``SqlManagedCredentialLeaseStore.upsert_authoritative`` seam
    after provider readback and external verifier freshness are present.
    """

    __tablename__ = "channel_managed_credential_leases"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "adapter_id",
            "adapter_version",
            "authorization_epoch",
            name="uq_channel_managed_lease_authority",
        ),
        CheckConstraint(
            "length(issuer) > 0 AND length(key_id) > 0 "
            "AND length(tenant_ref) > 0 AND length(entity_ref) > 0 "
            "AND length(store_ref) > 0 AND length(platform) > 0 "
            "AND length(account_ref) > 0 AND length(adapter_id) > 0 "
            "AND length(adapter_version) > 0 "
            "AND length(secret_reference) > 0 "
            "AND secret_reference LIKE 'msl_%' "
            "AND length(secret_reference_sha256) = 64 "
            "AND length(credential_fingerprint_sha256) = 64 "
            "AND length(provider_readback_sha256) = 64 "
            "AND length(external_verifier_observation_sha256) = 64 "
            "AND authorization_epoch > 0 "
            "AND issued_at < expires_at "
            "AND (revoked_at IS NULL OR revoked_at >= issued_at) "
            "AND length(client_id) > 0 AND length(api_key) > 0 "
            "AND provider_readback_verified_at IS NOT NULL "
            "AND external_verifier_verified_at IS NOT NULL "
            "AND provider_readback_verified_at <= expires_at "
            "AND external_verifier_verified_at <= expires_at",
            name="ck_channel_managed_lease_authority",
        ),
        Index(
            "ix_channel_managed_lease_scope",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "adapter_id",
            "adapter_version",
            "expires_at",
        ),
    )

    lease_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    issuer: Mapped[str] = mapped_column(String(160), nullable=False)
    key_id: Mapped[str] = mapped_column(String(160), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    account_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(160), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(80), nullable=False)
    capabilities_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    authorization_epoch: Mapped[int] = mapped_column(nullable=False)
    secret_reference: Mapped[str] = mapped_column(String(256), nullable=False)
    secret_reference_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    client_id: Mapped[str] = mapped_column(String(240), nullable=False)
    api_key: Mapped[str] = mapped_column(String(500), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    provider_readback_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_readback_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    external_verifier_observation_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    external_verifier_verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ManagedCredentialLeaseProvision:
    """Server-owned, non-secret provisioning facts for one lease write."""

    def __init__(
        self,
        *,
        lease_id: str,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        platform: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        capabilities: set[str],
        authorization_epoch: int,
        secret_reference: str,
        client_id: str,
        api_key: str,
        issued_at: datetime,
        expires_at: datetime,
        provider_readback_sha256: str,
        provider_readback_verified_at: datetime,
        external_verifier_observation_sha256: str,
        external_verifier_verified_at: datetime,
    ) -> None:
        self.lease_id = self._required(lease_id, "lease_id", 240)
        self.tenant_ref = self._required(tenant_ref, "tenant_ref", 160)
        self.entity_ref = self._required(entity_ref, "entity_ref", 160)
        self.store_ref = self._required(store_ref, "store_ref", 160)
        self.platform = self._required(platform, "platform", 80)
        self.account_ref = self._required(account_ref, "account_ref", 240)
        self.adapter_id = self._required(adapter_id, "adapter_id", 160)
        self.adapter_version = self._required(adapter_version, "adapter_version", 80)
        normalized_capabilities = {
            self._required(item, "capability", 160) for item in capabilities
        }
        if not normalized_capabilities:
            raise ValueError("Managed lease requires at least one capability")
        self.capabilities = frozenset(normalized_capabilities)
        if (
            isinstance(authorization_epoch, bool)
            or not isinstance(authorization_epoch, int)
            or authorization_epoch < 1
        ):
            raise ValueError("Managed lease authorization epoch must be a positive integer")
        self.authorization_epoch = authorization_epoch
        normalized_reference = self._required(secret_reference, "secret_reference", 256)
        if not normalized_reference.startswith(f"{SECRET_REFERENCE_NAMESPACE}_"):
            raise ValueError("secret_reference must be an opaque managed-store locator in the msl namespace")
        self.secret_reference = normalized_reference
        self.client_id = self._required(client_id, "client_id", 240)
        self.api_key = self._required(api_key, "api_key", 500)
        self.issued_at = self._aware(issued_at, "issued_at")
        self.expires_at = self._aware(expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("Managed lease expires_at must be after issued_at")
        self.provider_readback_sha256 = self._sha256(
            provider_readback_sha256,
            "provider_readback_sha256",
        )
        self.provider_readback_verified_at = self._aware(
            provider_readback_verified_at,
            "provider_readback_verified_at",
        )
        self.external_verifier_observation_sha256 = self._sha256(
            external_verifier_observation_sha256,
            "external_verifier_observation_sha256",
        )
        self.external_verifier_verified_at = self._aware(
            external_verifier_verified_at,
            "external_verifier_verified_at",
        )
        if self.provider_readback_verified_at > self.expires_at or (
            self.external_verifier_verified_at > self.expires_at
        ):
            raise ValueError("Managed lease verifier observations cannot outlive the lease")

    def secret_reference_sha256(self) -> str:
        return hashlib.sha256(self.secret_reference.encode()).hexdigest()

    @staticmethod
    def _required(value: str, name: str, limit: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > limit:
            raise ValueError(f"{name} is required")
        return normalized

    @staticmethod
    def _aware(value: datetime, name: str) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError(f"{name} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must include timezone")
        return value.astimezone(UTC)

    @staticmethod
    def _sha256(value: str, name: str) -> str:
        normalized = str(value or "").strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError(f"{name} must be a SHA-256 hexadecimal digest")
        return normalized


class SqlManagedCredentialLeaseStore:
    """PostgreSQL-backed authoritative lease store (the managed secret holder).

    ``get`` hydrates the canonical ``_ManagedCredentialLeaseRecord`` used by the
    signed resolver; ``upsert_authoritative`` is the only write seam and always
    recomputes the credential fingerprint from the provisioned material.
    """

    def __init__(
        self,
        *,
        engine,
        issuer: str,
        key_id: str,
    ) -> None:
        self.engine = engine
        self.issuer = SignedManagedCredentialLeaseResolver._required(issuer, "issuer")
        self.key_id = SignedManagedCredentialLeaseResolver._required(key_id, "key_id")

    def get(self, lease_id: str) -> _ManagedCredentialLeaseRecord | None:
        with Session(self.engine) as session:
            row = session.get(ManagedCredentialLeaseRow, lease_id)
            return self._record(row) if row is not None else None

    def upsert_authoritative(
        self,
        provision: ManagedCredentialLeaseProvision,
        *,
        created_by: str,
        expected_previous_epoch: int | None = None,
    ) -> _ManagedCredentialLeaseRecord:
        """Idempotent, drift-failing write of one authoritative lease."""
        created_by = self._required(created_by, "lease provisioner", 160)
        fingerprint = SignedManagedCredentialLeaseResolver.credential_fingerprint(
            client_id=provision.client_id,
            api_key=provision.api_key,
            platform=provision.platform,
            account_ref=provision.account_ref,
        )
        incoming = self._row_from_provision(
            provision,
            fingerprint,
            created_by,
        )
        now = datetime.now(UTC)
        incoming.created_at = now
        incoming.updated_at = now
        with Session(self.engine) as session, session.begin():
            row = session.get(ManagedCredentialLeaseRow, provision.lease_id)
            if row is not None:
                existing = self._record(row)
                if existing != self._record(incoming):
                    raise ValueError("Managed lease authority drift on idempotent write")
                return existing
            if expected_previous_epoch is not None:
                current = session.scalar(
                    select(ManagedCredentialLeaseRow)
                    .where(
                        ManagedCredentialLeaseRow.tenant_ref == provision.tenant_ref,
                        ManagedCredentialLeaseRow.entity_ref == provision.entity_ref,
                        ManagedCredentialLeaseRow.store_ref == provision.store_ref,
                        ManagedCredentialLeaseRow.platform == provision.platform,
                        ManagedCredentialLeaseRow.account_ref == provision.account_ref,
                        ManagedCredentialLeaseRow.adapter_id == provision.adapter_id,
                        ManagedCredentialLeaseRow.adapter_version == provision.adapter_version,
                    )
                    .order_by(desc(ManagedCredentialLeaseRow.authorization_epoch))
                    .limit(1)
                )
                if current is not None and int(current.authorization_epoch) != expected_previous_epoch:
                    raise ValueError("Managed lease rotation epoch drifted")
            session.add(incoming)
            session.flush()
            return self._record(incoming)

    def revoke(self, lease_id: str, *, revoked_at: datetime, revoked_by: str) -> None:
        revoked_at = self._aware(revoked_at, "revoked_at")
        revoked_by = self._required(revoked_by, "lease revoker", 160)
        with Session(self.engine) as session, session.begin():
            row = session.get(ManagedCredentialLeaseRow, lease_id)
            if row is None:
                raise KeyError(f"Managed lease not found: {lease_id}")
            if row.revoked_at is not None:
                raise ValueError("Managed lease is already revoked")
            if revoked_at < self._aware(row.issued_at, "issued_at"):
                raise ValueError("Managed lease cannot be revoked before issuance")
            row.revoked_at = revoked_at
            row.updated_at = datetime.now(UTC)

    def sign_handle(
        self,
        *,
        resolver: SignedManagedCredentialLeaseResolver,
        lease_id: str,
    ) -> ManagedCredentialLeaseHandle:
        record = self.get(lease_id)
        if record is None:
            raise KeyError(f"Managed lease not found: {lease_id}")
        return resolver.sign_authoritative_record(record)

    def _row_from_provision(
        self,
        provision: ManagedCredentialLeaseProvision,
        fingerprint: str,
        created_by: str,
    ) -> ManagedCredentialLeaseRow:
        return ManagedCredentialLeaseRow(
            lease_id=provision.lease_id,
            issuer=self.issuer,
            key_id=self.key_id,
            tenant_ref=provision.tenant_ref,
            entity_ref=provision.entity_ref,
            store_ref=provision.store_ref,
            platform=provision.platform,
            account_ref=provision.account_ref,
            adapter_id=provision.adapter_id,
            adapter_version=provision.adapter_version,
            capabilities_json=sorted(provision.capabilities),
            authorization_epoch=provision.authorization_epoch,
            secret_reference=provision.secret_reference,
            secret_reference_sha256=provision.secret_reference_sha256(),
            credential_fingerprint_sha256=fingerprint,
            client_id=provision.client_id,
            api_key=provision.api_key,
            issued_at=provision.issued_at,
            expires_at=provision.expires_at,
            revoked_at=None,
            provider_readback_sha256=provision.provider_readback_sha256,
            provider_readback_verified_at=provision.provider_readback_verified_at,
            external_verifier_observation_sha256=(
                provision.external_verifier_observation_sha256
            ),
            external_verifier_verified_at=provision.external_verifier_verified_at,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    @classmethod
    def _record(cls, row: ManagedCredentialLeaseRow) -> _ManagedCredentialLeaseRecord:
        return _ManagedCredentialLeaseRecord(
            lease_id=row.lease_id,
            issuer=row.issuer,
            key_id=row.key_id,
            tenant_ref=row.tenant_ref,
            entity_ref=row.entity_ref,
            store_ref=row.store_ref,
            platform=row.platform,
            account_ref=row.account_ref,
            adapter_id=row.adapter_id,
            adapter_version=row.adapter_version,
            capabilities=frozenset(row.capabilities_json),
            secret_reference_sha256=row.secret_reference_sha256,
            credential_fingerprint_sha256=row.credential_fingerprint_sha256,
            issued_at=cls._aware(row.issued_at, "issued_at"),
            expires_at=cls._aware(row.expires_at, "expires_at"),
            revoked_at=(
                cls._aware(row.revoked_at, "revoked_at") if row.revoked_at is not None else None
            ),
            client_id=row.client_id,
            api_key=row.api_key,
            provider_readback_sha256=row.provider_readback_sha256,
            provider_readback_verified_at=cls._aware(
                row.provider_readback_verified_at,
                "provider_readback_verified_at",
            ),
            external_verifier_observation_sha256=row.external_verifier_observation_sha256,
            external_verifier_verified_at=cls._aware(
                row.external_verifier_verified_at,
                "external_verifier_verified_at",
            ),
            authorization_epoch=row.authorization_epoch,
        )

    @staticmethod
    def _required(value: str, name: str, limit: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > limit:
            raise ValueError(f"{name} is required")
        return normalized

    @staticmethod
    def _aware(value: datetime | None, name: str) -> datetime:
        if value is None:
            raise ValueError(f"{name} is required")
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class SqlManagedCredentialLeaseBindingSource:
    """CanonicalLeaseBindingSource over the authoritative SQL managed store.

    Resolves the current, non-revoked, non-expired, verifier-fresh lease for an
    exact scope/adapter/capability and returns the server-signed handle plus the
    non-secret derivation facts consumed by the grant issuer.  It never exposes
    credential material.
    """

    def __init__(
        self,
        *,
        store: SqlManagedCredentialLeaseStore,
        resolver: SignedManagedCredentialLeaseResolver,
    ) -> None:
        self._store = store
        self._resolver = resolver

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
    ) -> CanonicalLeaseBinding:
        del purpose
        cutoff = self._aware(as_of, "as_of")
        with Session(self._store.engine) as session:
            rows = list(
                session.scalars(
                    select(ManagedCredentialLeaseRow)
                    .where(
                        ManagedCredentialLeaseRow.tenant_ref == tenant_ref,
                        ManagedCredentialLeaseRow.entity_ref == entity_ref,
                        ManagedCredentialLeaseRow.store_ref == store_ref,
                        ManagedCredentialLeaseRow.platform == platform,
                        ManagedCredentialLeaseRow.adapter_id == adapter_id,
                        ManagedCredentialLeaseRow.adapter_version == adapter_version,
                        ManagedCredentialLeaseRow.revoked_at.is_(None),
                        ManagedCredentialLeaseRow.issued_at <= cutoff,
                        ManagedCredentialLeaseRow.expires_at > cutoff,
                    )
                    .order_by(
                        desc(ManagedCredentialLeaseRow.authorization_epoch),
                        ManagedCredentialLeaseRow.updated_at,
                    )
                )
            )
        if not rows:
            raise PermissionError(
                "No current managed credential lease exists for the exact scope/capability"
            )
        row = rows[0]
        record = self._store._record(row)
        if required_capability not in record.capabilities:
            raise PermissionError("Managed credential lease lacks the required capability")
        ttl_seconds = SignedManagedCredentialLeaseResolver.VERIFIER_TTL_SECONDS
        if (
            self._aware(record.provider_readback_verified_at, "provider_readback_verified_at")
            > cutoff
            or self._aware(record.external_verifier_verified_at, "external_verifier_verified_at")
            > cutoff
            or (
                cutoff
                - self._aware(
                    record.provider_readback_verified_at,
                    "provider_readback_verified_at",
                )
            ).total_seconds()
            > ttl_seconds
            or (
                cutoff
                - self._aware(
                    record.external_verifier_verified_at,
                    "external_verifier_verified_at",
                )
            ).total_seconds()
            > ttl_seconds
        ):
            raise PermissionError("Managed credential lease verifier observation is stale")
        handle = self._resolver.sign_authoritative_record(record)
        return CanonicalLeaseBinding(
            tenant_ref=record.tenant_ref,
            entity_ref=record.entity_ref,
            store_ref=record.store_ref,
            platform=record.platform,
            account_ref=record.account_ref,
            adapter_id=record.adapter_id,
            adapter_version=record.adapter_version,
            required_capability=required_capability,
            authorization_epoch=record.authorization_epoch,
            lease_handle=handle,
            secret_reference_sha256=record.secret_reference_sha256,
            credential_fingerprint_sha256=record.credential_fingerprint_sha256,
            expires_at=record.expires_at,
        )

    @staticmethod
    def _aware(value: datetime | None, name: str) -> datetime:
        if value is None:
            raise ValueError(f"{name} is required")
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class SqlManagedStoreRuntimeIdentityVerifier:
    """API-side projection of the authoritative managed-store runtime state.

    Reads the live ``channel_managed_credential_leases`` table for the exact
    scope/platform/account/adapter and reports truthful runtime identity facts.
    It never reads secret material, never contacts the provider, and never
    claims freshness that the table cannot prove (missing rows stay
    ``no_data``; stale verifier observations stay ``stale``).
    """

    CONTRACT_ID = "kjds-channel-account-runtime-binding-probe-v1"

    def __init__(self, *, engine) -> None:
        self._engine = engine

    def verify(
        self,
        *,
        scope: dict[str, Any],
        platform: str,
        account_ref: str,
        adapter_id: str,
        adapter_version: str,
        capabilities: list[str],
        secret_reference_sha256: str,
        credential_fingerprint_sha256: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = self._aware(as_of, "as_of")
        with Session(self._engine) as session:
            rows = list(
                session.scalars(
                    select(ManagedCredentialLeaseRow)
                    .where(
                        ManagedCredentialLeaseRow.tenant_ref == str(scope.get("tenant_ref") or ""),
                        ManagedCredentialLeaseRow.entity_ref == str(scope.get("entity_ref") or ""),
                        ManagedCredentialLeaseRow.store_ref == str(scope.get("store_ref") or ""),
                        ManagedCredentialLeaseRow.platform == str(platform or ""),
                        ManagedCredentialLeaseRow.account_ref == str(account_ref or ""),
                        ManagedCredentialLeaseRow.adapter_id == str(adapter_id or ""),
                        ManagedCredentialLeaseRow.adapter_version == str(adapter_version or ""),
                        ManagedCredentialLeaseRow.revoked_at.is_(None),
                        ManagedCredentialLeaseRow.issued_at <= cutoff,
                        ManagedCredentialLeaseRow.expires_at > cutoff,
                    )
                    .order_by(
                        desc(ManagedCredentialLeaseRow.authorization_epoch),
                        ManagedCredentialLeaseRow.updated_at,
                    )
                )
            )
        if not rows:
            return self._payload(
                status="no_data",
                managed_store_bound=False,
                lease_fresh=False,
                fingerprint_match=False,
                scope_match=False,
                capabilities_match=False,
                provider_readback_fresh_passed=False,
                external_verifier_fresh_passed=False,
                source_gaps=["channel_account_managed_store_lease_missing"],
            )
        row = rows[0]
        fingerprint_match = (
            bool(credential_fingerprint_sha256)
            and str(credential_fingerprint_sha256).strip().lower()
            == str(row.credential_fingerprint_sha256).strip().lower()
        )
        scope_match = (
            bool(secret_reference_sha256)
            and str(secret_reference_sha256).strip().lower()
            == str(row.secret_reference_sha256).strip().lower()
        )
        capabilities_match = bool(capabilities) and set(capabilities) <= set(row.capabilities_json)
        provider_fresh = self._verifier_fresh(row.provider_readback_sha256, row.provider_readback_verified_at, cutoff)
        external_fresh = self._verifier_fresh(
            row.external_verifier_observation_sha256,
            row.external_verifier_verified_at,
            cutoff,
        )
        lease_fresh = bool(row.expires_at) and self._aware(row.expires_at, "expires_at") > cutoff
        all_flags = (
            fingerprint_match
            and scope_match
            and capabilities_match
            and provider_fresh
            and external_fresh
        )
        if all_flags and lease_fresh:
            status = "fresh_passed"
            source_gaps: list[str] = []
        elif not lease_fresh or not provider_fresh or not external_fresh:
            status = "stale"
            source_gaps = [
                "channel_account_managed_store_lease_stale",
            ]
        else:
            status = "blocked"
            source_gaps = []
            if not fingerprint_match:
                source_gaps.append("channel_account_managed_store_fingerprint_drift")
            if not scope_match:
                source_gaps.append("channel_account_managed_store_scope_drift")
            if not capabilities_match:
                source_gaps.append("channel_account_managed_store_capability_drift")
        return self._payload(
            status=status,
            managed_store_bound=True,
            lease_fresh=lease_fresh,
            fingerprint_match=fingerprint_match,
            scope_match=scope_match,
            capabilities_match=capabilities_match,
            provider_readback_fresh_passed=provider_fresh,
            external_verifier_fresh_passed=external_fresh,
            source_gaps=source_gaps,
        )

    def _payload(
        self,
        *,
        status: str,
        managed_store_bound: bool,
        lease_fresh: bool,
        fingerprint_match: bool,
        scope_match: bool,
        capabilities_match: bool,
        provider_readback_fresh_passed: bool,
        external_verifier_fresh_passed: bool,
        source_gaps: list[str],
    ) -> dict[str, Any]:
        return {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "managed_store_bound": managed_store_bound,
            "lease_fresh": lease_fresh,
            "fingerprint_match": fingerprint_match,
            "scope_match": scope_match,
            "capabilities_match": capabilities_match,
            "provider_readback_fresh_passed": provider_readback_fresh_passed,
            "external_verifier_fresh_passed": external_verifier_fresh_passed,
            "source_gaps": sorted(set(source_gaps)),
            "secret_values_returned": False,
        }

    @classmethod
    def _verifier_fresh(
        cls,
        digest: str,
        verified_at: datetime | None,
        cutoff: datetime,
    ) -> bool:
        if (
            not cls._valid_sha256(digest)
            or verified_at is None
            or cls._aware(verified_at, "verified_at") > cutoff
        ):
            return False
        return (
            cutoff - cls._aware(verified_at, "verified_at")
        ).total_seconds() <= SignedManagedCredentialLeaseResolver.VERIFIER_TTL_SECONDS

    @staticmethod
    def _valid_sha256(value: Any) -> bool:
        normalized = str(value or "").strip().lower()
        return len(normalized) == 64 and all(char in "0123456789abcdef" for char in normalized)

    @staticmethod
    def _aware(value: Any, name: str) -> datetime:
        parsed = (
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if not isinstance(value, datetime)
            else value
        )
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
