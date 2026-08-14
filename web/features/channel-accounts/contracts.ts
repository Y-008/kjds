import type { ChannelAccountProjectionStatus } from "../../lib/channel-account-state";

export type ChannelAccountState =
  | "ready"
  | "revoked"
  | "expired"
  | "verification_stale"
  | "health_blocked"
  | "rate_limited"
  | "schema_drift"
  | "unknown_outcome"
  | "evidence_blocked";

export type ChannelAccountFilters = {
  platform: string | null;
  account_ref: string | null;
  adapter_id: string | null;
  query: string | null;
  state: ChannelAccountState | null;
};

export type ChannelAccount = {
  platform: string;
  account_ref: string;
  adapter: {
    adapter_id: string;
    adapter_version: string;
    adapter_contract_sha256: string | null;
    authorization_source: string | null;
    official_or_explicitly_authorized: true;
    read_only: true;
  };
  role_ref: string | null;
  subaccount_ref: string | null;
  credential_kind: string | null;
  credential_reference: {
    present: boolean;
    sha256: string | null;
    value_returned: false;
  };
  credential_fingerprint_sha256: string | null;
  capabilities: string[];
  state: ChannelAccountState;
  health: {
    status: string | null;
    rate_limit_state: string | null;
    external_schema_version: string | null;
    readback_outcome: string | null;
    last_verified_at: string | null;
    expires_at: string | null;
  };
  runtime_identity: {
    contract_id: string | null;
    status: string | null;
    managed_store_bound: boolean;
    lease_fresh: boolean;
    fingerprint_match: boolean;
    scope_match: boolean;
    capabilities_match: boolean;
    provider_readback_fresh_passed: boolean;
    external_verifier_fresh_passed: boolean;
    secret_values_returned: false;
  };
  lifecycle: {
    event_count: number;
    latest_event_type: string | null;
    latest_sequence: number | null;
    latest_effective_at: string | null;
  };
  governance: {
    approval_id: string | null;
    permit_evidence_id: string | null;
    readback_evidence_id: string | null;
    kill_switch_evidence_id: string | null;
    compensation_evidence_id: string | null;
  };
  latest_evidence_id: string | null;
  latest_payload_sha256: string | null;
  source_gaps: string[];
  native_implementation_status: "implemented_unverified";
  verified_native: false;
  next: string;
};

export type ChannelAccountWorkspace = {
  contract_id: "kjds-native-exact-scope-channel-account-authority-v1";
  status: ChannelAccountProjectionStatus;
  as_of: string;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    scope_grant_authority_sha256: string | null;
  };
  filters: ChannelAccountFilters;
  counts: Record<string, number>;
  pagination: {
    page_size: number;
    next_cursor: string | null;
    filtered_total: number;
  };
  channel_accounts: ChannelAccount[];
  source_gaps: string[];
  upstream: Record<string, string | null>;
  native_implementation_status: "implemented_unverified";
  verified_native: false;
  agent_artifact: {
    contract_id: "kjds-channel-account-authority-agent-artifact-v1";
    scope: ChannelAccountWorkspace["scope"];
    as_of: string;
    authority: "reauthorization_rotation_and_internal_task_suggestion_only";
    accounts: Array<{
      platform: string;
      account_ref: string;
      state: ChannelAccountState;
      next: string;
    }>;
    artifact_sha256: string;
    reauthorization_allowed: false;
    credential_rotation_allowed: false;
    secret_read_allowed: false;
    scope_expansion_allowed: false;
    authorization_change_allowed: false;
    self_approval_allowed: false;
    permit_issue_allowed: false;
    external_verification_allowed: false;
    customer_contact_allowed: false;
    platform_contact_allowed: false;
    fictional_authority_allowed: false;
    external_write_allowed: false;
  };
  governed_action_contract: {
    production_workflow_status: "mutation_gated";
    policy_mode: "policy_only";
    internal_governance_api_exposed: true;
    provider_mutation_api_exposed: false;
    provider_mutation_enabled: false;
    actions: string[];
    requires: string[];
    projection_grants_permission: false;
    contract_only: true;
  };
  control_envelope: {
    read_only_projection: true;
    upstream_reads: string[];
    client_recalculation_allowed: false;
    append_only_authorization_authority: true;
    tenant_truth_duplicated: false;
    entity_truth_duplicated: false;
    store_truth_duplicated: false;
    secret_reference_returned: false;
    plaintext_secret_stored: false;
    cookie_allowed: false;
    internal_token_allowed: false;
    device_session_allowed: false;
    private_endpoint_allowed: false;
    captcha_bypass_allowed: false;
    access_control_bypass_allowed: false;
    external_write_allowed: false;
  };
  snapshot_sha256: string;
};

export type ChannelAccountFilterDraft = {
  storeRef: string;
  platform: string;
  accountRef: string;
  adapterId: string;
  query: string;
  state: "" | ChannelAccountState;
};

export type ChannelAccountGovernanceCommandType =
  | "submit_evidence"
  | "review_evidence"
  | "request_change_approval"
  | "decide_change_approval"
  | "materialize_internal_plan";

export type ChannelAccountGovernanceTransition = {
  contract_id: "kjds-channel-account-governance-transition-v1";
  transition_id: string;
  command: ChannelAccountGovernanceCommandType;
  from_state: string;
  to_state: string;
  scope: {
    tenant_ref: string;
    entity_ref: string;
    store_ref: string;
    scope_grant_authority_sha256?: string;
  };
  canonical_refs: {
    submission_evidence_id: string | null;
    review_evidence_id: string | null;
    approval_id: string | null;
    execution_plan_id: string | null;
    command_id: null;
    receipt_id: null;
    authorization_event_ref: null;
  };
  input_sha256: string;
  output_sha256: string;
  next_allowed_transitions: ChannelAccountGovernanceCommandType[];
  idempotent: boolean;
  blockers: string[];
  external_write_allowed: false;
  provider_contact_allowed: false;
  runtime_identity_verified: false;
  control_envelope: {
    internal_governance_write: true;
    business_fact_created: false;
    approval_created: boolean;
    permit_created: false;
    credential_created_or_read: false;
    provider_contact_allowed: false;
    external_write_allowed: false;
    agent_may_invoke: false;
  };
};

export type ChannelAccountGovernanceDraft = {
  storeRef: string;
  platform: string;
  accountRef: string;
  changeKind: string;
  capabilities: string;
  effectiveUntil: string;
  submitIdempotencyKey: string;
  submissionEvidenceId: string;
  reviewAccepted: boolean;
  reviewRationale: string;
  reviewedEvidenceId: string;
  approvalId: string;
  decisionApproved: boolean;
  decisionReason: string;
  planIdempotencyKey: string;
};
