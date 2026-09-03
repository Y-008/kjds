"""Provider-neutral enterprise control contracts.

This module is deliberately framework-free.  It supplies the domain contracts
that sit between existing KJDS adapters (scope authority, customer exit,
commercial lifecycle, Ozon workers and the kill switch) and future durable
storage.  No class in this file performs a provider write or persists a secret.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

CONTRACT_VERSION = "kjds-enterprise-control-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_RE = re.compile(
    r"(?i)(?:api[-_ ]?key|client[-_ ]?secret|access[-_ ]?token|authorization|cookie|password|验证码|密钥)"
)
PII_RE = re.compile(
    r"(?i)(?:e-?mail|phone|mobile|address|passport|bank|account|customer[_ -]?(?:name|id)|姓名|电话|地址|银行卡|账号)"
)
SECRET_VALUE_RE = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~+/=-]{12,}|(?:api[-_ ]?key|client[-_ ]?secret|access[-_ ]?token|refresh[-_ ]?token|cookie|password)\s*[=:]\s*\S+)"
)
EMAIL_VALUE_RE = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
PHONE_VALUE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)")


class EnterpriseControlError(ValueError):
    """Stable domain error for enterprise-control contract violations."""


class ScopeViolation(EnterpriseControlError):
    pass


class WriteFrozenError(EnterpriseControlError):
    pass


class ReconciliationError(EnterpriseControlError):
    pass


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    PERSONAL = "personal"
    FINANCIAL = "financial"
    SECRET = "secret"


class RetentionAction(StrEnum):
    KEEP = "keep"
    EXPORT = "export"
    DELETE = "delete"
    LEGAL_HOLD = "legal_hold"


class FreezeMode(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"


class CashState(StrEnum):
    CASH_UNKNOWN = "CASH_UNKNOWN"
    CASH_PARTIAL = "CASH_PARTIAL"
    CASH_VERIFIED = "CASH_VERIFIED"


class FulfillmentMode(StrEnum):
    FBS = "FBS"
    FBO = "FBO"
    REAL_FBS = "realFBS"


class FulfillmentState(StrEnum):
    OBSERVED = "observed"
    RESERVED = "reserved"
    PACKING = "packing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    CLOSED = "closed"


class ReturnState(StrEnum):
    OPEN = "open"
    REVIEW = "review"
    APPROVED = "approved"
    REFUNDED = "refunded"
    REJECTED = "rejected"
    CLOSED = "closed"


class ProviderState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


def _text(value: Any, field_name: str, *, maximum: int = 160) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise EnterpriseControlError(f"{field_name} must be 1 to {maximum} characters")
    return normalized


def _utc(value: datetime | str | None, field_name: str = "timestamp") -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError as exc:
        raise EnterpriseControlError(f"{field_name} must be ISO 8601") from exc
    if not isinstance(parsed, datetime):
        raise EnterpriseControlError(f"{field_name} must be datetime")
    return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC))


def _money(value: Any, field_name: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise EnterpriseControlError(f"{field_name} must be a finite decimal") from exc
    if not number.is_finite():
        raise EnterpriseControlError(f"{field_name} must be a finite decimal")
    return number


def _currency(value: Any) -> str:
    normalized = _text(value, "currency", maximum=3).upper()
    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
        raise EnterpriseControlError("currency must be a three-letter ASCII code")
    return normalized


def _sha256(value: Any) -> str:
    if isinstance(value, bytes):
        raw = value
    else:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ExactScope:
    tenant_ref: str
    entity_ref: str
    store_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_ref", _text(self.tenant_ref, "tenant_ref"))
        object.__setattr__(self, "entity_ref", _text(self.entity_ref, "entity_ref"))
        object.__setattr__(self, "store_ref", _text(self.store_ref, "store_ref"))

    @property
    def key(self) -> str:
        return ":".join((self.tenant_ref, self.entity_ref, self.store_ref))

    def matches(self, other: ExactScope) -> bool:
        return self == other


@dataclass(frozen=True, slots=True)
class DataAsset:
    asset_ref: str
    scope: ExactScope
    classification: DataClassification
    content_sha256: str
    retention_class: str
    created_at: datetime
    expires_at: datetime | None = None
    legal_hold: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset_ref", _text(self.asset_ref, "asset_ref"))
        if not SHA256_RE.fullmatch(self.content_sha256):
            raise EnterpriseControlError("content_sha256 must be lowercase SHA-256")
        object.__setattr__(self, "retention_class", _text(self.retention_class, "retention_class"))
        created = _utc(self.created_at, "created_at")
        expires = _utc(self.expires_at, "expires_at") if self.expires_at else None
        if expires is not None and expires < created:
            raise EnterpriseControlError("expires_at cannot precede created_at")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "expires_at", expires)

    def due(self, *, as_of: datetime | str | None = None) -> bool:
        return bool(self.expires_at and _utc(as_of) >= self.expires_at and not self.legal_hold)


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    retention_class: str
    ttl: timedelta
    action: RetentionAction
    legal_hold_allowed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "retention_class", _text(self.retention_class, "retention_class"))
        if self.ttl <= timedelta(0):
            raise EnterpriseControlError("retention ttl must be positive")
        if self.action is RetentionAction.LEGAL_HOLD and not self.legal_hold_allowed:
            raise EnterpriseControlError("retention policy cannot require legal hold")

    def expires_at(self, created_at: datetime | str) -> datetime:
        return _utc(created_at, "created_at") + self.ttl


@runtime_checkable
class TenantBoundaryPort(Protocol):
    def assert_access(self, requested: ExactScope, principal: ExactScope) -> None: ...


@runtime_checkable
class DataClassificationPort(Protocol):
    def classify(self, payload: Mapping[str, Any]) -> DataClassification: ...


@runtime_checkable
class RetentionPolicyPort(Protocol):
    def policy_for(self, retention_class: str) -> RetentionPolicy: ...


@runtime_checkable
class SecretProviderPort(Protocol):
    def get(self, handle: str) -> str: ...

    def rotate(self, handle: str, value: str) -> str: ...

    def revoke(self, handle: str) -> None: ...


@runtime_checkable
class CustomerExportPort(Protocol):
    def export(self, customer_ref: str, scope: ExactScope) -> dict[str, Any]: ...


@runtime_checkable
class DataDeletionPort(Protocol):
    def plan(self, assets: Sequence[DataAsset], *, as_of: datetime | str | None = None) -> tuple[DataAsset, ...]: ...

    def execute(self, assets: Sequence[DataAsset], *, actor_id: str) -> dict[str, Any]: ...


@runtime_checkable
class BackupRepositoryPort(Protocol):
    def create_manifest(self, *, scope: ExactScope, archive: bytes, alembic_head: str, created_at: datetime | str | None = None) -> BackupManifest: ...


@runtime_checkable
class RestoreCoordinatorPort(Protocol):
    def restore(self, manifest: BackupManifest, *, target_database: str, dry_run: bool = True) -> RestoreReceipt: ...


@runtime_checkable
class DisasterRecoveryCheckPort(Protocol):
    def check(self, *, backup_created_at: datetime | str, restored_at: datetime | str, rpo: timedelta, rto: timedelta, as_of: datetime | str | None = None) -> DisasterRecoveryReport: ...


@runtime_checkable
class ExternalWriteFreezePort(Protocol):
    def freeze(self, *, reason: str, actor_id: str, as_of: datetime | str | None = None) -> FreezeState: ...

    def release(self, *, reason: str, actor_id: str, as_of: datetime | str | None = None) -> FreezeState: ...

    def ensure_writes_allowed(self) -> None: ...

    def current(self) -> FreezeState: ...


@runtime_checkable
class SettlementPort(Protocol):
    def match(self, rows: Sequence[CashLink]) -> CashReconciliation: ...


@runtime_checkable
class PayoutEvidencePort(Protocol):
    def accept(self, payout_ref: str, *, scope: ExactScope, amount: Decimal, currency: str, evidence_sha256: str) -> CashLink: ...


@runtime_checkable
class BankStatementPort(Protocol):
    def accept(self, statement_ref: str, *, scope: ExactScope, amount: Decimal, currency: str, evidence_sha256: str) -> CashLink: ...


@runtime_checkable
class FxAuthorityPort(Protocol):
    def rate(self, *, base: str, quote: str, as_of: datetime | str) -> Decimal: ...


@runtime_checkable
class TaxRulePackPort(Protocol):
    def rule_hash(self, *, country: str, effective_at: datetime | str) -> str: ...


@runtime_checkable
class BillingMeterPort(Protocol):
    def record(self, *, scope: ExactScope, metric: str, quantity: Decimal, unit: str, occurred_at: datetime | str | None = None) -> UsageMeter: ...


class InMemoryTenantBoundary(TenantBoundaryPort):
    """Exact-scope boundary for unit tests and local dry-runs."""

    def assert_access(self, requested: ExactScope, principal: ExactScope) -> None:
        if not principal.matches(requested):
            raise ScopeViolation("requested scope is outside the authenticated exact scope")


class PayloadClassifier(DataClassificationPort):
    """Conservative classifier used before traces, exports or model calls."""

    def classify(self, payload: Mapping[str, Any]) -> DataClassification:
        stack: list[tuple[str, Any]] = [(str(key), value) for key, value in payload.items()]
        highest = DataClassification.PUBLIC
        rank = {item: index for index, item in enumerate(DataClassification)}
        while stack:
            key, value = stack.pop()
            if SECRET_RE.search(key):
                highest = max(highest, DataClassification.SECRET, key=lambda item: rank[item])
            elif PII_RE.search(key):
                highest = max(highest, DataClassification.PERSONAL, key=lambda item: rank[item])
            elif any(token in key.lower() for token in ("finance", "amount", "bank", "payout", "settlement")):
                highest = max(highest, DataClassification.FINANCIAL, key=lambda item: rank[item])
            if isinstance(value, str):
                if SECRET_VALUE_RE.search(value):
                    highest = max(highest, DataClassification.SECRET, key=lambda item: rank[item])
                elif EMAIL_VALUE_RE.search(value) or PHONE_VALUE_RE.search(value):
                    highest = max(highest, DataClassification.PERSONAL, key=lambda item: rank[item])
            if isinstance(value, Mapping):
                stack.extend((str(child_key), child_value) for child_key, child_value in value.items())
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                stack.extend((key, child) for child in value)
        return highest


class InMemoryRetentionPolicies(RetentionPolicyPort):
    def __init__(self, policies: Mapping[str, RetentionPolicy] | None = None) -> None:
        self._policies = dict(policies or {})

    def add(self, policy: RetentionPolicy) -> None:
        self._policies[policy.retention_class] = policy

    def policy_for(self, retention_class: str) -> RetentionPolicy:
        try:
            return self._policies[_text(retention_class, "retention_class")]
        except KeyError as exc:
            raise EnterpriseControlError("retention policy is not configured") from exc


class InMemorySecretProvider(SecretProviderPort):
    """Test-only secret provider; values never appear in snapshots or reprs."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._revoked: set[str] = set()

    def put(self, handle: str, value: str) -> None:
        handle = _text(handle, "secret handle")
        if not value or "\n" in value:
            raise EnterpriseControlError("secret value must be non-empty and single-line")
        self._values[handle] = value
        self._revoked.discard(handle)

    def get(self, handle: str) -> str:
        handle = _text(handle, "secret handle")
        if handle in self._revoked or handle not in self._values:
            raise EnterpriseControlError("secret handle is unavailable")
        return self._values[handle]

    def rotate(self, handle: str, value: str) -> str:
        self.put(handle, value)
        return _sha256({"handle": handle, "version": len(self._values), "value": value})

    def revoke(self, handle: str) -> None:
        handle = _text(handle, "secret handle")
        self._revoked.add(handle)

    def snapshot(self) -> dict[str, Any]:
        return {"handles": sorted(self._values), "revoked": sorted(self._revoked)}


