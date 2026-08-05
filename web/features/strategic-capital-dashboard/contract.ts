export const DASHBOARD_SECTION_ORDER = [
  "primary_source_coverage",
  "strategic_benchmark",
  "strategic_gaps",
  "opportunity_portfolio",
  "experiment_portfolio",
  "capital_proposals",
  "verified_outcomes",
  "invalidation_review",
] as const;

export type SectionId = (typeof DASHBOARD_SECTION_ORDER)[number];
export type DashboardStatus =
  | "ready"
  | "partial"
  | "no_data"
  | "not_connected"
  | "stale"
  | "invalidated"
  | "UNKNOWN";

export type DashboardSection = {
  section_id: SectionId;
  display_order: number;
  scope_binding_sha256: string;
  source_contract_id: string;
  source_contract_version: string;
  source_contract_sha256: string;
  status: DashboardStatus;
  reason_codes: string[];
  projection_ref: string | null;
  projection_sha256: string | null;
  data_as_of: string | null;
  recorded_at: string | null;
  effective_at: string | null;
  review_due_at: string | null;
  citations: Array<{ token: string; summary_sha256: string }>;
  display_items: Array<{
    item_ref: string;
    label: string;
    display_text: string;
  }>;
  invalidation_conditions: string[];
  global_top1_claim: false;
  production_admission: false;
  actionable_proposal: false;
};

export type StrategicCapitalDashboardProjection = {
  contract_id: "kjds-strategic-capital-dashboard-v1";
  contract_version: "1.0.0";
  registry_content_sha256: string;
  dashboard_ref: string;
  scope_binding_sha256: string;
  store_ref: string;
  data_as_of: string;
  authority_checked_at: string;
  overall_state: DashboardStatus;
  reason_codes: string[];
  sections: DashboardSection[];
  global_top1_claim: false;
  production_admission: false;
  budget_authority: false;
  observation_sha256: string;
  side_effects: Record<string, 0>;
};

