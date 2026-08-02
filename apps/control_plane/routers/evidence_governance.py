from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from ..api_contracts import (
    DemandReportReviewInput,
    EvidenceScopeBindingRecordInput,
    EvidenceScopeBindingReviewInput,
    EvidenceScopeBindingSubmitInput,
    GateReviewDecisionInput,
    GateReviewInput,
    GateReviewSubmitInput,
    LineageLinkInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..evidence import (
    CHANNEL_ACCOUNT_RESERVED_CONTRACTS,
    CHANNEL_ACCOUNT_RESERVED_SOURCES,
    EvidenceGrade,
)
from ..research_inbox import ResearchInboxService
from ..runtime import runtime
from ..security import Principal
from ..source_connectors import source_connector_catalog

router = APIRouter()


def _scope_context(
    principal: Principal,
    *,
    store_ref: str,
    as_of: str | None,
):
    cutoff = (
        datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if as_of
        else datetime.now(UTC)
    )
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise ValueError("as_of must include a timezone")
    cutoff = cutoff.astimezone(UTC)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return cutoff, entity_scope


def _ensure_channel_evidence_access(
    record,
    principal: Principal,
    *,
    content: bool = False,
) -> None:
    if record.source not in CHANNEL_ACCOUNT_RESERVED_SOURCES:
        return
    metadata = record.metadata
    store_ref = str(metadata.get("store_ref") or "")
    if metadata.get("tenant_ref") != principal.tenant_ref or not principal.can_access_store(store_ref):
        raise HTTPException(
            status_code=403,
            detail="Reserved Evidence is outside authenticated scope",
        )
    canonical_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=datetime.now(UTC),
    )
    if (
        canonical_scope.get("status") != "ready"
        or canonical_scope.get("tenant_ref") != principal.tenant_ref
        or canonical_scope.get("store_ref") != store_ref
        or canonical_scope.get("entity_ref") != metadata.get("entity_ref")
    ):
        raise HTTPException(
            status_code=403,
            detail="Reserved Evidence canonical entity scope is forbidden",
        )
    if content:
        raise HTTPException(
            status_code=403,
            detail=("Reserved channel account Evidence content is not downloadable"),
        )


@router.post("/v1/evidence", status_code=201)
async def capture_evidence(
    file: Annotated[UploadFile, File()],
    source: Annotated[str, Form()],
    source_ref: Annotated[str, Form()],
    grade: Annotated[EvidenceGrade, Form()],
    effective_at: Annotated[str, Form()],
    principal: Annotated[Principal, Depends(current_principal)],
    effective_until: Annotated[str | None, Form()] = None,
    metadata_json: Annotated[str, Form()] = "{}",
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    if source.strip().lower() in {
        *CHANNEL_ACCOUNT_RESERVED_SOURCES,
        "candidate_evidence_authority_review",
        "gate_requirement_review",
        "listing_russian_native_review",
        "ozon_execution_identity_authority_review",
        "ozon-isolated-execution-worker",
        "ozon_finance_report_review",
        "scope_authority_review",
        "scope_authority_source",
        "seller_erp_bridge_binding",
        "seller_erp_bridge_review",
        "seller_erp_bridge_revocation",
        "seller_erp_bridge_source",
        "supplier_quote_authority_review",
        "supplier_quote_source",
        "supplier_rfq_dispatch",
        "supplier_rfq_dispatch_review",
        "supplier_rfq_package",
    }:
        raise HTTPException(status_code=422, detail="Reserved evidence source requires its dedicated workflow")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Evidence file exceeds {max_bytes} bytes")
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="metadata_json must be valid JSON") from exc
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=422, detail="metadata_json must be a JSON object")
    if str(metadata.get("evidence_role", "")).strip().lower() == ResearchInboxService.EVIDENCE_ROLE:
        raise HTTPException(status_code=422, detail="Reserved research evidence role requires its dedicated workflow")
    if {
        "scope_authority_review_contract_id",
        "scope_authority_source_contract_id",
    }.intersection(metadata):
        raise HTTPException(
            status_code=422,
            detail="Reserved scope authority metadata requires its dedicated workflow",
        )
    if (
        str(metadata.get("contract_id") or "").strip() in CHANNEL_ACCOUNT_RESERVED_CONTRACTS
        or str(metadata.get("channel_account_review_contract_id") or "").strip() == "kjds-channel-account-sod-review-v1"
    ):
        raise HTTPException(
            status_code=422,
            detail=("Reserved channel account authority metadata requires its dedicated separation-of-duties workflow"),
        )
    return run(
        lambda: runtime.evidence.capture(
            content=content_bytes,
            filename=file.filename or "evidence.bin",
            content_type=file.content_type or "application/octet-stream",
            source=source,
            source_ref=source_ref,
            grade=grade,
            effective_at=effective_at,
            effective_until=effective_until,
            created_by=principal.actor_id,
            metadata=metadata,
        )
    )


