from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..api_contracts import current_principal, ensure_role, ensure_store_scope, run
from ..data_fabric_contracts import (
    LINEAGE_STAGE_ORDER,
    DrilldownNode,
    DrilldownPath,
    LineageChain,
    LineageEdgeContract,
    LineageNode,
)
from ..runtime import runtime
from ..security import Principal
from ..temporal_fact_store import (
    FactNotFoundError,
    LineageEdge,
    LineageRef,
    QualityState,
    ScopeRef,
    TemporalFactQueryResult,
    TemporalFactRevision,
    content_sha256,
)
from ..transparency_envelope import TransparencyEnvelope

router = APIRouter()


_STATUS_BY_QUALITY: dict[QualityState, str] = {
    QualityState.VALID: "ready",
    QualityState.PARTIAL: "partial",
    QualityState.STALE: "stale",
    QualityState.BLOCKED: "blocked",
    QualityState.NO_DATA: "no_data",
    QualityState.UNKNOWN_OUTCOME: "unknown_outcome",
}
_TERMINAL_QUALITY = frozenset(
    {
        QualityState.NO_DATA,
        QualityState.BLOCKED,
        QualityState.UNKNOWN_OUTCOME,
    }
)
_LINEAGE_STAGE_BY_KIND = {
    "dataset": "data_product",
    "data_product": "data_product",
    "fact": "canonical_fact",
    "canonical_fact": "canonical_fact",
    "fact_revision": "canonical_fact",
    "raw": "raw_fact",
    "raw_fact": "raw_fact",
    "evidence": "raw_file",
    "raw_file": "raw_file",
    "platform_response": "platform_response",
    "response": "platform_response",
    "hash": "hash",
    "import": "import_task",
    "import_task": "import_task",
    "rule": "rule_version",
    "rule_version": "rule_version",
    "decision": "agent_decision",
    "agent_decision": "agent_decision",
    "action": "action",
    "external_readback": "external_readback",
    "readback": "external_readback",
}


class RestateFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_ref: str = Field(min_length=1, max_length=160)
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    payload: dict[str, Any]
    correction_reason: str = Field(min_length=1, max_length=2000)
    observed_time: datetime | None = None
    event_time: datetime | None = None
    effective_time: datetime | None = None
    settled_time: datetime | None = None
    fresh_until: datetime | None = None
    quality_state: QualityState | None = None
    lineage: list[LineageRef] | None = None
    source_version: str | None = Field(default=None, min_length=1, max_length=120)
    causation_id: str | None = Field(default=None, max_length=300)
    correlation_id: str | None = Field(default=None, max_length=300)
    idempotency_key: str = Field(min_length=1, max_length=300)
    metadata: dict[str, Any] | None = None
    created_by: str | None = Field(default=None, min_length=1, max_length=160)


def _timestamp(value: str | None) -> datetime:
    trusted_now = datetime.now(UTC)
    if value is None:
        return trusted_now
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, "as_of must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise HTTPException(422, "as_of must include timezone")
    parsed = parsed.astimezone(UTC)
    if parsed > trusted_now:
        raise HTTPException(422, "as_of cannot be in the future")
    return parsed


def _scope(
    principal: Principal,
    entity_ref: str,
    store_ref: str,
    *,
    as_of: datetime | None = None,
) -> ScopeRef:
    ensure_store_scope(principal, store_ref)
    if not isinstance(entity_ref, str) or not entity_ref.strip():
        raise HTTPException(422, "entity_ref is required")
    authority_reader = getattr(runtime.scope_grants, "current", None)
    if not callable(authority_reader):
        raise HTTPException(503, "scope authority is unavailable")
    try:
        authority = authority_reader(
            principal=principal,
            store_ref=store_ref,
            as_of=as_of or datetime.now(UTC),
        )
    except PermissionError as exc:
        raise HTTPException(403, "entity is outside the current authorized scope") from exc
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        # An authority outage must never be interpreted as an empty or
        # unrestricted scope.  Keep the diagnostic generic so backend details
        # and tenant existence are not disclosed to callers.
        raise HTTPException(503, "scope authority is unavailable") from exc
    if not isinstance(authority, Mapping):
        raise HTTPException(503, "scope authority returned an invalid result")
    if authority.get("status") != "ready" or authority.get("entity_ref") != entity_ref:
        raise HTTPException(403, "entity is outside the current authorized scope")
    return ScopeRef(tenant_id=principal.tenant_ref, entity_id=entity_ref, store_ids=(store_ref,))