const SHA256 = /^[0-9a-f]{64}$/;
const CITATION_TOKEN = /^(?:sbc|psc|gdc|gapc|capc|expc|outc|invc)_[A-Za-z0-9_-]{16,256}$/;
const AVAILABLE = new Set<DashboardStatus>([
  "ready",
  "partial",
  "stale",
  "invalidated",
]);
const STATUSES = new Set<DashboardStatus>([
  ...AVAILABLE,
  "no_data",
  "not_connected",
  "UNKNOWN",
]);
const OVERALL_STATUSES = new Set<DashboardStatus>([
  "ready",
  "partial",
  "no_data",
  "stale",
  "invalidated",
  "UNKNOWN",
]);
const SIDE_EFFECT_KEYS = [
  "evidence_writes",
  "fact_writes",
  "finance_entry_writes",
  "graph_writes",
  "approval_writes",
  "permit_writes",
  "pilot_writes",
  "outbox_writes",
  "external_writes",
  "network_writes",
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const keys = Object.keys(value);
  return keys.length === expected.length && expected.every((key) => Object.hasOwn(value, key));
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isSection(
  value: unknown,
  sectionId: SectionId,
  displayOrder: number,
  scopeBindingSha256: string,
): value is DashboardSection {
  if (!isRecord(value)) return false;
  const expectedKeys = [
    "section_id", "display_order", "scope_binding_sha256", "source_contract_id",
    "source_contract_version", "source_contract_sha256", "status", "reason_codes",
    "projection_ref", "projection_sha256", "data_as_of", "recorded_at", "effective_at",
    "review_due_at", "citations", "display_items", "invalidation_conditions",
    "global_top1_claim", "production_admission", "actionable_proposal",
  ];
  if (!hasExactKeys(value, expectedKeys)) return false;
  if (
    value.section_id !== sectionId || value.display_order !== displayOrder ||
    typeof value.status !== "string" || !STATUSES.has(value.status as DashboardStatus) ||
    value.scope_binding_sha256 !== scopeBindingSha256 ||
    typeof value.source_contract_id !== "string" ||
    typeof value.source_contract_version !== "string" ||
    typeof value.source_contract_sha256 !== "string" || !SHA256.test(value.source_contract_sha256) ||
    !isStringArray(value.reason_codes) || !isStringArray(value.invalidation_conditions) ||
    value.global_top1_claim !== false || value.production_admission !== false ||
    value.actionable_proposal !== false
  ) return false;
  if (!Array.isArray(value.citations) || !value.citations.every((citation) =>
    isRecord(citation) && hasExactKeys(citation, ["token", "summary_sha256"]) &&
    typeof citation.token === "string" && CITATION_TOKEN.test(citation.token) &&
    typeof citation.summary_sha256 === "string" &&
    SHA256.test(citation.summary_sha256)
  )) return false;
  if (!Array.isArray(value.display_items) || !value.display_items.every((item) =>
    isRecord(item) && hasExactKeys(item, ["item_ref", "label", "display_text"]) &&
    typeof item.item_ref === "string" && typeof item.label === "string" &&
    typeof item.display_text === "string"
  )) return false;
  const temporalFields = ["data_as_of", "recorded_at", "effective_at", "review_due_at"] as const;
  if (AVAILABLE.has(value.status as DashboardStatus)) {
    const terminallyUnavailable = value.status === "stale" || value.status === "invalidated";
    return value.reason_codes.length > 0 && value.citations.length > 0 &&
      value.invalidation_conditions.length > 0 &&
      (terminallyUnavailable ? value.display_items.length === 0 : value.display_items.length > 0) &&
      typeof value.projection_ref === "string" &&
      typeof value.projection_sha256 === "string" && SHA256.test(value.projection_sha256) &&
      temporalFields.every((field) => typeof value[field] === "string");
  }
  return value.projection_ref === null && value.projection_sha256 === null &&
    temporalFields.every((field) => value[field] === null) &&
    value.reason_codes.length > 0 &&
    value.citations.length === 0 && value.display_items.length === 0 &&
    value.invalidation_conditions.length === 0;
}

export function isStrategicCapitalDashboardProjection(
  value: unknown,
  expectedStoreRef: string,
): value is StrategicCapitalDashboardProjection {
  if (!isRecord(value)) return false;
  const expectedKeys = [
    "contract_id", "contract_version", "registry_content_sha256", "dashboard_ref",
    "scope_binding_sha256", "store_ref", "data_as_of", "authority_checked_at",
    "overall_state", "reason_codes", "sections", "global_top1_claim",
    "production_admission", "budget_authority", "side_effects", "observation_sha256",
  ];
  if (!hasExactKeys(value, expectedKeys)) return false;
  if (
    value.contract_id !== "kjds-strategic-capital-dashboard-v1" ||
    value.contract_version !== "1.0.0" || value.store_ref !== expectedStoreRef ||
    typeof value.registry_content_sha256 !== "string" || !SHA256.test(value.registry_content_sha256) ||
    typeof value.scope_binding_sha256 !== "string" || !SHA256.test(value.scope_binding_sha256) ||
    typeof value.observation_sha256 !== "string" || !SHA256.test(value.observation_sha256) ||
    typeof value.dashboard_ref !== "string" || typeof value.data_as_of !== "string" ||
    typeof value.authority_checked_at !== "string" || typeof value.overall_state !== "string" ||
    !OVERALL_STATUSES.has(value.overall_state as DashboardStatus) || !isStringArray(value.reason_codes) ||
    value.global_top1_claim !== false || value.production_admission !== false ||
    value.budget_authority !== false
  ) return false;
  if (!Array.isArray(value.sections) || value.sections.length !== DASHBOARD_SECTION_ORDER.length) {
    return false;
  }
  if (!value.sections.every((section, index) =>
    isSection(
      section,
      DASHBOARD_SECTION_ORDER[index],
      index,
      value.scope_binding_sha256 as string,
    )
  )) return false;
  const sideEffects = value.side_effects;
  if (!isRecord(sideEffects) || !hasExactKeys(sideEffects, SIDE_EFFECT_KEYS)) {
    return false;
  }
  return SIDE_EFFECT_KEYS.every((key) => sideEffects[key] === 0);
}
