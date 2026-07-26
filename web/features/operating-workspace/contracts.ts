export type ContractStatus = "implemented" | "ready" | "gated" | "research_only";
export type RuntimeStatus =
  | "verified"
  | "in_progress"
  | "blocked"
  | "no_data"
  | "contract_only";

export type OperatingWorkspaceStage = {
  sequence: number;
  id: string;
  label: string;
  objective: string;
  business_object: string;
  operation_kind: string;
  contract_status: ContractStatus;
  runtime_status: RuntimeStatus;
  runtime_scope: string;
  facts: string[];
  evidence_ids: string[];
  current: number | string | null;
  target: number | string | null;
  progress_percent: number | null;
  next_action: string;
  input_contract: string[];
  output_contract: string[];
  evidence_gate: string;
  failure_queue: string;
  failure_modes: string[];
  readback: string;
  owner: string;
  reviewer: string;
  kpi: string[];
  sla: string;
  workspace_href: string;
  workspace_id: string;
  domain_href: string;
};

export type RuntimeSignal = {
  id: string;
  step: string;
  label: string;
  workspace: string;
  status: Exclude<RuntimeStatus, "contract_only">;
  current: number | string | null;
  target: number | string | null;
  progress_percent: number;
  facts: string[];
  source_ids: string[];
  next_action: string;
};

export type WorkspaceLink = {
  id: string;
  label: string;
  href: string;
};

export type OperatingWorkspaceSnapshot = {
  contract_id: "kjds-cross-border-operating-workspace-v1";
  kind: "points" | "lines" | "surfaces";
  item_id: string;
  store_ref: string;
  title: string;
  mission: string;
  release_version: string;
  registry_version: string;
  registry_sha256: string;
  source_as_of: string | null;
  context: Record<string, unknown> & {
    type: "point" | "line" | "surface";
    business_object?: string;
    operation_kind?: string;
    contract_status?: ContractStatus;
    source_kind?: string;
    evidence_tier?: string;
    source_boundary?: string;
    technology?: string;
    controls?: string[];
    markets?: string[];
    platforms?: string[];
    entry_gate?: string;
    exit_gate?: string;
    object_transitions?: string[];
    events?: string[];
    exceptions?: string[];
    human_takeover?: string;
    kpi?: string[];
    sla?: string;
    adapter_boundary?: string;
    dimensions?: string[];
    decisions?: string[];
    truth_owner?: string;
    alerts?: string[];
    write_boundary?: string;
  };
  stages: OperatingWorkspaceStage[];
  domain_signals: RuntimeSignal[];
  live: {
    status: string;
    summary: Record<string, number | string | null>;
    focal_listing: Record<string, unknown> | null;
    priority_items: Array<Record<string, unknown>>;
    data_gaps: string[];
    analytics_snapshot_sha256: string | null;
  };
  counts: {
    stages: number;
    related_points: number;
    related_lines: number;
    related_surfaces: number;
    domain_signals: number;
    contract_statuses: Record<string, number>;
    runtime_statuses: Record<string, number>;
  };
  actions: Array<{
    id: string;
    kind: "navigate";
    label: string;
    workspace_id: string;
    href: string;
    external_write: false;
    requires_human_for_side_effects: true;
  }>;
  navigation: {
    atlas_href: string;
    self_href: string;
    related_points: WorkspaceLink[];
    related_lines: WorkspaceLink[];
    related_surfaces: WorkspaceLink[];
  };
  control_envelope: {
    read_only: true;
    external_write_allowed: false;
    client_can_recalculate_runtime_status: false;
    contract_status_is_runtime_fact: false;
    missing_data_must_remain_visible: true;
    linkfox_is_workflow_reference_only: true;
  };
  workspace_sha256: string;
};
