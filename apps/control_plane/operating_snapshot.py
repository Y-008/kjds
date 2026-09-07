"""Immutable operating snapshot contract for PM replay and admission.

The Harness graph, server authority readers, and economic guard remain the
individual sources of truth.  This module only joins their already observed
values into one deterministic, secret-free snapshot.  It never reads a
clock, database, checkout, queue, credential, or external connector.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from typing import Any, Literal

CONTRACT_ID = "kjds-operating-snapshot-v1"
SNAPSHOT_STATES = {
    "proof": frozenset({"PROVED", "UNPROVED", "STALE", "BLOCKED", "NO_DATA"}),
    "evidence": frozenset({"VALID", "PARTIAL", "STALE", "BLOCKED", "NO_DATA", "UNKNOWN_OUTCOME"}),
    "operational": frozenset({"LIVE", "SHADOW", "PAUSED", "BLOCKED", "UNKNOWN"}),
    "economic": frozenset({"ALLOWED", "AT_RISK", "BLOCKED", "UNKNOWN"}),
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_SENSITIVE = ("token", "secret", "password", "credential", "cookie", "private_key", "api_key")
_AUTHORITY = ("permit", "approval", "external_write", "finance_entry", "formal_fact")


class OperatingSnapshotError(ValueError):
    """Raised when a snapshot is malformed or contains unsafe fields."""


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise OperatingSnapshotError("datetime requires timezone")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(mode="json"))
    raise OperatingSnapshotError(f"unsupported snapshot value: {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise OperatingSnapshotError("snapshot is not canonical JSON") from exc


def snapshot_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _text(value: Any, field: str, *, required: bool = True, maximum: int = 500) -> str:
    if value is None:
        if required:
            raise OperatingSnapshotError(f"{field} is required")
        return ""
    if not isinstance(value, str):
        raise OperatingSnapshotError(f"{field} must be text")
    result = value.strip()
    if required and not result:
        raise OperatingSnapshotError(f"{field} is required")
    if len(result) > maximum:
        raise OperatingSnapshotError(f"{field} exceeds {maximum} characters")
    return result


def _sha(value: Any, field: str, *, required: bool = True) -> str:
    result = _text(value, field, required=required, maximum=64).lower()
    if result and not _SHA256.fullmatch(result):
        raise OperatingSnapshotError(f"{field} must be a SHA-256 digest")
    return result


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise OperatingSnapshotError("observed_at must be ISO-8601") from exc
    else:
        raise OperatingSnapshotError("observed_at must be a datetime")
    if parsed.tzinfo is None:
        raise OperatingSnapshotError("observed_at requires timezone")
    return parsed.astimezone(UTC)


def _items(value: Any, field: str) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise OperatingSnapshotError(f"{field} must be an array")
    if len(value) > 500:
        raise OperatingSnapshotError(f"{field} exceeds 500 items")
    result = tuple(_jsonable(item) for item in value)
    if len(result) != len({json.dumps(item, sort_keys=True, ensure_ascii=False) for item in result}):
        raise OperatingSnapshotError(f"{field} must contain unique values")
    return result


def _scan_unsafe(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            token = str(key).lower().replace("-", "_")
            if any(marker in token for marker in _SENSITIVE):
                raise OperatingSnapshotError(f"{path}.{key} contains a sensitive field")
            if any(marker in token for marker in _AUTHORITY):
                raise OperatingSnapshotError(f"{path}.{key} contains an authority field")
            _scan_unsafe(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _scan_unsafe(item, f"{path}[{index}]")


@dataclass(frozen=True, slots=True)
class OperatingSnapshot:
    project_id: str
    tenant_ref: str
    entity_ref: str
    store_ref: str
    observed_at: datetime
    exact_head: str
    migration_head: str
    graph_snapshot_sha256: str
    proof_state: str
    evidence_state: str
    operational_state: str
    economic_state: str
    rollback_available: bool
    external_readback_passed: bool
    task_frontier: tuple[str, ...] = ()
    critical_path: tuple[str, ...] = ()
    blockers: tuple[Any, ...] = ()
    test_receipts: tuple[str, ...] = ()
    proof_receipts: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    snapshot_sha256: str = ""

    def __post_init__(self) -> None:
        for field_name in ("project_id", "tenant_ref", "entity_ref", "store_ref", "exact_head", "migration_head"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        object.__setattr__(self, "observed_at", _timestamp(self.observed_at))
        object.__setattr__(self, "graph_snapshot_sha256", _sha(self.graph_snapshot_sha256, "graph_snapshot_sha256"))
        for name in ("proof_state", "evidence_state", "operational_state", "economic_state"):
            state = _text(getattr(self, name), name).upper()
            category = name.removesuffix("_state")
            if state not in SNAPSHOT_STATES[category]:
                raise OperatingSnapshotError(f"{name} has unsupported state: {state}")
            object.__setattr__(self, name, state)
        for name in ("task_frontier", "critical_path", "test_receipts", "proof_receipts", "evidence_refs"):
            values = _items(getattr(self, name), name)
            if any(not isinstance(item, str) or not item.strip() for item in values):
                raise OperatingSnapshotError(f"{name} must contain non-empty strings")
            object.__setattr__(self, name, tuple(str(item).strip() for item in values))
        blockers = _items(self.blockers, "blockers")
        _scan_unsafe(blockers)
        object.__setattr__(self, "blockers", blockers)
        supplied = self.snapshot_sha256
        expected = snapshot_hash(self.payload())
        if supplied and supplied.lower() != expected:
            raise OperatingSnapshotError("snapshot_sha256 does not match payload")
        object.__setattr__(self, "snapshot_sha256", expected)

    def payload(self) -> dict[str, Any]:
        return {
            "contract_id": CONTRACT_ID,
            **{
                item.name: _jsonable(getattr(self, item.name))
                for item in fields(self)
                if item.name != "snapshot_sha256"
            },
            "admission_state": self.admission_state,
            "external_write_allowed": False,
        }

    def as_dict(self) -> dict[str, Any]:
        result = self.payload()
        result["snapshot_sha256"] = self.snapshot_sha256
        return result

    @property
    def admission_state(self) -> Literal["LIVE", "HOLD"]:
        return "LIVE" if (
            self.proof_state == "PROVED"
            and self.evidence_state == "VALID"
            and self.operational_state == "LIVE"
            and self.economic_state == "ALLOWED"
            and self.rollback_available
            and self.external_readback_passed
        ) else "HOLD"

    def replace(self, **changes: Any) -> OperatingSnapshot:
        return replace(self, **changes, snapshot_sha256="")


@dataclass(frozen=True, slots=True)
class OperatingSnapshotReplay:
    """Result of validating a persisted snapshot before it is replayed.

    A stored row is not evidence merely because it can be deserialized.  The
    surrounding heartbeat must bind the snapshot to the same project scope,
    graph digest, checkout observation and authority timestamp.  Keeping this
    result separate from :class:`OperatingSnapshot` lets API readers return a
    deterministic ``INVALID_REPLAY`` projection without ever exposing a
    malformed snapshot as an admissible one.
    """

    snapshot: OperatingSnapshot | None
    reasons: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.snapshot is not None and not self.reasons


def verify_operating_snapshot_replay(
    value: Any,
    *,
    expected_scope: Mapping[str, str] | None = None,
    expected_graph_snapshot_sha256: str | None = None,
    expected_exact_head: str | None = None,
    expected_observed_at: datetime | str | None = None,
) -> OperatingSnapshotReplay:
    """Validate a snapshot against the immutable heartbeat binding.

    This function is pure and does not read the clock or any external system.
    Missing or contradictory binding facts are reported as stable reason
    codes.  A caller must treat every non-empty reason tuple as unusable,
    even when the embedded snapshot's own digest is valid.
    """

    try:
        snapshot = build_operating_snapshot(value)
    except (OperatingSnapshotError, TypeError):
        return OperatingSnapshotReplay(None, ("snapshot_invalid",))

    reasons: list[str] = []
    if expected_scope is not None:
        for field in ("project_id", "tenant_ref", "entity_ref", "store_ref"):
            expected = expected_scope.get(field)
            if expected is not None and getattr(snapshot, field) != str(expected).strip():
                reasons.append(f"snapshot_scope_mismatch:{field}")

    if expected_graph_snapshot_sha256 is not None:
        expected_graph = str(expected_graph_snapshot_sha256).strip().lower()
        if snapshot.graph_snapshot_sha256 != expected_graph:
            reasons.append("snapshot_graph_digest_mismatch")

    if expected_exact_head is not None:
        expected_head = str(expected_exact_head).strip()
        if expected_head and snapshot.exact_head != expected_head:
            reasons.append("snapshot_head_mismatch")

    if expected_observed_at is not None:
        try:
            expected_time = _timestamp(expected_observed_at)
        except OperatingSnapshotError:
            reasons.append("snapshot_binding_time_invalid")
        else:
            if snapshot.observed_at != expected_time:
                reasons.append("snapshot_observed_at_mismatch")

    return OperatingSnapshotReplay(snapshot, tuple(dict.fromkeys(reasons)))


def build_operating_snapshot(value: Mapping[str, Any]) -> OperatingSnapshot:
    """Build a snapshot from already observed server facts."""

    if not isinstance(value, Mapping):
        raise OperatingSnapshotError("snapshot input must be an object")
    if value.get("external_write_allowed") is True:
        raise OperatingSnapshotError("snapshot cannot authorize external writes")
    scan_value = {
        key: item
        for key, item in value.items()
        if key not in {"contract_id", "admission_state", "external_write_allowed"}
    }
    _scan_unsafe(scan_value)
    allowed = {item.name for item in fields(OperatingSnapshot)}
    unknown = sorted(set(value) - allowed - {"contract_id", "admission_state", "external_write_allowed"})
    if unknown:
        raise OperatingSnapshotError("snapshot contains unsupported fields: " + ", ".join(unknown))
    return OperatingSnapshot(**{key: item for key, item in value.items() if key in allowed})


__all__ = [
    "CONTRACT_ID",
    "OperatingSnapshot",
    "OperatingSnapshotError",
    "OperatingSnapshotReplay",
    "build_operating_snapshot",
    "canonical_json",
    "snapshot_hash",
    "verify_operating_snapshot_replay",
]
