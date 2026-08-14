from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from .accounts_payable import AccountsPayableAuthorityService
from .action_policies import ActionAuthorizationService, ActionPolicyRegistry
from .agent_harness import AgentHarnessService
from .agent_inference import (
    AgentInferenceService,
    AgentTaskRegistry,
    OllamaInferenceAdapter,
    OpenAICompatibleInferenceAdapter,
)
from .agent_runtime import (
    AdapterProfile,
    ExistingInferenceRuntimeAdapter,
    GovernedAgentRuntime,
)
from .agent_runtime_evidence import SqlAgentRuntimeEvidenceLedger
from .ai_listing import AiListingPipeline
from .automation import AutomationService
from .batch_opportunity import BatchOpportunityWorkspace
from .browser_capture_inbox import BrowserCaptureInbox
from .candidate_evidence_review import CandidateEvidenceAuthorityService
from .capability_economics import CapabilityEconomicsService
from .catalog_read_run_handoff import CatalogReadRunHandoffService
from .causal_experiments import CausalExperimentService
from .causal_knowledge import CausalKnowledgeService
from .causal_policies import CausalPolicyService
from .channel_account_authority import (
    ChannelAccountAdapterRegistry,
    ChannelAccountAuthorizationAuthority,
    ChannelAccountGovernanceEvidenceAuthority,
)
from .channel_account_governance import ChannelAccountGovernanceStateMachine
from .channel_account_runtime_identity import SignedManagedCredentialLeaseResolver
from .closed_loop_evolution import (
    ClosedLoopAuthorityReceiptRegistrarPort,
    ClosedLoopEventEvidenceIssuerPort,
    ClosedLoopEvidenceIssuerPort,
    GovernedClosedLoopEvolutionWorkspace,
)
from .commerce_operating_system import CommerceOperatingSystem
from .commercial_lifecycle import CommercialLifecycleService
from .content_growth import ContentGrowthService
from .cost_evidence_review import CostEvidenceAuthorityService
from .cross_border_capability_atlas import CrossBorderCapabilityAtlas
from .customer_service import CustomerServiceAuthorityService
from .database import (
    create_closed_loop_database_engine,
    create_database_engine,
    create_global_data_coverage_evidence_authority,
    runtime_database_url,
)
from .decision_contracts import DecisionContractService
from .decision_lifecycle import DecisionLifecycleService
from .demand_report_gate import DemandReportGateService
from .editing_blueprint import GovernedEditingBlueprintWorkspace
from .enterprise_ai_erp_program import EnterpriseAiErpProgram
from .enterprise_positioning import EnterprisePositioningAdvisor
from .evidence import (
    ClosedLoopEvidenceAuthorityAdapter,
    EvidenceService,
    GlobalDataCoverageEvidenceAuthorityAdapter,
)
from .evidence_integrity import EvidenceIntegrityMonitorService
from .evidence_scope import ScopedEvidenceAuthority
from .evidence_scope_binding import EvidenceScopeBindingService
from .evidenceops_copilot import EvidenceOpsCopilot
from .execution_authority import ListingExecutionAuthorityService
from .execution_plans import ExecutionPlanService
from .facts import FactPromotionService
from .finance import FinanceService
from .fx_evidence_intake import FxEvidenceIntake
from .global_expert_team import GlobalPortfolioOrchestrator
from .governance import GovernanceService
from .governance_scope import GovernanceScopeAuthority
from .image_execution import ComfyImageExecutionService
from .imports import OzonImportService
from .incident_recovery import IncidentRecoveryService
from .intake import ProductMediaEvidenceService, SkuEpisodeIntakeService
from .intelligence import MarketIntelligenceService
from .intelligence_ingestion import IntelligenceSourceAdapterRegistry
from .limited_executor import LimitedExecutorService
from .logistics import LogisticsQuoteWorkspace, SqlLogisticsStore
from .loop_engineering import LoopEngineeringService
from .managed_credential_leases import (
    SqlManagedCredentialLeaseBindingSource,
    SqlManagedCredentialLeaseStore,
    SqlManagedStoreRuntimeIdentityVerifier,
)
from .market_recon_bundle import MarketReconBundleIngestion
from .marketplace_catalog import MarketplaceCatalogWorkspace, SqlMarketplaceCatalogStore
from .marketplace_growth import MarketplaceGrowthPlanner
from .marketplace_growth_workspace import (
    MarketplaceGrowthWorkspace,
    SqlMarketplaceGrowthStore,
)
from .marketplace_observation import (
    MarketplaceObservationWorkspace,
    PortfolioPilotWorkspace,
)
from .media_connectors import MediaConnectorContract, MediaConnectorRegistry
from .media_jobs import GovernedMediaJobWorkspace
from .media_workbench import FfmpegMediaWorker, MediaWorkbenchService
from .native_parity_acceptance import (
    ACCEPTANCE_DIMENSIONS,
    NativeParityAcceptanceWorkspace,
    RegistryMappingAcceptanceRecords,
)
from .native_parity_graph import SqlNativeParityAcceptanceRecords
from .operating_analytics import OperatingAnalyticsService
from .operating_gate_observer import OperatingGateObserverService
from .operating_intelligence import OperatingIntelligenceService
from .operating_workbench import OperatingWorkbenchService
from .operating_workspace import OperatingWorkspaceService
from .operations_queue import OperationsQueueService
from .outbox import OutboxService
from .ozon_finance_review import (
    OzonAccrualClassificationService,
    OzonFeeMappingApprovalService,
    OzonFinanceReportReviewService,
)
from .ozon_global_rules import OzonGlobalRuleRegistry
from .pilot_readiness import PilotReadinessService
from .pilot_runs import PilotRunService
from .policy_shadow import PolicyShadowService
from .post_execution import PostExecutionService
from .primary_source_intake import PrimarySourceIntake
from .procurement import ProcurementService
from .profit_command import ProfitCommandWorkspace
from .profit_data_remediation import ProfitDataRemediationWorkspace
from .profit_erp_sync import ProfitQualifiedErpSync, connector_from_environment
from .profit_truth_readiness import ProfitTruthReadinessWorkspace
from .providers import (
    ComfyUIProvider,
    FirecrawlProvider,
    N8nProvider,
    OllamaProvider,
    OpenAICompatibleProvider,
)
from .read_only_claims import ReadOnlyClaimService
from .readiness import ExecutionReadinessService, GateReadinessService
from .repository import InMemoryRepository
from .research_inbox import ResearchInboxService
from .scope_grants import ScopeGrantAuthority
from .scoped_accounts_payable import ScopedAccountsPayableWorkspace
from .scoped_batch_opportunity import ScopedBatchOpportunityAuthority
from .scoped_channel_account_authority import (
    AuthenticatedStoreMatrixAuthority,
    ChannelAccountMutationScopeAuthority,
    ScopedChannelAccountAuthorityWorkspace,
)
from .scoped_customer_service import ScopedCustomerServiceWorkspace
from .scoped_delivery_exceptions import ScopedDeliveryExceptionWorkspace
from .scoped_facts import ScopedFactPromotionAuthority
from .scoped_growth_experiments import ScopedGrowthExperimentWorkspace
from .scoped_inventory import ScopedInventoryFulfillmentWorkspace
from .scoped_listing_lifecycle import ScopedListingLifecycleWorkspace
from .scoped_marketplace_catalog import ScopedMarketplaceCatalogAuthority
from .scoped_marketplace_observation import (
    ScopedMarketplaceObservationAuthority,
)
from .scoped_media_factory import ScopedContentMediaFactoryWorkspace
from .scoped_oms import ScopedOmsWorkspace
from .scoped_ozon_imports import ScopedOzonImportAuthority
from .scoped_pim import ScopedPimWorkspace
from .scoped_procurement_receiving import (
    ScopedProcurementReceivingWorkspace,
)
from .scoped_product_content import ScopedProductContentAuthority
from .scoped_profit_ledger import (
    ScopedProfitLedgerAuthority,
    ScopedProfitOrderSkuReceiptAuthority,
)
from .scoped_read_only_claims import ScopedReadOnlyClaimAuthority
from .scoped_read_only_pilots import ScopedReadOnlyPilotAuthority
from .scoped_returns_aftersales import ScopedReturnsAfterSalesWorkspace
from .scoped_seller_erp_bridge import ScopedSellerErpBridge
from .scoped_settlement_cash import ScopedSettlementCashWorkspace
from .scoped_sourcing_intelligence import (
    ScopedSourcingIntelligenceWorkspace,
)
from .scoped_warehouse_fulfillment import (
    ScopedWarehouseFulfillmentWorkspace,
)
from .scoped_worker_credential_grants import CanonicalWorkerCredentialGrantIssuer
from .security import ApiKeyAuthenticator, KillSwitchService
from .seller_operating_system import SellerOperatingSystem
from .services import CommerceService
from .sourcing import SourcingService
from .sourcing_intake import SupplierComparisonIntakeService
from .sourcing_store import SqlSourcingStore
from .sql_repository import SqlAlchemyRepository
from .store_category_strategy import StoreCategoryStrategyWorkspace
from .store_profile_intake import StoreProfileIntake
from .strategic_benchmark import StrategicBenchmarkKernel
from .strategic_capital_dashboard import (
    ClosedLoopEvolutionReadPort,
    PrimarySourceCoverageReadPort,
    RuntimeCurrentScopeAuthority,
    ScopedDashboardCitationAuthority,
    StrategicBenchmarkReadPort,
    StrategicCapitalDashboardRegistry,
    StrategicCapitalDashboardService,
)
from .supplier_quote_authority import SupplierQuoteAuthorityService
from .supplier_rfq import SupplierRfqWorkspace
from .supplier_rfq_dispatch import SupplierRfqDispatchWorkspace
from .team_control_tower import TeamControlTower
from .truth_governance import TruthGovernanceService
from .warehouse_fulfillment import WarehouseExecutionAuthorityService


