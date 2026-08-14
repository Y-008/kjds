export type TeamControlTask = {
  id: string;
  title: string;
  severity: string;
  owner: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type TeamControlFlow = {
  flow_ref: string;
  display_title: string;
  objective: string;
  declared_state: string;
  runtime_status: string;
  accountable_role: string;
  risk_level: "L0" | "L1" | "L2" | "L3" | "L4";
  current_operating_task: TeamControlTask | null;
  source_assignments: Array<{
    lane_id: string;
    lane_name: string;
    accountable_role: string;
    current_task: { task_id: string; state: string } | null;
    next_task_id: string | null;
  }>;
  blockers: string[];
  overdue: boolean;
  due_at: string | null;
  default_next_action: string;
  success_evidence: string[];
};

export type TeamNextAction = {
  kind: string;
  label: string;
  owner: string;
  risk_level: "L0" | "L1" | "L2" | "L3" | "L4";
  due_at: string | null;
  blocker_refs: string[];
  required_evidence: string[];
  evidence_required: boolean;
  allowed_results: Array<"take" | "done" | "blocked" | "escalate" | "stop">;
  continuation: string;
  decision_basis_sha256: string;
};

export type TruthStatus = "VERIFIED" | "PARTIAL" | "BLOCKED" | "STALE" | "CONFLICTED" | "UNKNOWN";

export type TruthProjection = {
  status: TruthStatus;
  reason_codes: string[];
  source_refs: Array<{ ref: string; sha256?: string | null; as_of?: string }>;
  as_of: string;
  projection_sha256: string;
};

export type OrganizationReadiness = TruthProjection & {
  contract_counts: {
    human_core_required: number;
    ai_specialists_required: number;
    expert_pool_target: { minimum: number; maximum: number };
    independent_control_roles_required: number;
  };
  registry_counts: {
    human_core_contracts: number;
    ai_specialist_contracts: number;
    expert_pool_categories: number;
    control_role_contracts: number;
  };
  verified_bindings: { human_core: number; expert_pool: number | null; control_roles: number };
  missing: {
    primary_role_refs: string[];
    alternate_role_refs: string[];
    qualification_role_refs: string[];
    conflict_attestation_role_refs: string[];
  };
  blockers: string[];
};

export type CriticalPath = TruthProjection & {
  campaign_ref: string;
  planned_start_on: string;
  planned_end_on: string;
  actual_campaign_day: number | null;
  kickoff: {
    status: TruthStatus;
    occurred_at: string | null;
    evidence_count: number;
    reason_codes: string[];
  };
  earliest_blocking_phase_ref: string | null;
  phases: Array<{
    phase_ref: string;
    title: string;
    day_from: number;
    day_to: number;
    planned_start_on: string;
    planned_end_on: string;
    actual_campaign_day: number | null;
    status: TruthStatus;
    reason_codes: string[];
    owner_role: string;
    reviewer_role: string;
    blockers: string[];
    required_evidence: string[];
    gate_refs: string[];
    stop_conditions: string[];
    current_operating_task: TeamControlTask | null;
    runtime_task_status: string | null;
    formal_gate_pass: false;
  }>;
};

export type Top1Scorecard = TruthProjection & {
  global_top1_claim: false;
  dimension_count: number;
  metric_leader_count: number;
  largest_open_gap: { dimension_ref: string; title: string; gap_status: string } | null;
  dimensions: Array<{
    dimension_ref: string;
    title: string;
    status: TruthStatus;
    reason_codes: string[];
    owner_role: string;
    verifier_role: string;
    leadership_status: "METRIC_LEADER" | "NOT_LEADER" | "UNKNOWN";
    gap_status: "CLOSED" | "OPEN" | "UNKNOWN";
    current_value: { mode: string; value?: string; lower?: string; upper?: string } | null;
    cohort_ref: string | null;
    market: string | null;
    window: { start: string; end: string } | null;
    next_experiment: string;
    invalidates_at: string | null;
  }>;
};

export type CashAtRisk = TruthProjection & {
  forecast_weeks: 13;
  quote_currency: string;
  thirteen_week_cash: { status: TruthStatus; forecast: null; reason_codes: string[] };
  cash_runway: { status: TruthStatus; value: Record<string, string> | null; reason_codes: string[] } | null;
  maximum_loss: { status: TruthStatus; value: Record<string, string> | null; reason_codes: string[] } | null;
  cash_floor: { status: TruthStatus; value: null; reason_codes: string[] };
  committed_cash: { status: TruthStatus; value: null; reason_codes: string[] };
  actual_cash_truth: TruthProjection & {
    source_status: string;
    verified_cycle_count: number;
    minimum_reconciled_cycles: number;
    counts: {
      total_cycles: number;
      order_fact_cycles: number;
      settlement_cycles: number;
      cash_cycles: number;
      reconciled: number;
      actual_cash_cm3_available: number;
    } | null;
  };
  missing_authorities: string[];
  forecast_invoked: false;
};

export type DeliveryGate = TruthProjection & {
  gate_count: 5;
  passed_gate_count: number;
  gates: Array<{
    gate_ref: string;
    title: string;
    status: TruthStatus;
    reason_codes: string[];
    owner_role: string;
    pass_requires: string[];
    blockers: string[];
    formal_gate_pass: false;
    formal_gate_authority_status: "UNKNOWN";
    readiness_status: TruthStatus;
    readiness_reason_codes: string[];
  }>;
};

export type EnterpriseAiErpProgramContract = {
  contract_id: "kjds-enterprise-ai-erp-program-v1";
  contract_version: string;
  program_snapshot_sha256: string;
  registry_sha256: string;
  source_bundle_sha256: string;
  static_contract_integrity: "VERIFIED";
  runtime_authority_connected: false;
};

export type EnterpriseAiErpProjection = TruthProjection & {
  projection:
    | "squad_readiness"
    | "role_conflicts"
    | "parallel_execution"
    | "integration_queue"
    | "capacity_risk"
    | "next_release_train";
  program_contract?: EnterpriseAiErpProgramContract | null;
};

export type SquadReadiness = EnterpriseAiErpProjection & {
  projection: "squad_readiness";
  contract_count?: number;
  items?: Array<{
    squad_ref: string;
    title: string;
    owner_role_ref: string;
    reviewer_role_ref: string;
    primary_lane_id: string;
    supporting_lane_ids: string[];
    required_functions: string[];
    capability_atlas_ids: string[];
    capability_gap_refs: string[];
    work_item_refs: string[];
    first_acceptance_contract: string;
    status: "UNKNOWN";
    reason_codes: string[];
  }>;
};

export type RoleConflicts = EnterpriseAiErpProjection & {
  projection: "role_conflicts";
  contract_rules_verified?: boolean;
  rules?: Array<{
    rule_ref: string;
    left_function_ref: string;
    right_function_ref: string;
    same_role_allowed: boolean;
    same_principal_allowed: boolean;
    identity_authority_required: boolean;
  }>;
  observed_conflicts?: Array<Record<string, unknown>> | null;
};

export type ParallelExecution = EnterpriseAiErpProjection & {
  projection: "parallel_execution";
  policy?: {
    control_agent_count: number;
    max_parallel_specialist_agents: number;
    max_active_writers: number;
    max_active_tasks_per_specialist: number;
    max_active_tasks_per_writer: number;
    max_current_tasks_per_lane: number;
    max_weekly_company_outcomes: number;
    release_trains_per_week: number;
    single_integrator_domains: string[];
    failed_slice_blocks_independent_slices: boolean;
    path_or_hash_drift_action: string;
    shared_lease_conflict_action: string;
  };
  observed_active_writers?: number | null;
  observed_writer_wip?: number | null;
  observed_lane_current_tasks?: number | null;
};

export type IntegrationQueue = EnterpriseAiErpProjection & {
  projection: "integration_queue";
  planned_initial_state?: "NOT_STARTED";
  items?: Array<{
    work_item_ref: string;
    title: string;
    dependency_refs: string[];
    squad_refs: string[];
    lane_affinity_ids: string[];
    execution_status: "UNKNOWN";
  }>;
  parallel_waves?: string[][];
};

export type CapacityRisk = EnterpriseAiErpProjection & {
  projection: "capacity_risk";
  limits?: {
    control_agent_count: number;
    max_parallel_specialist_agents: number;
    max_active_writers: number;
    max_active_tasks_per_specialist: number;
    max_active_tasks_per_writer: number;
    max_current_tasks_per_lane: number;
    max_weekly_company_outcomes: number;
  };
  observed_active_writers?: number | null;
  observed_specialist_wip?: number | null;
  observed_lane_wip?: number | null;
  observed_weekly_company_outcomes?: number | null;
  capacity_proven_available?: false;
};

export type NextReleaseTrain = EnterpriseAiErpProjection & {
  projection: "next_release_train";
  release_trains_per_week?: number;
  scheduled_at?: string | null;
  eligible_work_item_refs?: string[] | null;
  gate_status?: TruthStatus;
  registry_proves_schedule?: false;
};

export type TeamControlBrief = {
  contract_id: "kjds-team-control-tower-v1";
  contract_version: string;
  status: "on_track" | "attention_required" | "blocked" | "awaiting_human" | "scope_invalid";
  headline: string;
  scope: {
    tenant_ref: string;
    entity_ref: string;
    store_ref: string;
    scope_authority_sha256: string;
  } | null;
  as_of: string;
  executive_summary: {
    flow_count: number;
    active_flow_count: number;
    blocked_flow_count: number;
    active_team_task_count: number;
    overdue_task_count: number;
    conflict_count: number;
    human_binding_ready: boolean;
  };
  next_action: TeamNextAction | null;
  flows: TeamControlFlow[];
  conflicts: Array<Record<string, unknown>>;
  organization_readiness: TruthProjection & Partial<Omit<OrganizationReadiness, keyof TruthProjection>>;
  critical_path: TruthProjection & Partial<Omit<CriticalPath, keyof TruthProjection>>;
  top1_scorecard: TruthProjection & Partial<Omit<Top1Scorecard, keyof TruthProjection>>;
  cash_at_risk: TruthProjection & Partial<Omit<CashAtRisk, keyof TruthProjection>>;
  delivery_gate: TruthProjection & Partial<Omit<DeliveryGate, keyof TruthProjection>>;
  squad_readiness: SquadReadiness;
  role_conflicts: RoleConflicts;
  parallel_execution: ParallelExecution;
  integration_queue: IntegrationQueue;
  capacity_risk: CapacityRisk;
  next_release_train: NextReleaseTrain;
  decision_basis_sha256: string | null;
  team?: {
    leader: string;
    specialist_count: number;
    control_role_count: number;
    escalation_chain: string[];
  } | null;
  snapshot_sha256: string;
  control_envelope: Record<string, boolean>;
};

export type TeamAdvanceReceipt = {
  outcome: "accepted" | "idempotent_replay";
  operating_task: TeamControlTask;
  event: { event_type: string } | null;
  external_write_allowed: false;
  receipt_sha256: string;
};

export type EnterpriseBusinessModel =
  | "merchant_operator"
  | "commerce_control_plane_provider"
  | "hybrid_operator_and_control_plane";

export type EnterpriseStage = "validation" | "repeatable" | "scale" | "enterprise";
export type EnterpriseHeadcountBand = "solo_to_micro" | "small" | "medium" | "large";
export type EnterpriseRiskClass = "standard" | "elevated" | "regulated";
export type EnterprisePrimaryObjective =
  | "actual_cash_truth"
  | "repeatable_growth"
  | "multi_market_scale"
  | "enterprise_ai_erp";

export type EnterpriseProfile = {
  enterprise_ref: string;
  business_model: EnterpriseBusinessModel;
  stage: EnterpriseStage;
  headcount_band: EnterpriseHeadcountBand;
  markets: string[];
  platforms: string[];
  risk_class: EnterpriseRiskClass;
  primary_objective: EnterprisePrimaryObjective;
};

export type EnterpriseRoleRecommendationStatus =
  | "required_now"
  | "supporting_ai"
  | "on_demand"
  | "standby";

export type EnterpriseRoleTemplate = {
  role_ref: string;
  role_template_ref: string;
  title: string;
  mission: string;
  role_kind: "core" | "ai_specialist" | "independent_control";
  recommendation_status: EnterpriseRoleRecommendationStatus;
  reason_codes: string[];
  objective_priority: number | null;
  runtime_mode: "capability_template_only";
  human_binding_status: "UNKNOWN";
  human_seat_eligible: boolean;
  production_authority_granted: false;
  external_write_allowed: false;
  formal_fact_promotion_allowed: false;
};

export type EnterprisePositioningProjection = {
  contract_id: "kjds-enterprise-positioning-advisor-v2";
  version: "2.0.0";
  status: "RECOMMENDATION_ONLY";
  enterprise_profile: EnterpriseProfile;
  profile_scope: {
    enterprise_ref: string;
    scope_ref: string;
    grants_authority: false;
  };
  enterprise_positioning: {
    archetype_ref: string;
    current_positioning: string;
    value_wedge: string;
    business_model_emphasis: string;
    target_positioning: string;
    promotion_gate_status: "BLOCKED_EVIDENCE";
    required_gates: string[];
    automation_ceiling:
      | "simulation_only"
      | "read_only_recommendation_only"
      | "zero_external_action_without_professional_gate";
    boundaries: {
      is_erp_replacement: false;
      is_unattended_autonomous_company: false;
      is_generic_ai_outsourcing: false;
      is_business_truth_authority: false;
      system_may_appoint_humans: false;
      system_may_grant_production_authority: false;
      role_templates_may_external_write: false;
      profile_scope_grants_authority: false;
    };
  };
  role_roster: EnterpriseRoleTemplate[];
  role_summary: {
    catalog_total: number;
    required_now: number;
    supporting_ai: number;
    on_demand: number;
    standby: number;
    unsupported_gap: number;
    core: number;
    ai_specialist: number;
    independent_control: number;
  };
  seat_plan: Array<{
    seat_ref: string;
    title: string;
    mission: string;
    binding_status: "UNKNOWN";
    role_bundle_refs: string[];
    ai_templates_excluded: true;
    appointment_evidence_present: false;
    sod_conflict_refs: string[];
  }>;
  minimum_human_accountability: Array<{
    seat_ref: string;
    binding_status: "UNKNOWN";
    appointment_evidence_present: false;
    role_template_is_appointment_evidence: false;
  }>;
  separation_of_duties: Array<{
    rule_ref: string;
    left_function_ref: string;
    right_function_ref: string;
    same_role_allowed: false;
    same_principal_allowed: false;
    identity_authority_required: true;
  }>;
  role_gaps: Array<{
    gap_ref: string;
    reason_code:
      | "market_specific_role_contract_missing"
      | "platform_specific_role_contract_missing";
    recommendation_status: "unsupported_gap";
    authority_status: "UNKNOWN";
  }>;
  next_role_activation: {
    role_ref: string | null;
    role_template_ref: string | null;
    current_status: EnterpriseRoleRecommendationStatus | null;
    target_status: "required_now";
    reason_code:
      | "primary_objective_next_capability"
      | "objective_capabilities_already_required";
    required_gate: string;
  };
  capacity_plan: {
    headcount_band: EnterpriseHeadcountBand;
    max_human_seats: number;
    planned_human_seats: number;
    max_parallel_workstreams: number;
    max_active_work_per_human: number;
    role_bundle_mode:
      | "four_seat_compressed"
      | "four_accountability_seats"
      | "dedicated_role_bindings_preferred"
      | "dedicated_role_bindings_required";
    ai_templates_count_as_humans: false;
  };
  system_actions: {
    identities_created: false;
    agents_created: false;
    humans_appointed: false;
    appointments_created: false;
    roles_bound: false;
    tasks_started: false;
    budgets_created: false;
    approvals_created: false;
    permits_issued: false;
    production_authority_granted: false;
    facts_promoted: false;
    external_write_performed: false;
  };
  source_hashes: {
    enterprise_ai_erp_program: string;
    enterprise_positioning_profiles: string;
    global_expert_team: string;
    team_control_tower: string;
  };
  source_bundle_sha256: string;
  snapshot_sha256: string;
};