@dataclass(frozen=True, slots=True)
class DeletionReceipt:
    asset_refs: tuple[str, ...]
    actor_id: str
    deleted_at: datetime
    receipt_sha256: str


class InMemoryDataLifecycle(CustomerExportPort, DataDeletionPort):
    def __init__(self, assets: Iterable[DataAsset] = ()) -> None:
        self._assets = {asset.asset_ref: asset for asset in assets}
        self._deleted: dict[str, DeletionReceipt] = {}

    def add(self, asset: DataAsset) -> None:
        if asset.asset_ref in self._deleted:
            raise EnterpriseControlError("deleted asset reference cannot be reused")
        self._assets[asset.asset_ref] = asset

    def export(self, customer_ref: str, scope: ExactScope) -> dict[str, Any]:
        customer_ref = _text(customer_ref, "customer_ref")
        visible = [
            asset
            for asset in self._assets.values()
            if asset.scope == scope and customer_ref in asset.asset_ref
        ]
        payload = {
            "contract_id": "kjds-customer-export-v1",
            "customer_ref": customer_ref,
            "scope": {"tenant_ref": scope.tenant_ref, "entity_ref": scope.entity_ref, "store_ref": scope.store_ref},
            "assets": [
                {
                    "asset_ref": asset.asset_ref,
                    "classification": asset.classification.value,
                    "sha256": asset.content_sha256,
                    "retention_class": asset.retention_class,
                }
                for asset in sorted(visible, key=lambda item: item.asset_ref)
            ],
        }
        return {**payload, "manifest_sha256": _sha256(payload)}

    def plan(self, assets: Sequence[DataAsset], *, as_of: datetime | str | None = None) -> tuple[DataAsset, ...]:
        cutoff = _utc(as_of)
        expired = tuple(
            asset
            for asset in assets
            if asset.asset_ref in self._assets
            and asset.expires_at is not None
            and cutoff >= asset.expires_at
        )
        if any(asset.legal_hold for asset in expired):
            raise EnterpriseControlError("legal-hold assets cannot enter deletion plan")
        return tuple(asset for asset in expired if not asset.legal_hold)

    def execute(self, assets: Sequence[DataAsset], *, actor_id: str) -> dict[str, Any]:
        actor_id = _text(actor_id, "actor_id")
        refs = tuple(sorted({asset.asset_ref for asset in assets}))
        if any(ref not in self._assets for ref in refs):
            raise EnterpriseControlError("deletion includes an unknown asset")
        deleted_at = datetime.now(UTC)
        receipt = DeletionReceipt(refs, actor_id, deleted_at, _sha256({"asset_refs": refs, "actor_id": actor_id, "deleted_at": deleted_at.isoformat()}))
        for ref in refs:
            self._assets.pop(ref, None)
            self._deleted[ref] = receipt
        return {
            "contract_id": "kjds-data-deletion-v1",
            "asset_refs": refs,
            "actor_id": actor_id,
            "deleted_at": deleted_at.isoformat(),
            "receipt_sha256": receipt.receipt_sha256,
        }


