"""Provider-neutral contracts for the KJDS data fabric and analytics boundary.

These models intentionally describe transport and validation only. They do not
create a second Fact, Evidence, Profit or execution authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

DataStatus = Literal[
    "ready",
    "partial",
    "stale",
    "conflicted",
    "blocked",
    "no_data",
    "unknown_outcome",
]

# ``DataStatus`` is the transport vocabulary (lower-case for compatibility
# with the original API).  Row-level facts use an upper-case quality state so
# that quality can never be confused with the value ``0`` carried by a row.
QualityStateValue = Literal[
    "NO_DATA",
    "PARTIAL",
    "STALE",
    "BLOCKED",
    "UNKNOWN_OUTCOME",
    "VALID",
]
FreshnessState = Literal["fresh", "stale", "unknown"]

# The names are deliberately stable.  Adapters may use the aliases accepted
# by ``normalize_stage`` below, but persisted lineage exports use these names.
LineageStage = Literal[
    "metric",
    "data_product",
    "canonical_fact",
    "raw_fact",
    "raw_file",
    "platform_response",
    "hash",
    "import_task",
    "rule_version",
    "agent_decision",
    "action",
    "external_readback",
]

LINEAGE_STAGE_ORDER: tuple[str, ...] = (
    "metric",
    "data_product",
    "canonical_fact",
    "raw_fact",
    "raw_file",
    "platform_response",
    "hash",
    "import_task",
    "rule_version",
    "agent_decision",
    "action",
    "external_readback",
)

DRILLDOWN_LEVEL_ORDER: tuple[str, ...] = (
    "entity",
    "store",
    "warehouse",
    "sku",
    "transaction",
    "evidence",
)


def _normalise_ids(value: Any, field: str) -> tuple[str, ...]:
    """Normalize one-or-many scope identifiers without accepting blanks."""

    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (tuple, list, set, frozenset)):
        raise ValueError(f"{field} must be a sequence of identifiers")
    result = tuple(str(item).strip() for item in value)
    if any(not item for item in result):
        raise ValueError(f"{field} cannot contain blank identifiers")
    return result


def _normalise_utc(value: Any, field: str) -> datetime:
    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 datetime") from exc
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _valid_sha256(value: str, field: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return normalized


class _Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )


class ScopeRef(_Contract):
    tenant_id: str = Field(min_length=1, max_length=160)
    entity_id: str = Field(min_length=1, max_length=160)
    store_ids: tuple[str, ...] = ()
    warehouse_ids: tuple[str, ...] = ()
    # SKU is a first-class scope dimension.  It is optional for legacy
    # account/entity facts that are intentionally SKU-agnostic.  Empty values
    # are omitted from serialized legacy envelopes by ``exclude_if``.
    sku_ids: tuple[str, ...] = Field(
        default=(),
        validation_alias=AliasChoices("sku_ids", "sku_refs", "skus", "sku", "sku_id"),
        exclude_if=lambda value: not value,
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_scope_inputs(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        for name in ("store_ids", "warehouse_ids", "sku_ids"):
            # ``AliasChoices`` handles the common singular names, while this
            # keeps a mapping assembled by an older adapter permissive.
            aliases = {
                "store_ids": ("store_ids", "store_refs", "stores", "store", "store_id"),
                "warehouse_ids": (
                    "warehouse_ids",
                    "warehouse_refs",
                    "warehouses",
                    "warehouse",
                    "warehouse_id",
                ),
                "sku_ids": ("sku_ids", "sku_refs", "skus", "sku", "sku_id"),
            }[name]
            raw = next((data[key] for key in aliases if key in data), None)
            if raw is not None:
                data[name] = _normalise_ids(raw, name)
            for alias in aliases:
                if alias != name:
                    data.pop(alias, None)
        for name in ("tenant_id", "entity_id"):
            if data.get(name) is not None:
                data[name] = str(data[name]).strip()
        return data

    @model_validator(mode="after")
    def unique_scope_ids(self) -> ScopeRef:
        for values in (self.store_ids, self.warehouse_ids, self.sku_ids):
            if len(values) != len(set(values)):
                raise ValueError("scope identifiers must be unique")
        if not self.tenant_id or not self.entity_id:
            raise ValueError("tenant_id and entity_id are required")
        return self

    @property
    def tenant(self) -> str:
        return self.tenant_id

    @property
    def entity(self) -> str:
        return self.entity_id

    @property
    def store(self) -> str | None:
        return self.store_ids[0] if len(self.store_ids) == 1 else None

    @property
    def warehouse(self) -> str | None:
        return self.warehouse_ids[0] if len(self.warehouse_ids) == 1 else None

    @property
    def sku(self) -> str | None:
        return self.sku_ids[0] if len(self.sku_ids) == 1 else None


def canonical_scope_key(
    scope: ScopeRef,
    *,
    sku_ids: tuple[str, ...] | list[str] | None = None,
) -> str:
    """Build the stable permission key used by row-level contracts.

    Existing four-part keys remain byte-for-byte identical when no SKU scope
    is present.  SKU-scoped facts append one deterministic fifth component,
    which prevents a SKU row from being mistaken for an entity-wide row.
    """

    selected_skus = tuple(scope.sku_ids if sku_ids is None else _normalise_ids(sku_ids, "sku_ids"))
    parts = (
        scope.tenant_id,
        scope.entity_id,
        ",".join(scope.store_ids),
        ",".join(scope.warehouse_ids),
    )
    if selected_skus:
        return ":".join((*parts, ",".join(selected_skus)))
    return ":".join(parts)


class EvidenceRef(_Contract):
    kind: Literal["evidence", "fact", "decision", "action"]
    id: str = Field(min_length=1, max_length=200)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)


class LineageRefContract(_Contract):
    """Provider-neutral lineage reference used by row contracts.

    ``temporal_fact_store.LineageRef`` remains the historical runtime type;
    this contract mirrors its wire shape so data-fabric models do not import
    the temporal implementation and create a dependency cycle.
    """

    kind: str = Field(min_length=1, max_length=120)
    id: str = Field(min_length=1, max_length=300)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    relationship: str = Field(default="supports", min_length=1, max_length=120)
    version: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="before")
    @classmethod
    def normalize_lineage_ref(cls, values: Any) -> Any:
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
    def validate_lineage_hash(self) -> LineageRefContract:
        if self.sha256 is not None:
            _valid_sha256(self.sha256, "lineage.sha256")
        return self


class LineageNode(_Contract):
    """One node in the auditable metric-to-source execution chain."""

    stage: str = Field(min_length=1, max_length=80)
    id: str = Field(min_length=1, max_length=300)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)
    version: str | None = Field(default=None, min_length=1, max_length=160)
    observed_time: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_node(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        if "stage" not in data:
            data["stage"] = data.get("type") or data.get("kind")
        if "sha256" not in data and data.get("hash") is not None:
            data["sha256"] = data.pop("hash")
        stage = str(data.get("stage") or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "dataset": "data_product",
            "data_product_descriptor": "data_product",
            "projection": "metric",
            "metric_result": "metric",
            "fact": "canonical_fact",
            "fact_revision": "canonical_fact",
            "canonical": "canonical_fact",
            "raw": "raw_fact",
            "raw_record": "raw_fact",
            "evidence": "raw_file",
            "file": "raw_file",
            "response": "platform_response",
            "platform": "platform_response",
            "import": "import_task",
            "rule": "rule_version",
            "decision": "agent_decision",
            "readback": "external_readback",
        }
        data["stage"] = aliases.get(stage, stage)
        if data.get("observed_time") is not None:
            data["observed_time"] = _normalise_utc(data["observed_time"], "lineage.observed_time")
        return data

    @model_validator(mode="after")
    def validate_node(self) -> LineageNode:
        if self.stage not in LINEAGE_STAGE_ORDER:
            raise ValueError(f"unsupported lineage stage: {self.stage}")
        if self.sha256 is not None:
            _valid_sha256(self.sha256, "lineage.sha256")
        return self


class LineageEdgeContract(_Contract):
    """Provider-neutral wire representation of a typed lineage edge."""

    from_type: str = Field(min_length=1, max_length=120)
    from_id: str = Field(min_length=1, max_length=300)
    to_type: str = Field(min_length=1, max_length=120)
    to_id: str = Field(min_length=1, max_length=300)
    relationship: str = Field(min_length=1, max_length=120)
    from_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    to_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def normalize_edge(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        if "from_type" not in data and data.get("from_stage") is not None:
            data["from_type"] = data["from_stage"]
        if "to_type" not in data and data.get("to_stage") is not None:
            data["to_type"] = data["to_stage"]
        for name in ("from_type", "from_id", "to_type", "to_id", "relationship"):
            if data.get(name) is not None:
                data[name] = str(data[name]).strip().lower() if name.endswith("type") else str(data[name]).strip()
        return data

    @model_validator(mode="after")
    def validate_edge(self) -> LineageEdgeContract:
        if self.from_type == self.to_type and self.from_id == self.to_id:
            raise ValueError("lineage edge cannot point to itself")
        if self.from_sha256 is not None:
            _valid_sha256(self.from_sha256, "lineage.from_sha256")
        if self.to_sha256 is not None:
            _valid_sha256(self.to_sha256, "lineage.to_sha256")
        return self


class LineageChain(_Contract):
    """Ordered lineage chain with explicit completeness diagnostics.

    The chain is a read-only declaration.  It does not assert that an
    artifact exists; callers must bind each node to the corresponding
    Evidence/Fact/decision/action authority before admitting production use.
    """

    nodes: tuple[LineageNode, ...] = ()
    edges: tuple[LineageEdgeContract, ...] = ()
    required_stages: tuple[str, ...] = LINEAGE_STAGE_ORDER

    @model_validator(mode="before")
    @classmethod
    def normalize_chain(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        for name in ("nodes", "edges", "required_stages"):
            if data.get(name) is not None and isinstance(data[name], list):
                data[name] = tuple(data[name])
        return data

    @model_validator(mode="after")
    def validate_chain(self) -> LineageChain:
        if not self.required_stages:
            raise ValueError("lineage chain requires at least one required stage")
        normalized_required = tuple(str(stage).strip().lower() for stage in self.required_stages)
        if len(normalized_required) != len(set(normalized_required)):
            raise ValueError("lineage required stages must be unique")
        if any(stage not in LINEAGE_STAGE_ORDER for stage in normalized_required):
            raise ValueError("lineage required stage is unsupported")
        object.__setattr__(self, "required_stages", normalized_required)
        keys = [(node.stage, node.id) for node in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("lineage nodes must be unique")
        edge_keys = [
            (edge.from_type, edge.from_id, edge.to_type, edge.to_id, edge.relationship)
            for edge in self.edges
        ]
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("lineage edges must be unique")
        return self

    @property
    def present_stages(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(node.stage for node in self.nodes))

    @property
    def missing_stages(self) -> tuple[str, ...]:
        present = set(self.present_stages)
        return tuple(stage for stage in self.required_stages if stage not in present)

    @property
    def complete(self) -> bool:
        return not self.missing_stages

    @property
    def present_stage_count(self) -> int:
        return len(self.present_stages)

    @property
    def coverage(self) -> float:
        """Fraction of required stages represented by the chain."""

        return self.present_stage_count / max(1, len(self.required_stages))

    def coverage_ratio(self) -> float:
        """Backward-friendly method spelling for callers using a ratio name."""

        return self.coverage


class DrilldownNode(_Contract):
    """One level in the six-level read-only business drill-down."""

    level: str = Field(min_length=1, max_length=60)
    id: str = Field(min_length=1, max_length=300)
    parent_id: str | None = Field(default=None, min_length=1, max_length=300)
    label: str | None = Field(default=None, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_level(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        if "level" not in data:
            data["level"] = data.get("kind") or data.get("type")
        aliases = {
            "group": "entity",
            "主体": "entity",
            "店铺": "store",
            "仓库": "warehouse",
            "variant": "sku",
            "变体": "sku",
            "order": "transaction",
            "fee": "transaction",
            "advertising": "transaction",
            "广告": "transaction",
            "raw_evidence": "evidence",
            "原始证据": "evidence",
        }
        level = str(data.get("level") or "").strip().lower().replace("-", "_")
        data["level"] = aliases.get(level, level)
        return data

    @model_validator(mode="after")
    def validate_level(self) -> DrilldownNode:
        if self.level not in DRILLDOWN_LEVEL_ORDER:
            raise ValueError(f"unsupported drilldown level: {self.level}")
        return self


class DrilldownPath(_Contract):
    """A deterministic, scope-preserving six-level hierarchy."""

    nodes: tuple[DrilldownNode, ...] = ()
    required_levels: tuple[str, ...] = DRILLDOWN_LEVEL_ORDER

    @model_validator(mode="before")
    @classmethod
    def normalize_path(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        if isinstance(data.get("nodes"), list):
            data["nodes"] = tuple(data["nodes"])
        if isinstance(data.get("required_levels"), list):
            data["required_levels"] = tuple(data["required_levels"])
        return data

    @model_validator(mode="after")
    def validate_path(self) -> DrilldownPath:
        levels = tuple(str(level).strip().lower() for level in self.required_levels)
        if not levels or len(levels) != len(set(levels)):
            raise ValueError("drilldown required levels must be unique and non-empty")
        if any(level not in DRILLDOWN_LEVEL_ORDER for level in levels):
            raise ValueError("drilldown required level is unsupported")
        object.__setattr__(self, "required_levels", levels)
        actual = [node.level for node in self.nodes]
        if len(actual) != len(set(actual)):
            raise ValueError("drilldown levels must occur at most once")
        positions = [DRILLDOWN_LEVEL_ORDER.index(level) for level in actual]
        if positions != sorted(positions):
            raise ValueError("drilldown levels must be ordered")
        return self

    @property
    def missing_levels(self) -> tuple[str, ...]:
        present = set(node.level for node in self.nodes)
        return tuple(level for level in self.required_levels if level not in present)

    @property
    def complete(self) -> bool:
        return not self.missing_levels


class FactDataContract(_Contract):
    """Strict row-level provenance contract for canonical data products.

    ``DataEnvelope.data`` remains an intentionally generic legacy transport.
    New producers can validate each row with this model (or place validated
    rows in ``DataEnvelope.records``) to guarantee that a value is never
    detached from its tenant, SKU, source, time, quality and permission
    context.  Keeping this as a separate strict model lets historical
    envelopes replay without fabricating provenance for old rows.
    """

    tenant: str = Field(
        min_length=1,
        max_length=160,
        validation_alias=AliasChoices("tenant", "tenant_id"),
    )
    entity: str = Field(
        min_length=1,
        max_length=160,
        validation_alias=AliasChoices("entity", "entity_id"),
    )
    store: str = Field(
        min_length=1,
        max_length=160,
        validation_alias=AliasChoices("store", "store_id"),
    )
    warehouse: str = Field(
        min_length=1,
        max_length=160,
        validation_alias=AliasChoices("warehouse", "warehouse_id"),
    )
    sku: str = Field(
        min_length=1,
        max_length=240,
        validation_alias=AliasChoices("sku", "sku_id", "seller_sku"),
    )
    source_system: str = Field(min_length=1, max_length=160)
    source_record_id: str = Field(
        min_length=1,
        max_length=300,
        validation_alias=AliasChoices("source_record_id", "source_ref"),
    )
    source_version: str = Field(default="1", min_length=1, max_length=120)
    event_time: datetime
    observed_time: datetime
    effective_time: datetime | None = None
    settled_time: datetime | None = None
    causation_id: str = Field(min_length=1, max_length=300)
    correlation_id: str = Field(min_length=1, max_length=300)
    idempotency_key: str = Field(min_length=1, max_length=300)
    quality_state: QualityStateValue = Field(
        validation_alias=AliasChoices("quality_state", "quality_status"),
    )
    freshness: FreshnessState
    fresh_until: datetime | None = None
    lineage_refs: tuple[LineageRefContract, ...] = Field(
        validation_alias=AliasChoices("lineage_refs", "lineage"),
    )
    permission_scope: str = Field(min_length=1, max_length=600)
    payload: dict[str, Any] = Field(default_factory=dict)
    fact_id: str | None = Field(default=None, min_length=1, max_length=200)
    revision_id: str | None = Field(default=None, min_length=1, max_length=200)
    revision: int | None = Field(default=None, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_fact_row(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        # Support a nested scope from TemporalFactRevision and the compact
        # names used by DataEnvelope adapters.
        raw_scope = data.get("scope")
        if isinstance(raw_scope, ScopeRef):
            raw_scope = raw_scope.model_dump(mode="python")
        if isinstance(raw_scope, Mapping):
            data.setdefault("tenant", raw_scope.get("tenant_id"))
            data.setdefault("entity", raw_scope.get("entity_id"))
            data.setdefault("store", raw_scope.get("store_id") or raw_scope.get("store"))
            data.setdefault("warehouse", raw_scope.get("warehouse_id") or raw_scope.get("warehouse"))
            data.setdefault("sku", raw_scope.get("sku_id") or raw_scope.get("sku"))
            for field_name, scope_key_name in (
                ("store", "store_ids"),
                ("warehouse", "warehouse_ids"),
                ("sku", "sku_ids"),
            ):
                if data.get(field_name) is None:
                    values_for_field = raw_scope.get(scope_key_name) or ()
                    if isinstance(values_for_field, (list, tuple)) and len(values_for_field) == 1:
                        data[field_name] = values_for_field[0]
        if "lineage_refs" not in data and "lineage" in data:
            data["lineage_refs"] = data["lineage"]
        if "effective_time" not in data and data.get("event_time") is not None:
            data["effective_time"] = data["event_time"]
        if data.get("payload") is None:
            data["payload"] = {}
        for name in ("event_time", "observed_time", "effective_time", "settled_time", "fresh_until"):
            if data.get(name) is not None:
                data[name] = _normalise_utc(data[name], name)
        if data.get("quality_state") is not None:
            data["quality_state"] = str(data["quality_state"]).strip().upper().replace("-", "_")
        if data.get("freshness") is None and data.get("quality_state") is not None:
            state = str(data["quality_state"]).upper()
            data["freshness"] = "fresh" if state == "VALID" else "stale" if state == "STALE" else "unknown"
        if data.get("metadata") is None:
            data["metadata"] = {}
        return data

    @model_validator(mode="after")
    def validate_fact_row(self) -> FactDataContract:
        if self.event_time > self.observed_time:
            raise ValueError("event_time cannot be after observed_time")
        if self.effective_time is not None and self.effective_time > self.observed_time:
            # Future-effective rules are valid in the temporal kernel, so this
            # is intentionally not rejected.  It remains explicit in the row.
            pass
        if self.settled_time is not None and self.settled_time < self.event_time:
            raise ValueError("settled_time cannot precede event_time")
        expected_freshness = {
            "VALID": "fresh",
            "STALE": "stale",
            "NO_DATA": "unknown",
            "PARTIAL": "unknown",
            "BLOCKED": "unknown",
            "UNKNOWN_OUTCOME": "unknown",
        }[self.quality_state]
        if self.freshness != expected_freshness:
            raise ValueError("quality_state and freshness disagree")
        if self.quality_state in {"NO_DATA", "BLOCKED", "UNKNOWN_OUTCOME"} and self.payload:
            raise ValueError(f"{self.quality_state} row cannot contain payload values")
        if not self.lineage_refs:
            raise ValueError("lineage_refs are required for a complete fact row")
        expected_scope = canonical_scope_key(
            ScopeRef(
                tenant_id=self.tenant,
                entity_id=self.entity,
                store_ids=(self.store,),
                warehouse_ids=(self.warehouse,),
                sku_ids=(self.sku,),
            )
        )
        if self.permission_scope != expected_scope:
            raise ValueError("permission_scope does not match row scope")
        return self

    @property
    def quality_status(self) -> QualityStateValue:
        return self.quality_state

    @classmethod
    def from_temporal_fact(cls, fact: Any, *, payload: Mapping[str, Any] | None = None) -> FactDataContract:
        """Adapt a TemporalFactRevision without importing that implementation."""

        scope = getattr(fact, "scope", None)
        if not isinstance(scope, ScopeRef):
            scope = ScopeRef.model_validate(scope)
        sku = getattr(fact, "sku", None) or scope.sku
        if not sku:
            raw_payload = getattr(fact, "payload", {}) or {}
            sku = raw_payload.get("sku") or raw_payload.get("sku_id") or raw_payload.get("seller_sku")
        if not sku or not scope.store or not scope.warehouse:
            raise ValueError("temporal fact lacks store, warehouse or sku for strict row projection")
        quality_state = getattr(getattr(fact, "quality_state", None), "value", None) or str(
            getattr(fact, "quality_state", "VALID")
        )
        freshness = getattr(fact, "freshness", None)
        if freshness is None:
            freshness = "fresh" if quality_state == "VALID" else "stale" if quality_state == "STALE" else "unknown"
        return cls(
            tenant=scope.tenant_id,
            entity=scope.entity_id,
            store=scope.store,
            warehouse=scope.warehouse,
            sku=str(sku),
            source_system=getattr(fact, "source_system", "unknown"),
            source_record_id=getattr(fact, "source_record_id", None),
            source_version=getattr(fact, "source_version", "1"),
            event_time=fact.event_time,
            observed_time=fact.observed_time,
            effective_time=getattr(fact, "effective_time", None),
            settled_time=getattr(fact, "settled_time", None),
            causation_id=getattr(fact, "causation_id", None) or getattr(fact, "fact_id", "unknown"),
            correlation_id=getattr(fact, "correlation_id", None) or getattr(fact, "fact_id", "unknown"),
            idempotency_key=getattr(fact, "idempotency_key", None) or getattr(fact, "revision_id", "unknown"),
            quality_state=quality_state,
            freshness=freshness,
            fresh_until=getattr(fact, "fresh_until", None),
            lineage_refs=[
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in (getattr(fact, "lineage", ()) or ())
            ],
            permission_scope=canonical_scope_key(
                ScopeRef(
                    tenant_id=scope.tenant_id,
                    entity_id=scope.entity_id,
                    store_ids=(scope.store,),
                    warehouse_ids=(scope.warehouse,),
                    sku_ids=(str(sku),),
                )
            ),
            payload=dict(payload if payload is not None else getattr(fact, "payload", {}) or {}),
            fact_id=getattr(fact, "fact_id", None),
            revision_id=getattr(fact, "revision_id", None),
            revision=getattr(fact, "revision", None),
            metadata=dict(getattr(fact, "metadata", {}) or {}),
        )


# Descriptive aliases keep the contract discoverable for adapters that call a
# row a ``DataRecord`` or a ``FactRow``.  They intentionally point to one
# implementation so validation semantics cannot drift between names.
DataRecordContract = FactDataContract
FactRowContract = FactDataContract
CanonicalFactContract = FactDataContract


class QualitySummary(_Contract):
    completeness: float = Field(ge=0, le=1)
    freshness: Literal["fresh", "stale", "unknown"]
    excluded_count: int = Field(default=0, ge=0)
    reasons: tuple[str, ...] = ()


class DataEnvelope(_Contract):
    dataset: str = Field(min_length=1, max_length=200)
    scope: ScopeRef
    as_of: datetime
    fresh_until: datetime | None = None
    status: DataStatus
    data: tuple[dict[str, Any], ...] = ()
    quality: QualitySummary
    lineage: tuple[EvidenceRef, ...] = ()
    # ``data`` stays an untyped tuple for wire compatibility.  Producers that
    # need the complete row contract attach validated records here; empty
    # legacy envelopes do not suddenly gain fabricated metadata.
    records: tuple[FactDataContract, ...] = Field(
        default=(),
        validation_alias=AliasChoices("records", "fact_records", "row_contracts"),
        exclude_if=lambda value: not value,
    )
    lineage_chain: LineageChain | None = Field(default=None, exclude_if=lambda value: value is None)
    drilldown_path: DrilldownPath | None = Field(default=None, exclude_if=lambda value: value is None)
    schema_version: str = Field(min_length=1, max_length=80)
    authority_hash: str = Field(min_length=1, max_length=200)
    next_cursor: str | None = None

    @model_validator(mode="after")
    def validate_state(self) -> DataEnvelope:
        if self.fresh_until is not None and self.fresh_until < self.as_of:
            raise ValueError("fresh_until must not precede as_of")
        if self.status in {"no_data", "blocked", "unknown_outcome"} and self.data:
            raise ValueError(f"{self.status} envelope cannot contain data rows")
        if self.status == "ready" and self.quality.freshness != "fresh":
            raise ValueError("ready envelope requires fresh quality")
        if self.quality.excluded_count and self.status == "ready":
            raise ValueError("excluded rows require partial or a non-ready status")
        if self.records:
            if self.data and len(self.records) != len(self.data):
                raise ValueError("records and data row counts differ")
            if self.status in {"no_data", "blocked", "unknown_outcome"}:
                raise ValueError(f"{self.status} envelope cannot contain validated records")
            for record in self.records:
                if record.tenant != self.scope.tenant_id or record.entity != self.scope.entity_id:
                    raise ValueError("record scope is outside envelope scope")
                if self.scope.store_ids and record.store not in self.scope.store_ids:
                    raise ValueError("record store is outside envelope scope")
                if self.scope.warehouse_ids and record.warehouse not in self.scope.warehouse_ids:
                    raise ValueError("record warehouse is outside envelope scope")
                if self.scope.sku_ids and record.sku not in self.scope.sku_ids:
                    raise ValueError("record SKU is outside envelope scope")
            if self.status == "ready" and any(record.quality_state != "VALID" for record in self.records):
                raise ValueError("ready envelope cannot contain non-VALID records")
        return self

    def validate_records(self, *, require_complete: bool = False) -> tuple[FactDataContract, ...]:
        """Validate row provenance on demand while preserving old envelopes.

        Legacy producers may have only supplied ``data``.  In that case this
        method returns an empty tuple unless ``require_complete`` is requested,
        where it fails closed instead of guessing source or permission fields.
        """

        if self.records:
            return self.records
        if not self.data:
            return ()
        parsed: list[FactDataContract] = []
        for index, row in enumerate(self.data):
            context = row.get("provenance") or row.get("fact_context") or row.get("__fact_context__")
            if context is None:
                if require_complete:
                    raise ValueError(f"data row {index} has no complete provenance context")
                continue
            try:
                parsed.append(FactDataContract.model_validate(context))
            except Exception as exc:
                if require_complete:
                    raise ValueError(f"data row {index} has invalid provenance context") from exc
        if require_complete and len(parsed) != len(self.data):
            raise ValueError("not every data row has a complete provenance context")
        return tuple(parsed)

    def lineage_audit(self) -> dict[str, Any]:
        """Return explicit completeness diagnostics for lineage and drilldown."""

        chain = self.lineage_chain
        path = self.drilldown_path
        return {
            "lineage_complete": bool(chain and chain.complete),
            "lineage_missing_stages": list(chain.missing_stages) if chain else list(LINEAGE_STAGE_ORDER),
            "lineage_coverage": chain.coverage_ratio() if chain else 0.0,
            "drilldown_complete": bool(path and path.complete),
            "drilldown_missing_levels": list(path.missing_levels) if path else list(DRILLDOWN_LEVEL_ORDER),
            "record_contract_complete": bool(self.records) and len(self.records) == len(self.data),
        }


class DataProductDescriptor(_Contract):
    dataset_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    owner: str = Field(min_length=1, max_length=160)
    grain: str = Field(min_length=1, max_length=160)
    source_refs: tuple[str, ...] = ()
    allowed_scopes: tuple[str, ...] = ()
    allowed_purposes: tuple[str, ...] = ()
    refresh_sla_seconds: int | None = Field(default=None, ge=1)
    quality_threshold: float = Field(ge=0, le=1)
    rebuild_method: str = Field(min_length=1, max_length=500)
    # Registry status and authority are part of the descriptor so a
    # contract-only product cannot be mistaken for a verified production
    # source by downstream planners.
    status: Literal["contract_only", "verified", "deprecated"] = "contract_only"
    authority: str = Field(default="unverified", min_length=1, max_length=160)


class MetricDefinition(_Contract):
    metric_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    formula: str = Field(min_length=1, max_length=4000)
    fact_grain: str = Field(min_length=1, max_length=160)
    dimensions: tuple[str, ...] = ()
    aggregation: Literal["sum", "count", "distinct", "average", "median", "ratio", "weighted"]
    currency_rule: str = Field(min_length=1, max_length=500)
    evidence_required: bool = True


class PeriodRef(_Contract):
    period_type: Literal["day", "week", "month", "quarter", "year", "ytd", "rolling", "custom"]
    start_at: datetime
    end_at: datetime
    timezone: str = Field(min_length=1, max_length=80)
    currency: str = Field(min_length=3, max_length=3)
    as_of: datetime
    partial: bool = False
    closed: bool = False

    @model_validator(mode="after")
    def valid_window(self) -> PeriodRef:
        if self.end_at <= self.start_at:
            raise ValueError("period end_at must be after start_at")
        if self.as_of < self.start_at:
            raise ValueError("period as_of cannot precede period start")
        return self


class AnalysisRecipe(_Contract):
    recipe_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    scope: ScopeRef
    period: PeriodRef
    dimensions: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    filters: tuple[tuple[str, str, str], ...] = ()
    compare_with: tuple[Literal["previous_period", "same_period_last_year", "rolling"] , ...] = ()

    @model_validator(mode="after")
    def unique_query_parts(self) -> AnalysisRecipe:
        if not self.metrics:
            raise ValueError("analysis recipe requires at least one metric")
        if len(self.dimensions) != len(set(self.dimensions)):
            raise ValueError("analysis dimensions must be unique")
        if len(self.metrics) != len(set(self.metrics)):
            raise ValueError("analysis metrics must be unique")
        return self


class ActionEnvelope(_Contract):
    command_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=240)
    scope: ScopeRef
    input_snapshot_id: str = Field(min_length=1, max_length=200)
    mode: Literal["propose", "execute"] = "propose"
    permit_ref: str | None = None
    budget_reservation_ref: str | None = None
    expected_readback: str | None = None
    rollback_ref: str | None = None

    @model_validator(mode="after")
    def require_execution_controls(self) -> ActionEnvelope:
        if self.mode == "execute":
            missing = [
                name
                for name, value in {
                    "permit_ref": self.permit_ref,
                    "budget_reservation_ref": self.budget_reservation_ref,
                    "expected_readback": self.expected_readback,
                    "rollback_ref": self.rollback_ref,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError("execute ActionEnvelope missing: " + ", ".join(missing))
        return self


__all__ = [
    "ActionEnvelope",
    "AnalysisRecipe",
    "CanonicalFactContract",
    "DataEnvelope",
    "DataProductDescriptor",
    "DataRecordContract",
    "DataStatus",
    "DRILLDOWN_LEVEL_ORDER",
    "DrilldownNode",
    "DrilldownPath",
    "EvidenceRef",
    "FactDataContract",
    "FactRowContract",
    "FreshnessState",
    "LINEAGE_STAGE_ORDER",
    "LineageChain",
    "LineageEdgeContract",
    "LineageNode",
    "LineageRefContract",
    "LineageStage",
    "MetricDefinition",
    "PeriodRef",
    "QualityStateValue",
    "QualitySummary",
    "ScopeRef",
    "canonical_scope_key",
]
