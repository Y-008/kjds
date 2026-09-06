"""Read-only admission projection for an official Ozon readback."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ..api_contracts import current_principal, ensure_role, ensure_store_scope, run
from ..evidence import parse_timestamp
from ..runtime import runtime
from ..security import Principal

router = APIRouter()

_READ_ROLES = (
    "pilot_reader",
    "operator",
    "reviewer",
    "compliance",
    "risk",
    "monitor",
    "admin",
)


def _cutoff(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        return parse_timestamp(value, "as_of")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v1/ozon/production-acceptance/{run_id}")
def get_ozon_production_acceptance(
    run_id: Annotated[str, Path(min_length=1, max_length=300)],
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: Annotated[str, Query(min_length=1, max_length=160)] = "ozon-primary",
    as_of: Annotated[str | None, Query(max_length=80)] = None,
):
    """Evaluate a stored Ozon read run without contacting or writing Ozon.

    The evaluator consumes only the SQL-scoped Pilot/Run, immutable raw
    response Evidence, and the server-owned channel runtime identity. A
    missing artifact or transport-failed run is returned as
    ``BLOCKED_EVIDENCE``; it is never downgraded to ``NO_DATA`` or treated as
    a successful read.
    """

    ensure_role(principal, *_READ_ROLES)
    ensure_store_scope(principal, store_ref)
    cutoff = _cutoff(as_of)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.ozon_production_acceptance.evaluate(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            run_id=run_id,
            as_of=cutoff,
        )
    )