@dataclass(frozen=True, slots=True)
class BackupManifest:
    backup_ref: str
    scope: ExactScope
    archive_sha256: str
    archive_bytes: int
    alembic_head: str
    created_at: datetime
    rpo_target_seconds: int = 900
    schema_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "backup_ref", _text(self.backup_ref, "backup_ref"))
        if not SHA256_RE.fullmatch(self.archive_sha256):
            raise EnterpriseControlError("archive_sha256 must be lowercase SHA-256")
        if self.archive_bytes <= 0:
            raise EnterpriseControlError("archive_bytes must be positive")
        if not _text(self.alembic_head, "alembic_head"):
            raise EnterpriseControlError("alembic_head is required")
        if self.rpo_target_seconds < 60:
            raise EnterpriseControlError("rpo target must be at least 60 seconds")
        object.__setattr__(self, "created_at", _utc(self.created_at, "created_at"))

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": "kjds-backup-manifest-v1",
            "backup_ref": self.backup_ref,
            "scope": {"tenant_ref": self.scope.tenant_ref, "entity_ref": self.scope.entity_ref, "store_ref": self.scope.store_ref},
            "archive_sha256": self.archive_sha256,
            "archive_bytes": self.archive_bytes,
            "alembic_head": self.alembic_head,
            "created_at": self.created_at.isoformat(),
            "rpo_target_seconds": self.rpo_target_seconds,
            "schema_version": self.schema_version,
        }


