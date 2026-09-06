"""Read-only analytics, lineage, liveness and economic projections.

These endpoints compile bounded projections from canonical contracts.  They do
not execute marketplace actions or silently turn missing operational evidence
into a healthy result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from ..analytics_query_plan import (
    compare_analytics_results,
    comparison_period,
    compile_query_plan,
    evaluate_data_product_gate,
    execute_analytics_plan,
)
from ..api_contracts import current_principal, ensure_role, ensure_store_scope, run
from ..data_fabric_contracts import AnalysisRecipe, PeriodRef, ScopeRef
from ..data_fabric_registry import load_data_product_registry
from ..economic_guard_service import EconomicGuardInput, evaluate_economic_guard
from ..runtime import runtime
from ..security import Principal
from ..stuck_task_detector import (
    RECOVERY_PLAN_VERSION,
    TaskLivenessObservation,
    detect_stuck_tasks,
)
from ..temporal_fact_store import QualityState, TemporalFactQueryResult
from ..transparency_envelope import TransparencyEnvelope

router = APIRouter()


def _time(value: str | None, name: str, default: datetime | None = None) -> datetime:
    if value is None:
        if default is None:
            raise HTTPException(422, f"{name} is required")
        return default
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise HTTPException(422, f"{name} must include timezone")
    parsed = parsed.astimezone(UTC)
    if name in {"as_of", "end_at"} and parsed > datetime.now(UTC):
        raise HTTPException(422, f"{name} cannot be in the future")
    return parsed


def _recipe(
    recipe_id: str,
    principal: Principal,
    *,
    entity_id: str,
    store_id: str,
    metric: tuple[str, ...],
    dimension: tuple[str, ...],
    compare_with: tuple[str, ...] = (),
    start_at: str | None,
    end_at: str | None,
    as_of: str | None,
) -> AnalysisRecipe:
    now = datetime.now(UTC)
    start = _time(start_at, "start_at", now - timedelta(days=30))
    end = _time(end_at, "end_at", now)
    cutoff = _time(as_of, "as_of", end)
    # ``Principal`` currently carries tenant and store scope; entity scope is
    # supplied by the authenticated scope-grant projection in deployments
    # that bind one.  Keep compatibility with those richer principals without
    # dereferencing a field that is absent from the base identity contract.
    authorized_entity = getattr(principal, "entity_ref", None)
    authorized_entities = getattr(principal, "entity_refs", None)
    if authorized_entity and entity_id != authorized_entity:
        raise HTTPException(403, "entity is outside principal scope")
    if authorized_entities and entity_id not in set(authorized_entities):
        raise HTTPException(403, "entity is outside principal scope")
    ensure_store_scope(principal, store_id)
    scope_authority = getattr(runtime, "scope_grants", None)
    current_grant = getattr(scope_authority, "current", None)
    if not callable(current_grant):
        raise HTTPException(403, "current entity scope authority is unavailable")
    try:
        grant = current_grant(principal=principal, store_ref=store_id, as_of=cutoff)
    except (KeyError, PermissionError, RuntimeError, ValueError) as exc:
        raise HTTPException(403, "entity is outside the current authorized scope") from exc
    if (
        not isinstance(grant, Mapping)
        or grant.get("status") != "ready"
        or grant.get("entity_ref") != entity_id
    ):
        raise HTTPException(403, "entity is outside the current authorized scope")
    return AnalysisRecipe(
        recipe_id=recipe_id,
        version="1",
        scope=ScopeRef(tenant_id=principal.tenant_ref, entity_id=entity_id, store_ids=(store_id,)),
        period=PeriodRef(
            period_type="custom",
            start_at=start,
            end_at=end,
            timezone="UTC",
            currency="USD",
            as_of=cutoff,
        ),
        dimensions=dimension,
        metrics=metric,
        compare_with=compare_with,
    )


def _query_temporal_facts(
    recipe: AnalysisRecipe,
    *,
    period: PeriodRef | None = None,
) -> tuple[TemporalFactQueryResult | None, str | None]:
    """Read the canonical temporal adapter for one analytics recipe.

    The helper keeps adapters interchangeable in tests and local deployments,
    while preserving the distinction between an empty result and an adapter
    outage.  No fallback fabricates rows or turns a failed read into ``VALID``.
    """

    target_period = period or recipe.period
    store = getattr(runtime, "temporal_fact_store", None)
    query_as_of = getattr(store, "query_as_of", None)
    try:
        if callable(query_as_of):
            result = query_as_of(
                target_period.as_of,
                scope=recipe.scope,
                event_start=target_period.start_at,
                event_end=target_period.end_at,
                include_stale=True,
            )
            if not isinstance(result, TemporalFactQueryResult):
                raise TypeError("temporal adapter returned an invalid query result")
            return result, None

        as_of = getattr(store, "as_of", None)
        if not callable(as_of):
            return None, "temporal_fact_source_not_bound"
        facts = tuple(
            as_of(
                target_period.as_of,
                scope=recipe.scope,
                event_start=target_period.start_at,
                event_end=target_period.end_at,
                include_stale=True,
            )
        )
        quality = QualityState.NO_DATA
        if facts:
            quality = QualityState.VALID
            if any(item.quality_state == QualityState.BLOCKED for item in facts):
                quality = QualityState.BLOCKED
            elif any(item.quality_state == QualityState.UNKNOWN_OUTCOME for item in facts):
                quality = QualityState.UNKNOWN_OUTCOME
            elif any(item.quality_state == QualityState.STALE for item in facts):
                quality = QualityState.STALE
            elif any(item.quality_state == QualityState.PARTIAL for item in facts):
                quality = QualityState.PARTIAL
        return TemporalFactQueryResult(
            as_of=target_period.as_of,
            items=facts,
            quality_state=quality,
        ), None
    except Exception:
        # Keep implementation details out of the public response, but retain
        # a stable diagnostic code so operators can distinguish an empty
        # period from an unavailable source.
        return None, "temporal_fact_source_unavailable"


def _quality_for_source_error(source_error: str | None) -> QualityState:
    """Map an adapter problem to a quality state without inventing ``NO_DATA``.

    ``NO_DATA`` means the canonical source was successfully queried and
    returned no rows.  An unbound or failing adapter leaves the result
    unknowable, so projections must remain blocked until the source is
    repaired.  Keeping this mapping in one place prevents drill-down and
    lineage from silently disagreeing about the same outage.
    """

    return QualityState.BLOCKED if source_error else QualityState.NO_DATA


def _analytics_transparency(
    result: TemporalFactQueryResult,
    recipe: AnalysisRecipe,
    compiled: Any,
) -> TransparencyEnvelope:
    """Build the auditable lineage projection for a query result."""

    lineage_edges = []
    edge_reader = getattr(runtime.temporal_fact_store, "lineage_edges", None)
    if callable(edge_reader):
        for fact in result.items:
            try:
                lineage_edges.extend(edge_reader(fact.fact_id, revision=fact.revision))
            except Exception:
                # A missing optional edge adapter does not erase fact lineage;
                # the envelope remains truthful with an empty edge list.
                continue
    source_watermarks: dict[str, str] = {}
    for fact in result.items:
        previous = source_watermarks.get(fact.source_system)
        observed = fact.observed_time.isoformat()
        if previous is None or observed > previous:
            source_watermarks[fact.source_system] = observed
    formula_version = ";".join(
        f"{metric}:{compiled.metric_versions[metric]}"
        for metric in compiled.metrics
    )
    envelope = TransparencyEnvelope.from_query_result(
        result,
        dataset=f"analytics.{recipe.recipe_id}.v1",
        scope=recipe.scope,
        authority_hash="temporal-fact-store",
        formula_version=formula_version or None,
        source_watermarks=source_watermarks,
        next_action=(
            None
            if result.quality_state == QualityState.VALID
            else "refresh_or_reconcile_temporal_facts"
        ),
    )
    # ``from_query_result`` intentionally keeps its compact constructor stable;
    # attach typed edges only after the fact projection has been validated.
    return envelope.model_copy(update={"lineage_edges": tuple(lineage_edges)})


def _blocked_query_result(recipe: AnalysisRecipe, reason: str) -> TemporalFactQueryResult:
    """Create an empty, explicit blocked projection for a failed read gate."""

    return TemporalFactQueryResult(
        as_of=recipe.period.as_of,
        items=(),
        quality_state=QualityState.BLOCKED,
        exclusion_reasons=(reason,),
    )


def _run_analytics_recipe(
    recipe: AnalysisRecipe,
    compiled: Any,
) -> dict[str, Any]:
    """Read and aggregate one recipe plus its requested comparison periods."""

    try:
        products = tuple(load_data_product_registry())
        registry_error = None
    except Exception:
        products = ()
        registry_error = "data_product_registry_unavailable"
    gate = evaluate_data_product_gate(compiled, products)
    if registry_error is not None:
        gate = dict(gate)
        gate["status"] = "BLOCKED"
        gate["verified"] = False
        gate["reasons"] = sorted(set((*gate.get("reasons", ()), registry_error)))

    if not gate["verified"]:
        query_result = _blocked_query_result(
            recipe,
            "data_product_gate_blocked",
        )
        execution = execute_analytics_plan(
            compiled,
            (),
            data_products=products,
            source_error="data_product_gate_blocked",
            source_quality_state=QualityState.BLOCKED.value,
        )
        source_error = "data_product_gate_blocked"
    else:
        query_result, source_error = _query_temporal_facts(recipe)
        if query_result is None:
            query_result = _blocked_query_result(
                recipe,
                source_error or "temporal_fact_source_unavailable",
            )
            execution = execute_analytics_plan(
                compiled,
                (),
                data_products=products,
                source_error=source_error or "temporal_fact_source_unavailable",
                source_quality_state=QualityState.BLOCKED.value,
            )
        else:
            execution = execute_analytics_plan(
                compiled,
                query_result.items,
                data_products=products,
                source_quality_state=query_result.quality_state.value,
            )

    comparisons: dict[str, dict[str, Any]] = {}
    for relation in recipe.compare_with:
        comparison_window = comparison_period(recipe.period, relation)
        comparison_recipe = recipe.model_copy(update={"period": comparison_window})
        comparison_plan = compile_query_plan(comparison_recipe)
        if not gate["verified"]:
            comparison_query = _blocked_query_result(
                comparison_recipe,
                "data_product_gate_blocked",
            )
            comparison_execution = execute_analytics_plan(
                comparison_plan,
                (),
                data_products=products,
                source_error="data_product_gate_blocked",
                source_quality_state=QualityState.BLOCKED.value,
            )
        else:
            comparison_query, comparison_error = _query_temporal_facts(
                recipe,
                period=comparison_window,
            )
            if comparison_query is None:
                comparison_query = _blocked_query_result(
                    comparison_recipe,
                    comparison_error or "temporal_fact_source_unavailable",
                )
                comparison_execution = execute_analytics_plan(
                    comparison_plan,
                    (),
                    data_products=products,
                    source_error=comparison_error or "temporal_fact_source_unavailable",
                    source_quality_state=QualityState.BLOCKED.value,
                )
            else:
                comparison_execution = execute_analytics_plan(
                    comparison_plan,
                    comparison_query.items,
                    data_products=products,
                    source_quality_state=comparison_query.quality_state.value,
                )
        comparison = compare_analytics_results(
            execution,
            comparison_execution,
            relation=relation,
        )
        comparison["execution"] = comparison_execution.as_dict()
        comparison["fact_quality_state"] = comparison_query.quality_state.value
        comparisons[relation] = comparison

    return {
        "products": products,
        "gate": gate,
        "execution": execution,
        "query_result": query_result,
        "source_error": source_error,
        "comparisons": comparisons,
    }


def _heartbeat_timestamp(value: object) -> datetime | None:
    """Parse a persisted heartbeat timestamp without inventing freshness."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        # The liveness detector treats a missing timestamp as expired.  Do
        # not discard the observation or substitute ``now`` when a producer
        # emitted malformed data.
        return None


