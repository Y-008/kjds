export type AcceptanceState =
  | "mapped"
  | "implemented_unverified"
  | "gated"
  | "verified_native"
  | "blocked"
  | "stale";

export type AcceptanceRecord = {
  record_id: string;
  dimension:
    | "code"
    | "migration"
    | "api_openapi"
    | "web"
    | "permission_write_path"
    | "runtime_replay"
    | "immutable_evidence"
    | "external_graph_verifier";
  status: "passed" | "failed";
  verifier_id: string;
  verifier_kind: string;
  artifact_ref?: string;
  evidence_ref?: string;
  expires_at: string;
  record_sha256: string;
};

export type AcceptanceItem = {
  scope: {
    provider_id: string;
    capability_id: string;
    capability_version: string;
  };
  state: AcceptanceState;
  status: "ready" | "no_data";
  verified_native: boolean;
  counts: Record<string, number>;
  missing_dimensions: string[];
  stale_dimensions: string[];
  failed_dimensions: string[];
  records: AcceptanceRecord[];
  invalid_records: Array<{ record_id: string; reason: string }>;
  source_gaps: string[];
  acceptance_artifact: {
    schema_version: string;
    input_sha256: string;
    artifact_sha256: string;
    blockers: string[];
  };
  snapshot_sha256: string;
};

export type NativeParityWorkspace = {
  contract_id: "native-parity-acceptance-workspace.v1";
  status: "ready" | "no_data";
  as_of: string;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    authority_sha256: string | null;
  };
  filters: {
    provider_id: string | null;
    capability_id: string | null;
    capability_version: string | null;
    status: AcceptanceState | null;
  };
  counts: {
    items: number;
    states: Record<AcceptanceState, number>;
  };
  provider_counts: Record<string, number>;
  capability_counts: Record<string, number>;
  items: AcceptanceItem[];
  next_cursor: string | null;
  source_gaps?: string[];
  snapshot_sha256: string;
  control_envelope: {
    read_only: true;
    client_can_recalculate_or_promote: false;
    self_certification_allowed: false;
    external_write_allowed: false;
  };
};
