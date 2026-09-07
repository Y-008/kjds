"""Pure contracts for project-manager task readiness and wave release packets.

This module is deliberately a side-effect-free seam.  It consumes the same
``changed_files``, ``test_receipts``, ``proof_refs``, ``evidence_refs`` and
``rollback_ref`` vocabulary emitted by :mod:`project_manager_cycle`, but it
does not open a database, inspect Git, call a router, or promote authority.

The contract separates four claim levels:

``engineering``
    The change is backed by an exact source/migration identity and tests.
``runtime``
    The engineering claim also has a current runtime receipt and no unresolved
    wave blockers.
``business``
    Runtime evidence is joined by business evidence and an economic impact.
``commercial``
    Business evidence and economic impact are present for a customer-facing
    or revenue-bearing release.  This is still a claim packet; it does not
    grant a Permit or external-write authority.

The validators return structured reports so callers can show every missing
precondition at once.  ``build_release_packet`` is the strict constructor for
callers that need an immutable, hashable packet.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Literal

CLAIM_LEVELS: tuple[str, ...] = (
    "engineering",
    "runtime",
    "business",
    "commercial",
)
type ClaimLevel = Literal["engineering", "runtime", "business", "commercial"]

PROJECT_STATUSES: tuple[str, ...] = (
    "PLANNED",
    "READY",
    "ASSIGNED",
    "IN_PROGRESS",
    "BLOCKED",
    "STALE",
    "INVALIDATED",
    "REVIEW",
    "CONTRACT_VERIFIED",
    "INTEGRATION_VERIFIED",
    "RUNTIME_PROVEN",
    "BUSINESS_EVIDENCE_READY",
    "COMMERCIAL_READY",
    "RELEASED",
    "ROLLED_BACK",
    "RECOVERY",
)
TERMINAL_TASK_STATUSES = frozenset(
    {
        "VERIFIED",
        "INTEGRATED",
        "RELEASED",
        "CONTRACT_VERIFIED",
        "INTEGRATION_VERIFIED",
        "RUNTIME_PROVEN",
        "BUSINESS_EVIDENCE_READY",
        "COMMERCIAL_READY",
    }
)

_HASH = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$|^[0-9a-fA-F]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,255}$")
_RISK_LEVELS = frozenset(
    {
        "R0",
        "R1",
        "R2",
        "R3",
        "R4",
        "L0",
        "L1",
        "L2",
        "L3",
        "L4",
        "LOW",
        "MEDIUM",
        "HIGH",
        "CRITICAL",
    }
)
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "bank_account",
        "card_number",
        "client_secret",
        "cookie",
        "credential",
        "password",
        "private_key",
        "refresh_token",
        "secret",
        "session_token",
    }
)
_AUTHORITY_KEY_PARTS = frozenset(
    {
        "approval",
        "external_write",
        "external_write_allowed",
        "fact",
        "finance_entry",
        "formal_fact",
        "permit",
    }
)


class ReleasePacketError(ValueError):
    """Raised when a strict task or release packet cannot be constructed."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One deterministic validation finding."""

    code: str
    field: str
    message: str
    severity: Literal["error", "warning"] = "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Immutable result returned by all readiness and release validators."""

    valid: bool
    issues: tuple[ValidationIssue, ...] = ()
    normalized: Mapping[str, Any] | None = None

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(item for item in self.issues if item.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(item for item in self.issues if item.severity == "warning")

    def require_valid(self) -> ValidationReport:
        if not self.valid:
            summary = "; ".join(f"{item.field}: {item.message}" for item in self.errors)
            raise ReleasePacketError(summary or "contract validation failed")
        return self

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [item.as_dict() for item in self.issues],
            "normalized": _jsonable(self.normalized) if self.normalized is not None else None,
        }


