export type Health = { name: string; status: string; detail?: string | null };
export type WebSession = {
  authenticated: boolean;
  auth_mode: "legacy" | "supabase";
  email: string | null;
  actor_id: string;
  roles: string[];
};
export type OzonImportResult = {
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
export type OzonImportPreview = {
  record_type: string;
  row_count: number;
  mapping: Record<string, string>;
  missing_columns: string[];
  ready: boolean;
};
export type FinanceReviewStatus = {
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
export type CostAuthorityCatalog = {
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
export type ActualCostAuthorityStatus = {
  evidence_id: string;
  cost_type: string;
  status: "pending" | "accepted" | "rejected";
  accepted_authorities: string[];
  review_ids: string[];
  review_count: number;
};
export type FeeCodeStatus = {
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
export type AccrualClassificationStatus = {
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
export type Recommendation = {
  id: string;
  agent: string;
  action: string;
  expected_cm3_delta?: string | null;
  risk: string;
  status: string;
  shadow_mode: boolean;
};
export type SourceConnector = {
  platform: string;
  ingestion: string;
  authentication: string;
  status: string;
  notes: string;
};
export type PassportReadiness = {
  kind: "product" | "compliance" | "quality";
  status: "missing" | "draft" | "awaiting_approval" | "approved" | "blocked";
  missing_fields: string[];
  evidence_count: number;
};
export type ProductReadiness = {
  product: { id: string; sku: string; name: string; status: string };
  passports: PassportReadiness[];
  ready_for_validation: boolean;
};
export type ProductMediaReadiness = {
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
export type ContentAssetView = {
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
export type PassportReview = {
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
export type ProductIdentity = { id: string; sku: string; name: string };
export type SourcingComparison = {
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
export type MarketplaceGrowthPlan = {
  plan_id: string;
  snapshot_hash: string;
  created_by: string;
  evaluated_at: string;
  target_cm3_rate: string;
  execution_mode: "recommendation_only";
  automatic_marketplace_write: false;
  automatic_ad_spend: false;
  summary: {
    sku_count: number;
    blocked_count: number;
    price_reset_count: number;
    source_mismatch_count: number;
    ad_test_eligible_count: number;
  };
  portfolio: Array<{
    marketplace_sku: string;
    product_id: string;
    product_name: string;
    scenario_id: string;
    snapshot_hash: string;
    evidence_ids: string[];
    commercial_status: string;
    priority_score: number;
    current: {
      price_rub: string;
      price_cny: string;
      stock: number;
      orders_14d: number;
      review_count: number;
      rating: string;
      content_score: string;
      price_position: string;
      price_gap_to_median: string;
    };
    market: {
      competitor_count: number;
      p25_rub: string;
      median_rub: string;
      p75_rub: string;
      observation_age_days: number;
    };
    economics: {
      cost_release_ready: boolean;
      fixed_costs_cny: string;
      target_floor_price_rub: string;
      recommended_test_price_rub: string | null;
      break_even_acos: string;
      target_acos_ceiling: string;
      max_ad_spend_per_order_cny: string;
      max_cpc_cny: string | null;
    };
    gates: Record<string, boolean>;
    ad_eligible: boolean;
    content_plan: {
      image_roles: Array<{ role: string; objective: string }>;
      copy_requirements: string[];
    };
    actions: Array<{ type: string; reason: string }>;
  }>;
};
export type MarketplaceGrowthObservation = {
  scenario_id: string;
  marketplace_sku: string;
  category: string;
  competitor_prices_rub: string[];
  stock: number;
  review_count: number;
  orders_14d: number;
  rating: string;
  content_score: string;
  conversion_rate: string | null;
  compliance_risk: "low" | "medium" | "high";
  observed_at: string;
  evidence_ids: string[];
  observation_hash: string;
  snapshot_id: string;
  snapshot_source: "ozon_seller_api" | "ozon_export" | "operator_verified";
  captured_by: string;
  captured_at: string;
};
export type ApprovalRecord = { id: string; action: string; resource_id: string; status: string; requested_by: string; payload: Record<string, unknown> };
export type ListingDraft = {
  id: string; product_id: string; offer_id: string; scenario_id: string; target_platform: string;
  listing_data: Record<string, unknown>; requested_by: string; status: string;
  approval_id: string | null; created_at: string;
};
export type SampleEvent = { id: string; sequence: number; event_type: string; effective_at: string; evidence_id: string; facts: Record<string, unknown> };
export type SampleOrder = {
  id: string; approval_id: string; product_id: string; product: { sku: string; name: string };
  offer_id: string; scenario_id: string; supplier_ref: string; quantity: number; currency: string;
  unit_price: string; status: string; next_events: string[]; events: SampleEvent[];
};
export type SupplierPerformance = {
  supplier_ref: string; sample_order_count: number; completed_sample_count: number; rejected_sample_count: number;
  quality_yield: string | null; delivery_completeness: string | null; on_time_rate: string | null;
  score: string | null; evidence_count: number;
};
export type BackupOption = {
  offer: { id: string; supplier_ref: string; platform: string; unit_price: string; currency: string; min_order_quantity: number };
  scenario: { id: string; cm3_cny: string; cm3_rate: string; break_even_price_rub: string };
  supplier_performance: SupplierPerformance | null;
  advisory_only: boolean;
};
export type GateRequirement = {
  id: string;
  title: string;
  ready: boolean;
  status: "ready_for_review" | "needs_input";
  current: number;
  target: number;
  next_action: string;
  details?: Record<string, unknown>;
};
export type GateReadiness = {
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
export type EvidenceSummary = {
  id: string; sha256: string; filename: string; source: string; source_ref: string; grade: string;
  effective_at: string; effective_until: string | null; created_by: string;
  metadata: Record<string, unknown>;
};
export type CandidateResearchAssessment = {
  candidate_ref: string; candidate_name: string; market: string; category: string; decision: "reject" | "collect_evidence" | "request_three_quotes";
  demand_report_evidence_id: string;
  reasons: string[]; missing_metrics: string[]; source_family_count: number; evidence_ids: string[];
  low_authority_evidence_ids: string[]; minimum_evidence_grades: Record<string, string[]>;
  measurement_policy_id: string; quote_policy_id: string; quote_policy_status: string; metric_values: Record<string, string>;
  threshold_failures: Array<{ metric: string; operator: "gte" | "lte"; threshold: string; actual: string }>;
  required_supplier_quotes: number; automatic_product_creation: false; automatic_listing: false; next_gate: string | null;
};
export type CandidateAuthorityStatus = {
  evidence_id: string; metric: string; status: "pending" | "accepted" | "rejected";
  accepted_grades: string[]; review_count: number;
};
export type CandidateSourcingHandoff = {
  product: ProductIdentity; created: boolean; candidate_ref: string; evidence_ids: string[]; next_gate: "sourcing_comparison_intake";
  automatic_procurement: false; automatic_listing: false;
};
export type InteractionProfile = {
  id: string; version: string; label: string; description: string; aliases: string[];
  workflow_steps: string[]; output_requirements: string[]; max_questions: number;
  presentation_only: boolean; evidence_required_before_conclusion: boolean;
  requires_options: boolean; requires_forecast_basis: boolean;
};
export type DecisionContract = {
  id: string; profile_id: string; profile_version: string; objective: string; decision_domain: string;
  risk_level: string; horizon_days: number | null; maximum_loss_amount: string | null; currency: string;
  source_contract_id: string | null; input: Record<string, unknown>; output_requirements: string[];
  evidence_ids: string[]; compiler_policy: Record<string, boolean | string | number>;
  missing_inputs: string[]; status: string; execution_eligible: boolean;
  requires_human_approval: boolean; requested_by: string; created_at: string;
};
export type DecisionAnalysis = {
  id: string; contract_id: string; conclusion: string; recommended_option_id: string | null;
  confidence: string; forecast: null | { metric: string; value: string; low: string; high: string; unit: string; due_at: string };
  assumptions: string[]; unknowns: string[]; selection_assessment: Record<string, unknown>;
  evidence_ids: string[]; model_ref: string | null;
  submitted_by: string; execution_eligible: boolean; created_at: string;
};
export type DecisionReview = { id: string; analysis_id: string; verdict: string; rationale: string; counterarguments: string[]; evidence_ids: string[]; reviewed_by: string; created_at: string };
export type DecisionResolution = { id: string; contract_id: string; analysis_id: string; disposition: string; rationale: string; conditions: string[]; decided_by: string; execution_eligible: boolean; created_at: string };
export type DecisionOutcome = { id: string; resolution_id: string; metric: string; predicted_value: string; interval_low: string; interval_high: string; actual_value: string; unit: string; signed_error: string; absolute_error: string; interval_covered: boolean; observed_at: string; evidence_ids: string[]; notes: string; recorded_by: string; created_at: string };
export type DecisionCalibration = { metric: string; unit: string; outcome_count: number; mean_absolute_error: string; mean_absolute_percentage_error: string | null; interval_coverage: string };
export type CausalExperiment = {
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
export type ExperimentEvaluation = {
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
export type CausalExperimentReview = {
  id: string; protocol_id: string; evaluation_hash: string; verdict: string; rationale: string;
  method_assessment: string; data_quality_assessment: string; counterarguments: string[];
  evidence_ids: string[]; reviewed_by: string; created_at: string; immutable: boolean;
};
export type CausalKnowledgeEntry = {
  id: string; protocol_id: string; review_id: string; claim: string; mechanism: string;
  applicability: Record<string, unknown>; falsification_conditions: string[];
  effect_snapshot: { primary_metric: string; incremental_value_per_unit: string | null };
  evidence_ids: string[]; valid_from: string; reevaluate_at: string; validity_status: string;
  usable: boolean; knowledge_strength: string; execution_eligible: boolean; automatic_rollout: boolean;
  replication_of: null | { source_knowledge_id: string; scope_relation: string };
  replications: Array<{ replication_knowledge_id: string; scope_relation: string }>;
};
export type CausalPolicy = {
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
export type PolicyShadowBatch = {
  id: string; policy_id: string; release_id: string; evaluation_ids: string[]; context_count: number;
  matched_count: number; fallback_count: number; zero_exposure: boolean; execution_eligible: boolean; created_at: string;
};
export type PolicyActivationHandoff = {
  id: string; policy_id: string; release_id: string; approval_id: string; approval_status: string;
  validity_status: string; activation_eligible: boolean; execution_eligible: boolean; created_at: string;
};
export type LimitedExecutionCommandStatus = "queued" | "claimed" | "write_started" | "succeeded" | "failed" | "uncertain" | "expired" | "precondition_failed";
export type GovernedExecutionPlan = {
  id: string;
  source_kind: "causal_policy_handoff" | "approved_listing_draft";
  source_id: string;
  source_approval_id: string;
  source_snapshot_hash: string;
  handoff_id: string | null; policy_id: string | null; release_id: string | null; adapter_id: string;
  target: Record<string, string>; precondition_state_hash: string;
  intended_patch: Record<string, unknown>; rollback_patch: Record<string, unknown>;
  approval_id: string; approval_status: string; source_approval_status?: string;
  handoff_validity_status: string | null; source_validity_status: string;
  authorization_blocking_reasons: string[];
  current_readiness_snapshot: Record<string, { ready: boolean; evidence_ids: string[]; blocking_reasons: string[] }>;
  evidence_ids: string[];
  dry_run: null | { id: string; passed: boolean; platform_write_performed: boolean };
  ready_for_executor: boolean; execution_eligible: boolean; live_execution_supported: boolean;
};
export type LimitedExecutionCommand = {
  id: string; plan_id: string; parent_command_id: string | null; command_kind: "execute" | "rollback";
  idempotency_token: string; operation: string; target: Record<string, string>;
  expected_state_hash: string; status: LimitedExecutionCommandStatus; claimed_by: string | null;
  receipt: null | { outcome: "succeeded" | "failed" | "uncertain"; mutation_applied: boolean; rollback_command_id: string | null; evidence_ids: string[]; error_code: string | null };
  platform_write_performed: boolean;
};
export type ExecutionObservationWindow = {
  id: string; command_id: string; plan_id: string; policy_id: string;
  primary_metric: string; baseline: Record<string, string>;
  guardrails: Array<{ metric: string; direction: "min" | "max"; threshold: string }>;
  required_observations: number; starts_at: string; ends_at: string; status: string;
  observations: Array<{ id: string; metric: string; value: string; observed_at: string; guardrail_breached: boolean; rollback_command_id: string | null }>;
  evaluation: { status: string; rollback_queued: boolean; kill_switch_engaged: boolean };
  automatic_policy_promotion: boolean;
};
export type CapabilityEconomicAssessment = {
  id: string; window_id: string; adapter_id: string; outcome_status: string;
  realized_incremental_value: string; avoided_loss: string; model_compute_cost: string;
  human_review_cost: string; incident_loss: string; maintenance_cost: string;
  net_value: string; currency: string; automatic_authority_change: boolean;
};
export type OperationalIncident = {
  id: string; mode: "live" | "drill"; severity: string; trigger_type: string;
  source_type: string | null; source_id: string | null; summary: string; impact: string[];
  status: string; owner_id: string | null; review_status: string | null; opened_by: string;
  checks: Record<string, { check: string; passed: boolean; notes: string }>;
  required_checks: string[]; kill_switch_engaged: boolean; automatic_release: boolean;
};
export type OperationsQueueItem = {
  queue_key: string; item_type: string; item_id: string; title: string; status: string;
  priority: string; owner_id: string | null; due_at: string; overdue: boolean;
  overdue_minutes: number; escalation_level: number; next_action: string;
};
export type OperatingWorkbenchBriefing = {
  contract_id: "kjds-operating-workbench-briefing-v1";
  mode: "shadow_advisory";
  status: "ready_for_review" | "needs_input";
  snapshot_sha256: string;
  summary: {
    gate_blockers: number; runtime_items: number; recommendations: number; visible_items: number;
    candidate_count: number; selection_ready_count: number;
  };
  agents: Array<{
    agent_id: string; name: string; status: "needs_attention" | "waiting_for_upstream";
    work_item_count: number; current_focus: string; automatic_execution: false;
  }>;
  work_items: Array<{
    id: string; item_type: "gate_blocker" | "runtime_operation" | "recommendation";
    source_type: string; source_id: string; agent_id: string; agent_name: string;
    title: string; status: string; priority: string; risk: string; next_action: string;
    human_required: true; evidence_ids: string[]; gate: string | null;
    progress: { current: number; target: number } | null; due_at: string | null;
    overdue: boolean | null; escalation_level: number | null;
    expected_cm3_delta?: string | null; automatic_execution: false; platform_write_allowed: false;
  }>;
  candidate_portfolio: GateReadiness["candidate_portfolio"];
  guardrails: {
    advisory_only: true; automatic_execution: false; automatic_product_selection: false;
    automatic_procurement: false; automatic_pricing: false; automatic_listing: false;
    platform_write_allowed: false; third_party_fact_promotion_allowed: false;
  };
};
export type ReadOnlyPilot = {
  id: string; platform: string; account_alias: string; allowed_operations: string[];
  max_daily_requests: number; max_targets: number; starts_at: string; ends_at: string;
  status: string; requested_by: string; reviewed_by: string | null; activated_by: string | null;
  controls: Record<string, { passed: boolean; notes: string }>;
  required_controls: string[]; platform_write_allowed: boolean; execution_eligible: boolean;
  credential_material_stored: boolean;
};
export type PilotEvaluation = {
  ready_for_review: boolean; ready_for_activation: boolean; requirements: Record<string, boolean>;
  blockers: string[]; recent_drill_ids: string[]; platform_write_allowed: boolean; automatic_activation: boolean;
};
