"""Transparent read envelopes for data products, facts and decisions.

``DataEnvelope`` is the stable transport contract already used by the data
fabric.  ``TransparencyEnvelope`` adds the explanation and lineage material a
human or Agent needs to audit a result: quality dimensions, source counts,
formula/rule versions, watermarks, included/excluded rows and typed lineage
edges.  It remains a read model; constructing one never grants write
authority and never changes a Fact.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from .data_fabric_contracts import (
    DRILLDOWN_LEVEL_ORDER,
    LINEAGE_STAGE_ORDER,
    DataEnvelope,
    DrilldownPath,
    FactDataContract,
    LineageChain,
    PeriodRef,
    QualitySummary,
    ScopeRef,
)
from .temporal_fact_store import (
    LineageEdge,
    LineageRef,
    QualityState,
    TemporalFactQueryResult,
    _json_safe,
    _utc,
    content_sha256,
)

DataEnvelopeStatus = Literal[
    "ready",
    "partial",
    "stale",
    "conflicted",
    "blocked",
    "no_data",
    "unknown_outcome",
]


class TransparencyEnvelopeError(ValueError):
    """The transparent projection is internally inconsistent."""


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class TransparencyQuality(_Contract):
    """Quality dimensions stay separate from the values being reported."""

    state: QualityState = QualityState.VALID
    completeness: float = Field(default=1.0, ge=0, le=1)
    freshness: Literal["fresh", "stale", "unknown"] = "fresh"
    validity: float = Field(default=1.0, ge=0, le=1)
    uniqueness: float = Field(default=1.0, ge=0, le=1)
    referential_integrity: float = Field(default=1.0, ge=0, le=1)
    cross_source_consistency: float = Field(default=1.0, ge=0, le=1)
    reconciliation: float = Field(default=1.0, ge=0, le=1)
    lineage_coverage: float = Field(default=1.0, ge=0, le=1)
    excluded_count: int = Field(default=0, ge=0)
    reasons: tuple[str, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def normalize_state(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        if data.get("state") is not None:
            data["state"] = QualityState(data["state"])
        if data.get("reasons") is not None:
            data["reasons"] = tuple(str(item).strip() for item in data["reasons"] if str(item).strip())
        return data

    @model_validator(mode="after")
    def validate_state(self) -> TransparencyQuality:
        if self.state == QualityState.VALID and self.freshness != "fresh":
            raise TransparencyEnvelopeError("VALID quality requires fresh freshness")
        if self.state == QualityState.STALE and self.freshness == "fresh":
            raise TransparencyEnvelopeError("STALE quality cannot declare fresh freshness")
        if self.excluded_count and self.state == QualityState.VALID:
            raise TransparencyEnvelopeError("excluded rows require non-VALID quality")
        return self

    def to_quality_summary(self):
        """Return the compact quality shape required by ``DataEnvelope``."""

        from .data_fabric_contracts import QualitySummary

        return QualitySummary(
            completeness=self.completeness,
            freshness=self.freshness,
            excluded_count=self.excluded_count,
            reasons=self.reasons,
        )


_STATUS_TO_QUALITY: dict[str, QualityState] = {
    "ready": QualityState.VALID,
    "partial": QualityState.PARTIAL,
    "stale": QualityState.STALE,
    "conflicted": QualityState.BLOCKED,
    "blocked": QualityState.BLOCKED,
    "no_data": QualityState.NO_DATA,
    "unknown_outcome": QualityState.UNKNOWN_OUTCOME,
}
_QUALITY_TO_STATUS: dict[QualityState, str] = {
    QualityState.VALID: "ready",
    QualityState.PARTIAL: "partial",
    QualityState.STALE: "stale",
    QualityState.BLOCKED: "blocked",
    QualityState.NO_DATA: "no_data",
    QualityState.UNKNOWN_OUTCOME: "unknown_outcome",
}


class TransparencyEnvelope(_Contract):
    """Auditable read projection with stable source and calculation metadata."""

    dataset: str = Field(min_length=1, max_length=240)
    scope: ScopeRef
    as_of: datetime
    fresh_until: datetime | None = None
    status: DataEnvelopeStatus | None = None
    quality_state: QualityState | None = None
    data: tuple[dict[str, Any], ...] = ()
    included_rows: tuple[dict[str, Any], ...] = ()
    excluded_rows: tuple[dict[str, Any], ...] = ()
    records: tuple[FactDataContract, ...] = Field(
        default=(),
        validation_alias=AliasChoices("records", "fact_records", "row_contracts"),
        exclude_if=lambda value: not value,
    )
    quality: TransparencyQuality | None = None
    source_count: int = Field(default=0, ge=0)
    excluded_count: int = Field(default=0, ge=0)
    exclusion_reasons: tuple[str, ...] = ()
    formula_version: str | None = Field(default=None, min_length=1, max_length=160)
    rule_version: str | None = Field(default=None, min_length=1, max_length=160)
    policy_hash: str | None = Field(default=None, min_length=1, max_length=200)
    model_version: str | None = Field(default=None, min_length=1, max_length=200)
    skill_version: str | None = Field(default=None, min_length=1, max_length=200)
    authority_hash: str = Field(default="transparency-envelope", min_length=1, max_length=240)
    lineage: tuple[LineageRef, ...] = ()
    lineage_edges: tuple[LineageEdge, ...] = ()
    lineage_chain: LineageChain | None = Field(default=None, exclude_if=lambda value: value is None)
    drilldown_path: DrilldownPath | None = Field(default=None, exclude_if=lambda value: value is None)
    source_watermarks: dict[str, str] = Field(default_factory=dict)
    period: PeriodRef | None = None
    next_action: str | None = Field(default=None, max_length=1000)
    schema_version: str = Field(default="1.0", min_length=1, max_length=80)
    next_cursor: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_input(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        if "lineage" not in data and "lineage_refs" in data:
            data["lineage"] = data.pop("lineage_refs")
        if "records" not in data:
            for alias in ("fact_records", "row_contracts"):
                if alias in data:
                    data["records"] = data.pop(alias)
                    break
        if "lineage_chain" not in data and "lineage_graph" in data:
            data["lineage_chain"] = data.pop("lineage_graph")
        if "drilldown_path" not in data:
            for alias in ("drilldown", "hierarchy"):
                if alias in data and isinstance(data[alias], Mapping):
                    data["drilldown_path"] = data.pop(alias)
                    break
        if "quality_state" not in data and "quality_status" in data:
            data["quality_state"] = data.pop("quality_status")
        if "excluded_rows" not in data and "exclusions" in data:
            data["excluded_rows"] = data.pop("exclusions")
        if data.get("as_of") is not None:
            data["as_of"] = _utc(data["as_of"], "as_of")
        if data.get("fresh_until") is not None:
            data["fresh_until"] = _utc(data["fresh_until"], "fresh_until")
        if data.get("status") is not None:
            data["status"] = str(data["status"]).strip().lower()
        if data.get("quality_state") is not None:
            data["quality_state"] = QualityState(data["quality_state"])
        raw_quality = data.get("quality")
        if isinstance(raw_quality, QualitySummary):
            data["quality"] = {
                "completeness": raw_quality.completeness,
                "freshness": raw_quality.freshness,
                "excluded_count": raw_quality.excluded_count,
                "reasons": raw_quality.reasons,
            }
            if "excluded_count" not in data:
                data["excluded_count"] = raw_quality.excluded_count
            if "exclusion_reasons" not in data:
                data["exclusion_reasons"] = raw_quality.reasons
            if data.get("quality_state") is not None:
                data["quality"]["state"] = data["quality_state"]
            elif data.get("status") is not None:
                data["quality"]["state"] = _STATUS_TO_QUALITY.get(
                    str(data["status"]).strip().lower(), QualityState.VALID
                )
        elif isinstance(raw_quality, Mapping) and "state" not in raw_quality:
            quality_data = dict(raw_quality)
            if "excluded_count" not in data and quality_data.get("excluded_count") is not None:
                data["excluded_count"] = quality_data["excluded_count"]
            if "exclusion_reasons" not in data and quality_data.get("reasons") is not None:
                data["exclusion_reasons"] = quality_data["reasons"]
            if data.get("quality_state") is not None:
                quality_data["state"] = data["quality_state"]
            elif data.get("status") is not None:
                quality_data["state"] = _STATUS_TO_QUALITY.get(str(data["status"]).strip().lower(), QualityState.VALID)
            data["quality"] = quality_data
        for name in ("data", "included_rows", "excluded_rows"):
            if data.get(name) is not None:
                rows = data[name]
                if not isinstance(rows, (list, tuple)):
                    raise TransparencyEnvelopeError(f"{name} must be a sequence of objects")
                normalized_rows: list[dict[str, Any]] = []
                for row in rows:
                    if not isinstance(row, Mapping):
                        raise TransparencyEnvelopeError(f"{name} must contain objects")
                    normalized_rows.append(_json_safe(row))
                data[name] = tuple(normalized_rows)
        if data.get("lineage") is not None:
            data["lineage"] = tuple(LineageRef.model_validate(item) for item in data["lineage"])
        if data.get("lineage_edges") is not None:
            data["lineage_edges"] = tuple(LineageEdge.model_validate(item) for item in data["lineage_edges"])
        if data.get("records") is not None:
            raw_records = data["records"]
            if not isinstance(raw_records, (list, tuple)):
                raise TransparencyEnvelopeError("records must be a sequence of objects")
            data["records"] = tuple(FactDataContract.model_validate(item) for item in raw_records)
        if data.get("lineage_chain") is not None:
            data["lineage_chain"] = LineageChain.model_validate(data["lineage_chain"])
        if data.get("drilldown_path") is not None:
            data["drilldown_path"] = DrilldownPath.model_validate(data["drilldown_path"])
        if data.get("source_watermarks") is not None:
            if not isinstance(data["source_watermarks"], Mapping):
                raise TransparencyEnvelopeError("source_watermarks must be an object")
            data["source_watermarks"] = {
                str(key).strip(): str(value).strip()
                for key, value in data["source_watermarks"].items()
                if str(key).strip()
            }
        if data.get("exclusion_reasons") is not None:
            data["exclusion_reasons"] = tuple(
                sorted({str(item).strip() for item in data["exclusion_reasons"] if str(item).strip()})
            )
        return data

    @model_validator(mode="after")
    def validate_projection(self) -> TransparencyEnvelope:
        status = self.status
        quality_state = self.quality_state
        if status is None and quality_state is None:
            status = "ready"
            quality_state = QualityState.VALID
        elif status is None:
            assert quality_state is not None
            status = _QUALITY_TO_STATUS[quality_state]
        elif quality_state is None:
            quality_state = _STATUS_TO_QUALITY[status]
        if status not in _STATUS_TO_QUALITY:
            raise TransparencyEnvelopeError(f"unsupported DataEnvelope status: {status}")
        expected_quality = _STATUS_TO_QUALITY[status]
        if quality_state != expected_quality:
            raise TransparencyEnvelopeError("status and quality_state disagree")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "quality_state", quality_state)

        # A missing included_rows field means the data rows are the included
        # rows; retaining both forms makes exports explicit without requiring
        # callers to duplicate a potentially large payload.
        if not self.included_rows and self.data:
            object.__setattr__(self, "included_rows", self.data)
        if self.data and self.included_rows and self.data != self.included_rows:
            raise TransparencyEnvelopeError("data and included_rows differ")
        if self.records:
            if self.data and len(self.records) != len(self.data):
                raise TransparencyEnvelopeError("records and data row counts differ")
            if quality_state in {
                QualityState.NO_DATA,
                QualityState.BLOCKED,
                QualityState.UNKNOWN_OUTCOME,
            }:
                raise TransparencyEnvelopeError(f"{quality_state.value} envelope cannot contain validated records")
            for record in self.records:
                if record.tenant != self.scope.tenant_id or record.entity != self.scope.entity_id:
                    raise TransparencyEnvelopeError("record scope is outside envelope scope")
                if self.scope.store_ids and record.store not in self.scope.store_ids:
                    raise TransparencyEnvelopeError("record store is outside envelope scope")
                if self.scope.warehouse_ids and record.warehouse not in self.scope.warehouse_ids:
                    raise TransparencyEnvelopeError("record warehouse is outside envelope scope")
                if self.scope.sku_ids and record.sku not in self.scope.sku_ids:
                    raise TransparencyEnvelopeError("record SKU is outside envelope scope")
            if quality_state == QualityState.VALID and any(
                record.quality_state != "VALID" for record in self.records
            ):
                raise TransparencyEnvelopeError("VALID envelope cannot contain non-VALID records")
        if self.excluded_count < len(self.excluded_rows):
            object.__setattr__(self, "excluded_count", len(self.excluded_rows))

        quality = self.quality
        if quality is None:
            freshness = (
                "fresh"
                if quality_state == QualityState.VALID
                else "stale"
                if quality_state == QualityState.STALE
                else "unknown"
            )
            completeness = 1.0
            if self.excluded_count:
                completeness = max(
                    0.0,
                    1.0 - self.excluded_count / max(1, len(self.data) + self.excluded_count),
                )
            quality = TransparencyQuality(
                state=quality_state,
                completeness=completeness,
                freshness=freshness,
                excluded_count=self.excluded_count,
                reasons=self.exclusion_reasons,
                lineage_coverage=(1.0 if self.data and self.lineage else 0.0 if self.data else 1.0),
            )
            object.__setattr__(self, "quality", quality)
        elif quality.state != quality_state:
            raise TransparencyEnvelopeError("quality.state and quality_state disagree")
        if quality.excluded_count != self.excluded_count:
            raise TransparencyEnvelopeError("quality.excluded_count and excluded_count disagree")
        if quality.reasons and self.exclusion_reasons and set(quality.reasons) != set(self.exclusion_reasons):
            raise TransparencyEnvelopeError("quality reasons and exclusion_reasons disagree")
        if quality_state == QualityState.VALID and self.excluded_count:
            raise TransparencyEnvelopeError("ready/VALID envelope cannot contain excluded rows")
        if (
            quality_state
            in {
                QualityState.NO_DATA,
                QualityState.BLOCKED,
                QualityState.UNKNOWN_OUTCOME,
            }
            and self.data
        ):
            raise TransparencyEnvelopeError(f"{quality_state.value} envelope cannot contain data rows")
        if status == "ready" and self.quality.freshness != "fresh":
            raise TransparencyEnvelopeError("ready envelope requires fresh quality")
        if self.fresh_until is not None and self.fresh_until < self.as_of and quality_state == QualityState.VALID:
            raise TransparencyEnvelopeError("VALID envelope cannot be past fresh_until")
        if self.source_count < len(self.lineage):
            object.__setattr__(self, "source_count", len(self.lineage))
        lineage_keys = [(item.kind, item.id, item.relationship) for item in self.lineage]
        if len(lineage_keys) != len(set(lineage_keys)):
            raise TransparencyEnvelopeError("lineage references must be unique")
        edge_keys = [
            (item.from_type, item.from_id, item.to_type, item.to_id, item.relationship) for item in self.lineage_edges
        ]
        if len(edge_keys) != len(set(edge_keys)):
            raise TransparencyEnvelopeError("lineage edges must be unique")
        return self

    @property
    def content_hash(self) -> str:
        """Hash of the complete canonical read projection."""

        return content_sha256(self.model_dump(mode="json", exclude={"content_hash"}))

    @property
    def quality_status(self) -> QualityState:
        assert self.quality_state is not None
        return self.quality_state

    def to_data_envelope(self) -> DataEnvelope:
        """Project to the existing transport contract."""

        # DataEnvelope intentionally rejects rows for blocked/no-data/unknown
        # states.  The transparent envelope retains excluded diagnostics while
        # the transport projection remains fail-closed.
        rows = self.data
        if self.quality_status in {
            QualityState.NO_DATA,
            QualityState.BLOCKED,
            QualityState.UNKNOWN_OUTCOME,
        }:
            rows = ()
        evidence_lineage = []
        seen: set[tuple[str, str]] = set()
        for ref in self.lineage:
            if ref.kind not in {"evidence", "fact", "decision", "action"}:
                continue
            key = (ref.kind, ref.id)
            if key in seen:
                continue
            seen.add(key)
            # Import locally to keep the public module import graph small.
            from .data_fabric_contracts import EvidenceRef

            evidence_lineage.append(EvidenceRef(kind=ref.kind, id=ref.id, sha256=ref.sha256))
        transport_fresh_until = self.fresh_until
        # The compact DataEnvelope contract rejects an expired
        # ``fresh_until`` even for a deliberately stale result.  Preserve the
        # stale state and omit the expired bound in that projection; the rich
        # envelope still carries the original timestamp for audit purposes.
        if transport_fresh_until is not None and transport_fresh_until < self.as_of:
            transport_fresh_until = None
        return DataEnvelope(
            dataset=self.dataset,
            scope=self.scope,
            as_of=self.as_of,
            fresh_until=transport_fresh_until,
            status=self.status or "ready",
            data=rows,
            quality=self.quality.to_quality_summary(),
            lineage=tuple(evidence_lineage),
            records=(
                self.records
                if self.quality_status
                not in {QualityState.NO_DATA, QualityState.BLOCKED, QualityState.UNKNOWN_OUTCOME}
                else ()
            ),
            lineage_chain=self.lineage_chain,
            drilldown_path=self.drilldown_path,
            schema_version=self.schema_version,
            authority_hash=self.authority_hash,
            next_cursor=self.next_cursor,
        )

    @classmethod
    def from_data_envelope(
        cls,
        envelope: DataEnvelope,
        *,
        lineage_edges: tuple[LineageEdge, ...] = (),
        formula_version: str | None = None,
        rule_version: str | None = None,
        policy_hash: str | None = None,
        model_version: str | None = None,
        skill_version: str | None = None,
        source_watermarks: Mapping[str, str] | None = None,
        next_action: str | None = None,
        records: tuple[FactDataContract, ...] = (),
        lineage_chain: LineageChain | None = None,
        drilldown_path: DrilldownPath | None = None,
    ) -> TransparencyEnvelope:
        quality_state = _STATUS_TO_QUALITY[envelope.status]
        quality = TransparencyQuality(
            state=quality_state,
            completeness=envelope.quality.completeness,
            freshness=envelope.quality.freshness,
            excluded_count=envelope.quality.excluded_count,
            reasons=envelope.quality.reasons,
            lineage_coverage=(1.0 if envelope.lineage else 0.0 if envelope.data else 1.0),
        )
        return cls(
            dataset=envelope.dataset,
            scope=envelope.scope,
            as_of=envelope.as_of,
            fresh_until=envelope.fresh_until,
            status=envelope.status,
            quality_state=quality_state,
            data=envelope.data,
            included_rows=envelope.data,
            quality=quality,
            source_count=len(envelope.lineage),
            excluded_count=envelope.quality.excluded_count,
            exclusion_reasons=envelope.quality.reasons,
            formula_version=formula_version,
            rule_version=rule_version,
            policy_hash=policy_hash,
            model_version=model_version,
            skill_version=skill_version,
            authority_hash=envelope.authority_hash,
            lineage=tuple(LineageRef(kind=item.kind, id=item.id, sha256=item.sha256) for item in envelope.lineage),
            records=records or envelope.records,
            lineage_chain=lineage_chain or envelope.lineage_chain,
            drilldown_path=drilldown_path or envelope.drilldown_path,
            lineage_edges=lineage_edges,
            source_watermarks=source_watermarks or {},
            schema_version=envelope.schema_version,
            next_cursor=envelope.next_cursor,
            next_action=next_action,
        )

    @classmethod
    def from_query_result(
        cls,
        result: TemporalFactQueryResult,
        *,
        dataset: str,
        scope: ScopeRef,
        authority_hash: str = "temporal-fact-store",
        schema_version: str = "1.0",
        fresh_until: datetime | None = None,
        formula_version: str | None = None,
        rule_version: str | None = None,
        source_watermarks: Mapping[str, str] | None = None,
        next_action: str | None = None,
        records: tuple[FactDataContract, ...] = (),
        lineage_chain: LineageChain | None = None,
        drilldown_path: DrilldownPath | None = None,
    ) -> TransparencyEnvelope:
        lineage: list[LineageRef] = []
        seen: set[tuple[str, str]] = set()
        for fact in result.items:
            for ref in fact.lineage:
                key = (ref.kind, ref.id)
                if key not in seen:
                    seen.add(key)
                    lineage.append(ref)
        data = tuple(
            {
                "fact_id": fact.fact_id,
                "revision_id": fact.revision_id,
                "revision": fact.revision,
                "fact_type": fact.fact_type,
                "natural_key": fact.natural_key,
                **copy.deepcopy(fact.payload),
            }
            for fact in result.items
        )
        unsafe_quality = result.quality_state in {
            QualityState.NO_DATA,
            QualityState.BLOCKED,
            QualityState.UNKNOWN_OUTCOME,
        }
        return cls(
            dataset=dataset,
            scope=scope,
            as_of=result.as_of,
            fresh_until=fresh_until,
            status=_QUALITY_TO_STATUS[result.quality_state],
            quality_state=result.quality_state,
            data=() if unsafe_quality else data,
            included_rows=() if unsafe_quality else data,
            excluded_rows=data if unsafe_quality else (),
            source_count=len(lineage),
            excluded_count=max(result.excluded_count, len(data) if unsafe_quality else 0),
            exclusion_reasons=result.exclusion_reasons,
            formula_version=formula_version,
            rule_version=rule_version,
            authority_hash=authority_hash,
            lineage=tuple(lineage),
            records=records,
            lineage_chain=lineage_chain,
            drilldown_path=drilldown_path,
            source_watermarks=source_watermarks or {},
            schema_version=schema_version,
            next_cursor=result.next_cursor,
            next_action=next_action,
        )

    def drilldown(self) -> tuple[dict[str, Any], ...]:
        """Return a stable, read-only lineage drill-down sequence."""

        return tuple(
            {
                "kind": ref.kind,
                "id": ref.id,
                "sha256": ref.sha256,
                "relationship": ref.relationship,
                "version": ref.version,
            }
            for ref in self.lineage
        )

    def lineage_audit(self) -> dict[str, Any]:
        """Expose chain and row-contract completeness without asserting truth.

        A complete shape still requires authority-level existence/hash checks by
        the Evidence and Fact services; this read projection only reports what
        was supplied and prevents a partial chain from being rendered as full.
        """

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

    def six_level_drilldown(self) -> tuple[dict[str, Any], ...]:
        """Return the ordered entity→evidence path for UI drill-downs."""

        if self.drilldown_path is None:
            return ()
        return tuple(node.model_dump(mode="json") for node in self.drilldown_path.nodes)

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


__all__ = [
    "DataEnvelopeStatus",
    "LineageEdge",
    "LineageRef",
    "QualityState",
    "TransparencyEnvelope",
    "TransparencyEnvelopeError",
    "TransparencyQuality",
]
