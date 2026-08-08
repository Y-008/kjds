from __future__ import annotations

import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..api_contracts import (
    API_SCHEMA_VERSION,
    APP_VERSION,
    AnomalyScanInput,
    EvidenceOpsPlanInput,
    GlobalExpertTaskRouteInput,
    KillSwitchInput,
    LoopValidationInput,
    OperatingTaskTransitionInput,
    RecommendationInput,
    ScopeGrantEventInput,
    ScopeGrantSourceReviewInput,
    TeamControlAdvanceInput,
    TeamControlBriefOutput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..database import database_health
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


def _scope_context(
    principal: Principal,
    *,
    store_ref: str,
    as_of: str | None,
) -> tuple[datetime, dict]:
    ensure_store_scope(principal, store_ref)
    authority_checked_at = datetime.now(UTC)
    if as_of is None:
        data_cutoff = authority_checked_at
    else:
        try:
            data_cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="as_of must be an ISO-8601 timestamp",
            ) from exc
        if data_cutoff.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="as_of must include a timezone",
            )
        data_cutoff = data_cutoff.astimezone(UTC)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=authority_checked_at,
    )
    return data_cutoff, entity_scope


@router.get("/health")
def health() -> dict:
    try:
        database = database_health()
        events = runtime.repo.event_count()
        write_safety = asdict(runtime.kill_switch.current())
        status = "ok"
    except Exception as exc:
        database = {"status": "error", "detail": type(exc).__name__}
        events = None
        write_safety = {"engaged": None, "detail": "unavailable"}
        status = "degraded"
    return {
        "status": status,
        "service": "kjds-control-plane",
        "version": APP_VERSION,
        "database": database,
        "events": events,
        "security": {"api_identity_configured": runtime.authenticator.configured, "write_safety": write_safety},
    }


@router.get("/version")
def version() -> dict:
    return {
        "service": "kjds-control-plane",
        "version": APP_VERSION,
        "schema_version": API_SCHEMA_VERSION,
        "database_provider": os.getenv("KJDS_DATABASE_PROVIDER", "local-postgres"),
        "shadow_mode": runtime.automation.shadow_mode,
        "api_identity_configured": runtime.authenticator.configured,
    }


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok", "service": "kjds-control-plane", "version": APP_VERSION}


@router.get("/health/ready")
def ready() -> dict:
    return health()


@router.get("/v1/integrations/health")
def integration_health(principal: Annotated[Principal, Depends(current_principal)]) -> dict:
    ensure_role(principal, "operator", "monitor", "reviewer", "admin")
    return {name: asdict(provider.healthcheck()) for name, provider in runtime.providers.items()}


@router.get("/v1/loop-engineering/registry")
def loop_engineering_registry(principal: Annotated[Principal, Depends(current_principal)]) -> dict:
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "monitor", "admin")
    return runtime.loop_engineering.registry_snapshot()


@router.post("/v1/loop-engineering/validate")
def validate_loop_engineering(
    body: LoopValidationInput, principal: Annotated[Principal, Depends(current_principal)]
) -> dict:
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "admin")
    return run(
        lambda: runtime.loop_engineering.validate(module=body.module, mode=body.mode, controls=body.controls).to_dict()
    )


@router.get("/v1/global-expert-team/registry")
def global_expert_team_registry(
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    return runtime.global_expert_team.snapshot()


@router.post("/v1/global-expert-team/route")
def route_global_expert_task(
    body: GlobalExpertTaskRouteInput,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "admin",
    )
    return run(lambda: runtime.global_expert_team.route(**body.model_dump()))


@router.get("/v1/team-control/brief", response_model=TeamControlBriefOutput)
def team_control_brief(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.team_control_tower.brief(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
    )


@router.post("/v1/team-control/advance")
def advance_team_control(
    body: TeamControlAdvanceInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
) -> dict:
    ensure_role(principal, "operator", "admin")
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=None,
    )
    return run(
        lambda: runtime.team_control_tower.advance(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            **body.model_dump(),
        )
    )


@router.get("/v1/operating-workbench/briefing")
def operating_workbench_briefing(
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 20,
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
) -> dict:
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "monitor", "admin")
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.operating_workbench.snapshot(
            limit=limit,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff.isoformat(),
        )
    )


@router.get("/v1/operating-analytics/snapshot")
def operating_analytics_snapshot(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.operating_analytics.snapshot(
            store_ref=store_ref,
            principal=principal,
            entity_scope=entity_scope,
            as_of=cutoff.isoformat(),
        )
    )


