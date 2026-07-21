from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .automation import AutomationService, RiskLevel
from .candidate_evidence_review import CandidateEvidenceAuthorityService
from .capability_economics import CapabilityEconomicsService
from .causal_experiments import CausalExperimentService, ExperimentEvent
from .causal_knowledge import (
    CausalKnowledgeService,
    ExperimentReviewVerdict,
)
from .causal_policies import (
    CausalPolicyService,
    PolicyReviewVerdict,
    StageOutcomeVerdict,
)
from .content_growth import ContentGrowthService
from .correlation import correlation_id
from .cost_evidence_review import (
    ACTUAL_COST_AUTHORITIES,
    ACTUAL_COST_AUTHORITY_LABELS,
    CostEvidenceAuthorityService,
)
from .database import create_database_engine, database_health
from .decision_contracts import DecisionContractService
from .decision_contracts import RiskLevel as DecisionRiskLevel
from .decision_lifecycle import (
    DecisionDisposition,
    DecisionLifecycleService,
    ReviewVerdict,
)
from .demand_report_gate import DemandReportGateService
from .domain import AgentMode, ChargeType, ContentType, PassportType
from .evidence import EvidenceGrade, EvidenceService
from .evidence_integrity import EvidenceIntegrityMonitorService
from .execution_plans import ExecutionPlanService
from .facts import FactPromotionService
from .finance import CashPlanStatus, FeeSignRule, FinanceEntryKind, FinanceService
from .governance import GovernanceService
from .image_execution import ComfyImageExecutionService
from .imports import MAX_IMPORT_BYTES, OzonImportService
from .incident_recovery import IncidentRecoveryService
from .intake import PassportEvidencePayload, ProductMediaEvidenceService, SkuEpisodeIntakeService
from .intelligence import MarketIntelligenceService
from .limited_executor import LimitedExecutorService
from .loop_engineering import LoopEngineeringService
from .operations_queue import OperationsQueueService
from .outbox import OutboxService
from .ozon_contracts import contract_catalog
from .ozon_finance_review import (
    AccrualAccountingClass,
    AccrualExpectedSign,
    OzonAccrualClassificationService,
    OzonFeeMappingApprovalService,
    OzonFinanceReportReviewService,
)
from .pilot_readiness import PilotReadinessService
from .pilot_runs import PilotRunService
from .policy_shadow import PolicyShadowService
from .post_execution import PostExecutionService
from .procurement import ProcurementService
from .providers import ComfyUIProvider, FirecrawlProvider, N8nProvider, OllamaProvider
from .read_only_claims import ReadOnlyClaimService
from .readiness import GateReadinessService
from .repository import InMemoryRepository
from .research_inbox import ResearchInboxService
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
from .sourcing import (
    PROFIT_TEMPLATE_FIELDS,
    PROFIT_TEMPLATE_ID,
    ProfitInputs,
    SourcePlatform,
    SourcingService,
    SupplierOffer,
    listing_approval_payload,
    profit_template_contract,
)
from .sourcing_intake import OfferEvidencePayload, SupplierComparisonIntakeService
from .sourcing_store import SqlSourcingStore
from .sql_repository import SqlAlchemyRepository

APP_VERSION = "0.47.0"
API_SCHEMA_VERSION = "v1"
app = FastAPI(title="KJDS Control Plane", version=APP_VERSION)


def build_repository():
    if os.getenv("KJDS_REPOSITORY", "postgres").lower() == "memory":
        return InMemoryRepository()
    return SqlAlchemyRepository()


repo = build_repository()
engine = getattr(repo, "engine", None) or create_database_engine()
evidence = EvidenceService(engine)
research_inbox = ResearchInboxService(evidence=evidence)
demand_reports = DemandReportGateService(evidence=evidence)
outbox = OutboxService(engine)
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
causal_policies = CausalPolicyService(
    engine=engine,
    knowledge=causal_knowledge,
    evidence=evidence,
)
commerce = CommerceService(repo, evidence_validator=evidence.require_valid)
policy_shadow = PolicyShadowService(
    engine=engine,
    policies=causal_policies,
    evidence=evidence,
    commerce=commerce,
)


def execution_readiness_context(
    _action: str, _target: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    demand = demand_reports.status()["readiness"]["real_execution"]
    return {
        "demand.real_execution": {
            "ready": demand["ready"],
            "evidence_ids": demand["evidence_ids"],
            "blocking_reasons": demand["blocking_reasons"],
        }
    }


execution_plans = ExecutionPlanService(
    engine=engine,
    policy_shadow=policy_shadow,
    policies=causal_policies,
    evidence=evidence,
    commerce=commerce,
    readiness_provider=execution_readiness_context,
)
intake = SkuEpisodeIntakeService(commerce=commerce, evidence=evidence)
product_media = ProductMediaEvidenceService(commerce=commerce, evidence=evidence)
candidate_evidence_authority = CandidateEvidenceAuthorityService(
    evidence=evidence,
    allowed_metrics=set(MarketIntelligenceService.CANDIDATE_METRICS),
)
market = MarketIntelligenceService(
    repo,
    evidence_validator=evidence.require_valid,
    evidence_lookup=evidence.get,
    demand_report_validator=lambda evidence_id: demand_reports.require_accepted(
        evidence_id,
        scope="research",
    ),
    evidence_authority_lookup=candidate_evidence_authority.require_approved_grade,
)
content = ContentGrowthService(
    repo,
    evidence_validator=evidence.require_valid,
    evidence_lookup=evidence.get,
    image_readiness=product_media.readiness,
)
imports = OzonImportService(engine)
finance_report_reviews = OzonFinanceReportReviewService(engine=engine, evidence=evidence, imports=imports)
finance = FinanceService(engine)
ozon_fee_mappings = OzonFeeMappingApprovalService(
    engine=engine,
    evidence=evidence,
    imports=imports,
    reviews=finance_report_reviews,
    finance=finance,
)
ozon_accrual_classifications = OzonAccrualClassificationService(
    engine=engine,
    evidence=evidence,
    imports=imports,
    reviews=finance_report_reviews,
)
facts = FactPromotionService(
    engine,
    finance_review_validator=finance_report_reviews.require_accepted,
    fee_mapping_validator=ozon_fee_mappings.require_mapped,
    accrual_classification_validator=ozon_accrual_classifications.require_classified,
)
automation = AutomationService(engine, repo, shadow_mode=os.getenv("KJDS_SHADOW_MODE", "true").lower() != "false")
loop_engineering = LoopEngineeringService()
sourcing_store = SqlSourcingStore(engine)
cost_evidence_authority = CostEvidenceAuthorityService(evidence=evidence)
sourcing = SourcingService(
    sourcing_store,
    repo,
    evidence_validator=evidence.require_valid,
    actual_cost_validator=cost_evidence_authority.require_actual,
)
sourcing_intake = SupplierComparisonIntakeService(sourcing=sourcing, evidence=evidence)
procurement = ProcurementService(
    engine=engine,
    repository=repo,
    sourcing_store=sourcing_store,
    sourcing=sourcing,
    evidence=evidence,
)
governance = GovernanceService(engine=engine, evidence=evidence)
read_only_claims = ReadOnlyClaimService(engine=engine, evidence=evidence)
readiness = GateReadinessService(
    commerce=commerce,
    sourcing_store=sourcing_store,
    evidence=evidence,
    facts=facts,
    finance=finance,
    governance=governance,
    demand_reports=demand_reports,
    scenario_release_validator=sourcing.require_release_ready,
)
authenticator = ApiKeyAuthenticator.from_environment()
kill_switch = KillSwitchService(engine)
limited_executor = LimitedExecutorService(
    engine=engine,
    execution_plans=execution_plans,
    evidence=evidence,
    kill_switch=kill_switch,
    enabled=os.getenv("KJDS_LIMITED_EXECUTION_ENABLED", "false").lower() == "true",
)
post_execution = PostExecutionService(
    engine=engine,
    limited_executor=limited_executor,
    execution_plans=execution_plans,
    policies=causal_policies,
    evidence=evidence,
    kill_switch=kill_switch,
)
capability_economics = CapabilityEconomicsService(
    engine=engine,
    post_execution=post_execution,
    execution_plans=execution_plans,
    evidence=evidence,
)
incident_recovery = IncidentRecoveryService(
    engine=engine,
    evidence=evidence,
    kill_switch=kill_switch,
)
evidence_integrity = EvidenceIntegrityMonitorService(
    evidence=evidence,
    incidents=incident_recovery,
)
operations_queue = OperationsQueueService(
    engine=engine,
    incidents=incident_recovery,
    limited_executor=limited_executor,
    post_execution=post_execution,
)
pilot_readiness = PilotReadinessService(
    engine=engine,
    evidence=evidence,
    incidents=incident_recovery,
    kill_switch=kill_switch,
)
pilot_runs = PilotRunService(
    engine=engine,
    pilots=pilot_readiness,
    evidence=evidence,
    lease_seconds=int(os.getenv("KJDS_PILOT_RUN_LEASE_SECONDS", "900")),
)
providers = {
    "ollama": OllamaProvider(os.getenv("KJDS_OLLAMA_URL", "http://127.0.0.1:11434")),
    "comfyui": ComfyUIProvider(os.getenv("KJDS_COMFYUI_URL", "http://127.0.0.1:8189")),
    "n8n": N8nProvider(os.getenv("KJDS_N8N_URL", "http://127.0.0.1:5678")),
    "firecrawl": FirecrawlProvider(
        os.getenv("FIRECRAWL_API_URL", "http://127.0.0.1:3002"),
        os.getenv("FIRECRAWL_API_KEY") or None,
    ),
}
image_execution = ComfyImageExecutionService(
    repository=repo,
    content=content,
    evidence=evidence,
    provider=providers["comfyui"],
)

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
KILL_SWITCH_CONTROL_PATHS = {
    "/v1/system/kill-switch/engage",
    "/v1/system/kill-switch/release",
    "/v1/loop-engineering/validate",
    "/v1/evidence/integrity-scan",
}


def is_write_safety_control_path(path: str) -> bool:
    return (
        path in KILL_SWITCH_CONTROL_PATHS
        or path.startswith("/v1/operational-incidents")
        or path.startswith("/v1/operations-control")
    )


def request_id_for(request: Request) -> str:
    """Return a bounded correlation id without trusting arbitrary header text."""
    return correlation_id(request.headers.get("X-Request-ID"), "req")


def trace_id_for(request: Request) -> str:
    return correlation_id(request.headers.get("X-Trace-ID"), "trace")


ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "PERMISSION_DENIED",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_FAILED",
    423: "WRITES_LOCKED",
    429: "RATE_LIMITED",
    503: "SERVICE_UNAVAILABLE",
}