class InMemoryBackupRepository(BackupRepositoryPort):
    def __init__(self) -> None:
        self._manifests: dict[str, BackupManifest] = {}

    def create_manifest(self, *, scope: ExactScope, archive: bytes, alembic_head: str, created_at: datetime | str | None = None) -> BackupManifest:
        if not archive:
            raise EnterpriseControlError("backup archive cannot be empty")
        created = _utc(created_at)
        backup_ref = f"backup-{created.strftime('%Y%m%dT%H%M%SZ')}-{_sha256(archive)[:12]}"
        manifest = BackupManifest(backup_ref, scope, _sha256(archive), len(archive), alembic_head, created)
        existing = self._manifests.get(backup_ref)
        if existing is not None and existing != manifest:
            raise EnterpriseControlError("backup reference conflicts with a different archive")
        self._manifests[backup_ref] = manifest
        return manifest

    def get(self, backup_ref: str) -> BackupManifest:
        try:
            return self._manifests[_text(backup_ref, "backup_ref")]
        except KeyError as exc:
            raise KeyError("backup manifest not found") from exc

    def list(self, *, scope: ExactScope) -> tuple[BackupManifest, ...]:
        return tuple(sorted((item for item in self._manifests.values() if item.scope == scope), key=lambda item: item.created_at))


@dataclass(frozen=True, slots=True)
class RestoreReceipt:
    backup_ref: str
    target_database: str
    dry_run: bool
    restored_at: datetime
    alembic_head: str
    receipt_sha256: str


class InMemoryRestoreCoordinator(RestoreCoordinatorPort):
    def restore(self, manifest: BackupManifest, *, target_database: str, dry_run: bool = True) -> RestoreReceipt:
        target = _text(target_database, "target_database")
        if target.lower() in {"postgres", "production", "main", "hermes"} and not dry_run:
            raise EnterpriseControlError("restore cannot overwrite the source or production database")
        restored = datetime.now(UTC)
        payload = {"backup_ref": manifest.backup_ref, "target_database": target, "dry_run": dry_run, "restored_at": restored.isoformat(), "alembic_head": manifest.alembic_head}
        return RestoreReceipt(manifest.backup_ref, target, dry_run, restored, manifest.alembic_head, _sha256(payload))


