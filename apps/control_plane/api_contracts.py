from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .automation import RiskLevel
from .causal_experiments import ExperimentEvent
from .causal_knowledge import ExperimentReviewVerdict
from .causal_policies import PolicyReviewVerdict, StageOutcomeVerdict
from .decision_contracts import RiskLevel as DecisionRiskLevel
from .decision_lifecycle import DecisionDisposition, ReviewVerdict
from .domain import AgentMode, ChargeType, ContentType, PassportType
from .evidence import EvidenceGrade
from .finance import CashPlanStatus, FeeSignRule, FinanceEntryKind
from .ozon_finance_review import AccrualAccountingClass, AccrualExpectedSign
from .security import Principal, require_any_role
from .sourcing import PROFIT_TEMPLATE_ID, SourcePlatform

APP_VERSION = "0.59.0"
API_SCHEMA_VERSION = "v1"


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


def ensure_store_scope(principal: Principal, store_ref: str) -> None:
    if not principal.can_access_store(store_ref):
        raise HTTPException(
            status_code=403,
            detail="Authenticated identity is not authorized for store_ref",
        )


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


class EvidenceOpsPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=3, max_length=1000)
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)


class ProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=300)
    store_ref: str | None = Field(default=None, min_length=1, max_length=160)


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


class MarketplaceObservationItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_item_id: str = Field(min_length=1, max_length=240)
    supplier_ref: str = Field(min_length=1, max_length=240)
    title: str = Field(min_length=1, max_length=2000)
    variant_key: str = Field(min_length=1, max_length=500)
    currency: str = Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    )
    displayed_price: Decimal = Field(gt=0)
    price_scope: Literal["unit_price", "checkout_total"] | None = None
    price_kind: Literal[
        "public_display_price",
        "new_customer_price",
        "member_price",
        "range_minimum",
        "marketplace_listing_price",
        "observed_checkout_price",
    ]
    min_order_quantity: int | None = Field(default=None, ge=1)
    availability: str = Field(default="unknown", min_length=1, max_length=80)
    specifications: dict[str, str] = Field(default_factory=dict)
    target_product_id: str | None = Field(default=None, min_length=1, max_length=160)
    target_offer_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_url: str | None = Field(default=None, min_length=8, max_length=2000)
    product_identity: dict[str, str] = Field(default_factory=dict, max_length=40)
    observed_quantity: int | None = Field(default=None, ge=1)
    checkout_verified: bool = False
    tax_included: bool | None = None
    domestic_freight_included: bool | None = None
    purchase_available: bool = False
    confidence: Decimal = Field(default=Decimal("0.5"), gt=0, le=1)
    market_signals: dict[str, Any] = Field(default_factory=dict, max_length=80)
    supply_signals: dict[str, Any] = Field(default_factory=dict, max_length=80)
    media_rights_status: Literal[
        "unverified_external_reference",
        "supplier_authorized",
        "owned",
        "licensed",
    ] = "unverified_external_reference"
    image_references: list[str] = Field(default_factory=list, max_length=20)
    experiment_readbacks: dict[str, Any] = Field(default_factory=dict, max_length=20)


class MarketplaceObservationCaptureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_profile: Literal[
        "browser_observation",
        "seller_tool_export",
        "manual_verified_public_page",
        "public_search_index_observation",
    ]
    marketplace: Literal["1688", "ozon"]
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    source_url: str = Field(min_length=8, max_length=2000)
    observed_at: str
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )
    capture_note: str | None = Field(default=None, max_length=4000)
    items: list[MarketplaceObservationItemInput] = Field(min_length=1, max_length=1000)
    confirmed: Literal[True]


class BrowserCapturePageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=2000)
    canonical_url: str | None = Field(default=None, min_length=8, max_length=2000)
    language: str | None = Field(default=None, min_length=2, max_length=40)
    extractor_version: Literal["kjds-visible-dom/1.0", "kjds-visible-dom/1.1"]
    capture_mode: Literal["active_tab_visible_dom"]


class BrowserCaptureEnvelopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal[
        "kjds-browser-capture-envelope/1.0",
        "kjds-browser-capture-envelope/1.1",
    ]
    source_profile: Literal["browser_observation"]
    marketplace: Literal["1688", "ozon"]
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    source_url: str = Field(min_length=8, max_length=2000)
    observed_at: str
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )
    page: BrowserCapturePageInput
    items: list[MarketplaceObservationItemInput] = Field(min_length=1, max_length=50)
    confirmed: Literal[True]


class AiListingRunPreflightInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capture_submission_id: str = Field(min_length=1, max_length=180)
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    selected_variant_key: str = Field(min_length=1, max_length=500)
    target_marketplace: Literal["ozon"] = "ozon"
    target_locale: Literal["ru-RU"] = "ru-RU"
    mode: Literal["internal_dry_run"] = "internal_dry_run"
    as_of: str


