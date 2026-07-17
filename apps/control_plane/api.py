from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .automation import AutomationService, RiskLevel
from .causal_experiments import CausalExperimentService, ExperimentEvent
from .causal_knowledge import (
    CausalKnowledgeService,
    ExperimentReviewVerdict,
)
from .content_growth import ContentGrowthService
from .database import create_database_engine, database_health
from .decision_contracts import DecisionContractService
from .decision_contracts import RiskLevel as DecisionRiskLevel
from .decision_lifecycle import (
    DecisionDisposition,
    DecisionLifecycleService,
    ReviewVerdict,
)
from .domain import AgentMode, ChargeType, ContentType, PassportType
from .evidence import EvidenceGrade, EvidenceService
from .facts import FactPromotionService
from .finance import CashPlanStatus, FeeSignRule, FinanceEntryKind, FinanceService
from .imports import MAX_IMPORT_BYTES, OzonImportService
from .intake import PassportEvidencePayload, SkuEpisodeIntakeService
from .intelligence import MarketIntelligenceService
from .ozon_contracts import contract_catalog
from .procurement import ProcurementService
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
from .sourcing_intake import OfferEvidencePayload, SupplierComparisonIntakeService
from .sourcing_store import SqlSourcingStore
from .sql_repository import SqlAlchemyRepository

APP_VERSION = "0.18.0"
app = FastAPI(title="KJDS Control Plane", version=APP_VERSION)


def build_repository():
    if os.getenv("KJDS_REPOSITORY", "postgres").lower() == "memory":
        return InMemoryRepository()
    return SqlAlchemyRepository()


repo = build_repository()
engine = getattr(repo, "engine", None) or create_database_engine()
evidence = EvidenceService(engine)
decision_contracts = DecisionContractService(engine=engine, evidence=evidence)
decision_lifecycle = DecisionLifecycleService(
    engine=engine,
    contracts=decision_contracts,
    evidence=evidence,
)
causal_experiments = CausalExperimentService(
    engine=engine,
    decisions=decision_lifecycle,
    evidence=evidence,
)
causal_knowledge = CausalKnowledgeService(
    engine=engine,
    experiments=causal_experiments,
    evidence=evidence,
)
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
sourcing_intake = SupplierComparisonIntakeService(sourcing=sourcing, evidence=evidence)
procurement = ProcurementService(
    engine=engine,
    repository=repo,
    sourcing_store=sourcing_store,
    sourcing=sourcing,
    evidence=evidence,
)
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


class ProcurementCandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str
    offer_id: str
    scenario_id: str
    quantity: int = Field(ge=1)
    rationale: str = Field(min_length=1, max_length=2000)


class SampleOrderInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(min_length=1)


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


class DecisionContractInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str = Field(min_length=1, max_length=80)
    objective: str = Field(min_length=1, max_length=5000)
    decision_domain: str = Field(min_length=1, max_length=100)
    risk_level: DecisionRiskLevel
    horizon_days: int | None = Field(default=None, ge=1, le=3650)
    maximum_loss_amount: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="CNY", min_length=3, max_length=3)
    source_contract_id: str | None = None
    facts: dict[str, Any] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    options: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class DecisionAnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conclusion: str = Field(min_length=1, max_length=10000)
    confidence: Decimal = Field(ge=0, le=1)
    recommended_option_id: str | None = None
    forecast_metric: str | None = None
    forecast_value: Decimal | None = None
    forecast_low: Decimal | None = None
    forecast_high: Decimal | None = None
    forecast_unit: str | None = None
    forecast_due_at: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    model_ref: str | None = None


class DecisionAnalysisReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: ReviewVerdict
    rationale: str = Field(min_length=1, max_length=10000)
    counterarguments: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class DecisionResolutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str = Field(min_length=1)
    disposition: DecisionDisposition
    rationale: str = Field(min_length=1, max_length=10000)
    conditions: list[str] = Field(default_factory=list)


class DecisionOutcomeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual_value: Decimal
    observed_at: str
    evidence_ids: list[str] = Field(min_length=1)
    notes: str = Field(min_length=1, max_length=10000)


class ExperimentVariantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=300)
    allocation: Decimal = Field(gt=0, le=1)
    control: bool


class ExperimentGuardrailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1, max_length=200)
    direction: Literal["min", "max"]
    threshold: Decimal


class ExperimentEffectMetricInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1, max_length=200)
    role: Literal[
        "cannibalization",
        "long_term_cost",
        "long_term_value",
        "secondary",
    ]
    multiplier: Decimal
    required: bool = True


class CausalExperimentProtocolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis: str = Field(min_length=1, max_length=10000)
    primary_metric: str = Field(min_length=1, max_length=200)
    randomization_unit: str = Field(min_length=1, max_length=100)
    interference_cluster: str | None = Field(default=None, max_length=100)
    variants: list[ExperimentVariantInput] = Field(min_length=2, max_length=2)
    target_sample_size: int = Field(ge=20)
    minimum_detectable_effect: Decimal = Field(gt=0)
    budget_cap_amount: Decimal = Field(gt=0)
    stop_loss_amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    start_at: str
    end_at: str
    outcome_window_days: int = Field(default=30, ge=0, le=365)
    guardrails: list[ExperimentGuardrailInput] = Field(min_length=1)
    stratification_keys: list[str] = Field(default_factory=list, max_length=3)
    effect_metrics: list[ExperimentEffectMetricInput] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)


class ExperimentTransitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: ExperimentEvent
    effective_at: str
    evidence_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=10000)


class ExperimentAssignmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_key: str = Field(min_length=1, max_length=1000)
    assigned_at: str
    strata: dict[str, str] = Field(default_factory=dict)


class ExperimentObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Decimal
    observed_at: str
    evidence_id: str = Field(min_length=1)
    metric: str | None = Field(default=None, max_length=200)


class ExperimentSafetyCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1, max_length=200)
    value: Decimal
    observed_at: str
    evidence_id: str = Field(min_length=1)


class CausalExperimentReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: ExperimentReviewVerdict
    rationale: str = Field(min_length=1, max_length=10000)
    method_assessment: str = Field(min_length=1, max_length=10000)
    data_quality_assessment: str = Field(min_length=1, max_length=10000)
    counterarguments: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class CausalKnowledgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1)
    claim: str = Field(min_length=1, max_length=10000)
    mechanism: str = Field(min_length=1, max_length=10000)
    applicability: dict[str, Any]
    falsification_conditions: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    valid_from: str
    reevaluate_at: str
    replicates_knowledge_id: str | None = None
    replication_rationale: str | None = Field(default=None, max_length=10000)


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


@app.get("/v1/interaction-profiles")
def interaction_profiles():
    return decision_contracts.profiles()


@app.post("/v1/decision-contracts", status_code=201)
def create_decision_contract(
    body: DecisionContractInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "admin")
    return run(
        lambda: decision_contracts.create(
            **body.model_dump(),
            requested_by=principal.actor_id,
        )
    )


@app.get("/v1/decision-contracts")
def list_decision_contracts(limit: int = 100):
    return decision_contracts.list(limit)


@app.get("/v1/decision-contracts/{contract_id}")
def get_decision_contract(contract_id: str):
    return run(lambda: decision_contracts.get(contract_id))


@app.post("/v1/decision-contracts/{contract_id}/analyses", status_code=201)
def submit_decision_analysis(
    contract_id: str,
    body: DecisionAnalysisInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: decision_lifecycle.submit_analysis(
            contract_id,
            **body.model_dump(),
            submitted_by=principal.actor_id,
        )
    )


@app.get("/v1/decision-analyses")
def list_decision_analyses(contract_id: str | None = None):
    return decision_lifecycle.list_analyses(contract_id)


@app.get("/v1/decision-analyses/{analysis_id}")
def get_decision_analysis(analysis_id: str):
    return run(lambda: decision_lifecycle.get_analysis(analysis_id))