@dataclass(frozen=True, slots=True)
class DisasterRecoveryReport:
    status: str
    observed_rpo_seconds: int
    observed_rto_seconds: int
    target_rpo_seconds: int
    target_rto_seconds: int
    blockers: tuple[str, ...]
    report_sha256: str


class RecoveryVerifier(DisasterRecoveryCheckPort):
    def check(self, *, backup_created_at: datetime | str, restored_at: datetime | str, rpo: timedelta, rto: timedelta, as_of: datetime | str | None = None) -> DisasterRecoveryReport:
        created = _utc(backup_created_at, "backup_created_at")
        restored = _utc(restored_at, "restored_at")
        if restored < created:
            raise EnterpriseControlError("restored_at cannot precede backup_created_at")
        observed_at = _utc(as_of, "as_of")
        observed_rpo = max(0, int((observed_at - created).total_seconds()))
        observed_rto = int((restored - created).total_seconds())
        blockers: list[str] = []
        if observed_rpo > int(rpo.total_seconds()):
            blockers.append("RPO_EXCEEDED")
        if observed_rto > int(rto.total_seconds()):
            blockers.append("RTO_EXCEEDED")
        payload = {"observed_rpo_seconds": observed_rpo, "observed_rto_seconds": observed_rto, "target_rpo_seconds": int(rpo.total_seconds()), "target_rto_seconds": int(rto.total_seconds()), "blockers": blockers}
        return DisasterRecoveryReport("PASS" if not blockers else "BLOCKED", observed_rpo, observed_rto, int(rpo.total_seconds()), int(rto.total_seconds()), tuple(blockers), _sha256(payload))


@dataclass(frozen=True, slots=True)
class FreezeState:
    mode: FreezeMode
    reason: str
    actor_id: str
    changed_at: datetime
    generation: int
    state_sha256: str


class InMemoryWriteFreeze(ExternalWriteFreezePort):
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self._state = self._make(FreezeMode.RUNNING, "initial", "system", now, 0)

    @staticmethod
    def _make(mode: FreezeMode, reason: str, actor_id: str, changed_at: datetime, generation: int) -> FreezeState:
        payload = {"mode": mode.value, "reason": reason, "actor_id": actor_id, "changed_at": changed_at.isoformat(), "generation": generation}
        return FreezeState(mode, reason, actor_id, changed_at, generation, _sha256(payload))

    def freeze(self, *, reason: str, actor_id: str, as_of: datetime | str | None = None) -> FreezeState:
        self._state = self._make(FreezeMode.PAUSED, _text(reason, "reason", maximum=500), _text(actor_id, "actor_id"), _utc(as_of), self._state.generation + 1)
        return self._state

    def release(self, *, reason: str, actor_id: str, as_of: datetime | str | None = None) -> FreezeState:
        self._state = self._make(FreezeMode.RUNNING, _text(reason, "reason", maximum=500), _text(actor_id, "actor_id"), _utc(as_of), self._state.generation + 1)
        return self._state

    def ensure_writes_allowed(self) -> None:
        if self._state.mode is FreezeMode.PAUSED:
            raise WriteFrozenError(f"external writes are frozen: {self._state.reason}")

    def current(self) -> FreezeState:
        return self._state


