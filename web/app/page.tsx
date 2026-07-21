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
  Download,
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
type WebSession = {
  authenticated: boolean;
  auth_mode: "legacy" | "supabase";
  email: string | null;
  actor_id: string;
  roles: string[];
};
type OzonImportResult = {
  id: string;
  record_type: string;
  filename: string;
  status: string;
  row_count: number;
  accepted_count: number;
  rejected_count: number;
  evidence_id: string | null;
  duplicate: boolean;
};
type OzonImportPreview = {
  record_type: string;
  row_count: number;
  mapping: Record<string, string>;
  missing_columns: string[];
  ready: boolean;
};
type FinanceReviewStatus = {
  import_id: string;
  report_evidence_id: string;
  record_type: string;
  status: "pending" | "accepted" | "rejected";
  ready: boolean;
  review_count: number;
  report_period_start: string;
  report_period_end: string;
  review_packet: {
    source: {
      filename: string; sha256: string; byte_size: number; content_type: string;
      submitted_by: string; recorded_at: string;
    };
    import: {
      filename: string; sha256: string; status: string; row_count: number;
      accepted_count: number; rejected_count: number; mapped_fields: string[];
    };
    integrity: {
      evidence_valid: boolean; sha256_matches_import: boolean;
      source_lineage_verified: boolean; row_numbers_contiguous: boolean;
    };
    aggregates: {
      currency_totals: Array<{ currency: string; row_count: number; total_amount: string }>;
      earliest_effective_at: string | null; latest_effective_at: string | null;
      accrual_pairs: Array<{
        accrual_group: string; accrual_type: string; row_count: number;
        currency_totals: Array<{ currency: string; total_amount: string }>;
      }>;
    };
    boundaries: {
      aggregate_only: true; raw_rows_exposed: false; automatic_acceptance: false;
      automatic_classification: false; automatic_finance_posting: false;
    };
  };
};
type CostAuthorityCatalog = {
  schema_version: "cost-actual-authority-v1";
  items: Array<{
    cost_type: string;
    label: string;
    authorities: Array<{ id: string; label: string }>;
  }>;
  automatic_state_change: false;
  automatic_finance_posting: false;
  automatic_procurement: false;
  automatic_listing: false;
};
type ActualCostAuthorityStatus = {
  evidence_id: string;
  cost_type: string;
  status: "pending" | "accepted" | "rejected";
  accepted_authorities: string[];
  review_ids: string[];
  review_count: number;
};
type FeeCodeStatus = {
  import_id: string;
  record_type: "ozon_fee";
  ready: boolean;
  codes: Array<{
    raw_code: string;
    row_count: number;
    earliest_effective_at: string;
    latest_effective_at: string;
    ready: boolean;
    mapping_ids: string[];
  }>;
};
type AccrualClassificationStatus = {
  import_id: string;
  record_type: "ozon_accrual";
  ready: boolean;
  posting_policy: "control_only_no_finance_entry";
  automatic_finance_posting: false;
  order_revenue_replacement: false;
  pairs: Array<{
    accrual_group: string;
    accrual_type: string;
    row_count: number;
    total_amount: string | null;
    currency: string | null;
    currency_totals: Array<{ currency: string; total_amount: string }>;
    observed_signs: Array<"positive" | "negative" | "zero">;
    earliest_effective_at: string;
    latest_effective_at: string;
    ready: boolean;
    approval_ids: string[];
    accounting_classes: string[];
    expected_signs: Array<"positive" | "negative" | "either">;
  }>;
};
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
type ProductMediaReadiness = {
  product: ProductIdentity;
  roles: Array<{
    role: string;
    status: "missing" | "captured_pending_passport" | "approved";
    source_asset_evidence_id: string | null;
    rights_evidence_id: string | null;
  }>;
  approved_role_count: number;
  missing_roles: string[];
  pending_passport_roles: string[];
  all_passports_approved: boolean;
  ready_for_full_production: boolean;
  automatic_generation: false;
  next_action: string;
};
type ContentAssetView = {
  id: string;
  product_id: string;
  content_type: string;
  status: string;
  brief: Record<string, unknown>;
  artifact_ref: string | null;
  qa_results: Array<{
    check: string;
    passed: boolean;
    notes: string;
    evidence_ids: string[];
    reviewed_by: string;
    reviewed_at: string;
  }>;
  generation: Record<string, unknown>;
  created_at: string;
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
    scenario: null | {
      id: string; cm3_cny: string; cm3_rate: string; break_even_price_rub: string; evidence: string[];
      template_id: string; cost_states: Record<string, "estimate" | "actual" | "unknown">;
      cost_evidence: Record<string, string>;
    };
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
  details?: Record<string, unknown>;
};
type GateReadiness = {
  status: "ready_for_review" | "needs_input";
  g0: "ready_for_review" | "blocked";
  g1: "ready_for_review" | "blocked";
  decision_scope_readiness?: {
    research: { ready: boolean; blocking_reasons: string[] };
    real_execution: { ready: boolean; blocking_reasons: string[] };
  };
  requirements: GateRequirement[];
  next_actions: string[];
  candidate_portfolio: {
    target_count: number; candidate_count: number; selection_ready_count: number; advisory_only: true;
    automatic_product_selection: false; automatic_procurement: false; automatic_pricing: false; automatic_listing: false;
    rows: Array<{
      product: ProductIdentity; qualified_candidate: boolean; passports_ready: boolean; supplier_count: number;
      offer_count: number; profit_scenario_count: number; complete_profit_scenario_count: number;
      sourcing_ready: boolean; ready_for_g1_review: boolean; blockers: string[];
      best_scenario: null | {
        id: string | null; offer_id: string; supplier_ref: string | null; cm3_cny: string; cm3_rate: string;
        break_even_price_rub: string; template_id: string | null; unknown_costs: string[];
        evidence_count: number; release_ready: boolean;
      };
    }>;
  };
  exception_workspace: {
    blocked_count: number; counts_by_gate: Record<string, number>; advisory_only: true;
    automatic_resolution: false; platform_write_allowed: false;
    items: Array<{
      queue_key: string; item_type: "gate_blocker"; source_type: "gate_requirement"; source_id: string;
      gate: string; title: string; status: "blocked"; attention: "current_gate" | "downstream";
      owner_role: string; current: number; target: number; next_action: string; details: Record<string, unknown>;
    }>;
  };
};
type EvidenceSummary = {
  id: string; filename: string; source: string; source_ref: string; grade: string;
  effective_at: string; effective_until: string | null; created_by: string;
  metadata: Record<string, unknown>;
};
type CandidateResearchAssessment = {
  candidate_ref: string; candidate_name: string; market: string; category: string; decision: "reject" | "collect_evidence" | "request_three_quotes";
  demand_report_evidence_id: string;
  reasons: string[]; missing_metrics: string[]; source_family_count: number; evidence_ids: string[];
  low_authority_evidence_ids: string[]; minimum_evidence_grades: Record<string, string[]>;
  measurement_policy_id: string; quote_policy_id: string; quote_policy_status: string; metric_values: Record<string, string>;
  threshold_failures: Array<{ metric: string; operator: "gte" | "lte"; threshold: string; actual: string }>;
  required_supplier_quotes: number; automatic_product_creation: false; automatic_listing: false; next_gate: string | null;
};
type CandidateAuthorityStatus = {
  evidence_id: string; metric: string; status: "pending" | "accepted" | "rejected";
  accepted_grades: string[]; review_count: number;
};
type CandidateSourcingHandoff = {
  product: ProductIdentity; created: boolean; candidate_ref: string; evidence_ids: string[]; next_gate: "sourcing_comparison_intake";
  automatic_procurement: false; automatic_listing: false;
};
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
  assumptions: string[]; unknowns: string[]; selection_assessment: Record<string, unknown>;
  evidence_ids: string[]; model_ref: string | null;
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
type OperationalIncident = {
  id: string; mode: "live" | "drill"; severity: string; trigger_type: string;
  source_type: string | null; source_id: string | null; summary: string; impact: string[];
  status: string; owner_id: string | null; review_status: string | null; opened_by: string;
  checks: Record<string, { check: string; passed: boolean; notes: string }>;
  required_checks: string[]; kill_switch_engaged: boolean; automatic_release: boolean;
};
type OperationsQueueItem = {
  queue_key: string; item_type: string; item_id: string; title: string; status: string;
  priority: string; owner_id: string | null; due_at: string; overdue: boolean;
  overdue_minutes: number; escalation_level: number; next_action: string;
};
type ReadOnlyPilot = {
  id: string; platform: string; account_alias: string; allowed_operations: string[];
  max_daily_requests: number; max_targets: number; starts_at: string; ends_at: string;
  status: string; requested_by: string; reviewed_by: string | null; activated_by: string | null;
  controls: Record<string, { passed: boolean; notes: string }>;
  required_controls: string[]; platform_write_allowed: boolean; execution_eligible: boolean;
  credential_material_stored: boolean;
};
type PilotEvaluation = {
  ready_for_review: boolean; ready_for_activation: boolean; requirements: Record<string, boolean>;
  blockers: string[]; recent_drill_ids: string[]; platform_write_allowed: boolean; automatic_activation: boolean;
};