@app.post("/v1/decision-analyses/{analysis_id}/reviews", status_code=201)
def review_decision_analysis(
    analysis_id: str,
    body: DecisionAnalysisReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: decision_lifecycle.review_analysis(
            analysis_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
    )


@app.get("/v1/decision-analyses/{analysis_id}/reviews")
def list_decision_analysis_reviews(analysis_id: str):
    return decision_lifecycle.list_reviews(analysis_id)


@app.post("/v1/decision-contracts/{contract_id}/resolution", status_code=201)
def resolve_decision_contract(
    contract_id: str,
    body: DecisionResolutionInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: decision_lifecycle.resolve(
            contract_id,
            **body.model_dump(),
            decided_by=principal.actor_id,
        )
    )


@app.get("/v1/decision-resolutions")
def list_decision_resolutions():
    return decision_lifecycle.list_resolutions()


@app.post("/v1/decision-resolutions/{resolution_id}/outcome", status_code=201)
def record_decision_outcome(
    resolution_id: str,
    body: DecisionOutcomeInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: decision_lifecycle.record_outcome(
            resolution_id,
            **body.model_dump(),
            recorded_by=principal.actor_id,
        )
    )


@app.get("/v1/decision-outcomes")
def list_decision_outcomes():
    return decision_lifecycle.list_outcomes()


@app.get("/v1/decision-calibration")
def decision_calibration():
    return decision_lifecycle.calibration()


@app.post(
    "/v1/decision-resolutions/{resolution_id}/experiment",
    status_code=201,
)
def register_causal_experiment(
    resolution_id: str,
    body: CausalExperimentProtocolInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: causal_experiments.register(
            resolution_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
    )


@app.get("/v1/causal-experiments")
def list_causal_experiments():
    return causal_experiments.list()


@app.get("/v1/causal-experiments/{protocol_id}")
def get_causal_experiment(protocol_id: str):
    return run(lambda: causal_experiments.get(protocol_id))


@app.get("/v1/causal-experiments/{protocol_id}/evaluation")
def evaluate_causal_experiment(protocol_id: str):
    return run(lambda: causal_experiments.evaluate(protocol_id))


@app.post("/v1/causal-experiments/{protocol_id}/events", status_code=201)
def transition_causal_experiment(
    protocol_id: str,
    body: ExperimentTransitionInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: causal_experiments.transition(
            protocol_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
    )


@app.post("/v1/causal-experiments/{protocol_id}/assignments", status_code=201)
def assign_causal_experiment(
    protocol_id: str,
    body: ExperimentAssignmentInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: causal_experiments.assign(protocol_id, **body.model_dump()))


@app.post(
    "/v1/causal-experiment-assignments/{assignment_id}/observation",
    status_code=201,
)
def observe_causal_experiment(
    assignment_id: str,
    body: ExperimentObservationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: causal_experiments.observe(
            assignment_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
    )


@app.post("/v1/causal-experiments/{protocol_id}/safety-checks", status_code=201)
def record_causal_experiment_safety(
    protocol_id: str,
    body: ExperimentSafetyCheckInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: causal_experiments.record_safety_check(
            protocol_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
    )


@app.post("/v1/causal-experiments/{protocol_id}/reviews", status_code=201)
def review_causal_experiment(
    protocol_id: str,
    body: CausalExperimentReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: causal_knowledge.review_experiment(
            protocol_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
    )


@app.get("/v1/causal-experiments/{protocol_id}/reviews")
def list_causal_experiment_reviews(protocol_id: str):
    return run(lambda: causal_knowledge.list_reviews(protocol_id))


@app.post("/v1/causal-experiments/{protocol_id}/knowledge", status_code=201)
def publish_causal_knowledge(
    protocol_id: str,
    body: CausalKnowledgeInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: causal_knowledge.publish(
            protocol_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
    )


@app.get("/v1/causal-knowledge")
def list_causal_knowledge(usable_only: bool = False):
    return causal_knowledge.list(usable_only=usable_only)


@app.get("/v1/causal-knowledge/{knowledge_id}")
def get_causal_knowledge(knowledge_id: str):
    return run(lambda: causal_knowledge.get(knowledge_id))


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


@app.post("/v1/sourcing/comparison-intake", status_code=201)
async def capture_supplier_comparison(
    product_id: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    offers_json: Annotated[str, Form()],
    profit_inputs_json: Annotated[str, Form()],
    offer_evidence_1: Annotated[UploadFile, File()],
    offer_evidence_2: Annotated[UploadFile, File()],
    offer_evidence_3: Annotated[UploadFile, File()],
    assumption_evidence: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    try:
        raw_offers = json.loads(offers_json)
        raw_inputs = json.loads(profit_inputs_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Offer and profit input payloads must be valid JSON") from exc
    if not isinstance(raw_offers, list) or len(raw_offers) != 3 or not isinstance(raw_inputs, dict):
        raise HTTPException(status_code=422, detail="Exactly three offers and one profit input object are required")
    offer_values = []
    for raw_offer in raw_offers:
        if not isinstance(raw_offer, dict):
            raise HTTPException(status_code=422, detail="Every supplier offer must be an object")
        validated = SupplierOfferInput(
            **raw_offer,
            product_id=product_id,
            evidence_ref="pending-capture",
        ).model_dump()
        validated.pop("product_id")
        validated.pop("evidence_ref")
        offer_values.append(validated)
    validated_inputs = ProfitScenarioInput(
        **raw_inputs,
        offer_id="pending-capture",
        evidence=["pending-capture"],
    ).model_dump()
    validated_inputs.pop("offer_id")
    validated_inputs.pop("evidence")
    uploads = [offer_evidence_1, offer_evidence_2, offer_evidence_3]
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    payloads = []
    for values, upload in zip(offer_values, uploads, strict=True):
        content = await upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="Supplier offer evidence exceeds size limit")
        payloads.append(
            OfferEvidencePayload(
                offer_data=values,
                content=content,
                filename=upload.filename or "supplier-offer.bin",
                content_type=upload.content_type or "application/octet-stream",
            )
        )
    assumption_content = await assumption_evidence.read(max_bytes + 1)
    if len(assumption_content) > max_bytes:
        raise HTTPException(status_code=413, detail="Profit assumption evidence exceeds size limit")
    return run(
        lambda: sourcing_intake.ingest(
            product_id=product_id,
            effective_at=effective_at,
            offers=payloads,
            profit_inputs=ProfitInputs(**validated_inputs),
            assumption_content=assumption_content,
            assumption_filename=assumption_evidence.filename or "profit-assumptions.bin",
            assumption_content_type=assumption_evidence.content_type or "application/octet-stream",
            created_by=principal.actor_id,
        )
    )


@app.get("/v1/sourcing/comparisons/{product_id}")
def compare_supplier_offers(product_id: str):
    return run(lambda: sourcing.compare_product_offers(product_id))


@app.post("/v1/sourcing/procurement-candidates", status_code=201)
def request_procurement_candidate(
    body: ProcurementCandidateInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")

    def request():
        comparison = sourcing.compare_product_offers(body.product_id)
        if not comparison["ready_for_procurement_review"]:
            raise ValueError("Three evidence-backed supplier offers and CM3 scenarios are required")
        selected = next(
            (
                item
                for item in comparison["rows"]
                if item["offer"].id == body.offer_id
                and item["scenario"] is not None
                and item["scenario"].id == body.scenario_id
            ),
            None,
        )
        if selected is None:
            raise ValueError("Selected offer and scenario are not part of this product comparison")
        if selected["scenario"].cm3_cny <= 0:
            raise ValueError("Procurement candidate requires positive expected CM3")
        if body.quantity < selected["offer"].min_order_quantity:
            raise ValueError("Procurement quantity is below supplier MOQ")
        if not commerce.product_readiness(body.product_id)["ready_for_validation"]:
            raise ValueError("All three Passports must be approved before procurement review")
        payload = {
            **body.model_dump(),
            "supplier_ref": selected["offer"].supplier_ref,
            "expected_cm3_cny": str(selected["scenario"].cm3_cny),
            "expected_cm3_rate": str(selected["scenario"].cm3_rate),
            "comparison_offer_ids": [item["offer"].id for item in comparison["rows"]],
            "evidence": selected["scenario"].evidence,
        }
        return commerce.request_approval(
            action="procurement.place_order",
            resource_type="profit_scenario",
            resource_id=body.scenario_id,
            requested_by=principal.actor_id,
            payload=payload,
        )

    return run(request)


@app.post("/v1/procurement/sample-orders", status_code=201)
def create_sample_purchase_order(
    body: SampleOrderInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: procurement.create_sample_order(body.approval_id, created_by=principal.actor_id))


@app.get("/v1/procurement/sample-orders")
def list_sample_purchase_orders(limit: int = 100):
    return run(lambda: procurement.list_orders(limit))


@app.get("/v1/procurement/sample-orders/{order_id}")
def get_sample_purchase_order(order_id: str):
    return run(lambda: procurement.get_order(order_id))


@app.post("/v1/procurement/sample-orders/{order_id}/events", status_code=201)
async def record_sample_procurement_event(
    order_id: str,
    event_type: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    facts_json: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    try:
        event_facts = json.loads(facts_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="facts_json must be valid JSON") from exc
    if not isinstance(event_facts, dict):
        raise HTTPException(status_code=422, detail="facts_json must be a JSON object")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Event evidence exceeds {max_bytes} bytes")
    digest = hashlib.sha256(content).hexdigest()
    def capture_and_record():
        record = evidence.capture(
            content=content,
            filename=file.filename or f"{event_type}-evidence.bin",
            content_type=file.content_type or "application/octet-stream",
            source="sample_procurement",
            source_ref=f"sample-procurement://{order_id}/{event_type}/sha256/{digest}",
            grade=EvidenceGrade.A,
            effective_at=effective_at,
            effective_until=None,
            created_by=principal.actor_id,
            metadata={"sample_order_id": order_id, "event_type": event_type},
        )
        return procurement.record_event(
            order_id,
            event_type=event_type,
            effective_at=effective_at,
            evidence_id=record.id,
            facts=event_facts,
            created_by=principal.actor_id,
        )

    return run(capture_and_record)


@app.get("/v1/procurement/suppliers/performance")
def supplier_performance():
    return run(procurement.supplier_performance)


@app.get("/v1/procurement/sample-orders/{order_id}/backup-options")
def sample_order_backup_options(order_id: str):
    return run(lambda: procurement.backup_options(order_id))


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


@app.get("/v1/approvals")
def list_approvals(principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "approver", "admin")
    return run(repo.list_approvals)


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