@dataclass(frozen=True, slots=True)
class CashLink:
    link_type: str
    external_ref: str
    scope: ExactScope
    amount: Decimal
    currency: str
    evidence_sha256: str
    matched_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "link_type", _text(self.link_type, "link_type", maximum=40))
        object.__setattr__(self, "external_ref", _text(self.external_ref, "external_ref"))
        object.__setattr__(self, "amount", _money(self.amount, "amount"))
        object.__setattr__(self, "currency", _currency(self.currency))
        if not SHA256_RE.fullmatch(self.evidence_sha256):
            raise EnterpriseControlError("cash evidence must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class CashReconciliation:
    state: CashState
    links: tuple[CashLink, ...]
    unmatched: tuple[str, ...]
    difference: Decimal
    currency: str
    reconciliation_sha256: str


class FiveLinkSettlementLedger(SettlementPort):
    REQUIRED = ("order", "posting", "accrual", "payout", "bank")

    def match(self, rows: Sequence[CashLink]) -> CashReconciliation:
        links = tuple(rows)
        if not links:
            return self._result(CashState.CASH_UNKNOWN, links, ("NO_LINKS",), Decimal(0), "CNY")
        currencies = {row.currency for row in links}
        if len(currencies) != 1:
            return self._result(CashState.CASH_PARTIAL, links, ("CURRENCY_MISMATCH",), Decimal(0), "MIXED")
        duplicate_types = sorted(
            link_type
            for link_type in {row.link_type for row in links}
            if sum(1 for row in links if row.link_type == link_type) > 1
        )
        if duplicate_types:
            return self._result(
                CashState.CASH_PARTIAL,
                links,
                tuple(f"DUPLICATE_{link_type.upper()}" for link_type in duplicate_types),
                Decimal(0),
                next(iter(currencies)),
            )
        if len({row.scope for row in links}) != 1:
            return self._result(
                CashState.CASH_PARTIAL,
                links,
                ("SCOPE_MISMATCH",),
                Decimal(0),
                next(iter(currencies)),
            )
        by_type = {row.link_type: row for row in links}
        unmatched = tuple(link_type for link_type in self.REQUIRED if link_type not in by_type)
        chain = {"order": "posting", "posting": "accrual", "accrual": "payout", "payout": "bank"}
        for current, target in chain.items():
            row = by_type.get(current)
            target_row = by_type.get(target)
            if row is not None and target_row is not None and row.matched_ref not in {None, target_row.external_ref}:
                unmatched += (f"CHAIN_{current.upper()}_MISMATCH",)
        difference = sum((row.amount for row in links), Decimal(0))
        if "bank" not in by_type:
            unmatched = (*unmatched, "BANK_EVIDENCE_MISSING") if "BANK_EVIDENCE_MISSING" not in unmatched else unmatched
        state = CashState.CASH_VERIFIED if not unmatched and difference == 0 else CashState.CASH_PARTIAL
        return self._result(state, links, tuple(sorted(set(unmatched))), difference, next(iter(currencies)))

    @staticmethod
    def _result(state: CashState, links: tuple[CashLink, ...], unmatched: tuple[str, ...], difference: Decimal, currency: str) -> CashReconciliation:
        payload = {"state": state.value, "links": [link.external_ref for link in links], "unmatched": unmatched, "difference": str(difference), "currency": currency}
        return CashReconciliation(state, links, unmatched, difference, currency, _sha256(payload))


@dataclass(frozen=True, slots=True)
class FulfillmentEpisode:
    episode_ref: str
    scope: ExactScope
    order_ref: str
    sku: str
    mode: FulfillmentMode
    state: FulfillmentState = FulfillmentState.OBSERVED
    state_changed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def transition(self, target: FulfillmentState, *, at: datetime | str | None = None) -> FulfillmentEpisode:
        base_allowed = {
            FulfillmentState.OBSERVED: {FulfillmentState.RESERVED, FulfillmentState.CANCELLED},
            FulfillmentState.RESERVED: {FulfillmentState.PACKING, FulfillmentState.CANCELLED},
            FulfillmentState.PACKING: {FulfillmentState.SHIPPED, FulfillmentState.CANCELLED},
            FulfillmentState.SHIPPED: {FulfillmentState.DELIVERED, FulfillmentState.RETURNED},
            FulfillmentState.DELIVERED: {FulfillmentState.RETURNED, FulfillmentState.CLOSED},
            FulfillmentState.RETURNED: {FulfillmentState.CLOSED},
            FulfillmentState.CANCELLED: {FulfillmentState.CLOSED},
            FulfillmentState.CLOSED: set(),
        }
        if self.mode is FulfillmentMode.FBO:
            allowed = {
                **base_allowed,
                FulfillmentState.RESERVED: {FulfillmentState.SHIPPED, FulfillmentState.CANCELLED},
                FulfillmentState.PACKING: set(),
            }
        elif self.mode is FulfillmentMode.REAL_FBS:
            allowed = {
                **base_allowed,
                FulfillmentState.PACKING: {FulfillmentState.SHIPPED},
            }
        else:
            allowed = base_allowed
        if target not in allowed[self.state]:
            raise EnterpriseControlError(f"invalid fulfillment transition: {self.state} -> {target}")
        return FulfillmentEpisode(self.episode_ref, self.scope, self.order_ref, self.sku, self.mode, target, _utc(at))


@dataclass(frozen=True, slots=True)
class InventoryReservation:
    reservation_ref: str
    scope: ExactScope
    sku: str
    quantity: int
    status: str = "reserved"

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise EnterpriseControlError("inventory reservation quantity must be positive")
        object.__setattr__(self, "sku", _text(self.sku, "sku"))

    def release(self) -> InventoryReservation:
        if self.status != "reserved":
            raise EnterpriseControlError("only reserved inventory can be released")
        return InventoryReservation(self.reservation_ref, self.scope, self.sku, self.quantity, "released")

    def commit(self) -> InventoryReservation:
        if self.status != "reserved":
            raise EnterpriseControlError("only reserved inventory can be committed")
        return InventoryReservation(self.reservation_ref, self.scope, self.sku, self.quantity, "committed")


@dataclass(frozen=True, slots=True)
class ReturnCase:
    case_ref: str
    scope: ExactScope
    order_ref: str
    sku: str
    reason: str
    state: ReturnState = ReturnState.OPEN

    def transition(self, target: ReturnState) -> ReturnCase:
        allowed = {
            ReturnState.OPEN: {ReturnState.REVIEW, ReturnState.REJECTED},
            ReturnState.REVIEW: {ReturnState.APPROVED, ReturnState.REJECTED},
            ReturnState.APPROVED: {ReturnState.REFUNDED},
            ReturnState.REFUNDED: {ReturnState.CLOSED},
            ReturnState.REJECTED: {ReturnState.CLOSED},
            ReturnState.CLOSED: set(),
        }
        if target not in allowed[self.state]:
            raise EnterpriseControlError(f"invalid return transition: {self.state} -> {target}")
        return ReturnCase(self.case_ref, self.scope, self.order_ref, self.sku, self.reason, target)


@dataclass(frozen=True, slots=True)
class SupplierQuote:
    quote_ref: str
    scope: ExactScope
    sku: str
    unit_cost: Decimal
    currency: str
    valid_until: datetime
    supplier_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "unit_cost", _money(self.unit_cost, "unit_cost"))
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "valid_until", _utc(self.valid_until, "valid_until"))
        object.__setattr__(self, "supplier_ref", _text(self.supplier_ref, "supplier_ref"))

    def is_current(self, *, as_of: datetime | str | None = None) -> bool:
        return _utc(as_of) <= self.valid_until


