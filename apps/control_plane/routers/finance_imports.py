from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..api_contracts import (
    CashPlanItemInput,
    FeeMappingInput,
    FinanceEntryInput,
    FxRateInput,
    OzonAccrualClassificationInput,
    OzonFeeMappingApprovalInput,
    OzonFinanceReportReviewInput,
    ReconciliationInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..evidence import EvidenceGrade
from ..finance import FinanceEntryKind
from ..imports import MAX_IMPORT_BYTES
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


def _store_ref(principal: Principal, requested: str | None) -> str:
    if requested:
        ensure_store_scope(principal, requested)
        return requested
    if len(principal.store_refs) != 1:
        raise HTTPException(
            status_code=422,
            detail="store_ref is required when identity has multiple stores",
        )
    return next(iter(principal.store_refs))


def _scope_context(
    principal: Principal,
    *,
    store_ref: str,
    as_of: str | None,
) -> tuple[datetime, dict]:
    ensure_store_scope(principal, store_ref)
    if as_of is None:
        cutoff = datetime.now(UTC)
    else:
        try:
            cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="as_of must be an ISO-8601 timestamp",
            ) from exc
        if cutoff.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="as_of must include a timezone",
            )
        cutoff = cutoff.astimezone(UTC)
        if cutoff > datetime.now(UTC):
            raise HTTPException(
                status_code=422,
                detail="as_of cannot be in the future",
            )
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    if (
        entity_scope.get("status") != "ready"
        or not entity_scope.get("entity_ref")
        or not entity_scope.get("authority_sha256")
    ):
        raise HTTPException(
            status_code=422,
            detail="Ozon import requires one current entity scope grant",
        )
    return cutoff, entity_scope


def _require_import(
    import_id: str,
    *,
    principal: Principal,
    store_ref: str | None,
    as_of: str | None = None,
) -> tuple[dict, str, datetime, dict]:
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )
    imported = runtime.scoped_imports.require_import(
        import_id,
        principal=principal,
        entity_scope=entity_scope,
        store_ref=store,
        as_of=cutoff,
    )
    return imported, store, cutoff, entity_scope


def validated_report_period(start_value: str, end_value: str) -> dict[str, str]:
    if not start_value or not end_value:
        raise HTTPException(status_code=422, detail="Report period requires both start and end dates")
    try:
        period_start = date.fromisoformat(start_value)
        period_end = date.fromisoformat(end_value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Report period dates must use YYYY-MM-DD") from exc
    if period_end < period_start or (period_end - period_start).days > 30:
        raise HTTPException(status_code=422, detail="Report period must be ordered and no longer than 31 days")
    return {"report_period_start": period_start.isoformat(), "report_period_end": period_end.isoformat()}


async def ozon_upload_bytes(file: UploadFile) -> bytes:
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail=f"Import file exceeds {MAX_IMPORT_BYTES} bytes")
    return content


@router.post("/v1/imports/ozon/preflight")
async def preflight_ozon_import(
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
    report_period_start: Annotated[str, Form()],
    report_period_end: Annotated[str, Form()],
    store_ref: Annotated[str | None, Form()] = None,
    as_of: Annotated[str | None, Form()] = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )
    content_bytes = await ozon_upload_bytes(file)
    report_period = validated_report_period(report_period_start, report_period_end)
    preview = run(lambda: runtime.imports.preview_file(filename=file.filename or "ozon-export", content=content_bytes))
    return {
        **preview,
        **report_period,
        "scope": {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_scope["entity_ref"],
            "store_ref": store,
            "scope_grant_authority_sha256": entity_scope[
                "authority_sha256"
            ],
            "as_of": cutoff.isoformat(),
        },
        "staging_only": True,
        "formal_fact_promotion_allowed": False,
        "external_write_allowed": False,
    }