@dataclass(frozen=True, slots=True)
class TaskBrief:
    """A bounded work package consumed by the Definition-of-Ready check."""

    task_id: str
    parent_id: str
    scope: Mapping[str, Any]
    owner: str
    reviewer: str
    objective: str
    business_context: str
    allowed_scope: tuple[str, ...]
    prohibited_scope: tuple[str, ...]
    dependencies: tuple[str, ...]
    exact_write_set: tuple[str, ...]
    input_snapshot: Any
    exact_files_or_domain: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    acceptance_tests: tuple[str, ...]
    budget: Any
    lease: Any
    deadline: datetime
    risk_tier: str
    rollback_ref: str
    reporting_format: Any
    status: str = "PLANNED"

    def as_dict(self) -> dict[str, Any]:
        result = {item.name: getattr(self, item.name) for item in fields(self)}
        return _jsonable(result)


@dataclass(frozen=True, slots=True)
class TaskResult:
    """Canonical terminal payload used by Definition-of-Done checks."""

    task_id: str
    status: str
    changed_files: tuple[str, ...]
    schema_changes: tuple[str, ...]
    api_changes: tuple[str, ...]
    test_receipts: tuple[str, ...]
    proof_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    blockers: tuple[Any, ...]
    invalidated_nodes: tuple[str, ...]
    economic_impact: Any
    rollback_ref: str | None
    next_dependencies: tuple[str, ...]
    exact_head: str | None = None
    migration_head: str | None = None
    claim_level: ClaimLevel = "engineering"

    def as_dict(self) -> dict[str, Any]:
        return _jsonable({item.name: getattr(self, item.name) for item in fields(self)})


@dataclass(frozen=True, slots=True)
class ReleasePacket:
    """Immutable, secret-free release evidence for one project wave."""

    wave_id: str
    goal: str
    included_tasks: tuple[str, ...]
    excluded_tasks: tuple[str, ...]
    dependency_frontier: tuple[str, ...]
    claim_level: ClaimLevel
    exact_head: str
    migration_head: str
    changed_paths: tuple[str, ...]
    api_schema_diff: Any
    test_receipts: tuple[str, ...]
    runtime_receipt: Any | None
    business_evidence: Any | None
    economic_impact: Any | None
    open_blockers: tuple[Any, ...]
    invalidated_nodes: tuple[str, ...]
    rollback_ref: str
    next_wave: tuple[str, ...]
    packet_sha256: str
    commercial_evidence: Any | None = None
    scope: Mapping[str, Any] | None = None
    snapshot_id: str | None = None
    graph_revision: str | None = None

    def payload(self) -> dict[str, Any]:
        """Return the canonical payload excluding the computed packet digest."""

        result = {item.name: getattr(self, item.name) for item in fields(self) if item.name != "packet_sha256"}
        return _jsonable(result)

    def as_dict(self) -> dict[str, Any]:
        result = self.payload()
        result["packet_sha256"] = self.packet_sha256
        return result

    def replace(self, **changes: Any) -> ReleasePacket:
        """Return a re-hashed packet; useful for immutable revision tests."""

        changed = replace(self, **changes)
        return _rehash_packet(changed)


_TASK_BRIEF_ALIASES = {
    "taskId": "task_id",
    "parentId": "parent_id",
    "businessContext": "business_context",
    "allowedScope": "allowed_scope",
    "prohibitedScope": "prohibited_scope",
    "exactWriteSet": "exact_write_set",
    "inputSnapshot": "input_snapshot",
    "exactFilesOrDomain": "exact_files_or_domain",
    "expectedOutputs": "expected_outputs",
    "acceptanceTests": "acceptance_tests",
    "riskTier": "risk_tier",
    "rollbackRef": "rollback_ref",
    "reportingFormat": "reporting_format",
}
_PACKET_ALIASES = {
    "waveId": "wave_id",
    "includedTasks": "included_tasks",
    "excludedTasks": "excluded_tasks",
    "dependencyFrontier": "dependency_frontier",
    "claimLevel": "claim_level",
    "exactHead": "exact_head",
    "migrationHead": "migration_head",
    "changedPaths": "changed_paths",
    "apiSchemaDiff": "api_schema_diff",
    "testReceipts": "test_receipts",
    "runtimeReceipt": "runtime_receipt",
    "businessEvidence": "business_evidence",
    "commercialEvidence": "commercial_evidence",
    "economicImpact": "economic_impact",
    "openBlockers": "open_blockers",
    "invalidatedNodes": "invalidated_nodes",
    "rollbackRef": "rollback_ref",
    "nextWave": "next_wave",
    "packetSha256": "packet_sha256",
    "snapshotId": "snapshot_id",
    "graphRevision": "graph_revision",
}


