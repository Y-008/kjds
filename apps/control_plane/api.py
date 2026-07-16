from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .automation import AutomationService, RiskLevel
from .content_growth import ContentGrowthService
from .database import create_database_engine, database_health
from .domain import AgentMode, ChargeType, ContentType, PassportType
from .evidence import EvidenceGrade, EvidenceService
from .facts import FactPromotionService
from .finance import CashPlanStatus, FeeSignRule, FinanceEntryKind, FinanceService
from .imports import MAX_IMPORT_BYTES, OzonImportService
from .intake import PassportEvidencePayload, SkuEpisodeIntakeService
from .intelligence import MarketIntelligenceService
from .ozon_contracts import contract_catalog
from .providers import ComfyUIProvider, FirecrawlProvider, N8nProvider, OllamaProvider
from .readiness import GateReadinessService
from .repository import InMemoryRepository
from .security import (
    ApiKeyAuthenticator,
    AuthenticationFailure,
    KillSwitchService,
    Principal,
    WritesDisabled,
    require_any_role,
)
from .services import CommerceService
from .source_connectors import source_connector_catalog
from .sourcing import ProfitInputs, SourcePlatform, SourcingService, SupplierOffer
from .sourcing_store import SqlSourcingStore
from .sql_repository import SqlAlchemyRepository

APP_VERSION = "0.11.0"
app = FastAPI(title="KJDS Control Plane", version=APP_VERSION)


def build_repository():
    if os.getenv("KJDS_REPOSITORY", "postgres").lower() == "memory":
        return InMemoryRepository()
    return SqlAlchemyRepository()


repo = build_repository()
engine = getattr(repo, "engine", None) or create_database_engine()
evidence = EvidenceService(engine)
commerce = CommerceService(repo, evidence_validator=evidence.require_valid)
intake = SkuEpisodeIntakeService(commerce=commerce, evidence=evidence)
market = MarketIntelligenceService(repo)
content = ContentGrowthService(repo)
imports = OzonImportService(engine)
facts = FactPromotionService(engine)
finance = FinanceService(engine)
automation = AutomationService(engine, repo, shadow_mode=os.getenv("KJDS_SHADOW_MODE", "true").lower() != "false")
sourcing_store = SqlSourcingStore(engine)
sourcing = SourcingService(sourcing_store, repo, evidence_validator=evidence.require_valid)
readiness = GateReadinessService(
    commerce=commerce,
    sourcing_store=sourcing_store,
    evidence=evidence,
    facts=facts,
    finance=finance,
)
authenticator = ApiKeyAuthenticator.from_environment()
kill_switch = KillSwitchService(engine)
providers = {
    "ollama": OllamaProvider(os.getenv("KJDS_OLLAMA_URL", "http://127.0.0.1:11434")),
    "comfyui": ComfyUIProvider(os.getenv("KJDS_COMFYUI_URL", "http://127.0.0.1:8189")),
    "n8n": N8nProvider(os.getenv("KJDS_N8N_URL", "http://127.0.0.1:5678")),
    "firecrawl": FirecrawlProvider(
        os.getenv("FIRECRAWL_API_URL", "http://127.0.0.1:3002"),
        os.getenv("FIRECRAWL_API_KEY") or None,
    ),
}

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
KILL_SWITCH_CONTROL_PATHS = {
    "/v1/system/kill-switch/engage",
    "/v1/system/kill-switch/release",
}


@app.middleware("http")
async def enforce_control_plane_security(request: Request, call_next):
    if request.url.path.startswith("/v1/"):
        try:
            request.state.principal = authenticator.authenticate(request.headers.get("X-KJDS-API-Key"))
        except AuthenticationFailure as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

        if request.method in WRITE_METHODS and request.url.path not in KILL_SWITCH_CONTROL_PATHS:
            if not request.state.principal.has_any_role("operator", "reviewer", "compliance", "approver", "admin"):
                return JSONResponse(status_code=403, content={"detail": "Authenticated actor has no write role"})
            try:
                kill_switch.ensure_writes_allowed()
            except WritesDisabled as exc:
                return JSONResponse(status_code=423, content={"detail": str(exc)})
            except Exception:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Write safety state is unavailable; writes fail closed"},
                )
    return await call_next(request)


def current_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="Authenticated identity is required")
    return principal


def ensure_role(principal: Principal, *roles: str) -> None:
    try:
        require_any_role(principal, *roles)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


def run(call):
    try:
        value = call()
        return asdict(value) if hasattr(value, "__dataclass_fields__") else value
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class ProductInput(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=300)


class PassportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: PassportType
    facts: dict[str, Any]
    evidence: list[str]


class PassportReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    decision: str
    review_notes: str = Field(default="", max_length=2000)


class OrderInput(BaseModel):
    external_id: str
    product_id: str
    quantity: int
    currency: str
    gross_revenue: Decimal
    booked_fx_rate: Decimal


class ChargeInput(BaseModel):
    kind: ChargeType
    amount: Decimal
    currency: str
    fx_rate: Decimal
    evidence_ref: str


class ObservationInput(BaseModel):
    source: str
    market: str
    category: str
    metric: str
    value: Decimal
    observed_at: str
    source_ref: str
    confidence: Decimal
    dimensions: dict[str, str] = Field(default_factory=dict)


class OpportunityInput(BaseModel):
    market: str
    category: str
    weights: dict[str, Decimal]
    recommended_action: str


class ContentBriefInput(BaseModel):
    product_id: str
    content_type: ContentType
    locale: str = "ru-RU"
    channel: str = "OZON"
    brief: dict[str, Any]


class AssetAttachInput(BaseModel):
    artifact_ref: str


class AssetReviewInput(BaseModel):
    checks: list[dict[str, Any]]


class ExperimentInput(BaseModel):
    product_id: str
    channel: str = "OZON"
    hypothesis: str
    primary_metric: str
    budget_cap_cny: Decimal
    stop_loss_cny: Decimal
    variants: list[str]


class ApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    resource_type: str
    resource_id: str
    payload: dict[str, Any]


class ApprovalDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    reason: str = Field(min_length=1)


class AgentTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    mode: AgentMode
    task_type: str
    input_data: dict[str, Any]
    idempotency_key: str


class RecommendationInput(BaseModel):
    product_id: str | None = None
    agent: str = Field(min_length=1, max_length=80)
    action: str = Field(min_length=1, max_length=200)
    rationale: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    expected_cm3_delta: Decimal | None = None
    risk: RiskLevel


class SupplierOfferInput(BaseModel):
    product_id: str = Field(min_length=1)
    supplier_ref: str = Field(min_length=1, max_length=300)
    platform: SourcePlatform
    external_id: str = Field(min_length=1, max_length=200)
    source_url: str = Field(min_length=8)
    title: str = Field(min_length=1, max_length=1000)
    currency: str = Field(min_length=3, max_length=3)
    unit_price: Decimal
    source_to_cny_rate: Decimal
    min_order_quantity: int = Field(ge=1)
    weight_kg: Decimal
    length_cm: Decimal = Decimal("0")
    width_cm: Decimal = Decimal("0")
    height_cm: Decimal = Decimal("0")
    domestic_logistics_per_unit: Decimal = Decimal("0")
    evidence_ref: str = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)
    media: list[str] = Field(default_factory=list)


class ProfitScenarioInput(BaseModel):
    offer_id: str
    sale_price_rub: Decimal
    rub_per_cny: Decimal
    international_freight_cny_per_kg: Decimal
    packaging_cny: Decimal = Decimal("0")
    last_mile_cny: Decimal = Decimal("0")
    customs_rate: Decimal = Decimal("0")
    platform_fee_rate: Decimal
    advertising_rate: Decimal = Decimal("0")
    return_reserve_rate: Decimal = Decimal("0")
    other_cost_cny: Decimal = Decimal("0")
    evidence: list[str] = Field(min_length=1)


class OzonListingDraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    offer_id: str
    scenario_id: str
    listing_data: dict[str, Any]


class KillSwitchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class LineageLinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(min_length=1, max_length=100)
    target_id: str = Field(min_length=1, max_length=300)
    relationship: str = Field(min_length=1, max_length=100)


class FeeMappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=80)
    raw_code: str = Field(min_length=1, max_length=300)
    canonical_type: ChargeType
    sign_rule: FeeSignRule
    effective_from: str
    effective_until: str | None = None
    evidence_id: str = Field(min_length=1)


class FxRateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_currency: str
    quote_currency: str = "CNY"
    rate: Decimal
    effective_at: str
    source: str = Field(min_length=1, max_length=200)
    evidence_id: str = Field(min_length=1)


class FinanceEntryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_kind: FinanceEntryKind
    source: str = Field(min_length=1, max_length=100)
    source_ref: str = Field(min_length=1, max_length=500)
    reconciliation_key: str = Field(min_length=1, max_length=300)
    raw_fee_code: str | None = None
    amount: Decimal
    currency: str
    effective_at: str
    evidence_id: str = Field(min_length=1)
    review_required: bool = False


class ReconciliationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_currency: str = "CNY"
    fx_source: str = Field(min_length=1, max_length=200)
    tolerance_ratio: Decimal = Decimal("0.003")


class CashPlanItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=100)
    source_ref: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=100)
    amount: Decimal
    currency: str
    expected_at: str
    probability: Decimal
    status: CashPlanStatus
    evidence_id: str = Field(min_length=1)


@app.get("/health")
def health() -> dict:
    try:
        database = database_health()
        events = repo.event_count()
        write_safety = asdict(kill_switch.current())
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
        "security": {
            "api_identity_configured": authenticator.configured,
            "write_safety": write_safety,
        },
    }


@app.get("/version")
def version() -> dict:
    return {
        "service": "kjds-control-plane",
        "version": APP_VERSION,
        "database_provider": os.getenv("KJDS_DATABASE_PROVIDER", "local-postgres"),
        "shadow_mode": automation.shadow_mode,
        "api_identity_configured": authenticator.configured,
    }


@app.get("/health/live")
def live() -> dict:
    return {"status": "ok", "service": "kjds-control-plane", "version": APP_VERSION}


@app.get("/health/ready")
def ready() -> dict:
    return health()


@app.get("/v1/integrations/health")
def integration_health() -> dict:
    return {name: asdict(provider.healthcheck()) for name, provider in providers.items()}


@app.get("/v1/system/kill-switch")
def kill_switch_state():
    return asdict(kill_switch.current())


@app.post("/v1/system/kill-switch/engage")
def engage_kill_switch(body: KillSwitchInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "risk", "admin")
    return asdict(kill_switch.set_state(engaged=True, reason=body.reason, actor_id=principal.actor_id))


@app.post("/v1/system/kill-switch/release")
def release_kill_switch(body: KillSwitchInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "admin")
    return asdict(kill_switch.set_state(engaged=False, reason=body.reason, actor_id=principal.actor_id))


