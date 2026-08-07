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
  decision_basis_sha256: string | null;
  team?: {
    leader: string;
    specialist_count: number;
    control_role_count: number;
    escalation_chain: string[];
  };
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
