from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..api_contracts import current_principal, ensure_role, run
from ..autonomous_execution_profile import StandingAutonomousExecutionProfile
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_ref: str = Field(min_length=1, max_length=160)
    entity_ref: str = Field(min_length=1, max_length=160)
    store_refs: list[str] = Field(min_length=1, max_length=100)
    allowed_channels: list[str] = Field(min_length=1, max_length=50)
    allowed_operations: list[str] = Field(min_length=1, max_length=100)
    max_permit_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    max_command_amount: Decimal | None = Field(default=None, ge=0)
    profile_version: str = Field(default="1", min_length=1, max_length=80)
    expires_at: datetime | None = None

    @field_validator("store_refs", "allowed_channels", "allowed_operations")
    @classmethod
    def normalize_strings(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if not normalized or any(not value for value in normalized):
            raise ValueError("profile collections cannot contain empty values")
        if len(set(normalized)) != len(normalized):
            raise ValueError("profile collections must be unique")
        return normalized

    @field_validator("expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("expires_at must include a timezone")
        return value.astimezone(UTC)


class GovernanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=300)
    reviewer_id: str = Field(min_length=1, max_length=200)
    compliance_id: str = Field(min_length=1, max_length=200)


def _profile(body: ProfileInput, *, profile_id: str) -> StandingAutonomousExecutionProfile:
    return StandingAutonomousExecutionProfile(
        profile_id=profile_id,
        tenant_ref=body.tenant_ref,
        entity_ref=body.entity_ref,
        store_refs=frozenset(body.store_refs),
        allowed_channels=frozenset(value.lower() for value in body.allowed_channels),
        allowed_operations=frozenset(body.allowed_operations),
        enabled=False,
        expires_at=body.expires_at,
        max_permit_ttl_seconds=body.max_permit_ttl_seconds,
        max_command_amount=body.max_command_amount,
        profile_version=body.profile_version,
    )


def _as_dict(profile: StandingAutonomousExecutionProfile) -> dict[str, object]:
    return {
        "profile_id": profile.profile_id,
        "tenant_ref": profile.tenant_ref,
        "entity_ref": profile.entity_ref,
        "store_refs": sorted(profile.store_refs),
        "allowed_channels": sorted(profile.allowed_channels),
        "allowed_operations": sorted(profile.allowed_operations),
        "enabled": profile.enabled,
        "activated_at": profile.activated_at.isoformat() if profile.activated_at else None,
        "expires_at": profile.expires_at.isoformat() if profile.expires_at else None,
        "max_permit_ttl_seconds": profile.max_permit_ttl_seconds,
        "max_command_amount": str(profile.max_command_amount) if profile.max_command_amount is not None else None,
        "profile_version": profile.profile_version,
        "profile_sha256": profile.profile_sha256,
        "external_write_allowed": False,
    }


@router.post("/v1/autonomous-execution-profiles/{profile_id}")
def create_profile(
    profile_id: str,
    body: ProfileInput,
    governance: GovernanceInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "admin", "compliance")
    if body.tenant_ref != principal.tenant_ref:
        raise HTTPException(status_code=403, detail="profile tenant scope does not match principal")
    profile = _profile(body, profile_id=profile_id)
    return run(lambda: _as_dict(runtime.autonomous_execution_profile_store.create(
        profile, idempotency_key=governance.idempotency_key,
        actor_id=principal.actor_id, reviewer_id=governance.reviewer_id,
        compliance_id=governance.compliance_id,
    )))


@router.post("/v1/autonomous-execution-profiles/{profile_id}/activate")
def activate_profile(
    profile_id: str,
    body: GovernanceInput,
    entity_ref: Annotated[str, Query(min_length=1, max_length=160)],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "admin", "compliance")
    return run(lambda: _as_dict(runtime.autonomous_execution_profile_store.activate(
        profile_id=profile_id, tenant_ref=principal.tenant_ref,
        entity_ref=entity_ref, idempotency_key=body.idempotency_key,
        actor_id=principal.actor_id, reviewer_id=body.reviewer_id,
        compliance_id=body.compliance_id,
    )))


@router.post("/v1/autonomous-execution-profiles/{profile_id}/suspend")
def suspend_profile(
    profile_id: str,
    body: GovernanceInput,
    entity_ref: Annotated[str, Query(min_length=1, max_length=160)],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "admin", "compliance")
    return run(lambda: _as_dict(runtime.autonomous_execution_profile_store.suspend(
        profile_id=profile_id, tenant_ref=principal.tenant_ref,
        entity_ref=entity_ref, idempotency_key=body.idempotency_key,
        actor_id=principal.actor_id, reviewer_id=body.reviewer_id,
        compliance_id=body.compliance_id,
    )))


@router.get("/v1/autonomous-execution-profiles/{profile_id}")
def get_profile(
    profile_id: str,
    entity_ref: Annotated[str, Query(min_length=1, max_length=160)],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "admin", "compliance", "reviewer", "monitor", "operator")
    return run(lambda: _as_dict(runtime.autonomous_execution_profile_store.current(
        profile_id=profile_id, tenant_ref=principal.tenant_ref,
        entity_ref=entity_ref,
    )))


@router.get("/v1/autonomous-execution-profiles/{profile_id}/history")
def profile_history(
    profile_id: str,
    entity_ref: Annotated[str, Query(min_length=1, max_length=160)],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "admin", "compliance", "reviewer", "monitor")
    return run(lambda: runtime.autonomous_execution_profile_store.history(
        profile_id=profile_id, tenant_ref=principal.tenant_ref,
        entity_ref=entity_ref,
    ))