@dataclass(slots=True)
class RuntimeServices:
    action_authorization: Any
    action_policies: Any
    agent_harness: Any
    agent_inference: Any
    agent_runtime_evidence: Any
    governed_agent_runtime: Any
    ai_listing: Any
    authenticator: Any
    automation: Any
    batch_opportunity: Any
    browser_capture_inbox: Any
    catalog_read_run_handoffs: Any
    scoped_batch_opportunity: Any
    scoped_product_content: Any
    scoped_pim: Any
    scoped_listing_lifecycle: Any
    scoped_media_factory: Any
    scoped_sourcing_intelligence: Any
    scoped_seller_erp_bridge: Any
    scoped_settlement_cash: Any
    scoped_returns_aftersales: Any
    scoped_customer_service: Any
    scoped_delivery_exceptions: Any
    scoped_growth_experiments: Any
    scoped_warehouse_fulfillment: Any
    scoped_channel_account_authority: Any
    scoped_procurement_receiving: Any
    scoped_accounts_payable: Any
    accounts_payable: Any
    customer_service: Any
    warehouse_fulfillment: Any
    channel_account_authority: Any
    channel_account_governance_evidence: Any
    channel_account_governance: Any
    candidate_evidence_authority: Any
    capability_economics: Any
    causal_experiments: Any
    causal_knowledge: Any
    causal_policies: Any
    commerce: Any
    commercial_lifecycle: Any
    commerce_os: Any
    native_parity_acceptance: Any
    content: Any
    cost_evidence_authority: Any
    cross_border_capability_atlas: Any
    decision_contracts: Any
    decision_lifecycle: Any
    demand_reports: Any
    engine: Any
    evidence: Any
    scoped_evidence: Any
    global_data_coverage_evidence_authority_factory: Any
    closed_loop_evidence_authority_factory: Any
    closed_loop_evolution: Any
    evidence_scope_binding: Any
    evidence_integrity: Any
    evidenceops_copilot: Any
    listing_execution_authority: Any
    execution_plans: Any
    facts: Any
    finance: Any
    fx_evidence_intake: Any
    finance_report_reviews: Any
    enterprise_positioning: Any
    global_expert_team: Any
    team_control_tower: Any
    governance: Any
    governance_scope: Any
    image_execution: Any
    imports: Any
    scoped_imports: Any
    scoped_facts: Any
    incident_recovery: Any
    intelligence_source_adapters: Any
    intake: Any
    kill_switch: Any
    limited_executor: Any
    logistics: Any
    logistics_store: Any
    loop_engineering: Any
    market: Any
    marketplace_catalog: Any
    scoped_marketplace_catalog: Any
    marketplace_growth: Any
    marketplace_observation: Any
    market_recon_bundles: Any
    media_connectors: Any
    media_jobs: Any
    editing_blueprint: Any
    scoped_marketplace_observation: Any
    scoped_oms: Any
    scoped_inventory: Any
    media_workbench: Any
    operating_analytics: Any
    operating_gate_observer: Any
    operating_intelligence: Any
    operating_workbench: Any
    operating_workspace: Any
    operations_queue: Any
    outbox: Any
    ozon_accrual_classifications: Any
    ozon_fee_mappings: Any
    ozon_global_rules: Any
    pilot_readiness: Any
    pilot_runs: Any
    scoped_read_only_pilots: Any
    scoped_read_only_claims: Any
    policy_shadow: Any
    post_execution: Any
    portfolio_pilot: Any
    procurement: Any
    profit_ledger: Any
    profit_command: Any
    profit_data_remediation: Any
    profit_erp_sync: Any
    profit_truth_readiness: Any
    product_media: Any
    primary_source_intake: Any
    strategic_benchmark: Any
    strategic_capital_dashboard: Any
    providers: Any
    read_only_claims: Any
    readiness: Any
    repo: Any
    research_inbox: Any
    seller_os: Any
    store_category_strategy: Any
    store_profile_intake: Any
    scope_grants: Any
    sourcing: Any
    sourcing_intake: Any
    sourcing_store: Any
    supplier_quote_authority: Any
    supplier_rfq: Any
    supplier_rfq_dispatch: Any
    truth_governance: Any


