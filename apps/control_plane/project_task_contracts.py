"""Pure contracts for the AI project-manager work-breakdown.

This module deliberately contains no persistence, clock reads, subprocesses,
network calls, or external writes.  It is a small contract/projection layer
that can be consumed by the existing project graph and PM heartbeat without
becoming a second task ledger.

The contract models the five planning levels ``Initiative -> Program ->
Epic -> Slice -> Task`` and provides deterministic validation, dependency and
WIP projections, task result envelopes, and immutable release packets.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

CONTRACT_ID = "kjds-project-task-contract-v1"
CONTRACT_VERSION = "1.0.0"


class ProjectTaskContractError(ValueError):
    """Base error for malformed or unsafe planning contracts."""


class HierarchyError(ProjectTaskContractError):
    """Raised when a five-level work breakdown is not a valid DAG."""


class DependencyError(ProjectTaskContractError):
    """Raised when a dependency or critical-path request is invalid."""


class WIPLimitError(ProjectTaskContractError):
    """Raised when active writers exceed a declared WIP policy."""


class WorkLevel(StrEnum):
    INITIATIVE = "initiative"
    PROGRAM = "program"
    EPIC = "epic"
    SLICE = "slice"
    TASK = "task"


class TaskStatus(StrEnum):
    PLANNED = "PLANNED"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"
    REVIEW = "REVIEW"
    CONTRACT_VERIFIED = "CONTRACT_VERIFIED"
    INTEGRATION_VERIFIED = "INTEGRATION_VERIFIED"
    RUNTIME_PROVEN = "RUNTIME_PROVEN"
    BUSINESS_EVIDENCE_READY = "BUSINESS_EVIDENCE_READY"
    COMMERCIAL_READY = "COMMERCIAL_READY"
    RELEASED = "RELEASED"
    ROLLED_BACK = "ROLLED_BACK"
    RECOVERY = "RECOVERY"


class ClaimLevel(StrEnum):
    ENGINEERING = "engineering"
    RUNTIME = "runtime"
    BUSINESS = "business"
    COMMERCIAL = "commercial"


class BlockerKind(StrEnum):
    CODE = "code"
    RUNTIME = "runtime"
    EXTERNAL_EVIDENCE = "external_evidence"


LEVEL_PARENT: dict[str, str | None] = {
    WorkLevel.INITIATIVE.value: None,
    WorkLevel.PROGRAM.value: WorkLevel.INITIATIVE.value,
    WorkLevel.EPIC.value: WorkLevel.PROGRAM.value,
    WorkLevel.SLICE.value: WorkLevel.EPIC.value,
    WorkLevel.TASK.value: WorkLevel.SLICE.value,
}

VALID_STATUSES = frozenset(item.value for item in TaskStatus)
TERMINAL_STATUSES = frozenset(
    {
        TaskStatus.CONTRACT_VERIFIED.value,
        TaskStatus.INTEGRATION_VERIFIED.value,
        TaskStatus.RUNTIME_PROVEN.value,
        TaskStatus.BUSINESS_EVIDENCE_READY.value,
        TaskStatus.COMMERCIAL_READY.value,
        TaskStatus.RELEASED.value,
    }
)
ACTIVE_STATUSES = frozenset(
    {
        TaskStatus.ASSIGNED.value,
        TaskStatus.IN_PROGRESS.value,
        TaskStatus.REVIEW.value,
    }
)
READY_CANDIDATE_STATUSES = frozenset({TaskStatus.PLANNED.value, TaskStatus.READY.value})

# The limits are policy, not an observation of the currently running system.
DEFAULT_WIP_LIMITS: dict[str, int] = {
    "migration": 1,
    "core_api": 1,
    "frontend": 1,
    "external_connector": 1,
    "shared_contract": 1,
    "default": 1,
}

_SENSITIVE_KEY_MARKERS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
    }
)
_AUTHORITY_KEY_MARKERS = frozenset(
    {
        "approval",
        "external_write",
        "fact",
        "finance_entry",
        "formal_fact",
        "permit",
    }
)
_EXACT_HEAD = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")


def _key_token(value: Any) -> str:
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(value))
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _canonicalize(value: Any) -> Any:
    """Convert supported values to deterministic JSON-compatible values."""

    if is_dataclass(value):
        if hasattr(value, "to_dict"):
            return _canonicalize(value.to_dict())
        return _canonicalize(asdict(value))
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ProjectTaskContractError("datetime values require a timezone")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ProjectTaskContractError("numeric values must be finite")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProjectTaskContractError("numeric values must be finite")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise ProjectTaskContractError("mapping keys must be non-empty strings")
            result[key] = _canonicalize(item)
        return {key: result[key] for key in sorted(result)}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        values = [_canonicalize(item) for item in value]
        return sorted(values, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise ProjectTaskContractError(f"unsupported value type: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Return the canonical JSON representation used by all contract hashes."""

    try:
        normalized = _canonicalize(value)
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, OverflowError) as exc:
        if isinstance(exc, ProjectTaskContractError):
            raise
        raise ProjectTaskContractError("value is not canonical JSON") from exc


def canonical_hash(value: Any) -> str:
    """Return a stable SHA-256 for a JSON-compatible contract value."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _string(value: Any, field_name: str, *, required: bool = False, max_length: int = 1000) -> str:
    if value is None:
        if required:
            raise ProjectTaskContractError(f"{field_name} is required")
        return ""
    if not isinstance(value, str):
        raise ProjectTaskContractError(f"{field_name} must be a string")
    result = value.strip()
    if required and not result:
        raise ProjectTaskContractError(f"{field_name} is required")
    if len(result) > max_length:
        raise ProjectTaskContractError(f"{field_name} exceeds {max_length} characters")
    return result


def _strings(value: Any, field_name: str, *, max_items: int = 200, max_length: int = 1000) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        raise ProjectTaskContractError(f"{field_name} must be an array of strings")
    if len(value) > max_items:
        raise ProjectTaskContractError(f"{field_name} exceeds {max_items} items")
    result = tuple(_string(item, field_name, required=True, max_length=max_length) for item in value)
    if len(result) != len(set(result)):
        raise ProjectTaskContractError(f"{field_name} must contain unique values")
    return result


def _mapping(value: Any, field_name: str, *, required: bool = False) -> dict[str, Any]:
    if value is None:
        if required:
            raise ProjectTaskContractError(f"{field_name} is required")
        return {}
    if not isinstance(value, Mapping):
        raise ProjectTaskContractError(f"{field_name} must be an object")
    result = dict(_canonicalize(value))
    if required and not result:
        raise ProjectTaskContractError(f"{field_name} is required")
    return result


def _deadline(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ProjectTaskContractError("deadline must include timezone")
        return value.astimezone(UTC).isoformat()
    return _string(value, "deadline", required=True, max_length=80)


def _exact_head(value: Any) -> str:
    result = _string(value, "exact_head", required=True, max_length=64)
    if not _EXACT_HEAD.fullmatch(result):
        raise ProjectTaskContractError("exact_head must be a full 40 or 64 character Git object ID")
    return result.lower()


def _scan_unsafe_keys(value: Any) -> None:
    """Reject authority/secret fields in machine result payloads."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            token = _key_token(key)
            if any(marker in token for marker in _SENSITIVE_KEY_MARKERS):
                raise ProjectTaskContractError("contract payload cannot contain sensitive fields")
            if token in _AUTHORITY_KEY_MARKERS or any(marker in token for marker in _AUTHORITY_KEY_MARKERS):
                raise ProjectTaskContractError("contract payload cannot mint authority")
            _scan_unsafe_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _scan_unsafe_keys(item)