@router.get("/v1/capability-atlas/snapshot")
def capability_atlas_snapshot(
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    return run(runtime.cross_border_capability_atlas.snapshot)


@router.get("/v1/truth-governance/snapshot")
def truth_governance_snapshot(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    evidence_id: Annotated[list[str] | None, Query()] = None,
    sku: str | None = None,
    order_id: str | None = None,
    currency: str = "CNY",
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    ensure_store_scope(principal, store_ref)
    return run(
        lambda: runtime.truth_governance.snapshot(
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
            evidence_ids=evidence_id,
            sku=sku,
            order_id=order_id,
            currency=currency,
        )
    )


@router.get("/v1/scope-grants/current")
def current_scope_grant(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    subject_actor_id: str | None = None,
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    ensure_store_scope(principal, store_ref)
    subject = principal
    if subject_actor_id and subject_actor_id != principal.actor_id:
        ensure_role(
            principal,
            "reviewer",
            "compliance",
            "risk",
            "monitor",
            "admin",
        )
        subject = runtime.authenticator.resolve_actor(subject_actor_id)
        if (
            subject.tenant_ref != principal.tenant_ref
            or not subject.can_access_store(store_ref)
        ):
            raise HTTPException(
                403,
                "Requested subject is outside authorized tenant/store scope",
            )
    cutoff = runtime.truth_governance._as_of(as_of)
    return run(
        lambda: runtime.scope_grants.current(
            principal=subject,
            store_ref=store_ref,
            as_of=cutoff,
        )
    )


@router.get("/v1/scope-grants/intake")
def scope_grant_intake(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    entity_ref: str | None = None,
    event_type: str = "grant",
    as_of: str | None = None,
    subject_actor_id: str | None = None,
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    ensure_store_scope(principal, store_ref)
    subject = principal
    if subject_actor_id and subject_actor_id != principal.actor_id:
        ensure_role(principal, "monitor", "admin")
        subject = runtime.authenticator.resolve_actor(subject_actor_id)
        if (
            subject.tenant_ref != principal.tenant_ref
            or not subject.can_access_store(store_ref)
        ):
            raise HTTPException(
                403,
                "Requested subject is outside authorized tenant/store scope",
            )
    cutoff = runtime.truth_governance._as_of(as_of)
    return run(
        lambda: runtime.scope_grants.intake(
            principal=principal,
            subject=subject,
            store_ref=store_ref,
            entity_ref=entity_ref,
            event_type=event_type,
            as_of=cutoff,
        )
    )


@router.get("/v1/scope-grants/events")
def scope_grant_events(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    subject_actor_id: str | None = None,
) -> list[dict]:
    ensure_role(principal, "reviewer", "compliance", "risk", "admin")
    ensure_store_scope(principal, store_ref)
    return run(
        lambda: runtime.scope_grants.events(
            principal=principal,
            store_ref=store_ref,
            subject_actor_id=subject_actor_id,
        )
    )


@router.post("/v1/scope-grants/events")
def record_scope_grant_event(
    body: ScopeGrantEventInput,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    ensure_role(principal, "compliance", "admin")
    ensure_store_scope(principal, body.store_ref)
    return run(
        lambda: runtime.scope_grants.record(
            principal=principal,
            **body.model_dump(),
        )
    )


@router.post("/v1/scope-grants/preflight")
def preflight_scope_grant_event(
    body: ScopeGrantEventInput,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    ensure_role(principal, "compliance", "admin")
    ensure_store_scope(principal, body.store_ref)
    return run(
        lambda: runtime.scope_grants.preflight(
            principal=principal,
            **body.model_dump(),
        )
    )


@router.post("/v1/scope-grants/evidence/reviews")
def review_scope_grant_source(
    body: ScopeGrantSourceReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    ensure_role(principal, "reviewer", "compliance", "risk", "admin")
    ensure_store_scope(principal, body.store_ref)
    return run(
        lambda: runtime.scope_grants.review_source(
            principal=principal,
            **body.model_dump(),
        )
    )


@router.get("/v1/operating-workspaces/{kind}/{item_id}")
def operating_workspace_snapshot(
    kind: str,
    item_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.operating_workspace.snapshot(
            kind=kind,
            item_id=item_id,
            store_ref=store_ref,
            principal=principal,
            entity_scope=entity_scope,
            as_of=cutoff.isoformat(),
        )
    )


@router.get("/v1/profit-ledger")
def profit_ledger(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    sku: str | None = None,
    order_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    grain: str = "order",
    currency: str = "CNY",
    as_of: str | None = None,
    query: str | None = None,
    page_size: int = 100,
    cursor: str | None = None,
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.profit_ledger.snapshot(
            store_ref=store_ref,
            sku=sku,
            order_id=order_id,
            date_from=date_from,
            date_to=date_to,
            grain=grain,
            currency=currency,
            as_of=cutoff.isoformat(),
            principal=principal,
            entity_scope=entity_scope,
            query=query,
            page_size=page_size,
            cursor=cursor,
        )
    )


@router.get("/v1/profit-ledger/erosion")
def profit_erosion(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    sku: str | None = None,
    order_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    grain: str = "order",
    currency: str = "CNY",
    as_of: str | None = None,
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.profit_ledger.erosion(
            store_ref=store_ref,
            sku=sku,
            order_id=order_id,
            date_from=date_from,
            date_to=date_to,
            grain=grain,
            currency=currency,
            as_of=cutoff.isoformat(),
            principal=principal,
            entity_scope=entity_scope,
        )
    )


@router.get("/v1/operating-intelligence/metrics")
@router.get("/v1/metrics")
def operating_metric_registry(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return runtime.operating_intelligence.metrics(
        store_ref=store_ref,
        principal=principal,
        entity_scope=entity_scope,
        as_of=cutoff.isoformat(),
    )


@router.post("/v1/operating-intelligence/anomaly-scans", status_code=201)
@router.post("/v1/anomaly-scans", status_code=201)
def scan_operating_anomalies(
    body: AnomalyScanInput,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    ensure_role(principal, "operator", "reviewer", "monitor", "admin")
    cutoff, _ = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=body.as_of,
    )
    _, entity_scope = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )
    return run(
        lambda: runtime.operating_intelligence.scan(
            store_ref=body.store_ref,
            actor_id=principal.actor_id,
            as_of=cutoff.isoformat(),
            principal=principal,
            entity_scope=entity_scope,
        )
    )


@router.get("/v1/anomaly-scans")
def list_anomaly_scans(
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 50,
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
) -> list[dict]:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.operating_intelligence.scans(
            limit=limit,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff.isoformat(),
        )
    )


@router.get("/v1/operating-tasks")
def list_operating_tasks(
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 100,
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
) -> list[dict]:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.operating_intelligence.tasks(
            limit=limit,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff.isoformat(),
        )
    )


@router.post("/v1/operating-tasks/{task_id}/events", status_code=201)
def transition_operating_task(
    task_id: str,
    body: OperatingTaskTransitionInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
) -> dict:
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    _, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=None,
    )
    return run(
        lambda: runtime.operating_intelligence.append_task_event(
            task_id,
            event_type=body.event_type,
            reason=body.reason,
            evidence_ids=body.evidence_ids,
            actor_id=principal.actor_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
    )


@router.get("/v1/operating-tasks/{task_id}/events")
def operating_task_events(
    task_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
) -> list[dict]:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    _, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.operating_intelligence.task_events(
            task_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
    )


@router.post("/v1/evidenceops/plan")
def evidenceops_plan(
    body: EvidenceOpsPlanInput,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )
    return run(
        lambda: runtime.evidenceops_copilot.plan(
            objective=body.objective,
            store_ref=body.store_ref,
            principal=principal,
            entity_scope=entity_scope,
            as_of=cutoff.isoformat(),
        )
    )


@router.get("/v1/system/kill-switch")
def kill_switch_state():
    return asdict(runtime.kill_switch.current())


@router.post("/v1/system/kill-switch/engage")
def engage_kill_switch(body: KillSwitchInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "risk", "admin")
    return asdict(runtime.kill_switch.set_state(engaged=True, reason=body.reason, actor_id=principal.actor_id))


@router.post("/v1/system/kill-switch/release")
def release_kill_switch(body: KillSwitchInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "admin")
    return asdict(runtime.kill_switch.set_state(engaged=False, reason=body.reason, actor_id=principal.actor_id))


@router.post("/v1/models/discover")
def discover_models(principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    provider = runtime.providers.get("ollama")
    if provider is None:
        raise HTTPException(status_code=503, detail="ollama is not configured")
    return run(lambda: runtime.automation.sync_ollama_models(provider))


@router.get("/v1/models")
def list_models():
    return run(runtime.automation.list_models)


@router.post("/v1/recommendations", status_code=201)
def create_recommendation(body: RecommendationInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.automation.create_recommendation(**body.model_dump()))


@router.get("/v1/recommendations")
def list_recommendations():
    return run(runtime.automation.list_recommendations)