@router.post("/v1/imports/ozon", status_code=201)
async def import_ozon(
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
    report_period_start: Annotated[str, Form()],
    report_period_end: Annotated[str, Form()],
    effective_at: Annotated[str | None, Form()] = None,
    store_ref: Annotated[str | None, Form()] = None,
    as_of: Annotated[str | None, Form()] = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )
    content_bytes = await ozon_upload_bytes(file)
    report_period = validated_report_period(report_period_start, report_period_end)
    preview = run(lambda: runtime.imports.preview_file(filename=file.filename or "ozon-export", content=content_bytes))
    if not preview["ready"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Ozon import preflight failed; preserve the original file",
                "missing_columns": preview["missing_columns"],
            },
        )
    existing = run(
        lambda: runtime.scoped_imports.find_by_content(
            content_bytes,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
        )
    )
    if existing is not None:
        if not existing["evidence_id"]:
            raise HTTPException(status_code=409, detail="Existing import has no immutable source evidence")
        try:
            existing_source = runtime.evidence.get(
                existing["evidence_id"]
            )
        except KeyError as exc:
            raise HTTPException(status_code=409, detail="Existing import source evidence is missing") from exc
        if any((existing_source.metadata.get(key) != value for key, value in report_period.items())):
            raise HTTPException(status_code=409, detail="Duplicate file conflicts with its immutable report period")
        return existing
    filename = file.filename or "ozon-export"
    digest = hashlib.sha256(content_bytes).hexdigest()
    captured_at = effective_at or datetime.now(UTC).isoformat()
    scope_digest = hashlib.sha256(
        (
            f"{principal.tenant_ref}\x1f{entity_scope['entity_ref']}"
            f"\x1f{store}"
        ).encode()
    ).hexdigest()

    def capture_and_import():
        source = runtime.evidence.capture(
            content=content_bytes,
            filename=filename,
            content_type=file.content_type or "application/octet-stream",
            source="ozon_export",
            source_ref=(
                f"ozon-upload://scope/{scope_digest}/sha256/{digest}"
            ),
            grade=EvidenceGrade.A,
            effective_at=captured_at,
            effective_until=None,
            created_by=principal.actor_id,
            metadata={
                "filename": filename,
                "sha256": digest,
                "retention_class": "financial",
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_scope["entity_ref"],
                "store_ref": store,
                "scope_grant_authority_sha256": entity_scope[
                    "authority_sha256"
                ],
                "scope_as_of": cutoff.isoformat(),
                **report_period,
            },
        )
        result = runtime.scoped_imports.import_file(
            filename=filename,
            content=content_bytes,
            evidence_id=source.id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
        )
        runtime.evidence.link(
            evidence_id=source.id,
            target_type="import_job",
            target_id=result["id"],
            relationship="source_for",
            created_by=principal.actor_id,
        )
        return result

    return run(capture_and_import)


