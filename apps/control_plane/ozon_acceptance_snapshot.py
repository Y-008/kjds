"""Immutable, local-only binding for an Ozon acceptance snapshot.

The Ozon production acceptance service answers whether one read-only run is
admissible.  This module answers a different question: *which exact local
inputs were observed together?*  A snapshot binds the checkout identity,
API/schema/migration identity, browser evidence bytes and raw evidence hash,
graph and observe receipts, and a secret-free managed-lease projection.

There are deliberately no router, database, browser, credential, or network
imports here.  ``read_artifact_binding`` reads only the path explicitly given
by its caller.  The resulting :class:`AcceptanceSnapshot` is a read-only
mapping whose nested values are also immutable.  ``validate_snapshot``
recomputes the local file hash and reports drift without returning any current
raw values.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

CONTRACT_ID = "kjds-ozon-acceptance-snapshot-binding-v1"
CONTRACT_VERSION = "1.0.0"
VALIDATION_CONTRACT_ID = "kjds-ozon-acceptance-snapshot-validation-v1"

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_HEAD = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
_MAX_TEXT = 1024
_MAX_AGE_SECONDS = 31_536_000  # one year; a caller may choose a smaller bound

# A lease projection is intentionally an allow-list.  These fields describe
# state or opaque digests, never credential material or a usable authorization.
_SAFE_LEASE_KEYS = frozenset(
    {
        "contract_id",
        "issuer",
        "key_id",
        "state",
        "status",
        "lease_status",
        "runtime_status",
        "managed_runtime_mode",
        "platform",
        "adapter_id",
        "adapter_version",
        "required_capability",
        "managed_store_bound",
        "lease_fresh",
        "scope_match",
        "capabilities_match",
        "provider_readback_fresh_passed",
        "external_verifier_fresh_passed",
        "read_only",
        "credential_material_returned",
        "issued_at",
        "created_at",
        "checked_at",
        "expires_at",
        "revoked_at",
        "renewed_at",
        "lease_id_sha256",
        "envelope_sha256",
        "grant_id_sha256",
        "account_ref_sha256",
        "store_ref_sha256",
        "scope_sha256",
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
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
        r"\s*[:=]\s*[^\s,;]{6,}"
    ),
)
_BOOL_KEYS = frozenset(
    {
        "managed_store_bound",
        "lease_fresh",
        "scope_match",
        "capabilities_match",
        "provider_readback_fresh_passed",
        "external_verifier_fresh_passed",
        "read_only",
    }
)
_TIME_KEYS = frozenset({"issued_at", "created_at", "checked_at", "expires_at", "revoked_at", "renewed_at"})


class OzonAcceptanceSnapshotError(ValueError):
    """Raised when a snapshot input cannot be safely bound."""


def _jsonable(value: Any, *, field: str = "value") -> Any:
    """Return deterministic JSON-safe data, rejecting ambiguous values."""

    if isinstance(value, datetime):
        return _timestamp(value, field).isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise OzonAcceptanceSnapshotError(f"{field} contains a non-finite number")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise OzonAcceptanceSnapshotError(f"{field} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item, field=f"{field}.{key}")
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item, field=f"{field}[]") for item in value]
    if isinstance(value, (set, frozenset)):
        items = [_jsonable(item, field=f"{field}[]") for item in value]
        return sorted(items, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    if value is None or isinstance(value, (str, int, bool)):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return _jsonable(dumped, field=field)
    raise OzonAcceptanceSnapshotError(f"{field} is not canonical JSON")


def canonical_json(value: Any) -> bytes:
    """Serialize a value using the snapshot's canonical JSON rules."""

    try:
        return json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise OzonAcceptanceSnapshotError("value is not canonical JSON") from exc


def sha256_json(value: Any) -> str:
    """Hash canonical JSON without exposing the source value."""

    return hashlib.sha256(canonical_json(value)).hexdigest()


