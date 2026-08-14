from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from pydantic import BaseModel, ConfigDict, Field

from ..api_contracts import current_principal, ensure_role, ensure_store_scope, run
from ..evidence import parse_timestamp
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


class ChannelAccountGovernanceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)


class ChannelAccountGovernanceTransitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    as_of: str | None = None
    command: ChannelAccountGovernanceCommand


@router.get("/v1/channel-accounts/workspace")
def channel_account_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    platform: str | None = None,
    account_ref: str | None = None,
    adapter_id: str | None = None,
    query: str | None = None,
    state: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
):
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
    cutoff = parse_timestamp(as_of, "as_of") if as_of else datetime.now(UTC)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.scoped_channel_account_authority.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            platform=platform,
            account_ref=account_ref,
            adapter_id=adapter_id,
            query=query,
            state=state,
            page_size=page_size,
            cursor=cursor,
        )
    )


@router.post("/v1/channel-account-governance/transitions", status_code=201)
def advance_channel_account_governance(
    body: ChannelAccountGovernanceTransitionInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "admin")
    ensure_store_scope(principal, body.store_ref)
    cutoff = parse_timestamp(body.as_of, "as_of") if body.as_of else datetime.now(UTC)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=body.store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.channel_account_governance.advance(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            command=body.command.model_dump(),
            as_of=cutoff,
        )
    )
