from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..api_contracts import (
    ProfitPilotProposalInput,
    ScopedFxEvidenceInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..fx_evidence_intake import (
    FxEvidenceScope,
    FxEvidenceSubmission,
)
from ..profit_command import ProfitCommandConflict
from ..runtime import runtime
from ..security import Principal

router = APIRouter()

READ_ROLES = (
    "operator",
    "reviewer",
    "compliance",
    "approver",
    "risk",
    "admin",
)


def _cutoff(as_of: str | None) -> datetime:
    if as_of is None:
        return datetime.now(UTC)
    try:
        cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="as_of must be an ISO-8601 timestamp"
        ) from exc
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    cutoff = cutoff.astimezone(UTC)
    if cutoff > datetime.now(UTC):
        raise HTTPException(status_code=422, detail="as_of cannot be in the future")
    return cutoff


def _context(
    principal: Principal,
    *,
    store_ref: str,
    as_of: str | None,
) -> tuple[datetime, dict]:
    ensure_store_scope(principal, store_ref)
    cutoff = _cutoff(as_of)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return cutoff, entity_scope


@router.get("/v1/profit-command/workspace")
def profit_command_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    display_currency: str = "CNY",
):
    ensure_role(principal, *READ_ROLES)
    cutoff, entity_scope = _context(principal, store_ref=store_ref, as_of=as_of)
    return run(
        lambda: runtime.profit_command.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            display_currency=display_currency,
        )
    )


@router.post("/v1/profit-command/fx-evidence", status_code=201)
def record_profit_fx_evidence(
    body: ScopedFxEvidenceInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    cutoff, entity_scope = _context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )
    if entity_scope.get("status") != "ready":
        raise HTTPException(
            status_code=403,
            detail="Current exact entity scope authority is required",
        )

    def record():
        scope = FxEvidenceScope(
            principal.tenant_ref,
            str(entity_scope["entity_ref"]),
            body.store_ref,
        )
        result = runtime.fx_evidence_intake.ingest(
            [
                FxEvidenceSubmission(
                    scope=scope,
                    source_currency=body.source_currency,
                    target_currency=body.target_currency,
                    rate=body.rate,
                    effective_at=body.effective_at,
                    expires_at=body.expires_at,
                    evidence_id=body.evidence_id,
                    source_type=body.source_type,
                    authority=body.authority,
                    purposes=tuple(body.purposes),
                    idempotency_key=body.idempotency_key,
                )
            ],
            expected_scope=scope,
        )
        if result.status != "ready" or len(result.records) != 1:
            codes = ",".join(item.code for item in result.blockers)
            raise ValueError(f"FX evidence intake blocked: {codes or result.status}")
        record = result.records[0]
        persisted = runtime.finance.add_fx_rate(
            base_currency=record.source_currency,
            quote_currency=record.target_currency,
            rate=record.rate,
            effective_at=record.effective_at.isoformat(),
            expires_at=record.expires_at.isoformat(),
            source=f"{record.source_type}:{record.authority}",
            source_type=record.source_type,
            authority=record.authority,
            purposes=list(record.purposes),
            intake_content_sha256=record.content_hash,
            idempotency_key=record.idempotency_key,
            evidence_id=record.evidence_id,
            created_by=principal.actor_id,
            scope_authority={
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_scope["entity_ref"],
                "store_ref": body.store_ref,
                "scope_grant_authority_sha256": entity_scope[
                    "authority_sha256"
                ],
                "scope_as_of": cutoff.isoformat(),
            },
        )
        return {
            "contract_id": "kjds-scoped-fx-evidence-intake-v1",
            "status": "recorded",
            "record": record.to_dict(),
            "finance_rate": persisted,
            "formal_fact_promoted": False,
            "automatic_decision_allowed": False,
            "external_write_allowed": False,
        }

    return run(record)


@router.get("/v1/profit-command/truth-readiness")
def profit_truth_readiness(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    display_currency: str = "CNY",
):
    ensure_role(principal, *READ_ROLES)
    cutoff, entity_scope = _context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.profit_truth_readiness.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            display_currency=display_currency,
        )
    )


