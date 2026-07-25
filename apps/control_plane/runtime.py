from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .action_policies import ActionAuthorizationService, ActionPolicyRegistry
from .automation import AutomationService
from .candidate_evidence_review import CandidateEvidenceAuthorityService
from .capability_economics import CapabilityEconomicsService
from .causal_experiments import CausalExperimentService
from .causal_knowledge import CausalKnowledgeService
from .causal_policies import CausalPolicyService
from .content_growth import ContentGrowthService
from .cost_evidence_review import CostEvidenceAuthorityService
from .database import create_database_engine
from .decision_contracts import DecisionContractService
from .decision_lifecycle import DecisionLifecycleService
from .demand_report_gate import DemandReportGateService
from .evidence import EvidenceService
from .evidence_integrity import EvidenceIntegrityMonitorService
from .execution_authority import ListingExecutionAuthorityService
from .execution_plans import ExecutionPlanService
from .facts import FactPromotionService
from .finance import FinanceService
from .governance import GovernanceService
from .image_execution import ComfyImageExecutionService
from .imports import OzonImportService
from .incident_recovery import IncidentRecoveryService
from .intake import ProductMediaEvidenceService, SkuEpisodeIntakeService
from .intelligence import MarketIntelligenceService
from .limited_executor import LimitedExecutorService
from .logistics import LogisticsQuoteWorkspace, SqlLogisticsStore
from .loop_engineering import LoopEngineeringService
from .marketplace_catalog import MarketplaceCatalogWorkspace, SqlMarketplaceCatalogStore
from .marketplace_growth import MarketplaceGrowthPlanner
from .marketplace_growth_workspace import (
    MarketplaceGrowthWorkspace,
    SqlMarketplaceGrowthStore,
)
from .operating_workbench import OperatingWorkbenchService
from .operations_queue import OperationsQueueService
from .outbox import OutboxService
from .ozon_finance_review import (
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
from .readiness import ExecutionReadinessService, GateReadinessService
from .repository import InMemoryRepository
from .research_inbox import ResearchInboxService
from .security import ApiKeyAuthenticator, KillSwitchService
from .services import CommerceService
from .sourcing import SourcingService
from .sourcing_intake import SupplierComparisonIntakeService
from .sourcing_store import SqlSourcingStore
from .sql_repository import SqlAlchemyRepository
from .supplier_quote_authority import SupplierQuoteAuthorityService


@dataclass(slots=True)
class RuntimeServices:
    action_authorization: Any
    action_policies: Any
    authenticator: Any
    automation: Any
    candidate_evidence_authority: Any
    capability_economics: Any
    causal_experiments: Any
    causal_knowledge: Any
    causal_policies: Any
    commerce: Any
    content: Any
    cost_evidence_authority: Any
    decision_contracts: Any
    decision_lifecycle: Any
    demand_reports: Any
    engine: Any
    evidence: Any
    evidence_integrity: Any
    listing_execution_authority: Any
    execution_plans: Any
    facts: Any
    finance: Any
    finance_report_reviews: Any
    governance: Any
    image_execution: Any
    imports: Any
    incident_recovery: Any
    intake: Any
    kill_switch: Any
    limited_executor: Any
    logistics: Any
    logistics_store: Any
    loop_engineering: Any
    market: Any
    marketplace_catalog: Any
    marketplace_growth: Any
    operating_workbench: Any
    operations_queue: Any
    outbox: Any
    ozon_accrual_classifications: Any
    ozon_fee_mappings: Any
    pilot_readiness: Any
    pilot_runs: Any
    policy_shadow: Any
    post_execution: Any
    procurement: Any
    product_media: Any
    providers: Any
    read_only_claims: Any
    readiness: Any
    repo: Any
    research_inbox: Any
    sourcing: Any
    sourcing_intake: Any
    sourcing_store: Any
    supplier_quote_authority: Any


def build_repository():
    if os.getenv("KJDS_REPOSITORY", "postgres").lower() == "memory":
        return InMemoryRepository()
    return SqlAlchemyRepository()


def build_runtime() -> RuntimeServices:
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
    action_policies = ActionPolicyRegistry()
    action_authorization = ActionAuthorizationService(action_policies)
    policy_shadow = PolicyShadowService(
        engine=engine,
        policies=causal_policies,
        evidence=evidence,
        commerce=commerce,
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
        action_authorization=action_authorization,
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
    logistics_store = SqlLogisticsStore(engine)
    logistics = LogisticsQuoteWorkspace(
        store=logistics_store,
        evidence_validator=evidence.require_valid,
        evidence_linker=evidence.link,
        evidence_resolver=evidence.get,
        fx_evidence_current_validator=evidence.require_current,
    )
    cost_evidence_authority = CostEvidenceAuthorityService(evidence=evidence)
    supplier_quote_authority = SupplierQuoteAuthorityService(evidence=evidence)
    sourcing = SourcingService(
        sourcing_store,
        repo,
        evidence_validator=evidence.require_valid,
        actual_cost_validator=cost_evidence_authority.require_actual,
        offer_authority_validator=supplier_quote_authority.require_accepted,
        action_authorization=action_authorization,
        logistics_profit_resolver=logistics.resolve_profit_cost,
    )
    marketplace_growth_planner = MarketplaceGrowthPlanner(
        sourcing_store=sourcing_store,
        sourcing=sourcing,
        repository=repo,
        evidence=evidence,
    )
    marketplace_growth = MarketplaceGrowthWorkspace(
        planner=marketplace_growth_planner,
        store=SqlMarketplaceGrowthStore(engine),
    )
    sourcing_intake = SupplierComparisonIntakeService(
        sourcing=sourcing,
        evidence=evidence,
        quote_authority=supplier_quote_authority,
        logistics=logistics,
    )
    procurement = ProcurementService(
        engine=engine,
        repository=repo,
        sourcing_store=sourcing_store,
        sourcing=sourcing,
        evidence=evidence,
    )
    governance = GovernanceService(engine=engine, evidence=evidence)
    read_only_claims = ReadOnlyClaimService(engine=engine, evidence=evidence)
    kill_switch = KillSwitchService(engine)
    listing_execution_authority = ListingExecutionAuthorityService(
        evidence=evidence,
        sourcing=sourcing,
    )
    execution_readiness = ExecutionReadinessService(
        commerce=commerce,
        sourcing=sourcing,
        evidence=evidence,
        demand_reports=demand_reports,
        kill_switch=kill_switch,
        listing_execution_authority=listing_execution_authority,
        execution_identity_ref=os.getenv("KJDS_OZON_EXECUTION_IDENTITY_REF", "").strip()
        or None,
    )

    execution_plans = ExecutionPlanService(
        engine=engine,
        policy_shadow=policy_shadow,
        policies=causal_policies,
        evidence=evidence,
        commerce=commerce,
        action_authorization=action_authorization,
        readiness_provider=execution_readiness.snapshot,
        sourcing=sourcing,
        repository=repo,
    )
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
    operating_workbench = OperatingWorkbenchService(
        readiness=readiness,
        operations_queue=operations_queue,
        automation=automation,
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
    marketplace_catalog = MarketplaceCatalogWorkspace(
        verified_bundle_loader=pilot_runs.verified_product_response_bundle,
        store=SqlMarketplaceCatalogStore(engine),
        evidence=evidence,
        repository=repo,
    )
    providers = {"comfyui": ComfyUIProvider(os.getenv("KJDS_COMFYUI_URL", "http://127.0.0.1:8189"))}
    if url := os.getenv("KJDS_OLLAMA_URL", "").strip():
        providers["ollama"] = OllamaProvider(url)
    if url := os.getenv("KJDS_N8N_URL", "").strip():
        providers["n8n"] = N8nProvider(url)
    if url := os.getenv("FIRECRAWL_API_URL", "").strip():
        providers["firecrawl"] = FirecrawlProvider(url, os.getenv("FIRECRAWL_API_KEY") or None)
    image_execution = ComfyImageExecutionService(
        repository=repo,
        content=content,
        evidence=evidence,
        provider=providers["comfyui"],
        action_authorization=action_authorization,
    )
    return RuntimeServices(
        action_authorization=action_authorization,
        action_policies=action_policies,
        authenticator=authenticator,
        automation=automation,
        candidate_evidence_authority=candidate_evidence_authority,
        capability_economics=capability_economics,
        causal_experiments=causal_experiments,
        causal_knowledge=causal_knowledge,
        causal_policies=causal_policies,
        commerce=commerce,
        content=content,
        cost_evidence_authority=cost_evidence_authority,
        decision_contracts=decision_contracts,
        decision_lifecycle=decision_lifecycle,
        demand_reports=demand_reports,
        engine=engine,
        evidence=evidence,
        evidence_integrity=evidence_integrity,
        listing_execution_authority=listing_execution_authority,
        execution_plans=execution_plans,
        facts=facts,
        finance=finance,
        finance_report_reviews=finance_report_reviews,
        governance=governance,
        image_execution=image_execution,
        imports=imports,
        incident_recovery=incident_recovery,
        intake=intake,
        kill_switch=kill_switch,
        limited_executor=limited_executor,
        logistics=logistics,
        logistics_store=logistics_store,
        loop_engineering=loop_engineering,
        market=market,
        marketplace_catalog=marketplace_catalog,
        marketplace_growth=marketplace_growth,
        operating_workbench=operating_workbench,
        operations_queue=operations_queue,
        outbox=outbox,
        ozon_accrual_classifications=ozon_accrual_classifications,
        ozon_fee_mappings=ozon_fee_mappings,
        pilot_readiness=pilot_readiness,
        pilot_runs=pilot_runs,
        policy_shadow=policy_shadow,
        post_execution=post_execution,
        procurement=procurement,
        product_media=product_media,
        providers=providers,
        read_only_claims=read_only_claims,
        readiness=readiness,
        repo=repo,
        research_inbox=research_inbox,
        sourcing=sourcing,
        sourcing_intake=sourcing_intake,
        sourcing_store=sourcing_store,
        supplier_quote_authority=supplier_quote_authority,
    )


runtime = build_runtime()