def _fact_matches_scope(fact: TemporalFactRevision, scope: ScopeRef) -> bool:
    """Check the caller boundary without requiring optional child dimensions.

    The route scope is entity/store level.  A fact may additionally carry a
    warehouse or SKU, so comparing ``ScopeRef`` objects for equality would
    incorrectly deny an otherwise authorized row.  Tenant, entity and the
    selected store remain exact; optional dimensions are constrained only when
    the request explicitly supplies them.
    """

    candidate = fact.scope
    if candidate.tenant_id != scope.tenant_id or candidate.entity_id != scope.entity_id:
        return False
    if set(candidate.store_ids) != set(scope.store_ids):
        return False
    if scope.warehouse_ids and set(candidate.warehouse_ids) != set(scope.warehouse_ids):
        return False
    return not scope.sku_ids or set(candidate.sku_ids) == set(scope.sku_ids)


def _query_quality(items: Iterable[TemporalFactRevision]) -> QualityState:
    rows = tuple(items)
    if not rows:
        return QualityState.NO_DATA
    if any(item.quality_state == QualityState.BLOCKED for item in rows):
        return QualityState.BLOCKED
    if any(item.quality_state == QualityState.UNKNOWN_OUTCOME for item in rows):
        return QualityState.UNKNOWN_OUTCOME
    if any(item.quality_state == QualityState.STALE for item in rows):
        return QualityState.STALE
    if any(item.quality_state == QualityState.PARTIAL for item in rows):
        return QualityState.PARTIAL
    return QualityState.VALID


def _blocked_result(cutoff: datetime, reason: str) -> TemporalFactQueryResult:
    return TemporalFactQueryResult(
        as_of=cutoff,
        items=(),
        quality_state=QualityState.BLOCKED,
        exclusion_reasons=(reason,),
    )


def _query_store(
    cutoff: datetime,
    *,
    scope: ScopeRef,
    fact_type: str | None = None,
    include_stale: bool = True,
) -> tuple[TemporalFactQueryResult, str | None]:
    """Read either temporal adapter while preserving outage semantics.

    ``SqlTemporalFactStore`` and the reference in-memory store expose the
    same methods, but small test/adaptor implementations often only expose
    ``as_of``.  Supporting both keeps the API boundary provider-neutral.  A
    failed read is represented as a blocked result with a stable reason; it
    is never changed into ``NO_DATA``.
    """

    store = getattr(runtime, "temporal_fact_store", None)
    query_reader = getattr(store, "query_as_of", None)
    try:
        if callable(query_reader):
            result = query_reader(
                cutoff,
                scope=scope,
                fact_type=fact_type,
                include_stale=include_stale,
            )
            if not isinstance(result, TemporalFactQueryResult):
                raise TypeError("temporal fact adapter returned an invalid query result")
            return result, None

        as_of_reader = getattr(store, "as_of", None)
        if not callable(as_of_reader):
            return _blocked_result(cutoff, "temporal_fact_source_not_bound"), "temporal_fact_source_not_bound"
        rows = tuple(
            as_of_reader(
                cutoff,
                scope=scope,
                fact_type=fact_type,
                include_stale=include_stale,
            )
        )
        if not all(isinstance(item, TemporalFactRevision) for item in rows):
            raise TypeError("temporal fact adapter returned invalid fact rows")
        result = TemporalFactQueryResult(
            as_of=cutoff,
            items=rows,
            quality_state=_query_quality(rows),
        )
        return result, None
    except Exception:
        reason = "temporal_fact_source_unavailable"
        return _blocked_result(cutoff, reason), reason


