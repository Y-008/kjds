"use client";

import {
  Activity,
  BarChart3,
  Boxes,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  Database,
  FileUp,
  FlaskConical,
  Image as ImageIcon,
  LayoutDashboard,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
  Waypoints,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";

type Health = { name: string; status: string; detail?: string | null };
type Recommendation = {
  id: string;
  agent: string;
  action: string;
  expected_cm3_delta?: string | null;
  risk: string;
  status: string;
  shadow_mode: boolean;
};
type SourceConnector = {
  platform: string;
  ingestion: string;
  authentication: string;
  status: string;
  notes: string;
};
type PassportReadiness = {
  kind: "product" | "compliance" | "quality";
  status: "missing" | "draft" | "awaiting_approval" | "approved" | "blocked";
  missing_fields: string[];
  evidence_count: number;
};
type ProductReadiness = {
  product: { id: string; sku: string; name: string; status: string };
  passports: PassportReadiness[];
  ready_for_validation: boolean;
};
type PassportReview = {
  product: { id: string; sku: string; name: string };
  passport: {
    id: string;
    kind: "product" | "compliance" | "quality";
    version: number;
    facts: Record<string, unknown>;
    evidence: string[];
    missing_fields: string[];
    created_at: string;
  };
};
type ProductIdentity = { id: string; sku: string; name: string };
type SourcingComparison = {
  product: ProductIdentity;
  supplier_count: number;
  offer_count: number;
  scenario_count: number;
  ready_for_procurement_review: boolean;
  rows: Array<{
    offer: { id: string; supplier_ref: string; platform: string; title: string; unit_price: string; currency: string; min_order_quantity: number; evidence_ref: string };
    scenario: null | { id: string; cm3_cny: string; cm3_rate: string; break_even_price_rub: string; evidence: string[] };
    has_positive_cm3: boolean;
  }>;
};
type ApprovalRecord = { id: string; action: string; resource_id: string; status: string; requested_by: string; payload: Record<string, unknown> };
type SampleEvent = { id: string; sequence: number; event_type: string; effective_at: string; evidence_id: string; facts: Record<string, unknown> };
type SampleOrder = {
  id: string; approval_id: string; product_id: string; product: { sku: string; name: string };
  offer_id: string; scenario_id: string; supplier_ref: string; quantity: number; currency: string;
  unit_price: string; status: string; next_events: string[]; events: SampleEvent[];
};
type SupplierPerformance = {
  supplier_ref: string; sample_order_count: number; completed_sample_count: number; rejected_sample_count: number;
  quality_yield: string | null; delivery_completeness: string | null; on_time_rate: string | null;
  score: string | null; evidence_count: number;
};
type BackupOption = {
  offer: { id: string; supplier_ref: string; platform: string; unit_price: string; currency: string; min_order_quantity: number };
  scenario: { id: string; cm3_cny: string; cm3_rate: string; break_even_price_rub: string };
  supplier_performance: SupplierPerformance | null;
  advisory_only: boolean;
};
type GateRequirement = {
  id: string;
  title: string;
  ready: boolean;
  status: "ready_for_review" | "needs_input";
  current: number;
  target: number;
  next_action: string;
};
type GateReadiness = {
  status: "ready_for_review" | "needs_input";
  g0: "ready_for_review" | "blocked";
  g1: "ready_for_review" | "blocked";
  requirements: GateRequirement[];
  next_actions: string[];
};
type EvidenceSummary = { id: string; filename: string; source: string; grade: string; effective_at: string };
type InteractionProfile = {
  id: string; version: string; label: string; description: string; aliases: string[];
  workflow_steps: string[]; output_requirements: string[]; max_questions: number;
  presentation_only: boolean; evidence_required_before_conclusion: boolean;
  requires_options: boolean; requires_forecast_basis: boolean;
};
type DecisionContract = {
  id: string; profile_id: string; profile_version: string; objective: string; decision_domain: string;
  risk_level: string; horizon_days: number | null; maximum_loss_amount: string | null; currency: string;
  source_contract_id: string | null; input: Record<string, unknown>; output_requirements: string[];
  evidence_ids: string[]; compiler_policy: Record<string, boolean | string | number>;
  missing_inputs: string[]; status: string; execution_eligible: boolean;
  requires_human_approval: boolean; requested_by: string; created_at: string;
};
type DecisionAnalysis = {
  id: string; contract_id: string; conclusion: string; recommended_option_id: string | null;
  confidence: string; forecast: null | { metric: string; value: string; low: string; high: string; unit: string; due_at: string };
  assumptions: string[]; unknowns: string[]; evidence_ids: string[]; model_ref: string | null;
  submitted_by: string; execution_eligible: boolean; created_at: string;
};
type DecisionReview = { id: string; analysis_id: string; verdict: string; rationale: string; counterarguments: string[]; evidence_ids: string[]; reviewed_by: string; created_at: string };
type DecisionResolution = { id: string; contract_id: string; analysis_id: string; disposition: string; rationale: string; conditions: string[]; decided_by: string; execution_eligible: boolean; created_at: string };
type DecisionOutcome = { id: string; resolution_id: string; metric: string; predicted_value: string; interval_low: string; interval_high: string; actual_value: string; unit: string; signed_error: string; absolute_error: string; interval_covered: boolean; observed_at: string; evidence_ids: string[]; notes: string; recorded_by: string; created_at: string };
type DecisionCalibration = { metric: string; unit: string; outcome_count: number; mean_absolute_error: string; mean_absolute_percentage_error: string | null; interval_coverage: string };
type CausalExperiment = {
  id: string; resolution_id: string; hypothesis: string; primary_metric: string;
  randomization_unit: string; interference_cluster: string | null;
  variants: Array<{ id: string; label: string; allocation: string; control: boolean }>;
  target_sample_size: number; minimum_detectable_effect: string;
  budget_cap_amount: string; stop_loss_amount: string; currency: string;
  start_at: string; end_at: string; outcome_window_days: number;
  guardrails: Array<{ metric: string; direction: string; threshold: string }>;
  stratification_keys: string[];
  effect_metrics: Array<{ metric: string; role: string; multiplier: string; required: boolean }>;
  evidence_ids: string[]; status: string;
  events: Array<{ id: string; event_type: string; effective_at: string }>;
};
type ExperimentEvaluation = {
  protocol_id: string; status: string; review_eligible: boolean; decision_eligible: boolean;
  automatic_rollout: boolean; assignment_count: number; observed_count: number;
  target_sample_size: number; sample_ratio_p_value: string; sample_ratio_mismatch: boolean;
  safety_gate_breached: boolean;
  safety_checks: Array<{ id: string; metric: string; value: string; threshold: string; status: string; observed_at: string }>;
  treatment_effect: null | { absolute_effect: string; relative_effect: string | null; confidence_interval_95: string[] };
  incremental_value_per_unit: string | null;
  missing_required_metrics: string[];
  heterogeneous_effects: Array<{ key: string; segments: Array<{ value: string; estimable: boolean; effect: null | { absolute_effect: string } }> }>;
  interpretation: string;
};
type CausalExperimentReview = {
  id: string; protocol_id: string; evaluation_hash: string; verdict: string; rationale: string;
  method_assessment: string; data_quality_assessment: string; counterarguments: string[];
  evidence_ids: string[]; reviewed_by: string; created_at: string; immutable: boolean;
};
type CausalKnowledgeEntry = {
  id: string; protocol_id: string; review_id: string; claim: string; mechanism: string;
  applicability: Record<string, unknown>; falsification_conditions: string[];
  effect_snapshot: { primary_metric: string; incremental_value_per_unit: string | null };
  evidence_ids: string[]; valid_from: string; reevaluate_at: string; validity_status: string;
  usable: boolean; knowledge_strength: string; execution_eligible: boolean; automatic_rollout: boolean;
  replication_of: null | { source_knowledge_id: string; scope_relation: string };
  replications: Array<{ replication_knowledge_id: string; scope_relation: string }>;
};
type CausalPolicy = {
  id: string; title: string; objective: string; knowledge_ids: string[]; applicability: Record<string, unknown>;
  conditions: Array<{ field: string; operator: string; value: unknown }>;
  action: { type: string; parameters: Record<string, unknown> };
  fallback_action: { type: string; parameters: Record<string, unknown> };
  guardrails: Array<{ metric: string; direction: string; threshold: string }>;
  rollout_stages: Array<{ name: string; max_exposure_fraction: string; minimum_observation_count: number; minimum_incremental_value: string }>;
  reviews: Array<{ id: string; verdict: string; rationale: string; reviewed_by: string }>;
  releases: Array<{ id: string; stage_index: number; stage: { name: string; max_exposure_fraction: string }; automatic_promotion: boolean; outcome: null | { verdict: string; observation_count: number; incremental_value: string; guardrail_breached: boolean } }>;
  proposed_by: string; usable: boolean; validity_status: string; execution_eligible: boolean; automatic_execution: boolean;
};
type PolicyShadowBatch = {
  id: string; policy_id: string; release_id: string; evaluation_ids: string[]; context_count: number;
  matched_count: number; fallback_count: number; zero_exposure: boolean; execution_eligible: boolean; created_at: string;
};
type PolicyActivationHandoff = {
  id: string; policy_id: string; release_id: string; approval_id: string; approval_status: string;
  validity_status: string; activation_eligible: boolean; execution_eligible: boolean; created_at: string;
};
type GovernedExecutionPlan = {
  id: string; handoff_id: string; policy_id: string; release_id: string; adapter_id: string;
  target: Record<string, string>; precondition_state_hash: string;
  intended_patch: Record<string, unknown>; rollback_patch: Record<string, unknown>;
  approval_id: string; approval_status: string; handoff_validity_status: string;
  dry_run: null | { id: string; passed: boolean; platform_write_performed: boolean };
  ready_for_executor: boolean; execution_eligible: boolean; live_execution_supported: boolean;
};
type LimitedExecutionCommand = {
  id: string; plan_id: string; parent_command_id: string | null; command_kind: "execute" | "rollback";
  idempotency_token: string; operation: string; target: Record<string, string>;
  expected_state_hash: string; status: string; claimed_by: string | null;
  receipt: null | { outcome: string; mutation_applied: boolean; rollback_command_id: string | null };
  platform_write_performed: boolean;
};
type ExecutionObservationWindow = {
  id: string; command_id: string; plan_id: string; policy_id: string;
  primary_metric: string; baseline: Record<string, string>;
  guardrails: Array<{ metric: string; direction: "min" | "max"; threshold: string }>;
  required_observations: number; starts_at: string; ends_at: string; status: string;
  observations: Array<{ id: string; metric: string; value: string; observed_at: string; guardrail_breached: boolean; rollback_command_id: string | null }>;
  evaluation: { status: string; rollback_queued: boolean; kill_switch_engaged: boolean };
  automatic_policy_promotion: boolean;
};
type CapabilityEconomicAssessment = {
  id: string; window_id: string; adapter_id: string; outcome_status: string;
  realized_incremental_value: string; avoided_loss: string; model_compute_cost: string;
  human_review_cost: string; incident_loss: string; maintenance_cost: string;
  net_value: string; currency: string; automatic_authority_change: boolean;
};

const passportLabels = { product: "商品资料", compliance: "俄罗斯合规", quality: "样品质量" } as const;
const procurementStatusLabels: Record<string, string> = {
  approved_to_order: "已批准，待确认样品单", order_confirmed: "供应商已确认", shipped: "样品运输中",
  received: "样品已签收", inspected: "验货完成，待决定", rework_required: "需要返工复验",
  golden_sample_approved: "黄金样已批准", sample_rejected: "样品已淘汰", cancelled: "样品单已取消",
};
const procurementEventLabels: Record<string, string> = {
  order_confirmed: "确认样品订单", shipped: "记录发货", received: "记录签收", inspection_completed: "完成验货",
  golden_sample_approved: "批准黄金样", sample_rejected: "淘汰样品", rework_required: "要求返工", cancelled: "取消",
};
const decisionStatusLabels: Record<string, string> = {
  clarification_required: "需要补充关键信息", ready_for_clarification: "可以开始澄清",
  evidence_pending: "等待可验证证据", ready_for_render: "可以生成通俗解释",
  ready_for_analysis: "可以进入分析",
};

const nav = [
  [LayoutDashboard, "经营总览", true],
  [FileUp, "数据中心", false],
  [Waypoints, "全球货源", false],
  [Boxes, "商品中心", false],
  [BrainCircuit, "AI 工作台", false],
  [ImageIcon, "内容工厂", false],
  [FlaskConical, "增长实验", false],
  [CircleDollarSign, "利润中心", false],
  [ShieldCheck, "审批中心", false],
] as const;

export default function Home() {
  const [health, setHealth] = useState<Record<string, Health>>({});
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [sourceConnectors, setSourceConnectors] = useState<SourceConnector[]>([]);
  const [offers, setOffers] = useState<unknown[]>([]);
  const [products, setProducts] = useState<ProductIdentity[]>([]);
  const [comparisons, setComparisons] = useState<SourcingComparison[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRecord[]>([]);
  const [sampleOrders, setSampleOrders] = useState<SampleOrder[]>([]);
  const [supplierPerformance, setSupplierPerformance] = useState<SupplierPerformance[]>([]);
  const [backupOptions, setBackupOptions] = useState<Record<string, BackupOption[]>>({});
  const [backupRationales, setBackupRationales] = useState<Record<string, string>>({});
  const [skuReadiness, setSkuReadiness] = useState<ProductReadiness[]>([]);
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
  const [selectedProfileId, setSelectedProfileId] = useState("evidence_research");
  const [selectedAnalysisContractId, setSelectedAnalysisContractId] = useState("");
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [lifecycleBusy, setLifecycleBusy] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [gateUploading, setGateUploading] = useState(false);
  const [skuUploading, setSkuUploading] = useState(false);
  const [reviewingKey, setReviewingKey] = useState<string | null>(null);
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [sourcingUploading, setSourcingUploading] = useState(false);
  const [procurementDrafts, setProcurementDrafts] = useState<Record<string, { quantity: string; rationale: string }>>({});
  const [procurementBusy, setProcurementBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("等待第一份 Ozon 数据");

  const load = useCallback(async () => {
    const [healthResponse, recommendationResponse, connectorResponse, offersResponse, productsResponse, gateResponse, reviewResponse, approvalsResponse, sampleOrdersResponse, supplierPerformanceResponse, evidenceResponse, profileResponse, contractResponse, analysisResponse, resolutionResponse, outcomeResponse, calibrationResponse, experimentResponse, causalKnowledgeResponse, causalPolicyResponse, policyShadowResponse, policyHandoffResponse, executionPlanResponse, executionCommandResponse, executionObservationResponse, capabilityEconomicsResponse] = await Promise.all([
      fetch("/backend/v1/integrations/health", { cache: "no-store" }),
      fetch("/backend/v1/recommendations", { cache: "no-store" }),
      fetch("/backend/v1/sourcing/connectors", { cache: "no-store" }),
      fetch("/backend/v1/sourcing/offers", { cache: "no-store" }),
      fetch("/backend/v1/products", { cache: "no-store" }),
      fetch("/backend/v1/operations/readiness", { cache: "no-store" }),
      fetch("/backend/v1/passport-reviews", { cache: "no-store" }),
      fetch("/backend/v1/approvals", { cache: "no-store" }),
      fetch("/backend/v1/procurement/sample-orders", { cache: "no-store" }),
      fetch("/backend/v1/procurement/suppliers/performance", { cache: "no-store" }),
      fetch("/backend/v1/evidence", { cache: "no-store" }),
      fetch("/backend/v1/interaction-profiles", { cache: "no-store" }),
      fetch("/backend/v1/decision-contracts", { cache: "no-store" }),
      fetch("/backend/v1/decision-analyses", { cache: "no-store" }),
      fetch("/backend/v1/decision-resolutions", { cache: "no-store" }),
      fetch("/backend/v1/decision-outcomes", { cache: "no-store" }),
      fetch("/backend/v1/decision-calibration", { cache: "no-store" }),
      fetch("/backend/v1/causal-experiments", { cache: "no-store" }),
      fetch("/backend/v1/causal-knowledge", { cache: "no-store" }),
      fetch("/backend/v1/causal-policies", { cache: "no-store" }),
      fetch("/backend/v1/causal-policy-shadow-batches", { cache: "no-store" }),
      fetch("/backend/v1/causal-policy-activation-handoffs", { cache: "no-store" }),
      fetch("/backend/v1/governed-execution-plans", { cache: "no-store" }),
      fetch("/backend/v1/limited-execution-commands", { cache: "no-store" }),
      fetch("/backend/v1/execution-observation-windows", { cache: "no-store" }),
      fetch("/backend/v1/capability-economic-assessments", { cache: "no-store" }),
    ]);
    if (healthResponse.ok) setHealth(await healthResponse.json());
    if (recommendationResponse.ok) setRecommendations(await recommendationResponse.json());
    if (connectorResponse.ok) setSourceConnectors(await connectorResponse.json());
    if (offersResponse.ok) setOffers(await offersResponse.json());
    if (gateResponse.ok) setGateReadiness(await gateResponse.json());
    if (reviewResponse.ok) setPassportReviews(await reviewResponse.json());
    if (approvalsResponse.ok) setApprovals(await approvalsResponse.json());
    if (sampleOrdersResponse.ok) setSampleOrders(await sampleOrdersResponse.json());
    if (supplierPerformanceResponse.ok) setSupplierPerformance(await supplierPerformanceResponse.json());
    if (evidenceResponse.ok) setEvidenceRecords(await evidenceResponse.json());
    if (profileResponse.ok) setInteractionProfiles(await profileResponse.json());
    if (contractResponse.ok) setDecisionContracts(await contractResponse.json());
    if (analysisResponse.ok) {
      const rows: DecisionAnalysis[] = await analysisResponse.json();
      setDecisionAnalyses(rows);
      const reviews = await Promise.all(rows.map(async (item) => {
        const response = await fetch(`/backend/v1/decision-analyses/${item.id}/reviews`, { cache: "no-store" });
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
        const response = await fetch(`/backend/v1/causal-experiments/${item.id}/evaluation`, { cache: "no-store" });
        return [item.id, response.ok ? await response.json() as ExperimentEvaluation : null] as const;
      }));
      const indexed: Record<string, ExperimentEvaluation> = {};
      evaluations.forEach(([id, evaluation]) => { if (evaluation) indexed[id] = evaluation; });
      setExperimentEvaluations(indexed);
      const reviews = await Promise.all(rows.map(async (item) => {
        const response = await fetch(`/backend/v1/causal-experiments/${item.id}/reviews`, { cache: "no-store" });
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
    if (productsResponse.ok) {
      const products: ProductIdentity[] = await productsResponse.json();
      setProducts(products);
      const readiness = await Promise.all(
        products.slice(0, 3).map(async (product) => {
          const response = await fetch(`/backend/v1/products/${product.id}/readiness`, { cache: "no-store" });
          return response.ok ? response.json() as Promise<ProductReadiness> : null;
        }),
      );
      setSkuReadiness(readiness.filter((item): item is ProductReadiness => item !== null));
      const comparisonRows = await Promise.all(products.slice(0, 3).map(async (product) => {
        const response = await fetch(`/backend/v1/sourcing/comparisons/${product.id}`, { cache: "no-store" });
        return response.ok ? response.json() as Promise<SourcingComparison> : null;
      }));
      setComparisons(comparisonRows.filter((item): item is SourcingComparison => item !== null && item.offer_count > 0));
    }
  }, []);

  useEffect(() => {
    load().catch(() => setNotice("后端尚未启动，请先启动 KJDS 服务"));
  }, [load]);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("file") as HTMLInputElement;
    if (!input.files?.[0]) return;
    setUploading(true);
    setNotice("正在校验并导入 Ozon 文件…");
    const body = new FormData();
    body.append("file", input.files[0]);
    try {
      const response = await fetch("/backend/v1/imports/ozon", { method: "POST", body });
      const result = await response.json();
      setNotice(
        response.ok
          ? `导入完成：${result.accepted_count} 行可用，${result.rejected_count} 行需检查`
          : result.detail ?? "导入失败",
      );
      if (response.ok) form.reset();
    } catch {
      setNotice("无法连接后端，请检查服务状态");
    } finally {
      setUploading(false);
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
      const response = await fetch("/backend/v1/operations/gate-evidence", { method: "POST", body });
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
      const response = await fetch("/backend/v1/intake/sku-episodes", { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${result.product.sku} 已建立，等待三类 Passport 人工复核` : result.detail ?? "SKU 录入失败");
      if (response.ok) { form.reset(); await load(); }
    } catch {
      setNotice("无法提交 SKU Episode，请检查服务状态");
    } finally {
      setSkuUploading(false);
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
      const response = await fetch(
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
      advertising_rate: value("advertising_rate"), return_reserve_rate: value("return_reserve_rate"), other_cost_cny: value("other_cost_cny"),
    };
    const body = new FormData();
    body.append("product_id", value("sourcing_product_id")); body.append("effective_at", new Date().toISOString());
    body.append("offers_json", JSON.stringify(offerRows)); body.append("profit_inputs_json", JSON.stringify(profitInputs));
    evidenceFiles.forEach((item, index) => body.append(`offer_evidence_${index + 1}`, item as File));
    body.append("assumption_evidence", assumptions);
    setSourcingUploading(true); setNotice("正在固化三家报价并计算可比 CM3…");
    try {
      const response = await fetch("/backend/v1/sourcing/comparison-intake", { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${result.comparison.product.sku} 已完成三家证据化报价比较` : result.detail ?? "报价比较录入失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法提交供应商比较，请检查服务状态"); }
    finally { setSourcingUploading(false); }
  }

  async function requestProcurement(comparison: SourcingComparison, row: SourcingComparison["rows"][number]) {
    if (!row.scenario) return;
    const draft = procurementDrafts[row.offer.id] ?? { quantity: String(row.offer.min_order_quantity), rationale: "" };
    if (!draft.rationale.trim()) { setNotice("提交采购审批前必须填写选择理由"); return; }
    try {
      const response = await fetch("/backend/v1/sourcing/procurement-candidates", {
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
      const response = await fetch("/backend/v1/procurement/sample-orders", {
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
      const response = await fetch(`/backend/v1/procurement/sample-orders/${order.id}/events`, { method: "POST", body });
      const result = await response.json();
      setNotice(response.ok ? `${order.product.sku} 已更新：${procurementStatusLabels[result.status] ?? result.status}` : result.detail ?? "样品进度提交失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法记录样品进度，请检查服务状态"); }
    finally { setProcurementBusy(null); }
  }

  async function loadBackupOptions(orderId: string) {
    setProcurementBusy(orderId);
    try {
      const response = await fetch(`/backend/v1/procurement/sample-orders/${orderId}/backup-options`, { cache: "no-store" });
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
      const response = await fetch("/backend/v1/sourcing/procurement-candidates", {
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
      const response = await fetch("/backend/v1/decision-contracts", {
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
    const dueValue = value("analysis_due_at");
    const body = {
      conclusion: value("analysis_conclusion"), confidence: value("analysis_confidence"),
      recommended_option_id: value("analysis_option_id") || null,
      forecast_metric: value("analysis_metric"), forecast_value: value("analysis_value"),
      forecast_low: value("analysis_low"), forecast_high: value("analysis_high"),
      forecast_unit: value("analysis_unit"), forecast_due_at: dueValue ? new Date(dueValue).toISOString() : null,
      assumptions: lines("analysis_assumptions"), unknowns: lines("analysis_unknowns"),
      evidence_ids: [value("analysis_evidence")].filter(Boolean), model_ref: value("analysis_model_ref") || null,
    };
    setLifecycleBusy("analysis"); setNotice("正在固化分析、预测区间与证据…");
    try {
      const response = await fetch(`/backend/v1/decision-contracts/${contractId}/analyses`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `分析 ${result.id} 已提交，必须由另一身份独立复核；仍无执行权。` : result.detail ?? "分析提交失败");
      if (response.ok) { form.reset(); setSelectedAnalysisContractId(""); await load(); }
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
      const response = await fetch(`/backend/v1/decision-analyses/${analysisId}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/decision-contracts/${analysis.contract_id}/resolution`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/decision-resolutions/${resolutionId}/outcome`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/decision-resolutions/${resolutionId}/experiment`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/causal-experiments/${protocol.id}/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/causal-experiments/${protocol.id}/safety-checks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/causal-experiments/${protocol.id}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/causal-experiments/${protocol.id}/knowledge`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch("/backend/v1/causal-policies", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/causal-policies/${policy.id}/reviews`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/causal-policies/${policy.id}/releases`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/causal-policy-releases/${releaseId}/outcome`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/causal-policy-releases/${releaseId}/shadow-batches`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/causal-policy-releases/${releaseId}/activation-handoff`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ evaluation_ids: batch.evaluation_ids, evidence_ids: [evidenceId] }) });
      const result = await response.json();
      setNotice(response.ok ? `已进入审批中心：${result.approval_id}。即使批准，也仍需独立执行适配器。` : result.detail ?? "审批交接失败");
      if (response.ok) await load();
    } catch { setNotice(`无法提交 ${policy.title} 的阶段交接`); }
    finally { setLifecycleBusy(null); }
  }

  async function createExecutionPlan(event: FormEvent<HTMLFormElement>, handoff: PolicyActivationHandoff) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const body = {
      idempotency_key: `listing-draft-${value("execution_listing_id")}`,
      adapter_id: "ozon.listing.draft.v1",
      target: { listing_id: value("execution_listing_id") },
      precondition_state_hash: value("execution_state_hash"),
      intended_patch: { title: value("execution_new_title") },
      rollback_patch: { title: value("execution_old_title") },
      evidence_ids: [value("execution_evidence")],
    };
    setLifecycleBusy(`execution-plan:${handoff.id}`); setNotice("正在建立可回滚执行计划并申请第二次独立审批…");
    try {
      const response = await fetch(`/backend/v1/causal-policy-activation-handoffs/${handoff.id}/execution-plans`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `执行计划 ${result.id} 已固化并进入审批；当前仍不支持平台写入。` : result.detail ?? "执行计划建立失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法建立执行计划，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function dryRunExecutionPlan(event: FormEvent<HTMLFormElement>, plan: GovernedExecutionPlan) {
    event.preventDefault();
    const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    setLifecycleBusy(`execution-dry-run:${plan.id}`); setNotice("正在核对当前平台快照、动作白名单和回滚合同；不会写入平台…");
    try {
      const response = await fetch(`/backend/v1/governed-execution-plans/${plan.id}/dry-run`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ current_state_hash: value("dry_run_state_hash"), evidence_ids: [value("dry_run_evidence")] }) });
      const result = await response.json();
      setNotice(response.ok ? `预演${result.passed ? "通过" : "失败"}；平台写入：${result.platform_write_performed ? "发生" : "未发生"}。` : result.detail ?? "预演失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法完成执行预演，请检查服务状态"); }
    finally { setLifecycleBusy(null); }
  }

  async function queueLimitedExecution(plan: GovernedExecutionPlan) {
    setLifecycleBusy(`execution-queue:${plan.id}`); setNotice("正在重新核验知识、阶段交接、预演和双审批，并尝试进入受限执行队列…");
    try {
      const response = await fetch(`/backend/v1/governed-execution-plans/${plan.id}/commands`, { method: "POST" });
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
      const response = await fetch(`/backend/v1/limited-execution-commands/${command.id}/observation-window`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/execution-observation-windows/${window.id}/observations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? (result.guardrail_breached ? `护栏已越界：补偿命令 ${result.rollback_command_id} 已排队，全部写操作已冻结，等待人工确认后执行回滚。` : "结果已记录，护栏正常，继续观察。") : result.detail ?? "结果记录失败");
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
      const response = await fetch(`/backend/v1/execution-observation-windows/${window.id}/capability-economics`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `能力净价值：${result.net_value} ${result.currency}。该结果只形成治理建议，不会自动改变权限。` : result.detail ?? "能力损益核算失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法完成能力损益核算，请检查观察是否结束及证据是否有效"); }
    finally { setLifecycleBusy(null); }
  }

  const toolCount = Object.values(health).filter((item) => item.status === "ok").length;
  const readySkuCount = skuReadiness.filter((item) => item.ready_for_validation).length;
  const pendingProcurementApprovals = approvals.filter((item) => item.action === "procurement.place_order" && item.status === "pending").length;
  const approvedWithoutSample = approvals.filter((item) => item.action === "procurement.place_order" && item.status === "approved" && !sampleOrders.some((order) => order.approval_id === item.id));
  const selectedProfile = interactionProfiles.find((item) => item.id === selectedProfileId);
  const selectedAnalysisContract = decisionContracts.find((item) => item.id === selectedAnalysisContractId);
  const analysisOptions = Array.isArray(selectedAnalysisContract?.input.options) ? selectedAnalysisContract.input.options as Array<{ id?: string; label?: string }> : [];
  const experimentResolutions = decisionResolutions.filter((item) => item.disposition === "experiment" && !causalExperiments.some((experiment) => experiment.resolution_id === item.id));

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">K</div>
          <div><strong>KJDS</strong><span>俄罗斯经营系统</span></div>
        </div>
        <nav>
          {nav.map(([Icon, label, active]) => (
            <button className={active ? "active" : ""} key={label}><Icon size={19} /><span>{label}</span>{active && <ChevronRight size={16} />}</button>
          ))}
        </nav>
        <div className="sidebar-status">
          <span className="pulse" />
          <div><strong>14天影子运行</strong><span>只建议，不执行高风险动作</span></div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div><p className="eyebrow">OZON · RUSSIA</p><h1>经营指挥中心</h1></div>
          <button className="refresh" onClick={() => load()}><RefreshCw size={17} />刷新状态</button>
        </header>

        <section className="hero">
          <div>
            <span className="hero-tag"><Sparkles size={15} />核心目标：单品净利润 CM3</span>
            <h2>先用真实数据跑通 3 个 SKU，<br />再把成功打法复制成规模。</h2>
            <p>系统会追踪证据、利润、内容和实验结果；缺失数据会明确提示，不允许 AI 编造。</p>
          </div>
          <form className="upload" onSubmit={upload}>
            <FileUp size={23} />
            <label htmlFor="ozon-file">导入 Ozon 经营数据</label>
            <span>支持 CSV / XLSX，重复文件不会重复入库</span>
            <input id="ozon-file" name="file" type="file" accept=".csv,.xlsx" />
            <button disabled={uploading}>{uploading ? "正在导入…" : "选择文件并导入"}</button>
          </form>
        </section>

        <div className="notice"><Activity size={17} /><span>{notice}</span></div>

        <section className="decision-workbench">
          <div className="panel-title">
            <div><p className="eyebrow">DECISION CONTRACT COMPILER</p><h3>把问题变成可审计的决策合同</h3></div>
            <span className="gate ready">只分析，不执行经营动作</span>
          </div>
          <div className="procurement-guardrail"><ShieldCheck size={17} /><p><strong>“深度思考”等口令只负责选择流程。</strong><span>证据、备选方案、损失上限、责任人与人工审批仍是硬门槛；缺什么就明确显示什么。</span></p></div>
          <div className="interaction-mode-grid">
            {interactionProfiles.map((profile) => <button type="button" className={selectedProfileId === profile.id ? "selected" : ""} onClick={() => setSelectedProfileId(profile.id)} key={profile.id}>
              <span>{profile.aliases.join(" · ")}</span><strong>{profile.label}</strong><small>{profile.description}</small><em>v{profile.version}</em>
            </button>)}
          </div>
          <div className="decision-layout">
            <form className="decision-form" onSubmit={compileDecisionContract}>
              <div className="decision-form-head"><div><strong>{selectedProfile?.label ?? "选择一种工作方式"}</strong><small>{selectedProfile?.workflow_steps.join(" → ")}</small></div><BrainCircuit size={19} /></div>
              <div className="decision-fields">
                <label className="wide">你要解决的真实问题<textarea name="decision_objective" placeholder="例如：是否应把某 SKU 的首批样品量从 100 件增加到 300 件？" required /></label>
                <label>决策领域<input name="decision_domain" defaultValue="operations" placeholder="采购 / 定价 / 广告" required /></label>
                <label>风险等级<select name="decision_risk" defaultValue="medium"><option value="low">低风险</option><option value="medium">中风险</option><option value="high">高风险</option><option value="critical">重大不可逆风险</option></select></label>
                <label>最坏可承受损失<input name="decision_maximum_loss" type="number" min="0" step="0.01" placeholder="高风险问题必须填写" /></label>
                <label>币种<input name="decision_currency" defaultValue="CNY" maxLength={3} /></label>
                <label>观察期限（天）<input name="decision_horizon" type="number" min="1" max="3650" placeholder="预测模式必须填写" /></label>
                <label>可验证证据<select name="decision_evidence" defaultValue=""><option value="">暂未选择；系统会标为待证据</option>{evidenceRecords.slice(0, 100).map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename} · {item.source}</option>)}</select></label>
                {selectedProfile?.presentation_only && <label className="wide">要解释的来源合同<select name="source_contract_id" defaultValue=""><option value="">选择一份已有合同</option>{decisionContracts.map((item) => <option value={item.id} key={item.id}>{item.id} · {item.objective}</option>)}</select></label>}
                {selectedProfile?.requires_options && <label className="wide">备选方案（每行一个，至少两个）<textarea name="decision_options" placeholder={"方案 A\n方案 B\n不行动"} /></label>}
                {selectedProfile?.requires_forecast_basis && <><label className="wide">基准情景 / 基础概率<textarea name="forecast_baseline" placeholder="写明历史基准、匹配样本或基础概率及其来源" /></label><label className="wide">未来情景（每行一个，至少两个）<textarea name="forecast_scenarios" placeholder={"基准情景\n下行情景\n上行情景"} /></label></>}
                <label className="wide">当前假设（每行一个）<textarea name="decision_assumptions" placeholder="尚未证实、但本轮暂时采用的前提" /></label>
                <label className="wide">已知未知项（每行一个）<textarea name="decision_unknowns" placeholder="缺少的数据、规则、责任人或外部条件" /></label>
              </div>
              <div className="decision-submit"><p>提交后生成不可变合同。即便“可以分析”，也不能直接改价、投放、采购或付款。</p><button disabled={decisionBusy}>{decisionBusy ? "正在编译…" : "建立决策合同"}</button></div>
            </form>
            <div className="decision-register">
              <div className="decision-register-head"><strong>最近的决策合同</strong><span>{decisionContracts.length} 份</span></div>
              {decisionContracts.length ? decisionContracts.slice(0, 6).map((contract) => <article key={contract.id}>
                <div><span>{interactionProfiles.find((item) => item.id === contract.profile_id)?.label ?? contract.profile_id}</span><b>{decisionStatusLabels[contract.status] ?? contract.status}</b></div>
                <strong>{contract.objective}</strong>
                <small>{contract.decision_domain} · {contract.risk_level} · v{contract.profile_version}</small>
                {contract.missing_inputs.length > 0 && <p>待补：{contract.missing_inputs.join("、")}</p>}
                <footer><span>{contract.evidence_ids.length} 份证据</span><em>{contract.requires_human_approval ? "必须人工审批" : "分析合同"}</em><b>无执行权</b></footer>
              </article>) : <div className="empty"><BrainCircuit size={25} /><strong>还没有决策合同</strong><p>先选择工作方式，再把第一个真实经营问题提交进来。</p></div>}
            </div>
          </div>
        </section>

        <section className="decision-lifecycle-panel">
          <div className="panel-title">
            <div><p className="eyebrow">DECISION LEARNING LOOP</p><h3>分析 → 独立复核 → 正式决定 → 结果回填</h3></div>
            <span className="badge">分权留痕 · 预测可校准</span>
          </div>
          <div className="lifecycle-summary">
            <article><span>分析</span><b>{decisionAnalyses.length}</b><small>提交人不能自审</small></article>
            <article><span>正式决定</span><b>{decisionResolutions.length}</b><small>仍然没有执行权</small></article>
            <article><span>真实结果</span><b>{decisionOutcomes.length}</b><small>证据到期后回填</small></article>
            <article><span>区间命中率</span><b>{decisionCalibration.length ? `${(Number(decisionCalibration[0].interval_coverage) * 100).toFixed(0)}%` : "待形成"}</b><small>{decisionCalibration.length ? `${decisionCalibration[0].outcome_count} 次可核验预测` : "先完成一次结果闭环"}</small></article>
          </div>
          <div className="lifecycle-grid">
            <form className="lifecycle-form" onSubmit={submitDecisionAnalysis}>
              <div className="lifecycle-form-title"><span>1</span><div><strong>提交证据化分析</strong><small>必须先给出预测值、区间和回填日期</small></div></div>
              <label>可分析合同<select name="analysis_contract_id" value={selectedAnalysisContractId} onChange={(event) => setSelectedAnalysisContractId(event.target.value)} required><option value="">选择一份已就绪合同</option>{decisionContracts.filter((item) => item.status === "ready_for_analysis" && ["decision_review", "probabilistic_forecast"].includes(item.profile_id)).map((item) => <option value={item.id} key={item.id}>{item.objective}</option>)}</select></label>
              {selectedAnalysisContract?.profile_id === "decision_review" && <label>推荐方案<select name="analysis_option_id" defaultValue="" required><option value="">选择合同中的方案</option>{analysisOptions.map((item) => <option value={item.id} key={item.id}>{item.id} · {item.label}</option>)}</select></label>}
              <label>分析结论<textarea name="analysis_conclusion" placeholder="结论必须说明为什么，并保留未知项" required /></label>
              <div className="lifecycle-pair"><label>置信度<input name="analysis_confidence" type="number" min="0" max="1" step="0.01" defaultValue="0.6" required /></label><label>预测指标<input name="analysis_metric" placeholder="例如 30天 CM3" required /></label></div>
              <div className="lifecycle-triple"><label>预测值<input name="analysis_value" type="number" step="0.01" required /></label><label>下界<input name="analysis_low" type="number" step="0.01" required /></label><label>上界<input name="analysis_high" type="number" step="0.01" required /></label></div>
              <div className="lifecycle-pair"><label>单位<input name="analysis_unit" defaultValue="CNY" required /></label><label>结果回填时间<input name="analysis_due_at" type="datetime-local" required /></label></div>
              <label>分析证据<select name="analysis_evidence" defaultValue="" required><option value="">选择原始证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select></label>
              <label>分析者 / 模型版本<input name="analysis_model_ref" placeholder="例如 human+qwen-v3" /></label>
              <label>关键假设（每行一个）<textarea name="analysis_assumptions" /></label><label>剩余未知项（每行一个）<textarea name="analysis_unknowns" /></label>
              <button disabled={lifecycleBusy === "analysis" || !selectedAnalysisContractId}>{lifecycleBusy === "analysis" ? "正在固化…" : "提交分析，进入独立复核"}</button>
            </form>

            <div className="analysis-review-queue">
              <div className="lifecycle-form-title"><span>2</span><div><strong>独立复核与正式决定</strong><small>分析者、复核者、重大决策者按风险分离</small></div></div>
              {decisionAnalyses.length ? decisionAnalyses.slice(0, 4).map((item) => {
                const reviews = decisionReviews[item.id] ?? [];
                const contract = decisionContracts.find((row) => row.id === item.contract_id);
                const blocking = reviews.some((row) => row.verdict !== "accepted");
                const requiredReviews = contract?.risk_level === "critical" ? 2 : 1;
                const acceptedCount = reviews.filter((row) => row.verdict === "accepted").length;
                const resolution = decisionResolutions.find((row) => row.analysis_id === item.id);
                return <article className="analysis-review-card" key={item.id}>
                  <div className="analysis-review-head"><div><strong>{item.conclusion}</strong><small>{contract?.risk_level ?? "-"} · 置信度 {(Number(item.confidence) * 100).toFixed(0)}% · {item.submitted_by}</small></div><span>{resolution ? "已决定" : blocking ? "需重做" : `${acceptedCount}/${requiredReviews} 复核`}</span></div>
                  {item.forecast && <p>预测 {item.forecast.value} {item.forecast.unit} · 区间 {item.forecast.low}–{item.forecast.high} · {new Date(item.forecast.due_at).toLocaleDateString("zh-CN")} 回填</p>}
                  {reviews.map((review) => <div className={`review-result ${review.verdict}`} key={review.id}><b>{review.verdict}</b><span>{review.rationale}</span><small>{review.reviewed_by}</small></div>)}
                  {!blocking && !resolution && acceptedCount < requiredReviews && <form className="mini-lifecycle-form" onSubmit={(event) => reviewDecisionAnalysis(event, item.id)}>
                    <select name="review_verdict" defaultValue="accepted"><option value="accepted">证据支持</option><option value="needs_revision">需要修订</option><option value="rejected">拒绝结论</option></select>
                    <textarea name="review_rationale" placeholder="独立复核理由" required />
                    <textarea name="review_counterarguments" placeholder="反方解释（每行一个）" />
                    <select name="review_evidence" defaultValue=""><option value="">无新增证据（接受结论时必须选择）</option>{evidenceRecords.map((evidence) => <option value={evidence.id} key={evidence.id}>{evidence.grade} · {evidence.filename}</option>)}</select>
                    <button disabled={lifecycleBusy === item.id}>提交独立复核</button>
                  </form>}
                  {!blocking && !resolution && acceptedCount >= requiredReviews && <form className="mini-lifecycle-form resolution" onSubmit={(event) => resolveDecisionAnalysis(event, item)}>
                    <select name="resolution_disposition" defaultValue="experiment"><option value="experiment">受控实验</option><option value="adopt">采纳方案</option><option value="defer">暂缓</option><option value="reject">拒绝</option></select>
                    <textarea name="resolution_rationale" placeholder="正式决定理由" required /><textarea name="resolution_conditions" placeholder="执行前条件（每行一个）" />
                    <button disabled={lifecycleBusy === item.id}>固化正式决定</button>
                  </form>}
                  {blocking && <p className="lifecycle-warning">存在阻断复核。不能覆盖旧分析，请基于反馈提交一份新分析。</p>}
                  {resolution && <div className="resolution-result"><b>{resolution.disposition}</b><span>{resolution.rationale}</span><em>无执行权</em></div>}
                </article>;
              }) : <div className="empty"><BrainCircuit size={24} /><strong>等待第一份分析</strong><p>合同就绪后，先提交带预测区间的分析。</p></div>}
            </div>

            <div className="outcome-queue">
              <div className="lifecycle-form-title"><span>3</span><div><strong>真实结果与校准</strong><small>只接受到期后的证据化事实</small></div></div>
              {decisionResolutions.filter((item) => ["adopt", "experiment"].includes(item.disposition)).length ? decisionResolutions.filter((item) => ["adopt", "experiment"].includes(item.disposition)).slice(0, 4).map((resolution) => {
                const outcome = decisionOutcomes.find((item) => item.resolution_id === resolution.id);
                const selectedAnalysis = decisionAnalyses.find((item) => item.id === resolution.analysis_id);
                return <article className="outcome-card" key={resolution.id}>
                  <div><strong>{selectedAnalysis?.forecast?.metric ?? "待回填指标"}</strong><span>{resolution.disposition}</span></div>
                  {selectedAnalysis?.forecast && <small>预测 {selectedAnalysis.forecast.value} {selectedAnalysis.forecast.unit} · 到期 {new Date(selectedAnalysis.forecast.due_at).toLocaleString("zh-CN")}</small>}
                  {outcome ? <div className={`outcome-result ${outcome.interval_covered ? "covered" : "missed"}`}><b>实际 {outcome.actual_value} {outcome.unit}</b><span>误差 {outcome.signed_error}</span><em>{outcome.interval_covered ? "区间命中" : "区间未命中"}</em></div> : <form className="mini-lifecycle-form" onSubmit={(event) => recordDecisionOutcome(event, resolution.id)}>
                    <input name="outcome_actual" type="number" step="0.01" placeholder="实际结果" required /><input name="outcome_observed_at" type="datetime-local" required />
                    <select name="outcome_evidence" defaultValue="" required><option value="">选择结果证据</option>{evidenceRecords.map((evidence) => <option value={evidence.id} key={evidence.id}>{evidence.grade} · {evidence.filename}</option>)}</select>
                    <textarea name="outcome_notes" placeholder="结果说明与异常" required /><button disabled={lifecycleBusy === resolution.id}>回填真实结果</button>
                  </form>}
                </article>;
              }) : <div className="empty"><Clock3 size={24} /><strong>还没有待回填决定</strong><p>正式采纳或实验后，系统才建立结果回填任务。</p></div>}
              {decisionCalibration.map((item) => <div className="calibration-card" key={`${item.metric}:${item.unit}`}><strong>{item.metric}</strong><span>平均绝对误差 {item.mean_absolute_error} {item.unit}</span><b>区间命中率 {(Number(item.interval_coverage) * 100).toFixed(0)}%</b></div>)}
            </div>
          </div>
        </section>

        <section className="causal-experiment-panel">
          <div className="panel-title">
            <div><p className="eyebrow">CAUSAL EXPERIMENT GATE</p><h3>预注册 → 稳定分流 → SRM 检查 → 独立复核</h3></div>
            <span className="gate ready">实验结果永不自动放量</span>
          </div>
          <div className="procurement-guardrail"><FlaskConical size={17} /><p><strong>先锁定假设与停止条件，再看结果。</strong><span>分流密钥不出系统，原始用户标识不入库；样本比例异常会直接阻断解释。</span></p></div>
          <div className="causal-experiment-layout">
            <form className="experiment-register-form" onSubmit={registerCausalExperiment}>
              <strong>登记一项受控实验</strong>
              <label>试验型正式决议<select name="experiment_resolution_id" required><option value="">选择尚未登记的决议</option>{experimentResolutions.map((item) => <option value={item.id} key={item.id}>{item.id} · {item.rationale}</option>)}</select></label>
              <label className="wide">可证伪假设<textarea name="experiment_hypothesis" placeholder="例如：新版详情页将每访客贡献利润提高至少 5 CNY" required /></label>
              <div className="lifecycle-pair"><label>唯一主指标<input name="experiment_metric" defaultValue="cm3_per_visitor" required /></label><label>随机化单位<input name="experiment_unit" defaultValue="visitor" required /></label></div>
              <div className="lifecycle-pair"><label>干扰集群<input name="experiment_cluster" defaultValue="product_family" placeholder="避免相似 SKU 互相污染" /></label><label>预注册分层字段<input name="experiment_segment_key" placeholder="例如 country_tier；可留空" /></label></div>
              <div className="lifecycle-pair"><label>内部蚕食成本指标<input name="experiment_cannibalization_metric" placeholder="例如 cannibalized_cm3；可留空" /></label><label>长期成本指标<input name="experiment_long_term_cost_metric" placeholder="例如 refund_cost_30d；可留空" /></label></div>
              <div className="lifecycle-pair"><label>对照组<input name="experiment_control_label" defaultValue="现行策略" required /></label><label>实验组<input name="experiment_treatment_label" defaultValue="候选策略" required /></label></div>
              <div className="lifecycle-triple"><label>目标样本<input name="experiment_sample_size" type="number" min="20" defaultValue="100" required /></label><label>最小有意义效果<input name="experiment_mde" type="number" min="0.0001" step="0.0001" defaultValue="5" required /></label><label>结果观察天数<input name="experiment_outcome_days" type="number" min="0" max="365" defaultValue="30" required /></label></div>
              <div className="lifecycle-triple"><label>实验预算<input name="experiment_budget" type="number" min="0.01" step="0.01" required /></label><label>止损线<input name="experiment_stop_loss" type="number" min="0.01" step="0.01" required /></label><label>币种<input name="experiment_currency" defaultValue="CNY" maxLength={3} required /></label></div>
              <div className="lifecycle-pair"><label>开始时间<input name="experiment_start_at" type="datetime-local" required /></label><label>结束时间<input name="experiment_end_at" type="datetime-local" required /></label></div>
              <div className="lifecycle-pair"><label>护栏指标<input name="experiment_guardrail_metric" defaultValue="refund_rate" required /></label><label>最大阈值<input name="experiment_guardrail_threshold" type="number" step="0.0001" defaultValue="0.1" required /></label></div>
              <label>预注册证据<select name="experiment_evidence" defaultValue="" required><option value="">选择原始证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select></label>
              <button disabled={lifecycleBusy === "experiment-register" || !experimentResolutions.length}>{lifecycleBusy === "experiment-register" ? "正在固化…" : "固化实验协议"}</button>
            </form>
            <div className="experiment-register-list">
              {causalExperiments.length ? causalExperiments.map((experiment) => {
                const evaluation = experimentEvaluations[experiment.id];
                const experimentReviews = causalExperimentReviews[experiment.id] ?? [];
                const acceptedReview = experimentReviews.find((item) => item.verdict === "accepted");
                const knowledgeEntry = causalKnowledge.find((item) => item.protocol_id === experiment.id);
                const nextEvent = experiment.status === "registered" ? "started" : experiment.status === "running" ? "paused" : experiment.status === "paused" ? "resumed" : null;
                return <article className="experiment-card" key={experiment.id}>
                  <div className="experiment-card-head"><div><strong>{experiment.hypothesis}</strong><small>{experiment.primary_metric} · {experiment.randomization_unit} · 50/50</small></div><span className={evaluation?.sample_ratio_mismatch ? "gate blocked" : "gate ready"}>{experiment.status}</span></div>
                  <div className="experiment-facts"><span>样本 <b>{evaluation?.observed_count ?? 0}/{experiment.target_sample_size}</b></span><span>分流 <b>{evaluation?.assignment_count ?? 0}</b></span><span>SRM <b>{evaluation?.sample_ratio_mismatch ? "阻断" : "通过"}</b></span><span>安全门 <b>{evaluation?.safety_gate_breached ? "冻结" : "通过"}</b></span></div>
                  <p>{evaluation?.interpretation === "SAFETY_BREACH_FREEZES_ASSIGNMENT" ? "预算、止损或护栏已越线，后续分流已冻结。" : evaluation?.interpretation === "SRM_BLOCKS_DECISION" ? "样本比例异常，禁止解释和决策。" : evaluation?.missing_required_metrics.length ? `仍缺长期/蚕食结果：${evaluation.missing_required_metrics.join("、")}` : evaluation?.review_eligible ? `净增量 ${evaluation.incremental_value_per_unit ?? evaluation.treatment_effect?.absolute_effect ?? "-"}/单位，已达到独立复核条件。` : "继续收集预注册样本，不允许提前挑选赢家。"}</p>
                  {evaluation?.review_eligible && !experimentReviews.length && <form className="causal-review-form" onSubmit={(event) => reviewCausalExperiment(event, experiment)}>
                    <strong>独立复核实验结论</strong>
                    <select name="causal_review_verdict" defaultValue="accepted"><option value="accepted">接受为待登记知识</option><option value="needs_replication">必须先复现</option><option value="rejected">拒绝结论</option></select>
                    <textarea name="causal_review_rationale" placeholder="复核结论与适用限制" required />
                    <textarea name="causal_review_method" placeholder="随机化、干扰、样本与估计方法审查" required />
                    <textarea name="causal_review_data" placeholder="SRM、缺失、异常、币种和长期窗口审查" required />
                    <textarea name="causal_review_counterarguments" placeholder="至少写一个替代解释或反方意见，每行一条" required />
                    <select name="causal_review_evidence" defaultValue="" required><option value="">选择复核证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select>
                    <button disabled={lifecycleBusy === `causal-review:${experiment.id}`}>固化独立复核</button>
                  </form>}
                  {acceptedReview && !knowledgeEntry && evaluation?.review_eligible && <form className="causal-knowledge-form" onSubmit={(event) => publishCausalKnowledge(event, experiment, acceptedReview.id)}>
                    <strong>把复核结论登记成有边界的知识</strong>
                    <textarea name="knowledge_claim" defaultValue={experiment.hypothesis} required />
                    <textarea name="knowledge_mechanism" placeholder="为什么有效：动作 → 中介机制 → 结果" required />
                    <div className="lifecycle-pair"><label>平台<input name="knowledge_platform" defaultValue="Ozon" required /></label><label>国家<input name="knowledge_country" defaultValue="RU" required /></label></div>
                    <div className="lifecycle-pair"><label>品类<input name="knowledge_category" placeholder="精确到可迁移边界" required /></label><label>适用人群<input name="knowledge_population" placeholder="例如 eligible-visitors" required /></label></div>
                    <textarea name="knowledge_falsification" placeholder="什么证据出现时必须推翻或暂停使用，每行一条" required />
                    <div className="lifecycle-pair"><label>生效时间<input name="knowledge_valid_from" type="datetime-local" required /></label><label>最晚复验时间<input name="knowledge_reevaluate_at" type="datetime-local" required /></label></div>
                    <select name="knowledge_replication_source" defaultValue=""><option value="">不是复现实验</option>{causalKnowledge.filter((item) => item.usable && item.protocol_id !== experiment.id).map((item) => <option value={item.id} key={item.id}>复现：{item.claim}</option>)}</select>
                    <input name="knowledge_replication_rationale" placeholder="若为复现，说明独立协议和范围关系" />
                    <select name="knowledge_evidence" defaultValue="" required><option value="">选择知识证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select>
                    <button disabled={lifecycleBusy === `causal-knowledge:${experiment.id}`}>登记不可变知识</button>
                  </form>}
                  {knowledgeEntry && <div className={knowledgeEntry.usable ? "knowledge-status usable" : "knowledge-status invalid"}><strong>{knowledgeEntry.knowledge_strength}</strong><span>{knowledgeEntry.validity_status} · {knowledgeEntry.usable ? "可供后续策略引用" : "禁止继续引用"}</span><b>执行权：无</b></div>}
                  {experiment.status === "running" && <form className="experiment-safety-form" onSubmit={(event) => recordExperimentSafety(event, experiment)}>
                    <select name="safety_metric" defaultValue="budget_spend_amount"><option value="budget_spend_amount">累计实验支出</option><option value="cumulative_loss_amount">累计实验损失</option>{experiment.guardrails.map((item) => <option value={item.metric} key={item.metric}>{item.metric}</option>)}</select>
                    <input name="safety_value" type="number" step="0.0001" placeholder="当前读数" required />
                    <select name="safety_evidence" defaultValue="" required><option value="">读数证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select>
                    <button disabled={lifecycleBusy === `safety:${experiment.id}`}>记录安全读数</button>
                  </form>}
                  {nextEvent && <form className="experiment-event-form" onSubmit={(event) => transitionCausalExperiment(event, experiment, nextEvent)}>
                    <input name="experiment_event_reason" placeholder={nextEvent === "started" ? "启动前检查结论" : nextEvent === "paused" ? "暂停原因" : "恢复原因"} required />
                    <select name="experiment_event_evidence" defaultValue="" required><option value="">选择事件证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select>
                    <button disabled={lifecycleBusy === experiment.id}>{nextEvent === "started" ? "人工批准启动" : nextEvent === "paused" ? "暂停实验" : "恢复实验"}</button>
                  </form>}
                  <footer><span>预算 {experiment.budget_cap_amount} {experiment.currency}</span><span>止损 {experiment.stop_loss_amount}</span><b>自动放量：禁止</b></footer>
                </article>;
              }) : <div className="empty"><FlaskConical size={25} /><strong>还没有预注册实验</strong><p>先完成分析、独立复核和“受控实验”正式决议。</p></div>}
            </div>
          </div>
          <div className="causal-knowledge-registry">
            <div className="panel-title"><div><p className="eyebrow">CAUSAL KNOWLEDGE REGISTRY</p><h3>企业因果知识账</h3></div><span className="badge">{causalKnowledge.filter((item) => item.usable).length} 条当前可用</span></div>
            {causalKnowledge.length ? <div className="knowledge-grid">{causalKnowledge.map((item) => <article className={item.usable ? "knowledge-card" : "knowledge-card invalid"} key={item.id}>
              <div><span>{item.knowledge_strength}</span><b>{item.validity_status}</b></div>
              <strong>{item.claim}</strong><p>{item.mechanism}</p>
              <small>{String(item.applicability.platform)} · {String(item.applicability.country)} · {String(item.applicability.category)} · {String(item.applicability.population)}</small>
              {item.usable && !causalPolicies.some((policy) => policy.knowledge_ids.includes(item.id)) && <details><summary>编译为条件策略</summary><form className="causal-policy-form" onSubmit={(event) => proposeCausalPolicy(event, item)}>
                <input name="policy_title" placeholder="策略名称" required /><textarea name="policy_objective" placeholder="策略要解决的决策问题" required />
                <div className="lifecycle-triple"><input name="policy_condition_field" defaultValue="inventory_cover_days" aria-label="条件字段" required /><select name="policy_condition_operator" defaultValue="gte" aria-label="条件比较"><option value="gte">不低于</option><option value="lte">不高于</option><option value="eq">等于</option></select><input name="policy_condition_value" defaultValue="45" aria-label="条件值" required /></div>
                <div className="lifecycle-pair"><select name="policy_action_type" defaultValue="recommend_listing_change"><option value="recommend_listing_change">建议切换详情页</option><option value="recommend_no_action">建议保持不动</option></select><input name="policy_action_variant" defaultValue="treatment" aria-label="候选方案" required /></div>
                <div className="lifecycle-pair"><input name="policy_guardrail_metric" defaultValue="refund_rate" aria-label="护栏指标" required /><input name="policy_guardrail_threshold" defaultValue="0.1" type="number" step="0.0001" aria-label="护栏阈值" required /></div>
                <div className="lifecycle-pair"><input name="policy_shadow_samples" defaultValue="20" type="number" min="0" aria-label="影子阶段最小样本" required /><input name="policy_shadow_value" defaultValue="0" type="number" step="0.0001" aria-label="影子阶段最小增量" required /></div>
                <div className="lifecycle-triple"><input name="policy_limited_fraction" defaultValue="0.1" type="number" min="0.0001" max="1" step="0.0001" aria-label="有限放量比例" required /><input name="policy_limited_samples" defaultValue="100" type="number" min="1" aria-label="有限阶段最小样本" required /><input name="policy_limited_value" defaultValue="3" type="number" step="0.0001" aria-label="有限阶段最小增量" required /></div>
                <select name="policy_evidence" defaultValue="" required><option value="">选择策略证据</option>{evidenceRecords.map((evidenceItem) => <option value={evidenceItem.id} key={evidenceItem.id}>{evidenceItem.grade} · {evidenceItem.filename}</option>)}</select>
                <button disabled={lifecycleBusy === `policy-propose:${item.id}`}>固化条件策略</button>
              </form></details>}
              <footer><span>最晚复验 {new Date(item.reevaluate_at).toLocaleDateString("zh-CN")}</span><b>不会自动执行</b></footer>
            </article>)}</div> : <div className="empty"><BrainCircuit size={24} /><strong>还没有通过复核的因果知识</strong><p>实验完成后先独立复核，再登记适用边界和失效时间。</p></div>}
          </div>
          <div className="causal-policy-registry">
            <div className="panel-title"><div><p className="eyebrow">CONDITIONAL POLICY GATE</p><h3>条件策略与分阶段晋级</h3></div><span className="gate ready">影子 → 有限；逐级人工批准</span></div>
            {causalPolicies.length ? <div className="policy-grid">{causalPolicies.map((policy) => {
              const acceptedReview = policy.reviews.find((item) => item.verdict === "accepted");
              const latestRelease = policy.releases[policy.releases.length - 1];
              const shadowRelease = policy.releases.find((item) => item.stage.max_exposure_fraction === "0");
              const shadowBatch = [...policyShadowBatches].reverse().find((item) => item.policy_id === policy.id && item.release_id === shadowRelease?.id);
              const activationHandoff = policyActivationHandoffs.find((item) => item.policy_id === policy.id);
              const executionPlan = governedExecutionPlans.find((item) => item.policy_id === policy.id);
              const executionCommand = limitedExecutionCommands.find((item) => item.plan_id === executionPlan?.id && item.command_kind === "execute");
              const observationWindow = executionObservationWindows.find((item) => item.command_id === executionCommand?.id);
              const capabilityAssessment = capabilityEconomicAssessments.find((item) => item.window_id === observationWindow?.id);
              const canReleaseNext = acceptedReview && policy.usable && policy.releases.length < policy.rollout_stages.length && (!latestRelease || latestRelease.outcome?.verdict === "passed");
              return <article className={policy.usable ? "policy-card" : "policy-card invalid"} key={policy.id}>
                <div className="policy-card-head"><div><strong>{policy.title}</strong><small>{policy.validity_status} · 来源知识 {policy.knowledge_ids.length} 条</small></div><span className={policy.usable ? "gate ready" : "gate blocked"}>{policy.usable ? "可评估" : "已冻结"}</span></div>
                <p>{policy.objective}</p><div className="policy-condition"><b>当</b>{policy.conditions.map((item) => <span key={`${item.field}:${item.operator}`}>{item.field} {item.operator} {String(item.value)}</span>)}<b>建议</b><span>{policy.action.type}</span></div>
                {!policy.reviews.length && <form className="policy-review-form" onSubmit={(event) => reviewCausalPolicy(event, policy)}><select name="policy_review_verdict" defaultValue="accepted"><option value="accepted">接受策略合同</option><option value="needs_revision">退回修改</option><option value="rejected">拒绝</option></select><textarea name="policy_review_rationale" placeholder="条件、护栏、退回和阶段门审查" required /><textarea name="policy_review_counterarguments" placeholder="至少一个反方意见" required /><select name="policy_review_evidence" defaultValue="" required><option value="">复核证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button>固化策略复核</button></form>}
                {canReleaseNext && <form className="policy-release-form" onSubmit={(event) => releaseCausalPolicyStage(event, policy, acceptedReview.id)}><strong>下一阶段：{policy.rollout_stages[policy.releases.length].name} · 最大暴露 {(Number(policy.rollout_stages[policy.releases.length].max_exposure_fraction) * 100).toFixed(0)}%</strong><input name="policy_release_rationale" placeholder="批准理由" required /><select name="policy_release_evidence" defaultValue="" required><option value="">阶段批准证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button>人工批准该阶段</button></form>}
                {shadowRelease && !shadowRelease.outcome && <form className="policy-outcome-form" onSubmit={(event) => runPolicyShadowBatch(event, policy, shadowRelease.id)}><strong>运行零暴露影子批次</strong><p>粘贴实际库存覆盖天数，用逗号分隔；仅记录策略会如何判断，不修改任何经营数据。</p><input name="policy_shadow_cover_days" placeholder="例如：60, 52, 47, 31（最多100条）" required /><select name="policy_shadow_evidence" defaultValue="" required><option value="">选择本批数据证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `policy-shadow:${shadowRelease.id}`}>固化影子批次</button></form>}
                {shadowBatch && <div className="knowledge-status usable"><strong>影子批次 {shadowBatch.context_count} 条</strong><span>命中 {shadowBatch.matched_count} · 退回 {shadowBatch.fallback_count} · 暴露 0%</span><b>执行权：无</b></div>}
                {latestRelease && !latestRelease.outcome && <form className="policy-outcome-form" onSubmit={(event) => recordCausalPolicyOutcome(event, policy, latestRelease.id)}><strong>回填 {latestRelease.stage.name} 真实结果</strong><div className="lifecycle-triple"><select name="policy_outcome_verdict" defaultValue="passed"><option value="passed">通过</option><option value="failed">失败</option><option value="inconclusive">不确定</option></select><input name="policy_outcome_count" type="number" min="0" placeholder="观察数" required /><input name="policy_outcome_value" type="number" step="0.0001" placeholder="单位增量" required /></div><select name="policy_outcome_guardrail" defaultValue="false"><option value="false">护栏未越线</option><option value="true">护栏已越线</option></select><textarea name="policy_outcome_notes" placeholder="真实结果说明" required /><select name="policy_outcome_evidence" defaultValue="" required><option value="">结果证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button>固化阶段结果</button></form>}
                {latestRelease && latestRelease.stage.max_exposure_fraction !== "0" && shadowBatch && !activationHandoff && <form className="policy-release-form" onSubmit={(event) => requestPolicyActivation(event, policy, latestRelease.id, shadowBatch)}><strong>移交阶段激活审批</strong><p>只创建独立审批事项；批准后仍不会直接操作平台。</p><select name="policy_handoff_evidence" defaultValue="" required><option value="">选择交接证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `policy-handoff:${latestRelease.id}`}>送入审批中心</button></form>}
                {activationHandoff && <div className={activationHandoff.validity_status === "active" ? "knowledge-status usable" : "knowledge-status invalid"}><strong>审批 {activationHandoff.approval_status}</strong><span>{activationHandoff.validity_status} · {activationHandoff.activation_eligible ? "可进入执行设计" : "不可激活"}</span><b>自动执行：禁止</b></div>}
                {activationHandoff?.activation_eligible && !executionPlan && <form className="policy-outcome-form" onSubmit={(event) => createExecutionPlan(event, activationHandoff)}><strong>建立可回滚执行计划</strong><p>绑定具体 Listing、当前状态指纹、新标题和恢复标题；系统会另行申请执行审批。</p><input name="execution_listing_id" placeholder="Ozon Listing ID" required /><input name="execution_state_hash" minLength={64} maxLength={64} placeholder="当前平台快照 SHA-256" required /><input name="execution_old_title" placeholder="当前标题（用于回滚）" required /><input name="execution_new_title" placeholder="拟更新标题" required /><select name="execution_evidence" defaultValue="" required><option value="">选择当前状态证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `execution-plan:${activationHandoff.id}`}>固化计划并申请执行审批</button></form>}
                {executionPlan && <div className={executionPlan.ready_for_executor ? "knowledge-status usable" : "knowledge-status invalid"}><strong>执行计划 {executionPlan.approval_status}</strong><span>{executionPlan.dry_run?.passed ? "预演通过" : "等待预演"} · {executionPlan.handoff_validity_status}</span><b>平台写入：禁用</b></div>}
                {executionPlan && !executionPlan.dry_run && <form className="policy-release-form" onSubmit={(event) => dryRunExecutionPlan(event, executionPlan)}><strong>执行前预演</strong><p>重新读取平台状态后填写快照指纹；与计划前置状态不一致将失败并要求重建计划。</p><input name="dry_run_state_hash" minLength={64} maxLength={64} defaultValue={executionPlan.precondition_state_hash} required /><select name="dry_run_evidence" defaultValue="" required><option value="">选择最新平台快照证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `execution-dry-run:${executionPlan.id}`}>只做预演</button></form>}
                {executionPlan?.ready_for_executor && executionPlan.live_execution_supported && !executionCommand && <div className="policy-release-form"><strong>受限执行队列</strong><p>默认全局关闭。启用后仍由专用执行器按状态指纹领取，网页不会直接调用 Ozon。</p><button type="button" disabled={lifecycleBusy === `execution-queue:${executionPlan.id}`} onClick={() => queueLimitedExecution(executionPlan)}>进入受限队列</button></div>}
                {executionCommand && <div className={executionCommand.status === "succeeded" ? "knowledge-status usable" : "knowledge-status invalid"}><strong>{executionCommand.command_kind === "rollback" ? "回滚" : "执行"}命令 {executionCommand.status}</strong><span>{executionCommand.claimed_by ? `执行器 ${executionCommand.claimed_by}` : "等待专用执行器领取"}</span><b>远端写入：{executionCommand.platform_write_performed ? "已由回执确认" : "未确认"}</b></div>}
                {executionCommand?.status === "succeeded" && executionCommand.platform_write_performed && !observationWindow && <form className="policy-outcome-form" onSubmit={(event) => createObservationWindow(event, executionCommand)}><strong>固化执行后观察合同</strong><p>预先锁定利润指标、退款护栏、基线和期限。超过护栏会先排队补偿并冻结写操作，不会自动继续放量。</p><div className="lifecycle-pair"><input name="observation_primary_metric" defaultValue="contribution_profit_per_visitor" aria-label="主要结果指标" required /><input name="observation_primary_baseline" defaultValue="0" type="number" step="0.0001" aria-label="主要指标基线" required /></div><div className="lifecycle-pair"><input name="observation_guardrail_metric" defaultValue={policy.guardrails[0]?.metric ?? "refund_rate"} aria-label="护栏指标" required /><input name="observation_guardrail_baseline" defaultValue="0" type="number" step="0.0001" aria-label="护栏基线" required /></div><input name="observation_required_count" defaultValue="2" type="number" min="1" max="10000" aria-label="最少观察数" required /><div className="lifecycle-pair"><input name="observation_starts_at" type="datetime-local" aria-label="观察开始时间" required /><input name="observation_ends_at" type="datetime-local" aria-label="观察结束时间" required /></div><select name="observation_evidence" defaultValue="" required><option value="">选择基线证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `observation-window:${executionCommand.id}`}>锁定观察合同</button></form>}
                {observationWindow && <div className={observationWindow.evaluation.status === "guardrail_breached" ? "knowledge-status invalid" : "knowledge-status usable"}><strong>执行后观察：{observationWindow.evaluation.status}</strong><span>{observationWindow.primary_metric} · 已记录 {observationWindow.observations.length}/{observationWindow.required_observations}</span><b>{observationWindow.evaluation.status === "guardrail_breached" ? "补偿已排队，写操作冻结" : "自动策略晋级：禁止"}</b></div>}
                {observationWindow?.evaluation.status === "monitoring" && <form className="policy-outcome-form" onSubmit={(event) => recordExecutionObservation(event, observationWindow)}><strong>上报真实经营结果</strong><p>只能填写合同内的主指标或护栏指标；记录一经提交不可修改。</p><select name="observed_metric" defaultValue={observationWindow.primary_metric} required><option value={observationWindow.primary_metric}>{observationWindow.primary_metric}</option>{observationWindow.guardrails.map((guardrail) => <option value={guardrail.metric} key={guardrail.metric}>{guardrail.metric}（{guardrail.direction} {guardrail.threshold}）</option>)}</select><input name="observed_value" type="number" step="0.0001" placeholder="实际结果" required /><input name="observed_at" type="datetime-local" aria-label="结果发生时间" required /><select name="observed_evidence" defaultValue="" required><option value="">选择结果证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `observation:${observationWindow.id}`}>记录并核对护栏</button></form>}
                {observationWindow && ["passed", "guardrail_breached"].includes(observationWindow.evaluation.status) && !capabilityAssessment && <form className="policy-outcome-form" onSubmit={(event) => assessCapabilityEconomics(event, observationWindow)}><strong>核算这项能力是否值得保留</strong><p>把实际增量、避免损失、模型费、人工审核、事故损失和维护成本放在同一本账里。金额必须由证据支持。</p><div className="lifecycle-pair"><input name="economics_realized_value" type="number" step="0.01" placeholder="实际增量（可为负）" required /><input name="economics_avoided_loss" type="number" min="0" step="0.01" defaultValue="0" placeholder="避免损失" required /></div><div className="lifecycle-pair"><input name="economics_model_cost" type="number" min="0" step="0.01" defaultValue="0" placeholder="模型与计算成本" required /><input name="economics_review_cost" type="number" min="0" step="0.01" defaultValue="0" placeholder="人工审核成本" required /></div><div className="lifecycle-pair"><input name="economics_incident_loss" type="number" min="0" step="0.01" defaultValue="0" placeholder="事故损失" required /><input name="economics_maintenance_cost" type="number" min="0" step="0.01" defaultValue="0" placeholder="维护成本" required /></div><div className="lifecycle-pair"><input name="economics_currency" defaultValue="CNY" minLength={3} maxLength={3} aria-label="币种" required /><input name="economics_as_of" type="datetime-local" aria-label="核算时间" required /></div><select name="economics_evidence" defaultValue="" required><option value="">选择损益证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `capability-economics:${observationWindow.id}`}>固化能力损益</button></form>}
                {capabilityAssessment && <div className={Number(capabilityAssessment.net_value) > 0 && capabilityAssessment.outcome_status !== "guardrail_breached" ? "knowledge-status usable" : "knowledge-status invalid"}><strong>能力净价值 {capabilityAssessment.net_value} {capabilityAssessment.currency}</strong><span>增量 {capabilityAssessment.realized_incremental_value} · 避免损失 {capabilityAssessment.avoided_loss} · 事故损失 {capabilityAssessment.incident_loss}</span><b>自动权限变更：禁止</b></div>}
                <div className="policy-stages">{policy.rollout_stages.map((stage, index) => { const release = policy.releases.find((item) => item.stage_index === index); return <span className={release?.outcome?.verdict === "passed" ? "passed" : release ? "released" : ""} key={stage.name}>{stage.name}<b>{(Number(stage.max_exposure_fraction) * 100).toFixed(0)}%</b></span>; })}</div>
                <footer><span>条件不满足：{policy.fallback_action.type}</span><b>自动执行：禁止</b></footer>
              </article>;
            })}</div> : <div className="empty"><Waypoints size={24} /><strong>还没有条件策略</strong><p>先从仍有效的因果知识编译，不能从聊天建议直接生成经营动作。</p></div>}
          </div>
        </section>

        <section className="gate-overview">
          <div className="gate-overview-head">
            <div><p className="eyebrow">REALITY GATE</p><h3>G0–G1 真实准入状态</h3></div>
            <span className={gateReadiness?.status === "ready_for_review" ? "gate ready" : "gate blocked"}>
              {gateReadiness?.status === "ready_for_review" ? "等待人工放行" : "等待真实输入"}
            </span>
          </div>
          {gateReadiness ? <div className="requirement-grid">
            {gateReadiness.requirements.map((item) => <article className={item.ready ? "requirement ready" : "requirement"} key={item.id}>
              <div><span>{item.id}</span><b>{item.current}/{item.target}</b></div>
              <strong>{item.title}</strong>
              <small>{item.ready ? "证据条件已满足，仍需阶段门人工复核" : item.next_action}</small>
            </article>)}
          </div> : <div className="gate-loading">正在读取阶段门事实…</div>}
          <form className="gate-evidence-upload" onSubmit={uploadGateEvidence}>
            <div><strong>补充阶段门证据</strong><small>原文件将哈希固化并自动链接，不覆盖历史。</small></div>
            <select name="requirement_id" aria-label="阶段门证据类型" defaultValue="" required>
              <option value="" disabled>选择证据类型</option>
              <option value="GOV-001">负责人、审批人与风险预算</option>
              <option value="OZN-001">Ozon 账户、权限与收款路径</option>
            </select>
            <input name="gate_file" aria-label="阶段门证据文件" type="file" required />
            <button disabled={gateUploading}>{gateUploading ? "正在固化…" : "提交证据"}</button>
          </form>
        </section>

        <section className="sku-intake-panel">
          <div className="panel-title"><div><p className="eyebrow">SKU EPISODE INTAKE</p><h3>候选 SKU 一站式录入</h3></div><span className="badge">草稿 · 需人工审核</span></div>
          <form className="sku-intake" onSubmit={uploadSkuEpisode}>
            <div className="intake-basic">
              <label>SKU<input name="sku" placeholder="例如 RU-001" required /></label>
              <label>商品名称<input name="product_name" placeholder="使用可稳定识别的商品名称" required /></label>
            </div>
            <div className="intake-passports">
              <details open>
                <summary><span>1</span><strong>商品 Passport</strong><small>材料、用途、产地、重量与尺寸</small></summary>
                <div className="intake-fields">
                  <label>材料<input name="material" required /></label><label>用途<input name="intended_use" required /></label>
                  <label>原产国<input name="country_of_origin" defaultValue="CN" required /></label><label>重量 kg<input name="weight_kg" type="number" min="0.001" step="0.001" required /></label>
                  <label>长 cm<input name="length_cm" type="number" min="0" step="0.1" required /></label><label>宽 cm<input name="width_cm" type="number" min="0" step="0.1" required /></label>
                  <label>高 cm<input name="height_cm" type="number" min="0" step="0.1" required /></label><label>商品证据<input name="product_evidence" type="file" required /></label>
                </div>
              </details>
              <details open>
                <summary><span>2</span><strong>俄罗斯合规 Passport</strong><small>先记录事实与未知项，审核人再作结论</small></summary>
                <div className="intake-fields">
                  <label>HS Code<input name="hs_code" required /></label><label>EAC 要求<input name="eac_requirement" defaultValue="unknown" required /></label>
                  <label>诚实标要求<input name="chestny_znak_requirement" defaultValue="unknown" required /></label><label>俄文标签<input name="russian_labeling" defaultValue="unknown" required /></label>
                  <label>知识产权状态<input name="ip_status" defaultValue="review_required" required /></label><label>运输限制<input name="transport_restrictions" defaultValue="unknown" required /></label>
                  <label>可售状态<input name="sellability" defaultValue="pending_review" required /></label><label>合规证据<input name="compliance_evidence" type="file" required /></label>
                  <label className="wide">EAEU 规则依据（每行一条）<textarea name="eaeu_rules" required /></label>
                </div>
              </details>
              <details open>
                <summary><span>3</span><strong>样品质量 Passport</strong><small>黄金样、验货计划与包装测试</small></summary>
                <div className="intake-fields">
                  <label>黄金样编号<input name="golden_sample_ref" required /></label><label>包装测试<input name="packaging_test" defaultValue="pending" required /></label>
                  <label>质量证据<input name="quality_evidence" type="file" required /></label><label className="wide">验货项目（每行一条）<textarea name="inspection_plan" required /></label>
                </div>
              </details>
            </div>
            <div className="intake-submit"><p>提交只建立可追溯草稿，不代表合规批准、采购授权或上架放行。</p><button disabled={skuUploading}>{skuUploading ? "正在建立…" : "建立 SKU Episode"}</button></div>
          </form>
        </section>

        <section className="passport-review-panel">
          <div className="panel-title">
            <div><p className="eyebrow">HUMAN REVIEW</p><h3>Passport 人工审核</h3></div>
            <span className={passportReviews.length ? "badge" : "gate ready"}>{passportReviews.length ? `${passportReviews.length} 项待审` : "队列已清空"}</span>
          </div>
          {passportReviews.length ? <div className="review-grid">{passportReviews.map((item) => {
            const key = item.passport.id;
            const busy = reviewingKey === key;
            return <article className="review-card" key={key}>
              <div className="review-head">
                <div><strong>{item.product.sku}</strong><small>{item.product.name}</small></div>
                <span>{passportLabels[item.passport.kind]} · V{item.passport.version}</span>
              </div>
              <div className="fact-list">{Object.entries(item.passport.facts).filter(([name]) => name !== "decision").map(([name, value]) => <div key={name}><span>{name}</span><b>{typeof value === "object" ? JSON.stringify(value) : String(value)}</b></div>)}</div>
              <div className="review-evidence"><ShieldCheck size={14} /><span>{item.passport.evidence.length} 份不可变证据</span>{item.passport.missing_fields.length ? <b>缺少 {item.passport.missing_fields.join("、")}</b> : <b>必填事实完整</b>}</div>
              <label>审核说明<textarea value={reviewNotes[key] ?? ""} onChange={(event) => setReviewNotes((current) => ({ ...current, [key]: event.target.value }))} placeholder="记录核查依据；阻断时必须填写原因" /></label>
              <div className="review-actions">
                <button className="reject" disabled={busy} onClick={() => reviewPassport(item, "blocked")}>阻断并退回</button>
                <button className="approve" disabled={busy || item.passport.missing_fields.length > 0} onClick={() => reviewPassport(item, "approved")}>{busy ? "提交中…" : "批准 Passport"}</button>
              </div>
            </article>;
          })}</div> : <div className="empty"><CheckCircle2 size={25} /><strong>没有待审核 Passport</strong><p>新的 SKU Episode 提交后会自动进入这里。</p></div>}
        </section>

        <section className="sourcing-intake-panel">
          <div className="panel-title"><div><p className="eyebrow">THREE-QUOTE GATE</p><h3>三家供应商证据化比价</h3></div><span className="badge">{pendingProcurementApprovals} 项采购待审批</span></div>
          <form className="sourcing-intake" onSubmit={uploadSupplierComparison}>
            <div className="sourcing-common">
              <label>候选 SKU<select name="sourcing_product_id" required><option value="">选择 SKU</option>{products.map((item) => <option value={item.id} key={item.id}>{item.sku} · {item.name}</option>)}</select></label>
              <label>目标售价 RUB<input name="sale_price_rub" type="number" min="0.01" step="0.01" required /></label><label>RUB/CNY<input name="rub_per_cny" type="number" min="0.0001" step="0.0001" required /></label>
              <label>国际运费 CNY/kg<input name="international_freight" type="number" min="0" step="0.01" required /></label><label>包装 CNY<input name="packaging_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>尾程 CNY<input name="last_mile_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>关税率<input name="customs_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
              <label>平台费率<input name="platform_fee_rate" type="number" min="0" max="0.9999" step="0.0001" required /></label><label>广告率<input name="advertising_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
              <label>退货准备率<input name="return_reserve_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label><label>其他成本 CNY<input name="other_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>利润假设证据<input name="assumption_evidence" type="file" required /></label>
            </div>
            <div className="supplier-entry-grid">{[1, 2, 3].map((index) => <details open key={index}><summary><span>{index}</span><strong>供应商 {index}</strong><small>原始报价与实测条件</small></summary><div className="supplier-fields">
              <label>供应商标识<input name={`supplier_ref_${index}`} required /></label><label>来源平台<select name={`platform_${index}`} defaultValue="1688"><option value="1688">1688</option><option value="alibaba">Alibaba</option><option value="manual">线下/人工</option></select></label>
              <label>报价快照编号<input name={`external_id_${index}`} required /></label><label>商品标题<input name={`offer_title_${index}`} required /></label>
              <label className="wide">原始链接<input name={`source_url_${index}`} type="url" required /></label><label>币种<input name={`currency_${index}`} defaultValue="CNY" maxLength={3} required /></label>
              <label>单价<input name={`unit_price_${index}`} type="number" min="0.01" step="0.01" required /></label><label>兑 CNY 汇率<input name={`source_to_cny_rate_${index}`} type="number" min="0.0001" step="0.0001" defaultValue="1" required /></label>
              <label>MOQ<input name={`moq_${index}`} type="number" min="1" required /></label><label>重量 kg<input name={`supplier_weight_${index}`} type="number" min="0.001" step="0.001" required /></label>
              <label>长 cm<input name={`supplier_length_${index}`} type="number" min="0" step="0.1" defaultValue="0" required /></label><label>宽 cm<input name={`supplier_width_${index}`} type="number" min="0" step="0.1" defaultValue="0" required /></label>
              <label>高 cm<input name={`supplier_height_${index}`} type="number" min="0" step="0.1" defaultValue="0" required /></label><label>国内物流/件<input name={`domestic_logistics_${index}`} type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label className="wide">报价证据<input name={`supplier_evidence_${index}`} type="file" required /></label>
            </div></details>)}</div>
            <div className="intake-submit"><p>三份报价和共同利润假设都会哈希固化；系统只生成比较与审批申请，不会自动采购。</p><button disabled={sourcingUploading}>{sourcingUploading ? "正在比较…" : "建立三家报价比较"}</button></div>
          </form>
        </section>

        {comparisons.length > 0 && <section className="comparison-panel">
          <div className="panel-title"><div><p className="eyebrow">SOURCING DECISION</p><h3>报价与 CM3 比较</h3></div><span className="gate ready">仅人工提交采购</span></div>
          {comparisons.map((comparison) => <div className="comparison-group" key={comparison.product.id}><div className="comparison-title"><strong>{comparison.product.sku} · {comparison.product.name}</strong><span>{comparison.supplier_count}/3 家供应商</span></div><div className="comparison-grid">{comparison.rows.map((row, index) => {
            const draft = procurementDrafts[row.offer.id] ?? { quantity: String(row.offer.min_order_quantity), rationale: "" };
            const passportReady = skuReadiness.find((item) => item.product.id === comparison.product.id)?.ready_for_validation;
            return <article className="comparison-card" key={row.offer.id}><div className="rank">#{index + 1}</div><strong>{row.offer.supplier_ref}</strong><small>{row.offer.platform} · {row.offer.unit_price} {row.offer.currency} · MOQ {row.offer.min_order_quantity}</small><div className="cm3"><span>预计 CM3</span><b>{row.scenario ? `${row.scenario.cm3_cny} CNY` : "缺少场景"}</b><small>{row.scenario ? `${(Number(row.scenario.cm3_rate) * 100).toFixed(1)}% · 保本价 ${row.scenario.break_even_price_rub} RUB` : ""}</small></div>
              <label>采购数量<input type="number" min={row.offer.min_order_quantity} value={draft.quantity} onChange={(event) => setProcurementDrafts((current) => ({ ...current, [row.offer.id]: { ...draft, quantity: event.target.value } }))} /></label>
              <label>选择理由<textarea value={draft.rationale} onChange={(event) => setProcurementDrafts((current) => ({ ...current, [row.offer.id]: { ...draft, rationale: event.target.value } }))} placeholder="为什么选择它，而不是另外两家？" /></label>
              <button disabled={!comparison.ready_for_procurement_review || !passportReady || !row.has_positive_cm3} onClick={() => requestProcurement(comparison, row)}>提交双人采购审批</button>{!passportReady && <em>需先批准三本 Passport</em>}
            </article>;
          })}</div></div>)}
        </section>}

        <section className="procurement-panel">
          <div className="panel-title">
            <div><p className="eyebrow">SAMPLE PROCUREMENT</p><h3>样品采购与供应商验证</h3></div>
            <span className="gate ready">每一步必须有证据</span>
          </div>
          <div className="procurement-guardrail"><ShieldCheck size={17} /><p><strong>真实付款不会自动执行。</strong><span>已批准候选只能建立样品跟踪；供应商切换会生成一项新的双人审批。</span></p></div>
          {approvedWithoutSample.length > 0 && <div className="approved-order-queue">
            <strong>已通过双人审批，等待建立样品单</strong>
            {approvedWithoutSample.map((approval) => <button key={approval.id} disabled={procurementBusy === approval.id} onClick={() => createSampleOrder(approval.id)}>
              {procurementBusy === approval.id ? "正在建立…" : `建立样品单 · ${String(approval.payload.quantity ?? "-")} 件`}
            </button>)}
          </div>}
          {sampleOrders.length ? <div className="sample-order-grid">{sampleOrders.map((order) => {
            const performance = supplierPerformance.find((item) => item.supplier_ref === order.supplier_ref);
            const terminal = order.next_events.length === 0;
            return <article className="sample-order-card" key={order.id}>
              <div className="sample-order-head"><div><strong>{order.product.sku} · {order.product.name}</strong><small>{order.supplier_ref} · {order.quantity} 件 · {order.unit_price} {order.currency}/件</small></div><span className={`sample-state ${terminal ? "terminal" : ""}`}>{procurementStatusLabels[order.status] ?? order.status}</span></div>
              <div className="sample-progress">{["确认", "发货", "签收", "验货", "定样"].map((label, index) => <span className={order.events.length > index ? "done" : ""} key={label}>{label}</span>)}</div>
              <div className="sample-facts">
                <div><span>证据事件</span><b>{order.events.length}</b></div><div><span>供应商评分</span><b>{performance?.score ? `${performance.score} 分` : "待形成"}</b></div><div><span>样品成功</span><b>{performance ? `${performance.completed_sample_count}/${performance.sample_order_count}` : "-"}</b></div>
              </div>
              {order.events.length > 0 && <details className="sample-timeline"><summary>查看不可变进度记录</summary><ol>{order.events.map((item) => <li key={item.id}><span>{item.sequence}</span><div><strong>{procurementEventLabels[item.event_type] ?? item.event_type}</strong><small>{new Date(item.effective_at).toLocaleString("zh-CN")} · 证据 {item.evidence_id.slice(-8)}</small></div></li>)}</ol></details>}
              {!terminal && <form className="sample-event-form" onSubmit={(event) => recordSampleEvent(event, order)}>
                <strong>下一步：{order.status === "inspected" ? "形成样品决定" : procurementEventLabels[order.next_events.find((item) => item !== "cancelled") ?? ""]}</strong>
                {order.status === "approved_to_order" && <div className="sample-event-fields"><label>供应商订单号<input name="supplier_order_ref" required /></label><label>承诺交付时间<input name="promised_delivery_at" type="datetime-local" required /></label></div>}
                {order.status === "order_confirmed" && <div className="sample-event-fields"><label>物流单号<input name="tracking_ref" required /></label><label>承运商<input name="carrier" required /></label></div>}
                {order.status === "shipped" && <div className="sample-event-fields"><label>签收数量<input name="received_quantity" type="number" min="0" max={order.quantity} defaultValue={order.quantity} required /></label><label>破损数量<input name="damaged_quantity" type="number" min="0" defaultValue="0" required /></label></div>}
                {(order.status === "received" || order.status === "rework_required") && <div className="sample-event-fields"><label>验货数量<input name="inspected_quantity" type="number" min="1" max={order.quantity} defaultValue={order.quantity} required /></label><label>通过数量<input name="passed_quantity" type="number" min="0" max={order.quantity} defaultValue={order.quantity} required /></label><label>缺陷数<input name="defect_count" type="number" min="0" defaultValue="0" required /></label><label>验货结论<select name="inspection_result" defaultValue="passed"><option value="passed">通过</option><option value="failed">不通过</option><option value="rework">需返工</option></select></label></div>}
                {order.status === "inspected" && <div className="sample-event-fields"><label>样品决定<select name="sample_decision" defaultValue="golden_sample_approved"><option value="golden_sample_approved">批准为黄金样</option><option value="rework_required">要求返工</option><option value="sample_rejected">淘汰供应商样品</option></select></label><label>黄金样编号 / 决定原因<input name="decision_detail" required /></label></div>}
                <label className="sample-evidence">本步原始证据<input name="event_evidence" type="file" required /></label>
                <button disabled={procurementBusy === order.id}>{procurementBusy === order.id ? "正在固化…" : "提交进度与证据"}</button>
              </form>}
              <div className="backup-control">
                <button className="secondary" disabled={procurementBusy === order.id} onClick={() => loadBackupOptions(order.id)}>查看备用供应商</button>
                <small>只提供建议，不自动切换</small>
              </div>
              {backupOptions[order.id] && <div className="backup-list">{backupOptions[order.id].length ? backupOptions[order.id].map((option) => {
                const rationaleKey = `${order.id}:${option.offer.id}`;
                return <div key={option.offer.id}><div><strong>{option.offer.supplier_ref}</strong><small>{option.offer.unit_price} {option.offer.currency} · MOQ {option.offer.min_order_quantity} · CM3 {option.scenario.cm3_cny} CNY</small><input value={backupRationales[rationaleKey] ?? ""} onChange={(event) => setBackupRationales((current) => ({ ...current, [rationaleKey]: event.target.value }))} placeholder="填写切换理由" /></div><button disabled={procurementBusy === order.id} onClick={() => requestBackupProcurement(order, option)}>重新提交审批</button></div>;
              }) : <p>暂无正 CM3 备用方案。</p>}</div>}
            </article>;
          })}</div> : <div className="empty"><Boxes size={25} /><strong>还没有受控样品单</strong><p>三家比价通过、Passport 批准并完成双人采购审批后，才会进入这里。</p></div>}
          {supplierPerformance.length > 0 && <div className="supplier-scoreboard"><strong>供应商实绩榜</strong><div>{supplierPerformance.map((item) => <article key={item.supplier_ref}><span>{item.supplier_ref}</span><b>{item.score ? `${item.score} 分` : "数据不足"}</b><small>质量 {item.quality_yield ? `${(Number(item.quality_yield) * 100).toFixed(0)}%` : "-"} · 准时 {item.on_time_rate ? `${(Number(item.on_time_rate) * 100).toFixed(0)}%` : "-"} · {item.evidence_count} 份证据</small></article>)}</div></div>}
        </section>

        <section className="metrics">
          <article><span className="metric-icon green"><CircleDollarSign /></span><div><p>CM3 净利润</p><strong>待导入</strong><small>真实费用齐全后计算</small></div></article>
          <article><span className="metric-icon blue"><ShieldCheck /></span><div><p>SKU 准入门</p><strong>{readySkuCount} / 3</strong><small>{skuReadiness.length ? "三类护照全部批准才可上线" : "先录入 3 个真实候选 SKU"}</small></div></article>
          <article><span className="metric-icon violet"><Waypoints /></span><div><p>全球货源平台</p><strong>{sourceConnectors.length}</strong><small>{offers.length} 个商品报价已入库</small></div></article>
          <article><span className="metric-icon amber"><CheckCircle2 /></span><div><p>工具连接</p><strong>{toolCount} / 4</strong><small>Ollama · ComfyUI · n8n · Firecrawl</small></div></article>
        </section>

        <section className="grid">
          <article className="panel agents">
            <div className="panel-title"><div><p className="eyebrow">AI SQUAD</p><h3>Agent 团队</h3></div><span className="badge">影子模式</span></div>
            <div className="agent-list">
              {["市场分析", "商品策略", "俄语 Listing", "内容生产", "运营建议", "利润审计", "质量检查"].map((name, index) => (
                <div className="agent" key={name}><span>{index + 1}</span><div><strong>{name}</strong><small>{index < 2 ? "等待数据" : "等待上游任务"}</small></div><Clock3 size={16} /></div>
              ))}
            </div>
          </article>

          <article className="panel">
            <div className="panel-title"><div><p className="eyebrow">INFRASTRUCTURE</p><h3>现有工具状态</h3></div><Database size={20} /></div>
            <div className="health-list">
              {(["ollama", "comfyui", "n8n", "firecrawl"] as const).map((key) => {
                const item = health[key];
                const ok = item?.status === "ok";
                return <div key={key}><span className={ok ? "health-dot ok" : "health-dot"} /><div><strong>{key === "ollama" ? "Ollama 本地模型" : key === "comfyui" ? "ComfyUI 内容引擎" : key === "n8n" ? "n8n 内部自动化" : "Firecrawl 数据采集"}</strong><small>{item?.detail || (ok ? "连接正常" : "等待连接")}</small></div><span className={ok ? "state ok" : "state"}>{ok ? "在线" : "离线"}</span></div>;
              })}
            </div>
            <div className="license-note"><ShieldCheck size={18} /><p><strong>商业授权保护已开启</strong><span>授权不明的模型默认不能参与生产。</span></p></div>
          </article>

          <article className="panel recommendations">
            <div className="panel-title"><div><p className="eyebrow">DECISIONS</p><h3>最新经营建议</h3></div><BarChart3 size={20} /></div>
            {recommendations.length ? recommendations.slice(0, 4).map((item) => (
              <div className="recommendation" key={item.id}><span className="risk">{item.risk}</span><div><strong>{item.action}</strong><small>{item.agent} · {item.status}</small></div><b>{item.expected_cm3_delta ? `¥${item.expected_cm3_delta}` : "待评估"}</b></div>
            )) : <div className="empty"><TriangleAlert size={25} /><strong>还没有可验证的建议</strong><p>导入经营数据后，Agent 才会生成有证据的建议。</p></div>}
          </article>

          <article className="panel sku-gates">
            <div className="panel-title"><div><p className="eyebrow">GATE 0–1</p><h3>三 SKU 准入门</h3></div><ShieldCheck size={20} /></div>
            {skuReadiness.length ? <div className="sku-list">{skuReadiness.map((item) => {
              const approved = item.passports.filter((passport) => passport.status === "approved").length;
              const blocked = item.passports.some((passport) => passport.status === "blocked");
              const next = item.passports.find((passport) => passport.status !== "approved");
              return <div className="sku-card" key={item.product.id}>
                <div className="sku-card-head"><div><strong>{item.product.sku}</strong><small>{item.product.name}</small></div><span className={blocked ? "gate blocked" : item.ready_for_validation ? "gate ready" : "gate"}>{blocked ? "已阻断" : item.ready_for_validation ? "可验证" : `${approved}/3`}</span></div>
                <div className="passport-row">{item.passports.map((passport) => <span className={passport.status} key={passport.kind}>{passportLabels[passport.kind]}</span>)}</div>
                <p>{item.ready_for_validation ? "资料、合规和样品质量均已通过人工批准。" : blocked ? "存在否决结论，停止采购和上架。" : next ? `下一步：补齐${passportLabels[next.kind]}（缺 ${next.missing_fields.length} 项）` : "等待审核。"}</p>
              </div>;
            })}</div> : <div className="empty"><Boxes size={25} /><strong>尚未录入真实候选 SKU</strong><p>下一步先确定 3 个 SKU，再逐个补齐商品、合规和质量护照。</p></div>}
          </article>

          <article className="panel source-platforms">
            <div className="panel-title"><div><p className="eyebrow">GLOBAL SOURCING</p><h3>货源连接器</h3></div><Waypoints size={20} /></div>
            <div className="platform-chips">
              {sourceConnectors.map((item) => <span key={item.platform}>{item.platform}<small>{item.ingestion}</small></span>)}
            </div>
            <div className="license-note"><Database size={18} /><p><strong>Supabase 数据底座</strong><span>报价、证据、利润方案和上架草稿统一留痕。</span></p></div>
          </article>
        </section>
      </section>
    </main>
  );
}
