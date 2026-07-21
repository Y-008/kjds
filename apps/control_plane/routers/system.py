from __future__ import annotations

import os
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends

from ..api_contracts import (
    API_SCHEMA_VERSION,
    APP_VERSION,
    KillSwitchInput,
    LoopValidationInput,
    RecommendationInput,
    current_principal,
    ensure_role,
    run,
)
from ..database import database_health
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


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
    return run(lambda: runtime.automation.sync_ollama_models(runtime.providers["ollama"]))


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
