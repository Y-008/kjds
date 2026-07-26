export type CapabilityStatus = "implemented" | "ready" | "gated" | "research_only";

export type CapabilityLeaf = {
  id: string;
  label: string;
  summary: string;
  linkfox: string;
  surpass: string;
  russia: string;
  global: string;
  technology: string;
  inputs: string[];
  outputs: string[];
  status: CapabilityStatus;
  markets: string[];
  platforms: string[];
  controls: string[];
  workspace: string;
};

export type CapabilityDomain = {
  id: string;
  label: string;
  mission: string;
  capabilities: CapabilityLeaf[];
};

export type AtomicPoint = {
  id: string;
  label: string;
  domain_id: string;
  parent_capability_id: string;
  objective: string;
  business_object: string;
  operation_kind: string;
  contract_profile_id: string;
  source_kind: "linkfox_public_C" | "repository_verified" | "product_architecture";
  evidence_tier: "C" | "repository_contract" | "design";
  source_boundary: string;
  status: CapabilityStatus;
  input_contract: string[];
  output_contract: string[];
  technology: string;
  evidence_gate: string;
  failure_modes: string[];
  failure_queue: string;
  readback: string;
  kpi: string[];
  sla: string;
  owner: string;
  reviewer: string;
  markets: string[];
  platforms: string[];
  controls: string[];
  value_stream_ids: string[];
  workspace_id: string;
  workspace: string;
};

export type ValueStream = {
  id: string;
  label: string;
  mission: string;
  stage_point_ids: string[];
  supporting_point_ids: string[];
  object_transitions: string[];
  entry_gate: string;
  exit_gate: string;
  events: string[];
  exceptions: string[];
  human_takeover: string;
  kpi: string[];
  sla: string;
  adapter_boundary: string;
  workspace: string;
};

export type OperatingSurface = {
  id: string;
  label: string;
  mission: string;
  value_stream_ids: string[];
  focus_point_ids: string[];
  dimensions: string[];
  decisions: string[];
  truth_owner: string;
  kpi: string[];
  alerts: string[];
  write_boundary: string;
  workspace: string;
};

export type OperatingGraph = {
  contract_id: "kjds-cross-border-operating-graph-v1";
  model: "point-line-surface";
  model_definition: {
    point: string;
    line: string;
    surface: string;
  };
  source_kinds: Record<
    AtomicPoint["source_kind"],
    { evidence_tier: string; boundary: string }
  >;
  contract_profiles: Record<
    string,
    {
      operation_kind: string;
      input_contract: string[];
      output_contract: string[];
      technology: string;
      evidence_gate: string;
      failure_modes: string[];
      failure_queue: string;
      readback: string;
      kpi: string[];
      sla: string;
      controls: string[];
    }
  >;
  atomic_points: AtomicPoint[];
  value_streams: ValueStream[];
  operating_surfaces: OperatingSurface[];
};

export type CapabilityAtlasSnapshot = {
  contract_id: "kjds-cross-border-capability-atlas-v1";
  release_version: string;
  registry_version: string;
  last_reviewed: string;
  primary_market: "RU";
  primary_platform: "ozon";
  source_policy: {
    linkfox_evidence_tier: "C";
    integration_status: "public_workflow_reference_only";
    observed_urls: string[];
    boundary: string;
  };
  status_definitions: Record<CapabilityStatus, string>;
  technology_principles: string[];
  counts: {
    domains: number;
    capabilities: number;
    atomic_points: number;
    value_streams: number;
    operating_surfaces: number;
    statuses: Record<CapabilityStatus, number>;
    markets: Record<string, number>;
    platforms: Record<string, number>;
    linkfox_reference: {
      observed: number;
      not_observed: number;
    };
    atomic_point_statuses: Record<CapabilityStatus, number>;
    atomic_point_sources: Record<string, number>;
    contract_profiles: Record<string, number>;
  };
  domains: CapabilityDomain[];
  operating_graph: OperatingGraph;
  registry_sha256: string;
  control_envelope: {
    read_only: true;
    marketing_claims_are_business_facts: false;
    linkfox_ozon_integration_verified: false;
    client_can_promote_status: false;
    external_write_allowed: false;
    operating_graph_is_execution_authority: false;
    expansion_rule: string;
  };
};
