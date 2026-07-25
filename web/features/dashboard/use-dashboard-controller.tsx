"use client";

import { FormEvent, useCallback, useState } from "react";
import { fetchJson, settleJsonRequests } from "../../lib/fetch-json";
import type { DomainState } from "./domain-status-panel";
import type {
  Health,
  WebSession,
  OzonImportResult,
  OzonImportPreview,
  FinanceReviewStatus,
  CostAuthorityCatalog,
  ActualCostAuthorityStatus,
  FeeCodeStatus,
  AccrualClassificationStatus,
  Recommendation,
  SourceConnector,
  PassportReadiness,
  ProductReadiness,
  ProductMediaReadiness,
  ContentAssetView,
  MarketplaceCatalogItem,
  MarketplaceGrowthObservation,
  MarketplaceGrowthPlan,
  PassportReview,
  ProductIdentity,
  SourcingComparison,
  ApprovalRecord,
  SampleEvent,
  SampleOrder,
  SupplierPerformance,
  BackupOption,
  GateRequirement,
  GateReadiness,
  EvidenceSummary,
  CandidateResearchAssessment,
  CandidateAuthorityStatus,
  CandidateSourcingHandoff,
  InteractionProfile,
  DecisionContract,
  DecisionAnalysis,
  DecisionReview,
  DecisionResolution,
  DecisionOutcome,
  DecisionCalibration,
  CausalExperiment,
  ExperimentEvaluation,
  CausalExperimentReview,
  CausalKnowledgeEntry,
  CausalPolicy,
  PolicyShadowBatch,
  PolicyActivationHandoff,
  GovernedExecutionPlan,
  LimitedExecutionCommand,
  ExecutionObservationWindow,
  CapabilityEconomicAssessment,
  OperationalIncident,
  OperationsQueueItem,
  OperatingWorkbenchBriefing,
  ReadOnlyPilot,
  PilotEvaluation
} from "./contracts";
import {
  passportLabels,
  productMediaRoleLabels,
  candidateMetricDefinitions,
  candidateMetricLabels,
  sourcingCostDefinitions,
  costStateLabels,
  financeReviewRecordTypes,
  imageQaDefinitions,
  procurementStatusLabels,
  procurementEventLabels,
  decisionStatusLabels
} from "./dashboard-config";
import { useDashboardBoot } from "./use-dashboard-boot";

