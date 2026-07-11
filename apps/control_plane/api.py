from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .content_growth import ContentGrowthService
from .database import database_health
from .domain import AgentMode, ChargeType, ContentType, PassportType
from .intelligence import MarketIntelligenceService
from .repository import InMemoryRepository
from .services import CommerceService

app = FastAPI(title="KJDS Control Plane", version="0.1.0")
repo = InMemoryRepository()
commerce = CommerceService(repo)
market = MarketIntelligenceService(repo)
content = ContentGrowthService(repo)


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


@app.get("/health")
def health() -> dict:
    try:
        database = database_health()
        status = "ok"
    except Exception as exc:
        database = {"status": "error", "detail": type(exc).__name__}
        status = "degraded"
    return {"status": status, "database": database, "events": len(repo.events)}


@app.post("/v1/products", status_code=201)
def create_product(body: ProductInput):
    return run(lambda: commerce.create_product(**body.model_dump()))


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
    return [event for event in repo.events if event["sequence"] > after]