def contract_error(
    *,
    status_code: int,
    detail: Any,
    request_id: str,
    trace_id: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    encoded_detail = jsonable_encoder(detail)
    error = {
        "code": ERROR_CODES.get(status_code, "INTERNAL_ERROR" if status_code >= 500 else "REQUEST_FAILED"),
        "message": detail if isinstance(detail, str) else "Request validation failed",
    }
    if not isinstance(detail, str):
        error["details"] = encoded_detail
    response = JSONResponse(
        status_code=status_code,
        content={
            "detail": encoded_detail,
            "error": error,
            "request_id": request_id,
            **({"trace_id": trace_id} if trace_id else {}),
            "schema_version": API_SCHEMA_VERSION,
        },
        headers=headers,
    )
    response.headers["X-Request-ID"] = request_id
    if trace_id:
        response.headers["X-Trace-ID"] = trace_id
    response.headers["X-KJDS-Schema-Version"] = API_SCHEMA_VERSION
    return response


@app.exception_handler(HTTPException)
async def contract_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return contract_error(
        status_code=exc.status_code,
        detail=exc.detail,
        request_id=getattr(request.state, "request_id", request_id_for(request)),
        trace_id=getattr(request.state, "trace_id", trace_id_for(request)),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def contract_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return contract_error(
        status_code=422,
        detail=exc.errors(),
        request_id=getattr(request.state, "request_id", request_id_for(request)),
        trace_id=getattr(request.state, "trace_id", trace_id_for(request)),
    )


@app.middleware("http")
async def enforce_control_plane_security(request: Request, call_next):
    request.state.request_id = request_id_for(request)
    request.state.trace_id = trace_id_for(request)
    if request.url.path.startswith("/v1/"):
        try:
            request.state.principal = authenticator.authenticate(request.headers.get("X-KJDS-API-Key"))
        except AuthenticationFailure as exc:
            return contract_error(
                status_code=exc.status_code,
                detail=str(exc),
                request_id=request.state.request_id,
                trace_id=request.state.trace_id,
            )

        if request.method in WRITE_METHODS and not is_write_safety_control_path(request.url.path):
            if not request.state.principal.has_any_role(
                "operator",
                "reviewer",
                "compliance",
                "approver",
                "risk",
                "executor",
                "monitor",
                "pilot_reader",
                "admin",
            ):
                return contract_error(
                    status_code=403,
                    detail="Authenticated actor has no write role",
                    request_id=request.state.request_id,
                    trace_id=request.state.trace_id,
                )
            try:
                kill_switch.ensure_writes_allowed()
            except WritesDisabled as exc:
                return contract_error(
                    status_code=423,
                    detail=str(exc),
                    request_id=request.state.request_id,
                    trace_id=request.state.trace_id,
                )
            except Exception:
                return contract_error(
                    status_code=503,
                    detail="Write safety state is unavailable; writes fail closed",
                    request_id=request.state.request_id,
                    trace_id=request.state.trace_id,
                )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Trace-ID"] = request.state.trace_id
    response.headers["X-KJDS-Schema-Version"] = API_SCHEMA_VERSION
    return response


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


class CandidateResearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_ref: str = Field(min_length=1, max_length=120)
    candidate_name: str = Field(min_length=1, max_length=240)
    market: str = Field(min_length=2, max_length=20)
    category: str = Field(min_length=1, max_length=120)
    as_of: str
    demand_report_evidence_id: str = Field(min_length=1, max_length=120)
    max_age_days: int = Field(default=90, ge=1, le=365)


class CandidateMetricInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Literal[
        "demand_signal",
        "competition_gap",
        "supplier_available",
        "compliance_redline",
        "return_risk",
    ]
    value: Decimal
    confidence: Decimal = Field(default=Decimal("0.8"), ge=0, le=1)
    evidence_id: str = Field(min_length=1, max_length=120)
    window_days: int = Field(ge=1, le=90)
    sample_size: int = Field(ge=1)


class CandidateResearchSubmissionInput(CandidateResearchInput):
    observations: list[CandidateMetricInput] = Field(min_length=5, max_length=5)


class CandidateSourcingHandoffInput(CandidateResearchInput):
    sku: str = Field(min_length=1, max_length=80)
    confirmed: Literal[True]


class CandidateEvidenceAuthorityReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: Literal[
        "demand_signal",
        "competition_gap",
        "supplier_available",
        "compliance_redline",
        "return_risk",
    ]
    approved_grade: Literal[EvidenceGrade.A, EvidenceGrade.B]
    accepted: bool
    authentic_original: bool
    source_scope_matches: bool
    authority_basis_verified: bool
    rationale: str = Field(min_length=1, max_length=2000)


class CostEvidenceAuthorityReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_type: Literal[
        "product_cost",
        "domestic_logistics",
        "international_logistics",
        "packaging",
        "warehousing",
        "customs",
        "tax",
        "last_mile",
        "platform_fee",
        "advertising",
        "return",
        "fx",
        "capital_cost",
        "aftersales",
        "loss",
    ]
    authority_id: str = Field(min_length=1, max_length=120)
    accepted: bool
    authentic_original: bool
    cost_scope_matches: bool
    charging_party_matches: bool
    amount_currency_period_matches: bool
    rationale: str = Field(min_length=1, max_length=2000)


class ContentBriefInput(BaseModel):
    product_id: str
    content_type: ContentType
    locale: str = "ru-RU"
    channel: str = "OZON"
    brief: dict[str, Any]


class AssetAttachInput(BaseModel):
    artifact_ref: str


class ContentQACheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check: str = Field(min_length=1, max_length=80)
    passed: bool
    notes: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class AssetReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[ContentQACheckInput] = Field(min_length=1, max_length=8)


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
    model_config = ConfigDict(extra="forbid")

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
    warehousing_cny: Decimal = Decimal("0")
    tax_cny: Decimal = Decimal("0")
    fx_cost_cny: Decimal = Decimal("0")
    capital_cost_cny: Decimal = Decimal("0")
    aftersales_cny: Decimal = Decimal("0")
    loss_reserve_cny: Decimal = Decimal("0")
    other_cost_cny: Decimal = Decimal("0")
    evidence: list[str] = Field(min_length=1)
    cost_evidence: dict[str, str] = Field(default_factory=dict)
    template_id: str = PROFIT_TEMPLATE_ID
    cost_states: dict[str, Literal["estimate", "actual", "unknown"]] = Field(default_factory=dict)


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
    content_asset_ids: list[str] = Field(min_length=1, max_length=20)
    listing_data: dict[str, Any]


class KillSwitchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class LoopValidationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module: Literal[
        "automations",
        "skills",
        "integrations",
        "subagents",
        "worktrees",
        "memory",
    ]
    mode: Literal["proposal", "shadow", "active"]
    controls: dict[str, Any]


class LineageLinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: str = Field(min_length=1, max_length=100)
    target_id: str = Field(min_length=1, max_length=300)
    relationship: str = Field(min_length=1, max_length=100)


class DemandReportReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_evidence_id: str = Field(min_length=1, max_length=100)
    accepted: bool
    rationale: str = Field(min_length=1, max_length=2000)


class OzonFinanceReportReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    authentic_account_export: bool
    period_matches: bool
    not_public_sample: bool
    complete_export: bool
    rationale: str = Field(min_length=1, max_length=2000)


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


class BestSolutionHardConstraintResultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=200)
    constraint: str = Field(min_length=1, max_length=1000)
    passed: bool
    rationale: str = Field(min_length=1, max_length=5000)


class BestSolutionOptionAssessmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=200)
    evidence_quality: Literal["A", "B", "C", "D", "UNKNOWN"]
    expected_risk_adjusted_long_term_value: str = Field(min_length=1, max_length=5000)
    total_cost_of_ownership: str = Field(min_length=1, max_length=5000)
    maximum_loss: str = Field(min_length=1, max_length=5000)
    reversibility_and_rollback: str = Field(min_length=1, max_length=5000)
    time_to_value: str = Field(min_length=1, max_length=5000)
    operational_fit: str = Field(min_length=1, max_length=5000)


class BestSolutionRejectedOptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=5000)


class BestSolutionAssessmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hard_constraint_results: list[BestSolutionHardConstraintResultInput]
    option_assessments: list[BestSolutionOptionAssessmentInput]
    rejected_options: list[BestSolutionRejectedOptionInput]
    sensitivity_drivers: list[str] = Field(min_length=1)
    invalidation_conditions: list[str] = Field(min_length=1)
    review_at: str = Field(min_length=1)
    approval_requirement: str = Field(min_length=1, max_length=5000)
    no_action_option_id: str | None = None
    no_action_omission_reason: str | None = None


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
    selection_assessment: BestSolutionAssessmentInput | None = None
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


class CausalPolicyConditionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=200)
    operator: Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in"]
    value: Any


class CausalPolicyActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(pattern=r"^recommend_", max_length=200)
    parameters: dict[str, Any] = Field(default_factory=dict)


class CausalPolicyGuardrailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1, max_length=200)
    direction: Literal["min", "max"]
    threshold: Decimal


class CausalPolicyRolloutStageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    max_exposure_fraction: Decimal = Field(ge=0, le=1)
    minimum_observation_count: int = Field(ge=0)
    minimum_incremental_value: Decimal


class CausalPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    objective: str = Field(min_length=1, max_length=10000)
    knowledge_ids: list[str] = Field(min_length=1)
    applicability: dict[str, Any]
    conditions: list[CausalPolicyConditionInput] = Field(min_length=1)
    action: CausalPolicyActionInput
    guardrails: list[CausalPolicyGuardrailInput] = Field(min_length=1)
    fallback_action: CausalPolicyActionInput
    rollout_stages: list[CausalPolicyRolloutStageInput] = Field(min_length=2)
    evidence_ids: list[str] = Field(min_length=1)


class CausalPolicyReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: PolicyReviewVerdict
    rationale: str = Field(min_length=1, max_length=10000)
    counterarguments: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class CausalPolicyReleaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(min_length=1)
    stage_index: int = Field(ge=0)
    rationale: str = Field(min_length=1, max_length=10000)
    evidence_ids: list[str] = Field(min_length=1)


class CausalPolicyStageOutcomeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: StageOutcomeVerdict
    observation_count: int = Field(ge=0)
    incremental_value: Decimal
    guardrail_breached: bool
    notes: str = Field(min_length=1, max_length=10000)
    evidence_ids: list[str] = Field(min_length=1)


class CausalPolicyContextInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: dict[str, Any]


class PolicyShadowBaselineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["champion", "human"]
    actor_id: str = Field(min_length=1, max_length=300)
    result: dict[str, Any]
    evidence_ids: list[str] = Field(min_length=1)


class PolicyEvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=300)
    context: dict[str, Any]
    baseline: PolicyShadowBaselineInput | None = None
    observed_at: str
    evidence_ids: list[str] = Field(min_length=1)


class PolicyShadowBatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_key: str = Field(min_length=1, max_length=300)
    contexts: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    baselines: list[PolicyShadowBaselineInput] | None = None
    observed_at: str
    evidence_ids: list[str] = Field(min_length=1)


class PolicyActivationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class GovernedExecutionPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=300)
    adapter_id: str = Field(min_length=1, max_length=200)
    target: dict[str, Any]
    precondition_state_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    intended_patch: dict[str, Any]
    rollback_patch: dict[str, Any]
    evidence_ids: list[str] = Field(min_length=1)
    risk_limits: dict[str, Any] | None = None
    risk_values: dict[str, Any] | None = None
    risk_currency: str | None = Field(default=None, min_length=3, max_length=3)


class GovernedExecutionDryRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_state_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    evidence_ids: list[str] = Field(min_length=1)


class LimitedExecutionClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_state_hash: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    lease_seconds: int = Field(default=120, ge=30, le=600)


class LimitedExecutionReceiptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["succeeded", "failed", "uncertain"]
    remote_operation_id: str | None = Field(default=None, max_length=500)
    resulting_state_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    mutation_applied: bool
    error_code: str | None = Field(default=None, max_length=300)
    error_detail: str | None = Field(default=None, max_length=5000)
    evidence_ids: list[str] = Field(min_length=1)


class ExecutionObservationWindowInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_metric: str = Field(min_length=1, max_length=300)
    baseline: dict[str, Decimal]
    required_observations: int = Field(ge=1, le=10000)
    starts_at: str
    ends_at: str
    evidence_ids: list[str] = Field(min_length=1)


class ExecutionMetricObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: str = Field(min_length=1, max_length=300)
    value: Decimal
    observed_at: str
    evidence_ids: list[str] = Field(min_length=1)


class CapabilityEconomicAssessmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    realized_incremental_value: Decimal
    avoided_loss: Decimal = Field(ge=0)
    model_compute_cost: Decimal = Field(ge=0)
    human_review_cost: Decimal = Field(ge=0)
    incident_loss: Decimal = Field(ge=0)
    maintenance_cost: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    evidence_ids: list[str] = Field(min_length=1)
    as_of: str | None = None


class OperationalIncidentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=300)
    mode: Literal["live", "drill"]
    severity: Literal["critical", "high", "medium", "low"]
    trigger_type: str = Field(min_length=1, max_length=300)
    source_type: str | None = Field(default=None, max_length=300)
    source_id: str | None = Field(default=None, max_length=500)
    summary: str = Field(min_length=1, max_length=5000)
    impact: list[str] = Field(min_length=1, max_length=100)
    evidence_ids: list[str] = Field(min_length=1)


class IncidentRecoveryCheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check: Literal[
        "remote_state_reconciled",
        "rollback_confirmed_or_not_required",
        "data_reconciled",
        "credentials_rotated_or_not_required",
        "monitoring_restored",
    ]
    passed: bool
    notes: str = Field(min_length=1, max_length=5000)
    evidence_ids: list[str] = Field(min_length=1)


class IncidentRecoveryReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    rationale: str = Field(min_length=1, max_length=5000)
    evidence_ids: list[str] = Field(min_length=1)


class IncidentClosureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str = Field(min_length=1, max_length=5000)
    evidence_ids: list[str] = Field(min_length=1)


class OperationsQueueScanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: str | None = None


class ReadOnlyPilotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=300)
    platform: Literal["ozon"] = "ozon"
    account_alias: str = Field(min_length=1, max_length=300)
    allowed_operations: list[
        Literal[
            "ozon.product.read",
            "ozon.inventory.read",
            "ozon.orders.read",
            "ozon.analytics.read",
            "ozon.finance.read",
        ]
    ] = Field(min_length=1)
    max_daily_requests: int = Field(ge=1, le=10000)
    max_targets: int = Field(ge=1, le=1000)
    starts_at: str
    ends_at: str
    evidence_ids: list[str] = Field(min_length=1)


class PilotControlAttestationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control: Literal[
        "credentials_isolated",
        "least_privilege_scope",
        "monitoring_configured",
        "data_export_backup_verified",
    ]
    passed: bool
    notes: str = Field(min_length=1, max_length=5000)
    evidence_ids: list[str] = Field(min_length=1)


class PilotReviewSubmissionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: str | None = None


class PilotReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    rationale: str = Field(min_length=1, max_length=5000)


class PilotActivationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: str | None = None


class PilotRunStartInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=300)
    operation: Literal["ozon.product.read", "ozon.finance.read"]
    target_ref: str = Field(min_length=1, max_length=500)
    as_of: str | None = None


class PilotRunCompletionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["succeeded", "failed"]
    response_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    response_byte_size: int = Field(ge=0)
    record_count: int = Field(ge=0)
    summary: dict[str, Any]
    error_code: str | None = Field(default=None, max_length=120)


class PilotRunReapInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class ReadOnlyClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=300)
    claim_type: Literal[
        "product_identity",
        "product_attribute",
        "inventory_observation",
        "price_observation",
    ]
    payload: dict[str, Any]
    source_state_sha256: str = Field(min_length=64, max_length=64)
    effective_at: str


class ReadOnlyClaimReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
    rationale: str = Field(min_length=1, max_length=5000)


class GateReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=300)
    gate_id: Literal["G0", "G1", "G4"]
    owner_id: str = Field(min_length=1, max_length=120)
    approver_id: str = Field(min_length=1, max_length=120)
    participants: list[str] = Field(min_length=1, max_length=50)
    objective: str = Field(min_length=1, max_length=5000)
    exit_criteria: str = Field(min_length=1, max_length=5000)
    deliverables: list[str] = Field(min_length=1, max_length=100)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    unknowns: list[str] = Field(default_factory=list, max_length=100)
    blockers: list[str] = Field(default_factory=list, max_length=100)
    risk_budget: dict[str, Any]
    max_loss: dict[str, Any]
    rollback_plan: str = Field(min_length=1, max_length=5000)


class GateReviewSubmitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_ids: list[str] = Field(min_length=1, max_length=100)


class GateReviewDecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["PASS", "CONDITIONAL", "FAIL", "STOP"]
    rationale: str = Field(min_length=1, max_length=5000)
    conditions: list[str] = Field(default_factory=list, max_length=100)


class FeeMappingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=80)
    raw_code: str = Field(min_length=1, max_length=300)
    canonical_type: ChargeType
    sign_rule: FeeSignRule
    effective_from: str
    effective_until: str | None = None
    evidence_id: str = Field(min_length=1)


class OzonFeeMappingApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_code: str = Field(min_length=1, max_length=300)
    canonical_type: ChargeType
    sign_rule: FeeSignRule
    effective_from: str
    effective_until: str | None = None
    rationale: str = Field(min_length=1, max_length=2000)


class OzonAccrualClassificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accrual_group: str = Field(min_length=1, max_length=300)
    accrual_type: str = Field(min_length=1, max_length=500)
    accounting_class: AccrualAccountingClass
    expected_sign: AccrualExpectedSign
    effective_from: str
    effective_until: str | None = None
    rationale: str = Field(min_length=1, max_length=2000)


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
        "schema_version": API_SCHEMA_VERSION,
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
def integration_health(
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    ensure_role(principal, "operator", "monitor", "reviewer", "admin")
    return {name: asdict(provider.healthcheck()) for name, provider in providers.items()}


@app.get("/v1/loop-engineering/registry")
def loop_engineering_registry(
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
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
    return loop_engineering.registry_snapshot()


@app.post("/v1/loop-engineering/validate")
def validate_loop_engineering(
    body: LoopValidationInput,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict:
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "admin",
    )
    return run(
        lambda: loop_engineering.validate(
            module=body.module,
            mode=body.mode,
            controls=body.controls,
        ).to_dict()
    )


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
    if source.strip().lower() in {
        "candidate_evidence_authority_review",
        "gate_requirement_review",
        "ozon_finance_report_review",
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


@app.post("/v1/evidence/integrity-scan")
def scan_evidence_integrity(
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 500,
    offset: int = 0,
    as_of: str | None = None,
):
    ensure_role(principal, "monitor", "risk", "admin")
    return run(
        lambda: evidence_integrity.scan(
            actor_id=principal.actor_id,
            limit=limit,
            offset=offset,
            as_of=as_of,
        )
    )


@app.get("/v1/evidence/{evidence_id}")
def get_evidence(evidence_id: str):
    return run(lambda: evidence.get(evidence_id))


@app.get("/v1/evidence/{evidence_id}/verify")
def verify_evidence(evidence_id: str):
    return run(lambda: evidence.verify(evidence_id))


@app.get("/v1/evidence/{evidence_id}/retention")
def evidence_retention(evidence_id: str):
    return run(lambda: evidence.retention(evidence_id))


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
    if body.target_type.strip().lower() == "gate_requirement" or (
        body.target_type.strip().lower() == "evidence"
        and body.relationship.strip().lower() in {"candidate_authority_review", "reviews"}
    ) or (
        body.target_type.strip().lower() == ResearchInboxService.TARGET_TYPE
        and body.relationship.strip().lower() == ResearchInboxService.RELATIONSHIP
    ):
        raise HTTPException(status_code=422, detail="Reserved lineage requires its dedicated workflow")
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


@app.post("/v1/causal-policies", status_code=201)
def propose_causal_policy(
    body: CausalPolicyInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: causal_policies.propose(
            **body.model_dump(),
            proposed_by=principal.actor_id,
        )
    )


@app.get("/v1/causal-policies")
def list_causal_policies():
    return causal_policies.list()


@app.get("/v1/causal-policies/{policy_id}")
def get_causal_policy(policy_id: str):
    return run(lambda: causal_policies.get(policy_id))


@app.post("/v1/causal-policies/{policy_id}/reviews", status_code=201)
def review_causal_policy(
    policy_id: str,
    body: CausalPolicyReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: causal_policies.review(
            policy_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
    )


@app.post("/v1/causal-policies/{policy_id}/releases", status_code=201)
def release_causal_policy_stage(
    policy_id: str,
    body: CausalPolicyReleaseInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: causal_policies.release_stage(
            policy_id,
            **body.model_dump(),
            approved_by=principal.actor_id,
        )
    )


@app.post("/v1/causal-policy-releases/{release_id}/outcome", status_code=201)
def record_causal_policy_stage_outcome(
    release_id: str,
    body: CausalPolicyStageOutcomeInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: policy_shadow.record_stage_outcome(
            release_id,
            **body.model_dump(),
            recorded_by=principal.actor_id,
        )
    )


@app.post("/v1/causal-policies/{policy_id}/evaluation")
def evaluate_causal_policy_context(
    policy_id: str,
    body: CausalPolicyContextInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "approver", "admin")
    return run(lambda: causal_policies.evaluate_context(policy_id, body.context))


@app.post("/v1/causal-policy-releases/{release_id}/evaluations", status_code=201)
def record_causal_policy_evaluation(
    release_id: str,
    body: PolicyEvaluationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: policy_shadow.record_evaluation(
            release_id,
            **body.model_dump(),
            evaluated_by=principal.actor_id,
        )
    )


@app.post("/v1/causal-policy-releases/{release_id}/shadow-batches", status_code=201)
def run_causal_policy_shadow_batch(
    release_id: str,
    body: PolicyShadowBatchInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: policy_shadow.run_shadow_batch(
            release_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
    )


@app.get("/v1/causal-policy-evaluations")
def list_causal_policy_evaluations(policy_id: str | None = None):
    return run(lambda: policy_shadow.list_evaluations(policy_id))


@app.get("/v1/causal-policy-shadow-batches")
def list_causal_policy_shadow_batches(policy_id: str | None = None):
    return run(lambda: policy_shadow.list_batches(policy_id))


@app.post(
    "/v1/causal-policy-releases/{release_id}/activation-handoff",
    status_code=201,
)
def request_causal_policy_activation(
    release_id: str,
    body: PolicyActivationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: policy_shadow.request_activation(
            release_id,
            **body.model_dump(),
            requested_by=principal.actor_id,
        )
    )


@app.get("/v1/causal-policy-activation-handoffs")
def list_causal_policy_activation_handoffs():
    return run(policy_shadow.list_handoffs)


@app.get("/v1/causal-policy-activation-handoffs/{handoff_id}")
def get_causal_policy_activation_handoff(handoff_id: str):
    return run(lambda: policy_shadow.get_handoff(handoff_id))


@app.get("/v1/governed-execution-adapters")
def list_governed_execution_adapters():
    return execution_plans.adapters()


@app.post(
    "/v1/causal-policy-activation-handoffs/{handoff_id}/execution-plans",
    status_code=201,
)
def create_governed_execution_plan(
    handoff_id: str,
    body: GovernedExecutionPlanInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: execution_plans.create(
            handoff_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
    )


@app.get("/v1/governed-execution-plans")
def list_governed_execution_plans():
    return run(execution_plans.list)


@app.get("/v1/governed-execution-plans/{plan_id}")
def get_governed_execution_plan(plan_id: str):
    return run(lambda: execution_plans.get(plan_id))


@app.post("/v1/governed-execution-plans/{plan_id}/dry-run", status_code=201)
def dry_run_governed_execution_plan(
    plan_id: str,
    body: GovernedExecutionDryRunInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: execution_plans.dry_run(
            plan_id,
            **body.model_dump(),
            performed_by=principal.actor_id,
        )
    )


@app.post("/v1/governed-execution-plans/{plan_id}/commands", status_code=201)
def queue_limited_execution_command(
    plan_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: limited_executor.queue(plan_id, queued_by=principal.actor_id))


@app.get("/v1/limited-execution-commands")
def list_limited_execution_commands():
    return run(limited_executor.list)


@app.get("/v1/limited-execution-commands/{command_id}")
def get_limited_execution_command(command_id: str):
    return run(lambda: limited_executor.get(command_id))


@app.post("/v1/limited-execution-commands/{command_id}/claim")
def claim_limited_execution_command(
    command_id: str,
    body: LimitedExecutionClaimInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "executor", "admin")
    return run(
        lambda: limited_executor.claim(
            command_id,
            **body.model_dump(),
            worker_id=principal.actor_id,
        )
    )


@app.post("/v1/limited-execution-commands/{command_id}/receipt", status_code=201)
def record_limited_execution_receipt(
    command_id: str,
    body: LimitedExecutionReceiptInput,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "executor", "admin")
    return run(
        lambda: limited_executor.record_receipt(
            command_id,
            **body.model_dump(),
            recorded_by=principal.actor_id,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        )
    )


@app.post("/v1/limited-execution-commands/{command_id}/rollback", status_code=201)
def request_limited_execution_rollback(
    command_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "risk", "admin")
    return run(
        lambda: limited_executor.request_rollback(
            command_id,
            requested_by=principal.actor_id,
        )
    )


@app.post(
    "/v1/limited-execution-commands/{command_id}/observation-window",
    status_code=201,
)
def create_execution_observation_window(
    command_id: str,
    body: ExecutionObservationWindowInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: post_execution.create_window(
            command_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
    )


@app.get("/v1/execution-observation-windows")
def list_execution_observation_windows():
    return run(post_execution.list_windows)


@app.get("/v1/execution-observation-windows/{window_id}")
def get_execution_observation_window(window_id: str):
    return run(lambda: post_execution.get_window(window_id))


@app.post(
    "/v1/execution-observation-windows/{window_id}/observations",
    status_code=201,
)
def record_execution_metric_observation(
    window_id: str,
    body: ExecutionMetricObservationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "monitor", "operator", "admin")

    def record_and_open_incident():
        result = post_execution.observe(
            window_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
        if not result["guardrail_breached"]:
            return result
        window = post_execution.get_window(window_id)
        incident = incident_recovery.open(
            idempotency_key=f"post-execution-guardrail:{result['id']}",
            mode="live",
            severity="critical",
            trigger_type="post_execution_guardrail_breached",
            source_type="execution_metric_observation",
            source_id=result["id"],
            summary=f"Post-execution guardrail breached: {result['metric']}",
            impact=[
                f"observation_window:{window_id}",
                f"execution_command:{window['command_id']}",
                f"execution_plan:{window['plan_id']}",
            ],
            evidence_ids=body.evidence_ids,
            opened_by="post-execution-guardrail",
        )
        return {**result, "incident_id": incident["id"]}

    return run(record_and_open_incident)


@app.get("/v1/execution-observation-windows/{window_id}/evaluation")
def evaluate_execution_observation_window(window_id: str, as_of: str | None = None):
    return run(lambda: post_execution.evaluate(window_id, as_of=as_of))


@app.post(
    "/v1/execution-observation-windows/{window_id}/capability-economics",
    status_code=201,
)
def assess_execution_capability_economics(
    window_id: str,
    body: CapabilityEconomicAssessmentInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "risk", "admin")
    return run(
        lambda: capability_economics.assess(
            window_id,
            **body.model_dump(),
            assessed_by=principal.actor_id,
        )
    )


@app.get("/v1/capability-economic-assessments")
def list_capability_economic_assessments():
    return run(capability_economics.list)


@app.get("/v1/capability-economic-summaries")
def list_capability_economic_summaries():
    return run(capability_economics.summaries)


@app.post("/v1/operational-incidents", status_code=201)
def open_operational_incident(
    body: OperationalIncidentInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "risk", "admin")
    return run(
        lambda: incident_recovery.open(
            **body.model_dump(),
            opened_by=principal.actor_id,
        )
    )


@app.get("/v1/operational-incidents")
def list_operational_incidents():
    return run(incident_recovery.list)


@app.get("/v1/operational-incidents/{incident_id}")
def get_operational_incident(incident_id: str):
    return run(lambda: incident_recovery.get(incident_id))


@app.post("/v1/operational-incidents/{incident_id}/claim")
def claim_operational_incident(
    incident_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "risk", "admin")
    return run(lambda: incident_recovery.claim(incident_id, actor_id=principal.actor_id))


@app.post("/v1/operational-incidents/{incident_id}/checks", status_code=201)
def record_operational_incident_check(
    incident_id: str,
    body: IncidentRecoveryCheckInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "risk", "admin")
    return run(
        lambda: incident_recovery.record_check(
            incident_id,
            **body.model_dump(),
            actor_id=principal.actor_id,
        )
    )


@app.post("/v1/operational-incidents/{incident_id}/review-request")
def request_operational_incident_review(
    incident_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "risk", "admin")
    return run(lambda: incident_recovery.submit_review(incident_id, actor_id=principal.actor_id))


@app.post("/v1/operational-incidents/{incident_id}/review", status_code=201)
def review_operational_incident(
    incident_id: str,
    body: IncidentRecoveryReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "risk", "admin")
    return run(
        lambda: incident_recovery.review(
            incident_id,
            **body.model_dump(),
            actor_id=principal.actor_id,
        )
    )


@app.post("/v1/operational-incidents/{incident_id}/close")
def close_operational_incident(
    incident_id: str,
    body: IncidentClosureInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "admin")
    return run(
        lambda: incident_recovery.close(
            incident_id,
            **body.model_dump(),
            actor_id=principal.actor_id,
        )
    )


@app.get("/v1/operations-control/queue")
def list_operations_control_queue(as_of: str | None = None):
    return run(lambda: operations_queue.queue(as_of=as_of))


@app.post("/v1/operations-control/escalation-scan")
def scan_operations_control_escalations(
    body: OperationsQueueScanInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "monitor", "risk", "admin")
    return run(
        lambda: operations_queue.scan(
            as_of=body.as_of,
            actor_id=principal.actor_id,
        )
    )


@app.get("/v1/operations-control/escalations")
def list_operations_control_escalations():
    return run(operations_queue.escalations)


@app.post("/v1/read-only-pilots", status_code=201)
def create_read_only_pilot(
    body: ReadOnlyPilotInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: pilot_readiness.create(
            **body.model_dump(),
            requested_by=principal.actor_id,
        )
    )


@app.get("/v1/read-only-pilots")
def list_read_only_pilots():
    return run(pilot_readiness.list)


@app.get("/v1/read-only-pilots/{pilot_id}")
def get_read_only_pilot(pilot_id: str):
    return run(lambda: pilot_readiness.get(pilot_id))


@app.get("/v1/read-only-pilots/{pilot_id}/evaluation")
def evaluate_read_only_pilot(pilot_id: str, as_of: str | None = None):
    return run(lambda: pilot_readiness.evaluate(pilot_id, as_of=as_of))


@app.post("/v1/read-only-pilots/{pilot_id}/attestations", status_code=201)
def attest_read_only_pilot_control(
    pilot_id: str,
    body: PilotControlAttestationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "compliance", "admin")
    return run(
        lambda: pilot_readiness.attest(
            pilot_id,
            **body.model_dump(),
            attested_by=principal.actor_id,
        )
    )


@app.post("/v1/read-only-pilots/{pilot_id}/review-request")
def submit_read_only_pilot_review(
    pilot_id: str,
    body: PilotReviewSubmissionInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: pilot_readiness.submit_review(
            pilot_id,
            actor_id=principal.actor_id,
            as_of=body.as_of,
        )
    )


@app.post("/v1/read-only-pilots/{pilot_id}/review")
def review_read_only_pilot(
    pilot_id: str,
    body: PilotReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "admin")
    return run(
        lambda: pilot_readiness.review(
            pilot_id,
            **body.model_dump(),
            actor_id=principal.actor_id,
        )
    )


@app.post("/v1/read-only-pilots/{pilot_id}/activate")
def activate_read_only_pilot(
    pilot_id: str,
    body: PilotActivationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "admin")
    return run(
        lambda: pilot_readiness.activate(
            pilot_id,
            actor_id=principal.actor_id,
            as_of=body.as_of,
        )
    )


@app.post("/v1/read-only-pilots/{pilot_id}/runs", status_code=201)
def start_read_only_pilot_run(
    pilot_id: str,
    body: PilotRunStartInput,
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "pilot_reader", "admin")
    return run(
        lambda: pilot_runs.start(
            pilot_id,
            **body.model_dump(),
            worker_id=principal.actor_id,
            request_id=request.state.request_id,
            trace_id=request.state.trace_id,
        )
    )


@app.post("/v1/read-only-pilot-runs/{run_id}/complete")
def complete_read_only_pilot_run(
    run_id: str,
    body: PilotRunCompletionInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "pilot_reader", "admin")
    return run(
        lambda: pilot_runs.complete(
            run_id,
            **body.model_dump(),
            worker_id=principal.actor_id,
        )
    )


@app.post("/v1/read-only-pilot-runs/{run_id}/response-evidence", status_code=201)
async def capture_read_only_pilot_response(
    run_id: str,
    response_sha256: Annotated[str, Form(min_length=64, max_length=64)],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "pilot_reader", "admin")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Evidence file exceeds {max_bytes} bytes")
    return run(
        lambda: pilot_runs.capture_response(
            run_id,
            content=content_bytes,
            response_sha256=response_sha256,
            worker_id=principal.actor_id,
        )
    )


@app.post("/v1/read-only-pilot-runs/{run_id}/response-checkpoint", status_code=201)
async def checkpoint_read_only_pilot_response(
    run_id: str,
    response_sha256: Annotated[str, Form(min_length=64, max_length=64)],
    response_byte_size: Annotated[int, Form(ge=1)],
    record_count: Annotated[int, Form(ge=0)],
    summary_json: Annotated[str, Form(min_length=2, max_length=8192)],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "pilot_reader", "admin")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Evidence file exceeds {max_bytes} bytes")
    try:
        summary = json.loads(summary_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="summary_json must be valid JSON") from exc
    return run(
        lambda: pilot_runs.checkpoint_success(
            run_id,
            content=content_bytes,
            response_sha256=response_sha256,
            response_byte_size=response_byte_size,
            record_count=record_count,
            summary=summary,
            worker_id=principal.actor_id,
        )
    )


@app.post("/v1/read-only-pilot-runs/{run_id}/finalize")
def finalize_read_only_pilot_response(
    run_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "pilot_reader", "admin")
    return run(lambda: pilot_runs.finalize_captured(run_id, worker_id=principal.actor_id))


@app.get("/v1/read-only-pilot-runs")
def list_read_only_pilot_runs(
    pilot_id: str | None = None,
    principal: Annotated[Principal, Depends(current_principal)] = None,
):
    ensure_role(principal, "pilot_reader", "operator", "reviewer", "admin")
    return run(lambda: pilot_runs.list(pilot_id=pilot_id))


@app.get("/v1/read-only-pilot-runs/{run_id}")
def get_read_only_pilot_run(
    run_id: str,
    principal: Annotated[Principal, Depends(current_principal)] = None,
):
    ensure_role(principal, "pilot_reader", "operator", "reviewer", "admin")
    return run(lambda: pilot_runs.get(run_id))


@app.post("/v1/read-only-pilot-runs/{run_id}/claims", status_code=201)
def propose_read_only_claim(
    run_id: str,
    body: ReadOnlyClaimInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: read_only_claims.propose(
            run_id,
            **body.model_dump(),
            proposed_by=principal.actor_id,
        )
    )


@app.get("/v1/read-only-claims")
def list_read_only_claims(
    run_id: str | None = None,
    status: str | None = None,
    principal: Annotated[Principal, Depends(current_principal)] = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: read_only_claims.list(run_id=run_id, status=status))


@app.get("/v1/read-only-claims/{claim_id}")
def get_read_only_claim(
    claim_id: str,
    principal: Annotated[Principal, Depends(current_principal)] = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: read_only_claims.get(claim_id))


@app.post("/v1/read-only-claims/{claim_id}/review")
def review_read_only_claim(
    claim_id: str,
    body: ReadOnlyClaimReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: read_only_claims.review(
            claim_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
    )


@app.post("/v1/read-only-pilot-runs/reap")
def reap_read_only_pilot_runs(
    body: PilotRunReapInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "admin")
    return run(
        lambda: pilot_runs.reap_expired(
            as_of=body.as_of,
            limit=body.limit,
            actor_id=principal.actor_id,
        )
    )


@app.get("/v1/read-only-pilots/{pilot_id}/usage")
def get_read_only_pilot_usage(
    pilot_id: str,
    as_of: str | None = None,
    principal: Annotated[Principal, Depends(current_principal)] = None,
):
    ensure_role(principal, "pilot_reader", "operator", "reviewer", "admin")
    return run(lambda: pilot_runs.usage(pilot_id, as_of=as_of))


@app.post("/v1/models/discover")
def discover_models(principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: automation.sync_ollama_models(providers["ollama"]))


@app.get("/v1/models")
def list_models():
    return run(automation.list_models)


@app.post("/v1/recommendations", status_code=201)
def create_recommendation(
    body: RecommendationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
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


@app.post("/v1/governance/gate-reviews", status_code=201)
def create_gate_review(
    body: GateReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: governance.create(
            **body.model_dump(),
            actor_id=principal.actor_id,
        )
    )


@app.get("/v1/governance/gate-reviews")
def list_gate_reviews(gate_id: str | None = None):
    return run(lambda: governance.list(gate_id=gate_id))


@app.get("/v1/governance/gate-reviews/{review_id}")
def get_gate_review(review_id: str):
    return run(lambda: governance.get(review_id))


@app.post("/v1/governance/gate-reviews/{review_id}/submit")
def submit_gate_review(
    review_id: str,
    body: GateReviewSubmitInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: governance.submit(
            review_id,
            evidence_ids=body.evidence_ids,
            actor_id=principal.actor_id,
        )
    )


@app.post("/v1/governance/gate-reviews/{review_id}/decide")
def decide_gate_review(
    review_id: str,
    body: GateReviewDecisionInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "approver", "admin")
    return run(
        lambda: governance.decide(
            review_id,
            **body.model_dump(),
            actor_id=principal.actor_id,
        )
    )


@app.post("/v1/operations/gate-evidence", status_code=201)
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
        normalized_source_system not in demand_reports.supported_source_systems
        or report_window_days is None
        or report_window_days < 28
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "SKU-000 requires a supported demand evidence source_system "
                "and report_window_days >= 28"
            ),
        )
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Evidence file exceeds {max_bytes} bytes")
    digest = hashlib.sha256(content_bytes).hexdigest()

    def capture_and_link():
        if requirement_id == "SKU-000":
            result = demand_reports.capture_report(
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
            metadata={
                "requirement_id": requirement_id,
                "source_system": source_system,
                "report_window_days": report_window_days,
            },
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


@app.post("/v1/operations/demand-report-review", status_code=201)
def review_demand_report(
    body: DemandReportReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "approver", "admin")

    def review():
        result = demand_reports.review(**body.model_dump(), reviewed_by=principal.actor_id)
        return {
            "report": asdict(result["report"]),
            "review": asdict(result["review"]),
            "lineage": [asdict(item) for item in result.get("lineage", [])],
            "idempotent": result["idempotent"],
        }

    return run(review)


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
    validated_inputs.pop("cost_evidence")
    template_id = validated_inputs.pop("template_id")
    cost_states = validated_inputs.pop("cost_states")
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
            cost_states=cost_states,
            template_id=template_id,
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
        if not selected["scenario"].cost_complete:
            raise ValueError("Procurement candidate requires complete, classified cost evidence")
        sourcing.require_release_ready(selected["scenario"])
        if body.quantity < selected["offer"].min_order_quantity:
            raise ValueError("Procurement quantity is below supplier MOQ")
        if not commerce.product_readiness(body.product_id)["ready_for_validation"]:
            raise ValueError("All three Passports must be approved before procurement review")
        payload = {
            **body.model_dump(),
            "supplier_ref": selected["offer"].supplier_ref,
            "expected_cm3_cny": str(selected["scenario"].cm3_cny),
            "expected_cm3_rate": str(selected["scenario"].cm3_rate),
            "cost_breakdown_cny": selected["scenario"].cost_breakdown(),
            "cost_evidence": selected["scenario"].cost_evidence,
            "cost_states": selected["scenario"].cost_states,
            "profit_template_id": selected["scenario"].template_id,
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
    cost_evidence = values.pop("cost_evidence")
    template_id = values.pop("template_id")
    cost_states = values.pop("cost_states")

    def calculate():
        result = sourcing.calculate_profit(
            offer_id,
            ProfitInputs(**values),
            assumption_evidence,
            cost_evidence,
            cost_states,
            template_id,
        )
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


@app.get("/v1/sourcing/profit-template")
def get_sourcing_profit_template():
    return profit_template_contract()


@app.get("/v1/sourcing/profit-scenarios/{scenario_id}/explain")
def explain_sourcing_profit_scenario(scenario_id: str):
    return run(lambda: sourcing_store.get_scenario(scenario_id).explain())


@app.post("/v1/listings/ozon/drafts", status_code=201)
def create_ozon_listing_draft(
    body: OzonListingDraftInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")

    def create():
        draft = sourcing.create_ozon_listing_draft(**body.model_dump(), requested_by=principal.actor_id)
        scenario = sourcing_store.get_scenario(draft.scenario_id)
        approval = commerce.request_approval(
            action="listing.publish",
            resource_type="listing_draft",
            resource_id=draft.id,
            requested_by=principal.actor_id,
            payload=listing_approval_payload(draft, scenario),
        )
        draft.approval_id = approval.id
        sourcing_store.attach_listing_approval(draft)
        return {"draft": asdict(draft), "approval": asdict(approval)}

    return run(create)


@app.get("/v1/listings/ozon/drafts")
def list_ozon_listing_drafts(limit: int = 100):
    return run(lambda: sourcing_store.list_listing_drafts(min(max(limit, 1), 500)))


@app.post("/v1/products", status_code=201)
def create_product(
    body: ProductInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
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


@app.post("/v1/products/{product_id}/media-evidence", status_code=201)
async def capture_product_media(
    product_id: str,
    variant_id: Annotated[str, Form()],
    asset_role: Annotated[str, Form()],
    source_kind: Annotated[str, Form()],
    source_ref: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    image: Annotated[UploadFile, File()],
    rights_file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    image_content = await image.read(max_bytes + 1)
    rights_content = await rights_file.read(max_bytes + 1)
    if len(image_content) > max_bytes or len(rights_content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Product media file exceeds {max_bytes} bytes")
    return run(
        lambda: product_media.ingest(
            product_id=product_id,
            variant_id=variant_id,
            asset_role=asset_role,
            source_kind=source_kind,
            source_ref=source_ref,
            effective_at=effective_at,
            image_content=image_content,
            image_filename=image.filename or "product-image.bin",
            image_content_type=image.content_type or "application/octet-stream",
            rights_content=rights_content,
            rights_filename=rights_file.filename or "product-rights.bin",
            rights_content_type=rights_file.content_type or "application/octet-stream",
            created_by=principal.actor_id,
        )
    )


@app.get("/v1/products/{product_id}/media-readiness")
def product_media_readiness(product_id: str):
    return run(lambda: product_media.readiness(product_id))


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
    return {
        "report_period_start": period_start.isoformat(),
        "report_period_end": period_end.isoformat(),
    }


async def ozon_upload_bytes(file: UploadFile) -> bytes:
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail=f"Import file exceeds {MAX_IMPORT_BYTES} bytes")
    return content


@app.post("/v1/imports/ozon/preflight")
async def preflight_ozon_import(
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
    report_period_start: Annotated[str, Form()],
    report_period_end: Annotated[str, Form()],
):
    ensure_role(principal, "operator", "admin")
    content_bytes = await ozon_upload_bytes(file)
    report_period = validated_report_period(report_period_start, report_period_end)
    preview = run(
        lambda: imports.preview_file(filename=file.filename or "ozon-export", content=content_bytes)
    )
    return {**preview, **report_period}


@app.post("/v1/imports/ozon", status_code=201)
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
    preview = run(
        lambda: imports.preview_file(filename=file.filename or "ozon-export", content=content_bytes)
    )
    if not preview["ready"]:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Ozon import preflight failed; preserve the original file",
                "missing_columns": preview["missing_columns"],
            },
        )
    existing = imports.find_by_content(content_bytes)
    if existing is not None:
        if not existing.evidence_id:
            raise HTTPException(status_code=409, detail="Existing import has no immutable source evidence")
        try:
            existing_source = evidence.get(existing.evidence_id)
        except KeyError as exc:
            raise HTTPException(status_code=409, detail="Existing import source evidence is missing") from exc
        if any(existing_source.metadata.get(key) != value for key, value in report_period.items()):
            raise HTTPException(status_code=409, detail="Duplicate file conflicts with its immutable report period")
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
            metadata={
                "filename": filename,
                "sha256": digest,
                "retention_class": "financial",
                **report_period,
            },
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


@app.get("/v1/imports/{import_id}/finance-review")
def get_finance_report_review(import_id: str):
    return run(lambda: finance_report_reviews.status(import_id))


@app.post("/v1/imports/{import_id}/finance-review", status_code=201)
def review_finance_report(
    import_id: str,
    body: OzonFinanceReportReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
        result = finance_report_reviews.review(
            import_id=import_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
        return {
            "import": asdict(result["import"]),
            "report": asdict(result["report"]),
            "review": asdict(result["review"]),
            "lineage": [asdict(item) for item in result.get("lineage", [])],
            "idempotent": result["idempotent"],
        }

    return run(review)


@app.post("/v1/imports/{import_id}/promote", status_code=201)
def promote_import(
    import_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: facts.promote(import_id, created_by=principal.actor_id))


@app.get("/v1/imports/{import_id}/fee-codes")
def get_import_fee_codes(import_id: str):
    return run(lambda: ozon_fee_mappings.status(import_id))


@app.post("/v1/imports/{import_id}/fee-mappings", status_code=201)
def approve_import_fee_mapping(
    import_id: str,
    body: OzonFeeMappingApprovalInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def approve():
        result = ozon_fee_mappings.approve(
            import_id=import_id,
            **body.model_dump(),
            approved_by=principal.actor_id,
        )
        return {
            "mapping": asdict(result["mapping"]),
            "approval": asdict(result["approval"]),
            "lineage": [asdict(item) for item in result["lineage"]],
        }

    return run(approve)


@app.get("/v1/imports/{import_id}/accrual-classifications")
def get_import_accrual_classifications(import_id: str):
    return run(lambda: ozon_accrual_classifications.status(import_id))


@app.post("/v1/imports/{import_id}/accrual-classifications", status_code=201)
def approve_import_accrual_classification(
    import_id: str,
    body: OzonAccrualClassificationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def approve():
        result = ozon_accrual_classifications.approve(
            import_id=import_id,
            **body.model_dump(),
            approved_by=principal.actor_id,
        )
        return {
            "approval": asdict(result["approval"]),
            "lineage": [asdict(item) for item in result.get("lineage", [])],
            "idempotent": result["idempotent"],
        }

    return run(approve)


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
    if body.provider.strip().lower() == "ozon":
        raise HTTPException(status_code=422, detail="Use an accepted Ozon import fee-mapping workflow")
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
def ingest_observation(
    body: ObservationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(lambda: market.ingest(**body.model_dump()))


@app.post("/v1/market/opportunities", status_code=201)
def score_opportunity(
    body: OpportunityInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: market.score_opportunity(**body.model_dump()))


@app.post("/v1/market/research-signals", status_code=201)
async def capture_research_signal(
    file: Annotated[UploadFile, File()],
    provider: Annotated[str, Form()],
    provider_record_id: Annotated[str, Form()],
    source_url: Annotated[str, Form()],
    observed_at: Annotated[str, Form()],
    declared_grade: Annotated[EvidenceGrade, Form()],
    license_status: Annotated[str, Form()],
    principal: Annotated[Principal, Depends(current_principal)],
    raw_fields_json: Annotated[str, Form()] = "{}",
    candidate_refs_json: Annotated[str, Form()] = "[]",
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Research file exceeds {max_bytes} bytes")
    try:
        raw_fields = json.loads(raw_fields_json)
        candidate_refs = json.loads(candidate_refs_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Research JSON fields must be valid JSON") from exc
    if not isinstance(raw_fields, dict) or not isinstance(candidate_refs, list):
        raise HTTPException(status_code=422, detail="raw_fields_json must be an object and candidate_refs_json a list")
    return run(
        lambda: research_inbox.capture(
            content=content_bytes,
            filename=file.filename or "research-signal.bin",
            content_type=file.content_type or "application/octet-stream",
            provider=provider,
            provider_record_id=provider_record_id,
            source_url=source_url,
            observed_at=observed_at,
            declared_grade=declared_grade,
            license_status=license_status,
            raw_fields=raw_fields,
            candidate_refs=candidate_refs,
            created_by=principal.actor_id,
        )
    )


@app.get("/v1/market/research-signals")
def list_research_signals(
    principal: Annotated[Principal, Depends(current_principal)],
    candidate_ref: str | None = None,
    limit: int = 100,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: research_inbox.list(candidate_ref=candidate_ref, limit=limit))


@app.post("/v1/market/candidates/assess")
def assess_candidate_research(
    body: CandidateResearchInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(lambda: market.assess_candidate_research(**body.model_dump()))


@app.get("/v1/market/candidate-evidence/{evidence_id}/authority-review")
def candidate_evidence_authority_status(
    evidence_id: str,
    metric: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: candidate_evidence_authority.status(evidence_id, metric))


@app.get("/v1/finance/cost-evidence/{evidence_id}/authority-review")
def cost_evidence_authority_status(
    evidence_id: str,
    cost_type: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: cost_evidence_authority.status(evidence_id, cost_type))


@app.get("/v1/finance/cost-authorities")
def cost_authority_catalog(
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    labels = {key: label for key, label, *_ in PROFIT_TEMPLATE_FIELDS}
    return {
        "schema_version": "cost-actual-authority-v1",
        "items": [
            {
                "cost_type": cost_type,
                "label": labels[cost_type],
                "authorities": [
                    {
                        "id": authority_id,
                        "label": ACTUAL_COST_AUTHORITY_LABELS[authority_id],
                    }
                    for authority_id in sorted(authority_ids)
                ],
            }
            for cost_type, authority_ids in ACTUAL_COST_AUTHORITIES.items()
        ],
        "automatic_state_change": False,
        "automatic_finance_posting": False,
        "automatic_procurement": False,
        "automatic_listing": False,
    }


@app.post("/v1/finance/cost-evidence/{evidence_id}/authority-review", status_code=201)
def review_cost_evidence_authority(
    evidence_id: str,
    body: CostEvidenceAuthorityReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
        result = cost_evidence_authority.review(
            evidence_id=evidence_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
        return {
            "evidence": asdict(result["evidence"]),
            "review": asdict(result["review"]),
            "lineage": asdict(result["lineage"]) if result.get("lineage") else None,
            "idempotent": result["idempotent"],
        }

    return run(review)


@app.post("/v1/market/candidate-evidence/{evidence_id}/authority-review", status_code=201)
def review_candidate_evidence_authority(
    evidence_id: str,
    body: CandidateEvidenceAuthorityReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
        result = candidate_evidence_authority.review(
            evidence_id=evidence_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
        return {
            "evidence": asdict(result["evidence"]),
            "review": asdict(result["review"]),
            "lineage": asdict(result["lineage"]) if result.get("lineage") else None,
            "idempotent": result["idempotent"],
        }

    return run(review)


@app.post("/v1/market/candidates/intake", status_code=201)
def submit_candidate_research(
    body: CandidateResearchSubmissionInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: market.submit_candidate_research(
            **body.model_dump(exclude={"observations"}),
            observations=[item.model_dump() for item in body.observations],
        )
    )


@app.post("/v1/market/candidates/sourcing-handoff", status_code=201)
def handoff_candidate_to_sourcing(
    body: CandidateSourcingHandoffInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")

    def handoff():
        result = market.handoff_candidate_to_sourcing(
            **body.model_dump(),
            confirmed_by=principal.actor_id,
        )
        for evidence_id in result["evidence_ids"]:
            evidence.link(
                evidence_id=evidence_id,
                target_type="product",
                target_id=result["product"].id,
                relationship="candidate_basis",
                created_by=principal.actor_id,
            )
        evidence.link(
            evidence_id=result["demand_report_evidence_id"],
            target_type="product",
            target_id=result["product"].id,
            relationship="demand_report_basis",
            created_by=principal.actor_id,
        )
        return result

    return run(handoff)


@app.post("/v1/content/assets", status_code=201)
def create_content_asset(
    body: ContentBriefInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: content.create_content_brief(**body.model_dump()))


@app.get("/v1/products/{product_id}/content-assets")
def list_product_content_assets(
    product_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "monitor", "admin")
    return run(lambda: content.repo.content_assets_for_product(product_id))


@app.post("/v1/content/assets/{asset_id}/generation", status_code=202)
def queue_content_asset_generation(
    asset_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: image_execution.queue(asset_id, requested_by=principal.actor_id))


@app.post("/v1/content/assets/{asset_id}/generation/sync")
def sync_content_asset_generation(
    asset_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: image_execution.sync(asset_id, requested_by=principal.actor_id))


@app.post("/v1/content/assets/{asset_id}/generated")
def attach_content_asset(
    asset_id: str,
    body: AssetAttachInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: content.attach_generated_asset(asset_id, **body.model_dump()))


@app.post("/v1/content/assets/{asset_id}/review")
def review_content_asset(
    asset_id: str,
    body: AssetReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: content.review_asset(
            asset_id,
            checks=[item.model_dump() for item in body.checks],
            reviewed_by=principal.actor_id,
        )
    )


@app.post("/v1/experiments", status_code=201)
def create_experiment(
    body: ExperimentInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: content.create_experiment(**body.model_dump()))


@app.post("/v1/experiments/{experiment_id}/start")
def start_experiment(
    experiment_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: content.start_experiment(experiment_id))


@app.post("/v1/orders", status_code=201)
def create_order(
    body: OrderInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: commerce.create_order(**body.model_dump()))


@app.post("/v1/orders/{order_id}/charges", status_code=201)
def add_charge(
    order_id: str,
    body: ChargeInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
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

    def decide():
        approval = repo.get_approval(approval_id)
        if body.approved and approval.action == "listing.publish":
            sourcing.verify_listing_approval(
                draft_id=approval.resource_id,
                approval_id=approval.id,
                approval_payload=approval.payload,
            )
        return commerce.decide_approval(approval_id, **body.model_dump(), decided_by=principal.actor_id)

    return run(decide)


@app.post("/v1/agent-tasks", status_code=201)
def submit_agent_task(body: AgentTaskInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: commerce.submit_agent_task(**body.model_dump(), requested_by=principal.actor_id))


@app.get("/v1/events")
def events(after: int = 0):
    return repo.events_after(after)


@app.get("/v1/outbox/status")
def outbox_status(principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "monitor", "reviewer", "admin")
    return outbox.status()