def _text(value: Any, field: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise OzonAcceptanceSnapshotError(f"{field} must be text")
    normalized = value.strip()
    if not normalized:
        raise OzonAcceptanceSnapshotError(f"{field} is required")
    if len(normalized) > maximum:
        raise OzonAcceptanceSnapshotError(f"{field} exceeds {maximum} characters")
    return normalized


def _sha(value: Any, field: str) -> str:
    normalized = _text(value, field, maximum=64).lower()
    if not _SHA256.fullmatch(normalized):
        raise OzonAcceptanceSnapshotError(f"{field} must be a SHA-256 digest")
    return normalized


def _head(value: Any, field: str = "canonical_head") -> str:
    normalized = _text(value, field, maximum=64).lower()
    if not _HEAD.fullmatch(normalized):
        raise OzonAcceptanceSnapshotError(f"{field} must be a 40- or 64-character commit digest")
    return normalized


def _timestamp(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise OzonAcceptanceSnapshotError(f"{field} must be ISO-8601") from exc
    else:
        raise OzonAcceptanceSnapshotError(f"{field} must be a timezone-aware datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OzonAcceptanceSnapshotError(f"{field} requires a timezone")
    return parsed.astimezone(UTC)


def _optional_timestamp(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _timestamp(value, field).isoformat()


def _normalize_path(value: str | Path, field: str = "browser_artifact_path") -> str:
    if isinstance(value, Path):
        path = value
    elif isinstance(value, str):
        if not value.strip():
            raise OzonAcceptanceSnapshotError(f"{field} is required")
        path = Path(value.strip())
    else:
        raise OzonAcceptanceSnapshotError(f"{field} must be a path")
    # Keep relative paths relative for replay portability, while making
    # separator spelling deterministic across Windows and POSIX callers.
    normalized = path.expanduser().as_posix()
    if not normalized or normalized == ".":
        raise OzonAcceptanceSnapshotError(f"{field} is required")
    if len(normalized) > _MAX_TEXT:
        raise OzonAcceptanceSnapshotError(f"{field} exceeds {_MAX_TEXT} characters")
    return normalized


def _file_sha256(path: str | Path) -> str:
    candidate = Path(path)
    try:
        if not candidate.is_file():
            raise OzonAcceptanceSnapshotError("browser artifact path is not a regular file")
        digest = hashlib.sha256()
        with candidate.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OzonAcceptanceSnapshotError:
        raise
    except (OSError, ValueError) as exc:
        raise OzonAcceptanceSnapshotError("browser artifact file cannot be read") from exc


def _contains_sensitive_key(key: Any) -> bool:
    token = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    if token in {
        "credential_material_returned",
        "credential_values_returned",
        "lease_id_sha256",
        "grant_id_sha256",
    }:
        return False
    return any(part in token for part in _SENSITIVE_KEY_PARTS)


def _contains_sensitive_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return any(pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS)


def _scan_for_sensitive(value: Any, path: str = "$") -> None:
    """Reject unsafe input without putting its value in an exception."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            if _contains_sensitive_key(key):
                raise OzonAcceptanceSnapshotError(f"{path}.{key} contains a sensitive field")
            _scan_for_sensitive(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _scan_for_sensitive(item, f"{path}[{index}]")
    elif _contains_sensitive_value(value):
        raise OzonAcceptanceSnapshotError(f"{path} contains a credential-like value")


def _bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise OzonAcceptanceSnapshotError(f"{field} must be boolean")


def sanitize_lease_projection(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return only allow-listed, non-sensitive lease state.

    Unknown non-sensitive fields are intentionally dropped so callers cannot
    smuggle an authorization or credential into an acceptance artifact.  A
    raw ``credential_material_returned`` value of true is always rejected.
    """

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise OzonAcceptanceSnapshotError("lease_projection must be an object")
    _scan_for_sensitive(value)
    result: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip().lower().replace("-", "_")
        if key not in _SAFE_LEASE_KEYS:
            # ``lease_id``/``secret_reference`` and similar names are unsafe
            # even though they are not retained; fail closed rather than hide
            # a caller error.
            if _contains_sensitive_key(key) or key in {"lease_id", "grant_id", "secret_reference", "credential_fingerprint"}:
                raise OzonAcceptanceSnapshotError(f"lease_projection.{raw_key} is not safe")
            continue
        if key == "credential_material_returned":
            normalized = _bool(raw_value, key)
            if normalized:
                raise OzonAcceptanceSnapshotError("lease projection returned credential material")
            result[key] = False
        elif key in _BOOL_KEYS:
            result[key] = _bool(raw_value, key)
        elif key.endswith("_sha256"):
            result[key] = _sha(raw_value, f"lease_projection.{key}")
        elif key in _TIME_KEYS:
            result[key] = _timestamp(raw_value, f"lease_projection.{key}").isoformat()
        else:
            result[key] = _text(raw_value, f"lease_projection.{key}")
    return {key: result[key] for key in sorted(result)}


def read_artifact_binding(
    path: str | Path,
    *,
    raw_sha256: str | None = None,
    browser_raw_sha256: str | None = None,
    observed_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Hash one explicitly supplied local browser artifact.

    ``raw_sha256`` is supplied by the evidence producer and is never inferred
    from or copied out of the artifact.  This keeps the helper independent of
    browser formats and prevents accidental inclusion of visible text.
    """

    normalized_path = _normalize_path(path)
    raw_hash = raw_sha256 if raw_sha256 is not None else browser_raw_sha256
    if raw_hash is None:
        raise OzonAcceptanceSnapshotError("browser raw SHA-256 is required")
    file_hash = _file_sha256(path)
    binding: dict[str, Any] = {
        "path": normalized_path,
        "file_sha256": file_hash,
        "raw_sha256": _sha(raw_hash, "browser_raw_sha256"),
        "observed_at": _optional_timestamp(observed_at, "browser_observed_at"),
    }
    return binding


def _coalesce(primary: Any, *aliases: Any) -> Any:
    if primary is not None:
        return primary
    for value in aliases:
        if value is not None:
            return value
    return None


def _metadata_values(
    *,
    api_version: Any,
    schema_sha256: Any,
    migration_head: Any,
    api_schema_migration: Mapping[str, Any] | None,
) -> tuple[str, str, str]:
    grouped = api_schema_migration if isinstance(api_schema_migration, Mapping) else {}
    api = _coalesce(api_version, grouped.get("api_version"), grouped.get("apiVersion"), grouped.get("version"))
    schema = _coalesce(
        schema_sha256,
        grouped.get("schema_sha256"),
        grouped.get("schemaSha256"),
        grouped.get("schema_hash"),
    )
    migration = _coalesce(
        migration_head,
        grouped.get("migration_head"),
        grouped.get("migrationHead"),
    )
    return (
        _text(api, "api_version"),
        _sha(schema, "schema_sha256"),
        _text(migration, "migration_head"),
    )


def _artifact_values(
    *,
    browser_artifact_path: str | Path | None,
    browser_artifact_file_sha256: Any,
    browser_file_sha256: Any,
    browser_raw_sha256: Any,
    raw_sha256: Any,
    browser_observed_at: datetime | str | None,
    browser_artifact: Mapping[str, Any] | None,
    read_file: bool,
) -> dict[str, Any]:
    grouped = browser_artifact if isinstance(browser_artifact, Mapping) else {}
    path = _coalesce(browser_artifact_path, grouped.get("path"), grouped.get("artifact_path"))
    if path is None:
        raise OzonAcceptanceSnapshotError("browser_artifact_path is required")
    raw_hash = _coalesce(
        browser_raw_sha256,
        raw_sha256,
        grouped.get("raw_sha256"),
        grouped.get("raw_hash"),
    )
    if raw_hash is None:
        raise OzonAcceptanceSnapshotError("browser_raw_sha256 is required")
    normalized_path = _normalize_path(path)
    observed = _coalesce(browser_observed_at, grouped.get("observed_at"), grouped.get("browser_observed_at"))
    actual_file_hash = _file_sha256(path) if read_file else _sha(
        _coalesce(browser_artifact_file_sha256, browser_file_sha256, grouped.get("file_sha256"), grouped.get("file_hash")),
        "browser_artifact_file_sha256",
    )
    supplied_file_hash = _coalesce(browser_artifact_file_sha256, browser_file_sha256, grouped.get("file_sha256"), grouped.get("file_hash"))
    if supplied_file_hash is not None and _sha(supplied_file_hash, "browser_artifact_file_sha256") != actual_file_hash:
        raise OzonAcceptanceSnapshotError("browser artifact file hash does not match bytes")
    return {
        "path": normalized_path,
        "file_sha256": actual_file_hash,
        "raw_sha256": _sha(raw_hash, "browser_raw_sha256"),
        "observed_at": _optional_timestamp(observed, "browser_observed_at"),
    }


def _validate_age(max_age_seconds: Any) -> int | None:
    if max_age_seconds is None:
        return None
    if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int):
        raise OzonAcceptanceSnapshotError("max_age_seconds must be an integer")
    if not 0 <= max_age_seconds <= _MAX_AGE_SECONDS:
        raise OzonAcceptanceSnapshotError("max_age_seconds is outside the supported range")
    return max_age_seconds


def _time_order(
    *,
    captured_at: datetime,
    as_of: datetime,
    browser_observed_at: str | None,
) -> None:
    if as_of > captured_at:
        raise OzonAcceptanceSnapshotError("as_of cannot be after captured_at")
    if browser_observed_at is not None and _timestamp(browser_observed_at, "browser_observed_at") > captured_at:
        raise OzonAcceptanceSnapshotError("browser_observed_at cannot be after captured_at")


def _snapshot_basis(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "snapshot_sha256"}


@dataclass(frozen=True, slots=True)
class AcceptanceSnapshot(Mapping[str, Any]):
    """Recursively immutable snapshot mapping.

    The mapping interface keeps the artifact convenient for API serializers;
    ``to_dict`` returns a detached mutable copy and never the internal state.
    """

    _payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self._payload, Mapping):
            raise OzonAcceptanceSnapshotError("snapshot payload must be an object")
        frozen = _freeze(_jsonable(self._payload, field="snapshot"))
        if not isinstance(frozen, Mapping):  # pragma: no cover - guarded above
            raise OzonAcceptanceSnapshotError("snapshot payload must be an object")
        object.__setattr__(self, "_payload", frozen)

    def __getitem__(self, key: str) -> Any:
        return self._payload[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._payload)

    def __len__(self) -> int:
        return len(self._payload)

    def __getattr__(self, name: str) -> Any:
        # Attribute access is useful to Python callers while retaining a
        # single canonical mapping representation.
        payload = object.__getattribute__(self, "_payload")
        try:
            return payload[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @property
    def snapshot_sha256(self) -> str:
        return str(self._payload["snapshot_sha256"])

    def payload(self) -> dict[str, Any]:
        return _thaw(_snapshot_basis(self._payload))

    def as_dict(self) -> dict[str, Any]:
        return _thaw(self._payload)

    def to_dict(self) -> dict[str, Any]:
        return self.as_dict()

    def __repr__(self) -> str:
        return f"AcceptanceSnapshot(snapshot_sha256={self.snapshot_sha256!r})"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _make_snapshot(payload: Mapping[str, Any]) -> AcceptanceSnapshot:
    canonical = _jsonable(payload, field="snapshot")
    if not isinstance(canonical, Mapping):
        raise OzonAcceptanceSnapshotError("snapshot payload must be an object")
    unsigned = _snapshot_basis(canonical)
    complete = dict(unsigned)
    complete["snapshot_sha256"] = sha256_json(unsigned)
    return AcceptanceSnapshot(complete)


def build_snapshot(
    *,
    canonical_head: str | None = None,
    exact_head: str | None = None,
    api_version: str | None = None,
    schema_sha256: str | None = None,
    migration_head: str | None = None,
    api_schema_migration: Mapping[str, Any] | None = None,
    browser_artifact_path: str | Path | None = None,
    browser_artifact_file_sha256: str | None = None,
    browser_file_sha256: str | None = None,
    browser_raw_sha256: str | None = None,
    raw_sha256: str | None = None,
    browser_observed_at: datetime | str | None = None,
    browser_artifact: Mapping[str, Any] | None = None,
    graph_snapshot_sha256: str | None = None,
    graph_snapshot_hash: str | None = None,
    observe_receipt_sha256: str | None = None,
    observe_receipt_hash: str | None = None,
    lease_projection: Mapping[str, Any] | None = None,
    captured_at: datetime | str | None = None,
    as_of: datetime | str | None = None,
    now: datetime | str | None = None,
    max_age_seconds: int | None = None,
) -> AcceptanceSnapshot:
    """Build one deterministic acceptance binding from already observed data."""

    head = _head(_coalesce(canonical_head, exact_head), "canonical_head")
    api, schema, migration = _metadata_values(
        api_version=api_version,
        schema_sha256=schema_sha256,
        migration_head=migration_head,
        api_schema_migration=api_schema_migration,
    )
    artifact = _artifact_values(
        browser_artifact_path=browser_artifact_path,
        browser_artifact_file_sha256=browser_artifact_file_sha256,
        browser_file_sha256=browser_file_sha256,
        browser_raw_sha256=browser_raw_sha256,
        raw_sha256=raw_sha256,
        browser_observed_at=browser_observed_at,
        browser_artifact=browser_artifact,
        read_file=True,
    )
    graph_hash = _sha(_coalesce(graph_snapshot_sha256, graph_snapshot_hash), "graph_snapshot_sha256")
    observe_hash = _sha(_coalesce(observe_receipt_sha256, observe_receipt_hash), "observe_receipt_sha256")
    if captured_at is None:
        raise OzonAcceptanceSnapshotError("captured_at is required")
    captured = _timestamp(captured_at, "captured_at")
    cutoff = captured if as_of is None else _timestamp(as_of, "as_of")
    _time_order(captured_at=captured, as_of=cutoff, browser_observed_at=artifact["observed_at"])
    age_limit = _validate_age(max_age_seconds)
    if now is not None:
        current = _timestamp(now, "now")
        if current < captured:
            raise OzonAcceptanceSnapshotError("now cannot be before captured_at")
        if age_limit is not None and (current - captured).total_seconds() > age_limit:
            raise OzonAcceptanceSnapshotError("snapshot exceeds max_age_seconds")
    lease = sanitize_lease_projection(lease_projection)
    payload = {
        "contract_id": CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "captured_at": captured.isoformat(),
        "as_of": cutoff.isoformat(),
        "canonical_head": head,
        "api_version": api,
        "schema_sha256": schema,
        "migration_head": migration,
        "api_schema_migration": {
            "api_version": api,
            "schema_sha256": schema,
            "migration_head": migration,
        },
        "browser_artifact": artifact,
        "graph_snapshot_sha256": graph_hash,
        "observe_receipt_sha256": observe_hash,
        "lease_projection": lease,
        "external_write_allowed": False,
        "credential_values_returned": False,
        "immutable": True,
    }
    return _make_snapshot(payload)


def _coerce_mapping(snapshot: AcceptanceSnapshot | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(snapshot, AcceptanceSnapshot):
        return snapshot
    if isinstance(snapshot, Mapping):
        return snapshot
    raise OzonAcceptanceSnapshotError("snapshot must be an object")


def _current_values(
    *,
    current: Mapping[str, Any] | None,
    current_head: Any,
    current_canonical_head: Any,
    current_api_version: Any,
    current_schema_sha256: Any,
    current_migration_head: Any,
    current_browser_artifact_path: str | Path | None,
    current_browser_artifact_file_sha256: Any,
    current_browser_file_sha256: Any,
    current_browser_raw_sha256: Any,
    current_raw_sha256: Any,
    current_graph_snapshot_sha256: Any,
    current_graph_snapshot_hash: Any,
    current_observe_receipt_sha256: Any,
    current_observe_receipt_hash: Any,
    current_lease_projection: Mapping[str, Any] | None,
    current_api_schema_migration: Mapping[str, Any] | None,
    current_browser_artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source = current if isinstance(current, Mapping) else {}
    head = _coalesce(current_head, current_canonical_head, source.get("canonical_head"), source.get("exact_head"), source.get("head"))
    api = _coalesce(current_api_version, source.get("api_version"), source.get("apiVersion"))
    schema = _coalesce(current_schema_sha256, source.get("schema_sha256"), source.get("schemaSha256"))
    migration = _coalesce(current_migration_head, source.get("migration_head"), source.get("migrationHead"))
    grouped = current_api_schema_migration or source.get("api_schema_migration")
    api, schema, migration = _metadata_values(
        api_version=api,
        schema_sha256=schema,
        migration_head=migration,
        api_schema_migration=grouped if isinstance(grouped, Mapping) else None,
    )
    artifact_path = _coalesce(
        current_browser_artifact_path,
        source.get("browser_artifact_path"),
        source.get("browser_artifact", {}).get("path") if isinstance(source.get("browser_artifact"), Mapping) else None,
    )
    artifact_raw = _coalesce(
        current_browser_raw_sha256,
        current_raw_sha256,
        source.get("browser_raw_sha256"),
        source.get("browser_artifact", {}).get("raw_sha256") if isinstance(source.get("browser_artifact"), Mapping) else None,
    )
    artifact_file = _coalesce(
        current_browser_artifact_file_sha256,
        current_browser_file_sha256,
        source.get("browser_artifact_file_sha256"),
        source.get("browser_artifact", {}).get("file_sha256") if isinstance(source.get("browser_artifact"), Mapping) else None,
    )
    if artifact_path is None or artifact_raw is None:
        raise OzonAcceptanceSnapshotError("current browser artifact binding is incomplete")
    artifact = _artifact_values(
        browser_artifact_path=artifact_path,
        browser_artifact_file_sha256=artifact_file,
        browser_file_sha256=None,
        browser_raw_sha256=artifact_raw,
        raw_sha256=None,
        browser_observed_at=None,
        browser_artifact=current_browser_artifact if isinstance(current_browser_artifact, Mapping) else None,
        read_file=True,
    )
    graph = _coalesce(
        current_graph_snapshot_sha256,
        current_graph_snapshot_hash,
        source.get("graph_snapshot_sha256"),
        source.get("graph_snapshot_hash"),
    )
    observe = _coalesce(
        current_observe_receipt_sha256,
        current_observe_receipt_hash,
        source.get("observe_receipt_sha256"),
        source.get("observe_receipt_hash"),
    )
    lease = current_lease_projection if current_lease_projection is not None else source.get("lease_projection")
    return {
        "canonical_head": _head(head, "current_canonical_head"),
        "api_version": api,
        "schema_sha256": schema,
        "migration_head": migration,
        "browser_artifact": artifact,
        "graph_snapshot_sha256": _sha(graph, "current_graph_snapshot_sha256"),
        "observe_receipt_sha256": _sha(observe, "current_observe_receipt_sha256"),
        "lease_projection": sanitize_lease_projection(lease),
    }


def _issue(code: str, field: str, *, severity: str = "error") -> dict[str, str]:
    return {"code": code, "field": field, "severity": severity}


def validate_snapshot(
    snapshot: AcceptanceSnapshot | Mapping[str, Any],
    *,
    current: Mapping[str, Any] | None = None,
    current_head: str | None = None,
    current_canonical_head: str | None = None,
    current_api_version: str | None = None,
    current_schema_sha256: str | None = None,
    current_migration_head: str | None = None,
    current_api_schema_migration: Mapping[str, Any] | None = None,
    current_browser_artifact_path: str | Path | None = None,
    current_browser_artifact_file_sha256: str | None = None,
    current_browser_file_sha256: str | None = None,
    current_browser_raw_sha256: str | None = None,
    current_raw_sha256: str | None = None,
    current_browser_artifact: Mapping[str, Any] | None = None,
    current_graph_snapshot_sha256: str | None = None,
    current_graph_snapshot_hash: str | None = None,
    current_observe_receipt_sha256: str | None = None,
    current_observe_receipt_hash: str | None = None,
    current_lease_projection: Mapping[str, Any] | None = None,
    now: datetime | str | None = None,
    as_of: datetime | str | None = None,
    max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Compare a snapshot with current local observations.

    The report contains stable issue codes and hashes only.  It never echoes
    current artifact bytes, raw browser text, or lease values.
    """

    issues: list[dict[str, str]] = []
    hash_checks: dict[str, bool] = {}
    time_checks: dict[str, bool] = {}
    observed_hash: str | None = None
    try:
        source = _coerce_mapping(snapshot)
        canonical = _jsonable(source, field="snapshot")
        if not isinstance(canonical, Mapping):
            raise OzonAcceptanceSnapshotError("snapshot must be an object")
        supplied_hash = canonical.get("snapshot_sha256")
        if not isinstance(supplied_hash, str) or not _SHA256.fullmatch(supplied_hash):
            issues.append(_issue("snapshot_hash_missing", "snapshot_sha256"))
        else:
            observed_hash = supplied_hash.lower()
            expected_hash = sha256_json(_snapshot_basis(canonical))
            hash_checks["snapshot"] = hmac_compare(observed_hash, expected_hash)
            if not hash_checks["snapshot"]:
                issues.append(_issue("snapshot_hash_drift", "snapshot_sha256"))
        if canonical.get("contract_id") != CONTRACT_ID:
            issues.append(_issue("contract_id_invalid", "contract_id"))
        if canonical.get("contract_version") != CONTRACT_VERSION:
            issues.append(_issue("contract_version_invalid", "contract_version"))
        if canonical.get("external_write_allowed") is not False:
            issues.append(_issue("external_write_forbidden", "external_write_allowed"))
        if canonical.get("credential_values_returned") is not False:
            issues.append(_issue("credential_values_present", "credential_values_returned"))
        if canonical.get("immutable") is not True:
            issues.append(_issue("snapshot_not_immutable", "immutable"))
        _scan_for_sensitive(canonical)
        captured = _timestamp(canonical.get("captured_at"), "captured_at")
        stored_as_of = _timestamp(canonical.get("as_of"), "as_of")
        if stored_as_of > captured:
            issues.append(_issue("as_of_after_capture", "as_of"))
        browser = canonical.get("browser_artifact")
        if not isinstance(browser, Mapping):
            raise OzonAcceptanceSnapshotError("browser_artifact is required")
        browser_observed = browser.get("observed_at")
        if browser_observed is not None and _timestamp(browser_observed, "browser_observed_at") > captured:
            issues.append(_issue("browser_observed_after_capture", "browser_artifact.observed_at"))
        stored_lease = sanitize_lease_projection(canonical.get("lease_projection"))
        if stored_lease != canonical.get("lease_projection"):
            issues.append(_issue("lease_projection_invalid", "lease_projection"))
        # Validate stored fixed fields even if no current values are available.
        stored_fields = {
            "canonical_head": _head(canonical.get("canonical_head")),
            "api_version": _text(canonical.get("api_version"), "api_version"),
            "schema_sha256": _sha(canonical.get("schema_sha256"), "schema_sha256"),
            "migration_head": _text(canonical.get("migration_head"), "migration_head"),
            "graph_snapshot_sha256": _sha(canonical.get("graph_snapshot_sha256"), "graph_snapshot_sha256"),
            "observe_receipt_sha256": _sha(canonical.get("observe_receipt_sha256"), "observe_receipt_sha256"),
        }
        grouped = canonical.get("api_schema_migration")
        if not isinstance(grouped, Mapping) or {
            "api_version": grouped.get("api_version"),
            "schema_sha256": grouped.get("schema_sha256"),
            "migration_head": grouped.get("migration_head"),
        } != {
            "api_version": stored_fields["api_version"],
            "schema_sha256": stored_fields["schema_sha256"],
            "migration_head": stored_fields["migration_head"],
        }:
            issues.append(_issue("api_schema_migration_binding_drift", "api_schema_migration"))
        stored_browser = {
            "path": _normalize_path(browser.get("path")),
            "file_sha256": _sha(browser.get("file_sha256"), "browser_artifact.file_sha256"),
            "raw_sha256": _sha(browser.get("raw_sha256"), "browser_artifact.raw_sha256"),
        }
        try:
            current_values = _current_values(
                current=current,
                current_head=current_head,
                current_canonical_head=current_canonical_head,
                current_api_version=current_api_version,
                current_schema_sha256=current_schema_sha256,
                current_migration_head=current_migration_head,
                current_browser_artifact_path=current_browser_artifact_path,
                current_browser_artifact_file_sha256=current_browser_artifact_file_sha256,
                current_browser_file_sha256=current_browser_file_sha256,
                current_browser_raw_sha256=current_browser_raw_sha256,
                current_raw_sha256=current_raw_sha256,
                current_graph_snapshot_sha256=current_graph_snapshot_sha256,
                current_graph_snapshot_hash=current_graph_snapshot_hash,
                current_observe_receipt_sha256=current_observe_receipt_sha256,
                current_observe_receipt_hash=current_observe_receipt_hash,
                current_lease_projection=current_lease_projection,
                current_api_schema_migration=current_api_schema_migration,
                current_browser_artifact=current_browser_artifact,
            )
        except OzonAcceptanceSnapshotError:
            issues.append(_issue("current_binding_incomplete", "current"))
            current_values = None
        if current_values is not None:
            comparisons = (
                ("canonical_head", "canonical_head_drift", stored_fields["canonical_head"], current_values["canonical_head"]),
                ("api_version", "api_version_drift", stored_fields["api_version"], current_values["api_version"]),
                ("schema_sha256", "schema_sha256_drift", stored_fields["schema_sha256"], current_values["schema_sha256"]),
                ("migration_head", "migration_head_drift", stored_fields["migration_head"], current_values["migration_head"]),
                ("graph_snapshot_sha256", "graph_snapshot_hash_drift", stored_fields["graph_snapshot_sha256"], current_values["graph_snapshot_sha256"]),
                ("observe_receipt_sha256", "observe_receipt_hash_drift", stored_fields["observe_receipt_sha256"], current_values["observe_receipt_sha256"]),
                ("lease_projection", "lease_projection_drift", stored_lease, current_values["lease_projection"]),
            )
            for field, code, expected, observed in comparisons:
                if expected != observed:
                    issues.append(_issue(code, field))
            current_browser = current_values["browser_artifact"]
            if stored_browser["path"] != current_browser["path"]:
                issues.append(_issue("browser_artifact_path_drift", "browser_artifact.path"))
            if stored_browser["file_sha256"] != current_browser["file_sha256"]:
                issues.append(_issue("browser_artifact_file_hash_drift", "browser_artifact.file_sha256"))
            if stored_browser["raw_sha256"] != current_browser["raw_sha256"]:
                issues.append(_issue("browser_artifact_raw_hash_drift", "browser_artifact.raw_sha256"))
            hash_checks.update(
                {
                    "browser_file": stored_browser["file_sha256"] == current_browser["file_sha256"],
                    "browser_raw": stored_browser["raw_sha256"] == current_browser["raw_sha256"],
                    "graph": stored_fields["graph_snapshot_sha256"] == current_values["graph_snapshot_sha256"],
                    "observe": stored_fields["observe_receipt_sha256"] == current_values["observe_receipt_sha256"],
                    "lease": stored_lease == current_values["lease_projection"],
                }
            )
        if as_of is not None:
            requested_as_of = _timestamp(as_of, "as_of")
            time_checks["as_of_matches"] = requested_as_of == stored_as_of
            if not time_checks["as_of_matches"]:
                issues.append(_issue("as_of_drift", "as_of"))
        if now is not None:
            current_time = _timestamp(now, "now")
            time_checks["not_from_future"] = current_time >= captured
            if not time_checks["not_from_future"]:
                issues.append(_issue("snapshot_from_future", "captured_at"))
            age_limit = _validate_age(max_age_seconds)
            if age_limit is not None and current_time >= captured:
                age_seconds = (current_time - captured).total_seconds()
                time_checks["within_max_age"] = age_seconds <= age_limit
                if not time_checks["within_max_age"]:
                    issues.append(_issue("snapshot_stale", "captured_at"))
    except OzonAcceptanceSnapshotError as exc:
        # Error text is generated from field names only.  Keep the report
        # machine-readable and avoid returning any potentially sensitive input.
        token = str(exc).split(" ", 1)[0] or "snapshot"
        issues.append(_issue("snapshot_invalid", token))

    # Stable order and deduplication make reports replayable.
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for item in issues:
        unique[(item["code"], item["field"])] = item
    ordered = [unique[key] for key in sorted(unique)]
    codes = [item["code"] for item in ordered]
    if any(
        code == "snapshot_invalid"
        or code.endswith("_invalid")
        or code.endswith("_incomplete")
        or code.endswith("_missing")
        or code in {"snapshot_hash_missing", "credential_values_present"}
        for code in codes
    ):
        status = "invalid"
    elif any(
        code.endswith("_drift")
        or code.endswith("_hash_drift")
        or code in {
            "snapshot_hash_drift",
            "api_schema_migration_binding_drift",
            "snapshot_from_future",
        }
        for code in codes
    ):
        status = "drifted"
    elif "snapshot_stale" in codes:
        status = "stale"
    else:
        status = "valid"
    return {
        "contract_id": VALIDATION_CONTRACT_ID,
        "contract_version": CONTRACT_VERSION,
        "status": status,
        "valid": status == "valid",
        "drifts": ordered,
        "blockers": [item["code"] for item in ordered],
        "hash_checks": hash_checks,
        "time_checks": time_checks,
        "snapshot_sha256": observed_hash,
        "external_write_allowed": False,
        "credential_values_returned": False,
        "secret_free": True,
    }


def hmac_compare(left: str, right: str) -> bool:
    """Constant-time comparison for digest strings."""

    return hashlib.sha256(left.encode("ascii")).digest() == hashlib.sha256(right.encode("ascii")).digest()


def freeze_snapshot(value: AcceptanceSnapshot | Mapping[str, Any]) -> AcceptanceSnapshot:
    """Freeze an already hashed snapshot mapping, validating its digest."""

    if isinstance(value, AcceptanceSnapshot):
        return value
    if not isinstance(value, Mapping):
        raise OzonAcceptanceSnapshotError("snapshot must be an object")
    normalized = _jsonable(value, field="snapshot")
    if not isinstance(normalized, Mapping):
        raise OzonAcceptanceSnapshotError("snapshot must be an object")
    supplied = normalized.get("snapshot_sha256")
    if not isinstance(supplied, str) or not _SHA256.fullmatch(supplied):
        raise OzonAcceptanceSnapshotError("snapshot_sha256 is required")
    expected = sha256_json(_snapshot_basis(normalized))
    if supplied.lower() != expected:
        raise OzonAcceptanceSnapshotError("snapshot_sha256 does not match payload")
    return AcceptanceSnapshot(normalized)


# Explicit aliases keep the public API discoverable beside the existing
# ``OzonProductionAcceptanceService`` naming.
OzonAcceptanceSnapshot = AcceptanceSnapshot
create_snapshot = build_snapshot
build_acceptance_snapshot = build_snapshot
create_acceptance_snapshot = build_snapshot
validate_acceptance_snapshot = validate_snapshot


__all__ = [
    "AcceptanceSnapshot",
    "CONTRACT_ID",
    "CONTRACT_VERSION",
    "OzonAcceptanceSnapshot",
    "OzonAcceptanceSnapshotError",
    "build_acceptance_snapshot",
    "build_snapshot",
    "canonical_json",
    "create_acceptance_snapshot",
    "create_snapshot",
    "freeze_snapshot",
    "read_artifact_binding",
    "sanitize_lease_projection",
    "sha256_json",
    "validate_acceptance_snapshot",
    "validate_snapshot",
]