@router.post("/v1/scope-grants/evidence", status_code=201)
async def submit_scope_grant_source(
    file: Annotated[UploadFile, File()],
    entity_ref: Annotated[str, Form()],
    store_ref: Annotated[str, Form()],
    subject_actor_id: Annotated[str, Form()],
    event_type: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    idempotency_key: Annotated[str, Form()],
    principal: Annotated[Principal, Depends(current_principal)],
    effective_until: Annotated[str | None, Form()] = None,
) -> dict:
    ensure_role(principal, "reviewer", "admin")
    ensure_store_scope(principal, store_ref)
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Evidence file exceeds {max_bytes} bytes",
        )
    return run(
        lambda: runtime.scope_grants.submit_source(
            principal=principal,
            entity_ref=entity_ref,
            store_ref=store_ref,
            subject_actor_id=subject_actor_id,
            event_type=event_type,
            effective_at=effective_at,
            effective_until=effective_until,
            idempotency_key=idempotency_key,
            content=content,
            filename=file.filename or "scope-authority-source.bin",
            content_type=(file.content_type or "application/octet-stream"),
        )
    )


@router.post("/v1/evidence/scope-bindings", status_code=201)
def submit_evidence_scope_binding(
    body: EvidenceScopeBindingSubmitInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    ensure_store_scope(principal, body.store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )
    return run(
        lambda: runtime.evidence_scope_binding.submit_binding(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            target_evidence_id=body.target_evidence_id,
            idempotency_key=body.idempotency_key,
            effective_at=body.effective_at,
            as_of=cutoff,
        )
    )


@router.post("/v1/evidence/scope-bindings/{submission_id}/review")
def review_evidence_scope_binding(
    submission_id: str,
    body: EvidenceScopeBindingReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(
        principal,
        "reviewer",
        "compliance",
        "risk",
        "admin",
    )
    ensure_store_scope(principal, body.store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )
    return run(
        lambda: runtime.evidence_scope_binding.review_binding(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            submission_evidence_id=submission_id,
            accepted=body.accepted,
            rationale=body.rationale,
            effective_at=body.effective_at,
            idempotency_key=body.idempotency_key,
            as_of=cutoff,
        )
    )


@router.post("/v1/evidence/scope-bindings/{submission_id}/record")
def record_evidence_scope_binding(
    submission_id: str,
    body: EvidenceScopeBindingRecordInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "compliance", "admin")
    ensure_store_scope(principal, body.store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )
    return run(
        lambda: runtime.evidence_scope_binding.record_binding(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            submission_evidence_id=submission_id,
            review_evidence_id=body.review_evidence_id,
            effective_at=body.effective_at,
            idempotency_key=body.idempotency_key,
            as_of=cutoff,
        )
    )


@router.get("/v1/evidence")
def list_evidence(
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 100,
):
    records = runtime.evidence.list(min(max(limit, 1), 500))
    visible = []
    for item in records:
        try:
            _ensure_channel_evidence_access(item, principal)
        except HTTPException:
            continue
        visible.append(asdict(item))
    return visible


@router.post("/v1/evidence/integrity-scan")
def scan_evidence_integrity(
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 500,
    offset: int = 0,
    as_of: str | None = None,
):
    ensure_role(principal, "monitor", "risk", "admin")
    return run(
        lambda: runtime.evidence_integrity.scan(actor_id=principal.actor_id, limit=limit, offset=offset, as_of=as_of)
    )


@router.get("/v1/evidence/{evidence_id}")
def get_evidence(
    evidence_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    def load():
        record = runtime.evidence.get_metadata(evidence_id)
        _ensure_channel_evidence_access(record, principal)
        return runtime.evidence.get(evidence_id)

    return run(load)


@router.get("/v1/evidence/{evidence_id}/verify")
def verify_evidence(
    evidence_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    def verify():
        record = runtime.evidence.get_metadata(evidence_id)
        _ensure_channel_evidence_access(record, principal)
        return runtime.evidence.verify(evidence_id)

    return run(verify)


@router.get("/v1/evidence/{evidence_id}/retention")
def evidence_retention(
    evidence_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    def retention():
        record = runtime.evidence.get_metadata(evidence_id)
        _ensure_channel_evidence_access(record, principal)
        return runtime.evidence.retention(evidence_id)

    return run(retention)


@router.get("/v1/evidence/{evidence_id}/content")
def evidence_content(
    evidence_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):

    def load():
        record = runtime.evidence.get_metadata(evidence_id)
        _ensure_channel_evidence_access(
            record,
            principal,
            content=True,
        )
        content_bytes, content_record = runtime.evidence.content(evidence_id)
        if content_record.id != record.id:
            raise HTTPException(
                status_code=409,
                detail="Evidence content binding drift",
            )
        return Response(
            content=content_bytes,
            media_type=content_record.content_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(content_record.filename)}"},
        )

    return run(load)


@router.post("/v1/evidence/{evidence_id}/lineage", status_code=201)
def link_evidence(
    evidence_id: str, body: LineageLinkInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    target_type = body.target_type.strip().lower()
    relationship = body.relationship.strip().lower()
    if (
        target_type in {"gate_requirement", "ozon_execution_identity"}
        or relationship
        in {
            "candidate_authority_review",
            "catalog_context_for",
            "listing_russian_native_review",
            "ozon_execution_identity_authority_review",
            "rfq_package_for",
            "reviews",
            "supplier_quote_authority_review",
            "supplier_response_to_dispatch",
            "supplier_response_context_for",
            "supplier_rfq_dispatch_review",
            "rfq_dispatch_context_for",
            "supplier_outreach_for",
        }
        or (target_type == ResearchInboxService.TARGET_TYPE and relationship == ResearchInboxService.RELATIONSHIP)
    ):
        raise HTTPException(status_code=422, detail="Reserved lineage requires its dedicated workflow")

    def link():
        source_record = runtime.evidence.get_metadata(evidence_id)
        _ensure_channel_evidence_access(source_record, principal)
        if target_type == "evidence":
            target_record = runtime.evidence.get_metadata(body.target_id)
            _ensure_channel_evidence_access(target_record, principal)
        return runtime.evidence.link(
            evidence_id=evidence_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )

    return run(link)


@router.get("/v1/evidence/{evidence_id}/lineage")
def evidence_lineage(
    evidence_id: str,
    principal: Annotated[
        Principal,
        Depends(current_principal),
    ],
):
    def load():
        record = runtime.evidence.get_metadata(evidence_id)
        _ensure_channel_evidence_access(record, principal)
        edges = runtime.evidence.lineage(evidence_id)
        for edge in edges:
            if edge.to_type == "evidence":
                target = runtime.evidence.get_metadata(edge.to_id)
                _ensure_channel_evidence_access(target, principal)
        return [asdict(item) for item in edges]

    return run(load)


@router.get("/v1/sourcing/connectors")
def sourcing_connectors():
    return source_connector_catalog()


@router.get("/v1/operations/readiness")
def operations_readiness():
    return run(runtime.readiness.report)


@router.post("/v1/governance/gate-reviews", status_code=201)
def create_gate_review(body: GateReviewInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.governance.create(**body.model_dump(), actor_id=principal.actor_id))


@router.get("/v1/governance/gate-reviews")
def list_gate_reviews(gate_id: str | None = None):
    return run(lambda: runtime.governance.list(gate_id=gate_id))


@router.get("/v1/governance/gate-reviews/{review_id}")
def get_gate_review(review_id: str):
    return run(lambda: runtime.governance.get(review_id))


@router.post("/v1/governance/gate-reviews/{review_id}/submit")
def submit_gate_review(
    review_id: str, body: GateReviewSubmitInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.governance.submit(review_id, evidence_ids=body.evidence_ids, actor_id=principal.actor_id)
    )


@router.post("/v1/governance/gate-reviews/{review_id}/decide")
def decide_gate_review(
    review_id: str, body: GateReviewDecisionInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "approver", "admin")
    return run(lambda: runtime.governance.decide(review_id, **body.model_dump(), actor_id=principal.actor_id))


@router.post("/v1/operations/gate-evidence", status_code=201)
async def capture_gate_requirement_evidence(
    requirement_id: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
    source_system: Annotated[str | None, Form()] = None,
    source_locator: Annotated[str | None, Form()] = None,
    report_window_days: Annotated[int | None, Form()] = None,
):
    requirement_id = requirement_id.strip().upper()
    allowed = {
        "GOV-001": ("approver", "admin"),
        "OZN-001": ("reviewer", "compliance", "admin"),
        "SKU-000": ("operator", "reviewer", "compliance", "admin"),
    }
    roles = allowed.get(requirement_id)
    if roles is None:
        raise HTTPException(status_code=422, detail="Unsupported gate requirement")
    ensure_role(principal, *roles)
    normalized_source_system = (source_system or "").strip().lower()
    if requirement_id == "SKU-000" and (
        normalized_source_system not in runtime.demand_reports.supported_source_systems
        or report_window_days is None
        or report_window_days < 28
    ):
        raise HTTPException(
            status_code=422,
            detail="SKU-000 requires a supported demand evidence source_system and report_window_days >= 28",
        )
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Evidence file exceeds {max_bytes} bytes")
    digest = hashlib.sha256(content_bytes).hexdigest()

    def capture_and_link():
        if requirement_id == "SKU-000":
            result = runtime.demand_reports.capture_report(
                content=content_bytes,
                filename=file.filename or "SKU-000-ozon-data-report.bin",
                content_type=file.content_type or "application/octet-stream",
                effective_at=effective_at,
                report_window_days=report_window_days or 0,
                created_by=principal.actor_id,
                source_system=normalized_source_system,
                source_locator=source_locator,
            )
            return {
                "evidence": asdict(result["evidence"]),
                "lineage": asdict(result["lineage"]),
                "review_status": result["review_status"],
            }
        record = runtime.evidence.capture(
            content=content_bytes,
            filename=file.filename or f"{requirement_id}-evidence.bin",
            content_type=file.content_type or "application/octet-stream",
            source="gate_requirement",
            source_ref=f"gate://{requirement_id}/sha256/{digest}",
            grade=EvidenceGrade.A,
            effective_at=effective_at,
            effective_until=None,
            created_by=principal.actor_id,
            metadata={
                "requirement_id": requirement_id,
                "source_system": source_system,
                "report_window_days": report_window_days,
            },
        )
        edge = runtime.evidence.link(
            evidence_id=record.id,
            target_type="gate_requirement",
            target_id=requirement_id,
            relationship="satisfies",
            created_by=principal.actor_id,
        )
        return {"evidence": asdict(record), "lineage": asdict(edge)}

    return run(capture_and_link)


@router.post("/v1/operations/demand-report-review", status_code=201)
def review_demand_report(body: DemandReportReviewInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "approver", "admin")

    def review():
        result = runtime.demand_reports.review(**body.model_dump(), reviewed_by=principal.actor_id)
        return {
            "report": asdict(result["report"]),
            "review": asdict(result["review"]),
            "lineage": [asdict(item) for item in result.get("lineage", [])],
            "idempotent": result["idempotent"],
        }

    return run(review)
