from __future__ import annotations

import os
from dataclasses import asdict
from decimal import Decimal
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .automation import AutomationService, RiskLevel
from .content_growth import ContentGrowthService
from .database import create_database_engine, database_health
from .domain import AgentMode, ChargeType, ContentType, PassportType
from .imports import OzonImportService
from .intelligence import MarketIntelligenceService
from .providers import ComfyUIProvider, FirecrawlProvider, N8nProvider, OllamaProvider
from .repository import InMemoryRepository
from .services import CommerceService
from .source_connectors import source_connector_catalog
from .sourcing import ProfitInputs, SourcePlatform, SourcingService, SupplierOffer
from .sourcing_store import SqlSourcingStore
from .sql_repository import SqlAlchemyRepository

APP_VERSION = "0.2.0"
app = FastAPI(title="KJDS Control Plane", version=APP_VERSION)


def build_repository():
    if os.getenv("KJDS_REPOSITORY", "postgres").lower() == "memory":
        return InMemoryRepository()
    return SqlAlchemyRepository()


repo = build_repository()
engine = getattr(repo, "engine", None) or create_database_engine()
commerce = CommerceService(repo)
market = MarketIntelligenceService(repo)
content = ContentGrowthService(repo)
imports = OzonImportService(engine)
automation = AutomationService(engine, repo, shadow_mode=os.getenv("KJDS_SHADOW_MODE", "true").lower() != "false")
sourcing_store = SqlSourcingStore(engine)
sourcing = SourcingService(sourcing_store, repo)
providers = {
    "ollama": OllamaProvider(os.getenv("KJDS_OLLAMA_URL", "http://127.0.0.1:11434")),
    "comfyui": ComfyUIProvider(os.getenv("KJDS_COMFYUI_URL", "http://127.0.0.1:8189")),
    "n8n": N8nProvider(os.getenv("KJDS_N8N_URL", "http://127.0.0.1:5678")),
    "firecrawl": FirecrawlProvider(
        os.getenv("FIRECRAWL_API_URL", "http://127.0.0.1:3002"),
        os.getenv("FIRECRAWL_API_KEY") or None,
    ),
}


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
    kind: PassportType
    facts: dict[str, Any]
    evidence: list[str]
    approved_by: str | None = None


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
    action: str
    resource_type: str
    resource_id: str
    requested_by: str
    payload: dict[str, Any]


class ApprovalDecisionInput(BaseModel):
    approved: bool
    decided_by: str
    reason: str


class AgentTaskInput(BaseModel):
    agent: str
    mode: AgentMode
    task_type: str
    input_data: dict[str, Any]
    requested_by: str
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


class OzonListingDraftInput(BaseModel):
    product_id: str
    offer_id: str
    scenario_id: str
    requested_by: str = Field(min_length=1, max_length=200)
    listing_data: dict[str, Any]


@app.get("/health")
def health() -> dict:
    try:
        database = database_health()
        events = repo.event_count()
        status = "ok"
    except Exception as exc:
        database = {"status": "error", "detail": type(exc).__name__}
        events = None
        status = "degraded"
    return {
        "status": status,
        "service": "kjds-control-plane",
        "version": APP_VERSION,
        "database": database,
        "events": events,
    }


@app.get("/version")
def version() -> dict:
    return {
        "service": "kjds-control-plane",
        "version": APP_VERSION,
        "database_provider": os.getenv("KJDS_DATABASE_PROVIDER", "local-postgres"),
        "shadow_mode": automation.shadow_mode,
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


@app.post("/v1/sourcing/offers", status_code=201)
def capture_supplier_offer(body: SupplierOfferInput):
    offer = SupplierOffer(**body.model_dump())
    return run(lambda: sourcing.capture_offer(offer))


@app.get("/v1/sourcing/offers")
def list_supplier_offers(limit: int = 100):
    return run(lambda: sourcing_store.list_offers(min(max(limit, 1), 500)))


@app.post("/v1/sourcing/profit-scenarios", status_code=201)
def calculate_sourcing_profit(body: ProfitScenarioInput):
    values = body.model_dump()
    offer_id = values.pop("offer_id")
    return run(lambda: sourcing.calculate_profit(offer_id, ProfitInputs(**values)))


@app.post("/v1/listings/ozon/drafts", status_code=201)
def create_ozon_listing_draft(body: OzonListingDraftInput):
    def create():
        draft = sourcing.create_ozon_listing_draft(**body.model_dump())
        approval = commerce.request_approval(
            action="listing.publish",
            resource_type="listing_draft",
            resource_id=draft.id,
            requested_by=body.requested_by,
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


@app.get("/v1/products")
def list_products():
    return run(commerce.list_products)


@app.get("/v1/products/{product_id}/readiness")
def product_readiness(product_id: str):
    return run(lambda: commerce.product_readiness(product_id))


@app.post("/v1/imports/ozon", status_code=201)
async def import_ozon(file: Annotated[UploadFile, File()]):
    content_bytes = await file.read()
    return run(lambda: imports.import_file(filename=file.filename or "ozon-export", content=content_bytes))


@app.get("/v1/imports/{import_id}")
def get_import(import_id: str):
    return run(lambda: imports.get(import_id))


@app.post("/v1/products/{product_id}/passports", status_code=201)
def add_passport(product_id: str, body: PassportInput):
    return run(lambda: commerce.add_passport(product_id=product_id, **body.model_dump()))


@app.post("/v1/products/{product_id}/validate")
def validate_product(product_id: str):
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
def request_approval(body: ApprovalInput):
    return run(lambda: commerce.request_approval(**body.model_dump()))


@app.post("/v1/approvals/{approval_id}/decision")
def decide_approval(approval_id: str, body: ApprovalDecisionInput):
    return run(lambda: commerce.decide_approval(approval_id, **body.model_dump()))


@app.post("/v1/agent-tasks", status_code=201)
def submit_agent_task(body: AgentTaskInput):
    return run(lambda: commerce.submit_agent_task(**body.model_dump()))


@app.get("/v1/events")
def events(after: int = 0):
    return repo.events_after(after)