class AiListingRunCreateInput(AiListingRunPreflightInput):
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )


class AiListingRunResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    bindings: dict[str, Any] = Field(default_factory=dict, max_length=20)
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )


class AiListingRunCancelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )


class AgentArtifactFeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    verdict: Literal["accepted", "modified", "rejected"]
    notes: str = Field(min_length=1, max_length=4000)
    edited_output: dict[str, Any] | None = None
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )


class PortfolioPilotPrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    product_id: str = Field(min_length=1, max_length=160)
    target_specification: dict[str, str] = Field(min_length=1, max_length=80)
    policy_id: Literal["ozon-cny-research-screening-v1"] = "ozon-cny-research-screening-v1"
    candidate_target: int = Field(default=100, ge=1, le=1000)
    pilot_limit: int = Field(default=10, ge=1, le=100)
    max_loss_cny: Decimal = Field(default=Decimal("500"), gt=0)
    cm3_floor_cny: Decimal = Field(default=Decimal("0"))
    as_of: str | None = None


class BatchOpportunityPrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    policy_id: Literal["cn-ozon-observed-cost-v1"] = "cn-ozon-observed-cost-v1"
    evidence_class: (
        Literal["manual_small", "auto_scale", "regulated", "eu_export"]
        | None
    ) = Field(
        default=None,
        description=(
            "Explicit scenario evidence class override. When omitted the "
            "policy is inferred deterministically (regulated flags, then "
            "EU market, then automated scan => auto_scale, fail-closed)."
        ),
    )
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )
    candidate_limit: int = Field(default=500, ge=1, le=50000)
    full_evaluate_limit: int = Field(default=500, ge=1, le=5000)
    scan_page_size: int = Field(default=500, ge=1, le=1000)
    scan_shard_count: int = Field(default=1, ge=1, le=100)
    scan_shard_index: int = Field(default=0, ge=0, le=99)
    pilot_limit: int = Field(default=20, ge=1, le=100)
    target_purchase_quantity: int = Field(default=3, ge=1, le=3)
    max_age_hours: int = Field(default=72, ge=1, le=720)
    max_inventory_cash_cny: Decimal = Field(default=Decimal("3000"), gt=0)
    max_batch_inventory_cash_cny: Decimal | None = Field(default=None, gt=0)
    cm3_floor_cny: Decimal = Field(default=Decimal("0"))
    as_of: str | None = None


class ProfitPilotProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    display_currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    idempotency_key: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,179}$",
    )
    max_budget_amount: Decimal | None = Field(default=None, gt=0)
    stop_loss_amount: Decimal | None = Field(default=None, gt=0)
    as_of: str | None = None


class ProfitErpItemSyncPrepareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_ref: str = Field(min_length=1, max_length=160)
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    candidate_id: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )


class OzonGlobalRuleEvaluationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku_ref: str = Field(min_length=1, max_length=160)
    country: Literal["CN"] = "CN"
    locale: Literal["zh"] = "zh"
    passport: dict[str, Any] = Field(default_factory=dict, max_length=80)
    content: dict[str, Any] = Field(default_factory=dict, max_length=100)
    prices: dict[str, Any] = Field(default_factory=dict, max_length=80)
    fulfillment: dict[str, Any] = Field(default_factory=dict, max_length=80)
    quality: dict[str, Any] = Field(default_factory=dict, max_length=80)
    fee: dict[str, Any] = Field(default_factory=dict, max_length=80)
    settlement: dict[str, Any] = Field(default_factory=dict, max_length=80)
    api_access: dict[str, Any] = Field(default_factory=dict, max_length=80)
    analytics: dict[str, Any] = Field(default_factory=dict, max_length=100)
    downside_cm3_cny: Decimal | None = None
    as_of: str | None = None


class OzonGlobalRuleImpactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previous_registry: dict[str, Any] | None = None
    previous_registry_hash: str | None = Field(default=None, min_length=64, max_length=64)
    sku_bindings: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    as_of: str | None = None


class SellerOperatingSystemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_ref: str = Field(default="default", min_length=1, max_length=160)
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    seller_facts: dict[str, Any] = Field(min_length=1, max_length=80)
    operating_facts: dict[str, Any] = Field(default_factory=dict, max_length=80)
    policy_overrides: dict[str, Any] = Field(default_factory=dict, max_length=40)
    portfolio_items: list[dict[str, Any]] = Field(default_factory=list, max_length=10000)
    advantage_facts: dict[str, Any] = Field(default_factory=dict, max_length=80)


class StoreCategoryLevelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=300)


class StoreCategoryPathInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path_id: str = Field(min_length=1, max_length=160)
    role: Literal["core", "adjacent", "experimental", "excluded"]
    level_1: StoreCategoryLevelInput | None = None
    level_2: StoreCategoryLevelInput | None = None
    level_3: StoreCategoryLevelInput | None = None
    leaf_category_id: str | None = Field(default=None, min_length=1, max_length=160)
    product_type_ids: list[str] = Field(default_factory=list, max_length=200)
    derived_tags: list[str] = Field(default_factory=list, max_length=50)
    target_regions: list[str] = Field(default_factory=list, max_length=100)


class StoreOperatingProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=180)
    effective_at: str | None = None
    confirmed: Literal[True]
    store_positioning: Literal[
        "general",
        "category_specialist",
        "brand_flagship",
        "test_lab",
        "outlet",
        "regional",
    ]
    assortment_mode: Literal[
        "controlled_distribution",
        "refined_operation",
        "hero_sku",
        "brand_building",
        "store_cluster",
        "hybrid",
    ]
    price_band: Literal["budget", "value", "mid", "premium", "luxury", "mixed"]
    target_regions: list[str] = Field(default_factory=list, max_length=100)
    fulfillment_models: list[str] = Field(default_factory=list, max_length=20)
    planned_growth_channels: list[Literal["ozon", "vk", "telegram"]] = Field(
        default_factory=list, max_length=3
    )
    customer_segments: list[str] = Field(default_factory=list, max_length=50)
    operational_capabilities: list[str] = Field(default_factory=list, max_length=100)
    category_paths: list[StoreCategoryPathInput] = Field(min_length=1, max_length=200)
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=100)


class StoreOperatingPlanFreezeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=180)
    as_of: str | None = None
    display_currency: str = Field(default="CNY", min_length=3, max_length=3)


class MarketplaceSkuGrowthObservationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1, max_length=120)
    marketplace_sku: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=300)
    competitor_prices_rub: list[Decimal] = Field(min_length=3, max_length=50)
    stock: int = Field(ge=0)
    review_count: int = Field(ge=0)
    orders_14d: int = Field(ge=0)
    rating: Decimal = Field(ge=0, le=5)
    content_score: Decimal = Field(ge=0, le=100)
    conversion_rate: Decimal | None = Field(default=None, ge=0, le=1)
    compliance_risk: Literal["low", "medium", "high"] = "low"
    observed_at: str
    evidence_ids: list[str] = Field(min_length=1, max_length=100)


class MarketplacePortfolioGrowthPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observations: list[MarketplaceSkuGrowthObservationInput] = Field(min_length=1, max_length=100)
    target_cm3_rate: Decimal = Field(gt=0, lt=Decimal("0.5"))
    as_of: str | None = None


class MarketplaceGrowthSnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["ozon_seller_api", "ozon_export", "operator_verified"]
    idempotency_key: str = Field(min_length=1, max_length=160)
    observations: list[MarketplaceSkuGrowthObservationInput] = Field(min_length=1, max_length=1000)


class MarketplaceLatestGrowthPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_cm3_rate: Decimal = Field(gt=0, lt=Decimal("0.5"))
    as_of: str | None = None


class OzonCatalogEvidenceImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_ids: list[str] = Field(min_length=1, max_length=50)
    store_ref: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=1, max_length=160)


class OzonCatalogReadRunImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=300)
    store_ref: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )


class ExistingOzonListingBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(min_length=1, max_length=160)
    offer_id: str = Field(min_length=1, max_length=160)
    expected_item_hash: str = Field(pattern="^[0-9a-f]{64}$")
    confirmed: Literal[True]


class SupplierRfqSpecificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    required_value: str = Field(min_length=1, max_length=500)


class SupplierRfqPackageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(min_length=1, max_length=160)
    offer_id: str = Field(min_length=1, max_length=160)
    expected_item_hash: str = Field(pattern="^[0-9a-f]{64}$")
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )
    quantity_breaks: list[int] = Field(min_length=1, max_length=6)
    required_specifications: list[SupplierRfqSpecificationInput] = Field(
        min_length=1,
        max_length=40,
    )
    destination: str = Field(min_length=1, max_length=240)
    response_due_at: str
    sample_required: bool
    tax_invoice_required: bool
    required_documents: list[str] = Field(min_length=1, max_length=20)
    packaging_requirements: list[str] = Field(min_length=1, max_length=20)
    operator_notes: str | None = Field(default=None, max_length=2000)
    confirmed: Literal[True]


class SupplierRfqDispatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rfq_package_evidence_id: str = Field(min_length=1, max_length=120)
    supplier_ref: str = Field(min_length=1, max_length=240)
    supplier_platform: Literal["1688", "alibaba", "manual"]
    supplier_locator: str = Field(min_length=1, max_length=1000)
    conversation_ref: str = Field(min_length=1, max_length=500)
    sent_at: str
    sent_message_text: str = Field(min_length=1, max_length=30_000)
    idempotency_key: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )
    confirmed: Literal[True]


class SupplierRfqDispatchAuthorityReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool
    authentic_platform_proof: bool
    supplier_identity_matches: bool
    frozen_message_matches: bool
    timestamp_and_conversation_match: bool
    rationale: str = Field(min_length=1, max_length=2000)


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
    metric: Literal["demand_signal", "competition_gap", "supplier_available", "compliance_redline", "return_risk"]
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
    metric: Literal["demand_signal", "competition_gap", "supplier_available", "compliance_redline", "return_risk"]
    approved_grade: Literal[EvidenceGrade.A, EvidenceGrade.B]
    accepted: bool
    authentic_original: bool
    source_scope_matches: bool
    authority_basis_verified: bool
    rationale: str = Field(min_length=1, max_length=2000)


class SupplierQuoteAuthorityReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool
    authentic_original: bool
    supplier_identity_matches: bool
    product_spec_matches: bool
    amount_currency_moq_matches: bool
    validity_and_delivery_terms_present: bool
    rationale: str = Field(min_length=1, max_length=2000)


class ListingRussianNativeReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool
    native_russian_verified: bool
    listing_snapshot_reviewed: bool
    terminology_accepted: bool
    claims_grounded: bool
    ozon_policy_checked: bool
    rationale: str = Field(min_length=1, max_length=2000)


class OzonExecutionIdentityAuthorityReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity_ref: str = Field(min_length=1, max_length=120)
    accepted: bool
    inventory_complete: bool
    credential_material_absent: bool
    owner_verified: bool
    caller_system_verified: bool
    scope_minimized: bool
    dedicated_executor: bool
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
    model_config = ConfigDict(extra="forbid")
    product_id: str
    content_type: ContentType
    locale: str = "ru-RU"
    channel: str = "OZON"
    brief: dict[str, Any]
    store_ref: str | None = Field(default=None, min_length=1, max_length=160)
    as_of: str | None = None


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
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
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
    logistics_calculation_id: str | None = None


class LogisticsRateCardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=160)
    route_code: str = Field(min_length=1, max_length=160)
    service_name: str = Field(min_length=1, max_length=300)
    origin_country: str = Field(min_length=2, max_length=12)
    destination_country: str = Field(min_length=2, max_length=12)
    marketplace: str = Field(min_length=1, max_length=40)
    currency: str = Field(min_length=3, max_length=3)
    declared_value_currency: str = Field(min_length=3, max_length=3)
    price_per_kg: Decimal
    base_charge_per_parcel: Decimal = Decimal("0")
    minimum_charge_per_parcel: Decimal = Decimal("0")
    volumetric_divisor_cm3_per_kg: Decimal = Decimal("0")
    weight_increment_kg: Decimal = Decimal("0.001")
    min_weight_kg: Decimal = Decimal("0")
    max_weight_kg: Decimal
    max_length_cm: Decimal = Decimal("0")
    max_width_cm: Decimal = Decimal("0")
    max_height_cm: Decimal = Decimal("0")
    max_dimensions_sum_cm: Decimal = Decimal("0")
    min_declared_value: Decimal = Decimal("0")
    max_declared_value: Decimal = Decimal("0")
    effective_at: str
    effective_until: str | None = None
    evidence_id: str = Field(min_length=1)
    source_sheet: str = Field(min_length=1, max_length=300)
    source_range: str = Field(min_length=1, max_length=80)


class LogisticsCalculationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    rate_card_id: str = Field(min_length=1)
    physical_weight_kg: Decimal
    length_cm: Decimal = Decimal("0")
    width_cm: Decimal = Decimal("0")
    height_cm: Decimal = Decimal("0")
    declared_value: Decimal = Decimal("0")
    quantity: int = Field(default=1, ge=1)
    currency_to_cny_rate: Decimal = Decimal("1")
    fx_evidence_id: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=160)
    evaluated_at: str | None = None


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
    store_ref: str | None = Field(default=None, min_length=1, max_length=160)
    as_of: str | None = None


class KillSwitchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


class LoopValidationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module: Literal["automations", "skills", "integrations", "subagents", "worktrees", "memory"]
    mode: Literal["proposal", "shadow", "active"]
    controls: dict[str, Any]


class GlobalExpertTaskRouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_ref: str = Field(min_length=1, max_length=160)
    task_type: Literal[
        "market_research",
        "country_entry",
        "product_portfolio",
        "platform_operations",
        "sourcing_quality",
        "logistics_customs",
        "finance_profit",
        "legal_compliance",
        "localization_content",
        "growth_commercial",
        "product_management",
        "data_ai",
        "architecture_delivery",
    ]
    market: str = Field(min_length=2, max_length=6)
    platform: str = Field(min_length=1, max_length=80)
    risk_level: Literal["L0", "L1", "L2", "L3", "L4"]
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class TeamControlAdvanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    continuation: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    result: Literal["take", "done", "blocked", "escalate", "stop"]
    rationale: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)
    idempotency_key: str = Field(min_length=1, max_length=200)


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
    role: Literal["cannibalization", "long_term_cost", "long_term_value", "secondary"]
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
    type: str = Field(pattern="^recommend_", max_length=200)
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
    precondition_state_hash: str = Field(pattern="^[0-9a-fA-F]{64}$")
    intended_patch: dict[str, Any]
    rollback_patch: dict[str, Any]
    evidence_ids: list[str] = Field(min_length=1)
    risk_limits: dict[str, Any] | None = None
    risk_values: dict[str, Any] | None = None
    risk_currency: str | None = Field(default=None, min_length=3, max_length=3)


class ApprovedListingExecutionPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=300)
    precondition_state_hash: str = Field(pattern="^[0-9a-fA-F]{64}$")
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    risk_limits: dict[str, Any]
    risk_values: dict[str, Any]
    risk_currency: str = Field(min_length=3, max_length=3)


class GovernedExecutionDryRunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_state_hash: str = Field(pattern="^[0-9a-fA-F]{64}$")
    evidence_ids: list[str] = Field(min_length=1)


class LimitedExecutionClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_state_hash: str = Field(pattern="^[0-9a-fA-F]{64}$")
    lease_seconds: int = Field(default=120, ge=30, le=600)


class LimitedExecutionReceiptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["succeeded", "failed", "uncertain"]
    remote_operation_id: str | None = Field(default=None, max_length=500)
    resulting_state_hash: str | None = Field(default=None, pattern="^[0-9a-fA-F]{64}$")
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
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    as_of: str | None = None


class AnomalyScanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    as_of: str | None = None


class ScopeGrantEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_ref: str = Field(min_length=1, max_length=160)
    store_ref: str = Field(min_length=1, max_length=160)
    subject_actor_id: str = Field(min_length=1, max_length=160)
    event_type: Literal["grant", "revoke"]
    effective_at: str
    evidence_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=300)


class ScopeGrantSourceReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_evidence_id: str = Field(min_length=1, max_length=160)
    entity_ref: str = Field(min_length=1, max_length=160)
    store_ref: str = Field(min_length=1, max_length=160)
    subject_actor_id: str = Field(min_length=1, max_length=160)
    event_type: Literal["grant", "revoke"]
    effective_at: str
    accepted: bool
    authentic_original: bool
    owner_authority_verified: bool
    scope_matches: bool
    rationale: str = Field(min_length=1, max_length=5000)
    idempotency_key: str = Field(min_length=1, max_length=300)


class EvidenceScopeBindingSubmitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    target_evidence_id: str = Field(min_length=1, max_length=240)
    effective_at: str
    idempotency_key: str = Field(min_length=1, max_length=300)


class EvidenceScopeBindingReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    submission_evidence_id: str = Field(min_length=1, max_length=240)
    accepted: bool
    rationale: str = Field(min_length=1, max_length=5000)
    effective_at: str
    idempotency_key: str = Field(min_length=1, max_length=300)


class EvidenceScopeBindingRecordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    submission_evidence_id: str = Field(min_length=1, max_length=240)
    review_evidence_id: str = Field(min_length=1, max_length=240)
    effective_at: str
    idempotency_key: str = Field(min_length=1, max_length=300)


class SellerErpBridgeReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_evidence_id: str = Field(min_length=1, max_length=160)
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    accepted: bool
    authentic_original: bool
    authorization_verified: bool
    export_scope_matches: bool
    schema_mapping_verified: bool
    no_session_or_secret_material: bool
    rationale: str = Field(min_length=1, max_length=5000)
    effective_at: str
    idempotency_key: str = Field(min_length=1, max_length=300)


class SellerErpBridgeBindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_evidence_id: str = Field(min_length=1, max_length=160)
    review_evidence_id: str = Field(min_length=1, max_length=160)
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    effective_at: str
    effective_until: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=300)


class SellerErpBridgeRevocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_evidence_id: str = Field(min_length=1, max_length=160)
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=2000)
    effective_at: str
    idempotency_key: str = Field(min_length=1, max_length=300)


class OperatingSubjectEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_actor_id: str = Field(min_length=1, max_length=160)
    event_type: Literal["bind", "revoke"]
    effective_at: str
    reason: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=300)


class OperatingTaskTransitionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["acknowledge", "start", "resolve", "dismiss"]
    reason: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class MediaExecutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=300)
    retry: bool = False


class MediaBatchItemInput(MediaExecutionInput):
    asset_id: str = Field(min_length=1, max_length=300)


class MediaBatchExecutionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=300)
    items: list[MediaBatchItemInput] = Field(min_length=1, max_length=100)


class ReadOnlyPilotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=300)
    platform: Literal["ozon"] = "ozon"
    account_alias: str = Field(min_length=1, max_length=300)
    allowed_operations: list[
        Literal[
            "ozon.product.read", "ozon.inventory.read", "ozon.orders.read", "ozon.analytics.read", "ozon.finance.read"
        ]
    ] = Field(min_length=1)
    max_daily_requests: int = Field(ge=1, le=10000)
    max_targets: int = Field(ge=1, le=1000)
    starts_at: str
    ends_at: str
    evidence_ids: list[str] = Field(min_length=1)
    store_ref: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    as_of: str | None = None


class PilotControlAttestationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    control: Literal[
        "credentials_isolated", "least_privilege_scope", "monitoring_configured", "data_export_backup_verified"
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
    claim_type: Literal["product_identity", "product_attribute", "inventory_observation", "price_observation"]
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


class ScopedFxEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(min_length=1, max_length=160)
    source_currency: str = Field(min_length=3, max_length=3)
    target_currency: str = Field(min_length=3, max_length=3)
    rate: Decimal
    effective_at: datetime
    expires_at: datetime
    evidence_id: str = Field(min_length=1, max_length=240)
    source_type: str = Field(min_length=1, max_length=120)
    authority: str = Field(min_length=1, max_length=300)
    purposes: list[str] = Field(min_length=1, max_length=20)
    idempotency_key: str = Field(min_length=1, max_length=180)


class CommercialScopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_ref: str = Field(min_length=1, max_length=160)
    deployment_ref: str = Field(min_length=1, max_length=160)
    tenant_ref: str = Field(min_length=1, max_length=160)
    entity_ref: str = Field(min_length=1, max_length=160)
    store_ref: str = Field(min_length=1, max_length=160)


class CommercialEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(min_length=1, max_length=240)
    evidence_sha256: str = Field(min_length=64, max_length=64)
    evidence_kind: str = Field(min_length=1, max_length=120)
    authority: str = Field(min_length=1, max_length=300)
    source_kind: str = Field(min_length=1, max_length=120)
    purposes: list[str] = Field(default_factory=list, max_length=20)


class CommercialPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: CommercialScopeInput
    plan_ref: str = Field(min_length=1, max_length=240)
    state: Literal["draft", "approved", "frozen", "closed"] = "approved"
    currency: str = Field(min_length=3, max_length=3)
    gross_amount: Decimal = Field(ge=0)
    effective_at: datetime
    billing_window_start: datetime
    billing_window_end: datetime
    metric_limits: list[dict[str, Any]] = Field(min_length=1, max_length=20)
    evidence: CommercialEvidenceInput
    idempotency_key: str = Field(min_length=1, max_length=180)


class CommercialSubscriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: CommercialScopeInput
    subscription_ref: str = Field(min_length=1, max_length=240)
    plan_ref: str = Field(min_length=1, max_length=240)
    state: Literal["pending", "active", "past_due", "canceled", "closed"] = "active"
    currency: str = Field(min_length=3, max_length=3)
    amount: Decimal = Field(ge=0)
    effective_at: datetime
    expires_at: datetime | None = None
    settlement_evidence: CommercialEvidenceInput
    evidence: CommercialEvidenceInput
    idempotency_key: str = Field(min_length=1, max_length=180)


class CommercialInvoiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: CommercialScopeInput
    invoice_ref: str = Field(min_length=1, max_length=240)
    subscription_ref: str = Field(min_length=1, max_length=240)
    state: Literal["draft", "issued", "partially_paid", "paid", "void", "closed"] = "issued"
    currency: str = Field(min_length=3, max_length=3)
    net_amount: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(ge=0)
    gross_amount: Decimal = Field(gt=0)
    issued_at: datetime
    due_at: datetime
    evidence: CommercialEvidenceInput
    idempotency_key: str = Field(min_length=1, max_length=180)


class CommercialPaymentAttemptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: CommercialScopeInput
    payment_attempt_ref: str = Field(min_length=1, max_length=240)
    invoice_ref: str = Field(min_length=1, max_length=240)
    state: Literal["pending", "submitted", "succeeded", "failed", "settled"] = "submitted"
    currency: str = Field(min_length=3, max_length=3)
    amount: Decimal = Field(gt=0)
    occurred_at: datetime
    evidence: CommercialEvidenceInput
    idempotency_key: str = Field(min_length=1, max_length=180)


class CommercialRefundInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: CommercialScopeInput
    refund_ref: str = Field(min_length=1, max_length=240)
    invoice_ref: str = Field(min_length=1, max_length=240)
    payment_attempt_ref: str | None = Field(default=None, min_length=1, max_length=240)
    state: Literal["requested", "approved", "paid", "rejected", "reversed"] = "requested"
    currency: str = Field(min_length=3, max_length=3)
    amount: Decimal = Field(gt=0)
    occurred_at: datetime
    evidence: CommercialEvidenceInput
    idempotency_key: str = Field(min_length=1, max_length=180)


class CommercialTaxEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: CommercialScopeInput
    tax_evidence_ref: str = Field(min_length=1, max_length=240)
    invoice_ref: str = Field(min_length=1, max_length=240)
    refund_ref: str | None = Field(default=None, min_length=1, max_length=240)
    state: Literal["recorded", "verified", "rejected"] = "recorded"
    currency: str = Field(min_length=3, max_length=3)
    amount: Decimal = Field(ge=0)
    observed_at: datetime
    evidence: CommercialEvidenceInput
    idempotency_key: str = Field(min_length=1, max_length=180)


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


class SupplierInvoiceLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_number: int = Field(ge=1, le=1000)
    product_id: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=5000)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    net_amount: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(ge=0)
    gross_amount: Decimal = Field(ge=0)


class SupplierInvoiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    invoice_ref: str = Field(min_length=1, max_length=240)
    purchase_order_id: str = Field(min_length=1, max_length=240)
    supplier_ref: str = Field(min_length=1, max_length=240)
    currency: str = Field(min_length=3, max_length=3)
    net_amount: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(ge=0)
    gross_amount: Decimal = Field(gt=0)
    issued_at: str
    due_at: str
    evidence_id: str = Field(min_length=1, max_length=240)
    lines: list[SupplierInvoiceLineInput] = Field(
        min_length=1,
        max_length=1000,
    )


class SupplierInvoiceAuthorityReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: bool
    authentic_original: bool
    legal_entity_matches: bool
    supplier_matches: bool
    purchase_order_matches: bool
    receipt_inspection_matches: bool
    line_quantity_price_matches: bool
    currency_tax_total_matches: bool
    rationale: str = Field(min_length=1, max_length=5000)
    idempotency_key: str = Field(min_length=1, max_length=300)


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


class CustomerServiceCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(
        default="ozon-primary",
        min_length=1,
        max_length=160,
    )
    external_case_ref: str = Field(min_length=1, max_length=240)
    channel: Literal["ozon", "email", "chat", "phone", "other_authorized"]
    order_external_id: str = Field(min_length=1, max_length=240)
    product_id: str = Field(min_length=1, max_length=240)
    sku: str = Field(min_length=1, max_length=240)
    locale: str = Field(min_length=1, max_length=40)
    classification: Literal[
        "product_question",
        "delivery",
        "damage",
        "return",
        "refund",
        "dispute",
        "rma",
        "other",
    ]
    priority: Literal["low", "normal", "high", "urgent"]
    evidence_id: str = Field(min_length=1, max_length=240)
    opened_at: str


class CustomerServiceEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    store_ref: str = Field(
        default="ozon-primary",
        min_length=1,
        max_length=160,
    )
    source_event_ref: str = Field(min_length=1, max_length=240)
    sequence: int = Field(ge=1)
    event_type: Literal[
        "case_opened",
        "triaged",
        "reply_drafted",
        "reply_approval_pending",
        "reply_permit_pending",
        "reply_readback_pending",
        "message_received",
        "message_sent_readback",
        "return_opened",
        "dispute_opened",
        "dispute_resolved",
        "rma_opened",
        "rma_resolved",
        "resolved",
        "closed",
    ]
    direction: Literal["inbound", "outbound", "system"]
    locale: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1, max_length=500)
    body_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern="^[0-9a-fA-F]{64}$",
    )
    evidence_id: str = Field(min_length=1, max_length=240)
    effective_at: str
    approval_id: str | None = Field(default=None, min_length=1, max_length=240)
    command_id: str | None = Field(default=None, min_length=1, max_length=240)
    receipt_id: str | None = Field(default=None, min_length=1, max_length=240)


class WarehouseExecutionEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_ref: str = Field(
        default="ozon-primary",
        min_length=1,
        max_length=160,
    )
    warehouse_ref: str = Field(min_length=1, max_length=160)
    source_event_ref: str = Field(min_length=1, max_length=240)
    aggregate_ref: str = Field(min_length=1, max_length=240)
    sequence: int = Field(ge=1)
    event_type: Literal[
        "location_registered",
        "bin_registered",
        "lot_received",
        "reservation_created",
        "reservation_released",
        "wave_created",
        "wave_order_added",
        "pick_scanned",
        "pack_scanned",
        "parcel_created",
        "label_bound",
        "weight_scanned",
        "inventory_adjustment_readback",
        "outbound_confirmed_readback",
        "label_purchased_readback",
        "carrier_handoff_readback",
        "exception_recorded",
    ]
    order_external_id: str = Field(min_length=1, max_length=240)
    product_id: str = Field(min_length=1, max_length=240)
    sku: str = Field(min_length=1, max_length=240)
    evidence_id: str = Field(min_length=1, max_length=240)
    effective_at: str = Field(min_length=1, max_length=80)
    location_ref: str | None = Field(default=None, max_length=240)
    bin_ref: str | None = Field(default=None, max_length=240)
    lot_ref: str | None = Field(default=None, max_length=240)
    wave_ref: str | None = Field(default=None, max_length=240)
    parcel_ref: str | None = Field(default=None, max_length=240)
    label_ref: str | None = Field(default=None, max_length=240)
    quantity: int | None = Field(default=None, ge=1)
    weight_kg: str | None = Field(default=None, max_length=48)
    weight_source: (
        Literal[
            "authorized_scale_readback",
            "official_carrier_readback",
            "authorized_formal_export",
        ]
        | None
    ) = None
    carrier_ref: str | None = Field(default=None, max_length=240)
    service_ref: str | None = Field(default=None, max_length=240)
    approval_id: str | None = Field(default=None, max_length=240)
    command_id: str | None = Field(default=None, max_length=240)
    receipt_id: str | None = Field(default=None, max_length=240)
    kill_switch_evidence_id: str | None = Field(
        default=None,
        max_length=240,
    )
    compensation_evidence_id: str | None = Field(
        default=None,
        max_length=240,
    )


class ChannelAccountAuthorizationEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_ref: str = Field(
        default="ozon-primary",
        min_length=1,
        max_length=160,
    )
    source_event_ref: str = Field(min_length=1, max_length=240)
    sequence: int = Field(ge=1)
    event_type: Literal[
        "authorization_granted",
        "authorization_refreshed",
        "credential_rotated",
        "authorization_revoked",
        "authorization_expired",
        "external_verification_readback",
        "health_observed",
        "rate_limit_observed",
        "schema_drift_observed",
        "unknown_outcome_observed",
    ]
    authorization_source: Literal[
        "official",
        "explicit_written_authorization",
    ]
    platform: str = Field(min_length=1, max_length=80)
    account_ref: str = Field(min_length=1, max_length=240)
    adapter_id: str = Field(min_length=1, max_length=160)
    adapter_version: str = Field(min_length=1, max_length=80)
    credential_kind: Literal[
        "api_key_ref",
        "oauth_client_ref",
        "service_account_ref",
    ]
    capabilities: list[str] = Field(min_length=1, max_length=100)
    secret_reference: str = Field(min_length=1, max_length=256)
    credential_fingerprint_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern="^[0-9a-fA-F]{64}$",
    )
    health_status: Literal[
        "healthy",
        "degraded",
        "unreachable",
        "unknown",
    ]
    readback_outcome: Literal[
        "succeeded",
        "failed",
        "unknown",
        "not_applicable",
    ]
    rate_limit_state: Literal[
        "available",
        "limited",
        "exhausted",
        "unknown",
    ]
    external_schema_version: str = Field(min_length=1, max_length=80)
    consent_evidence_id: str = Field(min_length=1, max_length=240)
    evidence_id: str = Field(min_length=1, max_length=240)
    effective_at: str = Field(min_length=1, max_length=80)
    expires_at: str = Field(min_length=1, max_length=80)
    verified_at: str = Field(min_length=1, max_length=80)
    role_ref: str | None = Field(default=None, max_length=160)
    subaccount_ref: str | None = Field(default=None, max_length=240)
    approval_id: str | None = Field(default=None, max_length=240)
    command_id: str | None = Field(default=None, max_length=240)
    receipt_id: str | None = Field(default=None, max_length=240)
    permit_evidence_id: str | None = Field(default=None, max_length=240)
    readback_evidence_id: str | None = Field(default=None, max_length=240)
    kill_switch_sequence: int | None = Field(default=None, ge=1)
    kill_switch_state_id: str | None = Field(
        default=None,
        max_length=240,
    )
    kill_switch_evidence_id: str | None = Field(
        default=None,
        max_length=240,
    )
    compensation_plan_id: str | None = Field(
        default=None,
        max_length=240,
    )
    compensation_evidence_id: str | None = Field(
        default=None,
        max_length=240,
    )


class ChannelAccountKillSwitchStateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_ref: str = Field(
        default="ozon-primary",
        min_length=1,
        max_length=160,
    )
    source_event_ref: str = Field(min_length=1, max_length=240)
    sequence: int = Field(ge=1)
    kill_switch_sequence: int = Field(ge=1)
    writes_enabled: bool
    action_id: Literal[
        "channel_authorization_grant",
        "channel_authorization_refresh",
        "channel_credential_rotate",
        "channel_authorization_revoke",
        "channel_authorization_external_verify",
    ]
    platform: str = Field(min_length=1, max_length=80)
    account_ref: str = Field(min_length=1, max_length=240)
    adapter_id: str = Field(min_length=1, max_length=160)
    adapter_version: str = Field(min_length=1, max_length=80)
    evidence_id: str = Field(min_length=1, max_length=240)
    effective_at: str = Field(min_length=1, max_length=80)