def _lineage_material(
    facts: Iterable[TemporalFactRevision],
    *,
    store: Any,
) -> tuple[tuple[LineageRef, ...], tuple[LineageEdge, ...], tuple[str, ...]]:
    """Collect deterministic lineage refs/edges after scope authorization."""

    refs: list[LineageRef] = []
    seen_refs: set[tuple[str, str, str, str | None]] = set()
    edges: list[LineageEdge] = []
    seen_edges: set[tuple[str, str, str, str, str]] = set()
    errors: list[str] = []
    edge_reader = getattr(store, "lineage_edges", None)
    for fact in facts:
        for ref in fact.lineage:
            key = (ref.kind, ref.id, ref.relationship, ref.version)
            if key not in seen_refs:
                seen_refs.add(key)
                refs.append(ref)
        if not callable(edge_reader):
            errors.append("lineage_edge_source_not_bound")
            continue
        try:
            raw_edges = edge_reader(fact.fact_id, revision=fact.revision)
            for raw_edge in raw_edges:
                edge = raw_edge if isinstance(raw_edge, LineageEdge) else LineageEdge.model_validate(raw_edge)
                key = (
                    edge.from_type,
                    edge.from_id,
                    edge.to_type,
                    edge.to_id,
                    edge.relationship,
                )
                if key not in seen_edges:
                    seen_edges.add(key)
                    edges.append(edge)
        except Exception:
            errors.append("lineage_edge_source_unavailable")
    return tuple(refs), tuple(edges), tuple(sorted(set(errors)))


def _lineage_stage(kind: str) -> str | None:
    return _LINEAGE_STAGE_BY_KIND.get(str(kind).strip().lower().replace("-", "_"))


def _lineage_chain(facts: Iterable[TemporalFactRevision]) -> LineageChain | None:
    """Build the present portion of the canonical chain without fabrication."""

    nodes: list[LineageNode] = []
    edges: list[LineageEdgeContract] = []
    seen_nodes: set[tuple[str, str]] = set()
    seen_edges: set[tuple[str, str, str, str, str]] = set()
    for fact in facts:
        canonical_key = ("canonical_fact", fact.revision_id)
        if canonical_key not in seen_nodes:
            seen_nodes.add(canonical_key)
            nodes.append(
                LineageNode(
                    stage="canonical_fact",
                    id=fact.revision_id,
                    sha256=fact.content_sha256,
                    version=str(fact.revision),
                    observed_time=fact.observed_time,
                    metadata={"fact_id": fact.fact_id, "fact_type": fact.fact_type},
                )
            )
        for ref in fact.lineage:
            stage = _lineage_stage(ref.kind)
            if stage is None:
                continue
            source_key = (stage, ref.id)
            if source_key not in seen_nodes:
                seen_nodes.add(source_key)
                nodes.append(
                    LineageNode(
                        stage=stage,
                        id=ref.id,
                        sha256=ref.sha256,
                        version=ref.version,
                        observed_time=fact.observed_time,
                        metadata={"fact_id": fact.fact_id, "revision": fact.revision},
                    )
                )
            edge_key = (stage, ref.id, "canonical_fact", fact.revision_id, ref.relationship)
            if edge_key not in seen_edges:
                seen_edges.add(edge_key)
                edges.append(
                    LineageEdgeContract(
                        from_type=stage,
                        from_id=ref.id,
                        to_type="canonical_fact",
                        to_id=fact.revision_id,
                        relationship=ref.relationship,
                        from_sha256=ref.sha256,
                        to_sha256=fact.content_sha256,
                    )
                )
    if not nodes:
        return None
    nodes.sort(key=lambda item: (LINEAGE_STAGE_ORDER.index(item.stage), item.id))
    edges.sort(key=lambda item: (item.from_type, item.from_id, item.to_id, item.relationship))
    return LineageChain(nodes=tuple(nodes), edges=tuple(edges))


