from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Protocol

from .security import Principal

ACCEPTANCE_DIMENSIONS = (
    "code",
    "migration",
    "api_openapi",
    "web",
    "permission_write_path",
    "runtime_replay",
    "immutable_evidence",
    "external_graph_verifier",
)
ACCEPTANCE_STATES = (
    "mapped",
    "implemented_unverified",
    "gated",
    "verified_native",
    "blocked",
    "stale",
)
_HEX = frozenset("0123456789abcdef")


class NativeParityAcceptanceError(ValueError):
    """The acceptance authority could not produce a trustworthy projection."""


class AcceptanceRecordAdapter(Protocol):
    """Read-only seam for verifier-owned mapping and acceptance records."""

    def read_records(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
    ) -> list[dict[str, Any]]: ...


class RegistryMappingAcceptanceRecords:
    """Expose server-owned benchmark mappings without claiming verification."""

    def __init__(self, identities: list[tuple[str, str, str]]) -> None:
        normalized = {
            (
                NativeParityAcceptanceWorkspace._text(provider, "provider_id"),
                NativeParityAcceptanceWorkspace._text(capability, "capability_id"),
                NativeParityAcceptanceWorkspace._text(version, "capability_version"),
            )
            for provider, capability, version in identities
        }
        self._identities = tuple(sorted(normalized))

    def read_records(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        recorded_at = datetime(1970, 1, 1, tzinfo=UTC)
        rows: list[dict[str, Any]] = []
        for sequence, (provider, capability, version) in enumerate(self._identities, start=1):
            row = {
                "tenant_ref": tenant_ref,
                "entity_ref": entity_ref,
                "store_ref": store_ref,
                "provider_id": provider,
                "capability_id": capability,
                "capability_version": version,
                "record_kind": "mapping",
                "record_id": f"registry:{provider}:{capability}:{version}",
                "sequence": sequence,
                "recorded_at": recorded_at,
                "status": "mapped",
                "gate_status": "gated",
            }
            row["record_sha256"] = NativeParityAcceptanceWorkspace._hash(row)
            rows.append(row)
        return rows


class NativeParityAcceptanceWorkspace:
    """Capability-granular, fail-closed native parity acceptance projection."""

    CONTRACT_ID = "native-parity-acceptance-workspace.v1"
    ARTIFACT_SCHEMA_VERSION = "native-parity-acceptance-artifact.v1"
    CURSOR_VERSION = 1

    def __init__(
        self,
        *,
        records: AcceptanceRecordAdapter,
        external_verifier_ids: frozenset[str] | set[str],
    ) -> None:
        self._records = records
        self._external_verifier_ids = frozenset(
            self._text(value, "external_verifier_id") for value in external_verifier_ids
        )
        if not self._external_verifier_ids:
            raise NativeParityAcceptanceError("At least one server-registered external verifier is required")

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: str | datetime,
        provider_id: str | None = None,
        capability_id: str | None = None,
        capability_version: str | None = None,
        status: str | None = None,
        cursor: str | None = None,
        page_size: int = 50,
    ) -> dict[str, Any]:
        store = self._text(store_ref, "store_ref")
        cutoff = self._instant(as_of, "as_of")
        if not principal.can_access_store(store):
            raise PermissionError("native parity store scope is not authorized")
        if not isinstance(entity_scope, dict):
            raise NativeParityAcceptanceError("entity_scope must be an object")
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        if not entity_ref:
            return self._empty_workspace(principal=principal, store_ref=store, cutoff=cutoff)
        authority_sha256 = str(entity_scope.get("authority_sha256") or "").strip()
        supplied_scope = (
            entity_scope.get("tenant_ref"),
            entity_scope.get("entity_ref"),
            entity_scope.get("store_ref"),
        )
        if (
            entity_scope.get("status") != "ready"
            or supplied_scope != (principal.tenant_ref, entity_ref, store)
            or not self._is_digest(authority_sha256)
        ):
            raise PermissionError("native parity entity scope is not authoritative")
        filters = {
            "provider_id": self._optional_text(provider_id, "provider_id"),
            "capability_id": self._optional_text(capability_id, "capability_id"),
            "capability_version": self._optional_text(capability_version, "capability_version"),
            "status": self._optional_text(status, "status"),
        }
        if filters["status"] is not None and filters["status"] not in ACCEPTANCE_STATES:
            raise NativeParityAcceptanceError("Unknown acceptance state filter")
        if not 1 <= page_size <= 100:
            raise NativeParityAcceptanceError("page_size must be between 1 and 100")

        base_scope = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store,
        }
        raw = self._records.read_records(**base_scope, as_of=cutoff)
        if not isinstance(raw, list):
            raise NativeParityAcceptanceError("Acceptance adapter must return a list")
        identities: set[tuple[str, str, str]] = set()
        for row in raw:
            if not isinstance(row, dict):
                raise NativeParityAcceptanceError("record_not_object")
            if any(row.get(field) != value for field, value in base_scope.items()):
                raise NativeParityAcceptanceError("adapter_returned_cross_scope_record")
            identities.add(
                tuple(
                    self._text(row.get(field), field)
                    for field in ("provider_id", "capability_id", "capability_version")
                )
            )

        items: list[dict[str, Any]] = []
        for provider, capability, version in sorted(identities):
            if filters["provider_id"] is not None and provider != filters["provider_id"]:
                continue
            if filters["capability_id"] is not None and capability != filters["capability_id"]:
                continue
            if filters["capability_version"] is not None and version != filters["capability_version"]:
                continue
            identity = {
                **base_scope,
                "provider_id": provider,
                "capability_id": capability,
                "capability_version": version,
            }
            item = self._project_one(
                **identity,
                as_of=cutoff,
                raw=[row for row in raw if all(row.get(field) == value for field, value in identity.items())],
            )
            if filters["status"] is None or item["state"] == filters["status"]:
                items.append(item)

        filter_hash = self._hash({"scope": base_scope, "as_of": cutoff.isoformat(), "filters": filters})
        start = self._decode_cursor(cursor, filter_hash=filter_hash)
        page = items[start : start + page_size]
        next_cursor = (
            self._encode_cursor(start + page_size, filter_hash=filter_hash) if start + page_size < len(items) else None
        )
        states = Counter(item["state"] for item in items)
        providers = Counter(item["scope"]["provider_id"] for item in items)
        capabilities = Counter(item["scope"]["capability_id"] for item in items)
        basis = {
            "contract_id": self.CONTRACT_ID,
            "scope": {**base_scope, "authority_sha256": authority_sha256},
            "as_of": cutoff.isoformat(),
            "filters": filters,
            "counts": {
                "items": len(items),
                "states": {state: states[state] for state in ACCEPTANCE_STATES},
            },
            "provider_counts": dict(sorted(providers.items())),
            "capability_counts": dict(sorted(capabilities.items())),
            "item_snapshot_sha256": [item["snapshot_sha256"] for item in items],
        }
        return {
            **basis,
            "status": "ready" if items else "no_data",
            "items": page,
            "next_cursor": next_cursor,
            "snapshot_sha256": self._hash(basis),
            "control_envelope": self._control_envelope(),
        }

    def _project_one(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        provider_id: str,
        capability_id: str,
        capability_version: str,
        as_of: str | datetime,
        raw: list[dict[str, Any]],
    ) -> dict[str, Any]:
        scope = {
            "tenant_ref": self._text(tenant_ref, "tenant_ref"),
            "entity_ref": self._text(entity_ref, "entity_ref"),
            "store_ref": self._text(store_ref, "store_ref"),
            "provider_id": self._text(provider_id, "provider_id"),
            "capability_id": self._text(capability_id, "capability_id"),
            "capability_version": self._text(capability_version, "capability_version"),
        }
        cutoff = self._instant(as_of, "as_of")
        if not isinstance(raw, list):
            raise NativeParityAcceptanceError("Acceptance adapter must return a list")

        mapping_rows: list[dict[str, Any]] = []
        observations: dict[str, list[dict[str, Any]]] = {item: [] for item in ACCEPTANCE_DIMENSIONS}
        invalid: list[dict[str, str]] = []
        for candidate in raw:
            try:
                record = self._validate_record(candidate, scope=scope, cutoff=cutoff)
            except NativeParityAcceptanceError as exc:
                invalid.append(
                    {
                        "record_id": self._safe_record_id(candidate),
                        "reason": str(exc),
                    }
                )
                continue
            if record["record_kind"] == "mapping":
                mapping_rows.append(record)
            else:
                observations[record["dimension"]].append(record)

        latest_mapping = self._latest(mapping_rows)
        latest: dict[str, dict[str, Any]] = {}
        for item, rows in observations.items():
            selected = self._latest(rows)
            if selected is not None:
                latest[item] = selected

        binding_hashes = {row["acceptance_input_sha256"] for row in latest.values()}
        binding_drift = len(binding_hashes) > 1
        failed_dimensions = sorted(item for item, row in latest.items() if row["status"] == "failed")
        stale_dimensions = sorted(item for item, row in latest.items() if row["expires_at"] < cutoff)
        missing_dimensions = sorted(set(ACCEPTANCE_DIMENSIONS) - set(latest))
        self_certified_dimensions = sorted(
            item
            for item, row in latest.items()
            if row["producer_id"] == row["verifier_id"] or row["verifier_id"] not in self._external_verifier_ids
        )
        graph = latest.get("external_graph_verifier")
        graph_verifier_missing = graph is not None and (graph["verifier_kind"] != "external_graph")

        blockers: list[str] = []
        if invalid:
            blockers.append("invalid_acceptance_record")
        if binding_drift:
            blockers.append("acceptance_input_hash_drift")
        if failed_dimensions:
            blockers.append("latest_dimension_failed")
        if self_certified_dimensions:
            blockers.append("self_or_unregistered_certification")
        if graph_verifier_missing:
            blockers.append("provider_specific_graph_verifier_missing")

        mapped = latest_mapping is not None and latest_mapping["status"] == "mapped"
        complete = not missing_dimensions and len(latest) == len(ACCEPTANCE_DIMENSIONS)
        all_passed = complete and all(row["status"] == "passed" for row in latest.values())
        if blockers:
            state = "blocked"
        elif stale_dimensions:
            state = "stale"
        elif all_passed:
            state = "verified_native"
        elif latest:
            state = "implemented_unverified"
        elif mapped and latest_mapping.get("gate_status") == "gated":
            state = "gated"
        else:
            state = "mapped"

        rows = [self._public_record(row) for row in latest.values()]
        rows.sort(key=lambda row: (row["dimension"], row["record_id"]))
        dimension_counts = Counter(row["status"] for row in latest.values())
        input_payload = {
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "latest_record_sha256": {item: row["record_sha256"] for item, row in sorted(latest.items())},
            "mapping_record_sha256": (latest_mapping["record_sha256"] if latest_mapping else None),
        }
        input_sha256 = self._hash(input_payload)
        artifact = {
            "schema_version": self.ARTIFACT_SCHEMA_VERSION,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "input_sha256": input_sha256,
            "state": state,
            "verified_native": state == "verified_native",
            "dimension_statuses": {
                item: latest[item]["status"] if item in latest else "missing" for item in ACCEPTANCE_DIMENSIONS
            },
            "missing_dimensions": missing_dimensions,
            "stale_dimensions": stale_dimensions,
            "failed_dimensions": failed_dimensions,
            "blockers": blockers,
        }
        artifact["artifact_sha256"] = self._hash(artifact)
        snapshot_basis = {
            "contract_id": self.CONTRACT_ID,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "state": state,
            "counts": {
                "required_dimensions": len(ACCEPTANCE_DIMENSIONS),
                "observed_dimensions": len(latest),
                "passed_dimensions": dimension_counts["passed"],
                "failed_dimensions": dimension_counts["failed"],
                "missing_dimensions": len(missing_dimensions),
                "stale_dimensions": len(stale_dimensions),
                "invalid_records": len(invalid),
                "filtered_records": len(rows),
            },
            "input_sha256": input_sha256,
            "artifact_sha256": artifact["artifact_sha256"],
        }
        return {
            **snapshot_basis,
            "status": "ready" if latest or mapped else "no_data",
            "verified_native": state == "verified_native",
            "missing_dimensions": missing_dimensions,
            "stale_dimensions": stale_dimensions,
            "failed_dimensions": failed_dimensions,
            "records": rows,
            "invalid_records": invalid,
            "source_gaps": [
                *(f"missing:{item}" for item in missing_dimensions),
                *(f"stale:{item}" for item in stale_dimensions),
            ],
            "acceptance_artifact": artifact,
            "control_envelope": {
                "read_only": True,
                "client_can_recalculate_or_promote": False,
                "mapping_is_implementation": False,
                "engineering_done_is_verified_native": False,
                "self_certification_allowed": False,
                "business_fact_created": False,
                "approval_created": False,
                "permit_created": False,
                "credential_created_or_read": False,
                "external_write_allowed": False,
            },
            "snapshot_sha256": self._hash(snapshot_basis),
        }

    def _empty_workspace(self, *, principal: Principal, store_ref: str, cutoff: datetime) -> dict[str, Any]:
        basis = {
            "contract_id": self.CONTRACT_ID,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": None,
                "store_ref": store_ref,
                "authority_sha256": None,
            },
            "as_of": cutoff.isoformat(),
            "filters": {
                "provider_id": None,
                "capability_id": None,
                "capability_version": None,
                "status": None,
            },
            "counts": {"items": 0, "states": {state: 0 for state in ACCEPTANCE_STATES}},
            "provider_counts": {},
            "capability_counts": {},
            "item_snapshot_sha256": [],
        }
        return {
            **basis,
            "status": "no_data",
            "items": [],
            "next_cursor": None,
            "source_gaps": ["entity_scope_missing"],
            "snapshot_sha256": self._hash(basis),
            "control_envelope": self._control_envelope(),
        }

    @staticmethod
    def _control_envelope() -> dict[str, bool]:
        return {
            "read_only": True,
            "client_can_recalculate_or_promote": False,
            "mapping_is_implementation": False,
            "engineering_done_is_verified_native": False,
            "self_certification_allowed": False,
            "business_fact_created": False,
            "approval_created": False,
            "permit_created": False,
            "credential_created_or_read": False,
            "external_write_allowed": False,
        }

    @classmethod
    def _optional_text(cls, value: Any, field: str) -> str | None:
        return None if value is None else cls._text(value, field)

    @staticmethod
    def _is_digest(value: Any) -> bool:
        return isinstance(value, str) and len(value) == 64 and not set(value) - _HEX

    def _validate_record(
        self,
        candidate: Any,
        *,
        scope: dict[str, str],
        cutoff: datetime,
    ) -> dict[str, Any]:
        if not isinstance(candidate, dict):
            raise NativeParityAcceptanceError("record_not_object")
        row = dict(candidate)
        for field, expected in scope.items():
            if row.get(field) != expected:
                raise NativeParityAcceptanceError(f"cross_scope_or_version:{field}")
        kind = row.get("record_kind")
        if kind not in {"mapping", "observation"}:
            raise NativeParityAcceptanceError("unknown_record_kind")
        row["record_id"] = self._text(row.get("record_id"), "record_id")
        row["recorded_at"] = self._instant(row.get("recorded_at"), "recorded_at")
        if row["recorded_at"] > cutoff:
            raise NativeParityAcceptanceError("record_from_future")
        row["sequence"] = row.get("sequence")
        if not isinstance(row["sequence"], int) or row["sequence"] < 1:
            raise NativeParityAcceptanceError("invalid_sequence")
        if kind == "mapping":
            if row.get("status") != "mapped":
                raise NativeParityAcceptanceError("invalid_mapping_status")
            if row.get("gate_status") not in {None, "gated"}:
                raise NativeParityAcceptanceError("invalid_gate_status")
        else:
            if row.get("dimension") not in ACCEPTANCE_DIMENSIONS:
                raise NativeParityAcceptanceError("unknown_dimension")
            if row.get("status") not in {"passed", "failed"}:
                raise NativeParityAcceptanceError("unknown_observation_status")
            row["expires_at"] = self._instant(row.get("expires_at"), "expires_at")
            row["producer_id"] = self._text(row.get("producer_id"), "producer_id")
            row["verifier_id"] = self._text(row.get("verifier_id"), "verifier_id")
            row["verifier_kind"] = self._text(row.get("verifier_kind"), "verifier_kind")
            for field in (
                "acceptance_input_sha256",
                "subject_sha256",
                "evidence_sha256",
            ):
                self._digest(row.get(field), field)
        claimed = row.pop("record_sha256", None)
        self._digest(claimed, "record_sha256")
        actual = self._hash(self._serializable(row))
        if not hmac.compare_digest(claimed, actual):
            raise NativeParityAcceptanceError("record_hash_mismatch")
        row["record_sha256"] = claimed
        return row

    @staticmethod
    def _latest(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not rows:
            return None
        return max(rows, key=lambda row: (row["sequence"], row["recorded_at"], row["record_id"]))

    @staticmethod
    def _public_record(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: (value.isoformat() if isinstance(value, datetime) else value)
            for key, value in row.items()
            if key not in {"tenant_ref", "entity_ref", "store_ref"}
        }

    @classmethod
    def _encode_cursor(cls, offset: int, *, filter_hash: str) -> str:
        raw = json.dumps(
            {"v": cls.CURSOR_VERSION, "o": offset, "f": filter_hash},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def _decode_cursor(cls, cursor: str | None, *, filter_hash: str) -> int:
        if cursor is None:
            return 0
        try:
            raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
            value = json.loads(raw)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise NativeParityAcceptanceError("Invalid opaque cursor") from exc
        if (
            not isinstance(value, dict)
            or value.get("v") != cls.CURSOR_VERSION
            or value.get("f") != filter_hash
            or not isinstance(value.get("o"), int)
            or value["o"] < 0
        ):
            raise NativeParityAcceptanceError("Cursor does not match this projection")
        return value["o"]

    @staticmethod
    def _serializable(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {key: NativeParityAcceptanceWorkspace._serializable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [NativeParityAcceptanceWorkspace._serializable(item) for item in value]
        return value

    @classmethod
    def _hash(cls, value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                cls._serializable(value),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @staticmethod
    def _text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise NativeParityAcceptanceError(f"{field} must be non-empty canonical text")
        return value

    @staticmethod
    def _instant(value: Any, field: str) -> datetime:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise NativeParityAcceptanceError(f"{field} must be ISO-8601") from exc
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise NativeParityAcceptanceError(f"{field} must include timezone")
        return value.astimezone(UTC)

    @staticmethod
    def _digest(value: Any, field: str) -> str:
        if not isinstance(value, str) or len(value) != 64 or any(character not in _HEX for character in value):
            raise NativeParityAcceptanceError(f"{field} must be lowercase SHA-256")
        return value

    @staticmethod
    def _safe_record_id(candidate: Any) -> str:
        if isinstance(candidate, dict) and isinstance(candidate.get("record_id"), str):
            return candidate["record_id"][:128]
        return "unknown"