def _number(value: Any, field_name: str, *, minimum: Decimal = Decimal("0")) -> Decimal:
    try:
        number = Decimal(str(value))
    except Exception as exc:  # Decimal raises several concrete subclasses
        raise ProjectTaskContractError(f"{field_name} must be numeric") from exc
    if not number.is_finite() or number < minimum:
        raise ProjectTaskContractError(f"{field_name} must be finite and >= {minimum}")
    return number


@dataclass(frozen=True, slots=True)
class TaskBrief:
    """Fixed input envelope sent to one Agent for one bounded task."""

    task_id: str
    objective: str
    business_context: str = ""
    allowed_scope: tuple[str, ...] = ()
    prohibited_scope: tuple[str, ...] = ()
    input_snapshot: Mapping[str, Any] = field(default_factory=dict)
    exact_files_or_domain: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    expected_outputs: tuple[str, ...] = ()
    acceptance_tests: tuple[str, ...] = ()
    budget: Mapping[str, Any] = field(default_factory=dict)
    lease: Mapping[str, Any] = field(default_factory=dict)
    deadline: str | datetime | None = None
    rollback_ref: str | None = None
    reporting_format: tuple[str, ...] = ()
    parent_id: str | None = None
    scope: Mapping[str, Any] = field(default_factory=dict)
    owner: str = ""
    reviewer: str = ""
    risk_tier: str = "R0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _string(self.task_id, "task_id", required=True))
        object.__setattr__(self, "objective", _string(self.objective, "objective", required=True, max_length=4000))
        object.__setattr__(
            self, "business_context", _string(self.business_context, "business_context", max_length=8000)
        )
        for name in (
            "allowed_scope",
            "prohibited_scope",
            "exact_files_or_domain",
            "dependencies",
            "expected_outputs",
            "acceptance_tests",
            "reporting_format",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        object.__setattr__(self, "input_snapshot", _mapping(self.input_snapshot, "input_snapshot"))
        object.__setattr__(self, "budget", _mapping(self.budget, "budget"))
        object.__setattr__(self, "lease", _mapping(self.lease, "lease"))
        object.__setattr__(self, "scope", _mapping(self.scope, "scope"))
        object.__setattr__(self, "deadline", _deadline(self.deadline))
        object.__setattr__(self, "parent_id", _string(self.parent_id, "parent_id") or None)
        object.__setattr__(self, "rollback_ref", _string(self.rollback_ref, "rollback_ref") or None)
        object.__setattr__(self, "owner", _string(self.owner, "owner"))
        object.__setattr__(self, "reviewer", _string(self.reviewer, "reviewer"))
        object.__setattr__(self, "risk_tier", _string(self.risk_tier, "risk_tier", required=True, max_length=40))
        _scan_unsafe_keys(self.input_snapshot)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TaskBrief:
        if not isinstance(value, Mapping):
            raise ProjectTaskContractError("task brief must be an object")
        allowed = {field_name for field_name in cls.__dataclass_fields__}
        unknown = sorted(set(value) - allowed - {"contract_id", "contract_version"})
        if unknown:
            raise ProjectTaskContractError("task brief contains unsupported fields: " + ", ".join(unknown))
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CONTRACT_ID + ".task-brief",
            "contract_version": CONTRACT_VERSION,
            "task_id": self.task_id,
            "objective": self.objective,
            "business_context": self.business_context,
            "allowed_scope": list(self.allowed_scope),
            "prohibited_scope": list(self.prohibited_scope),
            "input_snapshot": _canonicalize(self.input_snapshot),
            "exact_files_or_domain": list(self.exact_files_or_domain),
            "dependencies": list(self.dependencies),
            "expected_outputs": list(self.expected_outputs),
            "acceptance_tests": list(self.acceptance_tests),
            "budget": _canonicalize(self.budget),
            "lease": _canonicalize(self.lease),
            "deadline": self.deadline,
            "rollback_ref": self.rollback_ref,
            "reporting_format": list(self.reporting_format),
            "parent_id": self.parent_id,
            "scope": _canonicalize(self.scope),
            "owner": self.owner,
            "reviewer": self.reviewer,
            "risk_tier": self.risk_tier,
        }

    @property
    def brief_sha256(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class TaskResult:
    """Fixed terminal/progress envelope returned by an Agent."""

    task_id: str
    status: str
    changed_files: tuple[str, ...] = ()
    schema_changes: tuple[str, ...] = ()
    api_changes: tuple[str, ...] = ()
    test_receipts: tuple[str, ...] = ()
    proof_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    blockers: tuple[Any, ...] = ()
    invalidated_nodes: tuple[str, ...] = ()
    economic_impact: Any = None
    rollback_ref: str | None = None
    next_dependencies: tuple[str, ...] = ()
    claim_level: str = ClaimLevel.ENGINEERING.value

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _string(self.task_id, "task_id", required=True))
        status = _string(self.status, "status", required=True, max_length=60).upper()
        if status not in VALID_STATUSES:
            raise ProjectTaskContractError(f"unknown task status: {status}")
        object.__setattr__(self, "status", status)
        for name in (
            "changed_files",
            "schema_changes",
            "api_changes",
            "test_receipts",
            "proof_refs",
            "evidence_refs",
            "invalidated_nodes",
            "next_dependencies",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        if self.blockers is None:
            object.__setattr__(self, "blockers", ())
        elif not isinstance(self.blockers, Sequence) or isinstance(self.blockers, (str, bytes, bytearray)):
            raise ProjectTaskContractError("blockers must be an array")
        else:
            blockers = tuple(_canonicalize(item) for item in self.blockers)
            _scan_unsafe_keys(blockers)
            object.__setattr__(self, "blockers", blockers)
        if self.economic_impact is not None:
            impact = _canonicalize(self.economic_impact)
            _scan_unsafe_keys(impact)
            object.__setattr__(self, "economic_impact", impact)
        object.__setattr__(self, "rollback_ref", _string(self.rollback_ref, "rollback_ref") or None)
        claim = _string(self.claim_level, "claim_level", required=True).lower()
        if claim not in {item.value for item in ClaimLevel}:
            raise ProjectTaskContractError(f"unknown claim level: {claim}")
        object.__setattr__(self, "claim_level", claim)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TaskResult:
        if not isinstance(value, Mapping):
            raise ProjectTaskContractError("task result must be an object")
        for key in value:
            token = _key_token(key)
            if token == "external_write_allowed":
                if value[key] is True:
                    raise ProjectTaskContractError("task results cannot authorize external writes")
                continue
            if token in _AUTHORITY_KEY_MARKERS or any(marker in token for marker in _AUTHORITY_KEY_MARKERS):
                raise ProjectTaskContractError("contract payload cannot mint authority")
            if any(marker in token for marker in _SENSITIVE_KEY_MARKERS):
                raise ProjectTaskContractError("contract payload cannot contain sensitive fields")
        allowed = {field_name for field_name in cls.__dataclass_fields__}
        unknown = sorted(set(value) - allowed - {"contract_id", "contract_version", "external_write_allowed"})
        if unknown:
            raise ProjectTaskContractError("task result contains unsupported fields: " + ", ".join(unknown))
        if value.get("external_write_allowed") is True:
            raise ProjectTaskContractError("task results cannot authorize external writes")
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CONTRACT_ID + ".task-result",
            "contract_version": CONTRACT_VERSION,
            "task_id": self.task_id,
            "status": self.status,
            "changed_files": list(self.changed_files),
            "schema_changes": list(self.schema_changes),
            "api_changes": list(self.api_changes),
            "test_receipts": list(self.test_receipts),
            "proof_refs": list(self.proof_refs),
            "evidence_refs": list(self.evidence_refs),
            "blockers": _canonicalize(self.blockers),
            "invalidated_nodes": list(self.invalidated_nodes),
            "economic_impact": _canonicalize(self.economic_impact),
            "rollback_ref": self.rollback_ref,
            "next_dependencies": list(self.next_dependencies),
            "claim_level": self.claim_level,
            "external_write_allowed": False,
        }

    @property
    def result_sha256(self) -> str:
        return canonical_hash(self.to_dict())