def _payload_id(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _fact_drilldown_path(fact: TemporalFactRevision) -> DrilldownPath:
    """Project known hierarchy levels and leave unknown levels explicit."""

    scope = fact.scope
    nodes: list[DrilldownNode] = [
        DrilldownNode(level="entity", id=scope.entity_id),
    ]
    store_id = scope.store if len(scope.store_ids) == 1 else None
    if store_id:
        nodes.append(DrilldownNode(level="store", id=store_id, parent_id=scope.entity_id))
    warehouse_id = scope.warehouse if len(scope.warehouse_ids) == 1 else None
    if warehouse_id:
        parent = nodes[-1].id
        nodes.append(DrilldownNode(level="warehouse", id=warehouse_id, parent_id=parent))
    payload = fact.payload if isinstance(fact.payload, Mapping) else {}
    sku_id = fact.sku or scope.sku
    if sku_id is None:
        sku_id = _payload_id(payload, ("sku", "sku_id", "seller_sku", "variant_id"))
    if sku_id:
        parent = nodes[-1].id
        nodes.append(DrilldownNode(level="sku", id=sku_id, parent_id=parent))

    transaction_id = _payload_id(
        payload,
        (
            "order_id",
            "order_ref",
            "transaction_id",
            "return_id",
            "fee_id",
            "settlement_id",
            "ad_event_id",
        ),
    )
    if transaction_id is None and fact.fact_type in {
        "order",
        "order_line",
        "fee",
        "return",
        "return_line",
        "settlement",
        "settlement_line",
        "ad_event",
        "advertising",
        "bank_transaction",
    }:
        transaction_id = fact.natural_key
    if transaction_id:
        parent = nodes[-1].id
        nodes.append(DrilldownNode(level="transaction", id=transaction_id, parent_id=parent))

    evidence_ref = next(
        (
            ref
            for ref in fact.lineage
            if ref.kind.lower() in {"evidence", "raw_file", "platform_response", "response"}
        ),
        None,
    )
    if evidence_ref:
        parent = nodes[-1].id
        nodes.append(
            DrilldownNode(
                level="evidence",
                id=evidence_ref.id,
                parent_id=parent,
                metadata={"kind": evidence_ref.kind, "sha256": evidence_ref.sha256},
            )
        )
    return DrilldownPath(nodes=tuple(nodes))


def _transparency(
    result: TemporalFactQueryResult,
    *,
    scope: ScopeRef,
    lineage_edges: tuple[LineageEdge, ...],
) -> TransparencyEnvelope:
    chain = _lineage_chain(result.items)
    paths = tuple(_fact_drilldown_path(item) for item in result.items)
    envelope = TransparencyEnvelope.from_query_result(
        result,
        dataset="temporal.facts.v1",
        scope=scope,
        authority_hash="temporal-fact-store",
        lineage_chain=chain,
        drilldown_path=paths[0] if paths else None,
    )
    # ``LineageEdge`` is the runtime representation; the envelope validates
    # uniqueness and serializes it as part of the immutable read projection.
    return envelope.model_copy(update={"lineage_edges": lineage_edges})


def _projection_hash(payload: Mapping[str, Any]) -> str:
    return content_sha256(payload)


def _serialize_edges(edges: Iterable[LineageEdge]) -> list[dict[str, Any]]:
    return [edge.model_dump(mode="json") for edge in edges]


@router.get("/v1/facts/as-of")
def facts_as_of(
    principal: Annotated[Principal, Depends(current_principal)],
    entity_ref: str,
    store_ref: str = "ozon-primary",
    fact_type: str | None = None,
    as_of: str | None = None,
    include_stale: bool = True,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    cutoff = _timestamp(as_of)
    scope = _scope(principal, entity_ref, store_ref, as_of=cutoff)

    def query():
        result, source_error = _query_store(
            cutoff,
            scope=scope,
            fact_type=fact_type,
            include_stale=include_stale,
        )
        # A terminal quality state cannot carry included rows.  Keep the raw
        # revisions in ``excluded_facts`` for an authorized audit trail while
        # making the primary ``facts`` collection safe for consumers that
        # treat it as usable data.
        included = () if result.quality_state in _TERMINAL_QUALITY else result.items
        excluded = result.items if result.quality_state in _TERMINAL_QUALITY else ()
        lineage_refs, lineage_edges, lineage_errors = _lineage_material(
            result.items,
            store=getattr(runtime, "temporal_fact_store", None),
        )
        transparency = _transparency(
            result,
            scope=scope,
            lineage_edges=lineage_edges,
        )
        envelope = result.to_data_envelope(
            dataset="temporal.facts.v1",
            scope=scope,
            authority_hash="temporal-fact-store",
        )
        body = {
            "contract_id": "kjds-temporal-facts-as-of-v1",
            "status": _STATUS_BY_QUALITY[result.quality_state],
            "quality_state": result.quality_state.value,
            "as_of": cutoff.isoformat(),
            "scope": scope.model_dump(mode="json"),
            "facts": [item.model_dump(mode="json") for item in included],
            "excluded_facts": [item.model_dump(mode="json") for item in excluded],
            "included_count": len(included),
            "excluded_count": result.excluded_count + len(excluded),
            "reason": source_error or (None if included else "no_facts_at_as_of"),
            "quality": envelope.quality.model_dump(mode="json"),
            "data_envelope": envelope.model_dump(mode="json"),
            "lineage": [item.model_dump(mode="json") for item in lineage_refs],
            "lineage_edges": _serialize_edges(lineage_edges),
            "lineage_errors": list(lineage_errors),
            "lineage_status": "VALID" if not lineage_errors else "PARTIAL",
            "transparency": transparency.model_dump(mode="json"),
            "drilldown": [
                _fact_drilldown_path(item).model_dump(mode="json")
                for item in result.items
            ],
            "lineage_audit": transparency.lineage_audit(),
            "replay": {
                "mode": "historical_replay",
                "as_of": cutoff.isoformat(),
                "result_sha256": _projection_hash(
                    {
                        "scope": scope.model_dump(mode="json"),
                        "as_of": cutoff.isoformat(),
                        "quality_state": result.quality_state.value,
                        "facts": [item.model_dump(mode="json") for item in result.items],
                        "lineage": [item.model_dump(mode="json") for item in lineage_refs],
                        "lineage_edges": _serialize_edges(lineage_edges),
                    }
                ),
            },
            "external_write_allowed": False,
        }
        return body

    return run(query)


@router.get("/v1/facts/{fact_id}/versions")
def fact_versions(
    fact_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    entity_ref: str,
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    cutoff = _timestamp(as_of)
    scope = _scope(principal, entity_ref, store_ref, as_of=cutoff)

    def query():
        store = getattr(runtime, "temporal_fact_store", None)
        reader = getattr(store, "history", None)
        if not callable(reader):
            raise HTTPException(503, "temporal fact source is unavailable")
        try:
            rows = tuple(reader(fact_id))
        except FactNotFoundError:
            raise
        except Exception as exc:
            raise HTTPException(503, "temporal fact source is unavailable") from exc
        if not rows or not all(isinstance(row, TemporalFactRevision) for row in rows):
            raise HTTPException(503, "temporal fact source returned an invalid result")
        if any(not _fact_matches_scope(row, scope) for row in rows):
            raise PermissionError("fact is outside authorized scope")
        lineage_refs, lineage_edges, lineage_errors = _lineage_material(rows, store=store)
        chain = _lineage_chain(rows)
        history_hash = _projection_hash(
            {
                "fact_id": fact_id,
                "scope": scope.model_dump(mode="json"),
                "versions": [row.model_dump(mode="json") for row in rows],
            }
        )
        return {
            "contract_id": "kjds-temporal-fact-versions-v1",
            "status": "ready",
            "quality_state": "VALID",
            "fact_id": fact_id,
            "scope": scope.model_dump(mode="json"),
            "as_of": cutoff.isoformat(),
            "version_count": len(rows),
            "current_revision": rows[-1].revision,
            "versions": [row.model_dump(mode="json") for row in rows],
            "lineage": [item.model_dump(mode="json") for item in lineage_refs],
            "lineage_edges": _serialize_edges(lineage_edges),
            "lineage_errors": list(lineage_errors),
            "lineage_chain": chain.model_dump(mode="json") if chain else None,
            "replay": {
                "mode": "historical_replay",
                "as_of": cutoff.isoformat(),
                "history_sha256": history_hash,
            },
            "external_write_allowed": False,
        }

    return run(query)


@router.get("/v1/facts/{fact_id}/lineage")
def fact_lineage(
    fact_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    entity_ref: str,
    store_ref: str = "ozon-primary",
    revision: int | None = None,
    as_of: str | None = None,
):
    """Return one authorized fact revision and its auditable source path.

    This is deliberately read-only.  ``as_of`` selects what was knowable at
    the historical cutoff; ``revision`` selects an explicit immutable
    revision.  Supplying both is rejected so a caller cannot mistake a later
    revision for the historical one.
    """

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    if revision is not None and revision < 1:
        raise HTTPException(422, "revision must be at least 1")
    cutoff = _timestamp(as_of)
    scope = _scope(principal, entity_ref, store_ref, as_of=cutoff)

    def query():
        store = getattr(runtime, "temporal_fact_store", None)
        get_reader = getattr(store, "get", None)
        historical_reader = getattr(store, "get_as_of", None)
        if not callable(get_reader):
            raise HTTPException(503, "temporal fact source is unavailable")
        try:
            if revision is not None and as_of is not None:
                raise ValueError("revision and as_of cannot be supplied together")
            if as_of is not None:
                if not callable(historical_reader):
                    raise HTTPException(503, "temporal fact source does not support historical reads")
                fact = historical_reader(fact_id, cutoff)
            else:
                fact = get_reader(fact_id, revision=revision)
        except FactNotFoundError:
            raise
        except HTTPException:
            raise
        except ValueError:
            raise
        except Exception as exc:
            raise HTTPException(503, "temporal fact source is unavailable") from exc
        if not isinstance(fact, TemporalFactRevision):
            raise HTTPException(503, "temporal fact source returned an invalid result")
        if not _fact_matches_scope(fact, scope):
            raise PermissionError("fact is outside authorized scope")
        refs, edges, lineage_errors = _lineage_material((fact,), store=store)
        query_result = TemporalFactQueryResult(
            as_of=cutoff,
            items=(fact,),
            quality_state=fact.quality_state,
        )
        envelope = _transparency(
            query_result,
            scope=scope,
            lineage_edges=edges,
        )
        path = _fact_drilldown_path(fact)
        result_hash = _projection_hash(
            {
                "fact": fact.model_dump(mode="json"),
                "scope": scope.model_dump(mode="json"),
                "as_of": cutoff.isoformat(),
                "lineage": [ref.model_dump(mode="json") for ref in refs],
                "lineage_edges": _serialize_edges(edges),
            }
        )
        return {
            "contract_id": "kjds-temporal-fact-lineage-v1",
            "status": _STATUS_BY_QUALITY[fact.quality_state],
            "quality_state": fact.quality_state.value,
            "fact_id": fact.fact_id,
            "revision": fact.revision,
            "scope": scope.model_dump(mode="json"),
            "as_of": cutoff.isoformat(),
            "fact": fact.model_dump(mode="json"),
            "lineage": [ref.model_dump(mode="json") for ref in refs],
            "lineage_edges": _serialize_edges(edges),
            "lineage_errors": list(lineage_errors),
            "lineage_chain": _lineage_chain((fact,)).model_dump(mode="json"),
            "drilldown_path": path.model_dump(mode="json"),
            "lineage_audit": envelope.lineage_audit(),
            "transparency": envelope.model_dump(mode="json"),
            "replay": {
                "mode": "historical_replay" if as_of is not None else "current_snapshot",
                "as_of": cutoff.isoformat(),
                "revision_id": fact.revision_id,
                "result_sha256": result_hash,
            },
            "external_write_allowed": False,
        }

    return run(query)


@router.post("/v1/facts/{fact_id}/restate")
def restate_fact(
    fact_id: str,
    body: RestateFactInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    scope = _scope(principal, body.entity_ref, body.store_ref)
    def mutate():
        current = runtime.temporal_fact_store.get(fact_id)
        if current.scope != scope:
            raise PermissionError("fact is outside authorized scope")
        updated = runtime.temporal_fact_store.restate(
            fact_id,
            body.payload,
            correction_reason=body.correction_reason,
            observed_time=body.observed_time,
            event_time=body.event_time,
            effective_time=body.effective_time,
            settled_time=body.settled_time,
            fresh_until=body.fresh_until,
            quality_state=body.quality_state,
            lineage=body.lineage,
            source_version=body.source_version,
            causation_id=body.causation_id,
            correlation_id=body.correlation_id,
            idempotency_key=body.idempotency_key,
            metadata=body.metadata,
            # The authenticated actor is the only authoritative recorder;
            # caller-supplied identity is retained only as an ignored legacy
            # compatibility field in the transport model.
            created_by=principal.actor_id,
        )
        return updated.model_dump(mode="json")
    return run(mutate)