export function useDashboardController() {

  const [webSession, setWebSession] = useState<WebSession | null>(null);
  const [health, setHealth] = useState<Record<string, Health>>({});
  const [operatingWorkbench, setOperatingWorkbench] = useState<OperatingWorkbenchBriefing | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [sourceConnectors, setSourceConnectors] = useState<SourceConnector[]>([]);
  const [offers, setOffers] = useState<unknown[]>([]);
  const [products, setProducts] = useState<ProductIdentity[]>([]);
  const [comparisons, setComparisons] = useState<SourcingComparison[]>([]);
  const [marketplaceCatalogItems, setMarketplaceCatalogItems] = useState<MarketplaceCatalogItem[]>([]);
  const [marketplaceCatalogLoaded, setMarketplaceCatalogLoaded] = useState(false);
  const [marketplaceCatalogBusy, setMarketplaceCatalogBusy] = useState(false);
  const [marketplaceCatalogStoreRef, setMarketplaceCatalogStoreRef] = useState("ozon-primary");
  const [marketplaceGrowthPlan, setMarketplaceGrowthPlan] = useState<MarketplaceGrowthPlan | null>(null);
  const [marketplaceGrowthObservations, setMarketplaceGrowthObservations] = useState<MarketplaceGrowthObservation[]>([]);
  const [marketplaceGrowthFactsLoaded, setMarketplaceGrowthFactsLoaded] = useState(false);
  const [marketplaceGrowthBusy, setMarketplaceGrowthBusy] = useState(false);
  const [approvals, setApprovals] = useState<ApprovalRecord[]>([]);
  const [sampleOrders, setSampleOrders] = useState<SampleOrder[]>([]);
  const [supplierPerformance, setSupplierPerformance] = useState<SupplierPerformance[]>([]);
  const [backupOptions, setBackupOptions] = useState<Record<string, BackupOption[]>>({});
  const [backupRationales, setBackupRationales] = useState<Record<string, string>>({});
  const [skuReadiness, setSkuReadiness] = useState<ProductReadiness[]>([]);
  const [productMediaReadiness, setProductMediaReadiness] = useState<ProductMediaReadiness[]>([]);
  const [contentAssets, setContentAssets] = useState<ContentAssetView[]>([]);
  const [passportReviews, setPassportReviews] = useState<PassportReview[]>([]);
  const [gateReadiness, setGateReadiness] = useState<GateReadiness | null>(null);
  const [evidenceRecords, setEvidenceRecords] = useState<EvidenceSummary[]>([]);
  const [interactionProfiles, setInteractionProfiles] = useState<InteractionProfile[]>([]);
  const [decisionContracts, setDecisionContracts] = useState<DecisionContract[]>([]);
  const [decisionAnalyses, setDecisionAnalyses] = useState<DecisionAnalysis[]>([]);
  const [decisionReviews, setDecisionReviews] = useState<Record<string, DecisionReview[]>>({});
  const [decisionResolutions, setDecisionResolutions] = useState<DecisionResolution[]>([]);
  const [decisionOutcomes, setDecisionOutcomes] = useState<DecisionOutcome[]>([]);
  const [decisionCalibration, setDecisionCalibration] = useState<DecisionCalibration[]>([]);
  const [causalExperiments, setCausalExperiments] = useState<CausalExperiment[]>([]);
  const [experimentEvaluations, setExperimentEvaluations] = useState<Record<string, ExperimentEvaluation>>({});
  const [causalExperimentReviews, setCausalExperimentReviews] = useState<Record<string, CausalExperimentReview[]>>({});
  const [causalKnowledge, setCausalKnowledge] = useState<CausalKnowledgeEntry[]>([]);
  const [causalPolicies, setCausalPolicies] = useState<CausalPolicy[]>([]);
  const [policyShadowBatches, setPolicyShadowBatches] = useState<PolicyShadowBatch[]>([]);
  const [policyActivationHandoffs, setPolicyActivationHandoffs] = useState<PolicyActivationHandoff[]>([]);
  const [governedExecutionPlans, setGovernedExecutionPlans] = useState<GovernedExecutionPlan[]>([]);
  const [limitedExecutionCommands, setLimitedExecutionCommands] = useState<LimitedExecutionCommand[]>([]);
  const [executionObservationWindows, setExecutionObservationWindows] = useState<ExecutionObservationWindow[]>([]);
  const [capabilityEconomicAssessments, setCapabilityEconomicAssessments] = useState<CapabilityEconomicAssessment[]>([]);
  const [operationalIncidents, setOperationalIncidents] = useState<OperationalIncident[]>([]);
  const [operationsQueue, setOperationsQueue] = useState<OperationsQueueItem[]>([]);
  const [readOnlyPilots, setReadOnlyPilots] = useState<ReadOnlyPilot[]>([]);
  const [pilotEvaluations, setPilotEvaluations] = useState<Record<string, PilotEvaluation>>({});
  const [selectedProfileId, setSelectedProfileId] = useState("evidence_research");
  const [selectedAnalysisContractId, setSelectedAnalysisContractId] = useState("");
  const [selectedAnalysisOptionId, setSelectedAnalysisOptionId] = useState("");
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [lifecycleBusy, setLifecycleBusy] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [lastOzonImport, setLastOzonImport] = useState<OzonImportResult | null>(null);
  const [financeReviewStatus, setFinanceReviewStatus] = useState<FinanceReviewStatus | null>(null);
  const [financeReviewImportId, setFinanceReviewImportId] = useState("");
  const [financeReviewBusy, setFinanceReviewBusy] = useState(false);
  const [costAuthorityCatalog, setCostAuthorityCatalog] = useState<CostAuthorityCatalog | null>(null);
  const [actualCostAuthorityStatus, setActualCostAuthorityStatus] = useState<ActualCostAuthorityStatus | null>(null);
  const [actualCostEvidenceId, setActualCostEvidenceId] = useState("");
  const [actualCostType, setActualCostType] = useState("product_cost");
  const [actualCostReviewBusy, setActualCostReviewBusy] = useState(false);
  const [feeCodeStatus, setFeeCodeStatus] = useState<FeeCodeStatus | null>(null);
  const [feeMappingBusy, setFeeMappingBusy] = useState(false);
  const [accrualClassificationStatus, setAccrualClassificationStatus] = useState<AccrualClassificationStatus | null>(null);
  const [accrualClassificationBusy, setAccrualClassificationBusy] = useState(false);
  const [gateUploading, setGateUploading] = useState(false);
  const [candidateEvidenceUploading, setCandidateEvidenceUploading] = useState(false);
  const [candidateAuthorityBusy, setCandidateAuthorityBusy] = useState(false);
  const [candidateAuthorityStatus, setCandidateAuthorityStatus] = useState<CandidateAuthorityStatus | null>(null);
  const [candidateResearchBusy, setCandidateResearchBusy] = useState(false);
  const [candidateAssessment, setCandidateAssessment] = useState<CandidateResearchAssessment | null>(null);
  const [candidateHandoffBusy, setCandidateHandoffBusy] = useState(false);
  const [candidateHandoff, setCandidateHandoff] = useState<CandidateSourcingHandoff | null>(null);
  const [skuUploading, setSkuUploading] = useState(false);
  const [productMediaUploading, setProductMediaUploading] = useState(false);
  const [imageBriefBusy, setImageBriefBusy] = useState(false);
  const [imageExecutionBusy, setImageExecutionBusy] = useState<string | null>(null);
  const [imageQaBusy, setImageQaBusy] = useState<string | null>(null);
  const [listingDraftBusy, setListingDraftBusy] = useState<string | null>(null);
  const [reviewingKey, setReviewingKey] = useState<string | null>(null);
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [sourcingUploading, setSourcingUploading] = useState(false);
  const [procurementDrafts, setProcurementDrafts] = useState<Record<string, { quantity: string; rationale: string }>>({});
  const [procurementBusy, setProcurementBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("正在加载经营事实与 Evidence");
  const [domainStates, setDomainStates] = useState<Record<string, DomainState>>({
    core: "loading", product: "loading", finance: "loading", science: "loading", execution: "loading",
  });

  const load = useCallback(async (signal?: AbortSignal) => {
    setDomainStates({ core: "loading", product: "loading", finance: "loading", science: "loading", execution: "loading" });
    const request = (input: RequestInfo | URL, init: RequestInit = {}) =>
      fetchJson(input, { ...init, signal: signal ?? init.signal });
    const [healthResponse, operatingWorkbenchResponse, recommendationResponse, connectorResponse, offersResponse, productsResponse, gateResponse, reviewResponse, approvalsResponse, sampleOrdersResponse, supplierPerformanceResponse, evidenceResponse, profileResponse, contractResponse, analysisResponse, resolutionResponse, outcomeResponse, calibrationResponse, experimentResponse, causalKnowledgeResponse, causalPolicyResponse, policyShadowResponse, policyHandoffResponse, executionPlanResponse, executionCommandResponse, executionObservationResponse, capabilityEconomicsResponse, operationalIncidentsResponse, operationsQueueResponse, readOnlyPilotsResponse, costAuthorityResponse] = await settleJsonRequests([
      request("/backend/v1/integrations/health", { cache: "no-store" }),
      request("/backend/v1/operating-workbench/briefing", { cache: "no-store" }),
      request("/backend/v1/recommendations", { cache: "no-store" }),
      request("/backend/v1/sourcing/connectors", { cache: "no-store" }),
      request("/backend/v1/sourcing/offers", { cache: "no-store" }),
      request("/backend/v1/products", { cache: "no-store" }),
      request("/backend/v1/operations/readiness", { cache: "no-store" }),
      request("/backend/v1/passport-reviews", { cache: "no-store" }),
      request("/backend/v1/approvals", { cache: "no-store" }),
      request("/backend/v1/procurement/sample-orders", { cache: "no-store" }),
      request("/backend/v1/procurement/suppliers/performance", { cache: "no-store" }),
      request("/backend/v1/evidence", { cache: "no-store" }),
      request("/backend/v1/interaction-profiles", { cache: "no-store" }),
      request("/backend/v1/decision-contracts", { cache: "no-store" }),
      request("/backend/v1/decision-analyses", { cache: "no-store" }),
      request("/backend/v1/decision-resolutions", { cache: "no-store" }),
      request("/backend/v1/decision-outcomes", { cache: "no-store" }),
      request("/backend/v1/decision-calibration", { cache: "no-store" }),
      request("/backend/v1/causal-experiments", { cache: "no-store" }),
      request("/backend/v1/causal-knowledge", { cache: "no-store" }),
      request("/backend/v1/causal-policies", { cache: "no-store" }),
      request("/backend/v1/causal-policy-shadow-batches", { cache: "no-store" }),
      request("/backend/v1/causal-policy-activation-handoffs", { cache: "no-store" }),
      request("/backend/v1/governed-execution-plans", { cache: "no-store" }),
      request("/backend/v1/limited-execution-commands", { cache: "no-store" }),
      request("/backend/v1/execution-observation-windows", { cache: "no-store" }),
      request("/backend/v1/capability-economic-assessments", { cache: "no-store" }),
      request("/backend/v1/operational-incidents", { cache: "no-store" }),
      request("/backend/v1/operations-control/queue", { cache: "no-store" }),
      request("/backend/v1/read-only-pilots", { cache: "no-store" }),
      request("/backend/v1/finance/cost-authorities", { cache: "no-store" }),
    ]);
    setDomainStates({
      core: [healthResponse, operatingWorkbenchResponse].every((response) => response.ok) ? "ready" : "error",
      product: [connectorResponse, offersResponse, productsResponse, gateResponse, reviewResponse, approvalsResponse, sampleOrdersResponse, supplierPerformanceResponse, evidenceResponse].every((response) => response.ok) ? "ready" : "error",
      finance: costAuthorityResponse.ok ? "ready" : "error",
      science: [profileResponse, contractResponse, analysisResponse, resolutionResponse, outcomeResponse, calibrationResponse, experimentResponse, causalKnowledgeResponse, causalPolicyResponse].every((response) => response.ok) ? "ready" : "error",
      execution: [policyShadowResponse, policyHandoffResponse, executionPlanResponse, executionCommandResponse, executionObservationResponse, capabilityEconomicsResponse, operationalIncidentsResponse, operationsQueueResponse, readOnlyPilotsResponse].every((response) => response.ok) ? "ready" : "error",
    });
    if (healthResponse.ok) setHealth(await healthResponse.json());
    if (operatingWorkbenchResponse.ok) setOperatingWorkbench(await operatingWorkbenchResponse.json());
    if (recommendationResponse.ok) setRecommendations(await recommendationResponse.json());
    if (connectorResponse.ok) setSourceConnectors(await connectorResponse.json());
    if (offersResponse.ok) setOffers(await offersResponse.json());
    const gateData: GateReadiness | null = gateResponse.ok ? await gateResponse.json() : null;
    if (gateData) setGateReadiness(gateData);
    if (reviewResponse.ok) setPassportReviews(await reviewResponse.json());
    if (approvalsResponse.ok) setApprovals(await approvalsResponse.json());
    if (sampleOrdersResponse.ok) setSampleOrders(await sampleOrdersResponse.json());
    if (supplierPerformanceResponse.ok) setSupplierPerformance(await supplierPerformanceResponse.json());
    if (evidenceResponse.ok) setEvidenceRecords(await evidenceResponse.json());
    if (costAuthorityResponse.ok) setCostAuthorityCatalog(await costAuthorityResponse.json());
    if (profileResponse.ok) setInteractionProfiles(await profileResponse.json());
    if (contractResponse.ok) setDecisionContracts(await contractResponse.json());
    if (analysisResponse.ok) {
      const rows: DecisionAnalysis[] = await analysisResponse.json();
      setDecisionAnalyses(rows);
      const reviews = await Promise.all(rows.map(async (item) => {
        const response = await request(`/backend/v1/decision-analyses/${item.id}/reviews`, { cache: "no-store" });
        return [item.id, response.ok ? await response.json() as DecisionReview[] : []] as const;
      }));
      setDecisionReviews(Object.fromEntries(reviews));
    }
    if (resolutionResponse.ok) setDecisionResolutions(await resolutionResponse.json());
    if (outcomeResponse.ok) setDecisionOutcomes(await outcomeResponse.json());
    if (calibrationResponse.ok) setDecisionCalibration(await calibrationResponse.json());
    if (experimentResponse.ok) {
      const rows: CausalExperiment[] = await experimentResponse.json();
      setCausalExperiments(rows);
      const evaluations = await Promise.all(rows.map(async (item) => {
        const response = await request(`/backend/v1/causal-experiments/${item.id}/evaluation`, { cache: "no-store" });
        return [item.id, response.ok ? await response.json() as ExperimentEvaluation : null] as const;
      }));
      const indexed: Record<string, ExperimentEvaluation> = {};
      evaluations.forEach(([id, evaluation]) => { if (evaluation) indexed[id] = evaluation; });
      setExperimentEvaluations(indexed);
      const reviews = await Promise.all(rows.map(async (item) => {
        const response = await request(`/backend/v1/causal-experiments/${item.id}/reviews`, { cache: "no-store" });
        return [item.id, response.ok ? await response.json() as CausalExperimentReview[] : []] as const;
      }));
      setCausalExperimentReviews(Object.fromEntries(reviews));
    }
    if (causalKnowledgeResponse.ok) setCausalKnowledge(await causalKnowledgeResponse.json());
    if (causalPolicyResponse.ok) setCausalPolicies(await causalPolicyResponse.json());
    if (policyShadowResponse.ok) setPolicyShadowBatches(await policyShadowResponse.json());
    if (policyHandoffResponse.ok) setPolicyActivationHandoffs(await policyHandoffResponse.json());
    if (executionPlanResponse.ok) setGovernedExecutionPlans(await executionPlanResponse.json());
    if (executionCommandResponse.ok) setLimitedExecutionCommands(await executionCommandResponse.json());
    if (executionObservationResponse.ok) setExecutionObservationWindows(await executionObservationResponse.json());
    if (capabilityEconomicsResponse.ok) setCapabilityEconomicAssessments(await capabilityEconomicsResponse.json());
    if (operationalIncidentsResponse.ok) setOperationalIncidents(await operationalIncidentsResponse.json());
    if (operationsQueueResponse.ok) setOperationsQueue(await operationsQueueResponse.json());
    if (readOnlyPilotsResponse.ok) {
      const rows: ReadOnlyPilot[] = await readOnlyPilotsResponse.json(); setReadOnlyPilots(rows);
      const evaluations = await Promise.all(rows.map(async (item) => { const response = await request(`/backend/v1/read-only-pilots/${item.id}/evaluation`, { cache: "no-store" }); return [item.id, response.ok ? await response.json() as PilotEvaluation : null] as const; }));
      const indexed: Record<string, PilotEvaluation> = {}; evaluations.forEach(([id, evaluation]) => { if (evaluation) indexed[id] = evaluation; }); setPilotEvaluations(indexed);
    }
    if (productsResponse.ok) {
      const products: ProductIdentity[] = await productsResponse.json();
      setProducts(products);
      const candidateProducts = gateData?.candidate_portfolio.rows.map((item) => item.product) ?? [];
      const readiness = await Promise.all(
        candidateProducts.map(async (product) => {
          const response = await request(`/backend/v1/products/${product.id}/readiness`, { cache: "no-store" });
          return response.ok ? response.json() as Promise<ProductReadiness> : null;
        }),
      );
      setSkuReadiness(readiness.filter((item): item is ProductReadiness => item !== null));
      const mediaReadiness = await Promise.all(
        candidateProducts.map(async (product) => {
          const response = await request(`/backend/v1/products/${product.id}/media-readiness`, { cache: "no-store" });
          return response.ok ? response.json() as Promise<ProductMediaReadiness> : null;
        }),
      );
      setProductMediaReadiness(mediaReadiness.filter((item): item is ProductMediaReadiness => item !== null));
      const assetRows = await Promise.all(
        candidateProducts.map(async (product) => {
          const response = await request(`/backend/v1/products/${product.id}/content-assets`, { cache: "no-store" });
          return response.ok ? response.json() as Promise<ContentAssetView[]> : [];
        }),
      );
      setContentAssets(assetRows.flat());
      const comparisonRows = await Promise.all(candidateProducts.map(async (product) => {
        const response = await request(`/backend/v1/sourcing/comparisons/${product.id}`, { cache: "no-store" });
        return response.ok ? response.json() as Promise<SourcingComparison> : null;
      }));
      setComparisons(comparisonRows.filter((item): item is SourcingComparison => item !== null && item.offer_count > 0));
    }
  }, []);

  useDashboardBoot({ load, setSession: setWebSession, setNotice });

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("file") as HTMLInputElement;
    if (!input.files?.[0]) return;
    const file = input.files[0];
    const periodStart = (form.elements.namedItem("report_period_start") as HTMLInputElement).value;
    const periodEnd = (form.elements.namedItem("report_period_end") as HTMLInputElement).value;
    const uploadBody = () => {
      const body = new FormData();
      body.append("file", file);
      body.append("report_period_start", periodStart);
      body.append("report_period_end", periodEnd);
      return body;
    };
    setUploading(true);
    setNotice("正在只读预检 Ozon 原文件…");
    try {
      const preflightResponse = await fetchJson("/backend/v1/imports/ozon/preflight", { method: "POST", body: uploadBody() });
      const preflightResult = await preflightResponse.json();
      if (!preflightResponse.ok) {
        setNotice(preflightResult.detail ?? "原文件预检失败");
        return;
      }
      const preview = preflightResult as OzonImportPreview;
      if (!preview.ready) {
        setNotice(`原文件尚不能导入：缺少 ${preview.missing_columns.join("、")}。请保留原文件，不要手工改列名。`);
        return;
      }
      setNotice(`预检通过：识别为 ${preview.record_type}，共 ${preview.row_count} 行；正在固化原件…`);
      const response = await fetchJson("/backend/v1/imports/ozon", { method: "POST", body: uploadBody() });
      const result = await response.json();
      if (!response.ok) {
        setNotice(result.detail ?? "导入失败");
        return;
      }
      const imported = result as OzonImportResult;
      setLastOzonImport(imported);
      setFinanceReviewImportId(imported.id);
      form.reset();
      if (financeReviewRecordTypes.has(imported.record_type)) {
        await loadFinanceReviewStatus(imported.id);
        setNotice(`财务文件已暂存：${imported.accepted_count} 行可解析，尚未入账；请把导入编号交给另一位复核人。`);
      } else {
        setFinanceReviewStatus(null);
        setNotice(`导入完成：${imported.accepted_count} 行可用，${imported.rejected_count} 行需检查`);
      }
    } catch {
      setNotice("无法连接后端，请检查服务状态");
    } finally {
      setUploading(false);
    }
  }

  async function loadFinanceReviewStatus(importId = financeReviewImportId.trim()) {
    if (!importId) return;
    setFinanceReviewBusy(true);
    try {
      const response = await fetchJson(`/backend/v1/imports/${encodeURIComponent(importId)}/finance-review`, { cache: "no-store" });
      const result = await response.json();
      if (!response.ok) {
        setNotice(result.detail ?? "无法读取财务复核状态");
        return;
      }
      setFinanceReviewImportId(importId);
      setFinanceReviewStatus(result as FinanceReviewStatus);
      if (result.status === "accepted" && result.record_type === "ozon_fee") {
        await loadFeeCodeStatus(importId);
      } else {
        setFeeCodeStatus(null);
      }
      if (result.status === "accepted" && result.record_type === "ozon_accrual") {
        await loadAccrualClassificationStatus(importId);
      } else {
        setAccrualClassificationStatus(null);
      }
      setNotice(result.status === "accepted" ? "来源复核已通过；仍未自动入账，需等待会计字段映射和正式事实晋升。" : result.status === "rejected" ? "来源复核已拒绝，该财务文件保持阻塞。" : "财务文件仍在等待另一身份复核，尚未入账。");
    } catch {
      setNotice("无法连接后端，请检查服务状态");
    } finally {
      setFinanceReviewBusy(false);
    }
  }

  async function reviewFinanceReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const importId = (form.elements.namedItem("finance_review_import_id") as HTMLInputElement).value.trim();
    if (!importId) return;
    const checked = (name: string) => (form.elements.namedItem(name) as HTMLInputElement).checked;
    const accepted = (form.elements.namedItem("finance_review_decision") as HTMLSelectElement).value === "accepted";
    setFinanceReviewBusy(true);
    try {
      const response = await fetchJson(`/backend/v1/imports/${encodeURIComponent(importId)}/finance-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accepted,
          authentic_account_export: checked("authentic_account_export"),
          period_matches: checked("period_matches"),
          not_public_sample: checked("not_public_sample"),
          complete_export: checked("complete_export"),
          rationale: (form.elements.namedItem("finance_review_rationale") as HTMLTextAreaElement).value.trim(),
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        setNotice(result.detail ?? "财务复核提交失败");
        return;
      }
      form.reset();
      setFinanceReviewImportId(importId);
      await loadFinanceReviewStatus(importId);
    } catch {
      setNotice("无法连接后端，请检查服务状态");
    } finally {
      setFinanceReviewBusy(false);
    }
  }

  async function loadActualCostAuthorityStatus(
    evidenceId = actualCostEvidenceId.trim(),
    costType = actualCostType,
  ) {
    if (!evidenceId || !costType) return;
    setActualCostReviewBusy(true);
    try {
      const response = await fetchJson(
        `/backend/v1/finance/cost-evidence/${encodeURIComponent(evidenceId)}/authority-review?cost_type=${encodeURIComponent(costType)}`,
        { cache: "no-store" },
      );
      const result = await response.json();
      if (!response.ok) {
        setActualCostAuthorityStatus(null);
        setNotice(result.detail ?? "无法读取实际成本复核状态");
        return;
      }
      setActualCostAuthorityStatus(result as ActualCostAuthorityStatus);
      setNotice(result.status === "accepted" ? "该原件已通过实际成本权威复核；执行出口仍会重新验证原件和证明。" : result.status === "rejected" ? "该原件已有拒绝结论，不能作为实际成本。" : "该原件尚未获得独立实际成本证明。峰值、报价或估算不会自动转为实际成本。");
    } catch {
      setNotice("无法连接后端，请检查服务状态");
    } finally {
      setActualCostReviewBusy(false);
    }
  }

  async function reviewActualCostAuthority(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value.trim();
    const checked = (name: string) => (form.elements.namedItem(name) as HTMLInputElement).checked;
    const evidenceId = value("actual_cost_evidence_id");
    const costType = value("actual_cost_type");
    setActualCostReviewBusy(true);
    try {
      const response = await fetchJson(`/backend/v1/finance/cost-evidence/${encodeURIComponent(evidenceId)}/authority-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          cost_type: costType,
          authority_id: value("actual_cost_authority_id"),
          accepted: value("actual_cost_decision") === "accepted",
          authentic_original: checked("actual_cost_authentic_original"),
          cost_scope_matches: checked("actual_cost_scope_matches"),
          charging_party_matches: checked("actual_cost_charging_party_matches"),
          amount_currency_period_matches: checked("actual_cost_amount_currency_period_matches"),
          rationale: value("actual_cost_rationale"),
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        setNotice(result.detail ?? "实际成本复核提交失败");
        return;
      }
      setNotice(result.idempotent ? "相同复核记录已存在，没有重复写入。" : "不可变实际成本复核记录已保存；没有自动改场景、入账、采购或上架。");
      await loadActualCostAuthorityStatus(evidenceId, costType);
    } catch {
      setNotice("无法连接后端，请检查服务状态");
    } finally {
      setActualCostReviewBusy(false);
    }
  }

  async function loadFeeCodeStatus(importId = financeReviewImportId.trim()) {
    if (!importId) return;
    const response = await fetchJson(`/backend/v1/imports/${encodeURIComponent(importId)}/fee-codes`, { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) {
      setFeeCodeStatus(null);
      setNotice(result.detail ?? "无法读取费用代码状态");
      return;
    }
    setFeeCodeStatus(result as FeeCodeStatus);
  }

  async function approveFeeMapping(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const importId = financeReviewImportId.trim();
    if (!importId) return;
    const until = (form.elements.namedItem("fee_effective_until") as HTMLInputElement).value;
    setFeeMappingBusy(true);
    try {
      const response = await fetchJson(`/backend/v1/imports/${encodeURIComponent(importId)}/fee-mappings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          raw_code: (form.elements.namedItem("fee_raw_code") as HTMLSelectElement).value,
          canonical_type: (form.elements.namedItem("fee_canonical_type") as HTMLSelectElement).value,
          sign_rule: (form.elements.namedItem("fee_sign_rule") as HTMLSelectElement).value,
          effective_from: new Date((form.elements.namedItem("fee_effective_from") as HTMLInputElement).value).toISOString(),
          effective_until: until ? new Date(until).toISOString() : null,
          rationale: (form.elements.namedItem("fee_mapping_rationale") as HTMLTextAreaElement).value.trim(),
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        setNotice(result.detail ?? "费用代码批准失败");
        return;
      }
      form.reset();
      await loadFeeCodeStatus(importId);
      setNotice(`费用代码 ${result.mapping.raw_code} 的版本化映射已批准；仍未自动入账。`);
    } catch {
      setNotice("无法连接后端，请检查服务状态");
    } finally {
      setFeeMappingBusy(false);
    }
  }

  async function loadAccrualClassificationStatus(importId = financeReviewImportId.trim()) {
    if (!importId) return;
    const response = await fetchJson(`/backend/v1/imports/${encodeURIComponent(importId)}/accrual-classifications`, { cache: "no-store" });
    const result = await response.json();
    if (!response.ok) {
      setAccrualClassificationStatus(null);
      setNotice(result.detail ?? "无法读取应计分类状态");
      return;
    }
    setAccrualClassificationStatus(result as AccrualClassificationStatus);
  }

  async function approveAccrualClassification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const importId = financeReviewImportId.trim();
    if (!importId) return;
    const [accrualGroup, accrualType] = JSON.parse(
      (form.elements.namedItem("accrual_pair") as HTMLSelectElement).value,
    ) as [string, string];
    const until = (form.elements.namedItem("accrual_effective_until") as HTMLInputElement).value;
    setAccrualClassificationBusy(true);
    try {
      const response = await fetchJson(`/backend/v1/imports/${encodeURIComponent(importId)}/accrual-classifications`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          accrual_group: accrualGroup,
          accrual_type: accrualType,
          accounting_class: (form.elements.namedItem("accrual_accounting_class") as HTMLSelectElement).value,
          expected_sign: (form.elements.namedItem("accrual_expected_sign") as HTMLSelectElement).value,
          effective_from: new Date((form.elements.namedItem("accrual_effective_from") as HTMLInputElement).value).toISOString(),
          effective_until: until ? new Date(until).toISOString() : null,
          rationale: (form.elements.namedItem("accrual_classification_rationale") as HTMLTextAreaElement).value.trim(),
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        setNotice(result.detail ?? "应计分类批准失败");
        return;
      }
      form.reset();
      await loadAccrualClassificationStatus(importId);
      setNotice("应计组合的版本化控制分类已批准；仍不会生成财务分录或替代订单收入。");
    } catch {
      setNotice("无法连接后端，请检查服务状态");
    } finally {
      setAccrualClassificationBusy(false);
    }
  }

  async function uploadGateEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = (form.elements.namedItem("gate_file") as HTMLInputElement).files?.[0];
    const requirement = (form.elements.namedItem("requirement_id") as HTMLSelectElement).value;
    if (!file || !requirement) return;
    setGateUploading(true);
    setNotice("正在固化并校验阶段门证据…");
    const body = new FormData();
    body.append("file", file);
    body.append("requirement_id", requirement);
    body.append("effective_at", new Date().toISOString());
    try {
      const response = await fetchJson("/backend/v1/operations/gate-evidence", { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${requirement} 证据已固化并进入阶段门` : result.detail ?? "证据提交失败");
      if (response.ok) {
        form.reset();
        await load();
      }
    } catch {
      setNotice("无法提交阶段门证据，请检查服务状态");
    } finally {
      setGateUploading(false);
    }
  }

  async function uploadDemandReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = (form.elements.namedItem("demand_report_file") as HTMLInputElement).files?.[0];
    const windowDays = (form.elements.namedItem("demand_report_window_days") as HTMLInputElement).value;
    const sourceSystem = (form.elements.namedItem("demand_report_source_system") as HTMLSelectElement).value;
    const sourceLocator = (form.elements.namedItem("demand_report_source_locator") as HTMLInputElement).value;
    if (!file) return;
    setGateUploading(true);
    setNotice("正在固化需求研究原件…");
    const body = new FormData();
    body.append("file", file);
    body.append("requirement_id", "SKU-000");
    body.append("effective_at", new Date().toISOString());
    body.append("source_system", sourceSystem);
    body.append("source_locator", sourceLocator);
    body.append("report_window_days", windowDays);
    try {
      const response = await fetchJson("/backend/v1/operations/gate-evidence", { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? "SKU-000 研究原件已固化并进入待复核；研究与真实执行将按来源组合分别判定。" : result.detail ?? "需求报告提交失败");
      if (response.ok) {
        form.reset();
        await load();
      }
    } catch {
      setNotice("无法提交需求报告，请检查服务状态");
    } finally {
      setGateUploading(false);
    }
  }

  async function reviewDemandReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const reportEvidenceId = (form.elements.namedItem("demand_report_evidence_id") as HTMLSelectElement).value;
    const accepted = (form.elements.namedItem("demand_report_decision") as HTMLSelectElement).value === "accepted";
    const rationale = (form.elements.namedItem("demand_report_rationale") as HTMLInputElement).value.trim();
    if (!reportEvidenceId || !rationale) return;
    setLifecycleBusy("demand-report-review");
    setNotice("正在固化独立复核结论…");
    try {
      const response = await fetchJson("/backend/v1/operations/demand-report-review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report_evidence_id: reportEvidenceId, accepted, rationale }),
      });
      const result = await response.json();
      setNotice(response.ok ? `独立复核已固化：${accepted ? "接受" : "拒绝"}；历史结论不可覆盖。` : result.detail ?? "复核失败");
      if (response.ok) { form.reset(); await load(); }
    } catch {
      setNotice("无法完成独立复核，请确认当前身份与上传者不同");
    } finally {
      setLifecycleBusy(null);
    }
  }

  async function uploadCandidateEvidence(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = (form.elements.namedItem("candidate_evidence_file") as HTMLInputElement).files?.[0];
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value.trim();
    if (!file) return;
    setCandidateEvidenceUploading(true);
    setNotice("正在固化候选研究原件…");
    const body = new FormData();
    body.append("file", file);
    body.append("provider", value("candidate_evidence_source"));
    body.append("provider_record_id", value("candidate_evidence_source_ref"));
    body.append("source_url", value("candidate_evidence_source_url"));
    body.append("observed_at", new Date().toISOString());
    body.append("declared_grade", value("candidate_evidence_grade"));
    body.append("license_status", value("candidate_evidence_license_status"));
    body.append("raw_fields_json", value("candidate_evidence_raw_fields") || "{}");
    body.append("candidate_refs_json", JSON.stringify(value("candidate_evidence_candidate_refs").split(/[\s,]+/).filter(Boolean)));
    try {
      const response = await fetchJson("/backend/v1/market/research-signals", { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `研究信号已固化：${result.evidence.id}；只作为辅助资料，尚未通过独立权威复核。` : result.detail ?? "研究信号固化失败");
      if (response.ok) { form.reset(); await load(); }
    } catch {
      setNotice("无法固化候选原件，请检查服务状态");
    } finally {
      setCandidateEvidenceUploading(false);
    }
  }

  async function loadCandidateAuthorityStatus(evidenceId: string, metric: string) {
    if (!evidenceId || !metric) return;
    setCandidateAuthorityBusy(true);
    try {
      const response = await fetchJson(`/backend/v1/market/candidate-evidence/${encodeURIComponent(evidenceId)}/authority-review?metric=${encodeURIComponent(metric)}`, { cache: "no-store" });
      const result = await response.json();
      if (!response.ok) {
        setCandidateAuthorityStatus(null);
        setNotice(result.detail ?? "无法读取候选证据复核状态");
        return;
      }
      setCandidateAuthorityStatus(result as CandidateAuthorityStatus);
      setNotice(`复核状态：${result.status}；已记录 ${result.review_count} 条不可变结论。`);
    } catch {
      setNotice("无法读取候选证据复核状态，请检查服务状态");
    } finally {
      setCandidateAuthorityBusy(false);
    }
  }

  async function reviewCandidateEvidenceAuthority(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value.trim();
    const evidenceId = value("candidate_authority_evidence_id");
    const metric = value("candidate_authority_metric");
    const accepted = value("candidate_authority_decision") === "accepted";
    setCandidateAuthorityBusy(true);
    setNotice("正在固化候选证据独立权威复核…");
    try {
      const response = await fetchJson(`/backend/v1/market/candidate-evidence/${encodeURIComponent(evidenceId)}/authority-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          metric,
          approved_grade: value("candidate_authority_grade"),
          accepted,
          authentic_original: (form.elements.namedItem("candidate_authority_authentic") as HTMLInputElement).checked,
          source_scope_matches: (form.elements.namedItem("candidate_authority_scope") as HTMLInputElement).checked,
          authority_basis_verified: (form.elements.namedItem("candidate_authority_basis") as HTMLInputElement).checked,
          rationale: value("candidate_authority_rationale"),
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        setNotice(result.detail ?? "候选证据权威复核失败");
        return;
      }
      await loadCandidateAuthorityStatus(evidenceId, metric);
      setNotice(`独立复核已固化：${accepted ? "接受" : "拒绝"}；原件自报等级未被修改。`);
    } catch {
      setNotice("无法完成独立复核，请确认复核人与上传人是不同身份");
    } finally {
      setCandidateAuthorityBusy(false);
    }
  }

  async function submitCandidateResearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement).value.trim();
    const observations = candidateMetricDefinitions.map(([metric]) => ({
      metric,
      value: value(`candidate_${metric}_value`),
      confidence: value(`candidate_${metric}_confidence`),
      evidence_id: value(`candidate_${metric}_evidence`),
      window_days: Number(value(`candidate_${metric}_window_days`)),
      sample_size: Number(value(`candidate_${metric}_sample_size`)),
    }));
    setCandidateResearchBusy(true);
    setCandidateAssessment(null);
    setCandidateHandoff(null);
    setNotice("正在复验五类原件并执行候选预检…");
    try {
      const response = await fetchJson("/backend/v1/market/candidates/intake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidate_ref: value("candidate_ref"),
          candidate_name: value("candidate_name"),
          market: value("candidate_market"),
          category: value("candidate_category"),
          as_of: new Date().toISOString(),
          demand_report_evidence_id: value("candidate_demand_report_evidence_id"),
          observations,
        }),
      });
      const result = await response.json();
      if (response.ok) {
        setCandidateAssessment(result);
        const message = result.decision === "request_three_quotes"
          ? "预检通过：下一步收集三家真实报价"
          : result.decision === "reject" ? "候选已因合规红线淘汰" : "候选仍需补充或更新证据";
        setNotice(message);
      } else {
        setNotice(typeof result.detail === "string" ? result.detail : "候选预检失败，请检查五类输入");
      }
    } catch {
      setNotice("无法执行候选预检，请检查服务状态");
    } finally {
      setCandidateResearchBusy(false);
    }
  }

  async function createCandidateSourcingWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!candidateAssessment || candidateAssessment.decision !== "request_three_quotes") return;
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement).value.trim();
    setCandidateHandoffBusy(true);
    setNotice("正在复验证据并建立报价工作区…");
    try {
      const response = await fetchJson("/backend/v1/market/candidates/sourcing-handoff", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          candidate_ref: candidateAssessment.candidate_ref,
          candidate_name: candidateAssessment.candidate_name,
          market: candidateAssessment.market,
          category: candidateAssessment.category,
          as_of: new Date().toISOString(),
          demand_report_evidence_id: candidateAssessment.demand_report_evidence_id,
          sku: value("candidate_handoff_sku"),
          confirmed: (form.elements.namedItem("candidate_handoff_confirmed") as HTMLInputElement).checked,
        }),
      });
      const result = await response.json();
      if (response.ok) {
        setCandidateHandoff(result);
        setNotice(result.created ? "报价工作区已建立，请录入三家真实报价" : "已有同一报价工作区，已安全复用");
        await load();
      } else {
        setNotice(typeof result.detail === "string" ? result.detail : "报价工作区建立失败");
      }
    } catch {
      setNotice("无法建立报价工作区，请检查服务状态");
    } finally {
      setCandidateHandoffBusy(false);
    }
  }

  async function uploadSkuEpisode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement).value.trim();
    const lines = (name: string) => value(name).split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    const file = (name: string) => (form.elements.namedItem(name) as HTMLInputElement).files?.[0];
    const productEvidence = file("product_evidence");
    const complianceEvidence = file("compliance_evidence");
    const qualityEvidence = file("quality_evidence");
    if (!productEvidence || !complianceEvidence || !qualityEvidence) return;
    const productFacts = {
      decision: "draft",
      material: value("material"), intended_use: value("intended_use"), country_of_origin: value("country_of_origin"),
      weight_kg: value("weight_kg"),
      dimensions_cm: { length: value("length_cm"), width: value("width_cm"), height: value("height_cm") },
    };
    const complianceFacts = {
      decision: "draft", hs_code: value("hs_code"), eaeu_rules: lines("eaeu_rules"),
      eac_requirement: value("eac_requirement"), chestny_znak_requirement: value("chestny_znak_requirement"),
      russian_labeling: value("russian_labeling"), ip_status: value("ip_status"),
      transport_restrictions: value("transport_restrictions"), sellability: value("sellability"),
    };
    const qualityFacts = {
      decision: "draft", golden_sample_ref: value("golden_sample_ref"),
      inspection_plan: lines("inspection_plan"), packaging_test: value("packaging_test"),
    };
    const body = new FormData();
    body.append("sku", value("sku")); body.append("name", value("product_name"));
    body.append("effective_at", new Date().toISOString());
    body.append("product_facts_json", JSON.stringify(productFacts));
    body.append("compliance_facts_json", JSON.stringify(complianceFacts));
    body.append("quality_facts_json", JSON.stringify(qualityFacts));
    body.append("product_evidence", productEvidence); body.append("compliance_evidence", complianceEvidence);
    body.append("quality_evidence", qualityEvidence);
    setSkuUploading(true);
    setNotice("正在建立 SKU、三类 Passport 与证据血缘…");
    try {
      const response = await fetchJson("/backend/v1/intake/sku-episodes", { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${result.product.sku} 已建立，等待三类 Passport 人工复核` : result.detail ?? "SKU 录入失败");
      if (response.ok) { form.reset(); await load(); }
    } catch {
      setNotice("无法提交 SKU Episode，请检查服务状态");
    } finally {
      setSkuUploading(false);
    }
  }

  async function uploadProductMedia(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement).value.trim();
    const image = (form.elements.namedItem("product_media_image") as HTMLInputElement).files?.[0];
    const rights = (form.elements.namedItem("product_media_rights") as HTMLInputElement).files?.[0];
    const productId = value("product_media_product_id");
    if (!image || !rights || !productId) return;
    const body = new FormData();
    body.append("variant_id", value("product_media_variant_id"));
    body.append("asset_role", value("product_media_role"));
    body.append("source_kind", value("product_media_source_kind"));
    body.append("source_ref", value("product_media_source_ref"));
    body.append("effective_at", new Date().toISOString());
    body.append("image", image);
    body.append("rights_file", rights);
    setProductMediaUploading(true);
    setNotice("正在校验原图与权利文件，并追加 Quality Passport 草稿…");
    try {
      const response = await fetchJson(`/backend/v1/products/${productId}/media-evidence`, { method: "POST", body });
      const result = await response.json();
      setNotice(
        response.ok
          ? `${result.product.sku} · ${productMediaRoleLabels[value("product_media_role")]} 已固化，等待 Passport 人工批准`
          : result.detail ?? "商品图片证据提交失败",
      );
      if (response.ok) { form.reset(); await load(); }
    } catch {
      setNotice("无法提交商品图片证据，请检查服务状态");
    } finally {
      setProductMediaUploading(false);
    }
  }

  async function createImageBrief(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement).value.trim();
    const readiness = productMediaReadiness.find((item) => item.product.id === value("image_brief_product_id"));
    const role = readiness?.roles.find((item) => item.role === value("image_brief_role"));
    if (
      !readiness?.ready_for_full_production
      || role?.status !== "approved"
      || !role.source_asset_evidence_id
      || !role.rights_evidence_id
    ) {
      setNotice("必须先让七类真实素材与权利证据全部通过 Passport 审核");
      return;
    }
    setImageBriefBusy(true);
    setNotice("正在冻结商品事实、原图与权利证据，建立受控图片 Brief…");
    try {
      const response = await fetchJson("/backend/v1/content/assets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: readiness.product.id,
          content_type: "image",
          locale: "ru-RU",
          channel: "OZON",
          brief: {
            goal: value("image_brief_goal"),
            generation_mode: value("image_brief_mode"),
            preserve_product_facts: true,
            source_asset_evidence_ids: [role.source_asset_evidence_id],
            rights_evidence_ids: [role.rights_evidence_id],
          },
        }),
      });
      const result = await response.json();
      setNotice(
        response.ok
          ? `${readiness.product.sku} 图片 Brief ${result.id} 已冻结；保真精修可在执行队列中提交`
          : result.detail ?? "图片 Brief 建立失败",
      );
      if (response.ok) { form.reset(); await load(); }
    } catch {
      setNotice("无法建立图片 Brief，请检查服务状态");
    } finally {
      setImageBriefBusy(false);
    }
  }

  async function runImageGeneration(asset: ContentAssetView, action: "queue" | "sync") {
    setImageExecutionBusy(asset.id);
    setNotice(action === "queue" ? "正在提交固定保真工作流…" : "正在同步 ComfyUI 执行结果…");
    const endpoint = action === "queue"
      ? `/backend/v1/content/assets/${asset.id}/generation`
      : `/backend/v1/content/assets/${asset.id}/generation/sync`;
    try {
      const response = await fetchJson(endpoint, { method: "POST" });
      const result = await response.json();
      const promptId = String(result.generation?.prompt_id ?? "");
      setNotice(
        response.ok
          ? action === "queue"
            ? `已进入 ComfyUI 队列${promptId ? ` · ${promptId}` : ""}`
            : result.status === "generated"
              ? `结果已回收为不可变证据 · ${result.artifact_ref}`
              : result.status === "execution_failed"
                ? `执行失败并已关闭 · ${result.generation?.failure_code ?? "unknown"}`
                : "任务仍在执行，可稍后再次同步"
          : result.detail ?? "图片执行操作失败",
      );
      if (response.ok) await load();
    } catch {
      setNotice("无法连接图片执行服务，请检查 KJDS 与 ComfyUI 状态");
    } finally {
      setImageExecutionBusy(null);
    }
  }

  async function reviewImageAsset(event: FormEvent<HTMLFormElement>, asset: ContentAssetView) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const checks = imageQaDefinitions.map(([check]) => ({
      check,
      passed: data.get(`qa_${check}_passed`) === "true",
      notes: String(data.get(`qa_${check}_notes`) ?? "").trim(),
      evidence_ids: [],
    }));
    if (checks.some((item) => !item.notes)) {
      setNotice("八项图片 QA 都必须填写人工判断依据");
      return;
    }
    setImageQaBusy(asset.id);
    setNotice("正在记录八项图片 QA 与可信审核身份…");
    try {
      const response = await fetchJson(`/backend/v1/content/assets/${asset.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checks }),
      });
      const result = await response.json();
      setNotice(
        response.ok
          ? result.status === "approved"
            ? "图片已通过八项 QA，可作为 Listing 草稿素材；仍不会自动上架"
            : "图片未通过 QA，已退回内容队列"
          : result.detail ?? "图片 QA 提交失败",
      );
      if (response.ok) await load();
    } catch {
      setNotice("无法提交图片 QA，请检查服务状态");
    } finally {
      setImageQaBusy(null);
    }
  }

  async function createListingDraft(event: FormEvent<HTMLFormElement>, asset: ContentAssetView) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const [offerId, scenarioId] = String(data.get("listing_scenario") ?? "").split("::");
    if (!offerId || !scenarioId || !asset.artifact_ref) {
      setNotice("Listing 草稿需要已批准图片和正 CM3 利润场景");
      return;
    }
    setListingDraftBusy(asset.id);
    setNotice("正在建立仅供审批的 Ozon Listing 草稿…");
    try {
      const response = await fetchJson("/backend/v1/listings/ozon/drafts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: asset.product_id,
          offer_id: offerId,
          scenario_id: scenarioId,
          content_asset_ids: [asset.id],
          listing_data: {
            title: String(data.get("listing_title") ?? "").trim(),
            description: String(data.get("listing_description") ?? "").trim(),
            category_id: String(data.get("listing_category_id") ?? "").trim(),
            attributes: {},
            images: [asset.artifact_ref],
          },
        }),
      });
      const result = await response.json();
      setNotice(
        response.ok
          ? `Listing 草稿 ${result.draft.id} 已建立，发布审批 ${result.approval.id} 待人工处理；平台未发生写入`
          : result.detail ?? "Listing 草稿建立失败",
      );
      if (response.ok) { form.reset(); await load(); }
    } catch {
      setNotice("无法建立 Listing 草稿，请检查服务状态");
    } finally {
      setListingDraftBusy(null);
    }
  }

  async function reviewPassport(item: PassportReview, decision: "approved" | "blocked") {
    const key = item.passport.id;
    const notes = (reviewNotes[key] ?? "").trim();
    if (decision === "blocked" && !notes) {
      setNotice("阻断 Passport 必须填写明确原因");
      return;
    }
    setReviewingKey(key);
    setNotice(`正在记录 ${item.product.sku} 的人工审核结论…`);
    try {
      const response = await fetchJson(
        `/backend/v1/products/${item.product.id}/passports/${item.passport.kind}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_version: item.passport.version, decision, review_notes: notes }),
        },
      );
      const result = await response.json();
      setNotice(response.ok ? `${item.product.sku} · ${passportLabels[item.passport.kind]} 已${decision === "approved" ? "批准" : "阻断"}` : result.detail ?? "审核提交失败");
      if (response.ok) await load();
    } catch {
      setNotice("无法提交审核结论，请检查服务状态");
    } finally {
      setReviewingKey(null);
    }
  }

  async function uploadSupplierComparison(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement).value.trim();
    const file = (name: string) => (form.elements.namedItem(name) as HTMLInputElement).files?.[0];
    const evidenceFiles = [1, 2, 3].map((index) => file(`supplier_evidence_${index}`));
    const assumptions = file("assumption_evidence");
    if (evidenceFiles.some((item) => !item) || !assumptions) return;
    const offerRows = [1, 2, 3].map((index) => ({
      supplier_ref: value(`supplier_ref_${index}`), platform: value(`platform_${index}`), external_id: value(`external_id_${index}`),
      source_url: value(`source_url_${index}`), title: value(`offer_title_${index}`), currency: value(`currency_${index}`),
      unit_price: value(`unit_price_${index}`), source_to_cny_rate: value(`source_to_cny_rate_${index}`),
      min_order_quantity: Number(value(`moq_${index}`)), weight_kg: value(`supplier_weight_${index}`),
      length_cm: value(`supplier_length_${index}`), width_cm: value(`supplier_width_${index}`), height_cm: value(`supplier_height_${index}`),
      domestic_logistics_per_unit: value(`domestic_logistics_${index}`), attributes: {}, media: [],
    }));
    const profitInputs = {
      sale_price_rub: value("sale_price_rub"), rub_per_cny: value("rub_per_cny"),
      international_freight_cny_per_kg: value("international_freight"), packaging_cny: value("packaging_cny"),
      last_mile_cny: value("last_mile_cny"), customs_rate: value("customs_rate"), platform_fee_rate: value("platform_fee_rate"),
      advertising_rate: value("advertising_rate"), return_reserve_rate: value("return_reserve_rate"),
      warehousing_cny: value("warehousing_cny"), tax_cny: value("tax_cny"), fx_cost_cny: value("fx_cost_cny"),
      capital_cost_cny: value("capital_cost_cny"), aftersales_cny: value("aftersales_cny"), loss_reserve_cny: value("loss_reserve_cny"),
      other_cost_cny: value("other_cost_cny"), template_id: "ozon-ru-full-cost-v1",
      cost_states: Object.fromEntries(sourcingCostDefinitions.map(([key]) => [key, value(`cost_state_${key}`)])),
    };
    const body = new FormData();
    body.append("product_id", value("sourcing_product_id")); body.append("effective_at", new Date().toISOString());
    body.append("offers_json", JSON.stringify(offerRows)); body.append("profit_inputs_json", JSON.stringify(profitInputs));
    evidenceFiles.forEach((item, index) => body.append(`offer_evidence_${index + 1}`, item as File));
    body.append("assumption_evidence", assumptions);
    setSourcingUploading(true); setNotice("正在固化三家报价并计算可比 CM3…");
    try {
      const response = await fetchJson("/backend/v1/sourcing/comparison-intake", { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${result.comparison.product.sku} 已完成三家证据化报价比较` : result.detail ?? "报价比较录入失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法提交供应商比较，请检查服务状态"); }
    finally { setSourcingUploading(false); }
  }

  const loadMarketplaceCatalog = useCallback(async (storeRef?: string) => {
    const scope = (storeRef ?? marketplaceCatalogStoreRef).trim();
    if (!scope) return;
    setMarketplaceCatalogBusy(true);
    try {
      const response = await fetchJson(
        `/backend/v1/marketplace-catalog/items/latest?store_ref=${encodeURIComponent(scope)}&limit=100`,
        { cache: "no-store" },
      );
      const result = await response.json();
      if (!response.ok) {
        setMarketplaceCatalogItems([]);
        setNotice(result.detail ?? "无法读取 Ozon 商品目录");
        return;
      }
      setMarketplaceCatalogStoreRef(scope);
      const items = result as MarketplaceCatalogItem[];
      setMarketplaceCatalogItems(items);
      if (items.length) {
        setNotice(`已加载 ${items.length} 个真实 Ozon 目录条目；媒体仍是未核权外部引用`);
      }
    } catch {
      setMarketplaceCatalogItems([]);
      setNotice("无法连接商品目录服务，请稍后重试");
    } finally {
      setMarketplaceCatalogLoaded(true);
      setMarketplaceCatalogBusy(false);
    }
  }, [marketplaceCatalogStoreRef]);

  async function importMarketplaceCatalog(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const storeRef = (form.elements.namedItem("catalog_store_ref") as HTMLInputElement).value.trim();
    const idempotencyKey = (form.elements.namedItem("catalog_idempotency_key") as HTMLInputElement).value.trim();
    const evidenceSelect = form.elements.namedItem("catalog_evidence_ids") as HTMLSelectElement;
    const evidenceIds = Array.from(evidenceSelect.selectedOptions).map((option) => option.value);
    if (!evidenceIds.length) {
      setNotice("请选择至少一份已验证的 Ozon 原始响应 Evidence");
      return;
    }
    setMarketplaceCatalogBusy(true);
    try {
      const response = await fetchJson("/backend/v1/marketplace-catalog/ozon/import-evidence", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          evidence_ids: evidenceIds,
          store_ref: storeRef,
          idempotency_key: idempotencyKey,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        setNotice(result.detail ?? "Ozon 商品目录同步失败");
        return;
      }
      setMarketplaceCatalogStoreRef(storeRef);
      await loadMarketplaceCatalog(storeRef);
      setNotice(`已从 ${result.item_count} 份真实 Seller 响应生成不可变目录快照；未自动建商品、改价、上架或复制媒体`);
    } catch {
      setNotice("无法连接商品目录服务，请稍后重试");
    } finally {
      setMarketplaceCatalogBusy(false);
    }
  }

  async function planMarketplaceGrowth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) =>
      (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value.trim();
    const competitorPrices = value("growth_competitor_prices")
      .split(/[\s,，]+/)
      .map((item) => Number(item))
      .filter((item) => Number.isFinite(item) && item > 0)
      .map(String);
    const evidenceIds = value("growth_evidence_ids").split(/[\s,，]+/).filter(Boolean);
    if (competitorPrices.length < 3) {
      setNotice("增长诊断至少需要 3 个有效的同款同行价格");
      return;
    }
    if (!evidenceIds.length) {
      setNotice("增长诊断必须引用店铺或同行 Evidence");
      return;
    }
    const observedAt = new Date(value("growth_observed_at"));
    if (Number.isNaN(observedAt.getTime())) {
      setNotice("请选择有效的市场观察时间");
      return;
    }
    const conversionRate = value("growth_conversion_rate");
    const observation = {
        scenario_id: value("growth_scenario_id"),
        marketplace_sku: value("growth_marketplace_sku"),
        category: value("growth_category"),
        competitor_prices_rub: competitorPrices,
        stock: Number(value("growth_stock")),
        review_count: Number(value("growth_review_count")),
        orders_14d: Number(value("growth_orders_14d")),
        rating: value("growth_rating"),
        content_score: value("growth_content_score"),
        conversion_rate: conversionRate ? conversionRate : null,
        compliance_risk: value("growth_compliance_risk"),
        observed_at: observedAt.toISOString(),
        evidence_ids: evidenceIds,
    };
    setMarketplaceGrowthBusy(true);
    setNotice("正在保存不可变店铺事实，并复验全店成本、价格和广告门禁…");
    try {
      const snapshotResponse = await fetchJson("/backend/v1/marketplace-growth/snapshots", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "operator_verified",
          idempotency_key: `web-${crypto.randomUUID()}`,
          observations: [observation],
        }),
      });
      const snapshot = await snapshotResponse.json();
      if (!snapshotResponse.ok) {
        setNotice(snapshot.detail ?? "无法保存 Ozon 店铺事实");
        return;
      }
      const planResponse = await fetchJson("/backend/v1/marketplace-growth/portfolio-plan/latest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_cm3_rate: value("growth_target_cm3_rate"),
          as_of: new Date().toISOString(),
        }),
      });
      const result = await planResponse.json();
      if (!planResponse.ok) {
        setNotice(result.detail ?? `事实快照 ${snapshot.id} 已保存，但全店方案生成失败`);
        await loadMarketplaceGrowthFacts();
        return;
      }
      setMarketplaceGrowthPlan(result as MarketplaceGrowthPlan);
      await loadMarketplaceGrowthFacts();
      setNotice(`事实快照 ${snapshot.id} 已保存；全店增长方案只提供建议，不会自动改价或投放广告`);
    } catch {
      setNotice("无法连接增长规划服务，请稍后重试");
    } finally {
      setMarketplaceGrowthBusy(false);
    }
  }

  const loadMarketplaceGrowthFacts = useCallback(async () => {
    try {
      const response = await fetchJson("/backend/v1/marketplace-growth/observations/latest?limit=100", {
        cache: "no-store",
      });
      const result = await response.json();
      if (!response.ok) {
        setMarketplaceGrowthFactsLoaded(true);
        setNotice(result.detail ?? "无法读取最新店铺事实");
        return;
      }
      setMarketplaceGrowthObservations(result as MarketplaceGrowthObservation[]);
      setMarketplaceGrowthFactsLoaded(true);
    } catch {
      setMarketplaceGrowthFactsLoaded(true);
      setNotice("无法读取最新店铺事实，请检查服务状态");
    }
  }, []);

  async function planLatestMarketplaceGrowth() {
    setMarketplaceGrowthBusy(true);
    setNotice("正在使用每个 SKU 的最新事实生成全店组合方案…");
    try {
      const response = await fetchJson("/backend/v1/marketplace-growth/portfolio-plan/latest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_cm3_rate: "0.15",
          as_of: new Date().toISOString(),
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        setNotice(result.detail ?? "无法生成最新全店增长方案");
        return;
      }
      setMarketplaceGrowthPlan(result as MarketplaceGrowthPlan);
      setNotice("全店组合方案已更新：仍为建议模式，平台写入保持关闭");
    } catch {
      setNotice("无法连接增长规划服务，请稍后重试");
    } finally {
      setMarketplaceGrowthBusy(false);
    }
  }

  async function requestProcurement(comparison: SourcingComparison, row: SourcingComparison["rows"][number]) {
    if (!row.scenario) return;
    const draft = procurementDrafts[row.offer.id] ?? { quantity: String(row.offer.min_order_quantity), rationale: "" };
    if (!draft.rationale.trim()) { setNotice("提交采购审批前必须填写选择理由"); return; }
    try {
      const response = await fetchJson("/backend/v1/sourcing/procurement-candidates", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_id: comparison.product.id, offer_id: row.offer.id, scenario_id: row.scenario.id, quantity: Number(draft.quantity), rationale: draft.rationale }),
      });
      const result = await response.json();
      setNotice(response.ok ? `采购候选已进入双人审批：${result.id}` : result.detail ?? "采购审批申请失败");
      if (response.ok) await load();
    } catch { setNotice("无法提交采购审批，请检查服务状态"); }
  }

  async function createSampleOrder(approvalId: string) {
    setProcurementBusy(approvalId);
    setNotice("正在把已批准的采购候选转为受控样品单…");
    try {
      const response = await fetchJson("/backend/v1/procurement/sample-orders", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approval_id: approvalId }),
      });
      const result = await response.json();
      setNotice(response.ok ? `${result.product.sku} 样品单已建立，等待供应商确认` : result.detail ?? "样品单建立失败");
      if (response.ok) await load();
    } catch { setNotice("无法建立样品单，请检查服务状态"); }
    finally { setProcurementBusy(null); }
  }

  async function recordSampleEvent(event: FormEvent<HTMLFormElement>, order: SampleOrder) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const file = (form.elements.namedItem("event_evidence") as HTMLInputElement).files?.[0];
    if (!file) return;
    let eventType = order.next_events.find((item) => item !== "cancelled") ?? "";
    const facts: Record<string, string | number> = {};
    if (order.status === "approved_to_order") {
      facts.supplier_order_ref = value("supplier_order_ref"); facts.promised_delivery_at = value("promised_delivery_at");
    } else if (order.status === "order_confirmed") {
      facts.tracking_ref = value("tracking_ref"); facts.carrier = value("carrier");
    } else if (order.status === "shipped") {
      facts.received_quantity = Number(value("received_quantity")); facts.damaged_quantity = Number(value("damaged_quantity"));
    } else if (order.status === "received" || order.status === "rework_required") {
      facts.inspected_quantity = Number(value("inspected_quantity")); facts.passed_quantity = Number(value("passed_quantity"));
      facts.defect_count = Number(value("defect_count")); facts.result = value("inspection_result");
    } else if (order.status === "inspected") {
      eventType = value("sample_decision");
      if (eventType === "golden_sample_approved") facts.golden_sample_ref = value("decision_detail");
      else facts.reason = value("decision_detail");
    }
    if (!eventType) { setNotice("当前样品单没有可执行的下一步"); return; }
    const body = new FormData();
    body.append("event_type", eventType); body.append("effective_at", new Date().toISOString());
    body.append("facts_json", JSON.stringify(facts)); body.append("file", file);
    setProcurementBusy(order.id);
    setNotice(`正在固化“${procurementEventLabels[eventType] ?? eventType}”证据…`);
    try {
      const response = await fetchJson(`/backend/v1/procurement/sample-orders/${order.id}/events`, { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${order.product.sku} 已更新：${procurementStatusLabels[result.status] ?? result.status}` : result.detail ?? "样品进度提交失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法记录样品进度，请检查服务状态"); }
    finally { setProcurementBusy(null); }
  }

  async function loadBackupOptions(orderId: string) {
    setProcurementBusy(orderId);
    try {
      const response = await fetchJson(`/backend/v1/procurement/sample-orders/${orderId}/backup-options`, { cache: "no-store" });
      const result = await response.json();
      if (response.ok) {
        setBackupOptions((current) => ({ ...current, [orderId]: result.options }));
        setNotice(result.options.length ? `已找到 ${result.options.length} 个正 CM3 备用方案，切换仍需重新审批` : "没有满足正 CM3 条件的备用供应商");
      } else setNotice(result.detail ?? "备用方案读取失败");
    } catch { setNotice("无法读取备用供应商，请检查服务状态"); }
    finally { setProcurementBusy(null); }
  }

  async function requestBackupProcurement(order: SampleOrder, option: BackupOption) {
    const key = `${order.id}:${option.offer.id}`;
    const rationale = (backupRationales[key] ?? "").trim();
    if (!rationale) { setNotice("备用供应商切换必须填写明确理由"); return; }
    setProcurementBusy(order.id);
    try {
      const response = await fetchJson("/backend/v1/sourcing/procurement-candidates", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ product_id: order.product_id, offer_id: option.offer.id, scenario_id: option.scenario.id, quantity: Math.max(order.quantity, option.offer.min_order_quantity), rationale: `备用切换：${rationale}` }),
      });
      const result = await response.json();
      setNotice(response.ok ? `备用方案已进入全新双人审批：${result.id}` : result.detail ?? "备用方案提交失败");
      if (response.ok) await load();
    } catch { setNotice("无法提交备用方案审批，请检查服务状态"); }
    finally { setProcurementBusy(null); }
  }

  async function compileDecisionContract(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null)?.value.trim() ?? "";
    const lines = (name: string) => value(name).split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    const profile = interactionProfiles.find((item) => item.id === selectedProfileId);
    const horizon = value("decision_horizon");
    const maximumLoss = value("decision_maximum_loss");
    const evidenceId = value("decision_evidence");
    const sourceContractId = value("source_contract_id");
    const context: Record<string, unknown> = {};
    if (profile?.requires_forecast_basis) {
      context.baseline = value("forecast_baseline");
      context.scenarios = lines("forecast_scenarios").map((label) => ({ label }));
    }
    if (profile?.id === "best_solution") {
      context.hard_constraints = lines("decision_hard_constraints");
      context.decision_criteria = lines("decision_criteria");
    }
    const payload = {
      profile: selectedProfileId,
      objective: value("decision_objective"),
      decision_domain: value("decision_domain"),
      risk_level: value("decision_risk"),
      horizon_days: horizon ? Number(horizon) : null,
      maximum_loss_amount: maximumLoss || null,
      currency: value("decision_currency") || "CNY",
      source_contract_id: sourceContractId || null,
      assumptions: lines("decision_assumptions"),
      unknowns: lines("decision_unknowns"),
      options: lines("decision_options").map((label, index) => ({ id: String.fromCharCode(65 + index), label })),
      evidence_ids: evidenceId ? [evidenceId] : [],
      context,
    };
    setDecisionBusy(true);
    setNotice("正在把问题编译成可审计的决策合同…");
    try {
      const response = await fetchJson("/backend/v1/decision-contracts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (response.ok) {
        const detail = result.missing_inputs.length ? `仍缺：${result.missing_inputs.join("、")}` : decisionStatusLabels[result.status] ?? result.status;
        setNotice(`决策合同 ${result.id} 已固化；${detail}。该合同没有经营执行权。`);
        await load();
      } else setNotice(result.detail ?? "决策合同建立失败");
    } catch { setNotice("无法建立决策合同，请检查服务状态"); }
    finally { setDecisionBusy(false); }
  }

  async function submitDecisionAnalysis(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null)?.value.trim() ?? "";
    const lines = (name: string) => value(name).split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    const contractId = value("analysis_contract_id");
    const contract = decisionContracts.find((item) => item.id === contractId);
    const options = Array.isArray(contract?.input.options) ? contract.input.options as Array<{ id?: string; label?: string }> : [];
    const context = contract?.input.context as Record<string, unknown> | undefined;
    const hardConstraints = Array.isArray(context?.hard_constraints) ? context.hard_constraints.map(String) : [];
    const bestSolution = contract?.profile_id === "best_solution";
    const optionId = value("analysis_option_id");
    const dueValue = value("analysis_due_at");
    const selectionAssessment = bestSolution ? {
      hard_constraint_results: options.flatMap((option, optionIndex) => hardConstraints.map((constraint, constraintIndex) => ({
        option_id: String(option.id ?? ""), constraint,
        passed: value(`best_constraint_${optionIndex}_${constraintIndex}_passed`) === "true",
        rationale: value(`best_constraint_${optionIndex}_${constraintIndex}_rationale`),
      }))),
      option_assessments: options.map((option, index) => ({
        option_id: String(option.id ?? ""), evidence_quality: value(`best_evidence_quality_${index}`),
        expected_risk_adjusted_long_term_value: value(`best_long_term_value_${index}`),
        total_cost_of_ownership: value(`best_tco_${index}`), maximum_loss: value(`best_maximum_loss_${index}`),
        reversibility_and_rollback: value(`best_rollback_${index}`), time_to_value: value(`best_time_to_value_${index}`),
        operational_fit: value(`best_operational_fit_${index}`),
      })),
      rejected_options: options.filter((option) => String(option.id ?? "") !== optionId).map((option) => {
        const originalIndex = options.indexOf(option);
        return { option_id: String(option.id ?? ""), reason: value(`best_rejection_reason_${originalIndex}`) };
      }),
      sensitivity_drivers: lines("best_sensitivity_drivers"),
      invalidation_conditions: lines("best_invalidation_conditions"),
      review_at: value("best_review_at") ? new Date(value("best_review_at")).toISOString() : "",
      approval_requirement: value("best_approval_requirement"),
      no_action_option_id: value("best_no_action_option_id") || null,
      no_action_omission_reason: value("best_no_action_omission_reason") || null,
    } : null;
    const body = {
      conclusion: value("analysis_conclusion"), confidence: value("analysis_confidence"),
      recommended_option_id: optionId || null,
      forecast_metric: bestSolution ? null : value("analysis_metric") || null,
      forecast_value: bestSolution ? null : value("analysis_value") || null,
      forecast_low: bestSolution ? null : value("analysis_low") || null,
      forecast_high: bestSolution ? null : value("analysis_high") || null,
      forecast_unit: bestSolution ? null : value("analysis_unit") || null,
      forecast_due_at: bestSolution ? null : dueValue ? new Date(dueValue).toISOString() : null,
      assumptions: lines("analysis_assumptions"), unknowns: lines("analysis_unknowns"),
      selection_assessment: selectionAssessment,
      evidence_ids: [value("analysis_evidence")].filter(Boolean), model_ref: value("analysis_model_ref") || null,
    };
    setLifecycleBusy("analysis"); setNotice("正在固化分析、预测区间与证据…");
    try {
      const response = await fetchJson(`/backend/v1/decision-contracts/${contractId}/analyses`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `分析 ${result.id} 已提交，必须由另一身份独立复核；仍无执行权。` : result.detail ?? "分析提交失败");
      if (response.ok) { form.reset(); setSelectedAnalysisContractId(""); setSelectedAnalysisOptionId(""); await load(); }
    } catch { setNotice("无法提交分析，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function reviewDecisionAnalysis(event: FormEvent<HTMLFormElement>, analysisId: string) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null)?.value.trim() ?? "";
    const evidenceId = value("review_evidence");
    const body = { verdict: value("review_verdict"), rationale: value("review_rationale"), counterarguments: value("review_counterarguments").split(/\r?\n/).map((item) => item.trim()).filter(Boolean), evidence_ids: evidenceId ? [evidenceId] : [] };
    setLifecycleBusy(analysisId); setNotice("正在固化独立复核结论…");
    try {
      const response = await fetchJson(`/backend/v1/decision-analyses/${analysisId}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `独立复核已记录：${result.verdict}` : result.detail ?? "复核提交失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法提交独立复核，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function resolveDecisionAnalysis(event: FormEvent<HTMLFormElement>, analysis: DecisionAnalysis) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null)?.value.trim() ?? "";
    const body = { analysis_id: analysis.id, disposition: value("resolution_disposition"), rationale: value("resolution_rationale"), conditions: value("resolution_conditions").split(/\r?\n/).map((item) => item.trim()).filter(Boolean) };
    setLifecycleBusy(analysis.id); setNotice("正在记录正式决策；这仍不会执行经营动作…");
    try {
      const response = await fetchJson(`/backend/v1/decision-contracts/${analysis.contract_id}/resolution`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `正式决策已固化：${result.disposition}；执行仍需另行审批。` : result.detail ?? "正式决策提交失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法记录正式决策，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function recordDecisionOutcome(event: FormEvent<HTMLFormElement>, resolutionId: string) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null)?.value.trim() ?? "";
    const observedAt = value("outcome_observed_at");
    const body = { actual_value: value("outcome_actual"), observed_at: new Date(observedAt).toISOString(), evidence_ids: [value("outcome_evidence")].filter(Boolean), notes: value("outcome_notes") };
    setLifecycleBusy(resolutionId); setNotice("正在回填真实结果并计算预测误差…");
    try {
      const response = await fetchJson(`/backend/v1/decision-resolutions/${resolutionId}/outcome`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `结果已回填：误差 ${result.signed_error} ${result.unit}，区间${result.interval_covered ? "命中" : "未命中"}。` : result.detail ?? "结果回填失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法回填结果，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function registerCausalExperiment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null)?.value.trim() ?? "";
    const resolutionId = value("experiment_resolution_id");
    const startAt = value("experiment_start_at");
    const endAt = value("experiment_end_at");
    const effectMetrics = [];
    if (value("experiment_cannibalization_metric")) effectMetrics.push({ metric: value("experiment_cannibalization_metric"), role: "cannibalization", multiplier: "-1", required: true });
    if (value("experiment_long_term_cost_metric")) effectMetrics.push({ metric: value("experiment_long_term_cost_metric"), role: "long_term_cost", multiplier: "-1", required: true });
    const body = {
      hypothesis: value("experiment_hypothesis"), primary_metric: value("experiment_metric"),
      randomization_unit: value("experiment_unit"), interference_cluster: value("experiment_cluster") || null,
      variants: [
        { id: "control", label: value("experiment_control_label"), allocation: "0.5", control: true },
        { id: "treatment", label: value("experiment_treatment_label"), allocation: "0.5", control: false },
      ],
      target_sample_size: Number(value("experiment_sample_size")), minimum_detectable_effect: value("experiment_mde"),
      budget_cap_amount: value("experiment_budget"), stop_loss_amount: value("experiment_stop_loss"),
      currency: value("experiment_currency"), start_at: new Date(startAt).toISOString(), end_at: new Date(endAt).toISOString(),
      outcome_window_days: Number(value("experiment_outcome_days")),
      guardrails: [{ metric: value("experiment_guardrail_metric"), direction: "max", threshold: value("experiment_guardrail_threshold") }],
      stratification_keys: [value("experiment_segment_key")].filter(Boolean), effect_metrics: effectMetrics,
      evidence_ids: [value("experiment_evidence")],
    };
    setLifecycleBusy("experiment-register"); setNotice("正在固化实验假设、分流、预算、止损线和质量门禁…");
    try {
      const response = await fetchJson(`/backend/v1/decision-resolutions/${resolutionId}/experiment`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `实验协议 ${result.id} 已预注册；启动前仍需人工批准。` : result.detail ?? "实验预注册失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法预注册实验，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function transitionCausalExperiment(event: FormEvent<HTMLFormElement>, protocol: CausalExperiment, eventType: "started" | "paused" | "resumed" | "stopped" | "completed") {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const body = { event_type: eventType, effective_at: new Date().toISOString(), evidence_id: value("experiment_event_evidence"), reason: value("experiment_event_reason") };
    setLifecycleBusy(protocol.id); setNotice(`正在记录实验生命周期事件：${eventType}…`);
    try {
      const response = await fetchJson(`/backend/v1/causal-experiments/${protocol.id}/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `实验状态已更新为 ${result.status}；没有触发自动放量。` : result.detail ?? "实验状态更新失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法更新实验状态，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function recordExperimentSafety(event: FormEvent<HTMLFormElement>, protocol: CausalExperiment) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const body = { metric: value("safety_metric"), value: value("safety_value"), observed_at: new Date().toISOString(), evidence_id: value("safety_evidence") };
    setLifecycleBusy(`safety:${protocol.id}`); setNotice("正在记录预算、损失或护栏读数…");
    try {
      const response = await fetchJson(`/backend/v1/causal-experiments/${protocol.id}/safety-checks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `${result.metric}：${result.status === "breached" ? "已越线，后续分流冻结" : "仍在限制内"}` : result.detail ?? "安全读数提交失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法记录实验安全读数，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function reviewCausalExperiment(event: FormEvent<HTMLFormElement>, protocol: CausalExperiment) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const body = {
      verdict: value("causal_review_verdict"),
      rationale: value("causal_review_rationale"),
      method_assessment: value("causal_review_method"),
      data_quality_assessment: value("causal_review_data"),
      counterarguments: value("causal_review_counterarguments").split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      evidence_ids: [value("causal_review_evidence")],
    };
    setLifecycleBusy(`causal-review:${protocol.id}`); setNotice("正在固化独立因果复核；复核人与实验负责人必须不同…");
    try {
      const response = await fetchJson(`/backend/v1/causal-experiments/${protocol.id}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `独立复核已固化：${result.verdict}。只有 accepted 才能进入知识登记。` : result.detail ?? "因果复核提交失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法提交因果复核，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function publishCausalKnowledge(event: FormEvent<HTMLFormElement>, protocol: CausalExperiment, reviewId: string) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const validFrom = value("knowledge_valid_from");
    const reevaluateAt = value("knowledge_reevaluate_at");
    const replicationId = value("knowledge_replication_source");
    const body = {
      review_id: reviewId,
      claim: value("knowledge_claim"),
      mechanism: value("knowledge_mechanism"),
      applicability: {
        platform: value("knowledge_platform"), country: value("knowledge_country"),
        category: value("knowledge_category"), population: value("knowledge_population"),
      },
      falsification_conditions: value("knowledge_falsification").split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      evidence_ids: [value("knowledge_evidence")],
      valid_from: new Date(validFrom).toISOString(), reevaluate_at: new Date(reevaluateAt).toISOString(),
      replicates_knowledge_id: replicationId || null,
      replication_rationale: replicationId ? value("knowledge_replication_rationale") : null,
    };
    setLifecycleBusy(`causal-knowledge:${protocol.id}`); setNotice("正在登记适用边界、反证条件与复验期限…");
    try {
      const response = await fetchJson(`/backend/v1/causal-experiments/${protocol.id}/knowledge`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `因果知识 ${result.id} 已登记为 ${result.knowledge_strength}；仍无经营执行权。` : result.detail ?? "因果知识登记失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法登记因果知识，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function proposeCausalPolicy(event: FormEvent<HTMLFormElement>, entry: CausalKnowledgeEntry) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const body = {
      title: value("policy_title"), objective: value("policy_objective"), knowledge_ids: [entry.id], applicability: entry.applicability,
      conditions: [{ field: value("policy_condition_field"), operator: value("policy_condition_operator"), value: value("policy_condition_value") }],
      action: { type: value("policy_action_type"), parameters: { variant: value("policy_action_variant") } },
      guardrails: [{ metric: value("policy_guardrail_metric"), direction: "max", threshold: value("policy_guardrail_threshold") }],
      fallback_action: { type: "recommend_no_action", parameters: { reason: "conditions_or_knowledge_not_valid" } },
      rollout_stages: [
        { name: "shadow", max_exposure_fraction: "0", minimum_observation_count: Number(value("policy_shadow_samples")), minimum_incremental_value: value("policy_shadow_value") },
        { name: "limited", max_exposure_fraction: value("policy_limited_fraction"), minimum_observation_count: Number(value("policy_limited_samples")), minimum_incremental_value: value("policy_limited_value") },
      ],
      evidence_ids: [value("policy_evidence")],
    };
    setLifecycleBusy(`policy-propose:${entry.id}`); setNotice("正在把有效知识编译为条件、护栏、退回动作和分阶段门槛…");
    try {
      const response = await fetchJson("/backend/v1/causal-policies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `条件策略 ${result.id} 已固化；需要另一身份复核，当前无执行权。` : result.detail ?? "策略建立失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法建立条件策略，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function reviewCausalPolicy(event: FormEvent<HTMLFormElement>, policy: CausalPolicy) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLTextAreaElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const body = { verdict: value("policy_review_verdict"), rationale: value("policy_review_rationale"), counterarguments: value("policy_review_counterarguments").split(/\r?\n/).map((item) => item.trim()).filter(Boolean), evidence_ids: [value("policy_review_evidence")] };
    setLifecycleBusy(`policy-review:${policy.id}`); setNotice("正在固化条件策略独立复核…");
    try {
      const response = await fetchJson(`/backend/v1/causal-policies/${policy.id}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `策略复核已记录：${result.verdict}。` : result.detail ?? "策略复核失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法提交策略复核，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function releaseCausalPolicyStage(event: FormEvent<HTMLFormElement>, policy: CausalPolicy, reviewId: string) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const stageIndex = policy.releases.length;
    const body = { review_id: reviewId, stage_index: stageIndex, rationale: value("policy_release_rationale"), evidence_ids: [value("policy_release_evidence")] };
    setLifecycleBusy(`policy-release:${policy.id}`); setNotice(`正在审批 ${policy.rollout_stages[stageIndex]?.name ?? "下一"} 阶段；不会自动晋级…`);
    try {
      const response = await fetchJson(`/backend/v1/causal-policies/${policy.id}/releases`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `阶段 ${result.stage.name} 已批准为受控合同；仍未获得执行权。` : result.detail ?? "阶段审批失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法审批策略阶段，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function recordCausalPolicyOutcome(event: FormEvent<HTMLFormElement>, policy: CausalPolicy, releaseId: string) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const body = { verdict: value("policy_outcome_verdict"), observation_count: Number(value("policy_outcome_count")), incremental_value: value("policy_outcome_value"), guardrail_breached: value("policy_outcome_guardrail") === "true", notes: value("policy_outcome_notes"), evidence_ids: [value("policy_outcome_evidence")] };
    setLifecycleBusy(`policy-outcome:${releaseId}`); setNotice("正在回填本阶段真实结果和护栏状态…");
    try {
      const response = await fetchJson(`/backend/v1/causal-policy-releases/${releaseId}/outcome`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `阶段结果已固化：${result.verdict}；系统不会自行晋级。` : result.detail ?? "阶段结果回填失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法回填阶段结果，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function runPolicyShadowBatch(event: FormEvent<HTMLFormElement>, policy: CausalPolicy, releaseId: string) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const coverDays = value("policy_shadow_cover_days").split(/[，,\s]+/).map(Number).filter(Number.isFinite);
    const body = {
      batch_key: `manual-${Date.now()}`,
      contexts: coverDays.map((days) => ({ ...policy.applicability, inventory_cover_days: days })),
      observed_at: new Date().toISOString(),
      evidence_ids: [value("policy_shadow_evidence")],
    };
    setLifecycleBusy(`policy-shadow:${releaseId}`); setNotice("正在记录零暴露影子判断；不会修改价格、广告、库存或平台数据…");
    try {
      const response = await fetchJson(`/backend/v1/causal-policy-releases/${releaseId}/shadow-batches`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `影子批次已固化：${result.matched_count} 条命中、${result.fallback_count} 条退回，真实暴露为 0。` : result.detail ?? "影子批次失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法记录影子批次，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function requestPolicyActivation(event: FormEvent<HTMLFormElement>, policy: CausalPolicy, releaseId: string, batch: PolicyShadowBatch) {
    event.preventDefault();
    const evidenceId = (event.currentTarget.elements.namedItem("policy_handoff_evidence") as HTMLSelectElement).value;
    setLifecycleBusy(`policy-handoff:${releaseId}`); setNotice("正在将阶段激活建议移交独立审批；不会直接执行…");
    try {
      const response = await fetchJson(`/backend/v1/causal-policy-releases/${releaseId}/activation-handoff`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ evaluation_ids: batch.evaluation_ids, evidence_ids: [evidenceId] }) });
      const result = await response.json();
      setNotice(response.ok ? `已进入审批中心：${result.approval_id}。即使批准，也仍需独立执行适配器。` : result.detail ?? "审批交接失败");
      if (response.ok) await load();
    } catch { setNotice(`无法提交 ${policy.title} 的阶段交接`); }
    finally { setLifecycleBusy(null); }
  }

  async function prepareListingExecutionPlan(event: FormEvent<HTMLFormElement>, approval: ApprovalRecord) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const draftId = String(approval.payload.draft_id ?? approval.resource_id);
    const maximumExpectedLoss = value("execution_max_expected_loss");
    const body = {
      idempotency_key: `listing-draft-${draftId}-${approval.id}`,
      precondition_state_hash: value("execution_state_hash"),
      evidence_ids: [value("execution_evidence")],
      risk_limits: { max_quantity: "1", max_daily_runs: "1", max_expected_loss: maximumExpectedLoss },
      risk_values: { quantity: "1", expected_loss: value("execution_expected_loss") },
      risk_currency: value("execution_risk_currency"),
    };
    setLifecycleBusy(`listing-execution-plan:${draftId}`);
    setNotice("正在准备 Ozon Listing 执行计划并申请独立 Execution 审批；不会立即发布…");
    try {
      const response = await fetchJson(`/backend/v1/listings/ozon/drafts/${draftId}/execution-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      setNotice(response.ok ? `执行计划 ${result.id} 已准备并进入独立审批；尚未发布。` : result.detail ?? "执行计划准备失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法准备执行计划，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function reviewListingRussianNative(event: FormEvent<HTMLFormElement>, approval: ApprovalRecord) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null)?.value.trim() ?? "";
    const checked = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | null)?.checked ?? false;
    const draftId = String(approval.payload.draft_id ?? approval.resource_id);
    const body = {
      accepted: value("russian_review_decision") === "accepted",
      native_russian_verified: checked("native_russian_verified"),
      listing_snapshot_reviewed: checked("listing_snapshot_reviewed"),
      terminology_accepted: checked("terminology_accepted"),
      claims_grounded: checked("claims_grounded"),
      ozon_policy_checked: checked("ozon_policy_checked"),
      rationale: value("russian_review_rationale"),
    };
    setLifecycleBusy(`listing-russian-review:${draftId}`);
    setNotice("正在固化俄语母语独立复核；不会发布 Listing…");
    try {
      const response = await fetchJson(`/backend/v1/listings/ozon/drafts/${draftId}/russian-native-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      setNotice(response.ok ? `俄语母语复核 ${result.review.id} 已不可变固化；仍需通过其余执行门。` : result.detail ?? "俄语母语复核失败");
      if (response.ok) { form.reset(); await load(); }
    } catch {
      setNotice("无法提交俄语母语复核，请检查服务状态");
    } finally {
      setLifecycleBusy(null);
    }
  }

  async function reviewOzonExecutionIdentity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null)?.value.trim() ?? "";
    const checked = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | null)?.checked ?? false;
    const evidenceId = value("execution_identity_evidence");
    const body = {
      identity_ref: value("execution_identity_ref"),
      accepted: value("execution_identity_decision") === "accepted",
      inventory_complete: checked("inventory_complete"),
      credential_material_absent: checked("credential_material_absent"),
      owner_verified: checked("owner_verified"),
      caller_system_verified: checked("caller_system_verified"),
      scope_minimized: checked("scope_minimized"),
      dedicated_executor: checked("dedicated_executor"),
      rationale: value("execution_identity_rationale"),
    };
    setLifecycleBusy(`ozon-execution-identity:${evidenceId}`);
    setNotice("正在固化 Ozon 执行身份独立复核；不会读取凭证或执行平台写入…");
    try {
      const response = await fetchJson(`/backend/v1/operations/ozon/execution-identities/${evidenceId}/authority-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await response.json();
      setNotice(response.ok ? `执行身份复核 ${result.review.id} 已不可变固化；运行开关仍保持关闭。` : result.detail ?? "执行身份复核失败");
      if (response.ok) { form.reset(); await load(); }
    } catch {
      setNotice("无法提交执行身份复核，请检查服务状态");
    } finally {
      setLifecycleBusy(null);
    }
  }

  async function dryRunExecutionPlan(event: FormEvent<HTMLFormElement>, plan: GovernedExecutionPlan) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    setLifecycleBusy(`execution-dry-run:${plan.id}`); setNotice("正在核对当前平台快照、动作白名单和回滚合同；不会写入平台…");
    try {
      const response = await fetchJson(`/backend/v1/governed-execution-plans/${plan.id}/dry-run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_state_hash: value("dry_run_state_hash"), evidence_ids: [value("dry_run_evidence")] }) });
      const result = await response.json();
      setNotice(response.ok ? `预演${result.passed ? "通过" : "失败"}；平台写入：${result.platform_write_performed ? "发生" : "未发生"}。` : result.detail ?? "预演失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法完成执行预演，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function queueLimitedExecution(plan: GovernedExecutionPlan) {
    setLifecycleBusy(`execution-queue:${plan.id}`); setNotice("正在重新核验知识、阶段交接、预演和双审批，并尝试进入受限执行队列…");
    try {
      const response = await fetchJson(`/backend/v1/governed-execution-plans/${plan.id}/commands`, { method: "POST" });
      const result = await response.json();
      setNotice(response.ok ? `命令 ${result.id} 已入队，等待专用执行器按状态指纹领取。` : result.detail ?? "执行命令入队失败");
      if (response.ok) await load();
    } catch { setNotice("无法进入受限执行队列，请检查全局执行开关和服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function createObservationWindow(event: FormEvent<HTMLFormElement>, command: LimitedExecutionCommand) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const primaryMetric = value("observation_primary_metric");
    const guardrailMetric = value("observation_guardrail_metric");
    const body = {
      primary_metric: primaryMetric,
      baseline: { [primaryMetric]: value("observation_primary_baseline"), [guardrailMetric]: value("observation_guardrail_baseline") },
      required_observations: Number(value("observation_required_count")),
      starts_at: new Date(value("observation_starts_at")).toISOString(),
      ends_at: new Date(value("observation_ends_at")).toISOString(),
      evidence_ids: [value("observation_evidence")],
    };
    setLifecycleBusy(`observation-window:${command.id}`); setNotice("正在固化执行后指标、基线、护栏和观察期限…");
    try {
      const response = await fetchJson(`/backend/v1/limited-execution-commands/${command.id}/observation-window`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `观察合同 ${result.id} 已固化；结果只用于评估，不会自动放大策略。` : result.detail ?? "观察合同建立失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法建立执行后观察合同，请检查时间、证据和服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function recordExecutionObservation(event: FormEvent<HTMLFormElement>, window: ExecutionObservationWindow) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const body = { metric: value("observed_metric"), value: value("observed_value"), observed_at: new Date(value("observed_at")).toISOString(), evidence_ids: [value("observed_evidence")] };
    setLifecycleBusy(`observation:${window.id}`); setNotice("正在写入不可变结果并核对预注册护栏…");
    try {
      const response = await fetchJson(`/backend/v1/execution-observation-windows/${window.id}/observations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? (result.guardrail_breached ? `护栏已越界：事故 ${result.incident_id} 已登记，补偿命令 ${result.rollback_command_id} 已排队，全部写操作已冻结。` : "结果已记录，护栏正常，继续观察。") : result.detail ?? "结果记录失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法记录执行后结果，请检查指标、时间和服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function assessCapabilityEconomics(event: FormEvent<HTMLFormElement>, window: ExecutionObservationWindow) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const body = {
      realized_incremental_value: value("economics_realized_value"), avoided_loss: value("economics_avoided_loss"),
      model_compute_cost: value("economics_model_cost"), human_review_cost: value("economics_review_cost"),
      incident_loss: value("economics_incident_loss"), maintenance_cost: value("economics_maintenance_cost"),
      currency: value("economics_currency"), evidence_ids: [value("economics_evidence")], as_of: new Date(value("economics_as_of")).toISOString(),
    };
    setLifecycleBusy(`capability-economics:${window.id}`); setNotice("正在核算能力的真实增量、避免损失和全部成本…");
    try {
      const response = await fetchJson(`/backend/v1/execution-observation-windows/${window.id}/capability-economics`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `能力净价值：${result.net_value} ${result.currency}。该结果只形成治理建议，不会自动改变权限。` : result.detail ?? "能力损益核算失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法完成能力损益核算，请检查观察是否结束及证据是否有效"); }
    finally { setLifecycleBusy(null); }
  }

  async function claimIncident(incident: OperationalIncident) {
    setLifecycleBusy(`incident-claim:${incident.id}`); setNotice("正在登记事故恢复负责人…");
    try {
      const response = await fetchJson(`/backend/v1/operational-incidents/${incident.id}/claim`, { method: "POST" });
      const result = await response.json(); setNotice(response.ok ? `事故 ${result.id} 已进入人工恢复。` : result.detail ?? "事故领取失败");
      if (response.ok) await load();
    } catch { setNotice("无法领取事故，请检查身份与服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function recordIncidentCheck(event: FormEvent<HTMLFormElement>, incident: OperationalIncident) {
    event.preventDefault(); const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    setLifecycleBusy(`incident-check:${incident.id}`); setNotice("正在固化恢复检查证据…");
    try {
      const response = await fetchJson(`/backend/v1/operational-incidents/${incident.id}/checks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ check: value("incident_check"), passed: true, notes: value("incident_check_notes"), evidence_ids: [value("incident_check_evidence")] }) });
      const result = await response.json(); setNotice(response.ok ? "恢复检查已记录，历史不可覆盖。" : result.detail ?? "恢复检查失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法记录恢复检查，请确认当前身份是事故负责人"); }
    finally { setLifecycleBusy(null); }
  }

  async function submitIncidentReview(incident: OperationalIncident) {
    setLifecycleBusy(`incident-submit:${incident.id}`); setNotice("正在核对五项恢复条件并申请独立复核…");
    try {
      const response = await fetchJson(`/backend/v1/operational-incidents/${incident.id}/review-request`, { method: "POST" });
      const result = await response.json(); setNotice(response.ok ? "恢复方案已送交独立复核；熔断仍保持。" : result.detail ?? "提交复核失败");
      if (response.ok) await load();
    } catch { setNotice("无法提交恢复复核"); }
    finally { setLifecycleBusy(null); }
  }

  async function reviewIncident(event: FormEvent<HTMLFormElement>, incident: OperationalIncident) {
    event.preventDefault(); const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    setLifecycleBusy(`incident-review:${incident.id}`); setNotice("正在执行独立恢复复核…");
    try {
      const response = await fetchJson(`/backend/v1/operational-incidents/${incident.id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ accepted: value("incident_review_verdict") === "accepted", rationale: value("incident_review_rationale"), evidence_ids: [value("incident_review_evidence")] }) });
      const result = await response.json(); setNotice(response.ok ? (result.review_status === "accepted" ? "独立复核通过；仍需管理员单独解除熔断。" : "复核未通过，已退回继续恢复。") : result.detail ?? "事故复核失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法完成独立复核，请确认复核者不是事故发起人或负责人"); }
    finally { setLifecycleBusy(null); }
  }

  async function releaseIncidentFreeze(incident: OperationalIncident) {
    setLifecycleBusy(`incident-release:${incident.id}`); setNotice("正在请求管理员明确解除写入熔断…");
    try {
      const response = await fetchJson("/backend/v1/system/kill-switch/release", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: `Incident ${incident.id} independently reviewed; controlled recovery release` }) });
      const result = await response.json(); setNotice(response.ok ? "熔断已由管理员解除；事故仍需另行关闭。" : result.detail ?? "熔断解除失败");
      if (response.ok) await load();
    } catch { setNotice("无法解除熔断，请确认管理员身份"); }
    finally { setLifecycleBusy(null); }
  }

  async function closeIncident(event: FormEvent<HTMLFormElement>, incident: OperationalIncident) {
    event.preventDefault(); const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    setLifecycleBusy(`incident-close:${incident.id}`); setNotice("正在固化事故关闭证据…");
    try {
      const response = await fetchJson(`/backend/v1/operational-incidents/${incident.id}/close`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ notes: value("incident_close_notes"), evidence_ids: [value("incident_close_evidence")] }) });
      const result = await response.json(); setNotice(response.ok ? `事故 ${result.id} 已关闭，完整恢复历史已保留。` : result.detail ?? "事故关闭失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法关闭事故，请检查熔断状态和关闭证据"); }
    finally { setLifecycleBusy(null); }
  }

  async function scanOperationsQueue() {
    setLifecycleBusy("operations-scan"); setNotice("正在扫描逾期任务并固化升级记录…");
    try { const response = await fetchJson("/backend/v1/operations-control/escalation-scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ as_of: null }) }); const result = await response.json(); setNotice(response.ok ? `扫描 ${result.scanned_count} 项，发现 ${result.overdue_count} 项逾期，新建 ${result.new_escalation_ids.length} 条升级记录。` : result.detail ?? "运营队列扫描失败"); if (response.ok) await load(); }
    catch { setNotice("无法扫描运营队列"); } finally { setLifecycleBusy(null); }
  }

  async function createReadOnlyPilot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const operations = Array.from(form.querySelectorAll<HTMLInputElement>('input[name="pilot_operations"]:checked')).map((item) => item.value);
    const body = { idempotency_key: `ozon-read-only-${value("pilot_account_alias")}-${value("pilot_starts_at")}`, platform: "ozon", account_alias: value("pilot_account_alias"), allowed_operations: operations, max_daily_requests: Number(value("pilot_daily_limit")), max_targets: Number(value("pilot_target_limit")), starts_at: new Date(value("pilot_starts_at")).toISOString(), ends_at: new Date(value("pilot_ends_at")).toISOString(), evidence_ids: [value("pilot_evidence")] };
    setLifecycleBusy("pilot-create"); setNotice("正在固化 Ozon 只读试点边界…");
    try { const response = await fetchJson("/backend/v1/read-only-pilots", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); const result = await response.json(); setNotice(response.ok ? `只读试点 ${result.id} 已建立；平台写入仍被永久禁止。` : result.detail ?? "试点建立失败"); if (response.ok) { form.reset(); await load(); } }
    catch { setNotice("无法建立只读试点，请检查期限、限额和证据"); } finally { setLifecycleBusy(null); }
  }

  async function attestPilotControl(event: FormEvent<HTMLFormElement>, pilot: ReadOnlyPilot) {
    event.preventDefault(); const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    setLifecycleBusy(`pilot-attest:${pilot.id}`); setNotice("正在记录试点控制证据…");
    try { const response = await fetchJson(`/backend/v1/read-only-pilots/${pilot.id}/attestations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ control: value("pilot_control"), passed: true, notes: value("pilot_control_notes"), evidence_ids: [value("pilot_control_evidence")] }) }); const result = await response.json(); setNotice(response.ok ? "控制项已记录，仍需完成其余准入条件。" : result.detail ?? "控制项记录失败"); if (response.ok) { form.reset(); await load(); } }
    catch { setNotice("无法记录试点控制项"); } finally { setLifecycleBusy(null); }
  }

  async function submitPilotReview(pilot: ReadOnlyPilot) {
    setLifecycleBusy(`pilot-submit:${pilot.id}`); setNotice("正在核对控制项、事故、熔断与近期演练…");
    try { const response = await fetchJson(`/backend/v1/read-only-pilots/${pilot.id}/review-request`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ as_of: null }) }); const result = await response.json(); setNotice(response.ok ? "只读试点已提交独立复核。" : result.detail ?? "试点仍不满足准入条件"); if (response.ok) await load(); }
    catch { setNotice("无法提交试点复核"); } finally { setLifecycleBusy(null); }
  }

  async function reviewPilot(event: FormEvent<HTMLFormElement>, pilot: ReadOnlyPilot) {
    event.preventDefault(); const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    setLifecycleBusy(`pilot-review:${pilot.id}`); setNotice("正在执行只读试点独立复核…");
    try { const response = await fetchJson(`/backend/v1/read-only-pilots/${pilot.id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ accepted: value("pilot_review_verdict") === "accepted", rationale: value("pilot_review_rationale") }) }); const result = await response.json(); setNotice(response.ok ? `试点复核结果：${result.status}。` : result.detail ?? "试点复核失败"); if (response.ok) { form.reset(); await load(); } }
    catch { setNotice("无法完成试点独立复核"); } finally { setLifecycleBusy(null); }
  }

  async function activatePilot(pilot: ReadOnlyPilot) {
    setLifecycleBusy(`pilot-activate:${pilot.id}`); setNotice("正在重新核验全部准入条件…");
    try { const response = await fetchJson(`/backend/v1/read-only-pilots/${pilot.id}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ as_of: null }) }); const result = await response.json(); setNotice(response.ok ? `试点 ${result.id} 已激活：仅允许只读接口，禁止任何平台写入。` : result.detail ?? "试点激活被阻断"); if (response.ok) await load(); }
    catch { setNotice("无法激活只读试点"); } finally { setLifecycleBusy(null); }
  }

  const demandSourceReports = evidenceRecords.filter((item) =>
    item.metadata?.requirement_id === "SKU-000" && item.metadata?.evidence_role === "source_report"
  );
  const demandRequirement = gateReadiness?.requirements.find((item) => item.id === "SKU-000");
  const acceptedDemandReportIds = Array.isArray(demandRequirement?.details?.accepted_report_ids)
    ? demandRequirement.details.accepted_report_ids.filter((item): item is string => typeof item === "string")
    : [];
  const acceptedDemandReports = demandSourceReports.filter((item) => acceptedDemandReportIds.includes(item.id));
  const researchReadiness = gateReadiness?.decision_scope_readiness?.research;
  const realExecutionReadiness = gateReadiness?.decision_scope_readiness?.real_execution;
  const pendingProcurementApprovals = approvals.filter((item) => item.action === "procurement.place_order" && item.status === "pending").length;
  const pendingListingApprovals = approvals.filter((item) => item.action === "listing.publish" && item.status === "pending");
  const approvedListingApprovals = approvals.filter((item) => item.action === "listing.publish" && item.status === "approved");
  const listingExecutionPlans = governedExecutionPlans.filter((item) => item.source_kind === "approved_listing_draft");
  const causalPolicyExecutionPlans = governedExecutionPlans.filter((item) => item.source_kind === "causal_policy_handoff");
  const approvedWithoutSample = approvals.filter((item) => item.action === "procurement.place_order" && item.status === "approved" && !sampleOrders.some((order) => order.approval_id === item.id));
  const selectedProfile = interactionProfiles.find((item) => item.id === selectedProfileId);
  const selectedAnalysisContract = decisionContracts.find((item) => item.id === selectedAnalysisContractId);
  const analysisOptions = Array.isArray(selectedAnalysisContract?.input.options) ? selectedAnalysisContract.input.options as Array<{ id?: string; label?: string }> : [];
  const analysisContext = selectedAnalysisContract?.input.context as Record<string, unknown> | undefined;
  const analysisHardConstraints = Array.isArray(analysisContext?.hard_constraints) ? analysisContext.hard_constraints.map(String) : [];
  const isBestSolutionAnalysis = selectedAnalysisContract?.profile_id === "best_solution";
  const analysisNeedsForecast = Boolean(selectedAnalysisContract && !isBestSolutionAnalysis);
  const experimentResolutions = decisionResolutions.filter((item) => item.disposition === "experiment" && !causalExperiments.some((experiment) => experiment.resolution_id === item.id));
  const requirement = (id: string) => gateReadiness?.requirements.find((item) => item.id === id);
  const startupSteps = [
    { id: "GOV-001", title: "确认经营责任与风险预算", href: "#reality-gate", actionLabel: "前往处理", template: "/startup/g0-governance.csv", templateLabel: "治理模板", secondaryTemplate: null, secondaryTemplateLabel: null },
    { id: "OZN-001", title: "核验 Ozon 账户与只读权限", href: "#reality-gate", actionLabel: "前往处理", template: "/startup/g0-ozon-access.csv", templateLabel: "权限模板", secondaryTemplate: "/startup/g0-ozon-api-identities.csv", secondaryTemplateLabel: "身份盘点" },
    { id: "SKU-000", title: "取得合格需求研究依据", href: "https://data.ozon.ru/app", actionLabel: "打开 Ozon Data", template: null, templateLabel: null, secondaryTemplate: null, secondaryTemplateLabel: null },
    { id: "SKU-001", title: "研究并交接 3 个真实候选 SKU", href: "#candidate-research", actionLabel: "进入候选研究", template: "/startup/candidate-research.csv", templateLabel: "研究模板", secondaryTemplate: "/startup/sku-passports.csv", secondaryTemplateLabel: "Passport 模板" },
    { id: "SKU-002", title: "复核 Passport 并准备真实商品素材", href: "#passport-review", actionLabel: "前往处理", template: "/startup/sku-media.csv", templateLabel: "素材模板", secondaryTemplate: null, secondaryTemplateLabel: null },
    { id: "SKU-003", title: "补齐每个 SKU 的三家报价", href: "#sourcing-intake", actionLabel: "前往处理", template: "/startup/supplier-quotes.csv", templateLabel: "报价模板", secondaryTemplate: null, secondaryTemplateLabel: null },
    { id: "FIN-001", title: "导入结算、银行与 FX 样本", href: "#ozon-import", actionLabel: "前往处理", template: "/startup/finance-reconciliation.csv", templateLabel: "财务模板", secondaryTemplate: null, secondaryTemplateLabel: null },
  ];
  const nextStartupStep = startupSteps.find((item) => !requirement(item.id)?.ready);
  const canReviewFinance = webSession?.roles.some((role) => ["reviewer", "compliance", "admin"].includes(role)) ?? false;
  const canReviewExecutionAuthority = canReviewFinance;
  const actualCostAuthorityItem = costAuthorityCatalog?.items.find((item) => item.cost_type === actualCostType);
  const reviewableCostEvidence = evidenceRecords.filter((item) => item.source !== "cost_actual_authority_review");
  const researchSignals = evidenceRecords.filter((record) => record.metadata.evidence_role === "research_signal");

  return {
    webSession,
    setWebSession,
    health,
    setHealth,
    operatingWorkbench,
    setOperatingWorkbench,
    recommendations,
    setRecommendations,
    sourceConnectors,
    setSourceConnectors,
    offers,
    setOffers,
    products,
    setProducts,
    comparisons,
    setComparisons,
    marketplaceCatalogItems,
    setMarketplaceCatalogItems,
    marketplaceCatalogLoaded,
    setMarketplaceCatalogLoaded,
    marketplaceCatalogBusy,
    setMarketplaceCatalogBusy,
    marketplaceCatalogStoreRef,
    setMarketplaceCatalogStoreRef,
    marketplaceGrowthPlan,
    setMarketplaceGrowthPlan,
    marketplaceGrowthObservations,
    setMarketplaceGrowthObservations,
    marketplaceGrowthFactsLoaded,
    setMarketplaceGrowthFactsLoaded,
    marketplaceGrowthBusy,
    setMarketplaceGrowthBusy,
    approvals,
    setApprovals,
    sampleOrders,
    setSampleOrders,
    supplierPerformance,
    setSupplierPerformance,
    backupOptions,
    setBackupOptions,
    backupRationales,
    setBackupRationales,
    skuReadiness,
    setSkuReadiness,
    productMediaReadiness,
    setProductMediaReadiness,
    contentAssets,
    setContentAssets,
    passportReviews,
    setPassportReviews,
    gateReadiness,
    setGateReadiness,
    evidenceRecords,
    setEvidenceRecords,
    interactionProfiles,
    setInteractionProfiles,
    decisionContracts,
    setDecisionContracts,
    decisionAnalyses,
    setDecisionAnalyses,
    decisionReviews,
    setDecisionReviews,
    decisionResolutions,
    setDecisionResolutions,
    decisionOutcomes,
    setDecisionOutcomes,
    decisionCalibration,
    setDecisionCalibration,
    causalExperiments,
    setCausalExperiments,
    experimentEvaluations,
    setExperimentEvaluations,
    causalExperimentReviews,
    setCausalExperimentReviews,
    causalKnowledge,
    setCausalKnowledge,
    causalPolicies,
    setCausalPolicies,
    policyShadowBatches,
    setPolicyShadowBatches,
    policyActivationHandoffs,
    setPolicyActivationHandoffs,
    governedExecutionPlans,
    setGovernedExecutionPlans,
    limitedExecutionCommands,
    setLimitedExecutionCommands,
    executionObservationWindows,
    setExecutionObservationWindows,
    capabilityEconomicAssessments,
    setCapabilityEconomicAssessments,
    operationalIncidents,
    setOperationalIncidents,
    operationsQueue,
    setOperationsQueue,
    readOnlyPilots,
    setReadOnlyPilots,
    pilotEvaluations,
    setPilotEvaluations,
    selectedProfileId,
    setSelectedProfileId,
    selectedAnalysisContractId,
    setSelectedAnalysisContractId,
    selectedAnalysisOptionId,
    setSelectedAnalysisOptionId,
    decisionBusy,
    setDecisionBusy,
    lifecycleBusy,
    setLifecycleBusy,
    uploading,
    setUploading,
    lastOzonImport,
    setLastOzonImport,
    financeReviewStatus,
    setFinanceReviewStatus,
    financeReviewImportId,
    setFinanceReviewImportId,
    financeReviewBusy,
    setFinanceReviewBusy,
    costAuthorityCatalog,
    setCostAuthorityCatalog,
    actualCostAuthorityStatus,
    setActualCostAuthorityStatus,
    actualCostEvidenceId,
    setActualCostEvidenceId,
    actualCostType,
    setActualCostType,
    actualCostReviewBusy,
    setActualCostReviewBusy,
    feeCodeStatus,
    setFeeCodeStatus,
    feeMappingBusy,
    setFeeMappingBusy,
    accrualClassificationStatus,
    setAccrualClassificationStatus,
    accrualClassificationBusy,
    setAccrualClassificationBusy,
    gateUploading,
    setGateUploading,
    candidateEvidenceUploading,
    setCandidateEvidenceUploading,
    candidateAuthorityBusy,
    setCandidateAuthorityBusy,
    candidateAuthorityStatus,
    setCandidateAuthorityStatus,
    candidateResearchBusy,
    setCandidateResearchBusy,
    candidateAssessment,
    setCandidateAssessment,
    candidateHandoffBusy,
    setCandidateHandoffBusy,
    candidateHandoff,
    setCandidateHandoff,
    skuUploading,
    setSkuUploading,
    productMediaUploading,
    setProductMediaUploading,
    imageBriefBusy,
    setImageBriefBusy,
    imageExecutionBusy,
    setImageExecutionBusy,
    imageQaBusy,
    setImageQaBusy,
    listingDraftBusy,
    setListingDraftBusy,
    reviewingKey,
    setReviewingKey,
    reviewNotes,
    setReviewNotes,
    sourcingUploading,
    setSourcingUploading,
    procurementDrafts,
    setProcurementDrafts,
    procurementBusy,
    setProcurementBusy,
    notice,
    setNotice,
    domainStates,
    setDomainStates,
    load,
    upload,
    loadFinanceReviewStatus,
    reviewFinanceReport,
    loadActualCostAuthorityStatus,
    reviewActualCostAuthority,
    loadFeeCodeStatus,
    approveFeeMapping,
    loadAccrualClassificationStatus,
    approveAccrualClassification,
    uploadGateEvidence,
    uploadDemandReport,
    reviewDemandReport,
    uploadCandidateEvidence,
    loadCandidateAuthorityStatus,
    reviewCandidateEvidenceAuthority,
    submitCandidateResearch,
    createCandidateSourcingWorkspace,
    uploadSkuEpisode,
    uploadProductMedia,
    createImageBrief,
    runImageGeneration,
    reviewImageAsset,
    createListingDraft,
    reviewPassport,
    uploadSupplierComparison,
    importMarketplaceCatalog,
    loadMarketplaceCatalog,
    planMarketplaceGrowth,
    loadMarketplaceGrowthFacts,
    planLatestMarketplaceGrowth,
    requestProcurement,
    createSampleOrder,
    recordSampleEvent,
    loadBackupOptions,
    requestBackupProcurement,
    compileDecisionContract,
    submitDecisionAnalysis,
    reviewDecisionAnalysis,
    resolveDecisionAnalysis,
    recordDecisionOutcome,
    registerCausalExperiment,
    transitionCausalExperiment,
    recordExperimentSafety,
    reviewCausalExperiment,
    publishCausalKnowledge,
    proposeCausalPolicy,
    reviewCausalPolicy,
    releaseCausalPolicyStage,
    recordCausalPolicyOutcome,
    runPolicyShadowBatch,
    requestPolicyActivation,
    prepareListingExecutionPlan,
    reviewListingRussianNative,
    reviewOzonExecutionIdentity,
    dryRunExecutionPlan,
    queueLimitedExecution,
    createObservationWindow,
    recordExecutionObservation,
    assessCapabilityEconomics,
    claimIncident,
    recordIncidentCheck,
    submitIncidentReview,
    reviewIncident,
    releaseIncidentFreeze,
    closeIncident,
    scanOperationsQueue,
    createReadOnlyPilot,
    attestPilotControl,
    submitPilotReview,
    reviewPilot,
    activatePilot,
    demandSourceReports,
    demandRequirement,
    acceptedDemandReportIds,
    acceptedDemandReports,
    researchReadiness,
    realExecutionReadiness,
    pendingProcurementApprovals,
    pendingListingApprovals,
    approvedListingApprovals,
    listingExecutionPlans,
    causalPolicyExecutionPlans,
    approvedWithoutSample,
    selectedProfile,
    selectedAnalysisContract,
    analysisOptions,
    analysisContext,
    analysisHardConstraints,
    isBestSolutionAnalysis,
    analysisNeedsForecast,
    experimentResolutions,
    requirement,
    startupSteps,
    nextStartupStep,
    canReviewFinance,
    canReviewExecutionAuthority,
    actualCostAuthorityItem,
    reviewableCostEvidence,
    researchSignals
  };
}

export type DashboardModel = ReturnType<typeof useDashboardController>;
