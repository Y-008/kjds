"""Governed customer exit / data return / deletion contract kernel (COM-002 prep-only slice).

Freezes the C0 exit-export-and-deletion drill as a deterministic read-only state
machine: a customer-scoped exit request, a hash-bound export manifest, a
retention-policy deletion plan and a closed exit receipt. This kernel is a
contract and classifier only — it admits no real data export, deletion,
customer write, Fact, FinanceEntry, Approval, Permit, Pilot, Invoice, Payment or
Outbox authority; missing export content is reported UNKNOWN, never fabricated.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

EXIT_CONTRACT = "kjds-customer-exit-export-v1"
EXIT_VERSION = "1.0.0"

EXIT_STATES = (
    "requested",
    "export_prepared",
    "export_verified",
    "deletion_planned",
    "deletion_verified",
    "closed",
)

EXPORT_DATA_CLASSES = (
    "operating_products",
    "finance_orders",
    "profit_projections",
    "evidence_objects",
    "customer_pii",
)

RETENTION_DATA_CLASSES = ("deidentified_governance_audit_trail",)

DEFAULT_RETENTION_POLICY = ("deidentified_governance_audit_trail",)

REAL_EXECUTOR_ADMITTED = False

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,159}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")

SENSITIVE_MARKERS = (
    "authorization:",
    "bearer ",
    "cookie=",
    "api_key=",
    "access_token=",
    "refresh_token=",
    "client_secret=",
    "password=",
    "private_key=",
    "sk-",
)

ZERO_AUTHORITY_KEYS = frozenset(
    {
        "formal_fact",
        "finance_entry",
        "approval",
        "permit",
        "pilot",
        "outbox",
        "canonical_graph_write",
        "dependency_install",
        "network",
        "external_write",
        "invoice",
        "payment",
        "receivable",
        "external_data_export",
        "external_data_deletion",
    }
)


class CustomerExitError(ValueError):
    """Stable, non-sensitive contract failure for customer exit/export/deletion."""


@dataclass(frozen=True)
class ExitRequest:
    status: str
    contract_id: str
    customer_id: str
    scope: str
    authority: str
    requested_at: str
    retention_policy: tuple[str, ...]
    unknowns: tuple[str, ...]
    external_write_allowed: bool
    request_sha256: str


@dataclass(frozen=True)
class ExportManifest:
    status: str
    contract_id: str
    customer_id: str
    data_classes: tuple[dict[str, Any], ...]
    external_write_allowed: bool
    unknowns: tuple[str, ...]
    manifest_sha256: str


@dataclass(frozen=True)
class DeletionPlan:
    status: str
    contract_id: str
    customer_id: str
    targets: tuple[str, ...]
    retained: tuple[str, ...]
    external_write_allowed: bool
    unknowns: tuple[str, ...]
    plan_sha256: str


@dataclass(frozen=True)
class ExitReceipt:
    status: str
    contract_id: str
    customer_id: str
    export_sha256: str
    deletion_sha256: str
    closed_at: str
    external_write_allowed: bool
    receipt_sha256: str


def _text(value: Any, name: str, *, maximum: int = 300) -> str:
    if not isinstance(value, str) or not value:
        raise CustomerExitError(f"{name}_invalid")
    if len(value) > maximum:
        raise CustomerExitError(f"{name}_too_long")
    return value


def _token(value: Any, name: str) -> str:
    text = _text(value, name, maximum=160)
    if IDEMPOTENCY_PATTERN.fullmatch(text) is None:
        raise CustomerExitError(f"{name}_invalid")
    return text


def _hex64(value: Any, name: str) -> str:
    text = _text(value, name, maximum=64)
    if len(text) != 64 or HEX64.fullmatch(text) is None:
        raise CustomerExitError(f"{name}_invalid")
    return text


def _as_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _safe_tree(value: Any, *, depth: int = 0) -> None:
    if depth > 16:
        raise CustomerExitError("input_nesting_too_deep")
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SENSITIVE_MARKERS):
            raise CustomerExitError("sensitive_value_rejected")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise CustomerExitError("input_key_invalid")
            _safe_tree(child, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _safe_tree(child, depth=depth + 1)
        return
    if value is None or isinstance(value, (bool, int, float)):
        return
    raise CustomerExitError("input_type_invalid")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise CustomerExitError("time_invalid") from exc


def _norm_retention_policy(value: Any) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_RETENTION_POLICY
    if not isinstance(value, list):
        raise CustomerExitError("retention_policy_invalid")
    policy: list[str] = []
    for item in value:
        cls = _text(item, "retention_policy_item", maximum=120)
        if cls not in RETENTION_DATA_CLASSES:
            raise CustomerExitError("retention_policy_item_not_recognized")
        policy.append(cls)
    if not policy:
        raise CustomerExitError("retention_policy_empty")
    return tuple(sorted(set(policy)))


class GovernedCustomerExit:
    """Deterministic customer exit / data return / deletion contract kernel."""

    def __init__(self, *, clock: Any = None) -> None:
        self.clock = clock or (lambda: datetime.now(UTC))

    def open_exit_request(
        self,
        *,
        customer_id: str,
        scope: str,
        authority: str,
        requested_at: str | None = None,
        retention_policy: list[str] | None = None,
    ) -> ExitRequest:
        customer_id = _token(customer_id, "customer_id")
        scope = _text(scope, "scope", maximum=200)
        authority = _text(authority, "authority", maximum=200)
        if requested_at is None:
            requested_at = self.clock().isoformat()
        requested_at = _text(requested_at, "requested_at", maximum=40)
        _parse_time(requested_at)
        _safe_tree(customer_id)
        _safe_tree(scope)
        _safe_tree(authority)

        policy = _norm_retention_policy(retention_policy)

        unknowns: list[str] = []
        if retention_policy is None:
            unknowns.append("retention_policy")

        document = {
            "contract_id": EXIT_CONTRACT,
            "customer_id": customer_id,
            "scope": scope,
            "authority": authority,
            "requested_at": requested_at,
            "retention_policy": policy,
            "external_write_allowed": False,
        }
        return ExitRequest(
            status="requested",
            contract_id=EXIT_CONTRACT,
            customer_id=customer_id,
            scope=scope,
            authority=authority,
            requested_at=requested_at,
            retention_policy=policy,
            unknowns=tuple(sorted(unknowns)),
            external_write_allowed=False,
            request_sha256=_hash(document),
        )

    def prepare_export(self, *, request: ExitRequest, data_classes: list[dict[str, Any]] | None = None) -> ExportManifest:
        if not isinstance(request, ExitRequest):
            raise CustomerExitError("request_invalid")

        provided: dict[str, dict[str, Any]] = {}
        if data_classes is not None:
            if not isinstance(data_classes, list):
                raise CustomerExitError("data_classes_invalid")
            _safe_tree(data_classes)
            for entry in data_classes:
                if not isinstance(entry, Mapping):
                    raise CustomerExitError("data_class_entry_invalid")
                cls = _text(entry.get("class"), "data_class", maximum=120)
                if cls not in EXPORT_DATA_CLASSES:
                    raise CustomerExitError("data_class_not_recognized")
                if cls in provided:
                    raise CustomerExitError("data_class_duplicate")
                content_sha = entry.get("content_sha256")
                if content_sha is not None:
                    content_sha = _hex64(content_sha, "content_sha256")
                record_count = entry.get("record_count")
                if record_count is not None and _as_non_negative_int(record_count) is None:
                    raise CustomerExitError("record_count_invalid")
                provided[cls] = {
                    "content_sha256": content_sha,
                    "record_count": _as_non_negative_int(record_count) if record_count is not None else None,
                }

        rows: list[dict[str, Any]] = []
        unknowns: list[str] = []
        for cls in EXPORT_DATA_CLASSES:
            if cls in provided:
                entry = provided[cls]
                rows.append(
                    {
                        "data_class": cls,
                        "status": "EXPORTED" if entry["content_sha256"] is not None else "UNKNOWN",
                        "record_count": entry["record_count"],
                        "content_sha256": entry["content_sha256"],
                    }
                )
                if entry["content_sha256"] is None:
                    unknowns.append(f"{cls}_content_hash")
            else:
                rows.append({"data_class": cls, "status": "UNKNOWN", "record_count": None, "content_sha256": None})
                unknowns.append(cls)

        document = {
            "contract_id": EXIT_CONTRACT,
            "customer_id": request.customer_id,
            "data_classes": rows,
            "external_write_allowed": False,
        }
        return ExportManifest(
            status="export_prepared",
            contract_id=EXIT_CONTRACT,
            customer_id=request.customer_id,
            data_classes=tuple(rows),
            external_write_allowed=False,
            unknowns=tuple(sorted(set(unknowns))),
            manifest_sha256=_hash(document),
        )

    def plan_deletion(self, *, manifest: ExportManifest, retention_policy: list[str] | None = None) -> DeletionPlan:
        if not isinstance(manifest, ExportManifest):
            raise CustomerExitError("manifest_invalid")
        policy = _norm_retention_policy(retention_policy)
        targets = tuple(row["data_class"] for row in manifest.data_classes)
        document = {
            "contract_id": EXIT_CONTRACT,
            "customer_id": manifest.customer_id,
            "targets": targets,
            "retained": policy,
            "external_write_allowed": False,
        }
        return DeletionPlan(
            status="deletion_planned",
            contract_id=EXIT_CONTRACT,
            customer_id=manifest.customer_id,
            targets=targets,
            retained=policy,
            external_write_allowed=False,
            unknowns=(),
            plan_sha256=_hash(document),
        )

    def close_exit(self, *, manifest: ExportManifest, plan: DeletionPlan, closed_at: str | None = None) -> ExitReceipt:
        if not isinstance(manifest, ExportManifest):
            raise CustomerExitError("manifest_invalid")
        if not isinstance(plan, DeletionPlan):
            raise CustomerExitError("plan_invalid")
        if plan.customer_id != manifest.customer_id:
            raise CustomerExitError("customer_mismatch")
        if closed_at is None:
            closed_at = self.clock().isoformat()
        closed_at = _text(closed_at, "closed_at", maximum=40)
        _parse_time(closed_at)

        document = {
            "contract_id": EXIT_CONTRACT,
            "customer_id": manifest.customer_id,
            "export_sha256": manifest.manifest_sha256,
            "deletion_sha256": plan.plan_sha256,
            "closed_at": closed_at,
            "external_write_allowed": False,
        }
        return ExitReceipt(
            status="closed",
            contract_id=EXIT_CONTRACT,
            customer_id=manifest.customer_id,
            export_sha256=manifest.manifest_sha256,
            deletion_sha256=plan.plan_sha256,
            closed_at=closed_at,
            external_write_allowed=False,
            receipt_sha256=_hash(document),
        )

    def readback(self, obj: Any, *, observed: str | None = None) -> dict[str, Any]:
        if isinstance(obj, ExitRequest):
            digest = obj.request_sha256
        elif isinstance(obj, ExportManifest):
            digest = obj.manifest_sha256
        elif isinstance(obj, DeletionPlan):
            digest = obj.plan_sha256
        elif isinstance(obj, ExitReceipt):
            digest = obj.receipt_sha256
        else:
            raise CustomerExitError("readback_target_invalid")
        if observed is None:
            return {"readback_state": "PENDING", "integrity_ok": True}
        observed_hash = _hex64(observed, "observed")
        integrity_ok = observed_hash == digest
        return {
            "readback_state": "VERIFIED" if integrity_ok else "INVALIDATED",
            "integrity_ok": integrity_ok,
        }

    def zero_authority(self) -> dict[str, bool]:
        return {key: False for key in sorted(ZERO_AUTHORITY_KEYS)}


__all__ = [
    "DeletionPlan",
    "ExitReceipt",
    "ExitRequest",
    "ExportManifest",
    "GovernedCustomerExit",
    "CustomerExitError",
    "DEFAULT_RETENTION_POLICY",
    "EXIT_CONTRACT",
    "EXIT_STATES",
    "EXPORT_DATA_CLASSES",
    "REAL_EXECUTOR_ADMITTED",
    "RETENTION_DATA_CLASSES",
    "ZERO_AUTHORITY_KEYS",
]
