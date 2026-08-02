export type StatusValue = "available" | "available_unaggregated" | "blocked" | "no_data" | string;

export type MoneyProjection = {
  status?: StatusValue;
  amount: string | null;
  currency: string | null;
  reason?: string | null;
  evidence_id?: string;
  occurred_at?: string;
};

export type DistributionRow = {
  key: string;
  count: number;
};

export type CategoryLevel = {
  id: string;
  name: string;
};

export type CategoryPath = {
  path_id?: string;
  role?: string;
  level_1?: CategoryLevel | null;
  level_2?: CategoryLevel | null;
  level_3?: CategoryLevel | null;
  leaf_category_id?: string | null;
  product_type_ids?: string[];
  derived_tags?: string[];
};

export type StoreCategoryRoute = {
  decision: string;
  confidence: string;
  target_store_ref: string | null;
  target_category_path: CategoryPath | null;
  category_role: string | null;
  match_basis: string[];
  derived_tags: string[];
  derived_tags_are_official_taxonomy: false;
  reason_codes: string[];
  playbook: {
    lifecycle: string;
    operating_mode: string;
    listing: string;
    traffic: string;
    inventory: string;
    growth_channels: string[];
    required_gates: string[];
    focus_metrics: string[];
    next_action?: string | null;
    budget_limit?: MoneyProjection | null;
    stop_loss_condition?: string | null;
  };
  external_write_allowed: false;
};

export type ProfitBasis = MoneyProjection & {
  baseline_cm3?: string | null;
  expected_cm3?: string | null;
  downside_cm3?: string | null;
  cvar_cm3?: string | null;
  authority?: string | null;
};

export type ProfitCandidate = {
  candidate_id: string;
  offer_id: string;
  name: string;
  decision_class: string;
  decision_eligible: boolean;
  category_identity: {
    source_category_id: string | null;
    product_type_id: string | null;
    hierarchy: Record<string, string | null>;
    hierarchy_status?: string;
    derived_tags: string[];
    derived_tags_are_official_taxonomy: false;
  };
  raw_money: {
    own_price: MoneyProjection | null;
    market_reference_price: MoneyProjection | null;
    display_currency: string;
    fx_basis: Record<string, unknown> | null;
  };
  cost_coverage: {
    required: number;
    evidenced: number;
    estimated: number;
    unknown: number;
    components: Array<{ name: string; status: string }>;
  };
  profit: {
    scenario_profit: ProfitBasis;
    accrual_profit: ProfitBasis;
    settlement_profit: ProfitBasis;
    cash_profit: ProfitBasis;
    risk_adjusted_profit: ProfitBasis;
  };
  quality: Record<string, string>;
  reason_codes: string[];
  next_action: string;
  owner: string;
  budget_limit: MoneyProjection | null;
  stop_loss_condition: string | null;
  evidence_ids: string[];
  drillthrough: Record<string, string | null>;
  store_category_route?: StoreCategoryRoute;
  input_sha256: string;
  external_write_allowed: false;
};

export type ProfitWorkspace = {
  status: string;
  as_of: string;
  display_currency: string;
  scope: { tenant_ref: string; entity_ref: string; store_ref: string };
  bundle: {
    bundle_id: string;
    counts: { source_total: number; accepted: number; quarantined: number };
    quality: Record<string, unknown>;
  } | null;
  summary: {
    actual_cash_profit: MoneyProjection;
    risk_profit_opportunities: number;
    loss_exposure: MoneyProjection;
    inventory_cash: MoneyProjection;
    highest_value_action: {
      candidate_id: string;
      decision_class: string;
      next_action: string;
      owner: string;
    } | null;
    data_freshness: {
      as_of: string;
      bundle_available: boolean;
      decision_eligible_records: number;
    };
  };
  counts: Record<string, number>;
  candidates: ProfitCandidate[];
  authority_status: Record<string, { status: string; source_gaps: string[] }>;
  source_gaps: string[];
  evidence_ids: string[];
  snapshot_sha256: string;
};

export type ProfitAnalytics = {
  status: string;
  counts: Record<string, number>;
  decision_distribution: DistributionRow[];
  lifecycle_distribution: DistributionRow[];
  route_distribution: DistributionRow[];
  profit_basis_coverage: Record<string, DistributionRow[]>;
  profit_metrics: Record<string, MoneyProjection & {
    included_candidate_count?: number;
    excluded_candidate_count?: number;
  }>;
  cost_state_matrix: Record<string, DistributionRow[]>;
  category_matrix: Array<{
    source_category_id: string;
    product_type_id: string;
    candidate_count: number;
    decision_counts: Record<string, number>;
    route_counts: Record<string, number>;
  }>;
  time_series: {
    status: string;
    points: unknown[];
    reason: string;
    synthetic_points_created: false;
  };
  snapshot_sha256: string;
};