@dataclass(frozen=True, slots=True)
class WorkItem:
    """A node in the five-level planning hierarchy."""

    node_id: str
    level: str
    title: str = ""
    parent_id: str | None = None
    scope: Mapping[str, Any] = field(default_factory=dict)
    owner: str = ""
    reviewer: str = ""
    dependencies: tuple[str, ...] = ()
    exact_write_set: tuple[str, ...] = ()
    acceptance_tests: tuple[str, ...] = ()
    budget: Mapping[str, Any] = field(default_factory=dict)
    lease: Mapping[str, Any] = field(default_factory=dict)
    deadline: str | datetime | None = None
    risk_tier: str = "R0"
    rollback_ref: str | None = None
    status: str = TaskStatus.PLANNED.value
    blocker_kind: str | None = None
    critical_path_impact: Decimal | int | float = 1
    business_value: Decimal | int | float = 1
    information_gain: Decimal | int | float = 1
    risk_reduction: Decimal | int | float = 1
    estimated_cost: Decimal | int | float = 1
    claim_level: str = ClaimLevel.ENGINEERING.value

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _string(self.node_id, "node_id", required=True))
        level = _string(self.level, "level", required=True).lower()
        if level not in LEVEL_PARENT:
            raise ProjectTaskContractError(f"unknown work level: {level}")
        object.__setattr__(self, "level", level)
        object.__setattr__(self, "title", _string(self.title, "title", max_length=4000))
        object.__setattr__(self, "parent_id", _string(self.parent_id, "parent_id") or None)
        object.__setattr__(self, "scope", _mapping(self.scope, "scope"))
        object.__setattr__(self, "owner", _string(self.owner, "owner"))
        object.__setattr__(self, "reviewer", _string(self.reviewer, "reviewer"))
        object.__setattr__(self, "dependencies", _strings(self.dependencies, "dependencies"))
        object.__setattr__(self, "exact_write_set", _strings(self.exact_write_set, "exact_write_set"))
        object.__setattr__(self, "acceptance_tests", _strings(self.acceptance_tests, "acceptance_tests"))
        object.__setattr__(self, "budget", _mapping(self.budget, "budget"))
        object.__setattr__(self, "lease", _mapping(self.lease, "lease"))
        object.__setattr__(self, "deadline", _deadline(self.deadline))
        object.__setattr__(self, "risk_tier", _string(self.risk_tier, "risk_tier", required=True, max_length=40))
        object.__setattr__(self, "rollback_ref", _string(self.rollback_ref, "rollback_ref") or None)
        status = _string(self.status, "status", required=True).upper()
        if status not in VALID_STATUSES:
            raise ProjectTaskContractError(f"unknown task status: {status}")
        object.__setattr__(self, "status", status)
        if self.blocker_kind is not None:
            blocker = _string(self.blocker_kind, "blocker_kind", required=True).lower()
            if blocker not in {item.value for item in BlockerKind}:
                raise ProjectTaskContractError(f"unknown blocker kind: {blocker}")
            object.__setattr__(self, "blocker_kind", blocker)
        for name in (
            "critical_path_impact",
            "business_value",
            "information_gain",
            "risk_reduction",
            "estimated_cost",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        claim = _string(self.claim_level, "claim_level", required=True).lower()
        if claim not in {item.value for item in ClaimLevel}:
            raise ProjectTaskContractError(f"unknown claim level: {claim}")
        object.__setattr__(self, "claim_level", claim)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> WorkItem:
        if not isinstance(value, Mapping):
            raise ProjectTaskContractError("work item must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ProjectTaskContractError("work item contains unsupported fields: " + ", ".join(unknown))
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "level": self.level,
            "title": self.title,
            "parent_id": self.parent_id,
            "scope": _canonicalize(self.scope),
            "owner": self.owner,
            "reviewer": self.reviewer,
            "dependencies": list(self.dependencies),
            "exact_write_set": list(self.exact_write_set),
            "acceptance_tests": list(self.acceptance_tests),
            "budget": _canonicalize(self.budget),
            "lease": _canonicalize(self.lease),
            "deadline": self.deadline,
            "risk_tier": self.risk_tier,
            "rollback_ref": self.rollback_ref,
            "status": self.status,
            "blocker_kind": self.blocker_kind,
            "critical_path_impact": str(self.critical_path_impact),
            "business_value": str(self.business_value),
            "information_gain": str(self.information_gain),
            "risk_reduction": str(self.risk_reduction),
            "estimated_cost": str(self.estimated_cost),
            "claim_level": self.claim_level,
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    node_ids: tuple[str, ...]
    snapshot_sha256: str

    def raise_for_errors(self) -> ValidationReport:
        if not self.valid:
            raise HierarchyError("; ".join(self.errors))
        return self


def _coerce_items(items: Iterable[WorkItem | Mapping[str, Any]]) -> tuple[WorkItem, ...]:
    result: list[WorkItem] = []
    for item in items:
        result.append(item if isinstance(item, WorkItem) else WorkItem.from_mapping(item))
    return tuple(result)


def validate_work_breakdown(
    items: Iterable[WorkItem | Mapping[str, Any]],
    *,
    raise_on_error: bool = False,
) -> ValidationReport:
    """Validate hierarchy, dependencies, ownership and acceptance contracts."""

    nodes = _coerce_items(items)
    errors: list[str] = []
    warnings: list[str] = []
    by_id: dict[str, WorkItem] = {}
    for node in nodes:
        if node.node_id in by_id:
            errors.append(f"duplicate node_id: {node.node_id}")
        by_id[node.node_id] = node
    for node in nodes:
        expected_parent_level = LEVEL_PARENT[node.level]
        if expected_parent_level is None:
            if node.parent_id is not None:
                errors.append(f"{node.node_id}: initiative cannot have parent")
        elif node.parent_id is None:
            errors.append(f"{node.node_id}: {node.level} requires parent_id")
        elif node.parent_id not in by_id:
            errors.append(f"{node.node_id}: parent does not exist: {node.parent_id}")
        elif by_id[node.parent_id].level != expected_parent_level:
            errors.append(f"{node.node_id}: parent must be {expected_parent_level}")
        if not node.owner:
            errors.append(f"{node.node_id}: owner is required")
        if not node.reviewer:
            errors.append(f"{node.node_id}: reviewer is required")
        if node.owner and node.reviewer and node.owner == node.reviewer:
            errors.append(f"{node.node_id}: owner and reviewer must be distinct")
        if node.level in {WorkLevel.SLICE.value, WorkLevel.TASK.value}:
            if not node.exact_write_set:
                errors.append(f"{node.node_id}: exact_write_set is required")
            if not node.acceptance_tests:
                errors.append(f"{node.node_id}: acceptance_tests are required")
        if node.level in {WorkLevel.SLICE.value, WorkLevel.TASK.value} and node.status in TERMINAL_STATUSES and not node.rollback_ref:
            errors.append(f"{node.node_id}: terminal item requires rollback_ref")
        if node.status == TaskStatus.BLOCKED.value and not node.blocker_kind:
            errors.append(f"{node.node_id}: blocked item requires blocker_kind")
        for dependency in node.dependencies:
            if dependency == node.node_id:
                errors.append(f"{node.node_id}: self dependency")
            elif dependency not in by_id:
                errors.append(f"{node.node_id}: dependency does not exist: {dependency}")
    errors.extend(_cycle_errors(by_id))
    if not nodes:
        warnings.append("empty work breakdown")
    snapshot = canonical_hash({"contract_id": CONTRACT_ID, "nodes": [node.to_dict() for node in nodes]})
    report = ValidationReport(
        valid=not errors,
        errors=tuple(sorted(set(errors))),
        warnings=tuple(sorted(set(warnings))),
        node_ids=tuple(sorted(by_id)),
        snapshot_sha256=snapshot,
    )
    if raise_on_error:
        report.raise_for_errors()
    return report


def assert_valid_work_breakdown(items: Iterable[WorkItem | Mapping[str, Any]]) -> tuple[WorkItem, ...]:
    nodes = _coerce_items(items)
    validate_work_breakdown(nodes, raise_on_error=True)
    return nodes


def validate_task_brief(
    value: TaskBrief | Mapping[str, Any],
    *,
    require_owner: bool = True,
    require_reviewer: bool = True,
) -> ValidationReport:
    """Return a Definition-of-Ready report for a single task brief.

    This is intentionally a projection only.  It does not assign a lease,
    reserve budget, enqueue work, or create an OperatingTask.
    """

    try:
        brief = value if isinstance(value, TaskBrief) else TaskBrief.from_mapping(value)
    except ProjectTaskContractError as exc:
        return ValidationReport(False, (str(exc),), (), (), "")
    errors: list[str] = []
    if require_owner and not brief.owner:
        errors.append("owner is required")
    if require_reviewer and not brief.reviewer:
        errors.append("reviewer is required")
    if brief.owner and brief.reviewer and brief.owner == brief.reviewer:
        errors.append("owner and reviewer must be distinct")
    if not brief.scope:
        errors.append("scope is required")
    if not brief.exact_files_or_domain:
        errors.append("exact_files_or_domain is required")
    if not brief.acceptance_tests:
        errors.append("acceptance_tests is required")
    if brief.task_id in brief.dependencies:
        errors.append("task cannot depend on itself")
    digest = brief.brief_sha256
    report = ValidationReport(not errors, tuple(sorted(set(errors))), (), (brief.task_id,), digest)
    return report


def validate_task_result(
    value: TaskResult | Mapping[str, Any],
    *,
    requires_proof: bool = False,
    claim_level: str | None = None,
) -> ValidationReport:
    """Return a Definition-of-Done report without granting release authority."""

    try:
        result = value if isinstance(value, TaskResult) else TaskResult.from_mapping(value)
    except ProjectTaskContractError as exc:
        return ValidationReport(False, (str(exc),), (), (), "")
    errors: list[str] = []
    if result.status in TERMINAL_STATUSES:
        for field_name, values in (
            ("changed_files", result.changed_files),
            ("test_receipts", result.test_receipts),
            ("evidence_refs", result.evidence_refs),
        ):
            if not values:
                errors.append(f"{field_name} is required for terminal completion")
        if not result.rollback_ref:
            errors.append("rollback_ref is required for terminal completion")
        if result.blockers:
            errors.append("terminal completion cannot retain blockers")
        if result.invalidated_nodes:
            errors.append("terminal completion cannot retain invalidated nodes")
        if result.next_dependencies:
            errors.append("terminal completion cannot retain next_dependencies")
        if requires_proof and not result.proof_refs:
            errors.append("proof_refs are required")
        effective_claim = (claim_level or result.claim_level).lower()
        if effective_claim in {ClaimLevel.BUSINESS.value, ClaimLevel.COMMERCIAL.value} and result.economic_impact is None:
            errors.append("economic_impact is required for business/commercial completion")
    digest = result.result_sha256
    return ValidationReport(not errors, tuple(sorted(set(errors))), (), (result.task_id,), digest)


def build_project_snapshot(items: Iterable[WorkItem | Mapping[str, Any]]) -> dict[str, Any]:
    """Build a deterministic read-only PM projection for a work breakdown."""

    nodes = _nodes_or_raise(items)
    node_values = tuple(nodes.values())
    projection = {
        "contract_id": CONTRACT_ID + ".project-snapshot",
        "contract_version": CONTRACT_VERSION,
        "nodes": [node.to_dict() for node in sorted(node_values, key=lambda item: item.node_id)],
        "ready_frontier": list(ready_frontier(node_values)),
        "critical_path": list(critical_path(node_values)),
        "minimum_blocker_set": list(minimum_blocker_set(node_values)),
    }
    projection["snapshot_sha256"] = canonical_hash(projection)
    return projection


def project_harness_graph(graph: Mapping[str, Any]) -> dict[str, Any]:
    """Project an existing Harness workspace into the five-level WBS contract.

    This is intentionally a read-only adapter.  The Harness workspace remains
    the authority for task observations and graph snapshots; the returned WBS
    only makes planning completeness, frontier, blockers, and critical path
    visible to the AI project manager.  Missing owner, reviewer, write-set, or
    acceptance data is preserved as a validation error instead of being
    silently promoted to a completed task.
    """

    if not isinstance(graph, Mapping):
        raise ProjectTaskContractError("graph must be an object")
    project = graph.get("project") if isinstance(graph.get("project"), Mapping) else {}
    project_id = _string(project.get("id") or graph.get("project_id"), "project_id", required=True)
    prefix = f"project:{project_id}"
    system_owner = "system:project-manager"
    system_reviewer = "system:auditor"
    scope = graph.get("scope") if isinstance(graph.get("scope"), Mapping) else {}

    items: list[WorkItem] = [
        WorkItem(
            node_id=f"{prefix}:initiative",
            level=WorkLevel.INITIATIVE.value,
            title=str(project.get("title") or project_id),
            scope=scope,
            owner=system_owner,
            reviewer=system_reviewer,
            status=TaskStatus.CONTRACT_VERIFIED.value,
            claim_level=ClaimLevel.ENGINEERING.value,
        ),
        WorkItem(
            node_id=f"{prefix}:program",
            level=WorkLevel.PROGRAM.value,
            title="AI project manager control tower",
            parent_id=f"{prefix}:initiative",
            scope=scope,
            owner=system_owner,
            reviewer=system_reviewer,
            status=TaskStatus.CONTRACT_VERIFIED.value,
            claim_level=ClaimLevel.ENGINEERING.value,
        ),
        WorkItem(
            node_id=f"{prefix}:epic",
            level=WorkLevel.EPIC.value,
            title="Harness graph execution contract",
            parent_id=f"{prefix}:program",
            scope=scope,
            owner=system_owner,
            reviewer=system_reviewer,
            status=TaskStatus.CONTRACT_VERIFIED.value,
            claim_level=ClaimLevel.ENGINEERING.value,
        ),
        WorkItem(
            node_id=f"{prefix}:slice",
            level=WorkLevel.SLICE.value,
            title="Observed graph tasks",
            parent_id=f"{prefix}:epic",
            scope=scope,
            owner=system_owner,
            reviewer=system_reviewer,
            exact_write_set=(f"project-graph:{project_id}:planning-projection",),
            acceptance_tests=("source_snapshot_hash_bound", "wbs_validation_reported"),
            rollback_ref=(
                f"source-snapshot:{graph.get('snapshot_sha256')}"
                if graph.get("snapshot_sha256")
                else None
            ),
            status=TaskStatus.CONTRACT_VERIFIED.value,
            claim_level=ClaimLevel.ENGINEERING.value,
        ),
    ]

    state_map = {
        "passed": TaskStatus.CONTRACT_VERIFIED.value,
        "ready": TaskStatus.READY.value,
        "pending": TaskStatus.PLANNED.value,
        "running": TaskStatus.IN_PROGRESS.value,
        "in_progress": TaskStatus.IN_PROGRESS.value,
        "blocked": TaskStatus.BLOCKED.value,
        "failed": TaskStatus.BLOCKED.value,
        "stale": TaskStatus.STALE.value,
        "no_data": TaskStatus.BLOCKED.value,
    }
    tasks = graph.get("tasks") if isinstance(graph.get("tasks"), Sequence) else ()
    for raw in tasks:
        if not isinstance(raw, Mapping):
            continue
        task_id = _string(raw.get("id"), "task.id", required=True)
        raw_state = _string(raw.get("state") or "pending", "task.state").lower()
        status = state_map.get(raw_state, TaskStatus.BLOCKED.value)
        owner = _string(raw.get("owner"), "task.owner")
        reviewer = system_reviewer if owner != system_reviewer else system_owner
        workspace = _string(raw.get("workspace"), "task.workspace")
        verification = _string(raw.get("verification_condition"), "task.verification_condition")
        dependencies = tuple(str(item) for item in (raw.get("dependencies") or ()) if str(item).strip())
        blockers = raw.get("blockers") if isinstance(raw.get("blockers"), Sequence) else ()
        blocker_kind = BlockerKind.RUNTIME.value if status in {
            TaskStatus.BLOCKED.value,
            TaskStatus.STALE.value,
        } else None
        items.append(
            WorkItem(
                node_id=task_id,
                level=WorkLevel.TASK.value,
                title=_string(raw.get("title") or task_id, "task.title"),
                parent_id=f"{prefix}:slice",
                scope={"source": "harness", "project_id": project_id, **dict(scope)},
                owner=owner,
                reviewer=reviewer,
                dependencies=dependencies,
                exact_write_set=(workspace,) if workspace else (),
                acceptance_tests=(verification,) if verification else (),
                status=status,
                blocker_kind=blocker_kind,
                rollback_ref=(f"observation:{raw.get('observation_id')}" if raw.get("observation_id") else None),
                claim_level=ClaimLevel.ENGINEERING.value,
                business_value=2 if not blockers else 1,
                information_gain=2 if raw.get("evidence_ref") else 1,
                risk_reduction=2 if raw.get("artifact_ref") else 1,
            )
        )

    report = validate_work_breakdown(items)
    result = build_project_snapshot(items) if report.valid else {
        "contract_id": CONTRACT_ID + ".project-snapshot",
        "contract_version": CONTRACT_VERSION,
        "nodes": [item.to_dict() for item in sorted(items, key=lambda item: item.node_id)],
        "ready_frontier": [],
        "critical_path": [],
        "minimum_blocker_set": [],
    }
    result.update(
        {
            "projection_only": True,
            "source_contract_id": graph.get("contract_id"),
            "source_snapshot_sha256": graph.get("snapshot_sha256"),
            "project_id": project_id,
            "validation": {
                "valid": report.valid,
                "errors": list(report.errors),
                "warnings": list(report.warnings),
                "node_ids": list(report.node_ids),
                "snapshot_sha256": report.snapshot_sha256,
            },
            "external_write_allowed": False,
        }
    )
    # Invalid projections still need a deterministic binding for replay and
    # repair work.  The validation digest is the contract snapshot even when
    # the convenience planner fields are withheld due to malformed inputs.
    result.setdefault("snapshot_sha256", report.snapshot_sha256)
    result["projection_sha256"] = canonical_hash(result)
    return result


def _cycle_errors(by_id: Mapping[str, WorkItem]) -> list[str]:
    errors: list[str] = []
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node_id: str) -> None:
        marker = state.get(node_id, 0)
        if marker == 1:
            start = stack.index(node_id) if node_id in stack else 0
            errors.append("dependency cycle: " + " -> ".join(stack[start:] + [node_id]))
            return
        if marker == 2:
            return
        state[node_id] = 1
        stack.append(node_id)
        node = by_id[node_id]
        for dependency in node.dependencies:
            if dependency in by_id:
                visit(dependency)
        if node.parent_id and node.parent_id in by_id:
            visit(node.parent_id)
        stack.pop()
        state[node_id] = 2

    for node_id in sorted(by_id):
        visit(node_id)
    return errors


def _nodes_or_raise(items: Iterable[WorkItem | Mapping[str, Any]]) -> dict[str, WorkItem]:
    nodes = _coerce_items(items)
    validate_work_breakdown(nodes, raise_on_error=True)
    return {node.node_id: node for node in nodes}


def ready_frontier(items: Iterable[WorkItem | Mapping[str, Any]]) -> tuple[str, ...]:
    """Return actionable leaf IDs whose dependencies and parent are healthy.

    Initiative, program, epic and slice nodes are planning containers.  They
    remain visible in the graph, but only leaf work items are dispatchable by
    the PM frontier projection.
    """

    by_id = _nodes_or_raise(items)
    ready: list[str] = []
    child_ids = {node.parent_id for node in by_id.values() if node.parent_id}
    for node_id, node in by_id.items():
        if node.status not in READY_CANDIDATE_STATUSES:
            continue
        if node.level != WorkLevel.TASK.value and node_id in child_ids:
            continue
        if node.parent_id and by_id[node.parent_id].status in {
            TaskStatus.BLOCKED.value,
            TaskStatus.STALE.value,
            TaskStatus.INVALIDATED.value,
            TaskStatus.ROLLED_BACK.value,
            TaskStatus.RECOVERY.value,
        }:
            continue
        if all(by_id[dependency].status in TERMINAL_STATUSES for dependency in node.dependencies):
            ready.append(node_id)
    return tuple(sorted(ready))


def minimum_blocker_set(items: Iterable[WorkItem | Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Project the smallest explicit blockers without changing task state."""

    by_id = _nodes_or_raise(items)
    blockers: list[dict[str, Any]] = []
    for node_id, node in sorted(by_id.items()):
        missing = [dependency for dependency in node.dependencies if by_id[dependency].status not in TERMINAL_STATUSES]
        if node.status in {TaskStatus.BLOCKED.value, TaskStatus.STALE.value, TaskStatus.INVALIDATED.value} or missing:
            blockers.append(
                {
                    "node_id": node_id,
                    "kind": node.blocker_kind or (BlockerKind.CODE.value if missing else BlockerKind.RUNTIME.value),
                    "status": node.status,
                    "blocking_dependencies": sorted(missing),
                }
            )
    return tuple(blockers)


def _weight(node: WorkItem) -> Decimal:
    numerator = node.critical_path_impact * node.business_value * node.information_gain * node.risk_reduction
    return numerator / (node.estimated_cost or Decimal("1"))


def critical_path(items: Iterable[WorkItem | Mapping[str, Any]]) -> tuple[str, ...]:
    """Return the highest-weight unresolved dependency path.

    The result is deterministic and includes unresolved nodes only.  Completed
    prerequisites contribute no path weight but still satisfy dependencies.
    """

    by_id = _nodes_or_raise(items)
    unresolved = {node_id for node_id, node in by_id.items() if node.status not in TERMINAL_STATUSES}
    if not unresolved:
        return ()
    children: dict[str, list[str]] = defaultdict(list)
    for node in by_id.values():
        for dependency in node.dependencies:
            children[dependency].append(node.node_id)
    for values in children.values():
        values.sort()
    memo: dict[str, tuple[Decimal, tuple[str, ...]]] = {}

    def longest(node_id: str) -> tuple[Decimal, tuple[str, ...]]:
        if node_id in memo:
            return memo[node_id]
        node = by_id[node_id]
        candidates = [longest(child) for child in children.get(node_id, ()) if child in unresolved]
        own = _weight(node) if node_id in unresolved else Decimal("0")
        if not candidates:
            result = (own, (node_id,) if node_id in unresolved else ())
        else:
            best_score, best_path = max(candidates, key=lambda item: (item[0], tuple(reversed(item[1]))))
            result = (own + best_score, ((node_id,) if node_id in unresolved else ()) + best_path)
        memo[node_id] = result
        return result

    roots = sorted(
        node_id
        for node_id in unresolved
        if not any(dependency in unresolved for dependency in by_id[node_id].dependencies)
    )
    paths = [longest(node_id) for node_id in roots]
    if not paths:
        return tuple(sorted(unresolved))
    return max(paths, key=lambda item: (item[0], tuple(reversed(item[1]))))[1]


def _write_group(resource: str) -> tuple[str, str]:
    normalized = resource.strip().lower().replace("\\", "/")
    if not normalized:
        return "default", "default"
    if (
        normalized == "migration"
        or normalized.startswith("migration:")
        or "/migrations/" in f"/{normalized}/"
        or normalized.startswith("migrations/")
    ):
        return "migration", "migration"
    prefixes = (
        ("core_api", "core_api"),
        ("api", "core_api"),
        ("router", "core_api"),
        ("frontend", "frontend"),
        ("web", "frontend"),
        ("ui", "frontend"),
        ("external_connector", "external_connector"),
        ("connector", "external_connector"),
        ("shared_contract", "shared_contract"),
        ("contract", "shared_contract"),
        ("schema", "shared_contract"),
    )
    for prefix, category in prefixes:
        if normalized == prefix or normalized.startswith(prefix + ":") or normalized.startswith(prefix + "/"):
            suffix = normalized[len(prefix) :].lstrip(":/") or "*"
            # Domain-scoped policies count one writer per domain even when a
            # task owns several files below that domain.
            if "/" in suffix and suffix != "*":
                suffix = suffix.split("/", 1)[0]
            return category, f"{category}:{suffix}"
    return "default", normalized


@dataclass(frozen=True, slots=True)
class WIPPolicy:
    limits: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_WIP_LIMITS))

    def __post_init__(self) -> None:
        raw = _mapping(self.limits, "limits", required=True)
        normalized: dict[str, int] = {}
        for key, value in raw.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ProjectTaskContractError("WIP limits must be positive integers")
            normalized[key.lower()] = value
        object.__setattr__(self, "limits", normalized)


@dataclass(frozen=True, slots=True)
class WIPReport:
    valid: bool
    counts: Mapping[str, int]
    violations: tuple[str, ...]
    active_task_ids: tuple[str, ...]
    snapshot_sha256: str

    def raise_for_errors(self) -> WIPReport:
        if not self.valid:
            raise WIPLimitError("; ".join(self.violations))
        return self


def validate_wip(
    active_items: Iterable[TaskBrief | WorkItem | Mapping[str, Any]],
    policy: WIPPolicy | Mapping[str, int] | None = None,
    *,
    raise_on_error: bool = False,
) -> WIPReport:
    """Validate active writer limits and exact write-domain collisions."""

    wip_policy = policy if isinstance(policy, WIPPolicy) else WIPPolicy(policy or DEFAULT_WIP_LIMITS)
    tasks: list[TaskBrief | WorkItem] = []
    for item in active_items:
        if isinstance(item, (TaskBrief, WorkItem)):
            tasks.append(item)
        elif isinstance(item, Mapping):
            tasks.append(TaskBrief.from_mapping(item))
        else:
            raise ProjectTaskContractError("active_items must contain TaskBrief or WorkItem values")
    counts: dict[str, int] = defaultdict(int)
    violations: list[str] = []
    exact_owners: dict[str, str] = {}
    active_ids: list[str] = []
    for task in tasks:
        task_id = task.task_id if isinstance(task, TaskBrief) else task.node_id
        status = TaskStatus.IN_PROGRESS.value if isinstance(task, TaskBrief) else task.status
        if status not in ACTIVE_STATUSES:
            continue
        active_ids.append(task_id)
        resources = task.exact_files_or_domain if isinstance(task, TaskBrief) else task.exact_write_set
        groups_for_task: set[tuple[str, str]] = set()
        for resource in resources:
            category, group = _write_group(resource)
            groups_for_task.add((category, group))
            owner = exact_owners.get(group)
            if owner is not None and owner != task_id:
                violations.append(f"write-domain collision: {group} ({owner}, {task_id})")
            exact_owners[group] = task_id
        for category, group in sorted(groups_for_task):
            counts[group] += 1
            limit = wip_policy.limits.get(group, wip_policy.limits.get(category, wip_policy.limits.get("default", 1)))
            if counts[group] > limit:
                violations.append(f"WIP limit exceeded: {group} ({counts[group]}/{limit})")
    report = WIPReport(
        valid=not violations,
        counts=dict(sorted(counts.items())),
        violations=tuple(sorted(set(violations))),
        active_task_ids=tuple(sorted(active_ids)),
        snapshot_sha256=canonical_hash(
            {
                "contract_id": CONTRACT_ID + ".wip",
                "counts": dict(sorted(counts.items())),
                "violations": sorted(set(violations)),
            }
        ),
    )
    if raise_on_error:
        report.raise_for_errors()
    return report


@dataclass(frozen=True, slots=True)
class ReleasePacket:
    """Immutable wave handoff; it is evidence, not a release command."""

    wave_id: str
    goal: str
    included_tasks: tuple[str, ...]
    excluded_tasks: tuple[str, ...] = ()
    dependency_frontier: tuple[str, ...] = ()
    exact_head: str = ""
    migration_head: str | None = None
    changed_paths: tuple[str, ...] = ()
    api_schema_diff: tuple[str, ...] = ()
    test_receipts: tuple[str, ...] = ()
    runtime_receipt: str | None = None
    business_evidence: tuple[str, ...] = ()
    economic_impact: Any = None
    open_blockers: tuple[Any, ...] = ()
    invalidated_nodes: tuple[str, ...] = ()
    rollback_ref: str | None = None
    next_wave: tuple[str, ...] = ()
    claim_level: str = ClaimLevel.ENGINEERING.value
    external_write_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "wave_id", _string(self.wave_id, "wave_id", required=True))
        object.__setattr__(self, "goal", _string(self.goal, "goal", required=True, max_length=4000))
        for name in (
            "included_tasks",
            "excluded_tasks",
            "dependency_frontier",
            "changed_paths",
            "api_schema_diff",
            "test_receipts",
            "business_evidence",
            "invalidated_nodes",
            "next_wave",
        ):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        object.__setattr__(self, "exact_head", _exact_head(self.exact_head))
        object.__setattr__(self, "migration_head", _string(self.migration_head, "migration_head") or None)
        object.__setattr__(self, "runtime_receipt", _string(self.runtime_receipt, "runtime_receipt") or None)
        object.__setattr__(self, "rollback_ref", _string(self.rollback_ref, "rollback_ref") or None)
        if self.open_blockers is None:
            object.__setattr__(self, "open_blockers", ())
        elif not isinstance(self.open_blockers, Sequence) or isinstance(self.open_blockers, (str, bytes, bytearray)):
            raise ProjectTaskContractError("open_blockers must be an array")
        else:
            blockers = tuple(_canonicalize(item) for item in self.open_blockers)
            _scan_unsafe_keys(blockers)
            object.__setattr__(self, "open_blockers", blockers)
        if self.economic_impact is not None:
            impact = _canonicalize(self.economic_impact)
            _scan_unsafe_keys(impact)
            object.__setattr__(self, "economic_impact", impact)
        claim = _string(self.claim_level, "claim_level", required=True).lower()
        if claim not in {item.value for item in ClaimLevel}:
            raise ProjectTaskContractError(f"unknown claim level: {claim}")
        object.__setattr__(self, "claim_level", claim)
        if self.external_write_allowed:
            raise ProjectTaskContractError("release packets cannot authorize external writes")

    @property
    def packet_sha256(self) -> str:
        return canonical_hash(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ReleasePacket:
        if not isinstance(value, Mapping):
            raise ProjectTaskContractError("release packet must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(value) - allowed - {"contract_id", "contract_version"})
        if unknown:
            raise ProjectTaskContractError(
                "release packet contains unsupported fields: " + ", ".join(unknown)
            )
        if value.get("external_write_allowed") is True:
            raise ProjectTaskContractError("release packets cannot authorize external writes")
        return cls(**{key: item for key, item in value.items() if key in allowed})

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": CONTRACT_ID + ".release-packet",
            "contract_version": CONTRACT_VERSION,
            "wave_id": self.wave_id,
            "goal": self.goal,
            "included_tasks": list(self.included_tasks),
            "excluded_tasks": list(self.excluded_tasks),
            "dependency_frontier": list(self.dependency_frontier),
            "exact_head": self.exact_head,
            "migration_head": self.migration_head,
            "changed_paths": list(self.changed_paths),
            "api_schema_diff": list(self.api_schema_diff),
            "test_receipts": list(self.test_receipts),
            "runtime_receipt": self.runtime_receipt,
            "business_evidence": list(self.business_evidence),
            "economic_impact": _canonicalize(self.economic_impact),
            "open_blockers": _canonicalize(self.open_blockers),
            "invalidated_nodes": list(self.invalidated_nodes),
            "rollback_ref": self.rollback_ref,
            "next_wave": list(self.next_wave),
            "claim_level": self.claim_level,
            "external_write_allowed": False,
        }


def _task_ref(value: str | TaskBrief | WorkItem) -> str:
    if isinstance(value, TaskBrief):
        return value.task_id
    if isinstance(value, WorkItem):
        return value.node_id
    return _string(value, "task reference", required=True)


def build_release_packet(
    wave_id: str,
    goal: str,
    included_tasks: Iterable[str | TaskBrief | WorkItem],
    *,
    excluded_tasks: Iterable[str | TaskBrief | WorkItem] = (),
    dependency_frontier: Iterable[str] = (),
    exact_head: str,
    migration_head: str | None = None,
    changed_paths: Iterable[str] = (),
    api_schema_diff: Iterable[str] = (),
    test_receipts: Iterable[str] = (),
    runtime_receipt: str | None = None,
    business_evidence: Iterable[str] = (),
    economic_impact: Any = None,
    open_blockers: Iterable[Any] = (),
    invalidated_nodes: Iterable[str] = (),
    rollback_ref: str | None = None,
    next_wave: Iterable[str] = (),
    claim_level: str = ClaimLevel.ENGINEERING.value,
) -> ReleasePacket:
    """Build a deterministic release packet without publishing or mutating state."""

    return ReleasePacket(
        wave_id=wave_id,
        goal=goal,
        included_tasks=tuple(_task_ref(item) for item in included_tasks),
        excluded_tasks=tuple(_task_ref(item) for item in excluded_tasks),
        dependency_frontier=tuple(dependency_frontier),
        exact_head=exact_head,
        migration_head=migration_head,
        changed_paths=tuple(changed_paths),
        api_schema_diff=tuple(api_schema_diff),
        test_receipts=tuple(test_receipts),
        runtime_receipt=runtime_receipt,
        business_evidence=tuple(business_evidence),
        economic_impact=economic_impact,
        open_blockers=tuple(open_blockers),
        invalidated_nodes=tuple(invalidated_nodes),
        rollback_ref=rollback_ref,
        next_wave=tuple(next_wave),
        claim_level=claim_level,
    )


def invalidate_downstream(
    items: Iterable[WorkItem | Mapping[str, Any]],
    changed_node_ids: Iterable[str],
) -> tuple[WorkItem, ...]:
    """Return a new projection with dependent nodes marked INVALIDATED.

    Existing nodes and receipts are preserved; the function only projects the
    state transition and never deletes or overwrites a historical record.
    """

    nodes = _nodes_or_raise(items)
    changed = {_string(item, "changed_node_id", required=True) for item in changed_node_ids}
    unknown = sorted(changed - set(nodes))
    if unknown:
        raise DependencyError("changed node does not exist: " + ", ".join(unknown))
    invalidated = set(changed)
    queue = deque(sorted(changed))
    children: dict[str, list[str]] = defaultdict(list)
    for node in nodes.values():
        for dependency in node.dependencies:
            children[dependency].append(node.node_id)
        if node.parent_id:
            children[node.parent_id].append(node.node_id)
    while queue:
        current = queue.popleft()
        for child in sorted(children.get(current, ())):
            if child not in invalidated:
                invalidated.add(child)
                queue.append(child)
    result: list[WorkItem] = []
    for node in nodes.values():
        if node.node_id in invalidated and node.status not in {
            TaskStatus.ROLLED_BACK.value,
            TaskStatus.INVALIDATED.value,
        }:
            result.append(WorkItem(**{**node.to_dict(), "status": TaskStatus.INVALIDATED.value}))
        else:
            result.append(node)
    return tuple(sorted(result, key=lambda item: item.node_id))


__all__ = [
    "ACTIVE_STATUSES",
    "BlockerKind",
    "ClaimLevel",
    "CONTRACT_ID",
    "CONTRACT_VERSION",
    "DEFAULT_WIP_LIMITS",
    "DependencyError",
    "HierarchyError",
    "LEVEL_PARENT",
    "ReleasePacket",
    "ProjectTaskContractError",
    "TaskBrief",
    "TaskResult",
    "TaskStatus",
    "TERMINAL_STATUSES",
    "ValidationReport",
    "WIPLimitError",
    "WIPPolicy",
    "WIPReport",
    "WorkItem",
    "assert_valid_work_breakdown",
    "build_project_snapshot",
    "build_release_packet",
    "canonical_hash",
    "canonical_json",
    "critical_path",
    "invalidate_downstream",
    "minimum_blocker_set",
    "ready_frontier",
    "validate_task_brief",
    "validate_task_result",
    "validate_wip",
    "validate_work_breakdown",
]