def _payload_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _heartbeat_observation(row: Mapping[str, object]) -> TaskLivenessObservation:
    """Project one durable PM heartbeat into the watchdog's pure contract."""

    payload = _payload_mapping(row.get("payload"))
    liveness = _payload_mapping(payload.get("liveness"))
    # Newer producers can provide an explicit task state; older PM heartbeats
    # only have a decision status.  The mapping keeps legacy rows observable
    # while preserving the detector's active/terminal vocabulary.
    raw_state = liveness.get("state") or payload.get("task_state") or payload.get("state")
    if raw_state is None:
        raw_state = row.get("status")
    state = str(raw_state or "unknown").strip().lower()
    state_aliases = {
        "dispatch": "running",
        "hold": "paused",
        "isolate": "blocked",
        "success": "completed",
        "passed": "completed",
        "done": "completed",
    }
    state = state_aliases.get(state, state)

    # Missing consumer identity is evidence of an unowned task, not proof that
    # the project manager consumed it.
    consumer = liveness.get("consumer_id") or payload.get("consumer_id")
    readback = liveness.get("external_readback_state") or payload.get("external_readback_state")
    readback_value = str(readback).strip().lower() if readback is not None else None
    if readback_value not in {"passed", "failed", "unknown", "pending"}:
        readback_value = None
    # An isolated heartbeat is intentionally treated as an unresolved remote
    # outcome until a reconciliation signal says otherwise.  This prevents a
    # terminal-looking row from being reported healthy merely because it has
    # no explicit error string.
    readback_required = bool(
        liveness.get("external_readback_required")
        or payload.get("external_readback_required")
        or state == "blocked" and str(row.get("status", "")).lower() == "isolate"
    )
    evidence_refs_value = liveness.get("evidence_refs") or payload.get("evidence_refs") or ()
    evidence_refs = tuple(
        str(item).strip()
        for item in evidence_refs_value
        if isinstance(item, str) and item.strip()
    ) if isinstance(evidence_refs_value, (list, tuple, set, frozenset)) else ()
    duplicate_value = liveness.get("duplicate_execution_count") or payload.get("duplicate_execution_count") or 0
    try:
        duplicate_count = int(duplicate_value)
    except (TypeError, ValueError):
        duplicate_count = -1
    return TaskLivenessObservation(
        task_ref=str(row.get("project_id") or row.get("heartbeat_id") or "unknown-task"),
        state=state,
        last_heartbeat=_heartbeat_timestamp(row.get("heartbeat_at") or row.get("observed_at")),
        deadline=_heartbeat_timestamp(row.get("liveness_deadline")),
        progress_cursor=(
            str(row["progress_cursor"]) if row.get("progress_cursor") is not None else liveness.get("progress_cursor")
        ),
        expected_next_event=(
            str(row["expected_next_event"])
            if row.get("expected_next_event") is not None
            else liveness.get("expected_next_event")
        ),
        consumer_id=str(consumer) if consumer is not None else None,
        liveness_deadline=_heartbeat_timestamp(row.get("liveness_deadline")),
        progress_updated_at=_heartbeat_timestamp(
            liveness.get("progress_updated_at") or payload.get("progress_updated_at")
        ),
        lease_expires_at=_heartbeat_timestamp(
            liveness.get("lease_expires_at") or payload.get("lease_expires_at")
        ),
        external_readback_state=readback_value,  # type: ignore[arg-type]
        external_readback_required=readback_required,
        evidence_refs=evidence_refs,
        evidence_required=bool(liveness.get("evidence_required") or payload.get("evidence_required")),
        idempotency_key=(str(row["idempotency_key"]) if row.get("idempotency_key") else None),
        duplicate_execution_count=duplicate_count,
        compensation_action=(
            str(row["compensation_action"])
            if row.get("compensation_action")
            else None
        ),
        recovery_ref=str(row["recovery_ref"]) if row.get("recovery_ref") else None,
    )


