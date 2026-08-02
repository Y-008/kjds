from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from .channel_account_runtime_identity import (
    ManagedCredentialLeaseHandle,
    SignedManagedCredentialLeaseResolver,
    SignedWorkerCredentialGrantAuthority,
    _WorkerCredentialGrantRecord,
)
from .sql_repository import Base


class WorkerCredentialGrantRow(Base):
    """Non-secret derived authorization ledger with atomic one-time redemption."""

    __tablename__ = "channel_worker_credential_grants"
    __table_args__ = (
        CheckConstraint(
            "authorization_epoch > 0 "
            "AND issued_at < expires_at "
            "AND (revoked_at IS NULL OR revoked_at >= issued_at) "
            "AND (consumed_at IS NULL OR (consumed_at >= issued_at AND consumed_at < expires_at)) "
            "AND length(secret_reference_sha256) = 64 "
            "AND length(credential_fingerprint_sha256) = 64 "
            "AND length(lease_envelope_sha256) = 64 "
            "AND length(lease_signature) = 64",
            name="ck_channel_worker_credential_grant_authority",
        ),
        Index(
            "ix_channel_worker_credential_grant_scope",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "platform",
            "account_ref",
            "required_capability",
            "expires_at",
        ),
    )

    grant_id: Mapped[str] = mapped_column(String(240), primary_key=True)
    issuer: Mapped[str] = mapped_column(String(160), nullable=False)
    key_id: Mapped[str] = mapped_column(String(160), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    platform: Mapped[str] = mapped_column(String(80), nullable=False)
    account_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(160), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(80), nullable=False)
    required_capability: Mapped[str] = mapped_column(String(160), nullable=False)
    purpose: Mapped[str] = mapped_column(String(160), nullable=False)
    authorization_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_issuer: Mapped[str] = mapped_column(String(160), nullable=False)
    lease_key_id: Mapped[str] = mapped_column(String(160), nullable=False)
    lease_id: Mapped[str] = mapped_column(String(240), nullable=False)
    lease_envelope_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    lease_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    secret_reference_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    credential_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SqlWorkerCredentialGrantStore:
    """Session-bound store; consume_once is a single conditional database update."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, grant_id: str) -> _WorkerCredentialGrantRecord | None:
        row = self.session.get(WorkerCredentialGrantRow, grant_id)
        return self._record(row) if row is not None else None

    def consume_once(
        self,
        *,
        grant_id: str,
        consumed_at: datetime,
        expected_envelope_sha256: str,
    ) -> _WorkerCredentialGrantRecord:
        current = self.get(grant_id)
        if current is None:
            raise PermissionError("Worker credential grant does not exist")
        encoded = SignedManagedCredentialLeaseResolver._canonical_bytes(
            SignedWorkerCredentialGrantAuthority._envelope(current)
        )
        if hashlib.sha256(encoded).hexdigest() != expected_envelope_sha256:
            raise PermissionError("Worker credential grant envelope drift")
        statement = (
            update(WorkerCredentialGrantRow)
            .where(
                WorkerCredentialGrantRow.grant_id == grant_id,
                WorkerCredentialGrantRow.consumed_at.is_(None),
                WorkerCredentialGrantRow.revoked_at.is_(None),
                WorkerCredentialGrantRow.issued_at <= consumed_at,
                WorkerCredentialGrantRow.expires_at > consumed_at,
            )
            .values(consumed_at=consumed_at)
        )
        result = self.session.execute(statement)
        if result.rowcount != 1:
            raise PermissionError("Worker credential grant replay or inactive state was rejected")
        return replace(current, consumed_at=consumed_at)

    @staticmethod
    def _record(row: WorkerCredentialGrantRow) -> _WorkerCredentialGrantRecord:
        return _WorkerCredentialGrantRecord(
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
            revoked_at=(
                SignedManagedCredentialLeaseResolver._aware(row.revoked_at)
                if row.revoked_at is not None
                else None
            ),
            consumed_at=(
                SignedManagedCredentialLeaseResolver._aware(row.consumed_at)
                if row.consumed_at is not None
                else None
            ),
        )
