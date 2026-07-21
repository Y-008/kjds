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
    run,
)
from ..evidence import EvidenceGrade
from ..finance import FinanceEntryKind
from ..imports import MAX_IMPORT_BYTES
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


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
):
    ensure_role(principal, "operator", "admin")
    content_bytes = await ozon_upload_bytes(file)
    report_period = validated_report_period(report_period_start, report_period_end)
    preview = run(lambda: runtime.imports.preview_file(filename=file.filename or "ozon-export", content=content_bytes))
    return {**preview, **report_period}


@router.post("/v1/imports/ozon", status_code=201)
async def import_ozon(
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
    report_period_start: Annotated[str, Form()],
    report_period_end: Annotated[str, Form()],
    effective_at: Annotated[str | None, Form()] = None,
):
    ensure_role(principal, "operator", "admin")
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
    existing = runtime.imports.find_by_content(content_bytes)
    if existing is not None:
        if not existing.evidence_id:
            raise HTTPException(status_code=409, detail="Existing import has no immutable source evidence")
        try:
            existing_source = runtime.evidence.get(existing.evidence_id)
        except KeyError as exc:
            raise HTTPException(status_code=409, detail="Existing import source evidence is missing") from exc
        if any((existing_source.metadata.get(key) != value for key, value in report_period.items())):
            raise HTTPException(status_code=409, detail="Duplicate file conflicts with its immutable report period")
        return asdict(existing)
    filename = file.filename or "ozon-export"
    digest = hashlib.sha256(content_bytes).hexdigest()
    captured_at = effective_at or datetime.now(UTC).isoformat()

    def capture_and_import():
        source = runtime.evidence.capture(
            content=content_bytes,
            filename=filename,
            content_type=file.content_type or "application/octet-stream",
            source="ozon_export",
            source_ref=f"ozon-upload://sha256/{digest}",
            grade=EvidenceGrade.A,
            effective_at=captured_at,
            effective_until=None,
            created_by=principal.actor_id,
            metadata={"filename": filename, "sha256": digest, "retention_class": "financial", **report_period},
        )
        result = runtime.imports.import_file(filename=filename, content=content_bytes, evidence_id=source.id)
        runtime.evidence.link(
            evidence_id=source.id,
            target_type="import_job",
            target_id=result.id,
            relationship="source_for",
            created_by=principal.actor_id,
        )
        return result

    return run(capture_and_import)


@router.get("/v1/imports/{import_id}")
def get_import(import_id: str):
    return run(lambda: runtime.imports.get(import_id))


@router.get("/v1/imports/{import_id}/finance-review")
def get_finance_report_review(import_id: str):
    return run(lambda: runtime.finance_report_reviews.status(import_id))


@router.post("/v1/imports/{import_id}/finance-review", status_code=201)
def review_finance_report(
    import_id: str, body: OzonFinanceReportReviewInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
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
def promote_import(import_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.facts.promote(import_id, created_by=principal.actor_id))


@router.get("/v1/imports/{import_id}/fee-codes")
def get_import_fee_codes(import_id: str):
    return run(lambda: runtime.ozon_fee_mappings.status(import_id))


@router.post("/v1/imports/{import_id}/fee-mappings", status_code=201)
def approve_import_fee_mapping(
    import_id: str, body: OzonFeeMappingApprovalInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def approve():
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
def get_import_accrual_classifications(import_id: str):
    return run(lambda: runtime.ozon_accrual_classifications.status(import_id))


@router.post("/v1/imports/{import_id}/accrual-classifications", status_code=201)
def approve_import_accrual_classification(
    import_id: str, body: OzonAccrualClassificationInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def approve():
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
def list_facts(fact_type: str | None = None, limit: int = 100):
    return run(lambda: runtime.facts.list(fact_type=fact_type, limit=min(max(limit, 1), 500)))


@router.get("/v1/facts/{fact_id}")
def get_fact(fact_id: str):
    return run(lambda: runtime.facts.get(fact_id))


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
