from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..api_contracts import (
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..growth_channel import TELEGRAM_CAPABILITIES, VK_CAPABILITIES
from ..runtime import runtime
from ..security import Principal
from .customer_service import _cutoff

router = APIRouter()


@router.get("/v1/growth-channels/capabilities")
def growth_channel_capabilities(
    principal: Annotated[Principal, Depends(current_principal)],
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
    channels = [
        {
            "channel": capability.channel,
            "operations": sorted(capability.operations),
            "supports_deep_links": capability.supports_deep_links,
            "supports_direct_messages": capability.supports_direct_messages,
            "supports_broadcasts": capability.supports_broadcasts,
            "requires_initiated_or_subscribed_message": (
                capability.requires_initiated_or_subscribed_message
            ),
            "production_adapter": "injected_transport",
            "dry_run_adapter": True,
        }
        for capability in (VK_CAPABILITIES, TELEGRAM_CAPABILITIES)
    ]
    payload = {
        "contract_id": "kjds-growth-channel-capabilities-v1",
        "status": "ready_with_constraints",
        "channels": channels,
        "attribution_funnel": [
            "impression",
            "click",
            "deep_link",
            "conversation",
            "add_to_cart",
            "order",
            "refund",
            "settlement",
            "cash_cm3",
        ],
        "optimization_objective": "incremental_cash_cm3",
        "control_envelope": {
            "telegram_unsolicited_message_allowed": False,
            "reward_confirmed_before_refund_window_and_settlement": False,
            "external_write_without_exact_permit": False,
            "external_write_allowed": False,
        },
    }
    payload["snapshot_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


@router.get("/v1/growth-experiments/workspace")
def growth_experiment_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    query: str | None = None,
    action: str | None = None,
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
    cutoff = _cutoff(as_of) if as_of else datetime.now(UTC)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.scoped_growth_experiments.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            query=query,
            action=action,
            page_size=page_size,
            cursor=cursor,
        )
    )