@router.get("/v1/analytics/{recipe}/drilldown")
def analytics_drilldown(
    recipe: str,
    principal: Annotated[Principal, Depends(current_principal)],
    entity_id: str,
    store_id: str = "ozon-primary",
    metric: tuple[str, ...] = ("net_sales",),
    dimension: tuple[str, ...] = ("store", "sku"),
    compare_with: tuple[str, ...] = (),
    start_at: str | None = None,
    end_at: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")

    def project():
        recipe_contract = _recipe(
            recipe,
            principal,
            entity_id=entity_id,
            store_id=store_id,
            metric=metric,
            dimension=dimension,
            compare_with=compare_with,
            start_at=start_at,
            end_at=end_at,
            as_of=as_of,
        )
        compiled = compile_query_plan(recipe_contract)
        projection = _run_analytics_recipe(recipe_contract, compiled)
        query_result = projection["query_result"]
        execution = projection["execution"]
        source_error = projection["source_error"]
        facts = query_result.items
        transparency = _analytics_transparency(query_result, recipe_contract, compiled)
        quality_state = execution.quality_state
        rows = [item.model_dump(mode="json") for item in facts]
        status = quality_state
        return {
            "contract_id": "kjds-analytics-drilldown-v1",
            "status": status,
            "reason": source_error or (None if rows else "no_facts_at_as_of"),
            "plan": compiled.model_dump(mode="json"),
            "period": recipe_contract.period.model_dump(mode="json"),
            "levels": ["entity", "store", "warehouse", "sku", "order", "evidence"],
            "rows": rows,
            "quality_state": status,
            "fact_quality_state": query_result.quality_state.value,
            "included_count": execution.included_count,
            "excluded_count": execution.excluded_count,
            "aggregation": execution.as_dict(),
            "aggregates": list(execution.aggregates),
            "comparisons": projection["comparisons"],
            "data_product_gate": projection["gate"],
            "transparency": transparency.model_dump(mode="json") if transparency else None,
            "lineage": transparency.drilldown() if transparency else [],
            "lineage_audit": transparency.lineage_audit() if transparency else {
                "lineage_complete": False,
                "lineage_structurally_complete": False,
                "lineage_missing_stages": [],
                "lineage_coverage": 0.0,
                "lineage_continuity_errors": ["transparency_unavailable"],
                "drilldown_complete": False,
                "drilldown_missing_levels": [],
                "record_contract_complete": False,
            },
            "lineage_edges": (
                [edge.model_dump(mode="json") for edge in transparency.lineage_edges]
                if transparency
                else []
            ),
            "external_write_allowed": False,
        }

    return run(project)


@router.get("/v1/analytics/{recipe}/lineage")
def analytics_lineage(
    recipe: str,
    principal: Annotated[Principal, Depends(current_principal)],
    entity_id: str,
    store_id: str = "ozon-primary",
    metric: tuple[str, ...] = ("net_sales",),
    dimension: tuple[str, ...] = ("store", "sku"),
    compare_with: tuple[str, ...] = (),
    start_at: str | None = None,
    end_at: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")

    def project():
        recipe_contract = _recipe(
            recipe,
            principal,
            entity_id=entity_id,
            store_id=store_id,
            metric=metric,
            dimension=dimension,
            compare_with=compare_with,
            start_at=start_at,
            end_at=end_at,
            as_of=as_of,
        )
        compiled = compile_query_plan(recipe_contract)
        projection = _run_analytics_recipe(recipe_contract, compiled)
        query_result = projection["query_result"]
        execution = projection["execution"]
        source_error = projection["source_error"]
        products = {item.dataset_id: item for item in projection["products"]}
        facts = query_result.items
        quality_state = execution.quality_state
        transparency = _analytics_transparency(query_result, recipe_contract, compiled)
        fact_refs = [
            {
                "id": fact.revision_id,
                "fact_id": fact.fact_id,
                "revision": fact.revision,
                "fact_type": fact.fact_type,
                "sha256": fact.content_sha256,
            }
            for fact in facts
        ]
        raw_refs = []
        if transparency:
            raw_refs = [ref.model_dump(mode="json") for ref in transparency.lineage]
        chain = []
        for dataset_id in compiled.source_datasets:
            descriptor = products.get(dataset_id)
            chain.append({
                "metric": list(compiled.metrics),
                "data_product": dataset_id,
                "descriptor": descriptor.model_dump(mode="json") if descriptor else None,
                "facts": fact_refs,
                "raw_evidence": raw_refs,
                "lineage_edges": (
                    [edge.model_dump(mode="json") for edge in transparency.lineage_edges]
                    if transparency
                    else []
                ),
                "quality_state": quality_state,
            })
        return {
            "contract_id": "kjds-analytics-lineage-v1",
            "status": quality_state,
            "reason": source_error or (None if facts else "no_facts_at_as_of"),
            "plan_hash": compiled.plan_hash,
            "period": recipe_contract.period.model_dump(mode="json"),
            "quality_state": quality_state,
            "fact_quality_state": query_result.quality_state.value,
            "included_count": execution.included_count,
            "excluded_count": execution.excluded_count,
            "aggregation": execution.as_dict(),
            "aggregates": list(execution.aggregates),
            "comparisons": projection["comparisons"],
            "data_product_gate": projection["gate"],
            "chain": chain,
            "transparency": transparency.model_dump(mode="json") if transparency else None,
            "lineage_audit": transparency.lineage_audit() if transparency else {
                "lineage_complete": False,
                "lineage_structurally_complete": False,
                "lineage_missing_stages": [],
                "lineage_coverage": 0.0,
                "lineage_continuity_errors": ["transparency_unavailable"],
                "drilldown_complete": False,
                "drilldown_missing_levels": [],
                "record_contract_complete": False,
            },
            "external_write_allowed": False,
        }

    return run(project)


@router.get("/v1/operations/stuck")
def operations_stuck(
    principal: Annotated[Principal, Depends(current_principal)],
    heartbeat_timeout_seconds: int = 300,
    entity_ref: str | None = None,
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    if heartbeat_timeout_seconds < 1 or heartbeat_timeout_seconds > 86400:
        raise HTTPException(422, "heartbeat_timeout_seconds out of range")
    if entity_ref is not None and not entity_ref.strip():
        raise HTTPException(422, "entity_ref cannot be blank")
    visible_stores: tuple[str, ...]
    if store_ref is not None:
        ensure_store_scope(principal, store_ref)
        visible_stores = (store_ref,)
    else:
        # Preserve the principal's exact store boundary.  Passing an empty
        # tuple to the adapter is deliberately fail-closed.
        visible_stores = tuple(sorted(principal.store_refs))
    cutoff = _time(as_of, "as_of", datetime.now(UTC))

    def project():
        source = getattr(runtime, "project_heartbeat_store", None)
        list_latest = getattr(source, "list_latest", None)
        if not callable(list_latest):
            return {
                "contract_id": "kjds-operations-stuck-v1",
                "recovery_contract": RECOVERY_PLAN_VERSION,
                "recovery_mode": "proposal_only",
                "status": "BLOCKED",
                "tasks": [],
                "reason": "task_liveness_observation_source_not_bound",
                "quality_state": "BLOCKED",
                "as_of": cutoff.isoformat(),
                "observed_count": 0,
                "stuck_count": 0,
                "scope": {
                    "tenant_id": principal.tenant_ref,
                    "entity_ref": entity_ref,
                    "store_refs": list(visible_stores),
                },
                "external_write_allowed": False,
            }
        try:
            rows = tuple(
                list_latest(
                    tenant_id=principal.tenant_ref,
                    entity_id=entity_ref,
                    store_refs=visible_stores,
                    observed_until=cutoff,
                )
            )
        except Exception:
            # A liveness read outage must not be represented as healthy.  Keep
            # the error surface stable and avoid exposing database details.
            return {
                "contract_id": "kjds-operations-stuck-v1",
                "recovery_contract": RECOVERY_PLAN_VERSION,
                "recovery_mode": "proposal_only",
                "status": "BLOCKED",
                "tasks": [],
                "reason": "task_liveness_observation_source_unavailable",
                "quality_state": "BLOCKED",
                "as_of": cutoff.isoformat(),
                "observed_count": 0,
                "stuck_count": 0,
                "scope": {
                    "tenant_id": principal.tenant_ref,
                    "entity_ref": entity_ref,
                    "store_refs": list(visible_stores),
                },
                "external_write_allowed": False,
            }

        observations = tuple(
            _heartbeat_observation(row)
            for row in rows
            if isinstance(row, Mapping)
        )
        if rows and not observations:
            return {
                "contract_id": "kjds-operations-stuck-v1",
                "recovery_contract": RECOVERY_PLAN_VERSION,
                "recovery_mode": "proposal_only",
                "status": "BLOCKED",
                "quality_state": "BLOCKED",
                "reason": "invalid_heartbeat_observations",
                "as_of": cutoff.isoformat(),
                "observed_count": 0,
                "stuck_count": 0,
                "tasks": [],
                "scope": {
                    "tenant_id": principal.tenant_ref,
                    "entity_ref": entity_ref,
                    "store_refs": list(visible_stores),
                },
                "external_write_allowed": False,
            }
        detected = detect_stuck_tasks(
            observations,
            now=cutoff,
            heartbeat_timeout=timedelta(seconds=heartbeat_timeout_seconds),
        )
        stuck_count = sum(item.status == "stuck" for item in detected)
        status = "BLOCKED" if stuck_count else "VALID" if detected else "NO_DATA"
        quality_state = status
        return {
            "contract_id": "kjds-operations-stuck-v1",
            "recovery_contract": RECOVERY_PLAN_VERSION,
            "recovery_mode": "proposal_only",
            "status": status,
            "quality_state": quality_state,
            "reason": None if detected else "no_heartbeat_observations",
            "as_of": cutoff.isoformat(),
            "observed_count": len(observations),
            "stuck_count": stuck_count,
            "tasks": [asdict(item) for item in detected],
            "scope": {
                "tenant_id": principal.tenant_ref,
                "entity_ref": entity_ref,
                "store_refs": list(visible_stores),
            },
            "external_write_allowed": False,
        }

    return run(project)


@router.get("/v1/economics/guard-status")
def economics_guard_status(
    principal: Annotated[Principal, Depends(current_principal)],
    cash_available: Decimal | None = None,
    min_cash: Decimal = Decimal("0"),
    margin_rate: Decimal | None = None,
    min_margin_rate: Decimal | None = None,
    budget_remaining: Decimal | None = None,
    min_budget_remaining: Decimal = Decimal("0"),
    budget_id: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    resource_budget = None
    if budget_id is not None:
        resource_budget = run(lambda: runtime.resource_budget_ledger.snapshot(
            tenant_id=principal.tenant_ref,
            budget_id=budget_id,
        ))
        # A bound ledger snapshot is authoritative; query parameters cannot
        # override it with a more favorable value.
        budget_remaining = Decimal(resource_budget["available"])
    if cash_available is None:
        response = {
            "contract_id": "kjds-economics-guard-v1",
            "status": "UNKNOWN",
            "reason": "cash_snapshot_missing",
            "reasons": ["cash_snapshot_missing"],
            "quality_state": "NO_DATA",
            "snapshot_sha256": None,
            "scope": {"tenant_id": principal.tenant_ref},
            "external_write_allowed": False,
        }
        if resource_budget is not None:
            response["resource_budget"] = resource_budget
        return response
    result = evaluate_economic_guard(EconomicGuardInput(
        cash_available=cash_available, min_cash=min_cash, margin_rate=margin_rate,
        min_margin_rate=min_margin_rate, budget_remaining=budget_remaining,
        min_budget_remaining=min_budget_remaining,
    ))
    quality_state = "VALID" if result.status == "allowed" else "BLOCKED"
    response = {"contract_id": "kjds-economics-guard-v1", "status": result.status.upper(),
                "reasons": list(result.reasons), "snapshot_sha256": result.snapshot_sha256,
                "quality_state": quality_state, "external_write_allowed": False}
    if resource_budget is not None:
        response["resource_budget"] = resource_budget
    return response