def build_repository():
    if os.getenv("KJDS_REPOSITORY", "postgres").lower() == "memory":
        return InMemoryRepository()
    return SqlAlchemyRepository(engine=create_database_engine(runtime_database_url()))


def _build_worker_grant_issuer(engine):
    """Compose the control-plane worker grant authority from the managed lease store.

    Returns ``None`` (fail closed, preserving the pre-BAS-160 behavior) unless a
    channel lease signing key of at least 256 bits is configured.  The issuer
    shares the lease store issuer/key-id namespace with the worker composition
    root so grants issued here redeem there; no provider credential is read.
    """
    signing_key_raw = str(os.getenv("KJDS_CHANNEL_LEASE_SIGNING_KEY", "")).strip()
    signing_key = signing_key_raw.encode("utf-8")
    if len(signing_key) < 32:
        return None
    issuer = str(os.getenv("KJDS_CHANNEL_LEASE_ISSUER", "kjds-managed-store")).strip()
    key_id = str(os.getenv("KJDS_CHANNEL_LEASE_KEY_ID", "lease-kid-1")).strip()
    if not issuer or not key_id:
        return None
    store = SqlManagedCredentialLeaseStore(
        engine=engine,
        issuer=issuer,
        key_id=key_id,
    )
    resolver = SignedManagedCredentialLeaseResolver(
        issuer=issuer,
        key_id=key_id,
        signing_key=signing_key,
        store=store,
    )
    binding_source = SqlManagedCredentialLeaseBindingSource(
        store=store,
        resolver=resolver,
    )
    return CanonicalWorkerCredentialGrantIssuer(
        grant_issuer=issuer,
        grant_key_id=key_id,
        signing_key=signing_key,
        lease_source=binding_source,
    )


def build_global_data_coverage_evidence_authority(
    *,
    evidence: EvidenceService,
    scope_grants: ScopeGrantAuthority,
    intake_authority: Any,
    clock: Any | None = None,
) -> GlobalDataCoverageEvidenceAuthorityAdapter:
    """Compose the issuer only into its purpose-specific intake authority."""
    return create_global_data_coverage_evidence_authority(
        evidence=evidence,
        scope_grants=scope_grants,
        intake_authority=intake_authority,
        clock=clock,
    )


def _build_closed_loop_evidence_authority(
    *, evidence, scope_grants, attestation_authorities, clock=None
):
    engines = {}
    try:
        for purpose in (
            "issuer",
            "experiment",
            "cost",
            "business_outcome",
            "review_event",
        ):
            engines[purpose] = create_closed_loop_database_engine(
                purpose, generic_url=runtime_database_url()
            )
        issuer = ClosedLoopEvidenceIssuerPort(engines["issuer"])
        registrars = {
            purpose: ClosedLoopAuthorityReceiptRegistrarPort(
                purpose_engine, purpose=purpose
            )
            for purpose, purpose_engine in engines.items()
            if purpose != "issuer"
        }
        return ClosedLoopEvidenceAuthorityAdapter(
            evidence,
            scope_grants=scope_grants,
            attestation_authorities=attestation_authorities,
            issuer_port=issuer,
            receipt_registrars=registrars,
            clock=clock,
        )
    except Exception:
        for engine in engines.values():
            engine.dispose()
        raise


