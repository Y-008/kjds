from __future__ import annotations

from dataclasses import asdict
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

APP_VERSION = "0.48.0"
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


class SourceAcquisitionPullInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connector_name: str = Field(min_length=1, max_length=120)
    cursor: str | None = Field(default=None, max_length=500)


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


class SalesFulfillmentPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sales_order_id: str = Field(min_length=1, max_length=200)


class SalesFulfillmentRouteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effective_at: str
    evidence_id: str = Field(min_length=1)
    aggregator: Literal["kuajing84"] = "kuajing84"
    carrier_code: str = Field(min_length=2, max_length=40)
    service_code: str = Field(min_length=1, max_length=120)
    warehouse_id: str = Field(min_length=1, max_length=200)
    warehouse_name: str = Field(min_length=1, max_length=300)
    warehouse_address: str = Field(min_length=1, max_length=1000)
    address_valid_at: str
    delivery_method_status: Literal["active", "legacy_only"]
    legacy_connection: bool = False


class SalesFulfillmentProcurementApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offer_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    quantity: int = Field(ge=1)
    rationale: str = Field(default="", max_length=2000)


class SalesFulfillmentEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal[
        "supplier_order_confirmed",
        "domestic_shipped",
        "warehouse_received",
        "packed_for_export",
        "international_handover",
        "cancelled",
    ]
    effective_at: str
    evidence_id: str = Field(min_length=1)
    facts: dict[str, Any]


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
    module: Literal["automations", "skills", "integrations", "subagents", "worktrees", "memory"]
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
    as_of: str | None = None


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