def _jsonable(value: Any) -> Any:
    """Convert values into deterministic JSON-safe data without mutation."""

    if isinstance(value, datetime):
        timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ReleasePacketError("non-finite Decimal is not allowed")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReleasePacketError("non-finite number is not allowed")
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(item) for item in value), key=lambda item: repr(item))
    if value is None or isinstance(value, (str, int, bool)):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump(mode="json"))
    raise ReleasePacketError(f"value of type {type(value).__name__} is not canonical JSON")


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReleasePacketError("value is not canonical JSON") from exc


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return dumped
    raise ReleasePacketError(f"{field} must be an object")


def _alias_mapping(value: Any, aliases: Mapping[str, str], field: str) -> dict[str, Any]:
    source = _mapping(value, field)
    normalized: dict[str, Any] = {}
    for key, item in source.items():
        name = aliases.get(str(key), str(key))
        if name in normalized and normalized[name] != item:
            raise ReleasePacketError(f"{field} contains duplicate aliases for {name}")
        normalized[name] = item
    return normalized


def _text(value: Any, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str):
        raise ReleasePacketError(f"{field} must be text")
    result = value.strip()
    if not result:
        raise ReleasePacketError(f"{field} cannot be blank")
    if len(result) > maximum:
        raise ReleasePacketError(f"{field} exceeds {maximum} characters")
    return result


def _optional_text(value: Any, field: str, *, maximum: int = 512) -> str | None:
    if value is None:
        return None
    return _text(value, field, maximum=maximum)


def _list(value: Any, field: str, *, allow_objects: bool = False) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ReleasePacketError(f"{field} must be an array")
    if len(value) > 500:
        raise ReleasePacketError(f"{field} exceeds 500 items")
    result: list[Any] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            normalized = item.strip()
            if not normalized:
                raise ReleasePacketError(f"{field}[{index}] cannot be blank")
            if len(normalized) > 2000:
                raise ReleasePacketError(f"{field}[{index}] is too long")
            result.append(normalized)
        elif allow_objects and isinstance(item, Mapping):
            result.append(_jsonable(item))
        else:
            raise ReleasePacketError(f"{field}[{index}] must be text")
    if all(isinstance(item, str) for item in result) and len(result) != len(set(result)):
        raise ReleasePacketError(f"{field} values must be unique")
    return tuple(result)


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Mapping, Sequence, set, frozenset)) and not isinstance(value, (str, bytes, bytearray)):
        return bool(value)
    return True


def _canonical_level(value: Any) -> ClaimLevel:
    if not isinstance(value, str):
        raise ReleasePacketError("claim_level must be text")
    normalized = value.strip().lower().replace("-", "_")
    aliases = {
        "engineering": "engineering",
        "engineer": "engineering",
        "runtime": "runtime",
        "business": "business",
        "commercial": "commercial",
    }
    try:
        return aliases[normalized]  # type: ignore[return-value]
    except KeyError as exc:
        raise ReleasePacketError(f"claim_level must be one of {', '.join(CLAIM_LEVELS)}") from exc


def claim_level_rank(value: str) -> int:
    """Return the monotonic rank of a claim level (engineering is zero)."""

    level = _canonical_level(value)
    return CLAIM_LEVELS.index(level)