@app.post("/v1/evidence", status_code=201)
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
    return run(
        lambda: evidence.capture(
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


@app.get("/v1/evidence")
def list_evidence(limit: int = 100):
    return [asdict(item) for item in evidence.list(min(max(limit, 1), 500))]


@app.get("/v1/evidence/{evidence_id}")
def get_evidence(evidence_id: str):
    return run(lambda: evidence.get(evidence_id))


@app.get("/v1/evidence/{evidence_id}/verify")
def verify_evidence(evidence_id: str):
    return run(lambda: evidence.verify(evidence_id))


@app.get("/v1/evidence/{evidence_id}/content")
def evidence_content(evidence_id: str):
    def load():
        content_bytes, record = evidence.content(evidence_id)
        return Response(
            content=content_bytes,
            media_type=record.content_type,
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(record.filename)}"},
        )

    return run(load)


@app.post("/v1/evidence/{evidence_id}/lineage", status_code=201)
def link_evidence(
    evidence_id: str,
    body: LineageLinkInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: evidence.link(evidence_id=evidence_id, **body.model_dump(), created_by=principal.actor_id))


@app.get("/v1/evidence/{evidence_id}/lineage")
def evidence_lineage(evidence_id: str):
    return [asdict(item) for item in evidence.lineage(evidence_id)]


@app.post("/v1/models/discover")
def discover_models():
    return run(lambda: automation.sync_ollama_models(providers["ollama"]))


@app.get("/v1/models")
def list_models():
    return run(automation.list_models)


@app.post("/v1/recommendations", status_code=201)
def create_recommendation(body: RecommendationInput):
    return run(lambda: automation.create_recommendation(**body.model_dump()))


@app.get("/v1/recommendations")
def list_recommendations():
    return run(automation.list_recommendations)


@app.get("/v1/sourcing/connectors")
def sourcing_connectors():
    return source_connector_catalog()


@app.get("/v1/operations/readiness")
def operations_readiness():
    return run(readiness.report)


@app.post("/v1/operations/gate-evidence", status_code=201)
async def capture_gate_requirement_evidence(
    requirement_id: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    requirement_id = requirement_id.strip().upper()
    allowed = {
        "GOV-001": ("approver", "admin"),
        "OZN-001": ("reviewer", "compliance", "admin"),
    }
    roles = allowed.get(requirement_id)
    if roles is None:
        raise HTTPException(status_code=422, detail="Unsupported gate requirement")
    ensure_role(principal, *roles)
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Evidence file exceeds {max_bytes} bytes")
    digest = hashlib.sha256(content_bytes).hexdigest()

    def capture_and_link():
        record = evidence.capture(
            content=content_bytes,
            filename=file.filename or f"{requirement_id}-evidence.bin",
            content_type=file.content_type or "application/octet-stream",
            source="gate_requirement",
            source_ref=f"gate://{requirement_id}/sha256/{digest}",
            grade=EvidenceGrade.A,
            effective_at=effective_at,
            effective_until=None,
            created_by=principal.actor_id,
            metadata={"requirement_id": requirement_id},
        )
        edge = evidence.link(
            evidence_id=record.id,
            target_type="gate_requirement",
            target_id=requirement_id,
            relationship="satisfies",
            created_by=principal.actor_id,
        )
        return {"evidence": asdict(record), "lineage": asdict(edge)}

    return run(capture_and_link)


@app.post("/v1/sourcing/offers", status_code=201)
def capture_supplier_offer(
    body: SupplierOfferInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    offer = SupplierOffer(**body.model_dump())

    def capture():
        result = sourcing.capture_offer(offer)
        evidence.link(
            evidence_id=result.evidence_ref,
            target_type="supplier_offer",
            target_id=result.id,
            relationship="source_for",
            created_by=principal.actor_id,
        )
        return result

    return run(capture)


@app.get("/v1/sourcing/offers")
def list_supplier_offers(limit: int = 100):
    return run(lambda: sourcing_store.list_offers(min(max(limit, 1), 500)))


@app.post("/v1/sourcing/profit-scenarios", status_code=201)
def calculate_sourcing_profit(
    body: ProfitScenarioInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    values = body.model_dump()
    offer_id = values.pop("offer_id")
    assumption_evidence = values.pop("evidence")

    def calculate():
        result = sourcing.calculate_profit(offer_id, ProfitInputs(**values), assumption_evidence)
        for evidence_id in result.evidence:
            evidence.link(
                evidence_id=evidence_id,
                target_type="profit_scenario",
                target_id=result.id,
                relationship="supports",
                created_by=principal.actor_id,
            )
        return result

    return run(calculate)


@app.post("/v1/listings/ozon/drafts", status_code=201)
def create_ozon_listing_draft(
    body: OzonListingDraftInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")

    def create():
        draft = sourcing.create_ozon_listing_draft(**body.model_dump(), requested_by=principal.actor_id)
        approval = commerce.request_approval(
            action="listing.publish",
            resource_type="listing_draft",
            resource_id=draft.id,
            requested_by=principal.actor_id,
            payload={
                "target_platform": "OZON",
                "product_id": body.product_id,
                "scenario_id": body.scenario_id,
            },
        )
        draft.approval_id = approval.id
        sourcing_store.attach_listing_approval(draft)
        return {"draft": asdict(draft), "approval": asdict(approval)}

    return run(create)


@app.get("/v1/listings/ozon/drafts")
def list_ozon_listing_drafts(limit: int = 100):
    return run(lambda: sourcing_store.list_listing_drafts(min(max(limit, 1), 500)))


@app.post("/v1/products", status_code=201)
def create_product(body: ProductInput):
    return run(lambda: commerce.create_product(**body.model_dump()))


@app.post("/v1/intake/sku-episodes", status_code=201)
async def intake_sku_episode(
    sku: Annotated[str, Form()],
    name: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    product_facts_json: Annotated[str, Form()],
    compliance_facts_json: Annotated[str, Form()],
    quality_facts_json: Annotated[str, Form()],
    product_evidence: Annotated[UploadFile, File()],
    compliance_evidence: Annotated[UploadFile, File()],
    quality_evidence: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    facts_by_kind: dict[PassportType, dict] = {}
    for kind, raw in (
        (PassportType.PRODUCT, product_facts_json),
        (PassportType.COMPLIANCE, compliance_facts_json),
        (PassportType.QUALITY, quality_facts_json),
    ):
        try:
            facts = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"{kind.value}_facts_json must be valid JSON") from exc
        if not isinstance(facts, dict):
            raise HTTPException(status_code=422, detail=f"{kind.value}_facts_json must be a JSON object")
        facts_by_kind[kind] = facts

    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    uploads = {
        PassportType.PRODUCT: product_evidence,
        PassportType.COMPLIANCE: compliance_evidence,
        PassportType.QUALITY: quality_evidence,
    }
    payloads = []
    for kind, upload in uploads.items():
        content = await upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"{kind.value} evidence exceeds {max_bytes} bytes")
        payloads.append(
            PassportEvidencePayload(
                kind=kind,
                facts=facts_by_kind[kind],
                content=content,
                filename=upload.filename or f"{kind.value}-evidence.bin",
                content_type=upload.content_type or "application/octet-stream",
            )
        )
    return run(
        lambda: intake.ingest(
            sku=sku,
            name=name,
            effective_at=effective_at,
            payloads=payloads,
            created_by=principal.actor_id,
        )
    )


@app.get("/v1/products")
def list_products():
    return run(commerce.list_products)


@app.get("/v1/products/{product_id}/readiness")
def product_readiness(product_id: str):
    return run(lambda: commerce.product_readiness(product_id))


@app.get("/v1/passport-reviews")
def passport_review_queue(principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(commerce.passport_review_queue)


@app.post("/v1/products/{product_id}/passports/{kind}/review", status_code=201)
def review_passport(
    product_id: str,
    kind: PassportType,
    body: PassportReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: commerce.review_passport(
            product_id=product_id,
            kind=kind,
            reviewed_by=principal.actor_id,
            **body.model_dump(),
        )
    )


@app.get("/v1/contracts/ozon")
def ozon_contracts():
    return contract_catalog()


@app.post("/v1/imports/ozon", status_code=201)
async def import_ozon(
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
    effective_at: Annotated[str | None, Form()] = None,
):
    ensure_role(principal, "operator", "admin")
    content_bytes = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content_bytes) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail=f"Import file exceeds {MAX_IMPORT_BYTES} bytes")
    existing = imports.find_by_content(content_bytes)
    if existing is not None:
        return asdict(existing)

    filename = file.filename or "ozon-export"
    digest = hashlib.sha256(content_bytes).hexdigest()
    captured_at = effective_at or datetime.now(UTC).isoformat()

    def capture_and_import():
        source = evidence.capture(
            content=content_bytes,
            filename=filename,
            content_type=file.content_type or "application/octet-stream",
            source="ozon_export",
            source_ref=f"ozon-upload://sha256/{digest}",
            grade=EvidenceGrade.A,
            effective_at=captured_at,
            effective_until=None,
            created_by=principal.actor_id,
            metadata={"filename": filename, "sha256": digest},
        )
        result = imports.import_file(filename=filename, content=content_bytes, evidence_id=source.id)
        evidence.link(
            evidence_id=source.id,
            target_type="import_job",
            target_id=result.id,
            relationship="source_for",
            created_by=principal.actor_id,
        )
        return result

    return run(capture_and_import)


@app.get("/v1/imports/{import_id}")
def get_import(import_id: str):
    return run(lambda: imports.get(import_id))


@app.post("/v1/imports/{import_id}/promote", status_code=201)
def promote_import(
    import_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: facts.promote(import_id, created_by=principal.actor_id))


@app.get("/v1/facts")
def list_facts(fact_type: str | None = None, limit: int = 100):
    return run(lambda: facts.list(fact_type=fact_type, limit=min(max(limit, 1), 500)))


@app.get("/v1/facts/{fact_id}")
def get_fact(fact_id: str):
    return run(lambda: facts.get(fact_id))


@app.post("/v1/finance/fee-mappings", status_code=201)
def register_fee_mapping(
    body: FeeMappingInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: finance.register_fee_mapping(**body.model_dump(), approved_by=principal.actor_id))


@app.get("/v1/finance/fee-mappings")
def list_fee_mappings(provider: str | None = None):
    return run(lambda: finance.list_fee_mappings(provider=provider))


@app.post("/v1/finance/fx-rates", status_code=201)
def add_fx_rate(
    body: FxRateInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: finance.add_fx_rate(**body.model_dump(), created_by=principal.actor_id))


@app.get("/v1/finance/fx-rates")
def list_fx_rates(base_currency: str | None = None):
    return run(lambda: finance.list_fx_rates(base_currency=base_currency))


@app.post("/v1/finance/facts/{fact_id}/ingest", status_code=201)
def ingest_finance_fact(
    fact_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: finance.ingest_fact(fact_id, created_by=principal.actor_id))


@app.post("/v1/finance/entries", status_code=201)
def record_finance_entry(
    body: FinanceEntryInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: finance.record_entry(**body.model_dump(), created_by=principal.actor_id))


@app.get("/v1/finance/entries")
def list_finance_entries(
    reconciliation_key: str | None = None,
    entry_kind: FinanceEntryKind | None = None,
):
    return run(lambda: finance.list_entries(reconciliation_key=reconciliation_key, entry_kind=entry_kind))


@app.get("/v1/finance/unknown-fees")
def list_unknown_fees(provider: str = "ozon"):
    return run(lambda: finance.unknown_fee_entries(provider=provider))


@app.post("/v1/finance/reconciliations/{reconciliation_key}", status_code=201)
def reconcile_finance(
    reconciliation_key: str,
    body: ReconciliationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: finance.reconcile(
            reconciliation_key,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
    )


@app.post("/v1/finance/cash-plan", status_code=201)
def add_cash_plan_item(
    body: CashPlanItemInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: finance.add_cash_plan_item(**body.model_dump(), created_by=principal.actor_id))


@app.get("/v1/finance/cash-forecast")
def cash_forecast(
    start_at: str,
    opening_balance: Decimal,
    fx_source: str,
    quote_currency: str = "CNY",
):
    return run(
        lambda: finance.cash_forecast(
            start_at=start_at,
            opening_balance=opening_balance,
            quote_currency=quote_currency,
            fx_source=fx_source,
        )
    )


@app.post("/v1/products/{product_id}/passports", status_code=201)
def add_passport(
    product_id: str,
    body: PassportInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    decision = body.facts.get("decision")
    reviewed = decision in {"approved", "rejected", "blocked"}
    if reviewed:
        ensure_role(principal, "reviewer", "compliance", "admin")
    def create_and_link():
        passport = commerce.add_passport(
            product_id=product_id,
            **body.model_dump(),
            approved_by=principal.actor_id if reviewed else None,
        )
        for evidence_id in passport.evidence:
            evidence.link(
                evidence_id=evidence_id,
                target_type="passport",
                target_id=passport.id,
                relationship="supports",
                created_by=principal.actor_id,
            )
        return passport

    return run(create_and_link)


@app.post("/v1/products/{product_id}/validate")
def validate_product(
    product_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: commerce.validate_product(product_id))


@app.post("/v1/market/observations", status_code=201)
def ingest_observation(body: ObservationInput):
    return run(lambda: market.ingest(**body.model_dump()))


@app.post("/v1/market/opportunities", status_code=201)
def score_opportunity(body: OpportunityInput):
    return run(lambda: market.score_opportunity(**body.model_dump()))


@app.post("/v1/content/assets", status_code=201)
def create_content_asset(body: ContentBriefInput):
    return run(lambda: content.create_content_brief(**body.model_dump()))


@app.post("/v1/content/assets/{asset_id}/generated")
def attach_content_asset(asset_id: str, body: AssetAttachInput):
    return run(lambda: content.attach_generated_asset(asset_id, **body.model_dump()))


@app.post("/v1/content/assets/{asset_id}/review")
def review_content_asset(asset_id: str, body: AssetReviewInput):
    return run(lambda: content.review_asset(asset_id, **body.model_dump()))


@app.post("/v1/experiments", status_code=201)
def create_experiment(body: ExperimentInput):
    return run(lambda: content.create_experiment(**body.model_dump()))


@app.post("/v1/experiments/{experiment_id}/start")
def start_experiment(experiment_id: str):
    return run(lambda: content.start_experiment(experiment_id))


@app.post("/v1/orders", status_code=201)
def create_order(body: OrderInput):
    return run(lambda: commerce.create_order(**body.model_dump()))


@app.post("/v1/orders/{order_id}/charges", status_code=201)
def add_charge(order_id: str, body: ChargeInput):
    return run(lambda: commerce.add_charge(order_id=order_id, **body.model_dump()))


@app.get("/v1/orders/{order_id}/profit")
def profit(order_id: str):
    return run(lambda: commerce.calculate_profit(order_id))


@app.post("/v1/approvals", status_code=201)
def request_approval(body: ApprovalInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: commerce.request_approval(**body.model_dump(), requested_by=principal.actor_id))


@app.post("/v1/approvals/{approval_id}/decision")
def decide_approval(
    approval_id: str,
    body: ApprovalDecisionInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "approver", "admin")
    return run(lambda: commerce.decide_approval(approval_id, **body.model_dump(), decided_by=principal.actor_id))


@app.post("/v1/agent-tasks", status_code=201)
def submit_agent_task(body: AgentTaskInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: commerce.submit_agent_task(**body.model_dump(), requested_by=principal.actor_id))


@app.get("/v1/events")
def events(after: int = 0):
    return repo.events_after(after)