export type CandidateCollection = {
  status: string;
  count: number;
  candidates: ProfitCandidate[];
  pagination: { page_size: number; next_cursor: string | null };
  snapshot_sha256: string;
};

export type OperatingPlan = {
  status: string;
  profile: {
    store_ref: string;
    store_positioning: string;
    assortment_mode: string;
    price_band: string;
    target_regions: string[];
    fulfillment_models: string[];
    planned_growth_channels: string[];
    category_paths: CategoryPath[];
  } | null;
  summary: {
    candidate_count: number;
    route_counts: Record<string, number>;
  };
  category_tree: Array<CategoryPath & {
    candidate_count: number;
    route_counts?: Record<string, number>;
    candidates?: Array<{ candidate_id: string; name: string; route: string }>;
  }>;
  candidates: ProfitCandidate[];
  reason_codes: string[];
  snapshot_sha256: string;
};

export type StoreRoutingMatrix = {
  status: string;
  store_coverage: Array<{
    store_ref: string;
    scope_status: string;
    profile_status: string;
  }>;
  routes: Array<{
    candidate_id: string;
    offer_id: string;
    name: string;
    source_store_ref: string;
    recommended_store_ref: string | null;
    recommended_route: {
      decision: string;
      confidence: string;
      target_category_path: CategoryPath | null;
      category_role: string | null;
      reason_codes: string[];
    } | null;
    cross_store_handoff_required: boolean;
    alternatives: Array<{
      store_ref: string;
      decision: string;
      confidence: string;
    }>;
    external_write_allowed: false;
  }>;
};

export type StoreProfileProposal = {
  contract_id: string;
  status: string;
  truth_status: "proposal_only";
  seller_tier: string;
  quality: {
    confidence: string;
    data_grade: string;
    identity_quality: string;
    variant_quality: string;
    evidence_type_coverage: string[];
    required_evidence_types: string[];
  };
  proposed_profile: Record<string, unknown>;
  category_role_assignments: Array<{
    category_id: string;
    category_name: string;
    role: "primary" | "secondary" | "tertiary" | "derived";
    confidence: string;
    data_grade: string;
    identity_quality: string;
    variant_quality: string;
    evidence_refs: string[];
  }>;
  placement_recommendations: Array<{
    recommendation_id: string;
    source_category_id: string;
    target_store_ref: string;
    target_category_id: string;
    category_role: string;
    eligible: boolean;
    automatic_publish_allowed: false;
    external_write_allowed: false;
  }>;
  reviewer_gates: Array<{ gate: string; status: string }>;
  reason_codes: string[];
  source_gaps: string[];
  source_observation_count: number;
  proposal_sha256: string;
  snapshot_sha256: string;
  control_envelope: {
    proposal_only: true;
    formal_fact: false;
    automatic_publish_allowed: false;
    permit_created: false;
    external_write_allowed: false;
  };
};

export type GrowthChannelCapabilities = {
  contract_id: string;
  status: string;
  channels: Array<{
    channel: "vk" | "telegram" | string;
    operations: string[];
    supports_deep_links: boolean;
    supports_direct_messages: boolean;
    supports_broadcasts: boolean;
    requires_initiated_or_subscribed_message: boolean;
    production_adapter: string;
    dry_run_adapter: boolean;
  }>;
  attribution_funnel: string[];
  optimization_objective: "incremental_cash_cm3";
  snapshot_sha256: string;
  control_envelope: {
    telegram_unsolicited_message_allowed: false;
    reward_confirmed_before_refund_window_and_settlement: false;
    external_write_without_exact_permit: false;
    external_write_allowed: false;
  };
};

export type ProfitLineage = {
  status: string;
  nodes: Array<{ id: string; stage: string; count: number; status: string }>;
  edges: Array<{ source: string; target: string; automatic_promotion: false }>;
  candidate_lineage: Array<{
    candidate_id: string;
    offer_id: string;
    data_stage: string;
    evidence_ids: string[];
    input_sha256: string;
    drillthrough: Record<string, string | null>;
  }>;
  quarantine: {
    count: number;
    quality_endpoint: string | null;
    raw_data_deleted: false;
  };
  snapshot_sha256: string;
};

