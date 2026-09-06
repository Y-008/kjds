export type OzonAcceptanceCheckMap = Record<string, boolean>;

export type OzonProductionAcceptance = {
  contract_id: string;
  contract_version: string;
  status: "accepted" | "blocked" | "no_data";
  gate_status: "PASS" | "BLOCKED_EVIDENCE" | "NO_DATA";
  accepted: boolean;
  scope: {
    tenant_ref: string;
    entity_ref: string | null;
    store_ref: string;
    scope_grant_authority_sha256: string | null;
  };
  run: {
    id: string;
    pilot_id: string | null;
    operation: string;
    status: string;
    outcome: string | null;
    response_sha256: string | null;
    response_byte_size: number | null;
    record_count: number | null;
    summary: Record<string, unknown> | null;
    started_at: string | null;
    completed_at: string | null;
    raw_response_evidence_id: string | null;
    raw_response_stored: boolean;
    raw_response_verified: boolean;
    error_code: string | null;
  } | null;
  checks: OzonAcceptanceCheckMap;
  blockers: string[];
  evidence_ids: string[];
  source_contract: Record<string, unknown> | null;
  runtime_identity: {
    platform: string;
    account_ref: string | null;
    adapter: {
      adapter_id: string | null;
      adapter_version: string | null;
      read_only: boolean;
    };
    state: string | null;
    runtime_status: string | null;
    required_capability: string | null;
    capabilities_match: boolean;
    provider_readback_fresh_passed: boolean;
    external_verifier_fresh_passed: boolean;
  } | null;
  next_action: string;
  external_write_allowed: false;
  formal_fact_promotion_allowed: false;
  production_release_allowed: false;
  credential_values_returned: false;
  snapshot_sha256: string;
};

type RecordValue = Record<string, unknown>;

function isRecord(value: unknown): value is RecordValue {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringOrNull(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/i.test(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isSafeRun(value: unknown): boolean {
  if (value === null) return true;
  if (!isRecord(value)) return false;
  if (typeof value.id !== "string" || !value.id.trim()) return false;
  for (const key of ["pilot_id", "operation", "status", "outcome", "response_sha256", "started_at", "completed_at", "raw_response_evidence_id", "error_code"]) {
    if (!isStringOrNull(value[key])) return false;
  }
  for (const key of ["response_byte_size", "record_count"]) {
    if (value[key] !== null && (typeof value[key] !== "number" || !Number.isFinite(value[key]) || value[key] < 0)) return false;
  }
  if (value.summary !== null && !isRecord(value.summary)) return false;
  return typeof value.raw_response_stored === "boolean"
    && typeof value.raw_response_verified === "boolean"
    && (value.response_sha256 === null || isSha256(value.response_sha256));
}

function isRuntimeIdentity(value: unknown): boolean {
  if (value === null) return true;
  if (!isRecord(value)) return false;
  if (value.platform !== "ozon" || !isStringOrNull(value.account_ref)) return false;
  if (!isRecord(value.adapter)) return false;
  if (!isStringOrNull(value.adapter.adapter_id) || !isStringOrNull(value.adapter.adapter_version)) return false;
  return typeof value.adapter.read_only === "boolean"
    && isStringOrNull(value.state)
    && isStringOrNull(value.runtime_status)
    && isStringOrNull(value.required_capability)
    && typeof value.capabilities_match === "boolean"
    && typeof value.provider_readback_fresh_passed === "boolean"
    && typeof value.external_verifier_fresh_passed === "boolean";
}

/** Fail closed on malformed or contradictory server projections. */
export function parseOzonProductionAcceptance(value: unknown): OzonProductionAcceptance {
  if (!isRecord(value)) throw new Error("Ozon 验收响应不是对象");
  if (value.contract_id !== "kjds-ozon-production-acceptance-v1") throw new Error("Ozon 验收 contract_id 不匹配");
  if (value.contract_version !== "1.0.0") throw new Error("Ozon 验收 contract_version 不匹配");
  if (!["accepted", "blocked", "no_data"].includes(String(value.status))) throw new Error("Ozon 验收 status 不合法");
  if (!["PASS", "BLOCKED_EVIDENCE", "NO_DATA"].includes(String(value.gate_status))) throw new Error("Ozon 验收 gate_status 不合法");
  if (typeof value.accepted !== "boolean" || value.accepted !== (value.gate_status === "PASS")) throw new Error("Ozon 验收 accepted 与 gate_status 矛盾");
  if (!isRecord(value.scope) || typeof value.scope.tenant_ref !== "string" || typeof value.scope.store_ref !== "string" || !isStringOrNull(value.scope.entity_ref) || !isStringOrNull(value.scope.scope_grant_authority_sha256)) throw new Error("Ozon 验收 scope 不合法");
  if (value.scope.scope_grant_authority_sha256 !== null && !isSha256(value.scope.scope_grant_authority_sha256)) throw new Error("Ozon 验收 scope authority 不合法");
  if (!isSafeRun(value.run) || !isRecord(value.checks) || Object.values(value.checks).some((item) => typeof item !== "boolean")) throw new Error("Ozon 验收 checks 或 run 不合法");
  if (!isStringArray(value.blockers) || !isStringArray(value.evidence_ids) || typeof value.next_action !== "string" || !isRuntimeIdentity(value.runtime_identity) || (value.source_contract !== null && !isRecord(value.source_contract))) throw new Error("Ozon 验收证据投影不合法");
  for (const key of ["external_write_allowed", "formal_fact_promotion_allowed", "production_release_allowed", "credential_values_returned"] as const) {
    if (value[key] !== false) throw new Error(`Ozon 验收 guardrail ${key} 必须为 false`);
  }
  if (!isSha256(value.snapshot_sha256)) throw new Error("Ozon 验收 snapshot_sha256 不合法");
  return value as OzonProductionAcceptance;
}
