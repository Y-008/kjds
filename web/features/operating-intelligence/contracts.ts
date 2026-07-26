export type LedgerRow = {
  order_id: string;
  sku: string | null;
  accounting_date: string;
  currency: string;
  gross_revenue: string;
  scenario_cm3: string | null;
  accrual_contribution: string | null;
  settlement_contribution: string | null;
  cash_contribution: string | null;
  actual_profit: string | null;
  evidence_ids: string[];
  blockers: string[];
  erosion: Record<string, string>;
};

export type ProfitLedger = {
  contract_id: string;
  status: "no_data" | "blocked" | "partial" | "reconciled";
  coverage_ratio: string;
  rows: LedgerRow[];
  unallocated: Array<{
    source_ref: string;
    amount: string;
    currency: string;
    reason: string;
  }>;
  blockers: string[];
  snapshot_sha256: string;
  control_envelope: Record<string, boolean>;
};

export type ProfitErosion = {
  status: ProfitLedger["status"];
  baseline: string;
  result: string;
  conservation_delta: string;
  conserved: boolean;
  items: Array<{ category: string; amount: string }>;
  snapshot_sha256: string;
};

export type Metric = {
  id: string;
  label: string;
  unit: string;
  operator: "lt" | "gt";
  threshold: string;
  baseline: string;
  minimum_sample: number;
  severity: string;
  cooldown_minutes: number;
  owner: string;
  evidence_required: boolean;
  data_status: "ready" | "no_data";
  observation: {
    value: string;
    sample_size: number;
    evidence_ids: string[];
  };
};

export type MetricRegistry = {
  registry_version: string;
  metrics: Metric[];
  snapshot_sha256: string;
};

export type OperatingTask = {
  id: string;
  metric_id: string;
  title: string;
  severity: string;
  owner: string;
  status: string;
  cooldown_until: string;
  evidence_ids: string[];
  snapshot: Record<string, unknown>;
  updated_at: string;
  automatic_business_action: false;
};

export type TaskEvent = {
  id: string;
  sequence: number;
  event_type: string;
  from_status: string;
  to_status: string;
  reason: string;
  evidence_ids: string[];
  actor_id: string;
  occurred_at: string;
};

export type MediaExecution = {
  id: string;
  asset_id: string;
  media_kind: string;
  template_id: string;
  status: string;
  attempt: number;
  input_sha256: string;
  queued_at: string;
  latency_ms: number | null;
  cost: { amount: string; currency: string };
  outputs: Record<string, unknown>;
  error_code: string | null;
};

export type MediaSnapshot = {
  contract_id: string;
  status: "no_data" | "partial" | "ready";
  templates: Array<{
    id: string;
    kind: string;
    version: string;
    status: string;
    executor: string;
    fixed_workflow: boolean;
  }>;
  assets: Array<{
    id: string;
    product_id: string;
    content_type: string;
    status: string;
    brief: Record<string, unknown>;
    qa_results: Array<Record<string, unknown>>;
    generation: Record<string, unknown>;
  }>;
  executions: MediaExecution[];
  manifests: Array<Record<string, unknown>>;
  summary: {
    asset_count: number;
    execution_count: number;
    failed_count: number;
    blocked_count: number;
    manifest_count: number;
  };
  snapshot_sha256: string;
  control_envelope: Record<string, boolean>;
};