export type ProfitRemediationItem = {
  remediation_item_id: string;
  status: string;
  severity: string;
  priority_rank: number;
  unblock_impact_score: number;
  source_ref: string;
  source_item_id: string | null;
  candidate_id: string | null;
  sku: string | null;
  error_code: string;
  evidence_requirement: string;
  action: {
    action_code: string;
    instruction: string;
    owner_role: string;
    deadline_class: string;
    automatic_execution_allowed: false;
  };
  estimated_loss_exposure: MoneyProjection;
  value_at_risk: MoneyProjection;
  evidence_ids: string[];
  missing_value_guessed: false;
};

export type ProfitRemediation = {
  contract_id: string;
  status: string;
  as_of: string;
  scope: { tenant_ref: string; entity_ref: string; store_ref: string };
  reconciliation: {
    source_total: number | null;
    accepted: number | null;
    quarantined: number | null;
    conservation_passed: boolean | null;
  };
  summary: {
    source_items: number;
    candidates: number;
    remediation_items: number;
    open: number;
    stale: number;
    blocked: number;
  };
  groups: {
    by_sku: Array<{ key: string; issue_count: number }>;
    by_source: Array<{ key: string; issue_count: number }>;
    by_error_code: Array<{ key: string; issue_count: number }>;
    by_evidence_requirement: Array<{ key: string; issue_count: number }>;
  };
  remediation_queue: ProfitRemediationItem[];
  pagination: {
    page_size: number;
    offset: number;
    previous_offset: number | null;
    next_offset: number | null;
    page_count: number;
    total_count: number;
  };
  drillthrough: Record<string, string | null>;
  snapshot_sha256: string;
  control_envelope: {
    missing_values_guessed: false;
    formal_fact_promoted: false;
    automatic_action_allowed: false;
    external_write_allowed: false;
  };
};

export type ProfitTruthReadiness = {
  contract_id: string;
  status: string;
  as_of: string;
  display_currency: string;
  scope: { tenant_ref: string; entity_ref: string; store_ref: string };
  data_chain: {
    path: string[];
    stage_counts: Record<string, number>;
    source_total: number;
    retained_total: number;
    conservation_passed: boolean;
    raw_data_deleted: false;
  };
  summary: {
    sku_count: number;
    identity_source_count: number;
    finance_operation_count: number;
    finance_entry_proposal_count: number;
    complete_scoped_fx_count: number;
    legacy_unscoped_fx_count: number;
    cost_evidence_request_count: number;
    formal_fact_count: number;
    finance_entry_count: number;
    decision_snapshot_count: number;
    blocker_count: number;
  };
  fx_readiness: {
    status: string;
    complete_scoped_records: Array<Record<string, unknown>>;
    legacy_unscoped_record_count: number;
    legacy_records_decision_eligible: false;
    required_pair: string;
    required_pairs: Array<{
      source_currency: string;
      quote_currency: string;
      status: string;
    }>;
    record_endpoint: string;
  };
  variant_identity: {
    summary: Record<string, number>;
    reconciliation: { conservation_passed: boolean };
    exact_resolutions: Array<{
      resolution_id: string;
      source_refs: string[];
      matched_on: Record<string, string[]>;
      evidence_refs: string[];
    }>;
    candidate_proposals: Array<Record<string, unknown>>;
    quarantine: Array<Record<string, unknown>>;
  };
  finance_allocation: {
    status: string;
    summary: Record<string, number>;
    reconciliation: { count_conservation_passed: boolean };
    operations: Array<{
      operation_id: string | null;
      posting_number: string | null;
      sku: string | null;
      amount_raw: string | null;
      currency: string | null;
      disposition: string;
      reason_codes: string[];
    }>;
  };
  cost_evidence: {
    status: string;
    summary: Record<string, number | Record<string, number>>;
    evidence_request_queue: Array<{
      request_id: string;
      sku: string;
      request_type: string;
      cost_type?: string;
      owner: string;
      required_document: string;
      priority_rank: number;
      blocker_codes: string[];
    }>;
  };
  profit_books: Record<string, {
    status?: string;
    record_count?: number;
    amount?: string | null;
    currency?: string;
  } | boolean>;
  blockers: Array<{
    code: string;
    affected_count: number;
    owner: string;
    missing_value_guessed: false;
  }>;
  drillthrough: Record<string, string | null>;
  snapshot_sha256: string;
};

export type ProfitPortfolio = {
  status: string;
  tenant_ref: string;
  store_coverage: Array<{ store_ref: string; status: string; reason?: string | null }>;
  summary: {
    store_count: number;
    candidate_count: number;
    decision_counts: Record<string, number>;
    actual_cash_profit: MoneyProjection & { stores?: unknown[] };
  };
};