def build_runtime() -> RuntimeServices:
    repo = build_repository()
    engine = getattr(repo, "engine", None) or create_database_engine()
    media_connector_contract = MediaConnectorContract()
    media_connectors = MediaConnectorRegistry(
        engine=engine,
        contract=media_connector_contract,
    )
    agent_harness = AgentHarnessService(engine)
    evidence = EvidenceService(engine)
    market_recon_bundles = MarketReconBundleIngestion(
        engine=engine,
        evidence=evidence,
    )
    scope_grants = ScopeGrantAuthority(engine=engine, evidence=evidence)

    def coverage_intake_authority_factory(*, intake_authority, clock=None):
        return build_global_data_coverage_evidence_authority(
            evidence=evidence,
            scope_grants=scope_grants,
            intake_authority=intake_authority,
            clock=clock,
        )

    def closed_loop_evidence_authority_factory(
        *, attestation_authorities, clock=None
    ):
        return _build_closed_loop_evidence_authority(
            evidence=evidence,
            scope_grants=scope_grants,
            attestation_authorities=attestation_authorities,
            clock=clock,
        )

    closed_loop_evolution = GovernedClosedLoopEvolutionWorkspace(
        engine=engine,
        evidence=evidence,
        scope_grants=scope_grants,
        event_evidence_issuer=ClosedLoopEventEvidenceIssuerPort(),
    )

    scoped_evidence = ScopedEvidenceAuthority(evidence=evidence)
    primary_source_intake = PrimarySourceIntake(
        engine=engine,
        evidence=evidence,
        scope_grants=scope_grants,
        scoped_evidence=scoped_evidence,
    )
    strategic_benchmark = StrategicBenchmarkKernel(
        engine=engine,
        evidence=evidence,
        scope_grants=scope_grants,
        scoped_evidence=scoped_evidence,
    )
    strategic_dashboard_registry = StrategicCapitalDashboardRegistry.load()
    strategic_dashboard_citation_authority = ScopedDashboardCitationAuthority(
        sealing_key=os.getenv("KJDS_STRATEGIC_BENCHMARK_SEALING_KEY", "").encode()
    )
    strategic_capital_dashboard = StrategicCapitalDashboardService(
        scope_authority=RuntimeCurrentScopeAuthority(scope_grants=scope_grants),
        section_ports={
            "primary_source_coverage": PrimarySourceCoverageReadPort(
                service=primary_source_intake,
                source_contract=strategic_dashboard_registry.payload[
                    "source_contracts"
                ]["primary_source_coverage"],
                citation_authority=strategic_dashboard_citation_authority,
            ),
            "strategic_benchmark": StrategicBenchmarkReadPort(
                service=strategic_benchmark,
                source_contract=strategic_dashboard_registry.payload[
                    "source_contracts"
                ]["strategic_benchmark"],
            ),
            "verified_outcomes": ClosedLoopEvolutionReadPort(
                service=closed_loop_evolution,
                section_id="verified_outcomes",
                source_contract=strategic_dashboard_registry.payload[
                    "source_contracts"
                ]["verified_outcomes"],
                citation_authority=strategic_dashboard_citation_authority,
            ),
            "invalidation_review": ClosedLoopEvolutionReadPort(
                service=closed_loop_evolution,
                section_id="invalidation_review",
                source_contract=strategic_dashboard_registry.payload[
                    "source_contracts"
                ]["invalidation_review"],
                citation_authority=strategic_dashboard_citation_authority,
            ),
        },
        clock=lambda: datetime.now(UTC),
    )
    evidence_scope_binding = EvidenceScopeBindingService(
        evidence=evidence,
        scoped_evidence=scoped_evidence,
    )
    authenticator = ApiKeyAuthenticator.from_environment()
    channel_account_store_matrix = AuthenticatedStoreMatrixAuthority(
        identity_resolver=authenticator.resolve_actor,
    )
    channel_account_mutation_scope = ChannelAccountMutationScopeAuthority(
        scope_grants=scope_grants,
        store_matrix=channel_account_store_matrix,
    )
    channel_account_adapters = ChannelAccountAdapterRegistry()
    channel_account_governance_evidence = ChannelAccountGovernanceEvidenceAuthority(
        evidence=evidence,
        scope_authority=channel_account_mutation_scope,
    )
    channel_account_authority = ChannelAccountAuthorizationAuthority(
        engine=engine,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
        adapters=channel_account_adapters,
        scope_authority=channel_account_mutation_scope,
    )
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
    commercial_lifecycle = CommercialLifecycleService(engine=engine)
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
    scoped_imports = ScopedOzonImportAuthority(
        engine=engine,
        imports=imports,
        evidence=evidence,
    )
    finance_report_reviews = OzonFinanceReportReviewService(engine=engine, evidence=evidence, imports=imports)
    finance = FinanceService(engine)
    fx_evidence_intake = FxEvidenceIntake()
    profit_erp_sync = ProfitQualifiedErpSync(
        engine=engine,
        evidence=evidence,
        repository=repo,
        connector=connector_from_environment(),
        action_authorization=action_authorization,
    )
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
    scoped_facts = ScopedFactPromotionAuthority(
        engine=engine,
        scoped_imports=scoped_imports,
        scoped_evidence=scoped_evidence,
        finance_review_validator=finance_report_reviews.require_accepted,
        fee_mapping_validator=ozon_fee_mappings.require_mapped,
        accrual_classification_validator=(ozon_accrual_classifications.require_classified),
    )
    scoped_oms = ScopedOmsWorkspace(
        engine=engine,
        evidence=evidence,
    )
    scoped_inventory = ScopedInventoryFulfillmentWorkspace(
        engine=engine,
        evidence=evidence,
        oms=scoped_oms,
    )
    automation = AutomationService(engine, repo, shadow_mode=os.getenv("KJDS_SHADOW_MODE", "true").lower() != "false")
    loop_engineering = LoopEngineeringService()
    enterprise_positioning = EnterprisePositioningAdvisor()
    global_expert_team = GlobalPortfolioOrchestrator()
    enterprise_ai_erp_program = EnterpriseAiErpProgram()
    sourcing_store = SqlSourcingStore(engine)
    logistics_store = SqlLogisticsStore(engine)
    logistics = LogisticsQuoteWorkspace(
        store=logistics_store,
        evidence_validator=evidence.require_valid,
        evidence_linker=evidence.link,
        evidence_resolver=evidence.get,
        fx_evidence_current_validator=evidence.require_current,
        scoped_evidence=scoped_evidence,
    )
    cost_evidence_authority = CostEvidenceAuthorityService(evidence=evidence)
    cross_border_capability_atlas = CrossBorderCapabilityAtlas()
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
    procurement = ProcurementService(
        engine=engine,
        repository=repo,
        sourcing_store=sourcing_store,
        sourcing=sourcing,
        evidence=evidence,
    )
    scoped_procurement_receiving = ScopedProcurementReceivingWorkspace(
        engine=engine,
        procurement=procurement,
        repository=repo,
        sourcing_store=sourcing_store,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
    )
    accounts_payable = AccountsPayableAuthorityService(
        engine=engine,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
    )
    scoped_accounts_payable = ScopedAccountsPayableWorkspace(
        engine=engine,
        accounts_payable=accounts_payable,
        scoped_procurement_receiving=scoped_procurement_receiving,
        finance=finance,
        repository=repo,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
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
        execution_identity_ref=os.getenv("KJDS_OZON_EXECUTION_IDENTITY_REF", "").strip() or None,
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
    channel_account_governance = ChannelAccountGovernanceStateMachine(
        governance_evidence=channel_account_governance_evidence,
        commerce=commerce,
        execution_plans=execution_plans,
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
    scoped_channel_account_authority = ScopedChannelAccountAuthorityWorkspace(
        authority=channel_account_authority,
        adapters=channel_account_adapters,
        scope_grants=scope_grants,
        store_matrix=channel_account_store_matrix,
        runtime_identity=(SqlManagedStoreRuntimeIdentityVerifier(engine=engine)),
    )
    worker_grant_issuer = _build_worker_grant_issuer(engine)
    limited_executor = LimitedExecutorService(
        engine=engine,
        execution_plans=execution_plans,
        evidence=evidence,
        kill_switch=kill_switch,
        enabled=os.getenv("KJDS_LIMITED_EXECUTION_ENABLED", "false").lower() == "true",
        credential_grant_issuer=worker_grant_issuer,
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
    profit_ledger = ScopedProfitLedgerAuthority(
        engine=engine,
        finance=finance,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
    )
    profit_receipt_authority = ScopedProfitOrderSkuReceiptAuthority(
        engine=engine,
        finance=finance,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
    )
    scoped_settlement_cash = ScopedSettlementCashWorkspace(
        finance=finance,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
        profit_ledger=profit_ledger,
        profit_receipt_authority=profit_receipt_authority,
    )
    scoped_returns_aftersales = ScopedReturnsAfterSalesWorkspace(
        oms=scoped_oms,
        finance=scoped_settlement_cash,
    )
    customer_service = CustomerServiceAuthorityService(
        engine=engine,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
    )
    scoped_customer_service = ScopedCustomerServiceWorkspace(
        engine=engine,
        source=customer_service,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
        returns=scoped_returns_aftersales,
        repository=repo,
        action_policies=action_policies,
    )
    operating_intelligence = OperatingIntelligenceService(
        engine=engine,
        profit_ledger=profit_ledger,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
    )
    team_control_tower = TeamControlTower(
        expert_team=global_expert_team,
        operating_tasks=operating_intelligence,
        scoped_evidence=scoped_evidence,
        strategic_benchmark=strategic_benchmark,
        settlement_cash=scoped_settlement_cash,
        enterprise_ai_erp_program=enterprise_ai_erp_program,
    )
    governance_scope = GovernanceScopeAuthority(
        governance=governance,
        execution_plans=execution_plans,
        limited_executor=limited_executor,
        post_execution=post_execution,
        scoped_evidence=scoped_evidence,
    )
    operations_queue = OperationsQueueService(
        engine=engine,
        incidents=incident_recovery,
        limited_executor=limited_executor,
        post_execution=post_execution,
        operating_tasks=operating_intelligence,
        governance_scope=governance_scope,
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
        credential_grant_issuer=worker_grant_issuer,
    )
    scoped_read_only_pilots = ScopedReadOnlyPilotAuthority(
        engine=engine,
        pilots=pilot_readiness,
        pilot_runs=pilot_runs,
        scoped_evidence=scoped_evidence,
    )
    scoped_read_only_claims = ScopedReadOnlyClaimAuthority(
        engine=engine,
        claims=read_only_claims,
        scoped_pilots=scoped_read_only_pilots,
        scoped_evidence=scoped_evidence,
    )
    marketplace_catalog = MarketplaceCatalogWorkspace(
        verified_bundle_loader=pilot_runs.verified_product_response_bundle,
        store=SqlMarketplaceCatalogStore(engine),
        evidence=evidence,
        repository=repo,
    )
    scoped_marketplace_catalog = ScopedMarketplaceCatalogAuthority(
        catalog=marketplace_catalog,
        scoped_evidence=scoped_evidence,
    )
    marketplace_observation = MarketplaceObservationWorkspace(
        engine=engine,
        evidence=evidence,
    )
    intelligence_source_adapters = IntelligenceSourceAdapterRegistry()
    browser_capture_inbox = BrowserCaptureInbox(
        engine=engine,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
        source_adapters=intelligence_source_adapters,
    )
    catalog_read_run_handoffs = CatalogReadRunHandoffService(
        engine=engine,
        pilot_runs=pilot_runs,
        scoped_pilots=scoped_read_only_pilots,
        scoped_catalog=scoped_marketplace_catalog,
        source_adapters=intelligence_source_adapters,
        catalog=marketplace_catalog,
    )
    scoped_marketplace_observation = ScopedMarketplaceObservationAuthority(
        observations=marketplace_observation,
        scoped_evidence=scoped_evidence,
    )
    ozon_global_rules = OzonGlobalRuleRegistry()
    seller_os = SellerOperatingSystem(ozon_rules=ozon_global_rules)
    store_category_strategy = StoreCategoryStrategyWorkspace(
        engine=engine,
        evidence=evidence,
    )
    truth_governance = TruthGovernanceService(
        evidence=evidence,
        rules=ozon_global_rules,
        profit_ledger=profit_ledger,
        governance=governance,
        execution_plans=execution_plans,
        limited_executor=limited_executor,
        post_execution=post_execution,
        kill_switch=kill_switch,
        scope_grants=scope_grants,
        scoped_evidence=scoped_evidence,
        scoped_governance=governance_scope,
    )
    portfolio_pilot = PortfolioPilotWorkspace(
        observations=marketplace_observation,
        marketplace_catalog=marketplace_catalog,
        sourcing=sourcing,
        repository=repo,
        operating_tasks=operating_intelligence,
    )
    batch_opportunity = BatchOpportunityWorkspace(
        engine=engine,
        observations=marketplace_observation,
        evidence=evidence,
        finance=finance,
        repository=repo,
        operating_tasks=operating_intelligence,
        facts=facts,
        ozon_rules=ozon_global_rules,
        seller_os=seller_os,
    )
    media_jobs = GovernedMediaJobWorkspace(
        engine,
        evidence=evidence,
        authority=scope_grants,
        content_assets=repo,
    )
    scoped_product_content = ScopedProductContentAuthority(
        repository=repo,
        scoped_catalog=scoped_marketplace_catalog,
        scoped_evidence=scoped_evidence,
        sourcing=sourcing,
        evidence=evidence,
        media_jobs=media_jobs,
    )
    scoped_pim = ScopedPimWorkspace(
        catalog=scoped_marketplace_catalog,
        product_content=scoped_product_content,
    )
    scoped_listing_lifecycle = ScopedListingLifecycleWorkspace(
        pim=scoped_pim,
        listing_store=sourcing_store,
        scoped_evidence=scoped_evidence,
        evidence=evidence,
        approval_repository=repo,
        execution_plans=execution_plans,
    )
    scoped_growth_experiments = ScopedGrowthExperimentWorkspace(
        pim=scoped_pim,
        listing=scoped_listing_lifecycle,
        inventory=scoped_inventory,
        oms=scoped_oms,
        profit=profit_ledger,
        market=scoped_marketplace_observation,
        customer_service=scoped_customer_service,
    )
    scoped_delivery_exceptions = ScopedDeliveryExceptionWorkspace(
        oms=scoped_oms,
        inventory=scoped_inventory,
        procurement=scoped_procurement_receiving,
        returns=scoped_returns_aftersales,
        customer_service=scoped_customer_service,
        profit=profit_ledger,
    )
    warehouse_fulfillment = WarehouseExecutionAuthorityService(
        engine=engine,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
    )
    scoped_warehouse_fulfillment = ScopedWarehouseFulfillmentWorkspace(
        oms=scoped_oms,
        inventory=scoped_inventory,
        pim=scoped_pim,
        procurement=scoped_procurement_receiving,
        delivery=scoped_delivery_exceptions,
        warehouse_events=warehouse_fulfillment,
    )
    scoped_batch_opportunity = ScopedBatchOpportunityAuthority(
        batch=batch_opportunity,
        scoped_observations=scoped_marketplace_observation,
        scoped_catalog=scoped_marketplace_catalog,
        scoped_evidence=scoped_evidence,
        scoped_product_content=scoped_product_content,
        rules=ozon_global_rules,
    )
    supplier_rfq = SupplierRfqWorkspace(
        marketplace_catalog=marketplace_catalog,
        evidence=evidence,
    )
    supplier_rfq_dispatch = SupplierRfqDispatchWorkspace(
        rfq_packages=supplier_rfq,
        evidence=evidence,
    )
    scoped_sourcing_intelligence = ScopedSourcingIntelligenceWorkspace(
        pim=scoped_pim,
        scoped_batch=scoped_batch_opportunity,
        scoped_evidence=scoped_evidence,
        supplier_rfq=supplier_rfq,
        supplier_rfq_dispatch=supplier_rfq_dispatch,
        supplier_quote_authority=supplier_quote_authority,
    )
    profit_data_remediation = ProfitDataRemediationWorkspace()
    store_profile_intake = StoreProfileIntake()
    profit_command = ProfitCommandWorkspace(
        engine=engine,
        evidence=evidence,
        batch_opportunity=scoped_batch_opportunity,
        profit_ledger=profit_ledger,
        settlement_cash=scoped_settlement_cash,
        inventory=scoped_inventory,
        oms=scoped_oms,
        sourcing=scoped_sourcing_intelligence,
        growth=scoped_growth_experiments,
        store_strategy=store_category_strategy,
        data_remediation=profit_data_remediation,
        store_profile_intake=store_profile_intake,
    )
    profit_truth_readiness = ProfitTruthReadinessWorkspace(engine=engine)
    scoped_seller_erp_bridge = ScopedSellerErpBridge(
        evidence=evidence,
        scoped_evidence=scoped_evidence,
        pim=scoped_pim,
        oms=scoped_oms,
        inventory=scoped_inventory,
    )
    operating_analytics = OperatingAnalyticsService(
        readiness=readiness,
        operating_workbench=operating_workbench,
        marketplace_catalog=marketplace_catalog,
        scoped_marketplace_catalog=scoped_marketplace_catalog,
        marketplace_growth=marketplace_growth,
        supplier_rfq=supplier_rfq,
        supplier_rfq_dispatch=supplier_rfq_dispatch,
        procurement=procurement,
        execution_plans=execution_plans,
        post_execution=post_execution,
        finance=finance,
        product_media=product_media,
    )
    operating_workspace = OperatingWorkspaceService(
        capability_atlas=cross_border_capability_atlas,
        operating_analytics=operating_analytics,
    )
    evidenceops_copilot = EvidenceOpsCopilot(
        operating_analytics=operating_analytics,
        operating_workbench=operating_workbench,
    )
    sourcing_intake = SupplierComparisonIntakeService(
        sourcing=sourcing,
        evidence=evidence,
        quote_authority=supplier_quote_authority,
        logistics=logistics,
        rfq_packages=supplier_rfq,
        rfq_dispatches=supplier_rfq_dispatch,
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
    agent_task_registry = AgentTaskRegistry()
    local_inference = None
    if "ollama" in providers:
        local_profile = agent_task_registry.payload["providers"]["ollama"]
        local_inference = OllamaInferenceAdapter(
            providers["ollama"],
            model=str(local_profile["text_model"]),
            capabilities=set(local_profile["capabilities"]),
            vision_model=str(local_profile.get("vision_model") or ""),
        )
    compat_config = {
        "base_url": os.getenv("KJDS_OPENAI_COMPAT_BASE_URL", "").strip(),
        "api_key": os.getenv("KJDS_OPENAI_COMPAT_API_KEY", "").strip(),
        "text_model": os.getenv("KJDS_OPENAI_COMPAT_TEXT_MODEL", "").strip(),
        "vision_model": os.getenv("KJDS_OPENAI_COMPAT_VISION_MODEL", "").strip(),
    }
    configured_compat_values = [bool(value) for value in compat_config.values()]
    if any(configured_compat_values) and not all(configured_compat_values):
        raise RuntimeError(
            "OpenAI-compatible inference requires base URL, API key, text model, and vision model"
        )
    cloud_inference = None
    if all(configured_compat_values):
        compat_provider = OpenAICompatibleProvider(
            base_url=compat_config["base_url"],
            api_key=compat_config["api_key"],
        )
        providers["openai_compatible"] = compat_provider
        cloud_profile = agent_task_registry.payload["providers"]["openai_compatible"]
        cloud_inference = OpenAICompatibleInferenceAdapter(
            compat_provider,
            text_model=compat_config["text_model"],
            vision_model=compat_config["vision_model"],
            capabilities=set(cloud_profile["capabilities"]),
        )
    ai_listing_enabled = os.getenv("KJDS_AI_LISTING_ENABLED", "false").lower() == "true"
    agent_inference = AgentInferenceService(
        engine=engine,
        evidence=evidence,
        registry=agent_task_registry,
        local_adapter=local_inference,
        cloud_adapter=cloud_inference,
        enabled=ai_listing_enabled,
    )
    governed_runtime_adapters = []
    if local_inference is not None:
        governed_runtime_adapters.append(
            ExistingInferenceRuntimeAdapter(
                local_inference,
                profile=AdapterProfile(
                    name="ollama-local",
                    provider="ollama",
                    model=local_inference.model,
                    capabilities=local_inference.capabilities,
                    estimated_accuracy=Decimal(
                        os.getenv("KJDS_AGENT_LOCAL_ESTIMATED_ACCURACY", "0.75")
                    ),
                    p95_latency_ms=int(
                        os.getenv("KJDS_AGENT_LOCAL_P95_LATENCY_MS", "3000")
                    ),
                    estimated_cost_usd=Decimal(
                        os.getenv("KJDS_AGENT_LOCAL_ESTIMATED_COST_USD", "0.001")
                    ),
                    config_sha256=local_inference.config_sha256,
                ),
            )
        )
    if cloud_inference is not None:
        governed_runtime_adapters.append(
            ExistingInferenceRuntimeAdapter(
                cloud_inference,
                profile=AdapterProfile(
                    name="openai-compatible-cloud",
                    provider="openai_compatible",
                    model=cloud_inference.model,
                    capabilities=cloud_inference.capabilities,
                    estimated_accuracy=Decimal(
                        os.getenv("KJDS_AGENT_CLOUD_ESTIMATED_ACCURACY", "0.92")
                    ),
                    p95_latency_ms=int(
                        os.getenv("KJDS_AGENT_CLOUD_P95_LATENCY_MS", "8000")
                    ),
                    estimated_cost_usd=Decimal(
                        os.getenv("KJDS_AGENT_CLOUD_ESTIMATED_COST_USD", "0.10")
                    ),
                    config_sha256=cloud_inference.config_sha256,
                ),
            )
        )
    agent_runtime_evidence = SqlAgentRuntimeEvidenceLedger(
        engine=engine,
        evidence=evidence,
    )
    governed_agent_runtime = GovernedAgentRuntime(
        governed_runtime_adapters,
        task_registry=agent_task_registry,
        audit_ledger=agent_runtime_evidence,
    )
    ai_listing = AiListingPipeline(
        engine=engine,
        browser_capture_inbox=browser_capture_inbox,
        inference=agent_inference,
        repository=repo,
        sourcing=sourcing,
        sourcing_store=sourcing_store,
        product_media=product_media,
        content=content,
        image_execution=image_execution,
        scoped_product_content=scoped_product_content,
        listing_execution_authority=listing_execution_authority,
        commerce=commerce,
        execution_plans=execution_plans,
        evidence=evidence,
        enabled=ai_listing_enabled,
    )
    media_workbench = MediaWorkbenchService(
        engine=engine,
        repository=repo,
        evidence=evidence,
        image_execution=image_execution,
    )
    ffmpeg_adapter = FfmpegMediaWorker()
    editing_blueprint = GovernedEditingBlueprintWorkspace(
        jobs=media_jobs,
        product_content=scoped_product_content,
        evidence=evidence,
        media_workbench=media_workbench,
        ffmpeg_adapter=ffmpeg_adapter,
        media_connector_contract=media_connector_contract,
    )
    scoped_media_factory = ScopedContentMediaFactoryWorkspace(
        product_content=scoped_product_content,
        media_workbench=media_workbench,
    )
    native_parity_identities = [
        (provider_id, capability_id, "1")
        for provider_id, capability_ids in (CommerceOperatingSystem.BENCHMARK_CAPABILITIES.items())
        for capability_id in capability_ids
    ]
    native_parity_mappings = RegistryMappingAcceptanceRecords(
        native_parity_identities
    )
    native_parity_acceptance = NativeParityAcceptanceWorkspace(
        records=SqlNativeParityAcceptanceRecords(
            engine=engine,
            mappings=native_parity_mappings,
        ),
        external_verifier_ids={
            f"native-parity-{dimension}"
            for dimension in ACCEPTANCE_DIMENSIONS
        },
    )
    commerce_os = CommerceOperatingSystem(
        truth_governance=truth_governance,
        batch_opportunity=scoped_batch_opportunity,
        profit_erp_sync=profit_erp_sync,
        operating_analytics=operating_analytics,
        operating_workbench=operating_workbench,
        media_workbench=scoped_media_factory,
        product_content=scoped_product_content,
        intelligence_source_adapters=intelligence_source_adapters,
        scoped_ozon_imports=scoped_imports,
        scoped_facts=scoped_facts,
        scoped_read_only_pilots=scoped_read_only_pilots,
        scoped_read_only_claims=scoped_read_only_claims,
        native_parity_acceptance=native_parity_acceptance,
    )
    operating_gate_observer = OperatingGateObserverService(
        engine=engine,
        commerce_os=commerce_os,
        scope_grants=scope_grants,
        agent_harness=agent_harness,
        identity_resolver=authenticator.resolve_actor,
    )
    return RuntimeServices(
        action_authorization=action_authorization,
        action_policies=action_policies,
        agent_harness=agent_harness,
        agent_inference=agent_inference,
        agent_runtime_evidence=agent_runtime_evidence,
        governed_agent_runtime=governed_agent_runtime,
        ai_listing=ai_listing,
        authenticator=authenticator,
        automation=automation,
        batch_opportunity=batch_opportunity,
        browser_capture_inbox=browser_capture_inbox,
        catalog_read_run_handoffs=catalog_read_run_handoffs,
        scoped_batch_opportunity=scoped_batch_opportunity,
        scoped_product_content=scoped_product_content,
        scoped_pim=scoped_pim,
        scoped_listing_lifecycle=scoped_listing_lifecycle,
        scoped_media_factory=scoped_media_factory,
        scoped_sourcing_intelligence=scoped_sourcing_intelligence,
        scoped_seller_erp_bridge=scoped_seller_erp_bridge,
        scoped_settlement_cash=scoped_settlement_cash,
        scoped_returns_aftersales=scoped_returns_aftersales,
        scoped_customer_service=scoped_customer_service,
        scoped_delivery_exceptions=scoped_delivery_exceptions,
        scoped_growth_experiments=scoped_growth_experiments,
        scoped_warehouse_fulfillment=scoped_warehouse_fulfillment,
        scoped_channel_account_authority=(scoped_channel_account_authority),
        scoped_procurement_receiving=scoped_procurement_receiving,
        scoped_accounts_payable=scoped_accounts_payable,
        accounts_payable=accounts_payable,
        customer_service=customer_service,
        warehouse_fulfillment=warehouse_fulfillment,
        channel_account_authority=channel_account_authority,
        channel_account_governance_evidence=(channel_account_governance_evidence),
        channel_account_governance=channel_account_governance,
        candidate_evidence_authority=candidate_evidence_authority,
        capability_economics=capability_economics,
        causal_experiments=causal_experiments,
        causal_knowledge=causal_knowledge,
        causal_policies=causal_policies,
        commerce=commerce,
        commercial_lifecycle=commercial_lifecycle,
        commerce_os=commerce_os,
        native_parity_acceptance=native_parity_acceptance,
        content=content,
        cost_evidence_authority=cost_evidence_authority,
        cross_border_capability_atlas=cross_border_capability_atlas,
        decision_contracts=decision_contracts,
        decision_lifecycle=decision_lifecycle,
        demand_reports=demand_reports,
        engine=engine,
        evidence=evidence,
        scoped_evidence=scoped_evidence,
        global_data_coverage_evidence_authority_factory=(
            coverage_intake_authority_factory
        ),
        closed_loop_evidence_authority_factory=(
            closed_loop_evidence_authority_factory
        ),
        closed_loop_evolution=closed_loop_evolution,
        evidence_scope_binding=evidence_scope_binding,
        evidence_integrity=evidence_integrity,
        evidenceops_copilot=evidenceops_copilot,
        listing_execution_authority=listing_execution_authority,
        execution_plans=execution_plans,
        facts=facts,
        finance=finance,
        fx_evidence_intake=fx_evidence_intake,
        finance_report_reviews=finance_report_reviews,
        enterprise_positioning=enterprise_positioning,
        global_expert_team=global_expert_team,
        team_control_tower=team_control_tower,
        governance=governance,
        governance_scope=governance_scope,
        image_execution=image_execution,
        imports=imports,
        scoped_imports=scoped_imports,
        scoped_facts=scoped_facts,
        incident_recovery=incident_recovery,
        intelligence_source_adapters=intelligence_source_adapters,
        intake=intake,
        kill_switch=kill_switch,
        limited_executor=limited_executor,
        logistics=logistics,
        logistics_store=logistics_store,
        loop_engineering=loop_engineering,
        market=market,
        marketplace_catalog=marketplace_catalog,
        scoped_marketplace_catalog=scoped_marketplace_catalog,
        marketplace_growth=marketplace_growth,
        marketplace_observation=marketplace_observation,
        market_recon_bundles=market_recon_bundles,
        media_connectors=media_connectors,
        media_jobs=media_jobs,
        editing_blueprint=editing_blueprint,
        scoped_marketplace_observation=scoped_marketplace_observation,
        scoped_oms=scoped_oms,
        scoped_inventory=scoped_inventory,
        media_workbench=media_workbench,
        operating_analytics=operating_analytics,
        operating_gate_observer=operating_gate_observer,
        operating_intelligence=operating_intelligence,
        operating_workbench=operating_workbench,
        operating_workspace=operating_workspace,
        operations_queue=operations_queue,
        outbox=outbox,
        ozon_accrual_classifications=ozon_accrual_classifications,
        ozon_fee_mappings=ozon_fee_mappings,
        ozon_global_rules=ozon_global_rules,
        pilot_readiness=pilot_readiness,
        pilot_runs=pilot_runs,
        scoped_read_only_pilots=scoped_read_only_pilots,
        scoped_read_only_claims=scoped_read_only_claims,
        policy_shadow=policy_shadow,
        post_execution=post_execution,
        portfolio_pilot=portfolio_pilot,
        procurement=procurement,
        profit_erp_sync=profit_erp_sync,
        profit_truth_readiness=profit_truth_readiness,
        profit_ledger=profit_ledger,
        profit_command=profit_command,
        profit_data_remediation=profit_data_remediation,
        product_media=product_media,
        primary_source_intake=primary_source_intake,
        strategic_benchmark=strategic_benchmark,
        strategic_capital_dashboard=strategic_capital_dashboard,
        providers=providers,
        read_only_claims=read_only_claims,
        readiness=readiness,
        repo=repo,
        research_inbox=research_inbox,
        seller_os=seller_os,
        store_category_strategy=store_category_strategy,
        store_profile_intake=store_profile_intake,
        scope_grants=scope_grants,
        sourcing=sourcing,
        sourcing_intake=sourcing_intake,
        sourcing_store=sourcing_store,
        supplier_quote_authority=supplier_quote_authority,
        supplier_rfq=supplier_rfq,
        supplier_rfq_dispatch=supplier_rfq_dispatch,
        truth_governance=truth_governance,
    )


runtime = build_runtime()
