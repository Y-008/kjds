"""Versioned temporal facts for the first data-fabric slice.

The existing ``facts`` module is the authority for the current Ozon import
pipeline.  This module deliberately provides a small, provider-neutral
temporal kernel that can be used by projections and replay tooling before a
PostgreSQL table is introduced.  It is append-only: a correction is a new
revision and an ``as_of`` read returns the revision that was observable at the
requested cutoff.

The store is intentionally in-memory for this slice.  Keeping the contract
independent of SQL makes it useful in tests, import previews, and deterministic
replay; a later persistence adapter can implement the same model without
changing callers.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .data_fabric_contracts import (
    DataEnvelope,
    EvidenceRef,
    FreshnessState,
    QualitySummary,
    ScopeRef,
    canonical_scope_key,
)


class QualityState(StrEnum):
    """Quality is independent from the numeric value carried by a fact."""

    NO_DATA = "NO_DATA"
    PARTIAL = "PARTIAL"
    STALE = "STALE"
    BLOCKED = "BLOCKED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    VALID = "VALID"

    @classmethod
    def _missing_(cls, value: object) -> QualityState | None:
        if isinstance(value, str):
            normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
            aliases = {
                "READY": cls.VALID,
                "FRESH": cls.VALID,
                "UNKNOWN": cls.UNKNOWN_OUTCOME,
                "UNKNOWN_RESULT": cls.UNKNOWN_OUTCOME,
                "NO_DATA": cls.NO_DATA,
                "PARTIAL": cls.PARTIAL,
                "STALE": cls.STALE,
                "BLOCKED": cls.BLOCKED,
                "UNKNOWN_OUTCOME": cls.UNKNOWN_OUTCOME,
                "VALID": cls.VALID,
            }
            return aliases.get(normalized)
        return None


# A public alias makes the vocabulary discoverable without requiring callers
# to know whether the project prefers an enum or a typing alias.
FactQualityState = QualityState


class TemporalFactError(ValueError):
    """Base error raised by the temporal fact contract."""


class FactNotFoundError(KeyError, TemporalFactError):
    """The requested fact or revision is not present/visible."""


class RevisionConflictError(TemporalFactError):
    """An append would violate immutable identity or revision ordering."""


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _utc(value: Any, field: str) -> datetime:
    """Parse an aware timestamp and normalize it to UTC."""

    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 datetime") from exc
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _optional_utc(value: Any, field: str) -> datetime | None:
    return None if value is None else _utc(value, field)


def _text(value: Any, field: str, maximum: int = 500) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _sha256(value: Any, field: str) -> str:
    normalized = _text(value, field, 64).lower()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return normalized


def _json_safe(value: Any) -> Any:
    """Return canonical-JSON-compatible data without silently losing values."""

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("payload contains a non-finite Decimal")
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.astimezone(UTC).isoformat() if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_safe(item) for item in value), key=lambda item: repr(item))
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError("payload contains a non-finite float")
        return value
    raise TypeError(f"payload value of type {type(value).__name__} is not JSON serializable")


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def lineage_edge_id(
    *, revision_id: str, from_type: str, from_id: str, relationship: str
) -> str:
    """Return a deterministic identifier for a fact lineage edge."""

    digest = content_sha256(
        {
            "revision_id": revision_id,
            "from_type": from_type,
            "from_id": from_id,
            "relationship": relationship,
        }
    )
    return f"lin_{digest[:40]}"


class LineageRef(_Contract):
    """A compact reference to an upstream or downstream artifact."""

    kind: str = Field(min_length=1, max_length=120)
    id: str = Field(min_length=1, max_length=300)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    relationship: str = Field(default="supports", min_length=1, max_length=120)
    version: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="before")
    @classmethod
    def normalize_values(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        if "sha256" not in data and "hash" in data:
            data["sha256"] = data.pop("hash")
        for name in ("kind", "id", "relationship", "version"):
            if data.get(name) is not None:
                data[name] = str(data[name]).strip()
        if data.get("sha256") is not None:
            data["sha256"] = str(data["sha256"]).strip().lower()
        return data

    @model_validator(mode="after")
    def validate_hash(self) -> LineageRef:
        if self.sha256 is not None:
            _sha256(self.sha256, "lineage.sha256")
        return self


class LineageEdge(_Contract):
    """A typed edge used by transparency views and replay exports."""

    id: str = Field(default_factory=lambda: _new_id("lin"), min_length=1, max_length=200)
    from_type: str = Field(min_length=1, max_length=120)
    from_id: str = Field(min_length=1, max_length=300)
    to_type: str = Field(min_length=1, max_length=120)
    to_id: str = Field(min_length=1, max_length=300)
    relationship: str = Field(min_length=1, max_length=120)
    from_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    to_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    created_by: str = Field(default="system", min_length=1, max_length=160)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_values(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        for name in ("from_type", "from_id", "to_type", "to_id", "relationship", "created_by"):
            if data.get(name) is not None:
                data[name] = str(data[name]).strip()
        for name in ("from_sha256", "to_sha256"):
            if data.get(name) is not None:
                data[name] = str(data[name]).strip().lower()
        if data.get("recorded_at") is not None:
            data["recorded_at"] = _utc(data["recorded_at"], "lineage.recorded_at")
        return data

    @model_validator(mode="after")
    def validate_edge(self) -> LineageEdge:
        if self.from_type == self.to_type and self.from_id == self.to_id:
            raise ValueError("lineage edge cannot point to itself")
        if self.from_sha256 is not None:
            _sha256(self.from_sha256, "lineage.from_sha256")
        if self.to_sha256 is not None:
            _sha256(self.to_sha256, "lineage.to_sha256")
        return self


class TemporalFactTimes(_Contract):
    """Business, observation, rule-effective and settlement timestamps."""

    event_time: datetime
    observed_time: datetime
    effective_time: datetime
    settled_time: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_times(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        aliases = {
            "event_at": "event_time",
            "occurred_at": "event_time",
            "observed_at": "observed_time",
            "captured_at": "observed_time",
            "recorded_at": "observed_time",
            "effective_at": "effective_time",
            "settled_at": "settled_time",
        }
        for source, target in aliases.items():
            if target not in data and source in data:
                data[target] = data[source]
            data.pop(source, None)

        nested_times = data.pop("times", None)
        if nested_times is not None:
            if isinstance(nested_times, TemporalFactTimes):
                nested_times = nested_times.model_dump(mode="python")
            if not isinstance(nested_times, Mapping):
                raise ValueError("times must be a TemporalFactTimes object")
            for name in ("event_time", "observed_time", "effective_time", "settled_time"):
                if name not in data and name in nested_times:
                    data[name] = nested_times[name]
        for name in ("event_time", "observed_time", "effective_time", "settled_time"):
            if data.get(name) is not None:
                data[name] = _utc(data[name], name)
        return data

    @model_validator(mode="after")
    def validate_chronology(self) -> TemporalFactTimes:
        if self.event_time > self.observed_time:
            raise ValueError("event_time cannot be after observed_time")
        # ``effective_time`` is the business/rule time and may legitimately be
        # scheduled after the observation (for example, a price rule imported
        # before its launch).  Settlement is ordered against the business event,
        # rather than the rule-effective timestamp, because a late rule
        # correction must not make an already-settled order invalid.
        if self.settled_time is not None and self.settled_time < self.event_time:
            raise ValueError("settled_time cannot precede event_time")
        return self


class TemporalFactRevision(_Contract):
    """One immutable version of a canonical fact."""

    fact_id: str = Field(default_factory=lambda: _new_id("fact"), min_length=1, max_length=200)
    revision_id: str = Field(default_factory=lambda: _new_id("rev"), min_length=1, max_length=200)
    revision: int = Field(default=1, ge=1)
    fact_type: str = Field(default="generic", min_length=1, max_length=160)
    natural_key: str = Field(min_length=1, max_length=300)
    payload: dict[str, Any] = Field(default_factory=dict)
    scope: ScopeRef
    # SKU is optional only for legacy entity-level facts.  New SKU-level
    # producers should provide it (or include one SKU in ``scope.sku_ids``);
    # ``exclude_if`` keeps old serialized rows byte-compatible when absent.
    sku: str | None = Field(default=None, min_length=1, max_length=240, exclude_if=lambda value: value is None)
    event_time: datetime
    observed_time: datetime
    effective_time: datetime
    settled_time: datetime | None = None
    fresh_until: datetime | None = None
    source_system: str = Field(default="unknown", min_length=1, max_length=160)
    source_record_id: str = Field(min_length=1, max_length=300)
    source_version: str = Field(default="1", min_length=1, max_length=120)
    causation_id: str = Field(default="", max_length=300)
    correlation_id: str = Field(default="", max_length=300)
    idempotency_key: str = Field(default="", max_length=300)
    permission_scope: str | None = Field(default=None, max_length=800)
    quality_state: QualityState = QualityState.VALID
    # Freshness is deliberately separate from quality state.  It is persisted
    # on new rows but derived from the state for legacy input that omitted it.
    freshness: FreshnessState | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    lineage: tuple[LineageRef, ...] = ()
    supersedes_revision: int | None = Field(default=None, ge=1)
    revision_reason: str | None = Field(default=None, max_length=2000)
    created_by: str = Field(default="system", min_length=1, max_length=160)
    payload_hash: str | None = Field(default=None, min_length=64, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_input(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)

        # Accept the names used by the existing event and FactRecord contracts.
        aliases = {
            "id": "fact_id",
            "version": "revision",
            "version_id": "revision_id",
            "occurred_at": "event_time",
            "event_at": "event_time",
            "observed_at": "observed_time",
            "captured_at": "observed_time",
            "recorded_at": "observed_time",
            "effective_at": "effective_time",
            "settled_at": "settled_time",
            "data": "payload",
            "value": "payload",
            "source": "source_system",
            "source_ref": "source_record_id",
            "contract_version": "source_version",
            "hash": "payload_hash",
            "sku_id": "sku",
            "seller_sku": "sku",
            "quality_status": "quality_state",
        }
        for source, target in aliases.items():
            if target not in data and source in data:
                data[target] = data[source]
            data.pop(source, None)

        if "scope" not in data or data.get("scope") is None:
            # Convenience input for adapters that have singular scope columns.
            tenant = data.pop("tenant_id", data.pop("tenant_ref", None))
            entity = data.pop("entity_id", data.pop("entity_ref", None))
            store = data.pop("store_id", data.pop("store_ref", None))
            warehouse = data.pop("warehouse_id", data.pop("warehouse_ref", None))
            if tenant is not None and entity is not None:
                data["scope"] = {
                    "tenant_id": tenant,
                    "entity_id": entity,
                    "store_ids": (store,) if store else (),
                    "warehouse_ids": (warehouse,) if warehouse else (),
                }

        if not data.get("natural_key") and data.get("source_record_id"):
            data["natural_key"] = data["source_record_id"]
        if not data.get("source_record_id") and data.get("natural_key"):
            data["source_record_id"] = data["natural_key"]
        if not data.get("fact_type"):
            data["fact_type"] = "generic"
        if not data.get("source_system"):
            data["source_system"] = "unknown"
        if not data.get("created_by"):
            data["created_by"] = "system"

        event = data.get("event_time")
        observed = data.get("observed_time")
        if event is None and observed is not None:
            data["event_time"] = observed
            event = observed
        if observed is None and event is not None:
            data["observed_time"] = event
            observed = event
        if data.get("effective_time") is None:
            data["effective_time"] = event or observed

        payload = data.get("payload", {})
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be an object")
        data["payload"] = _json_safe(payload)
        # Promote the common SKU keys into the row-level contract.  This is a
        # lossless projection: the original payload remains untouched and
        # legacy facts without a SKU continue to be valid entity-level facts.
        if data.get("sku") is None:
            payload_sku = payload.get("sku") or payload.get("sku_id") or payload.get("seller_sku")
            if payload_sku is not None:
                data["sku"] = str(payload_sku).strip()
        raw_scope = data.get("scope")
        if data.get("sku") and raw_scope is not None:
            scope_obj = raw_scope if isinstance(raw_scope, ScopeRef) else ScopeRef.model_validate(raw_scope)
            if scope_obj.sku_ids:
                if data["sku"] not in scope_obj.sku_ids:
                    raise ValueError("sku does not match fact scope")
            else:
                # Bind an explicit SKU to scope so permission and identity
                # keys cannot accidentally collapse into an entity-wide row.
                data["scope"] = scope_obj.model_copy(update={"sku_ids": (data["sku"],)})
        elif data.get("sku") and raw_scope is None:
            # Singular scope adapters may provide tenant/entity/store fields;
            # the scope synthesis below will include the promoted SKU.
            pass
        elif raw_scope is not None:
            scope_obj = raw_scope if isinstance(raw_scope, ScopeRef) else ScopeRef.model_validate(raw_scope)
            if scope_obj.sku_ids and len(scope_obj.sku_ids) == 1:
                data["sku"] = scope_obj.sku_ids[0]
        if data.get("metadata") is not None:
            data["metadata"] = _json_safe(data["metadata"])
        if data.get("payload_hash") is None:
            data["payload_hash"] = content_sha256(data["payload"])
        if data.get("causation_id") is None:
            data["causation_id"] = ""
        if data.get("correlation_id") is None:
            data["correlation_id"] = ""
        if data.get("idempotency_key") is None:
            data["idempotency_key"] = ""
        # Derive freshness after quality aliases have been normalized.  An
        # explicit value is checked in ``validate_revision`` below.
        if data.get("freshness") is None:
            state_value = getattr(data.get("quality_state"), "value", data.get("quality_state", "VALID"))
            data["freshness"] = (
                "fresh"
                if str(state_value).upper() == "VALID"
                else "stale"
                if str(state_value).upper() == "STALE"
                else "unknown"
            )
        if data.get("permission_scope") is None and data.get("scope") is not None:
            scope = data["scope"]
            if isinstance(scope, ScopeRef):
                data["permission_scope"] = _scope_key(scope)
            elif isinstance(scope, Mapping):
                data["permission_scope"] = _scope_key(ScopeRef.model_validate(scope))

        for name in ("event_time", "observed_time", "effective_time", "settled_time", "fresh_until"):
            if data.get(name) is not None:
                data[name] = _utc(data[name], name)
        for name in (
            "fact_type",
            "natural_key",
            "source_system",
            "source_record_id",
            "source_version",
            "causation_id",
            "correlation_id",
            "idempotency_key",
            "permission_scope",
            "revision_reason",
            "created_by",
            "sku",
        ):
            if data.get(name) is not None:
                data[name] = str(data[name]).strip()
        if data.get("quality_state") is not None:
            data["quality_state"] = QualityState(data["quality_state"])
        if data.get("lineage") is not None:
            data["lineage"] = tuple(LineageRef.model_validate(item) for item in data["lineage"])
        return data

    @model_validator(mode="after")
    def validate_revision(self) -> TemporalFactRevision:
        if self.payload_hash != content_sha256(self.payload):
            raise ValueError("payload_hash does not match payload")
        if self.payload_hash is not None:
            _sha256(self.payload_hash, "payload_hash")
        if self.event_time > self.observed_time:
            raise ValueError("event_time cannot be after observed_time")
        if self.sku is not None and self.scope.sku_ids and self.sku not in self.scope.sku_ids:
            raise ValueError("sku does not match fact scope")
        canonical_permission_scope = _scope_key(self.scope)
        if self.permission_scope != canonical_permission_scope:
            raise ValueError("permission_scope does not match fact scope")
        if self.settled_time is not None and self.settled_time < self.event_time:
            raise ValueError("settled_time cannot precede event_time")
        # A late-arriving fact can already be stale when it is observed.  Keep
        # that fact and its freshness horizon so historical and current quality
        # projections remain truthful; callers may explicitly set
        # ``quality_state=STALE`` when the source says it is stale.
        if (
            self.quality_state
            in {
                QualityState.NO_DATA,
                QualityState.BLOCKED,
                QualityState.UNKNOWN_OUTCOME,
            }
            and self.payload
        ):
            raise ValueError(f"{self.quality_state.value} fact cannot contain payload rows")
        expected_freshness = {
            QualityState.VALID: "fresh",
            QualityState.STALE: "stale",
            QualityState.NO_DATA: "unknown",
            QualityState.PARTIAL: "unknown",
            QualityState.BLOCKED: "unknown",
            QualityState.UNKNOWN_OUTCOME: "unknown",
        }[self.quality_state]
        if self.freshness != expected_freshness:
            raise ValueError("quality_state and freshness disagree")
        if self.supersedes_revision is not None and self.supersedes_revision >= self.revision:
            raise ValueError("supersedes_revision must precede revision")
        lineage_keys = [(item.kind, item.id, item.relationship) for item in self.lineage]
        if len(lineage_keys) != len(set(lineage_keys)):
            raise ValueError("fact lineage references must be unique")
        return self

    @property
    def version(self) -> int:
        return self.revision

    @property
    def version_id(self) -> str:
        return self.revision_id

    @property
    def content_sha256(self) -> str:
        return self.payload_hash or content_sha256(self.payload)

    @property
    def times(self) -> TemporalFactTimes:
        return TemporalFactTimes(
            event_time=self.event_time,
            observed_time=self.observed_time,
            effective_time=self.effective_time,
            settled_time=self.settled_time,
        )

    def copy_for_read(self) -> TemporalFactRevision:
        """Detach nested payload/metadata from the store-owned object."""

        return self.model_copy(deep=True)


def _scope_key(scope: ScopeRef) -> str:
    return canonical_scope_key(scope)


def _scope_matches(candidate: ScopeRef, requested: ScopeRef | None) -> bool:
    if requested is None:
        return True
    if candidate.tenant_id != requested.tenant_id or candidate.entity_id != requested.entity_id:
        return False
    if requested.store_ids and set(candidate.store_ids) != set(requested.store_ids):
        return False
    if requested.warehouse_ids and set(candidate.warehouse_ids) != set(requested.warehouse_ids):
        return False
    return not requested.sku_ids or set(candidate.sku_ids) == set(requested.sku_ids)


def _identity(fact: TemporalFactRevision) -> tuple[str, str, str]:
    """Return the canonical identity independent of source representation.

    A source system or record identifier can change when a platform republishes
    a correction.  The scoped fact type plus natural key is the stable object;
    provenance remains on each revision and in its lineage.
    """

    return (
        _scope_key(fact.scope),
        fact.fact_type,
        fact.natural_key,
    )


def _request_fingerprint(fact: TemporalFactRevision) -> str:
    return content_sha256(
        {
            "identity": _identity(fact),
            "payload_hash": fact.payload_hash,
            "sku": fact.sku,
            "event_time": fact.event_time.isoformat(),
            "observed_time": fact.observed_time.isoformat(),
            "effective_time": fact.effective_time.isoformat(),
            "settled_time": fact.settled_time.isoformat() if fact.settled_time else None,
            "fresh_until": fact.fresh_until.isoformat() if fact.fresh_until else None,
            "source_system": fact.source_system,
            "source_record_id": fact.source_record_id,
            "source_version": fact.source_version,
            "causation_id": fact.causation_id,
            "correlation_id": fact.correlation_id,
            "idempotency_key": fact.idempotency_key,
            "permission_scope": fact.permission_scope,
            "quality_state": fact.quality_state.value,
            "freshness": fact.freshness,
            "lineage": [item.model_dump(mode="json") for item in fact.lineage],
            "revision_reason": fact.revision_reason,
            "created_by": fact.created_by,
            "metadata": fact.metadata,
        }
    )


def _project_quality_at_cutoff(
    fact: TemporalFactRevision,
    cutoff: datetime,
) -> TemporalFactRevision:
    """Project freshness at a read cutoff without rewriting the fact revision."""

    if fact.quality_state == QualityState.VALID and fact.fresh_until is not None and cutoff >= fact.fresh_until:
        values = fact.model_dump(mode="python")
        values["quality_state"] = QualityState.STALE
        values["freshness"] = "stale"
        return TemporalFactRevision.model_validate(values)
    return fact


class TemporalFactQueryResult(_Contract):
    """A deterministic as-of page that can be converted to ``DataEnvelope``."""

    as_of: datetime
    items: tuple[TemporalFactRevision, ...] = ()
    quality_state: QualityState = QualityState.VALID
    excluded_count: int = Field(default=0, ge=0)
    exclusion_reasons: tuple[str, ...] = ()
    next_cursor: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_cutoff(cls, values: Any) -> Any:
        if isinstance(values, Mapping) and values.get("as_of") is not None:
            data = dict(values)
            data["as_of"] = _utc(data["as_of"], "as_of")
            return data
        return values

    def to_data_envelope(
        self,
        *,
        dataset: str,
        scope: ScopeRef | None = None,
        schema_version: str = "1.0",
        authority_hash: str = "temporal-fact-store",
        fresh_until: datetime | None = None,
    ) -> DataEnvelope:
        status_map = {
            QualityState.VALID: "ready",
            QualityState.PARTIAL: "partial",
            QualityState.STALE: "stale",
            QualityState.BLOCKED: "blocked",
            QualityState.NO_DATA: "no_data",
            QualityState.UNKNOWN_OUTCOME: "unknown_outcome",
        }
        rows = tuple(
            {
                "fact_id": item.fact_id,
                "revision_id": item.revision_id,
                "revision": item.revision,
                "fact_type": item.fact_type,
                "natural_key": item.natural_key,
                **copy.deepcopy(item.payload),
            }
            for item in self.items
        )
        if self.quality_state in {
            QualityState.NO_DATA,
            QualityState.BLOCKED,
            QualityState.UNKNOWN_OUTCOME,
        }:
            rows = ()
        freshness = (
            "fresh"
            if self.quality_state == QualityState.VALID
            else "stale"
            if self.quality_state == QualityState.STALE
            else "unknown"
        )
        completeness = (
            0.0
            if self.quality_state == QualityState.NO_DATA
            else 1.0
            if not self.excluded_count
            else max(0.0, 1.0 - self.excluded_count / max(1, len(self.items) + self.excluded_count))
        )
        lineage: list[EvidenceRef] = []
        seen: set[tuple[str, str]] = set()
        for item in self.items:
            for ref in item.lineage:
                if ref.kind not in {"evidence", "fact", "decision", "action"}:
                    continue
                key = (ref.kind, ref.id)
                if key in seen:
                    continue
                seen.add(key)
                lineage.append(EvidenceRef(kind=ref.kind, id=ref.id, sha256=ref.sha256))
        if scope is None:
            if not self.items:
                raise ValueError("scope is required for an empty temporal query")
            scope = self.items[0].scope
        return DataEnvelope(
            dataset=dataset,
            scope=scope,
            as_of=self.as_of,
            fresh_until=fresh_until,
            status=status_map[self.quality_state],
            data=rows,
            quality=QualitySummary(
                completeness=completeness,
                freshness=freshness,
                excluded_count=self.excluded_count,
                reasons=self.exclusion_reasons,
            ),
            lineage=tuple(lineage),
            schema_version=schema_version,
            authority_hash=authority_hash,
            next_cursor=self.next_cursor,
        )


class TemporalFactStore:
    """Thread-safe append-only temporal fact store.

    ``append`` is idempotent for an identical request.  A changed payload for
    an existing identity is a new revision; callers should normally use
    ``restate`` so a correction reason is recorded explicitly.
    """

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._rows: dict[str, list[TemporalFactRevision]] = {}
        self._identity_index: dict[tuple[str, str, str], str] = {}
        self._idempotency_index: dict[tuple[str, str], tuple[str, int, str]] = {}
        self._lineage_edges: dict[tuple[str, str, str, str, str], LineageEdge] = {}
        self._lock = threading.RLock()

    def append(
        self,
        fact: TemporalFactRevision | Mapping[str, Any] | None = None,
        **values: Any,
    ) -> TemporalFactRevision:
        """Append a first revision or correction and return a detached copy."""

        if fact is not None:
            if values:
                raise TypeError("append accepts either a fact or keyword fields, not both")
            candidate = fact if isinstance(fact, TemporalFactRevision) else TemporalFactRevision.model_validate(fact)
        else:
            candidate = TemporalFactRevision.model_validate(values)

        # ``model_copy(update=...)`` is intentionally used by callers such as
        # ``restate``; re-validating here prevents an untrusted nested mapping
        # from bypassing the immutable Pydantic contract.
        candidate = TemporalFactRevision.model_validate(candidate.model_dump(mode="python"))

        with self._lock:
            identity = _identity(candidate)
            existing_id = self._identity_index.get(identity)

            # Idempotency is scoped by source and key, so two tenants can use
            # the same connector key without colliding.
            if candidate.idempotency_key:
                idem_key = (_scope_key(candidate.scope), candidate.idempotency_key)
                existing_request = self._idempotency_index.get(idem_key)
                if existing_request is not None:
                    existing_fact_id, existing_revision, request_hash = existing_request
                    if request_hash != _request_fingerprint(candidate):
                        raise RevisionConflictError("idempotency key was reused with a different payload")
                    return self._rows[existing_fact_id][existing_revision - 1].copy_for_read()

            if existing_id is None:
                if candidate.revision != 1:
                    raise RevisionConflictError("first fact revision must be 1")
                row = candidate
                self._identity_index[identity] = row.fact_id
                self._rows[row.fact_id] = [row]
            else:
                if candidate.fact_id != existing_id:
                    raise RevisionConflictError("natural fact identity is already bound to another fact_id")
                current = self._rows[existing_id][-1]
                fingerprint = _request_fingerprint(candidate)
                if fingerprint == _request_fingerprint(current):
                    return current.copy_for_read()
                if candidate.observed_time < current.observed_time:
                    raise RevisionConflictError("revision observed_time cannot move backwards")
                expected_revision = current.revision + 1
                row = candidate.model_copy(
                    update={
                        "revision": expected_revision,
                        "revision_id": candidate.revision_id if candidate.revision > 1 else _new_id("rev"),
                        "supersedes_revision": current.revision,
                    },
                    deep=True,
                )
                self._rows[existing_id].append(row)

            if row.idempotency_key:
                self._idempotency_index[(_scope_key(row.scope), row.idempotency_key)] = (
                    row.fact_id,
                    row.revision,
                    _request_fingerprint(row),
                )
            self._index_lineage(row)
            return row.copy_for_read()

    record = append
    add = append
    save = append
    put = append
    append_revision = append
    upsert = append

    def restate(
        self,
        fact_id: str,
        payload: Mapping[str, Any],
        *,
        correction_reason: str,
        observed_time: datetime | None = None,
        event_time: datetime | None = None,
        effective_time: datetime | None = None,
        settled_time: datetime | None = None,
        fresh_until: datetime | None = None,
        quality_state: QualityState | str | None = None,
        lineage: Iterable[LineageRef | Mapping[str, Any]] | None = None,
        source_version: str | None = None,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_by: str | None = None,
    ) -> TemporalFactRevision:
        """Create a traceable correction revision; never mutate the old row."""

        reason = str(correction_reason or "").strip()
        if not reason:
            raise ValueError("correction_reason is required for a restatement")
        current = self.get(fact_id)
        now = _utc(observed_time or self._clock(), "observed_time")
        candidate_values = current.model_dump(mode="python")
        candidate_values.update(
            {
                "revision_id": _new_id("rev"),
                "revision": current.revision + 1,
                "payload": dict(payload),
                "payload_hash": None,
                "event_time": event_time or current.event_time,
                "observed_time": now,
                "effective_time": effective_time or current.effective_time,
                "settled_time": settled_time if settled_time is not None else current.settled_time,
                "fresh_until": fresh_until if fresh_until is not None else current.fresh_until,
                "quality_state": quality_state or current.quality_state,
                "lineage": tuple(lineage) if lineage is not None else current.lineage,
                "source_version": source_version or current.source_version,
                "causation_id": causation_id or current.causation_id,
                "correlation_id": correlation_id or current.correlation_id,
                "idempotency_key": idempotency_key or "",
                "metadata": dict(metadata) if metadata is not None else current.metadata,
                "revision_reason": reason,
                "created_by": created_by or current.created_by,
                "supersedes_revision": current.revision,
            }
        )
        candidate = TemporalFactRevision.model_validate(candidate_values)
        return self.append(candidate)

    correct = restate

    def get(self, fact_id: str, *, revision: int | None = None, version: int | None = None) -> TemporalFactRevision:
        key = str(fact_id or "").strip()
        if not key:
            raise FactNotFoundError("fact_id is required")
        selected_revision = revision if revision is not None else version
        with self._lock:
            rows = self._rows.get(key)
            if not rows:
                raise FactNotFoundError(f"Unknown fact: {key}")
            if selected_revision is None:
                return rows[-1].copy_for_read()
            if selected_revision < 1 or selected_revision > len(rows):
                raise FactNotFoundError(f"Unknown fact revision: {key}@{selected_revision}")
            return rows[selected_revision - 1].copy_for_read()

    def history(self, fact_id: str) -> tuple[TemporalFactRevision, ...]:
        with self._lock:
            rows = self._rows.get(str(fact_id or "").strip())
            if not rows:
                raise FactNotFoundError(f"Unknown fact: {fact_id}")
            return tuple(item.copy_for_read() for item in rows)

    versions = history
    list_versions = history

    def get_as_of(
        self,
        fact_id: str,
        cutoff: datetime | None = None,
        *,
        as_of: datetime | None = None,
    ) -> TemporalFactRevision:
        """Return one fact's revision visible at a historical cutoff."""

        if cutoff is None:
            cutoff = as_of
        if cutoff is None:
            raise ValueError("as_of cutoff is required")
        cutoff_utc = _utc(cutoff, "as_of")
        key = str(fact_id or "").strip()
        with self._lock:
            rows = self._rows.get(key)
            if not rows:
                raise FactNotFoundError(f"Unknown fact: {fact_id}")
            candidates = [item for item in rows if item.observed_time <= cutoff_utc]
            if not candidates:
                raise FactNotFoundError(f"Fact is not visible at requested cutoff: {fact_id}")
            selected = max(candidates, key=lambda item: (item.observed_time, item.revision))
            return _project_quality_at_cutoff(selected, cutoff_utc).copy_for_read()

    get_at = get_as_of
    version_at = get_as_of

    def list(
        self,
        *,
        fact_type: str | None = None,
        scope: ScopeRef | None = None,
        quality_state: QualityState | str | None = None,
    ) -> tuple[TemporalFactRevision, ...]:
        quality = QualityState(quality_state) if quality_state is not None else None
        with self._lock:
            rows = [revisions[-1] for revisions in self._rows.values()]
            selected = [
                item
                for item in rows
                if (fact_type is None or item.fact_type == fact_type)
                and _scope_matches(item.scope, scope)
                and (quality is None or item.quality_state == quality)
            ]
            selected.sort(key=lambda item: (item.fact_type, item.natural_key, item.fact_id))
            return tuple(item.copy_for_read() for item in selected)

    def as_of(
        self,
        cutoff: datetime | None = None,
        *,
        as_of: datetime | None = None,
        scope: ScopeRef | None = None,
        fact_type: str | None = None,
        natural_key: str | None = None,
        quality_states: Iterable[QualityState | str] | None = None,
        event_start: datetime | None = None,
        event_end: datetime | None = None,
        include_stale: bool = True,
    ) -> tuple[TemporalFactRevision, ...]:
        """Return the newest revision known at ``cutoff`` for each identity.

        ``observed_time`` defines historical visibility.  The business event
        and effective times are filters only; this preserves the distinction
        between *when an event happened* and *when KJDS knew about it*.
        """

        if cutoff is None:
            cutoff = as_of
        if cutoff is None:
            raise ValueError("as_of cutoff is required")
        as_of = _utc(cutoff, "as_of")
        allowed = {QualityState(value) for value in quality_states} if quality_states is not None else None
        start = _utc(event_start, "event_start") if event_start is not None else None
        end = _utc(event_end, "event_end") if event_end is not None else None
        if start is not None and end is not None and end < start:
            raise ValueError("event_end must not precede event_start")
        with self._lock:
            visible: list[TemporalFactRevision] = []
            for revisions in self._rows.values():
                candidates = [item for item in revisions if item.observed_time <= as_of]
                if not candidates:
                    continue
                item = max(candidates, key=lambda value: (value.observed_time, value.revision))
                if fact_type is not None and item.fact_type != fact_type:
                    continue
                if natural_key is not None and item.natural_key != natural_key:
                    continue
                if not _scope_matches(item.scope, scope):
                    continue
                # Freshness is a property of the *read cutoff*, rather than a
                # mutation of the stored revision.  Project it before applying
                # quality filters so ``include_stale=False`` also excludes a
                # VALID revision whose freshness window expired at ``as_of``.
                projected = _project_quality_at_cutoff(item, as_of)
                if allowed is not None and projected.quality_state not in allowed:
                    continue
                if not include_stale and projected.quality_state == QualityState.STALE:
                    continue
                if start is not None and item.event_time < start:
                    continue
                if end is not None and item.event_time >= end:
                    continue
                visible.append(projected)
            visible.sort(key=lambda item: (item.fact_type, item.natural_key, item.fact_id))
            return tuple(item.copy_for_read() for item in visible)

    list_as_of = as_of

    def query_as_of(
        self,
        cutoff: datetime | None = None,
        *,
        as_of: datetime | None = None,
        **filters: Any,
    ) -> TemporalFactQueryResult:
        if cutoff is None:
            cutoff = as_of
        if cutoff is None:
            raise ValueError("as_of cutoff is required")
        items = self.as_of(cutoff, **filters)
        quality = QualityState.VALID
        if not items:
            quality = QualityState.NO_DATA
        elif any(item.quality_state == QualityState.BLOCKED for item in items):
            quality = QualityState.BLOCKED
        elif any(item.quality_state == QualityState.UNKNOWN_OUTCOME for item in items):
            quality = QualityState.UNKNOWN_OUTCOME
        elif any(item.quality_state == QualityState.STALE for item in items):
            quality = QualityState.STALE
        elif any(item.quality_state == QualityState.PARTIAL for item in items):
            quality = QualityState.PARTIAL
        return TemporalFactQueryResult(as_of=cutoff, items=items, quality_state=quality)

    query = query_as_of
    replay = query_as_of

    def lineage(self, fact_id: str, *, revision: int | None = None) -> tuple[LineageRef, ...]:
        return self.get(fact_id, revision=revision).lineage

    def lineage_edges(self, fact_id: str, *, revision: int | None = None) -> tuple[LineageEdge, ...]:
        fact = self.get(fact_id, revision=revision)
        with self._lock:
            return tuple(
                edge.model_copy(deep=True)
                for edge in self._lineage_edges.values()
                # Lineage edges point from the upstream source to the fact
                # revision.  Filtering on ``from_id`` silently returned an
                # empty graph for every valid fact and broke drill-down
                # transparency; the destination is the canonical revision.
                if edge.to_id == fact.revision_id
            )

    def _index_lineage(self, fact: TemporalFactRevision) -> None:
        for ref in fact.lineage:
            key = ("lineage_ref", ref.id, "fact_revision", fact.revision_id, ref.relationship)
            self._lineage_edges[key] = LineageEdge(
                id=lineage_edge_id(
                    revision_id=fact.revision_id,
                    from_type=ref.kind,
                    from_id=ref.id,
                    relationship=ref.relationship,
                ),
                from_type=ref.kind,
                from_id=ref.id,
                from_sha256=ref.sha256,
                to_type="fact_revision",
                to_id=fact.revision_id,
                relationship=ref.relationship,
                created_by=fact.created_by,
                recorded_at=fact.observed_time,
                metadata={"fact_id": fact.fact_id, "revision": fact.revision},
            )

    def snapshot(self) -> tuple[TemporalFactRevision, ...]:
        """Return current revisions in stable order for deterministic replay."""

        return self.list()

    def history_snapshot(self) -> tuple[TemporalFactRevision, ...]:
        """Return every revision in stable identity/revision order."""

        with self._lock:
            rows = [item for revisions in self._rows.values() for item in revisions]
            rows.sort(key=lambda item: (item.fact_type, item.natural_key, item.fact_id, item.revision))
            return tuple(item.copy_for_read() for item in rows)


# Names used by early design notes and downstream adapters.
TemporalFact = TemporalFactRevision
FactRevision = TemporalFactRevision
TemporalStore = TemporalFactStore


__all__ = [
    "FactNotFoundError",
    "FactQualityState",
    "FactRevision",
    "LineageEdge",
    "LineageRef",
    "QualityState",
    "RevisionConflictError",
    "TemporalFact",
    "TemporalFactError",
    "TemporalFactQueryResult",
    "TemporalFactRevision",
    "TemporalFactStore",
    "TemporalFactTimes",
    "TemporalStore",
    "canonical_json",
    "content_sha256",
    "lineage_edge_id",
]