@dataclass(frozen=True, slots=True)
class LandedCostSnapshot:
    sku: str
    currency: str
    unit_cost: Decimal
    packaging_cost: Decimal
    freight_cost: Decimal
    customs_cost: Decimal
    warehouse_cost: Decimal
    platform_cost: Decimal
    fx_rate: Decimal
    effective_at: datetime
    source_hash: str

    @property
    def total_cost(self) -> Decimal:
        return sum((self.unit_cost, self.packaging_cost, self.freight_cost, self.customs_cost, self.warehouse_cost, self.platform_cost), Decimal(0))

    def __post_init__(self) -> None:
        object.__setattr__(self, "currency", _currency(self.currency))
        object.__setattr__(self, "fx_rate", _money(self.fx_rate, "fx_rate"))
        if self.fx_rate <= 0:
            raise EnterpriseControlError("fx_rate must be positive")
        if not SHA256_RE.fullmatch(self.source_hash):
            raise EnterpriseControlError("source_hash must be lowercase SHA-256")
        object.__setattr__(self, "effective_at", _utc(self.effective_at, "effective_at"))
        for name in ("unit_cost", "packaging_cost", "freight_cost", "customs_cost", "warehouse_cost", "platform_cost"):
            value = _money(getattr(self, name), name)
            if value < 0:
                raise EnterpriseControlError(f"{name} cannot be negative")
            object.__setattr__(self, name, value)


@dataclass(frozen=True, slots=True)
class ReconciliationException:
    exception_ref: str
    scope: ExactScope
    kind: str
    amount: Decimal
    currency: str
    owner_id: str
    due_at: datetime
    status: str = "open"

    def close(self, *, actor_id: str) -> ReconciliationException:
        if self.status != "open":
            raise ReconciliationError("reconciliation exception is already closed")
        if _text(actor_id, "actor_id") != self.owner_id:
            raise ReconciliationError("only the assigned owner may close a reconciliation exception")
        return ReconciliationException(self.exception_ref, self.scope, self.kind, self.amount, self.currency, self.owner_id, self.due_at, "closed")


@dataclass(frozen=True, slots=True)
class UsageMeter:
    scope: ExactScope
    metric: str
    quantity: Decimal
    unit: str
    occurred_at: datetime
    usage_sha256: str