def _check_secret_free(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).strip().lower().replace("-", "_")
            if key_text in _AUTHORITY_KEY_PARTS or any(
                marker in key_text for marker in _AUTHORITY_KEY_PARTS
            ):
                raise ReleasePacketError(f"{path}.{key} contains an authority field")
            if key_text in _SENSITIVE_KEY_PARTS or any(
                token in key_text for token in ("access_token", "api_key", "secret", "password")
            ):
                raise ReleasePacketError(f"{path}.{key} contains a sensitive field")
            _check_secret_free(child, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, child in enumerate(value):
            _check_secret_free(child, f"{path}[{index}]")


def _issue(issues: list[ValidationIssue], code: str, field: str, message: str) -> None:
    issues.append(ValidationIssue(code=code, field=field, message=message))


def _report(issues: list[ValidationIssue], normalized: Mapping[str, Any] | None = None) -> ValidationReport:
    safe = MappingProxyType(dict(normalized)) if normalized is not None else None
    return ValidationReport(
        valid=not any(item.severity == "error" for item in issues), issues=tuple(issues), normalized=safe
    )


def normalize_task_brief(value: TaskBrief | Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a task brief without changing its source object."""

    if isinstance(value, TaskBrief):
        result = value.as_dict()
    else:
        result = _alias_mapping(value, _TASK_BRIEF_ALIASES, "task_brief")
    _check_secret_free(result)
    return _jsonable(result)


def validate_definition_of_ready(value: TaskBrief | Mapping[str, Any]) -> ValidationReport:
    """Validate that a task has enough information to be assigned safely."""

    issues: list[ValidationIssue] = []
    try:
        data = normalize_task_brief(value)
    except (ReleasePacketError, TypeError, ValueError) as exc:
        return _report([ValidationIssue("malformed", "$", str(exc))])

    required = (
        "task_id",
        "parent_id",
        "scope",
        "owner",
        "reviewer",
        "objective",
        "business_context",
        "allowed_scope",
        "prohibited_scope",
        "dependencies",
        "exact_write_set",
        "input_snapshot",
        "exact_files_or_domain",
        "expected_outputs",
        "acceptance_tests",
        "budget",
        "lease",
        "deadline",
        "risk_tier",
        "rollback_ref",
        "reporting_format",
    )
    collection_fields = {
        "allowed_scope",
        "prohibited_scope",
        "dependencies",
        "exact_write_set",
        "exact_files_or_domain",
        "expected_outputs",
        "acceptance_tests",
    }
    for field in required:
        missing = field not in data or data[field] is None
        if field not in collection_fields and field in data and not _present(data[field]):
            missing = True
        if missing:
            _issue(issues, "required", field, "field is required for Definition of Ready")

    for field in (
        "task_id",
        "parent_id",
        "owner",
        "reviewer",
        "objective",
        "business_context",
        "rollback_ref",
    ):
        if field in data and _present(data[field]):
            try:
                _text(data[field], field)
            except ReleasePacketError as exc:
                _issue(issues, "invalid_text", field, str(exc))

    for field in (
        "allowed_scope",
        "prohibited_scope",
        "dependencies",
        "exact_write_set",
        "exact_files_or_domain",
        "expected_outputs",
        "acceptance_tests",
    ):
        if field not in data:
            continue
        try:
            items = _list(data[field], field)
            if field in {"exact_write_set", "exact_files_or_domain", "acceptance_tests"} and not items:
                _issue(issues, "empty", field, "must contain at least one item")
            if field == "dependencies" and data.get("task_id") in items:
                _issue(issues, "self_dependency", field, "task cannot depend on itself")
            if field == "exact_write_set":
                for path in items:
                    if (
                        path in {"*", "**"}
                        or path.startswith(("/", "\\"))
                        or ".." in path.replace("\\", "/").split("/")
                    ):
                        _issue(issues, "broad_write_set", field, f"write target is not exact: {path}")
        except ReleasePacketError as exc:
            _issue(issues, "invalid_array", field, str(exc))

    scope = data.get("scope")
    if not isinstance(scope, Mapping) or not scope:
        _issue(issues, "invalid_scope", "scope", "scope must be a non-empty object")

    risk = data.get("risk_tier")
    if isinstance(risk, str) and risk.strip().upper() not in _RISK_LEVELS:
        _issue(issues, "invalid_risk_tier", "risk_tier", "risk_tier is not recognized")

    deadline = data.get("deadline")
    if deadline is not None and _present(deadline):
        try:
            parsed = deadline if isinstance(deadline, datetime) else datetime.fromisoformat(str(deadline))
            if parsed.tzinfo is None:
                _issue(issues, "timezone_required", "deadline", "deadline must include a timezone")
        except (TypeError, ValueError):
            _issue(issues, "invalid_deadline", "deadline", "deadline must be ISO-8601")

    budget = data.get("budget")
    if isinstance(budget, Mapping):
        for key in ("limit", "amount", "reserved", "max"):
            if key in budget:
                try:
                    amount = Decimal(str(budget[key]))
                    if not amount.is_finite() or amount < 0:
                        _issue(issues, "invalid_budget", "budget", "budget values must be finite and non-negative")
                except Exception:
                    _issue(issues, "invalid_budget", "budget", "budget values must be numeric")
    elif isinstance(budget, (int, float, Decimal)):
        try:
            amount = Decimal(str(budget))
            if not amount.is_finite() or amount < 0:
                _issue(issues, "invalid_budget", "budget", "budget must be finite and non-negative")
        except Exception:
            _issue(issues, "invalid_budget", "budget", "budget must be numeric")

    return _report(issues, data)


def is_definition_of_ready(value: TaskBrief | Mapping[str, Any]) -> bool:
    return validate_definition_of_ready(value).valid


def _normalize_task_result(value: TaskResult | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, TaskResult):
        result = value.as_dict()
    else:
        source = _mapping(value, "task_result")
        nested = source.get("task_result")
        result = dict(_mapping(nested, "task_result")) if nested is not None else dict(source)
    aliases = {
        "taskId": "task_id",
        "testReceipts": "test_receipts",
        "proofRefs": "proof_refs",
        "evidenceRefs": "evidence_refs",
        "changedFiles": "changed_files",
        "schemaChanges": "schema_changes",
        "apiChanges": "api_changes",
        "invalidatedNodes": "invalidated_nodes",
        "economicImpact": "economic_impact",
        "rollbackRef": "rollback_ref",
        "nextDependencies": "next_dependencies",
        "exactHead": "exact_head",
        "migrationHead": "migration_head",
        "claimLevel": "claim_level",
    }
    result = {aliases.get(str(key), str(key)): item for key, item in result.items()}
    _check_secret_free(result)
    return _jsonable(result)


def validate_definition_of_done(
    value: TaskResult | Mapping[str, Any],
    *,
    requires_proof: bool = False,
    claim_level: str | None = None,
) -> ValidationReport:
    """Validate terminal evidence without granting release authority."""

    issues: list[ValidationIssue] = []
    try:
        data = _normalize_task_result(value)
    except (ReleasePacketError, TypeError, ValueError) as exc:
        return _report([ValidationIssue("malformed", "$", str(exc))])

    for field in ("task_id", "status", "changed_files", "test_receipts", "evidence_refs", "rollback_ref"):
        if field not in data or not _present(data[field]):
            _issue(issues, "required", field, "field is required for Definition of Done")

    task_id = data.get("task_id")
    if task_id is not None:
        try:
            _text(task_id, "task_id")
        except ReleasePacketError as exc:
            _issue(issues, "invalid_text", "task_id", str(exc))

    status = str(data.get("status", "")).strip().upper()
    if status and status not in TERMINAL_TASK_STATUSES:
        _issue(issues, "non_terminal_status", "status", "status is not a terminal verified state")

    for field in (
        "changed_files",
        "schema_changes",
        "api_changes",
        "test_receipts",
        "proof_refs",
        "evidence_refs",
        "invalidated_nodes",
        "next_dependencies",
    ):
        if field not in data:
            if field in {"schema_changes", "api_changes", "proof_refs", "invalidated_nodes", "next_dependencies"}:
                data[field] = []
            continue
        try:
            _list(data[field], field)
        except ReleasePacketError as exc:
            _issue(issues, "invalid_array", field, str(exc))

    if requires_proof and not _present(data.get("proof_refs")):
        _issue(issues, "proof_required", "proof_refs", "proof_refs are required for this task")
    if _present(data.get("blockers")):
        _issue(issues, "open_blockers", "blockers", "a completed task cannot retain blockers")
    if _present(data.get("invalidated_nodes")):
        _issue(issues, "invalidations", "invalidated_nodes", "a completed task cannot retain invalidated nodes")
    if _present(data.get("next_dependencies")):
        _issue(
            issues, "next_dependencies", "next_dependencies", "next dependencies must be empty at terminal completion"
        )

    effective_level = claim_level or data.get("claim_level") or "engineering"
    try:
        level = _canonical_level(effective_level)
    except ReleasePacketError as exc:
        _issue(issues, "invalid_claim_level", "claim_level", str(exc))
        level = "engineering"
    if level in {"business", "commercial"} and not _present(data.get("economic_impact")):
        _issue(issues, "economic_impact_required", "economic_impact", f"{level} completion requires economic impact")

    head = data.get("exact_head") or data.get("head")
    if not _present(head):
        _issue(issues, "head_required", "exact_head", "terminal evidence must bind to an exact source head")
    migration = data.get("migration_head")
    if not _present(migration):
        _issue(issues, "migration_required", "migration_head", "terminal evidence must bind to a migration head")
    if data.get("runtime_receipt") is not None and isinstance(data["runtime_receipt"], Mapping):
        receipt_head = data["runtime_receipt"].get("exact_head") or data["runtime_receipt"].get("head")
        if receipt_head and head and str(receipt_head) != str(head):
            _issue(issues, "receipt_head_mismatch", "runtime_receipt", "runtime receipt head does not match task head")

    return _report(issues, data)


def is_definition_of_done(
    value: TaskResult | Mapping[str, Any],
    *,
    requires_proof: bool = False,
    claim_level: str | None = None,
) -> bool:
    return validate_definition_of_done(value, requires_proof=requires_proof, claim_level=claim_level).valid


def _packet_data(value: ReleasePacket | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, ReleasePacket):
        data = value.as_dict()
    else:
        data = _alias_mapping(value, _PACKET_ALIASES, "release_packet")
    _check_secret_free(data)
    return _jsonable(data)


def validate_release_packet(value: ReleasePacket | Mapping[str, Any]) -> ValidationReport:
    """Validate a wave packet and its monotonic claim level."""

    issues: list[ValidationIssue] = []
    try:
        data = _packet_data(value)
    except (ReleasePacketError, TypeError, ValueError) as exc:
        return _report([ValidationIssue("malformed", "$", str(exc))])

    supplied_fields = set(data)
    required = (
        "wave_id",
        "goal",
        "included_tasks",
        "excluded_tasks",
        "dependency_frontier",
        "claim_level",
        "exact_head",
        "migration_head",
        "changed_paths",
        "api_schema_diff",
        "test_receipts",
        "runtime_receipt",
        "business_evidence",
        "economic_impact",
        "open_blockers",
        "invalidated_nodes",
        "rollback_ref",
        "next_wave",
    )
    for field in required:
        # Runtime/business fields are conditionally required; retain them as
        # explicit nulls in the normalized shape for deterministic replay.
        if field not in data:
            data[field] = (
                None
                if field in {"runtime_receipt", "business_evidence", "economic_impact"}
                else ([] if field.endswith("s") or field in {"changed_paths", "next_wave"} else "")
            )
    conditional_fields = {"runtime_receipt", "business_evidence", "economic_impact"}
    for field in required:
        if field not in supplied_fields and field not in conditional_fields and field != "api_schema_diff":
            _issue(issues, "required", field, "field is required for a release packet")

    for field in ("wave_id", "goal", "exact_head", "migration_head", "rollback_ref"):
        try:
            _text(data[field], field)
        except ReleasePacketError as exc:
            _issue(issues, "required" if field not in supplied_fields else "invalid_text", field, str(exc))

    try:
        level = _canonical_level(data.get("claim_level"))
    except ReleasePacketError as exc:
        _issue(issues, "invalid_claim_level", "claim_level", str(exc))
        level = "engineering"

    for field in (
        "included_tasks",
        "excluded_tasks",
        "dependency_frontier",
        "changed_paths",
        "test_receipts",
        "open_blockers",
        "invalidated_nodes",
        "next_wave",
    ):
        try:
            items = _list(data[field], field, allow_objects=(field == "open_blockers"))
            data[field] = items
            if field == "included_tasks" and not items:
                _issue(issues, "empty", field, "at least one included task is required")
            if field == "changed_paths":
                for path in items:
                    normalized_path = path.replace("\\", "/")
                    if (
                        normalized_path.startswith("/")
                        or normalized_path.startswith("../")
                        or "/../" in normalized_path
                    ):
                        _issue(issues, "unsafe_path", field, f"changed path is not repository-relative: {path}")
        except ReleasePacketError as exc:
            _issue(issues, "invalid_array", field, str(exc))

    if not data.get("test_receipts"):
        _issue(issues, "tests_required", "test_receipts", "at least one test receipt is required")
    if "api_schema_diff" not in supplied_fields:
        _issue(
            issues,
            "schema_diff_required",
            "api_schema_diff",
            "api/schema diff must be recorded, including an explicit empty object",
        )
    else:
        try:
            data["api_schema_diff"] = _jsonable(data["api_schema_diff"])
        except ReleasePacketError as exc:
            _issue(issues, "invalid_schema_diff", "api_schema_diff", str(exc))

    level_rank = claim_level_rank(level)
    if level_rank >= claim_level_rank("runtime"):
        if not _present(data.get("runtime_receipt")):
            _issue(
                issues, "runtime_receipt_required", "runtime_receipt", "runtime claim requires a runtime receipt"
            )
        if data.get("dependency_frontier"):
            _issue(
                issues,
                "unresolved_dependencies",
                "dependency_frontier",
                "runtime claim cannot retain unresolved dependencies",
            )
        if data.get("open_blockers"):
            _issue(issues, "open_blockers", "open_blockers", "runtime claim cannot retain open blockers")
        if data.get("invalidated_nodes"):
            _issue(issues, "invalidations", "invalidated_nodes", "runtime claim cannot retain invalidated nodes")
    if level_rank >= claim_level_rank("business"):
        if not _present(data.get("business_evidence")):
            _issue(
                issues,
                "business_evidence_required",
                "business_evidence",
                "business claim requires business evidence",
            )
        if not _present(data.get("economic_impact")):
            _issue(issues, "economic_impact_required", "economic_impact", "business claim requires economic impact")
    if level_rank >= claim_level_rank("commercial") and not _present(data.get("commercial_evidence")):
        _issue(
            issues,
            "commercial_evidence_required",
            "commercial_evidence",
            "commercial claim requires customer/contract/usage evidence",
        )

    runtime_receipt = data.get("runtime_receipt")
    if isinstance(runtime_receipt, Mapping):
        receipt_head = runtime_receipt.get("exact_head") or runtime_receipt.get("head")
        if receipt_head and str(receipt_head) != str(data.get("exact_head")):
            _issue(issues, "receipt_head_mismatch", "runtime_receipt", "runtime receipt is bound to another exact head")

    supplied_digest = data.get("packet_sha256")
    digest_payload = {key: value for key, value in data.items() if key != "packet_sha256"}
    try:
        calculated = sha256_json(digest_payload)
        if supplied_digest is not None and str(supplied_digest).lower() != calculated:
            _issue(issues, "packet_hash_mismatch", "packet_sha256", "packet digest does not match canonical payload")
    except ReleasePacketError as exc:
        _issue(issues, "packet_not_hashable", "$", str(exc))
        calculated = ""
    data["packet_sha256"] = calculated
    return _report(issues, data)


def _rehash_packet(packet: ReleasePacket) -> ReleasePacket:
    digest = sha256_json(packet.payload())
    return replace(packet, packet_sha256=digest)


def build_release_packet(value: ReleasePacket | Mapping[str, Any]) -> ReleasePacket:
    """Construct an immutable packet only after full validation."""

    report = validate_release_packet(value)
    report.require_valid()
    data = dict(report.normalized or {})
    level = _canonical_level(data["claim_level"])
    packet = ReleasePacket(
        wave_id=_text(data["wave_id"], "wave_id"),
        goal=_text(data["goal"], "goal"),
        included_tasks=tuple(data["included_tasks"]),
        excluded_tasks=tuple(data["excluded_tasks"]),
        dependency_frontier=tuple(data["dependency_frontier"]),
        claim_level=level,
        exact_head=_text(data["exact_head"], "exact_head"),
        migration_head=_text(data["migration_head"], "migration_head"),
        changed_paths=tuple(data["changed_paths"]),
        api_schema_diff=data["api_schema_diff"],
        test_receipts=tuple(data["test_receipts"]),
        runtime_receipt=data.get("runtime_receipt"),
        business_evidence=data.get("business_evidence"),
        economic_impact=data.get("economic_impact"),
        open_blockers=tuple(data["open_blockers"] or ()),
        invalidated_nodes=tuple(data["invalidated_nodes"]),
        rollback_ref=_text(data["rollback_ref"], "rollback_ref"),
        next_wave=tuple(data["next_wave"]),
        packet_sha256="",
        commercial_evidence=data.get("commercial_evidence"),
        scope=data.get("scope"),
        snapshot_id=data.get("snapshot_id"),
        graph_revision=data.get("graph_revision"),
    )
    return _rehash_packet(packet)


def derive_claim_level(value: ReleasePacket | Mapping[str, Any]) -> ClaimLevel | None:
    """Return the highest claim level currently supported by a packet."""

    data = _packet_data(value)
    requested = data.get("claim_level", "commercial")
    try:
        rank = claim_level_rank(str(requested))
    except ReleasePacketError:
        return None
    # Try from the requested level downward, preserving the caller's evidence
    # rather than manufacturing fields.  This is useful for PM dashboards that
    # need to explain why a wave fell back from business to runtime evidence.
    for candidate in reversed(CLAIM_LEVELS[: rank + 1]):
        candidate_data = dict(data)
        candidate_data["claim_level"] = candidate
        candidate_data.pop("packet_sha256", None)
        if validate_release_packet(candidate_data).valid:
            return candidate  # type: ignore[return-value]
    return None


def summarize_delivery_lanes(
    packets: Sequence[ReleasePacket | Mapping[str, Any]],
) -> dict[str, Any]:
    """Produce a read-only four-lane progress projection for a PM dashboard."""

    counts = {level: 0 for level in CLAIM_LEVELS}
    valid_packets = 0
    invalid_packets = 0
    blockers: list[str] = []
    for packet in packets:
        report = validate_release_packet(packet)
        if not report.valid:
            invalid_packets += 1
            blockers.extend(f"{item.field}:{item.code}" for item in report.errors)
            continue
        valid_packets += 1
        level = str(report.normalized.get("claim_level")) if report.normalized else "engineering"
        for candidate in CLAIM_LEVELS:
            if claim_level_rank(level) >= claim_level_rank(candidate):
                counts[candidate] += 1
    total = valid_packets + invalid_packets
    return {
        "engineering": {"packets": counts["engineering"], "ready": counts["engineering"] > 0},
        "runtime": {"packets": counts["runtime"], "ready": counts["runtime"] > 0},
        "business": {"packets": counts["business"], "ready": counts["business"] > 0},
        "commercial": {"packets": counts["commercial"], "ready": counts["commercial"] > 0},
        "valid_packets": valid_packets,
        "invalid_packets": invalid_packets,
        "total_packets": total,
        "blockers": tuple(sorted(set(blockers))),
    }


# Short aliases keep the contract ergonomic for PM adapters while the verbose
# names remain the canonical public API used in documentation and tests.
validate_dor = validate_definition_of_ready
validate_dod = validate_definition_of_done
definition_of_ready = is_definition_of_ready
definition_of_done = is_definition_of_done
WaveReleasePacket = ReleasePacket


__all__ = [
    "CLAIM_LEVELS",
    "ClaimLevel",
    "PROJECT_STATUSES",
    "TERMINAL_TASK_STATUSES",
    "ReleasePacketError",
    "ValidationIssue",
    "ValidationReport",
    "TaskBrief",
    "TaskResult",
    "ReleasePacket",
    "WaveReleasePacket",
    "canonical_json",
    "sha256_json",
    "claim_level_rank",
    "normalize_task_brief",
    "validate_definition_of_ready",
    "is_definition_of_ready",
    "validate_dor",
    "definition_of_ready",
    "validate_definition_of_done",
    "is_definition_of_done",
    "validate_dod",
    "definition_of_done",
    "validate_release_packet",
    "build_release_packet",
    "derive_claim_level",
    "summarize_delivery_lanes",
]