@router.get("/v1/profit-command/portfolio")
def profit_command_portfolio(
    principal: Annotated[Principal, Depends(current_principal)],
    as_of: str | None = None,
    display_currency: str = "CNY",
):
    ensure_role(principal, *READ_ROLES)
    cutoff = _cutoff(as_of)

    def project():
        if (
            len(display_currency) != 3
            or not display_currency.isascii()
            or not display_currency.isalpha()
            or not display_currency.isupper()
        ):
            raise ValueError(
                "display_currency must be a three-letter uppercase ASCII currency"
            )
        workspaces = []
        coverage = []
        for store_ref in sorted(principal.store_refs):
            entity_scope = runtime.scope_grants.current(
                principal=principal,
                store_ref=store_ref,
                as_of=cutoff,
            )
            scope_status = str(entity_scope.get("status") or "no_data")
            if scope_status != "ready":
                coverage.append(
                    {
                        "store_ref": store_ref,
                        "status": scope_status,
                        "reason": "current_entity_scope_grant_missing",
                    }
                )
                continue
            workspace = runtime.profit_command.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=cutoff,
                display_currency=display_currency,
            )
            workspaces.append(workspace)
            coverage.append(
                {
                    "store_ref": store_ref,
                    "status": workspace.get("status", "no_data"),
                    "reason": None,
                }
            )
        return runtime.profit_command.portfolio(
            workspaces,
            tenant_ref=principal.tenant_ref,
            as_of=cutoff,
            display_currency=display_currency,
            store_coverage=coverage,
        )

    return run(project)


@router.get("/v1/profit-command/analytics")
def profit_command_analytics(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    display_currency: str = "CNY",
):
    ensure_role(principal, *READ_ROLES)
    cutoff, entity_scope = _context(principal, store_ref=store_ref, as_of=as_of)
    return run(
        lambda: runtime.profit_command.analytics(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            display_currency=display_currency,
        )
    )


@router.get("/v1/profit-command/remediation")
def profit_command_remediation(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    display_currency: str = "CNY",
    queue_page_size: int = 50,
    queue_offset: int = 0,
):
    ensure_role(principal, *READ_ROLES)
    cutoff, entity_scope = _context(principal, store_ref=store_ref, as_of=as_of)
    return run(
        lambda: runtime.profit_command.remediation(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            display_currency=display_currency,
            queue_page_size=queue_page_size,
            queue_offset=queue_offset,
        )
    )


@router.get("/v1/profit-command/candidates")
def profit_command_candidates(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    display_currency: str = "CNY",
    decision_class: str | None = None,
    lifecycle: str | None = None,
    category_id: str | None = None,
    query: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
):
    ensure_role(principal, *READ_ROLES)
    cutoff, entity_scope = _context(principal, store_ref=store_ref, as_of=as_of)
    return run(
        lambda: runtime.profit_command.candidates(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            display_currency=display_currency,
            decision_class=decision_class,
            lifecycle=lifecycle,
            category_id=category_id,
            query=query,
            page_size=page_size,
            cursor=cursor,
        )
    )


@router.get("/v1/profit-command/lineage")
def profit_command_lineage(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    display_currency: str = "CNY",
    candidate_id: str | None = None,
):
    ensure_role(principal, *READ_ROLES)
    cutoff, entity_scope = _context(principal, store_ref=store_ref, as_of=as_of)
    return run(
        lambda: runtime.profit_command.lineage(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            display_currency=display_currency,
            candidate_id=candidate_id,
        )
    )


@router.get("/v1/profit-command/candidates/{candidate_id}")
def profit_command_candidate(
    candidate_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    display_currency: str = "CNY",
):
    ensure_role(principal, *READ_ROLES)
    cutoff, entity_scope = _context(principal, store_ref=store_ref, as_of=as_of)
    return run(
        lambda: runtime.profit_command.candidate(
            candidate_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            display_currency=display_currency,
        )
    )


@router.post("/v1/profit-command/candidates/{candidate_id}/pilot-proposals", status_code=201)
def create_profit_pilot_proposal(
    candidate_id: str,
    body: ProfitPilotProposalInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    cutoff, entity_scope = _context(principal, store_ref=body.store_ref, as_of=body.as_of)
    try:
        return runtime.profit_command.propose_pilot(
            candidate_id,
            request=body.model_dump(mode="json"),
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            as_of=cutoff,
            display_currency=body.display_currency,
        )
    except ProfitCommandConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