class InMemoryBillingMeter(BillingMeterPort):
    def __init__(self, limits: Mapping[tuple[str, str], Decimal] | None = None) -> None:
        self._limits = {key: _money(value, "limit") for key, value in (limits or {}).items()}
        self._used: dict[tuple[str, str], Decimal] = {}
        self._entries: list[UsageMeter] = []

    def record(self, *, scope: ExactScope, metric: str, quantity: Decimal, unit: str, occurred_at: datetime | str | None = None) -> UsageMeter:
        metric = _text(metric, "metric")
        unit = _text(unit, "unit", maximum=40)
        quantity = _money(quantity, "quantity")
        if quantity < 0:
            raise EnterpriseControlError("usage quantity cannot be negative")
        key = (scope.key, metric)
        next_total = self._used.get(key, Decimal(0)) + quantity
        limit = self._limits.get(key)
        if limit is not None and next_total > limit:
            raise EnterpriseControlError(f"usage limit exceeded for {metric}")
        entry = UsageMeter(scope, metric, quantity, unit, _utc(occurred_at), _sha256({"scope": scope.key, "metric": metric, "quantity": str(quantity), "unit": unit, "occurred_at": _utc(occurred_at).isoformat()}))
        self._used[key] = next_total
        self._entries.append(entry)
        return entry

    def used(self, *, scope: ExactScope, metric: str) -> Decimal:
        return self._used.get((scope.key, _text(metric, "metric")), Decimal(0))


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    provider: str
    state: ProviderState
    checked_at: datetime
    detail: str | None = None


class ProviderFailoverRouter:
    """Deterministic provider choice; never turns provider health into business truth."""

    def __init__(self, *, primary: str, fallback: str, max_attempts: int = 2) -> None:
        self.primary = _text(primary, "primary provider")
        self.fallback = _text(fallback, "fallback provider")
        if self.primary == self.fallback:
            raise EnterpriseControlError("primary and fallback providers must differ")
        if max_attempts not in {1, 2}:
            raise EnterpriseControlError("provider router allows one or two attempts")
        self.max_attempts = max_attempts
        self._health: dict[str, ProviderSnapshot] = {}

    def update(self, snapshot: ProviderSnapshot) -> None:
        self._health[snapshot.provider] = snapshot

    def candidates(self) -> tuple[str, ...]:
        primary = self._health.get(self.primary)
        if primary is not None and primary.state is ProviderState.UNAVAILABLE:
            return (self.fallback,) if self.max_attempts > 1 else ()
        if self.max_attempts == 1:
            return (self.primary,)
        return (self.primary, self.fallback)

    def require_candidate(self) -> tuple[str, ...]:
        candidates = self.candidates()
        if not candidates:
            raise EnterpriseControlError("no model provider is available")
        return candidates


def safe_export_payload(payload: Mapping[str, Any], classifier: DataClassificationPort | None = None) -> dict[str, Any]:
    """Return a metadata-only projection suitable for audit logs."""
    classifier = classifier or PayloadClassifier()
    classification = classifier.classify(payload)
    if classification in {DataClassification.SECRET, DataClassification.PERSONAL, DataClassification.FINANCIAL}:
        return {"classification": classification.value, "payload_sha256": _sha256(payload), "field_count": len(payload)}
    return {"classification": classification.value, "payload": json.loads(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))}


__all__ = [
    "BackupManifest",
    "BackupRepositoryPort",
    "BankStatementPort",
    "CashLink",
    "CashReconciliation",
    "CashState",
    "CustomerExportPort",
    "DataAsset",
    "DataClassification",
    "DataClassificationPort",
    "DataDeletionPort",
    "DisasterRecoveryCheckPort",
    "DisasterRecoveryReport",
    "ExactScope",
    "ExternalWriteFreezePort",
    "FiveLinkSettlementLedger",
    "FreezeMode",
    "FreezeState",
    "FulfillmentEpisode",
    "FulfillmentMode",
    "FulfillmentState",
    "FxAuthorityPort",
    "InMemoryBackupRepository",
    "InMemoryDataLifecycle",
    "InMemoryRestoreCoordinator",
    "InMemoryRetentionPolicies",
    "InMemorySecretProvider",
    "InMemoryTenantBoundary",
    "InMemoryWriteFreeze",
    "InventoryReservation",
    "LandedCostSnapshot",
    "PayloadClassifier",
    "PayoutEvidencePort",
    "ProviderFailoverRouter",
    "ProviderSnapshot",
    "ProviderState",
    "ReconciliationException",
    "RecoveryVerifier",
    "RestoreCoordinatorPort",
    "RestoreReceipt",
    "RetentionAction",
    "RetentionPolicy",
    "RetentionPolicyPort",
    "ReturnCase",
    "ReturnState",
    "SecretProviderPort",
    "SettlementPort",
    "SupplierQuote",
    "TaxRulePackPort",
    "TenantBoundaryPort",
    "UsageMeter",
    "BillingMeterPort",
    "InMemoryBillingMeter",
    "WriteFrozenError",
    "safe_export_payload",
]