@router.get("/v1/imports/{import_id}")
def get_import(
    import_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    return run(
        lambda: _require_import(
            import_id,
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
        )[0]
    )


@router.get("/v1/imports/{import_id}/finance-review")
def get_finance_report_review(
    import_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    run(
        lambda: _require_import(
            import_id,
            principal=principal,
            store_ref=store_ref,
        )
    )
    return run(lambda: runtime.finance_report_reviews.status(import_id))


@router.post("/v1/imports/{import_id}/finance-review", status_code=201)
def review_finance_report(
    import_id: str,
    body: OzonFinanceReportReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
        _require_import(
            import_id,
            principal=principal,
            store_ref=store_ref,
        )
        result = runtime.finance_report_reviews.review(
            import_id=import_id, **body.model_dump(), reviewed_by=principal.actor_id
        )
        return {
            "import": asdict(result["import"]),
            "report": asdict(result["report"]),
            "review": asdict(result["review"]),
            "lineage": [asdict(item) for item in result.get("lineage", [])],
            "idempotent": result["idempotent"],
        }

    return run(review)


@router.post("/v1/imports/{import_id}/promote", status_code=201)
def promote_import(
    import_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "admin")

    def promote():
        _, store, cutoff, entity_scope = _require_import(
            import_id,
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
        )
        return runtime.scoped_facts.promote(
            import_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            created_by=principal.actor_id,
        )

    return run(promote)


@router.get("/v1/imports/{import_id}/fee-codes")
def get_import_fee_codes(
    import_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    run(
        lambda: _require_import(
            import_id,
            principal=principal,
            store_ref=store_ref,
        )
    )
    return run(lambda: runtime.ozon_fee_mappings.status(import_id))


@router.post("/v1/imports/{import_id}/fee-mappings", status_code=201)
def approve_import_fee_mapping(
    import_id: str,
    body: OzonFeeMappingApprovalInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def approve():
        _require_import(
            import_id,
            principal=principal,
            store_ref=store_ref,
        )
        result = runtime.ozon_fee_mappings.approve(
            import_id=import_id, **body.model_dump(), approved_by=principal.actor_id
        )
        return {
            "mapping": asdict(result["mapping"]),
            "approval": asdict(result["approval"]),
            "lineage": [asdict(item) for item in result["lineage"]],
        }

    return run(approve)


@router.get("/v1/imports/{import_id}/accrual-classifications")
def get_import_accrual_classifications(
    import_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    run(
        lambda: _require_import(
            import_id,
            principal=principal,
            store_ref=store_ref,
        )
    )
    return run(lambda: runtime.ozon_accrual_classifications.status(import_id))


@router.post("/v1/imports/{import_id}/accrual-classifications", status_code=201)
def approve_import_accrual_classification(
    import_id: str,
    body: OzonAccrualClassificationInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def approve():
        _require_import(
            import_id,
            principal=principal,
            store_ref=store_ref,
        )
        result = runtime.ozon_accrual_classifications.approve(
            import_id=import_id, **body.model_dump(), approved_by=principal.actor_id
        )
        return {
            "approval": asdict(result["approval"]),
            "lineage": [asdict(item) for item in result.get("lineage", [])],
            "idempotent": result["idempotent"],
        }

    return run(approve)


@router.get("/v1/facts")
def list_facts(
    principal: Annotated[Principal, Depends(current_principal)],
    fact_type: str | None = None,
    limit: int = 100,
    store_ref: str | None = None,
    as_of: str | None = None,
):
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )
    return run(
        lambda: runtime.scoped_facts.list(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            fact_type=fact_type,
            limit=limit,
        )
    )


@router.get("/v1/facts/{fact_id}")
def get_fact(
    fact_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )
    return run(
        lambda: runtime.scoped_facts.get(
            fact_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
        )
    )


@router.post("/v1/finance/fee-mappings", status_code=201)
def register_fee_mapping(body: FeeMappingInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "reviewer", "compliance", "admin")
    if body.provider.strip().lower() == "ozon":
        raise HTTPException(status_code=422, detail="Use an accepted Ozon import fee-mapping workflow")
    return run(lambda: runtime.finance.register_fee_mapping(**body.model_dump(), approved_by=principal.actor_id))


@router.get("/v1/finance/fee-mappings")
def list_fee_mappings(provider: str | None = None):
    return run(lambda: runtime.finance.list_fee_mappings(provider=provider))


@router.post("/v1/finance/fx-rates", status_code=201)
def add_fx_rate(body: FxRateInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: runtime.finance.add_fx_rate(**body.model_dump(), created_by=principal.actor_id))


@router.get("/v1/finance/fx-rates")
def list_fx_rates(base_currency: str | None = None):
    return run(lambda: runtime.finance.list_fx_rates(base_currency=base_currency))


@router.post("/v1/finance/facts/{fact_id}/ingest", status_code=201)
def ingest_finance_fact(fact_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: runtime.finance.ingest_fact(fact_id, created_by=principal.actor_id))


@router.post("/v1/finance/entries", status_code=201)
def record_finance_entry(body: FinanceEntryInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: runtime.finance.record_entry(**body.model_dump(), created_by=principal.actor_id))


@router.get("/v1/finance/entries")
def list_finance_entries(reconciliation_key: str | None = None, entry_kind: FinanceEntryKind | None = None):
    return run(lambda: runtime.finance.list_entries(reconciliation_key=reconciliation_key, entry_kind=entry_kind))


@router.get("/v1/finance/unknown-fees")
def list_unknown_fees(provider: str = "ozon"):
    return run(lambda: runtime.finance.unknown_fee_entries(provider=provider))


@router.post("/v1/finance/reconciliations/{reconciliation_key}", status_code=201)
def reconcile_finance(
    reconciliation_key: str, body: ReconciliationInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: runtime.finance.reconcile(reconciliation_key, **body.model_dump(), created_by=principal.actor_id)
    )


@router.post("/v1/finance/cash-plan", status_code=201)
def add_cash_plan_item(body: CashPlanItemInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: runtime.finance.add_cash_plan_item(**body.model_dump(), created_by=principal.actor_id))


@router.get("/v1/finance/cash-forecast")
def cash_forecast(start_at: str, opening_balance: Decimal, fx_source: str, quote_currency: str = "CNY"):
    return run(
        lambda: runtime.finance.cash_forecast(
            start_at=start_at, opening_balance=opening_balance, quote_currency=quote_currency, fx_source=fx_source
        )
    )