const passportLabels = { product: "商品资料", compliance: "俄罗斯合规", quality: "样品质量" } as const;
const productMediaRoleLabels: Record<string, string> = {
  front_main: "正面主图", back: "背面", side: "侧面", detail: "细节",
  accessories: "配件", packaging: "包装", scale_reference: "比例参照",
};
const candidateMetricDefinitions = [
  ["demand_signal", "需求信号", "类目需求百分位；至少 28 天、30 个样本；询价线 ≥50", 30, 30],
  ["competition_gap", "竞争缺口", "类目供需缺口百分位；至少 28 天、30 个样本；询价线 ≥50", 30, 30],
  ["supplier_available", "可采购性", "是否已有可核验供应来源；至少核验 1 个供应对象", 30, 1],
  ["compliance_redline", "合规红线", "按当前官方规则核验；一旦确认红线，候选立即淘汰", 30, 1],
  ["return_risk", "退货风险", "预期 30 日退货率百分比；至少 28 天、30 个样本；询价线 ≤30%", 30, 30],
] as const;
const candidateMetricLabels = Object.fromEntries(candidateMetricDefinitions.map(([key, label]) => [key, label]));
const sourcingCostDefinitions = [
  ["product_cost", "采购成本"], ["domestic_logistics", "国内物流"],
  ["international_logistics", "头程物流"], ["packaging", "包装"],
  ["warehousing", "仓储"], ["customs", "关税"], ["tax", "税费"],
  ["last_mile", "尾程"], ["platform_fee", "平台佣金"], ["advertising", "广告"],
  ["return", "退款退货"], ["fx", "汇兑"], ["capital_cost", "资金占用"],
  ["aftersales", "售后"], ["loss", "损耗"],
] as const;
const costStateLabels = { estimate: "预估", actual: "实际", unknown: "未知（阻断）" } as const;
const financeReviewRecordTypes = new Set(["ozon_accrual", "ozon_fee", "ozon_return", "ozon_settlement"]);
const imageQaDefinitions = [
  ["factual_grounding", "事实一致", "商品事实、参数与已批准 Passport 一致"],
  ["policy", "平台规则", "主图、文字和表达符合当前 Ozon 规则"],
  ["localization", "俄语本地化", "俄语自然、无歧义，适合目标消费者"],
  ["ip_rights", "知识产权", "图片、字体、品牌和素材权利可追溯"],
  ["brand", "品牌一致", "视觉语气、颜色与品牌规范一致"],
  ["product_fidelity", "商品保真", "外观、颜色、结构、配件和数量未被改变"],
  ["source_provenance", "来源血缘", "原图、权利文件、处理结果与 Evidence 对应"],
  ["text_accuracy", "文字参数", "图中俄语、尺寸、数量和声明准确无误"],
] as const;
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
  const [webSession, setWebSession] = useState<WebSession | null>(null);
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
  const [notice, setNotice] = useState("等待第一份 Ozon 数据");

  const load = useCallback(async () => {
    const [healthResponse, recommendationResponse, connectorResponse, offersResponse, productsResponse, gateResponse, reviewResponse, approvalsResponse, sampleOrdersResponse, supplierPerformanceResponse, evidenceResponse, profileResponse, contractResponse, analysisResponse, resolutionResponse, outcomeResponse, calibrationResponse, experimentResponse, causalKnowledgeResponse, causalPolicyResponse, policyShadowResponse, policyHandoffResponse, executionPlanResponse, executionCommandResponse, executionObservationResponse, capabilityEconomicsResponse, operationalIncidentsResponse, operationsQueueResponse, readOnlyPilotsResponse, costAuthorityResponse] = await Promise.all([
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
      fetch("/backend/v1/operational-incidents", { cache: "no-store" }),
      fetch("/backend/v1/operations-control/queue", { cache: "no-store" }),
      fetch("/backend/v1/read-only-pilots", { cache: "no-store" }),
      fetch("/backend/v1/finance/cost-authorities", { cache: "no-store" }),
    ]);
    if (healthResponse.ok) setHealth(await healthResponse.json());
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
    if (operationalIncidentsResponse.ok) setOperationalIncidents(await operationalIncidentsResponse.json());
    if (operationsQueueResponse.ok) setOperationsQueue(await operationsQueueResponse.json());
    if (readOnlyPilotsResponse.ok) {
      const rows: ReadOnlyPilot[] = await readOnlyPilotsResponse.json(); setReadOnlyPilots(rows);
      const evaluations = await Promise.all(rows.map(async (item) => { const response = await fetch(`/backend/v1/read-only-pilots/${item.id}/evaluation`, { cache: "no-store" }); return [item.id, response.ok ? await response.json() as PilotEvaluation : null] as const; }));
      const indexed: Record<string, PilotEvaluation> = {}; evaluations.forEach(([id, evaluation]) => { if (evaluation) indexed[id] = evaluation; }); setPilotEvaluations(indexed);
    }
    if (productsResponse.ok) {
      const products: ProductIdentity[] = await productsResponse.json();
      setProducts(products);
      const candidateProducts = gateData?.candidate_portfolio.rows.map((item) => item.product) ?? [];
      const readiness = await Promise.all(
        candidateProducts.map(async (product) => {
          const response = await fetch(`/backend/v1/products/${product.id}/readiness`, { cache: "no-store" });
          return response.ok ? response.json() as Promise<ProductReadiness> : null;
        }),
      );
      setSkuReadiness(readiness.filter((item): item is ProductReadiness => item !== null));
      const mediaReadiness = await Promise.all(
        candidateProducts.map(async (product) => {
          const response = await fetch(`/backend/v1/products/${product.id}/media-readiness`, { cache: "no-store" });
          return response.ok ? response.json() as Promise<ProductMediaReadiness> : null;
        }),
      );
      setProductMediaReadiness(mediaReadiness.filter((item): item is ProductMediaReadiness => item !== null));
      const assetRows = await Promise.all(
        candidateProducts.map(async (product) => {
          const response = await fetch(`/backend/v1/products/${product.id}/content-assets`, { cache: "no-store" });
          return response.ok ? response.json() as Promise<ContentAssetView[]> : [];
        }),
      );
      setContentAssets(assetRows.flat());
      const comparisonRows = await Promise.all(candidateProducts.map(async (product) => {
        const response = await fetch(`/backend/v1/sourcing/comparisons/${product.id}`, { cache: "no-store" });
        return response.ok ? response.json() as Promise<SourcingComparison> : null;
      }));
      setComparisons(comparisonRows.filter((item): item is SourcingComparison => item !== null && item.offer_count > 0));
    }
  }, []);

  useEffect(() => {
    async function boot() {
      const sessionResponse = await fetch("/auth/session", { cache: "no-store" });
      if (sessionResponse.status === 401) {
        window.location.assign("/login");
        return;
      }
      if (sessionResponse.status === 428) {
        window.location.assign("/mfa");
        return;
      }
      if (!sessionResponse.ok) {
        const body = await sessionResponse.json().catch(() => ({}));
        setNotice(body.detail ?? "Web 身份服务尚未就绪");
        return;
      }
      setWebSession(await sessionResponse.json());
      await load();
    }
    boot().catch(() => setNotice("后端或身份服务尚未启动，请先检查 KJDS 服务"));
  }, [load]);

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
      const preflightResponse = await fetch("/backend/v1/imports/ozon/preflight", { method: "POST", body: uploadBody() });
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
      const response = await fetch("/backend/v1/imports/ozon", { method: "POST", body: uploadBody() });
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
      const response = await fetch(`/backend/v1/imports/${encodeURIComponent(importId)}/finance-review`, { cache: "no-store" });
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
      const response = await fetch(`/backend/v1/imports/${encodeURIComponent(importId)}/finance-review`, {
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
      const response = await fetch(
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
      const response = await fetch(`/backend/v1/finance/cost-evidence/${encodeURIComponent(evidenceId)}/authority-review`, {
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
    const response = await fetch(`/backend/v1/imports/${encodeURIComponent(importId)}/fee-codes`, { cache: "no-store" });
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
      const response = await fetch(`/backend/v1/imports/${encodeURIComponent(importId)}/fee-mappings`, {
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
    const response = await fetch(`/backend/v1/imports/${encodeURIComponent(importId)}/accrual-classifications`, { cache: "no-store" });
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
      const response = await fetch(`/backend/v1/imports/${encodeURIComponent(importId)}/accrual-classifications`, {
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
      const response = await fetch("/backend/v1/operations/gate-evidence", { method: "POST", body });
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
      const response = await fetch("/backend/v1/operations/demand-report-review", {
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
      const response = await fetch("/backend/v1/market/research-signals", { method: "POST", body });
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
      const response = await fetch(`/backend/v1/market/candidate-evidence/${encodeURIComponent(evidenceId)}/authority-review?metric=${encodeURIComponent(metric)}`, { cache: "no-store" });
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
      const response = await fetch(`/backend/v1/market/candidate-evidence/${encodeURIComponent(evidenceId)}/authority-review`, {
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
      const response = await fetch("/backend/v1/market/candidates/intake", {
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
      const response = await fetch("/backend/v1/market/candidates/sourcing-handoff", {
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
      const response = await fetch(`/backend/v1/products/${productId}/media-evidence`, { method: "POST", body });
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
      const response = await fetch("/backend/v1/content/assets", {
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
      const response = await fetch(endpoint, { method: "POST" });
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
      const response = await fetch(`/backend/v1/content/assets/${asset.id}/review`, {
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
      const response = await fetch("/backend/v1/listings/ozon/drafts", {
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
      const response = await fetch(`/backend/v1/decision-contracts/${contractId}/analyses`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
      const response = await fetch(`/backend/v1/execution-observation-windows/${window.id}/capability-economics`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const result = await response.json();
      setNotice(response.ok ? `能力净价值：${result.net_value} ${result.currency}。该结果只形成治理建议，不会自动改变权限。` : result.detail ?? "能力损益核算失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法完成能力损益核算，请检查观察是否结束及证据是否有效"); }
    finally { setLifecycleBusy(null); }
  }

  async function claimIncident(incident: OperationalIncident) {
    setLifecycleBusy(`incident-claim:${incident.id}`); setNotice("正在登记事故恢复负责人…");
    try {
      const response = await fetch(`/backend/v1/operational-incidents/${incident.id}/claim`, { method: "POST" });
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
      const response = await fetch(`/backend/v1/operational-incidents/${incident.id}/checks`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ check: value("incident_check"), passed: true, notes: value("incident_check_notes"), evidence_ids: [value("incident_check_evidence")] }) });
      const result = await response.json(); setNotice(response.ok ? "恢复检查已记录，历史不可覆盖。" : result.detail ?? "恢复检查失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法记录恢复检查，请确认当前身份是事故负责人"); }
    finally { setLifecycleBusy(null); }
  }

  async function submitIncidentReview(incident: OperationalIncident) {
    setLifecycleBusy(`incident-submit:${incident.id}`); setNotice("正在核对五项恢复条件并申请独立复核…");
    try {
      const response = await fetch(`/backend/v1/operational-incidents/${incident.id}/review-request`, { method: "POST" });
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
      const response = await fetch(`/backend/v1/operational-incidents/${incident.id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ accepted: value("incident_review_verdict") === "accepted", rationale: value("incident_review_rationale"), evidence_ids: [value("incident_review_evidence")] }) });
      const result = await response.json(); setNotice(response.ok ? (result.review_status === "accepted" ? "独立复核通过；仍需管理员单独解除熔断。" : "复核未通过，已退回继续恢复。") : result.detail ?? "事故复核失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法完成独立复核，请确认复核者不是事故发起人或负责人"); }
    finally { setLifecycleBusy(null); }
  }

  async function releaseIncidentFreeze(incident: OperationalIncident) {
    setLifecycleBusy(`incident-release:${incident.id}`); setNotice("正在请求管理员明确解除写入熔断…");
    try {
      const response = await fetch("/backend/v1/system/kill-switch/release", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: `Incident ${incident.id} independently reviewed; controlled recovery release` }) });
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
      const response = await fetch(`/backend/v1/operational-incidents/${incident.id}/close`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ notes: value("incident_close_notes"), evidence_ids: [value("incident_close_evidence")] }) });
      const result = await response.json(); setNotice(response.ok ? `事故 ${result.id} 已关闭，完整恢复历史已保留。` : result.detail ?? "事故关闭失败");
      if (response.ok) { form.reset(); await load(); }
    } catch { setNotice("无法关闭事故，请检查熔断状态和关闭证据"); }
    finally { setLifecycleBusy(null); }
  }

  async function scanOperationsQueue() {
    setLifecycleBusy("operations-scan"); setNotice("正在扫描逾期任务并固化升级记录…");
    try { const response = await fetch("/backend/v1/operations-control/escalation-scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ as_of: null }) }); const result = await response.json(); setNotice(response.ok ? `扫描 ${result.scanned_count} 项，发现 ${result.overdue_count} 项逾期，新建 ${result.new_escalation_ids.length} 条升级记录。` : result.detail ?? "运营队列扫描失败"); if (response.ok) await load(); }
    catch { setNotice("无法扫描运营队列"); } finally { setLifecycleBusy(null); }
  }

  async function createReadOnlyPilot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    const operations = Array.from(form.querySelectorAll<HTMLInputElement>('input[name="pilot_operations"]:checked')).map((item) => item.value);
    const body = { idempotency_key: `ozon-read-only-${value("pilot_account_alias")}-${value("pilot_starts_at")}`, platform: "ozon", account_alias: value("pilot_account_alias"), allowed_operations: operations, max_daily_requests: Number(value("pilot_daily_limit")), max_targets: Number(value("pilot_target_limit")), starts_at: new Date(value("pilot_starts_at")).toISOString(), ends_at: new Date(value("pilot_ends_at")).toISOString(), evidence_ids: [value("pilot_evidence")] };
    setLifecycleBusy("pilot-create"); setNotice("正在固化 Ozon 只读试点边界…");
    try { const response = await fetch("/backend/v1/read-only-pilots", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); const result = await response.json(); setNotice(response.ok ? `只读试点 ${result.id} 已建立；平台写入仍被永久禁止。` : result.detail ?? "试点建立失败"); if (response.ok) { form.reset(); await load(); } }
    catch { setNotice("无法建立只读试点，请检查期限、限额和证据"); } finally { setLifecycleBusy(null); }
  }

  async function attestPilotControl(event: FormEvent<HTMLFormElement>, pilot: ReadOnlyPilot) {
    event.preventDefault(); const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    setLifecycleBusy(`pilot-attest:${pilot.id}`); setNotice("正在记录试点控制证据…");
    try { const response = await fetch(`/backend/v1/read-only-pilots/${pilot.id}/attestations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ control: value("pilot_control"), passed: true, notes: value("pilot_control_notes"), evidence_ids: [value("pilot_control_evidence")] }) }); const result = await response.json(); setNotice(response.ok ? "控制项已记录，仍需完成其余准入条件。" : result.detail ?? "控制项记录失败"); if (response.ok) { form.reset(); await load(); } }
    catch { setNotice("无法记录试点控制项"); } finally { setLifecycleBusy(null); }
  }

  async function submitPilotReview(pilot: ReadOnlyPilot) {
    setLifecycleBusy(`pilot-submit:${pilot.id}`); setNotice("正在核对控制项、事故、熔断与近期演练…");
    try { const response = await fetch(`/backend/v1/read-only-pilots/${pilot.id}/review-request`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ as_of: null }) }); const result = await response.json(); setNotice(response.ok ? "只读试点已提交独立复核。" : result.detail ?? "试点仍不满足准入条件"); if (response.ok) await load(); }
    catch { setNotice("无法提交试点复核"); } finally { setLifecycleBusy(null); }
  }

  async function reviewPilot(event: FormEvent<HTMLFormElement>, pilot: ReadOnlyPilot) {
    event.preventDefault(); const form = event.currentTarget;
    const value = (name: string) => (form.elements.namedItem(name) as HTMLInputElement | HTMLSelectElement | null)?.value.trim() ?? "";
    setLifecycleBusy(`pilot-review:${pilot.id}`); setNotice("正在执行只读试点独立复核…");
    try { const response = await fetch(`/backend/v1/read-only-pilots/${pilot.id}/review`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ accepted: value("pilot_review_verdict") === "accepted", rationale: value("pilot_review_rationale") }) }); const result = await response.json(); setNotice(response.ok ? `试点复核结果：${result.status}。` : result.detail ?? "试点复核失败"); if (response.ok) { form.reset(); await load(); } }
    catch { setNotice("无法完成试点独立复核"); } finally { setLifecycleBusy(null); }
  }

  async function activatePilot(pilot: ReadOnlyPilot) {
    setLifecycleBusy(`pilot-activate:${pilot.id}`); setNotice("正在重新核验全部准入条件…");
    try { const response = await fetch(`/backend/v1/read-only-pilots/${pilot.id}/activate`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ as_of: null }) }); const result = await response.json(); setNotice(response.ok ? `试点 ${result.id} 已激活：仅允许只读接口，禁止任何平台写入。` : result.detail ?? "试点激活被阻断"); if (response.ok) await load(); }
    catch { setNotice("无法激活只读试点"); } finally { setLifecycleBusy(null); }
  }

  const toolCount = Object.values(health).filter((item) => item.status === "ok").length;
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
  const readySkuCount = skuReadiness.filter((item) => item.ready_for_validation).length;
  const pendingProcurementApprovals = approvals.filter((item) => item.action === "procurement.place_order" && item.status === "pending").length;
  const pendingListingApprovals = approvals.filter((item) => item.action === "listing.publish" && item.status === "pending");
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
  const actualCostAuthorityItem = costAuthorityCatalog?.items.find((item) => item.cost_type === actualCostType);
  const reviewableCostEvidence = evidenceRecords.filter((item) => item.source !== "cost_actual_authority_review");
  const researchSignals = evidenceRecords.filter((record) => record.metadata.evidence_role === "research_signal");

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
          <div className="topbar-actions">
            <div className="session-chip">
              <ShieldCheck size={16} />
              <span>
                {webSession?.email ?? (webSession?.auth_mode === "legacy" ? "本地运营身份" : "身份校验中")}
                {webSession ? ` · ${webSession.actor_id} · ${webSession.roles.join("/")}` : ""}
              </span>
            </div>
            {webSession?.auth_mode === "supabase" ? <form action="/auth/logout" method="post"><button className="refresh" type="submit">退出</button></form> : null}
            <button className="refresh" onClick={() => load()}><RefreshCw size={17} />刷新状态</button>
          </div>
        </header>

        <section className="hero" id="ozon-import">
          <div>
            <span className="hero-tag"><Sparkles size={15} />核心目标：单品净利润 CM3</span>
            <h2>先用真实数据跑通 3 个 SKU，<br />再把成功打法复制成规模。</h2>
            <p>系统会追踪证据、利润、内容和实验结果；缺失数据会明确提示，不允许 AI 编造。</p>
          </div>
          <form className="upload" onSubmit={upload}>
            <FileUp size={23} />
            <label htmlFor="ozon-file">导入 Ozon 经营数据</label>
            <span>支持 CSV / XLSX；先只读预检原文件，通过后才存证和导入</span>
            <input id="ozon-file" name="file" type="file" accept=".csv,.xlsx" />
            <div className="report-period-fields">
              <label>查询开始日期<input name="report_period_start" type="date" required /></label>
              <label>查询结束日期<input name="report_period_end" type="date" required /></label>
            </div>
            <button disabled={uploading}>{uploading ? "正在处理…" : "预检并导入"}</button>
          </form>
        </section>

        <div className="notice"><Activity size={17} /><span>{notice}</span></div>

        {(lastOzonImport && financeReviewRecordTypes.has(lastOzonImport.record_type)) || canReviewFinance ? (
          <section className="finance-review-panel" aria-labelledby="finance-review-title">
            <div className="finance-review-head">
              <div><p className="eyebrow">DOUBLE CONTROL</p><h3 id="finance-review-title">Ozon 财务来源复核</h3></div>
              <span className={`gate ${financeReviewStatus?.status === "accepted" ? "ready" : financeReviewStatus?.status === "rejected" ? "blocked" : ""}`}>
                {financeReviewStatus?.status === "accepted" ? "来源已接受" : financeReviewStatus?.status === "rejected" ? "来源已拒绝" : "等待复核"}
              </span>
            </div>
            <p className="finance-review-boundary">应计、费用、退货和结算文件上传后只进入暂存区。复核通过也不会自动入账、批准会计字段或启动对账。</p>
            <div className="finance-review-grid">
              <article className="finance-handoff">
                <strong>上传人交接</strong>
                {lastOzonImport && financeReviewRecordTypes.has(lastOzonImport.record_type) ? <>
                  <dl>
                    <div><dt>导入编号</dt><dd><code>{lastOzonImport.id}</code></dd></div>
                    <div><dt>文件类型</dt><dd>{lastOzonImport.record_type}</dd></div>
                    <div><dt>暂存结果</dt><dd>{lastOzonImport.accepted_count}/{lastOzonImport.row_count} 行可解析</dd></div>
                    <div><dt>当前状态</dt><dd>{financeReviewStatus?.status ?? "pending"} · 未入账</dd></div>
                    <div><dt>交接期间</dt><dd>{financeReviewStatus ? `${financeReviewStatus.report_period_start} — ${financeReviewStatus.report_period_end}` : "读取中"}</dd></div>
                  </dl>
                  <p>把导入编号交给另一位 Reviewer/Compliance 用户；上传人不能复核自己的文件。</p>
                </> : <p>本会话没有刚上传的财务文件。复核人可在右侧输入上传人提供的导入编号。</p>}
              </article>
              {canReviewFinance ? <form className="finance-review-form" onSubmit={reviewFinanceReport}>
                <strong>独立复核人</strong>
                <label>导入编号
                  <span className="finance-review-id-row">
                    <input name="finance_review_import_id" value={financeReviewImportId} onChange={(event) => setFinanceReviewImportId(event.target.value)} required />
                    <button type="button" disabled={financeReviewBusy || !financeReviewImportId.trim()} onClick={() => loadFinanceReviewStatus()}>{financeReviewBusy ? "读取中…" : "读取状态"}</button>
                  </span>
                </label>
                {financeReviewStatus ? <div className="finance-handoff" role="note" aria-label="财务原件只读核验包">
                  <strong>提交前核验包</strong>
                  <dl>
                    <div><dt>原件</dt><dd>{financeReviewStatus.review_packet.source.filename} · {financeReviewStatus.review_packet.source.byte_size} bytes</dd></div>
                    <div><dt>SHA-256</dt><dd><code>{financeReviewStatus.review_packet.source.sha256}</code></dd></div>
                    <div><dt>上传身份</dt><dd><code>{financeReviewStatus.review_packet.source.submitted_by}</code></dd></div>
                    <div><dt>解析覆盖</dt><dd>{financeReviewStatus.review_packet.import.accepted_count}/{financeReviewStatus.review_packet.import.row_count} 行通过；{financeReviewStatus.review_packet.import.rejected_count} 行拒绝</dd></div>
                    <div><dt>精确合计</dt><dd>{financeReviewStatus.review_packet.aggregates.currency_totals.length ? financeReviewStatus.review_packet.aggregates.currency_totals.map((item) => `${item.total_amount} ${item.currency}（${item.row_count} 行）`).join("；") : "原件没有可聚合金额"}</dd></div>
                    <div><dt>日期覆盖</dt><dd>{financeReviewStatus.review_packet.aggregates.earliest_effective_at && financeReviewStatus.review_packet.aggregates.latest_effective_at ? `${financeReviewStatus.review_packet.aggregates.earliest_effective_at} — ${financeReviewStatus.review_packet.aggregates.latest_effective_at}` : "无可聚合日期"}</dd></div>
                    <div><dt>完整性</dt><dd>{Object.values(financeReviewStatus.review_packet.integrity).every(Boolean) ? "原件、哈希、血缘和行号连续性均通过" : "存在完整性异常，禁止接受"}</dd></div>
                  </dl>
                  {financeReviewStatus.review_packet.aggregates.accrual_pairs.length ? <details>
                    <summary>查看原件中 {financeReviewStatus.review_packet.aggregates.accrual_pairs.length} 个应计组/类型</summary>
                    <ul>{financeReviewStatus.review_packet.aggregates.accrual_pairs.map((item) => <li key={`${item.accrual_group}:${item.accrual_type}`}><strong>{item.accrual_group} / {item.accrual_type}</strong><span>{item.row_count} 行 · {item.currency_totals.map((total) => `${total.total_amount} ${total.currency}`).join("；")}</span></li>)}</ul>
                  </details> : null}
                  <p>这里只展示只读聚合，不返回商品、订单或客户原始行；核验包不会自动接受、分类或入账。</p>
                </div> : null}
                <fieldset>
                  <legend>逐项核对原件</legend>
                  <label><input name="authentic_account_export" type="checkbox" />来自真实 Ozon 店铺账户导出</label>
                  <label><input name="period_matches" type="checkbox" />报告期间与上方结构化交接期间一致</label>
                  <label><input name="not_public_sample" type="checkbox" />不是公开样例或演示数据</label>
                  <label><input name="complete_export" type="checkbox" />导出完整，没有缺页或截断</label>
                </fieldset>
                <label>复核结论
                  <select name="finance_review_decision" defaultValue="accepted"><option value="accepted">接受来源</option><option value="rejected">拒绝并保持阻塞</option></select>
                </label>
                <label>依据与异常说明<textarea name="finance_review_rationale" minLength={1} required /></label>
                <button className="finance-review-submit" disabled={financeReviewBusy}>{financeReviewBusy ? "正在提交…" : "保存不可变复核记录"}</button>
              </form> : <article className="finance-review-locked"><ShieldCheck size={23} /><strong>当前身份只能上传</strong><p>请让另一位拥有 Reviewer 或 Compliance 角色的用户登录后完成复核。</p></article>}
            </div>
            {canReviewFinance && financeReviewStatus?.status === "accepted" && financeReviewStatus.record_type === "ozon_fee" ? (
              <div className="fee-mapping-panel">
                <div className="fee-mapping-status">
                  <strong>实际费用代码</strong>
                  <span className={`gate ${feeCodeStatus?.ready ? "ready" : "blocked"}`}>{feeCodeStatus?.ready ? "全部已映射" : "仍有未映射代码"}</span>
                  <p>只显示该已接受文件中真实出现的代码。每条映射单独留证；全部覆盖后 Operator 才能另行晋升事实。</p>
                  <ul>{feeCodeStatus?.codes.map((item) => <li key={item.raw_code}><code>{item.raw_code}</code><span>{item.row_count} 行 · {item.ready ? "已覆盖" : "待批准"}</span></li>)}</ul>
                </div>
                <form className="finance-review-form" onSubmit={approveFeeMapping}>
                  <strong>批准一个代码映射</strong>
                  <label>原始费用代码<select name="fee_raw_code" defaultValue="" required><option value="">选择文件中的代码</option>{feeCodeStatus?.codes.map((item) => <option value={item.raw_code} key={item.raw_code}>{item.raw_code}{item.ready ? "（已有有效映射）" : ""}</option>)}</select></label>
                  <label>会计类型<select name="fee_canonical_type" defaultValue="platform_fee" required><option value="platform_fee">平台佣金/服务费</option><option value="international_logistics">国际物流</option><option value="last_mile">尾程配送</option><option value="warehousing">仓储</option><option value="advertising">广告</option><option value="return">退货</option><option value="refund">退款</option><option value="tax">税费</option><option value="customer_compensation">客户补偿</option><option value="damage">损耗</option></select></label>
                  <label>金额符号<select name="fee_sign_rule" defaultValue="absolute_outflow" required><option value="absolute_outflow">始终记为支出</option><option value="absolute_inflow">始终记为收入</option><option value="preserve">保留原始正负号</option></select></label>
                  <label>生效时间<input name="fee_effective_from" type="datetime-local" required /></label>
                  <label>失效时间（可选）<input name="fee_effective_until" type="datetime-local" /></label>
                  <label>映射依据与口径<textarea name="fee_mapping_rationale" minLength={1} required /></label>
                  <button className="finance-review-submit" disabled={feeMappingBusy || !feeCodeStatus?.codes.length}>{feeMappingBusy ? "正在留证…" : "批准版本化映射"}</button>
                </form>
              </div>
            ) : null}
            {financeReviewStatus?.status === "accepted" && financeReviewStatus.record_type === "ozon_accrual" ? (
              <div className="fee-mapping-panel">
                <div className="accrual-classification-boundary" role="note">
                  <ShieldCheck size={20} />
                  <p><strong>来源已核验，仍禁止计入利润</strong><span>应计报告同时包含销售、折扣、佣金、物流、补偿等不同性质项目。系统保留原始“应计组 + 应计类型”，等待独立、版本化的会计分类合同；不得把整份报告当作平台费用。</span></p>
                </div>
                <div className="fee-mapping-status">
                  <p><strong>{accrualClassificationStatus?.ready ? "控制分类已完整" : "控制分类仍有缺口"}</strong><span>仅控制账；不生成财务分录；不替代订单收入。</span></p>
                  <span>{accrualClassificationStatus?.pairs.filter((item) => item.ready).length ?? 0}/{accrualClassificationStatus?.pairs.length ?? 0} 组已批准</span>
                </div>
                <div className="fee-code-list" aria-label="应计组与应计类型分类状态">
                  {accrualClassificationStatus?.pairs.map((item) => (
                    <div key={`${item.accrual_group}:${item.accrual_type}`}>
                      <strong>{item.accrual_group} / {item.accrual_type}</strong>
                      <span>{item.row_count} 行 · {item.currency_totals.map((total) => `${total.total_amount} ${total.currency}`).join(" / ")} · 实际符号 {item.observed_signs.join("、")} · {item.ready ? `${item.accounting_classes.join("、")}（合同符号 ${item.expected_signs.join("、")}）` : "待分类"}</span>
                    </div>
                  ))}
                </div>
                {canReviewFinance ? (
                  <form className="finance-review-form" onSubmit={approveAccrualClassification}>
                    <strong>批准一个应计组合</strong>
                    <label>应计组 / 类型<select name="accrual_pair" defaultValue="" required><option value="">选择文件中的组合</option>{accrualClassificationStatus?.pairs.map((item) => <option value={JSON.stringify([item.accrual_group, item.accrual_type])} key={`${item.accrual_group}:${item.accrual_type}`}>{item.accrual_group} / {item.accrual_type}{item.ready ? "（已有有效分类）" : ""}</option>)}</select></label>
                    <label>会计分类<select name="accrual_accounting_class" defaultValue="platform_fee" required><option value="sales">销售</option><option value="discount">折扣</option><option value="platform_fee">平台费用</option><option value="logistics">物流</option><option value="compensation">补偿</option><option value="other_review">其他待复核</option></select></label>
                    <label>预期金额符号<select name="accrual_expected_sign" defaultValue="either" required><option value="positive">正数</option><option value="negative">负数</option><option value="either">允许正负</option></select></label>
                    <label>生效时间<input name="accrual_effective_from" type="datetime-local" required /></label>
                    <label>失效时间（可选）<input name="accrual_effective_until" type="datetime-local" /></label>
                    <label>分类依据与口径<textarea name="accrual_classification_rationale" minLength={1} required /></label>
                    <button className="finance-review-submit" disabled={accrualClassificationBusy || !accrualClassificationStatus?.pairs.length}>{accrualClassificationBusy ? "正在留证…" : "批准版本化控制分类"}</button>
                  </form>
                ) : null}
              </div>
            ) : null}
          </section>
        ) : null}

        <section className="finance-review-panel" aria-labelledby="actual-cost-review-title">
          <div className="finance-review-head">
            <div><p className="eyebrow">ACTUAL COST PROOF</p><h3 id="actual-cost-review-title">实际成本权威复核</h3></div>
            <span className={`gate ${actualCostAuthorityStatus?.status === "accepted" ? "ready" : actualCostAuthorityStatus?.status === "rejected" ? "blocked" : ""}`}>
              {actualCostAuthorityStatus?.status === "accepted" ? "实际依据已接受" : actualCostAuthorityStatus?.status === "rejected" ? "实际依据已拒绝" : "等待独立复核"}
            </span>
          </div>
          <p className="finance-review-boundary">只有非上传者核对原件、成本范围、计费主体以及金额—币种—期间后，Evidence 才能证明对应成本为实际值。复核不会自动改写利润场景、入账、采购、定价或上架。</p>
          <div className="finance-review-grid">
            <article className="finance-handoff">
              <strong>原件与规则交接</strong>
              <dl>
                <div><dt>规则版本</dt><dd><code>{costAuthorityCatalog?.schema_version ?? "读取中"}</code></dd></div>
                <div><dt>成本项</dt><dd>{costAuthorityCatalog?.items.length ?? 0}/15</dd></div>
                <div><dt>当前原件</dt><dd>{actualCostEvidenceId ? <code>{actualCostEvidenceId}</code> : "尚未选择"}</dd></div>
                <div><dt>复核记录</dt><dd>{actualCostAuthorityStatus ? `${actualCostAuthorityStatus.review_count} 条 · ${actualCostAuthorityStatus.status}` : "尚未读取"}</dd></div>
                <div><dt>已接受权威</dt><dd>{actualCostAuthorityStatus?.accepted_authorities.length ? actualCostAuthorityStatus.accepted_authorities.join("、") : "无"}</dd></div>
              </dl>
              <p>权威类型由后端统一下发，页面不能自造或修改。上传人不能复核自己的原件；任一拒绝结论优先阻断。</p>
            </article>
            <form className="finance-review-form" onSubmit={canReviewFinance ? reviewActualCostAuthority : (event) => event.preventDefault()}>
              <strong>{canReviewFinance ? "独立复核人" : "只读状态查询"}</strong>
              <label>原件 Evidence
                <select name="actual_cost_evidence_id" value={actualCostEvidenceId} onChange={(event) => { setActualCostEvidenceId(event.target.value); setActualCostAuthorityStatus(null); }} required>
                  <option value="">选择已有原件</option>
                  {reviewableCostEvidence.map((item) => <option value={item.id} key={item.id}>{item.filename} · {item.source} · 上传者 {item.created_by}</option>)}
                </select>
              </label>
              <label>精确成本项
                <select name="actual_cost_type" value={actualCostType} onChange={(event) => { setActualCostType(event.target.value); setActualCostAuthorityStatus(null); }} required>
                  {costAuthorityCatalog?.items.map((item) => <option value={item.cost_type} key={item.cost_type}>{item.label}</option>)}
                </select>
              </label>
              <label>允许的实际权威类型
                <select name="actual_cost_authority_id" key={`${actualCostType}:${actualCostAuthorityItem?.authorities[0]?.id ?? "loading"}`} defaultValue={actualCostAuthorityItem?.authorities[0]?.id ?? ""} required>
                  {actualCostAuthorityItem?.authorities.map((item) => <option value={item.id} key={item.id}>{item.label}</option>)}
                </select>
              </label>
              <button type="button" className="finance-review-submit" disabled={actualCostReviewBusy || !actualCostEvidenceId} onClick={() => loadActualCostAuthorityStatus()}>{actualCostReviewBusy ? "读取中…" : "读取当前状态"}</button>
              {canReviewFinance ? <>
                <fieldset>
                  <legend>逐项核对实际原件</legend>
                  <label><input name="actual_cost_authentic_original" type="checkbox" />原件真实、完整且哈希有效</label>
                  <label><input name="actual_cost_scope_matches" type="checkbox" />原件范围与该成本项精确对应</label>
                  <label><input name="actual_cost_charging_party_matches" type="checkbox" />计费方与实际责任主体一致</label>
                  <label><input name="actual_cost_amount_currency_period_matches" type="checkbox" />金额、币种和归属期间一致</label>
                </fieldset>
                <label>复核结论<select name="actual_cost_decision" defaultValue="accepted"><option value="accepted">接受为实际成本依据</option><option value="rejected">拒绝并保持阻断</option></select></label>
                <label>依据与异常说明<textarea name="actual_cost_rationale" minLength={1} required /></label>
                <button className="finance-review-submit" disabled={actualCostReviewBusy || !actualCostEvidenceId || !actualCostAuthorityItem}>{actualCostReviewBusy ? "正在保存…" : "保存不可变实际成本复核"}</button>
              </> : <div className="finance-review-locked"><ShieldCheck size={23} /><strong>当前身份不能提交结论</strong><p>Operator 可以查询状态；请由另一位 Reviewer、Compliance 或 Admin 核对并留证。</p></div>}
            </form>
          </div>
        </section>

        <section className="startup-path" aria-labelledby="startup-path-title">
          <div className="startup-path-head">
            <div><p className="eyebrow">START HERE</p><h3 id="startup-path-title">真实业务启动路径</h3></div>
            <div className={nextStartupStep ? "startup-next" : "startup-next ready"}>
              <span>{nextStartupStep ? "当前下一步" : "资料条件已齐"}</span>
              <strong>{nextStartupStep?.title ?? "等待阶段门人工复核"}</strong>
            </div>
          </div>
          <p className="startup-explainer">按顺序准备真实资料。模板只帮助收集，不会代替原始凭证、独立审批或平台权限验证。</p>
          <div className="startup-boundary" role="note" aria-label="本地资料预检与系统证据状态边界">
            <strong>两层状态不要混淆</strong>
            <p>本地资料包只检查必填项是否齐全；下方卡片只认系统 Evidence、Passport、事实账与人工审批。两者都不会自动上架。</p>
            <code>uv run python scripts/validate_startup_package.py .runtime/startup-intake --require-review-ready</code>
          </div>
          <div className="startup-step-grid">
            {startupSteps.map((step, index) => {
              const state = requirement(step.id);
              return <article className={state?.ready ? "startup-step ready" : "startup-step"} key={step.id}>
                <div><span>{index + 1}</span><b>{step.id} · 系统证据</b><em>{state?.ready ? "已满足" : `${state?.current ?? 0}/${state?.target ?? "-"}`}</em></div>
                <strong>{step.title}</strong>
                <p>{state?.ready ? "证据条件已满足，等待人工阶段门复核。" : state?.next_action ?? "正在读取真实准入状态…"}</p>
                <footer>
                  {step.template ? <a href={step.template} download><Download size={13} />{step.templateLabel}</a> : null}
                  {step.secondaryTemplate ? <a href={step.secondaryTemplate} download><Download size={13} />{step.secondaryTemplateLabel}</a> : null}
                  <a className="primary" href={step.href} target={step.href.startsWith("https://") ? "_blank" : undefined} rel={step.href.startsWith("https://") ? "noreferrer" : undefined}>{step.actionLabel}<ChevronRight size={13} /></a>
                </footer>
              </article>;
            })}
          </div>
        </section>

        <section className="decision-workbench">
          <div className="panel-title"><div><p className="eyebrow">OPERATIONS CONTROL</p><h3>今日异常中心与 Ozon 只读试点</h3></div><button type="button" disabled={lifecycleBusy === "operations-scan"} onClick={scanOperationsQueue}>扫描逾期升级</button></div>
          <p className="section-copy">Gate 阻断来自服务端 readiness，不伪造 SLA；事故、命令和观察合同继续按真实截止时间升级。这里只解释和导航，不会自动补证、关事故或写平台。</p>
          <div className="lifecycle-summary"><article><span>经营阻断</span><b>{gateReadiness?.exception_workspace.blocked_count ?? 0}</b><small>按 Gate、来源对象和责任角色展示</small></article><article><span>运行待处理</span><b>{operationsQueue.length}</b><small>事故、命令和观察合同按 SLA 排序</small></article><article><span>已逾期</span><b>{operationsQueue.filter((item) => item.overdue).length}</b><small>只升级提醒，不自动执行经营动作</small></article><article><span>未关闭事故</span><b>{operationalIncidents.filter((item) => item.status !== "closed").length}</b><small>严重事故阻断试点准入</small></article></div>
          <div className="decision-layout">
            <div className="decision-register"><div className="decision-register-head"><strong>经营阻断与运行异常</strong><span>{(gateReadiness?.exception_workspace.blocked_count ?? 0) + operationsQueue.length} 项</span></div>{gateReadiness?.exception_workspace.items.map((item) => <article key={item.queue_key}><div><span>{item.gate} · {item.attention === "current_gate" ? "当前门" : "后续门"}</span><b>{item.current}/{item.target}</b></div><strong>{item.source_id} · {item.title}</strong><small>责任角色：{item.owner_role} · 来源：{item.source_type}</small><p>{item.next_action}</p></article>)}{operationsQueue.slice(0, Math.max(0, 8 - (gateReadiness?.exception_workspace.blocked_count ?? 0))).map((item) => <article key={item.queue_key}><div><span>{item.priority} · L{item.escalation_level}</span><b>{item.overdue ? `逾期 ${item.overdue_minutes} 分钟` : item.status}</b></div><strong>{item.title}</strong><small>截止 {new Date(item.due_at).toLocaleString("zh-CN")} · {item.owner_id ?? "待领取"}</small><p>{item.next_action}</p></article>)}{!(gateReadiness?.exception_workspace.blocked_count || operationsQueue.length) && <div className="empty"><ShieldCheck size={25} /><strong>当前没有待处理异常</strong><p>Gate 阻断由 readiness 计算；运行队列只展示事故、执行命令和观察窗口。</p></div>}</div>
            <form className="decision-form" onSubmit={createReadOnlyPilot}><div className="decision-form-head"><div><strong>建立 Ozon 只读试点</strong><small>不保存凭证，不允许商品、价格、广告或库存写入</small></div><ShieldCheck size={19} /></div><div className="decision-fields"><label>账户别名<input name="pilot_account_alias" placeholder="例如 ozon-ru-main（不得填写密钥）" required /></label><label>每日请求上限<input name="pilot_daily_limit" type="number" min="1" max="10000" defaultValue="100" required /></label><label>最大目标数<input name="pilot_target_limit" type="number" min="1" max="1000" defaultValue="10" required /></label><label>准入证据<select name="pilot_evidence" defaultValue="" required><option value="">选择账户范围或运行手册证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select></label><label>开始时间<input name="pilot_starts_at" type="datetime-local" required /></label><label>结束时间<input name="pilot_ends_at" type="datetime-local" required /></label><label className="wide">允许的只读能力<span><input name="pilot_operations" type="checkbox" value="ozon.product.read" />商品读取　<input name="pilot_operations" type="checkbox" value="ozon.inventory.read" />库存读取　<input name="pilot_operations" type="checkbox" value="ozon.orders.read" />订单读取　<input name="pilot_operations" type="checkbox" value="ozon.analytics.read" />分析读取　<input name="pilot_operations" type="checkbox" value="ozon.finance.read" />财务读取</span></label></div><div className="decision-submit"><p>最长 14 天；即使批准并激活，仍固定 execution_eligible=false。</p><button disabled={lifecycleBusy === "pilot-create"}>固化只读试点边界</button></div></form>
          </div>
          {readOnlyPilots.map((pilot) => { const evaluation = pilotEvaluations[pilot.id]; return <article className="policy-card" key={pilot.id}><div className="policy-card-head"><div><strong>{pilot.account_alias} · {pilot.status}</strong><small>{pilot.allowed_operations.join("、")} · 日限额 {pilot.max_daily_requests}</small></div><span className={evaluation?.ready_for_review ? "gate ready" : "gate blocked"}>{evaluation?.ready_for_review ? "准入条件齐备" : "仍有阻断项"}</span></div><div className="knowledge-status invalid"><strong>平台写入：永久禁止</strong><span>不保存凭证材料 · 不授予执行资格</span><b>自动激活：禁止</b></div>{["draft", "changes_requested"].includes(pilot.status) && <form className="policy-outcome-form" onSubmit={(event) => attestPilotControl(event, pilot)}><strong>逐项提交准入控制</strong><select name="pilot_control" defaultValue="" required><option value="">选择未完成控制项</option>{pilot.required_controls.filter((control) => !pilot.controls[control]?.passed).map((control) => <option value={control} key={control}>{control}</option>)}</select><input name="pilot_control_notes" placeholder="验证方法和结果" required /><select name="pilot_control_evidence" defaultValue="" required><option value="">选择控制证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `pilot-attest:${pilot.id}`}>记录控制项</button>{evaluation?.ready_for_review && <button type="button" disabled={lifecycleBusy === `pilot-submit:${pilot.id}`} onClick={() => submitPilotReview(pilot)}>提交独立复核</button>}</form>}{pilot.status === "pending_review" && <form className="policy-outcome-form" onSubmit={(event) => reviewPilot(event, pilot)}><strong>独立准入复核</strong><select name="pilot_review_verdict" defaultValue="" required><option value="">选择结论</option><option value="accepted">批准只读试点</option><option value="rejected">要求补充控制</option></select><input name="pilot_review_rationale" placeholder="独立复核理由" required /><button disabled={lifecycleBusy === `pilot-review:${pilot.id}`}>提交复核</button></form>}{pilot.status === "approved" && <button type="button" disabled={lifecycleBusy === `pilot-activate:${pilot.id}`} onClick={() => activatePilot(pilot)}>管理员重新核验并激活只读试点</button>}{evaluation?.blockers.length ? <footer><span>阻断：{evaluation.blockers.join("、")}</span><b>不得激活</b></footer> : <footer><span>近期演练 {evaluation?.recent_drill_ids.length ?? 0} 次</span><b>仍无写权限</b></footer>}</article>; })}
        </section>

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
                {selectedProfile?.id === "best_solution" && <><label className="wide">不可突破的硬约束（每行一个）<textarea name="decision_hard_constraints" placeholder={"必须有一手证据\n不得越权或自动执行\n最坏损失不得超过预算"} /></label><label className="wide">比较维度（每行一个）<textarea name="decision_criteria" defaultValue={"长期风险调整价值\n证据质量\n总拥有成本\n可逆性与回滚\n落地时间\n运维适配"} /></label></>}
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
              <div className="lifecycle-form-title"><span>1</span><div><strong>提交证据化分析</strong><small>{isBestSolutionAnalysis ? "先过硬约束，再比较长期价值与总成本" : "必须先给出预测值、区间和回填日期"}</small></div></div>
              <label>可分析合同<select name="analysis_contract_id" value={selectedAnalysisContractId} onChange={(event) => { setSelectedAnalysisContractId(event.target.value); setSelectedAnalysisOptionId(""); }} required><option value="">选择一份已就绪合同</option>{decisionContracts.filter((item) => item.status === "ready_for_analysis" && ["decision_review", "best_solution", "probabilistic_forecast"].includes(item.profile_id)).map((item) => <option value={item.id} key={item.id}>{item.objective}</option>)}</select></label>
              {selectedAnalysisContract && ["decision_review", "best_solution"].includes(selectedAnalysisContract.profile_id) && <label>推荐方案<select name="analysis_option_id" value={selectedAnalysisOptionId} onChange={(event) => setSelectedAnalysisOptionId(event.target.value)} required><option value="">选择合同中的方案</option>{analysisOptions.map((item) => <option value={item.id} key={item.id}>{item.id} · {item.label}</option>)}</select></label>}
              <label>分析结论<textarea name="analysis_conclusion" placeholder="结论必须说明为什么，并保留未知项" required /></label>
              <label>置信度<input name="analysis_confidence" type="number" min="0" max="1" step="0.01" defaultValue="0.6" required /></label>
              {analysisNeedsForecast && <><div className="lifecycle-pair"><label>预测指标<input name="analysis_metric" placeholder="例如 30天 CM3" required /></label><label>单位<input name="analysis_unit" defaultValue="CNY" required /></label></div><div className="lifecycle-triple"><label>预测值<input name="analysis_value" type="number" step="0.01" required /></label><label>下界<input name="analysis_low" type="number" step="0.01" required /></label><label>上界<input name="analysis_high" type="number" step="0.01" required /></label></div><label>结果回填时间<input name="analysis_due_at" type="datetime-local" required /></label></>}
              {isBestSolutionAnalysis && <div className="best-solution-assessment">
                <strong>逐项方案比较</strong>
                <p>每个方案都必须覆盖全部硬约束与六项经营判断；系统不会把“最新”或“最复杂”自动当成最好。</p>
                {analysisOptions.map((option, optionIndex) => <fieldset key={String(option.id)}>
                  <legend>{option.id} · {option.label}</legend>
                  {analysisHardConstraints.map((constraint, constraintIndex) => <div className="lifecycle-pair" key={`${option.id}-${constraint}`}><label>{constraint}<select name={`best_constraint_${optionIndex}_${constraintIndex}_passed`} defaultValue="false" required><option value="false">不满足</option><option value="true">满足</option></select></label><label>判断依据<input name={`best_constraint_${optionIndex}_${constraintIndex}_rationale`} placeholder="引用证据或说明缺口" required /></label></div>)}
                  <label>证据质量<select name={`best_evidence_quality_${optionIndex}`} defaultValue="UNKNOWN" required><option value="A">A · 官方原件/直接事实</option><option value="B">B · 可靠二手/独立复核</option><option value="C">C · 第三方参考</option><option value="D">D · 弱信号</option><option value="UNKNOWN">未知</option></select></label>
                  <label>长期风险调整价值<textarea name={`best_long_term_value_${optionIndex}`} required /></label>
                  <label>总拥有成本<textarea name={`best_tco_${optionIndex}`} placeholder="建设、采购、运维、迁移、失败和人工成本" required /></label>
                  <label>最大损失<textarea name={`best_maximum_loss_${optionIndex}`} required /></label>
                  <label>可逆性与回滚<textarea name={`best_rollback_${optionIndex}`} required /></label>
                  <label>见效时间<textarea name={`best_time_to_value_${optionIndex}`} required /></label>
                  <label>现有团队与系统适配<textarea name={`best_operational_fit_${optionIndex}`} required /></label>
                  {selectedAnalysisOptionId && selectedAnalysisOptionId !== String(option.id) && <label>淘汰该方案的原因<textarea name={`best_rejection_reason_${optionIndex}`} required /></label>}
                </fieldset>)}
                <label>不行动方案<select name="best_no_action_option_id" defaultValue=""><option value="">合同中没有明确的不行动方案</option>{analysisOptions.map((item) => <option value={item.id} key={item.id}>{item.id} · {item.label}</option>)}</select></label>
                <label>若没有不行动方案，说明原因<textarea name="best_no_action_omission_reason" /></label>
                <label>敏感性驱动因素（每行一个）<textarea name="best_sensitivity_drivers" required /></label>
                <label>结论失效条件（每行一个）<textarea name="best_invalidation_conditions" required /></label>
                <label>重新审查时间<input name="best_review_at" type="datetime-local" required /></label>
                <label>审批要求<textarea name="best_approval_requirement" placeholder="谁复核、谁批准、什么条件下才能进入执行" required /></label>
              </div>}
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
                  {contract?.profile_id === "best_solution" && <p>推荐 {item.recommended_option_id} · 已记录 {Array.isArray(item.selection_assessment.rejected_options) ? item.selection_assessment.rejected_options.length : 0} 个淘汰理由 · 仍需反方审查</p>}
                  {reviews.map((review) => <div className={`review-result ${review.verdict}`} key={review.id}><b>{review.verdict}</b><span>{review.rationale}</span><small>{review.reviewed_by}</small></div>)}
                  {!blocking && !resolution && acceptedCount < requiredReviews && <form className="mini-lifecycle-form" onSubmit={(event) => reviewDecisionAnalysis(event, item.id)}>
                    <select name="review_verdict" defaultValue="accepted"><option value="accepted">证据支持</option><option value="needs_revision">需要修订</option><option value="rejected">拒绝结论</option></select>
                    <textarea name="review_rationale" placeholder="独立复核理由" required />
                    <textarea name="review_counterarguments" placeholder="反方解释（每行一个）" required={contract?.profile_id === "best_solution"} />
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
              const operationalIncident = operationalIncidents.find((item) => item.impact.includes(`observation_window:${observationWindow?.id}`));
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
                {operationalIncident && <div className={operationalIncident.status === "closed" ? "knowledge-status usable" : "knowledge-status invalid"}><strong>{operationalIncident.mode === "drill" ? "恢复演练" : "生产事故"}：{operationalIncident.status}</strong><span>{operationalIncident.summary} · {Object.keys(operationalIncident.checks).length}/{operationalIncident.required_checks.length} 项恢复检查</span><b>熔断：{operationalIncident.kill_switch_engaged ? "保持" : "已解除"} · 自动解除：禁止</b></div>}
                {operationalIncident && !operationalIncident.owner_id && <button type="button" disabled={lifecycleBusy === `incident-claim:${operationalIncident.id}`} onClick={() => claimIncident(operationalIncident)}>领取事故恢复责任</button>}
                {operationalIncident?.status === "recovering" && <form className="policy-outcome-form" onSubmit={(event) => recordIncidentCheck(event, operationalIncident)}><strong>恢复检查表</strong><p>远端状态、回滚、数据、凭证和监控必须逐项提供证据，不能一键全部通过。</p><select name="incident_check" defaultValue="" required><option value="">选择待确认项目</option>{operationalIncident.required_checks.filter((check) => !operationalIncident.checks[check]?.passed).map((check) => <option value={check} key={check}>{check}</option>)}</select><input name="incident_check_notes" placeholder="核对方法与结果" required /><select name="incident_check_evidence" defaultValue="" required><option value="">选择恢复证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `incident-check:${operationalIncident.id}`}>记录本项检查</button>{operationalIncident.required_checks.every((check) => operationalIncident.checks[check]?.passed) && <button type="button" disabled={lifecycleBusy === `incident-submit:${operationalIncident.id}`} onClick={() => submitIncidentReview(operationalIncident)}>提交独立复核</button>}</form>}
                {operationalIncident?.status === "pending_review" && <form className="policy-outcome-form" onSubmit={(event) => reviewIncident(event, operationalIncident)}><strong>独立恢复复核</strong><p>复核者不能是事故发起人或恢复负责人；通过也不会自动解除熔断。</p><select name="incident_review_verdict" defaultValue="" required><option value="">选择复核结论</option><option value="accepted">接受恢复</option><option value="rejected">退回继续处理</option></select><input name="incident_review_rationale" placeholder="独立复核理由" required /><select name="incident_review_evidence" defaultValue="" required><option value="">选择复核证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `incident-review:${operationalIncident.id}`}>提交独立复核</button></form>}
                {operationalIncident?.status === "ready_for_release" && operationalIncident.kill_switch_engaged && <div className="policy-release-form"><strong>管理员解除熔断</strong><p>只有独立复核通过后才显示；解除熔断与关闭事故是两个独立动作。</p><button type="button" disabled={lifecycleBusy === `incident-release:${operationalIncident.id}`} onClick={() => releaseIncidentFreeze(operationalIncident)}>明确解除熔断</button></div>}
                {operationalIncident?.status === "ready_for_release" && !operationalIncident.kill_switch_engaged && <form className="policy-outcome-form" onSubmit={(event) => closeIncident(event, operationalIncident)}><strong>关闭事故</strong><input name="incident_close_notes" placeholder="关闭结论与后续行动" required /><select name="incident_close_evidence" defaultValue="" required><option value="">选择关闭证据</option>{evidenceRecords.map((item) => <option value={item.id} key={item.id}>{item.grade} · {item.filename}</option>)}</select><button disabled={lifecycleBusy === `incident-close:${operationalIncident.id}`}>固化并关闭事故</button></form>}
                <div className="policy-stages">{policy.rollout_stages.map((stage, index) => { const release = policy.releases.find((item) => item.stage_index === index); return <span className={release?.outcome?.verdict === "passed" ? "passed" : release ? "released" : ""} key={stage.name}>{stage.name}<b>{(Number(stage.max_exposure_fraction) * 100).toFixed(0)}%</b></span>; })}</div>
                <footer><span>条件不满足：{policy.fallback_action.type}</span><b>自动执行：禁止</b></footer>
              </article>;
            })}</div> : <div className="empty"><Waypoints size={24} /><strong>还没有条件策略</strong><p>先从仍有效的因果知识编译，不能从聊天建议直接生成经营动作。</p></div>}
          </div>
        </section>

        <section className="gate-overview" id="reality-gate">
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
          {gateReadiness && <div className="requirement-grid">
            <article className={researchReadiness?.ready ? "requirement ready" : "requirement"}>
              <div><span>研究闭环</span><b>{researchReadiness?.ready ? "READY" : "BLOCKED"}</b></div>
              <strong>分析、模拟、生图/视频与 Listing 草稿</strong>
              <small>{researchReadiness?.ready ? "只允许 research_signal / estimate / simulation / draft，不允许外部副作用" : researchReadiness?.blocking_reasons.join("；") || "等待合格研究原件及独立复核"}</small>
            </article>
            <article className={realExecutionReadiness?.ready ? "requirement ready" : "requirement"}>
              <div><span>真实经营</span><b>{realExecutionReadiness?.ready ? "READY" : "BLOCKED"}</b></div>
              <strong>付款、采购、发布、广告、补货与 actual 晋升</strong>
              <small>{realExecutionReadiness?.ready ? "动作仍需按风险等级、审批、额度和执行时复验" : realExecutionReadiness?.blocking_reasons.join("；") || "等待 Ozon Data 或两项独立官方分析证据"}</small>
            </article>
          </div>}
          <form className="gate-evidence-upload" onSubmit={uploadDemandReport}>
            <div><strong>1. 上传需求研究原件</strong><small>上传后只进入待复核。测试数据最多放行研究闭环；真实经营要求 Ozon Data，或至少两个独立 Ozon 官方分析入口。</small></div>
            <select name="demand_report_source_system" aria-label="需求研究来源" defaultValue="ozon_category_analytics" required>
              <option value="ozon_data">Ozon Data 正式报告</option>
              <option value="ozon_category_analytics">Ozon 类目分析</option>
              <option value="ozon_trends">Ozon 趋势数据</option>
              <option value="ozon_what_to_sell">Ozon 卖什么</option>
              <option value="ozon_search_terms">Ozon 搜索词</option>
              <option value="ozon_competitor_compare">Ozon 竞品/类目比较</option>
              <option value="sanitized_history">脱敏历史样本</option>
              <option value="fixed_test_data">固定工程测试数据</option>
            </select>
            <input name="demand_report_source_locator" aria-label="需求研究来源定位" placeholder="原始页面 URL、导出编号或 fixture:// 路径" required />
            <input name="demand_report_window_days" aria-label="需求报告窗口天数" type="number" min="28" max="365" defaultValue="28" required />
            <input name="demand_report_file" aria-label="需求研究原件文件" type="file" accept=".json,.csv,.xlsx,.xls,.pdf" required />
            <button disabled={gateUploading}>{gateUploading ? "正在固化…" : "固化研究原件"}</button>
          </form>
          <form className="gate-evidence-upload" onSubmit={reviewDemandReport}>
            <div><strong>2. 独立复核需求报告</strong><small>复核身份必须与上传者不同；接受或拒绝都会形成不可覆盖的证据。</small></div>
            <select name="demand_report_evidence_id" aria-label="待复核需求报告" defaultValue="" required>
              <option value="" disabled>{demandSourceReports.length ? "选择报告" : "暂无待复核报告"}</option>
              {demandSourceReports.map((item) => <option value={item.id} key={item.id}>{item.filename} · {String(item.metadata.source_system ?? "unknown")} · 上传者 {item.created_by}</option>)}
            </select>
            <select name="demand_report_decision" aria-label="需求报告复核结论" defaultValue="accepted" required>
              <option value="accepted">接受：已核对后台来源、窗口与字段</option>
              <option value="rejected">拒绝：来源或范围不可复验</option>
            </select>
            <input name="demand_report_rationale" aria-label="需求报告复核理由" placeholder="写明核对位置、日期范围和异常" required />
            <button disabled={lifecycleBusy === "demand-report-review" || demandSourceReports.length === 0}>{lifecycleBusy === "demand-report-review" ? "正在复核…" : "固化独立复核"}</button>
          </form>
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

        <section className="sku-intake-panel" id="candidate-research">
          <div className="panel-title">
            <div><p className="eyebrow">CANDIDATE RESEARCH</p><h3>新上新候选预检</h3></div>
            <span className="badge">先证据 · 后报价</span>
          </div>
          <div className="procurement-guardrail">
            <ShieldCheck size={18} />
            <p><strong>系统不会替你编造来源</strong><span>先固化原文件，再让每个指标绑定一份可复验原件。预检通过也只进入三家真实报价。</span></p>
          </div>
          <form className="candidate-evidence-form" onSubmit={uploadCandidateEvidence}>
            <div><strong>1. 研究收集箱：固化信号与原件</strong><small>保存原文件、来源时间、原始字段和候选关联；不自动生成商品或上架</small></div>
            <input name="candidate_evidence_source" placeholder="来源机构，例如 Seerfar、萌啦或 Ozon Analytics" required />
            <input name="candidate_evidence_source_ref" placeholder="提供方稳定记录编号，例如 export://2026-07/row-18" required />
            <input name="candidate_evidence_source_url" type="url" placeholder="原始页面 URL（不得包含账号、Token 或密钥）" required />
            <input name="candidate_evidence_candidate_refs" placeholder="关联候选编号，可用逗号分隔；允许一条信号关联多个候选" />
            <textarea name="candidate_evidence_raw_fields" aria-label="提供方原始字段" defaultValue="{}" placeholder='原始字段 JSON，例如 {"keyword":"storage box","search_index":81.5}' required />
            <select name="candidate_evidence_license_status" defaultValue="requires_review" aria-label="来源使用状态"><option value="requires_review">使用条款待核对</option><option value="verified">已核对允许保存/使用</option><option value="restricted">受限，仅留档不得复用</option></select>
            <select name="candidate_evidence_grade" defaultValue="C" aria-label="证据等级"><option value="A">A · 官方原件</option><option value="B">B · 一手业务数据</option><option value="C">C · 可追溯二手资料</option><option value="D">D · 探索线索</option></select>
            <small>第三方选品、ERP 和利润计算器默认是 C 级辅助资料；A/B 只能按原始账户、供应商或官方规则依据声明，后续仍需独立复核。</small>
            <input name="candidate_evidence_file" type="file" required />
            <button disabled={candidateEvidenceUploading}>{candidateEvidenceUploading ? "正在固化…" : "固化原件"}</button>
          </form>
          {researchSignals.length > 0 && <div className="candidate-inbox-list">
            <strong>最近研究信号</strong>
            {researchSignals.slice(0, 5).map((record) => <p key={`signal-${record.id}`}><code>{record.id}</code><span>{record.source} · {String(record.metadata.license_status ?? "requires_review")} · 辅助资料</span></p>)}
          </div>}
          <div className="finance-review-grid">
            <article className="finance-handoff">
              <strong>2. 上传人交接复核</strong>
              <p>把 Evidence 编号、对应指标和原始依据交给另一位 Reviewer/Compliance 用户。上传时选择的 A/B/C/D 只是声明，不会直接推动候选进入三报价。</p>
              {candidateAuthorityStatus && <dl>
                <div><dt>Evidence</dt><dd><code>{candidateAuthorityStatus.evidence_id}</code></dd></div>
                <div><dt>指标</dt><dd>{candidateMetricLabels[candidateAuthorityStatus.metric] ?? candidateAuthorityStatus.metric}</dd></div>
                <div><dt>状态</dt><dd>{candidateAuthorityStatus.status}</dd></div>
                <div><dt>有效等级</dt><dd>{candidateAuthorityStatus.accepted_grades.join("/") || "无"}</dd></div>
              </dl>}
            </article>
            {canReviewFinance ? <form className="finance-review-form" onSubmit={reviewCandidateEvidenceAuthority}>
              <strong>独立权威复核人</strong>
              <label>候选 Evidence<select name="candidate_authority_evidence_id" defaultValue="" required><option value="">选择原件</option>{evidenceRecords.filter((record) => record.source !== "candidate_evidence_authority_review").map((record) => <option value={record.id} key={`authority-${record.id}`}>{record.source} · {record.filename}</option>)}</select></label>
              <label>适用指标<select name="candidate_authority_metric" defaultValue="" required><option value="">选择指标</option>{candidateMetricDefinitions.map(([metric, label]) => <option value={metric} key={`authority-metric-${metric}`}>{label}</option>)}</select></label>
              <label>批准等级<select name="candidate_authority_grade" defaultValue="B"><option value="A">A · 官方原件</option><option value="B">B · 一手业务数据</option></select></label>
              <fieldset>
                <legend>逐项核对原件</legend>
                <label><input name="candidate_authority_authentic" type="checkbox" />原件真实、完整且哈希可复验</label>
                <label><input name="candidate_authority_scope" type="checkbox" />来源范围与本指标、市场和时间窗口一致</label>
                <label><input name="candidate_authority_basis" type="checkbox" />A/B 权威依据已核对，不依赖二手计算器声明</label>
              </fieldset>
              <label>复核结论<select name="candidate_authority_decision" defaultValue="accepted"><option value="accepted">接受该指标的 A/B 等级</option><option value="rejected">拒绝并保持阻塞</option></select></label>
              <label>依据与异常说明<textarea name="candidate_authority_rationale" minLength={1} required /></label>
              <span className="finance-review-id-row">
                <button type="button" disabled={candidateAuthorityBusy} onClick={(event) => { const form = event.currentTarget.form; if (form) loadCandidateAuthorityStatus((form.elements.namedItem("candidate_authority_evidence_id") as HTMLSelectElement).value, (form.elements.namedItem("candidate_authority_metric") as HTMLSelectElement).value); }}>读取状态</button>
                <button className="finance-review-submit" disabled={candidateAuthorityBusy}>{candidateAuthorityBusy ? "处理中…" : "保存不可变复核记录"}</button>
              </span>
            </form> : <article className="finance-review-locked"><ShieldCheck size={23} /><strong>当前身份只能上传</strong><p>请让另一位 Reviewer 或 Compliance 用户核对原件；上传人不能复核自己的证据。</p></article>}
          </div>
          <form className="sku-intake candidate-research-form" onSubmit={submitCandidateResearch}>
            <div className="candidate-heading"><strong>3. 绑定五类证据并预检</strong><small>每份原件还必须有该指标的独立 A/B 复核；五项全部验真后才会一起落账。</small></div>
            <div className="candidate-basics">
              <label>已接受需求报告<select name="candidate_demand_report_evidence_id" defaultValue="" required><option value="" disabled>{acceptedDemandReports.length ? "选择本次研究依据" : "请先完成需求报告独立复核"}</option>{acceptedDemandReports.map((report) => <option value={report.id} key={`candidate-report-${report.id}`}>{report.filename} · {report.effective_at.slice(0, 10)}</option>)}</select></label>
              <label>候选编号<input name="candidate_ref" placeholder="candidate://stable-name-v1" required /></label>
              <label>候选名称<input name="candidate_name" placeholder="便于经营人员识别的名称" required /></label>
              <label>市场<input name="candidate_market" defaultValue="RU" required /></label>
              <label>类目<input name="candidate_category" placeholder="例如 kitchen_storage" required /></label>
            </div>
            <div className="candidate-metric-list">
              {candidateMetricDefinitions.map(([metric, label, help, defaultWindow, defaultSample]) => <div className="candidate-metric" key={metric}>
                <div><strong>{label}</strong><small>{help}</small></div>
                {metric === "supplier_available" || metric === "compliance_redline"
                  ? <select name={`candidate_${metric}_value`} aria-label={`${label}数值`} defaultValue="" required><option value="" disabled>请选择</option><option value="1">是</option><option value="0">否</option></select>
                  : <input name={`candidate_${metric}_value`} aria-label={`${label}数值`} type="number" min="0" max="100" step="0.1" placeholder="0–100" required />}
                <select name={`candidate_${metric}_evidence`} aria-label={`${label}原件`} defaultValue="" required>
                  <option value="" disabled>{evidenceRecords.length ? "选择 Evidence 原件" : "请先固化原件"}</option>
                  {evidenceRecords.map((record) => <option value={record.id} key={`${metric}-${record.id}`}>{record.grade}级 · {record.source} · {record.filename} · {record.effective_at.slice(0, 10)}</option>)}
                </select>
                <label>可信度<input name={`candidate_${metric}_confidence`} aria-label={`${label}可信度`} type="number" min="0.01" max="1" step="0.01" defaultValue="0.8" required /></label>
                <label>观察窗口（天）<input name={`candidate_${metric}_window_days`} aria-label={`${label}观察窗口`} type="number" min={metric === "supplier_available" || metric === "compliance_redline" ? 1 : 28} max="90" step="1" defaultValue={defaultWindow} required /></label>
                <label>样本量<input name={`candidate_${metric}_sample_size`} aria-label={`${label}样本量`} type="number" min={defaultSample} step="1" defaultValue={defaultSample} required /></label>
              </div>)}
            </div>
            <div className="intake-submit"><p>同一候选包重复提交不会重复建账；需求报告未接受、坏原件或缺任一指标时，五条观测全部不写入。</p><button disabled={candidateResearchBusy || evidenceRecords.length === 0 || acceptedDemandReports.length === 0}>{candidateResearchBusy ? "正在预检…" : "执行候选预检"}</button></div>
          </form>
          {candidateAssessment && <article className={`candidate-result ${candidateAssessment.decision}`}>
            <div><strong>{candidateAssessment.candidate_name}</strong><span>{candidateAssessment.decision === "request_three_quotes" ? "进入三报价" : candidateAssessment.decision === "reject" ? "淘汰" : "需要补证"}</span></div>
            <p>测量合同：{candidateAssessment.measurement_policy_id}；筛选策略：{candidateAssessment.quote_policy_id}（工程默认值，G0 前需经营负责人复核）</p>
            <p>需求报告：{candidateAssessment.demand_report_evidence_id}</p>
            <p>聚合值：需求 {candidateAssessment.metric_values.demand_signal ?? "—"} · 缺口 {candidateAssessment.metric_values.competition_gap ?? "—"} · 退货风险 {candidateAssessment.metric_values.return_risk ?? "—"}%</p>
            {candidateAssessment.threshold_failures.length > 0 && <ul>{candidateAssessment.threshold_failures.map((item) => <li key={item.metric}>{candidateMetricLabels[item.metric] ?? item.metric}：实际 {item.actual}，要求 {item.operator === "gte" ? "≥" : "≤"} {item.threshold}</li>)}</ul>}
            <p>{candidateAssessment.decision === "request_three_quotes"
              ? `已核验 ${candidateAssessment.evidence_ids.length} 份原件、${candidateAssessment.source_family_count} 个独立来源族；下一步必须收集 ${candidateAssessment.required_supplier_quotes} 家真实报价并计算风险调整后 CM3。`
              : candidateAssessment.reasons.join("；")}</p>
            {candidateAssessment.missing_metrics.length > 0 && <small>缺失或无效：{candidateAssessment.missing_metrics.map((metric) => candidateMetricLabels[metric] ?? metric).join("、")}</small>}
            {candidateAssessment.low_authority_evidence_ids.length > 0 && <small>有 {candidateAssessment.low_authority_evidence_ids.length} 条辅助资料已保留，但权威等级不足，不能推动三报价。</small>}
            <small>不会自动创建商品、采购或 Listing。</small>
            {candidateAssessment.decision === "request_three_quotes" && !candidateHandoff && <form className="candidate-handoff" onSubmit={createCandidateSourcingWorkspace}>
              <label>内部 SKU<input name="candidate_handoff_sku" placeholder="例如 RU-CAND-001" required /></label>
              <label className="candidate-confirm"><input name="candidate_handoff_confirmed" type="checkbox" required />我确认建立报价工作区；这不代表采购或上架批准</label>
              <button disabled={candidateHandoffBusy}>{candidateHandoffBusy ? "正在建立…" : "建立报价工作区"}</button>
            </form>}
            {candidateHandoff && <div className="candidate-next-step"><strong>{candidateHandoff.product.sku} 已就绪</strong><a href="#sourcing-intake">前往录入三家报价</a></div>}
          </article>}
        </section>

        <section className="sku-intake-panel" id="sku-intake">
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

        <section className="sku-intake-panel" id="product-media-intake">
          <div className="panel-title">
            <div><p className="eyebrow">PRODUCT MEDIA EVIDENCE</p><h3>真实原图与权利证据</h3></div>
            <span className="badge">上传不触发生成</span>
          </div>
          <form className="sku-intake" onSubmit={uploadProductMedia}>
            <div className="intake-basic">
              <label>候选 SKU<select name="product_media_product_id" required><option value="">选择 SKU</option>{products.map((item) => <option value={item.id} key={item.id}>{item.sku} · {item.name}</option>)}</select></label>
              <label>变体标识<input name="product_media_variant_id" defaultValue="base" required /></label>
              <label>图片角色<select name="product_media_role" defaultValue="front_main">{Object.entries(productMediaRoleLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <label>来源类型<select name="product_media_source_kind" defaultValue="sample_photo"><option value="sample_photo">真实样品拍摄</option><option value="supplier_authorized">供应商授权原图</option></select></label>
              <label>来源编号 / 链接<input name="product_media_source_ref" placeholder="样品编号、供应商报价编号或原始链接" required /></label>
              <label>真实原图<input name="product_media_image" type="file" accept="image/jpeg,image/png,image/webp" required /></label>
              <label>权利 / 授权文件<input name="product_media_rights" type="file" accept="application/pdf,text/plain,image/jpeg,image/png" required /></label>
            </div>
            <div className="intake-submit"><p>服务端校验文件签名并哈希固化；最新 Quality Passport 未获人工批准前，Content Agent 无权引用。</p><button disabled={productMediaUploading}>{productMediaUploading ? "正在固化…" : "提交一组素材证据"}</button></div>
          </form>
          {productMediaReadiness.length > 0 && <div className="media-readiness-grid">{productMediaReadiness.map((item) => <article className="media-readiness-card" key={item.product.id}>
            <div className="sku-card-head"><div><strong>{item.product.sku}</strong><small>{item.product.name}</small></div><span className={item.ready_for_full_production ? "gate ready" : "gate"}>{item.approved_role_count}/7</span></div>
            <div className="media-role-row">{item.roles.map((role) => <span className={role.status} key={role.role}>{productMediaRoleLabels[role.role]}</span>)}</div>
            <p>{item.ready_for_full_production ? "七类原图与权利证据均已批准，可以建立受控图片 Brief。" : item.pending_passport_roles.length ? "已捕获素材正在等待 Passport 人工批准。" : `仍缺：${item.missing_roles.map((role) => productMediaRoleLabels[role]).join("、")}`}</p>
          </article>)}</div>}
          <form className="sku-intake image-brief-form" onSubmit={createImageBrief}>
            <div className="procurement-guardrail">
              <ImageIcon size={18} />
              <p>
                <strong>官方 ComfyUI · {health.comfyui?.status === "ok" ? "本地执行器在线" : "执行器离线"}</strong>
                <span>{health.comfyui?.detail || "仅建立 Brief；执行器恢复后再受控生成。"} 第三方 custom nodes 默认禁用。</span>
              </p>
            </div>
            <div className="intake-basic">
              <label>已就绪 SKU<select name="image_brief_product_id" required><option value="">选择已通过 7/7 的 SKU</option>{productMediaReadiness.filter((item) => item.ready_for_full_production).map((item) => <option value={item.product.id} key={item.product.id}>{item.product.sku} · {item.product.name}</option>)}</select></label>
              <label>来源图片角色<select name="image_brief_role" defaultValue="front_main">{Object.entries(productMediaRoleLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
              <label>处理模式<select name="image_brief_mode" defaultValue="retouch"><option value="retouch">真实图精修</option><option value="composite">受控场景合成</option><option value="infographic">固定模板信息图</option></select></label>
              <label>图片目标<input name="image_brief_goal" defaultValue="Ozon 正面主图" required /></label>
            </div>
            <div className="intake-submit"><p>提交只冻结事实、来源与权利证据，不向 ComfyUI 暴露任意工作流，也不会自动生成或上架。</p><button disabled={imageBriefBusy || !productMediaReadiness.some((item) => item.ready_for_full_production)}>{imageBriefBusy ? "正在冻结…" : "建立受控图片 Brief"}</button></div>
          </form>
          {contentAssets.length > 0 && <div className="content-execution-grid">{contentAssets.map((asset) => {
            const product = products.find((item) => item.id === asset.product_id);
            const mode = String(asset.brief.generation_mode ?? "");
            const busy = imageExecutionBusy === asset.id;
            const comparison = comparisons.find((item) => item.product.id === asset.product_id);
            const profitableRows = comparison?.rows.filter((item) => item.has_positive_cm3 && item.scenario) ?? [];
            return <article className={`content-execution-card ${["generated", "approved"].includes(asset.status) ? "wide" : ""}`} key={asset.id}>
              <div className="sku-card-head">
                <div><strong>{product?.sku ?? asset.product_id}</strong><small>{String(asset.brief.goal ?? "受控图片任务")}</small></div>
                <span className={`gate ${asset.status === "generated" ? "ready" : asset.status === "execution_failed" ? "blocked" : ""}`}>{asset.status}</span>
              </div>
              <p>{mode === "retouch" ? "固定核心节点：真实原图 → Lanczos 4MP 保真缩放 → 证据回收" : "当前只冻结 Brief；场景合成与信息图需真实 SKU 模板验证后开放。"}</p>
              {Boolean(asset.generation.prompt_id) && <small>Prompt · {String(asset.generation.prompt_id)}</small>}
              {asset.artifact_ref && <small>Evidence · {asset.artifact_ref}</small>}
              {mode === "retouch" && ["brief", "qa_failed", "execution_failed"].includes(asset.status) && <button disabled={busy || health.comfyui?.status !== "ok"} onClick={() => runImageGeneration(asset, "queue")}>{busy ? "提交中…" : "提交保真处理"}</button>}
              {asset.status === "queued" && <button disabled={busy} onClick={() => runImageGeneration(asset, "sync")}>{busy ? "同步中…" : "同步执行结果"}</button>}
              {asset.status === "generated" && <form className="image-qa-form" onSubmit={(event) => reviewImageAsset(event, asset)}>
                <div className="content-next-step"><ShieldCheck size={14} />八项必须全部判断；任一失败都会退回</div>
                {imageQaDefinitions.map(([check, label, help]) => <label key={check}>
                  <span><strong>{label}</strong><small>{help}</small></span>
                  <select name={`qa_${check}_passed`} defaultValue="" required>
                    <option value="" disabled>请选择结论</option>
                    <option value="true">通过</option>
                    <option value="false">不通过</option>
                  </select>
                  <textarea name={`qa_${check}_notes`} placeholder="填写核查依据、看到的证据或失败原因" required />
                </label>)}
                <button disabled={imageQaBusy === asset.id}>{imageQaBusy === asset.id ? "正在提交…" : "提交完整人工 QA"}</button>
                <small>审核身份与 UTC 时间由服务端记录；提交后仍不触发 Ozon 发布。</small>
              </form>}
              {asset.status === "approved" && <div className="content-next-step"><CheckCircle2 size={14} />八项 QA 已通过，可进入 Listing 草稿引用；发布仍需独立审批</div>}
              {asset.status === "approved" && <form className="listing-handoff-form" onSubmit={(event) => createListingDraft(event, asset)}>
                <div>
                  <label>正 CM3 方案<select name="listing_scenario" defaultValue="" required>
                    <option value="" disabled>选择已复算方案</option>
                    {profitableRows.map((row) => <option key={row.scenario!.id} value={`${row.offer.id}::${row.scenario!.id}`}>
                      {row.offer.supplier_ref} · CM3 ¥{row.scenario!.cm3_cny} · {row.scenario!.cm3_rate}
                    </option>)}
                  </select></label>
                  <label>Ozon 类目 ID<input name="listing_category_id" required /></label>
                  <label>俄语标题<input name="listing_title" required /></label>
                  <label className="wide">俄语描述<textarea name="listing_description" required /></label>
                </div>
                <p>{profitableRows.length ? "草稿会锁定当前图片 Evidence 与利润场景；创建后只进入发布审批。" : "尚无正 CM3 供应商方案，禁止建立 Listing 草稿。"}</p>
                <button disabled={listingDraftBusy === asset.id || profitableRows.length === 0}>{listingDraftBusy === asset.id ? "正在建立…" : "建立待审批 Listing 草稿"}</button>
              </form>}
              {asset.status === "qa_failed" && asset.qa_results.length > 0 && <div className="image-qa-failures">
                <strong>退回原因</strong>
                {asset.qa_results.filter((item) => !item.passed).map((item) => <span key={item.check}>{imageQaDefinitions.find(([check]) => check === item.check)?.[1] ?? item.check} · {item.notes}</span>)}
              </div>}
            </article>;
          })}</div>}
        </section>

        <section className="passport-review-panel" id="listing-approval">
          <div className="panel-title">
            <div><p className="eyebrow">IMMUTABLE LISTING REVIEW</p><h3>Ozon Listing 发布审批快照</h3></div>
            <span className={pendingListingApprovals.length ? "badge" : "gate ready"}>{pendingListingApprovals.length ? `${pendingListingApprovals.length} 项待独立审批` : "队列已清空"}</span>
          </div>
          {pendingListingApprovals.length ? <div className="review-grid">{pendingListingApprovals.map((approval) => {
            const payload = approval.payload;
            const product = products.find((item) => item.id === String(payload.product_id ?? ""));
            const contentAssetIds = Array.isArray(payload.content_asset_ids) ? payload.content_asset_ids : [];
            const imageRefs = Array.isArray(payload.image_evidence_refs) ? payload.image_evidence_refs : [];
            const snapshot = String(payload.listing_snapshot_sha256 ?? "");
            return <article className="review-card listing-approval-card" key={approval.id}>
              <div className="review-head">
                <div><strong>{product?.sku ?? String(payload.product_id ?? "未知商品")}</strong><small>{String(payload.title ?? "无标题")}</small></div>
                <span>等待独立审批</span>
              </div>
              <div className="fact-list">
                <div><span>Ozon 类目</span><b>{String(payload.category_id ?? "未填写")}</b></div>
                <div><span>预计 CM3</span><b>¥{String(payload.expected_cm3_cny ?? "未知")} · {String(payload.expected_cm3_rate ?? "未知")}</b></div>
                <div><span>图片血缘</span><b>{contentAssetIds.length} 个内容资产 / {imageRefs.length} 份产物证据</b></div>
                <div><span>申请人</span><b>{approval.requested_by}</b></div>
              </div>
              <details className="listing-snapshot-details">
                <summary>查看审批中的完整文案与属性</summary>
                <p>{String(payload.description ?? "无描述")}</p>
                <pre>{JSON.stringify(payload.attributes ?? {}, null, 2)}</pre>
              </details>
              <div className="review-evidence"><ShieldCheck size={14} /><span>草稿摘要</span><b title={snapshot}>{snapshot ? `${snapshot.slice(0, 16)}…` : "摘要缺失"}</b></div>
              <div className="content-next-step"><ShieldCheck size={14} />平台未写入；必须由不同身份核对完整摘要后审批</div>
            </article>;
          })}</div> : <div className="empty"><CheckCircle2 size={25} /><strong>没有待审批 Listing</strong><p>批准图片建立草稿后，会在这里显示完整快照、CM3 和内容血缘。</p></div>}
        </section>

        <section className="passport-review-panel" id="passport-review">
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

        <section className="sourcing-intake-panel" id="sourcing-intake">
          <div className="panel-title"><div><p className="eyebrow">THREE-QUOTE GATE</p><h3>三家供应商证据化比价</h3></div><span className="badge">{pendingProcurementApprovals} 项采购待审批</span></div>
          <form className="sourcing-intake" onSubmit={uploadSupplierComparison}>
            <div className="sourcing-common">
              <label>候选 SKU<select name="sourcing_product_id" required><option value="">选择 SKU</option>{products.map((item) => <option value={item.id} key={item.id}>{item.sku} · {item.name}</option>)}</select></label>
              <label>目标售价 RUB<input name="sale_price_rub" type="number" min="0.01" step="0.01" required /></label><label>RUB/CNY<input name="rub_per_cny" type="number" min="0.0001" step="0.0001" required /></label>
              <label>国际运费 CNY/kg<input name="international_freight" type="number" min="0" step="0.01" required /></label><label>包装 CNY<input name="packaging_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>尾程 CNY<input name="last_mile_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>关税率<input name="customs_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
              <label>平台费率<input name="platform_fee_rate" type="number" min="0" max="0.9999" step="0.0001" required /></label><label>广告率<input name="advertising_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label>
              <label>退货准备率<input name="return_reserve_rate" type="number" min="0" max="0.9999" step="0.0001" defaultValue="0" required /></label><label>仓储 CNY<input name="warehousing_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>税费 CNY<input name="tax_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>汇兑成本 CNY<input name="fx_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>资金占用 CNY<input name="capital_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>售后 CNY<input name="aftersales_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>损耗准备 CNY<input name="loss_reserve_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label><label>未分类成本 CNY（放行须为 0）<input name="other_cost_cny" type="number" min="0" step="0.01" defaultValue="0" required /></label>
              <label>全成本依据清单<input name="assumption_evidence" type="file" required /></label>
            </div>
            <fieldset className="cost-state-grid"><legend>逐项证据状态 · v1.0.0</legend>{sourcingCostDefinitions.map(([key, label]) => <label key={key}>{label}<select name={`cost_state_${key}`} defaultValue="estimate">{(key === "product_cost" || key === "domestic_logistics" ? ["estimate", "actual"] : ["estimate", "actual", "unknown"]).map((state) => <option value={state} key={state}>{costStateLabels[state as keyof typeof costStateLabels]}</option>)}</select></label>)}</fieldset>
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

        {gateReadiness && <section className="comparison-panel">
          <div className="panel-title"><div><p className="eyebrow">THREE-CANDIDATE PORTFOLIO</p><h3>三候选组合决策台</h3></div><span className="badge">{gateReadiness.candidate_portfolio.selection_ready_count} / {gateReadiness.candidate_portfolio.target_count} 可进入人工选择</span></div>
          <p className="section-copy">只展示通过候选交接、原件复验和需求报告门的商品；排序只是决策辅助，不会自动选品、采购、定价或上架。</p>
          {gateReadiness.candidate_portfolio.rows.length ? <div className="comparison-grid">{gateReadiness.candidate_portfolio.rows.map((item, index) => <article className="comparison-card" key={item.product.id}>
            <div className="rank">#{index + 1}</div><strong>{item.product.sku} · {item.product.name}</strong>
            <small>{item.supplier_count}/3 家当前供应商 · {item.complete_profit_scenario_count} 个完整正 CM3 场景 · Passport {item.passports_ready ? "已通过" : "未完成"}</small>
            <div className="cm3"><span>当前最佳可用场景</span><b>{item.best_scenario ? `${item.best_scenario.cm3_cny} CNY` : "尚无场景"}</b><small>{item.best_scenario ? `${item.best_scenario.supplier_ref ?? "供应商未知"} · CM3 ${(Number(item.best_scenario.cm3_rate) * 100).toFixed(1)}% · 保本价 ${item.best_scenario.break_even_price_rub || "未知"} RUB` : "需要三报价和全成本证据"}</small></div>
            <div className={item.ready_for_g1_review ? "knowledge-status usable" : "knowledge-status invalid"}><span>{item.ready_for_g1_review ? "证据链满足人工选择门" : item.blockers.join("；")}</span><b>自动执行：禁止</b></div>
          </article>)}</div> : <div className="empty-state">还没有通过资格门的真实候选。历史目录和未复核商品不会进入本组合。</div>}
        </section>}

        {comparisons.length > 0 && <section className="comparison-panel">
          <div className="panel-title"><div><p className="eyebrow">SOURCING DECISION</p><h3>报价与 CM3 比较</h3></div><span className="gate ready">仅人工提交采购</span></div>
          {comparisons.map((comparison) => <div className="comparison-group" key={comparison.product.id}><div className="comparison-title"><strong>{comparison.product.sku} · {comparison.product.name}</strong><span>{comparison.supplier_count}/3 家供应商</span></div><div className="comparison-grid">{comparison.rows.map((row, index) => {
            const draft = procurementDrafts[row.offer.id] ?? { quantity: String(row.offer.min_order_quantity), rationale: "" };
            const passportReady = skuReadiness.find((item) => item.product.id === comparison.product.id)?.ready_for_validation;
            const unknownCosts = row.scenario ? Object.values(row.scenario.cost_states).filter((state) => state === "unknown").length : 0;
            return <article className="comparison-card" key={row.offer.id}><div className="rank">#{index + 1}</div><strong>{row.offer.supplier_ref}</strong><small>{row.offer.platform} · {row.offer.unit_price} {row.offer.currency} · MOQ {row.offer.min_order_quantity}</small><div className="cm3"><span>预计 CM3 · {row.scenario?.template_id ?? "无模板"}</span><b>{row.scenario ? `${row.scenario.cm3_cny} CNY` : "缺少场景"}</b><small>{row.scenario ? `${(Number(row.scenario.cm3_rate) * 100).toFixed(1)}% · 保本价 ${row.scenario.break_even_price_rub} RUB · ${unknownCosts ? `${unknownCosts} 项未知` : "成本项可追溯"}` : ""}</small></div>
              {row.scenario && <details className="cost-provenance"><summary>查看 15 项成本来源</summary><div>{sourcingCostDefinitions.map(([key, label]) => {
                const state = row.scenario?.cost_states[key] ?? "unknown";
                const evidenceId = row.scenario?.cost_evidence[key];
                return <p className={`cost-source ${state}`} key={key}><span>{label}</span><b>{costStateLabels[state]}</b><code>{evidenceId ? `证据 …${evidenceId.slice(-8)}` : "无证据"}</code></p>;
              })}</div></details>}
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
