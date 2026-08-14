from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ..api_contracts import current_principal, ensure_role, run
from ..media_connectors import CONTRACT_ID, MediaConnectorConflictError
from ..runtime import runtime
from ..security import Principal

router = APIRouter()

Provider = Literal[
    "codex_oauth", "comfyui", "ffmpeg", "remotion", "windows_agent"
]
DeploymentMode = Literal["customer_local", "hosted_isolated"]
Health = Literal[
    "ENROLLING",
    "READY",
    "BUSY",
    "LOGIN_REQUIRED",
    "LIMITED",
    "OFFLINE",
    "ERROR",
    "REVOKED",
]
ObservableHealth = Literal[
    "READY", "BUSY", "LOGIN_REQUIRED", "LIMITED", "OFFLINE", "ERROR"
]
RateStatus = Literal["ok", "limited", "unknown"]


class RegistrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Provider
    deployment_mode: DeploymentMode
    protocol_version: str = Field(min_length=1, max_length=80)
    capabilities: list[str] = Field(min_length=1, max_length=16)
    concurrency_limit: Literal[1] = 1


class RateLimitSummaryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: RateStatus
    observed_at: datetime
    retry_after_at: datetime | None = None


class HealthObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    health: ObservableHealth
    observed_at: datetime
    rate_limit_summary: RateLimitSummaryInput | None = None


class RevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime


class RateLimitSummaryOutput(BaseModel):
    status: RateStatus
    observed_at: datetime
    retry_after_at: datetime | None


class MediaConnectorDescriptorOutput(BaseModel):
    connector_ref: str
    derived_tenant_ref: str
    provider: Provider
    deployment_mode: DeploymentMode
    binding_sha256: str
    protocol_version: str
    capabilities: list[str]
    health: Health
    concurrency_limit: Literal[1]
    rate_limit_summary: RateLimitSummaryOutput | None
    last_heartbeat_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None


class MediaConnectorResultOutput(BaseModel):
    contract_id: Literal[CONTRACT_ID]
    connector: MediaConnectorDescriptorOutput


class MediaConnectorListOutput(BaseModel):
    contract_id: Literal[CONTRACT_ID]
    items: list[MediaConnectorDescriptorOutput]
    next_cursor: str | None


def _idempotency_key(
    value: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=160,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
        ),
    ],
) -> str:
    return value


def _execute(call):
    try:
        return run(call)
    except MediaConnectorConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/v1/media-connectors",
    status_code=201,
    response_model=MediaConnectorResultOutput,
)
def register_media_connector(
    body: RegistrationInput,
    principal: Annotated[Principal, Depends(current_principal)],
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
):
    ensure_role(principal, "admin")
    return _execute(
        lambda: runtime.media_connectors.register(
            principal=principal,
            provider=body.provider,
            deployment_mode=body.deployment_mode,
            protocol_version=body.protocol_version,
            capabilities=body.capabilities,
            concurrency_limit=body.concurrency_limit,
            idempotency_key=idempotency_key,
        )
    )


@router.get(
    "/v1/media-connectors",
    response_model=MediaConnectorListOutput,
)
def list_media_connectors(
    principal: Annotated[Principal, Depends(current_principal)],
    provider: Provider | None = None,
    health: Health | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    cursor: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "monitor",
        "admin",
    )
    return _execute(
        lambda: runtime.media_connectors.list(
            principal=principal,
            provider=provider,
            health=health,
            limit=limit,
            cursor=cursor,
        )
    )


@router.get(
    "/v1/media-connectors/{connector_ref}",
    response_model=MediaConnectorResultOutput,
)
def get_media_connector(
    connector_ref: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "monitor",
        "admin",
    )
    return _execute(
        lambda: runtime.media_connectors.get(
            principal=principal,
            connector_ref=connector_ref,
        )
    )


@router.post(
    "/v1/media-connectors/{connector_ref}/observations",
    response_model=MediaConnectorResultOutput,
)
def observe_media_connector(
    connector_ref: str,
    body: HealthObservationInput,
    principal: Annotated[Principal, Depends(current_principal)],
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
):
    ensure_role(principal, "operator", "monitor", "admin")
    rate = body.rate_limit_summary
    return _execute(
        lambda: runtime.media_connectors.observe(
            principal=principal,
            connector_ref=connector_ref,
            health=body.health,
            observed_at=body.observed_at,
            rate_limit_status=rate.status if rate else None,
            rate_limit_observed_at=rate.observed_at if rate else None,
            retry_after_at=rate.retry_after_at if rate else None,
            idempotency_key=idempotency_key,
        )
    )


@router.post(
    "/v1/media-connectors/{connector_ref}/revoke",
    response_model=MediaConnectorResultOutput,
)
def revoke_media_connector(
    connector_ref: str,
    body: RevokeInput,
    principal: Annotated[Principal, Depends(current_principal)],
    idempotency_key: Annotated[str, Depends(_idempotency_key)],
):
    ensure_role(principal, "admin")
    return _execute(
        lambda: runtime.media_connectors.revoke(
            principal=principal,
            connector_ref=connector_ref,
            observed_at=body.observed_at,
            idempotency_key=idempotency_key,
        )
    )
