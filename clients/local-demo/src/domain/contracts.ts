export const DEMO_CONTRACT_VERSION = "local-demo-gateway/1.0.0" as const;

export const DEMO_MARKERS = Object.freeze({
  demo: true,
  synthetic: true,
  non_billable: true,
  external_side_effect_allowed: false,
});

export const FORBIDDEN_SCOPE_KEYS = Object.freeze([
  "tenant_ref",
  "entity_ref",
  "store_ref",
  "principal_ref",
  "entitlement_ref",
  "quota_ledger_ref",
  "approval_ref",
  "permit_ref",
  "api_key",
  "cookie",
  "oauth_token",
]);

export type JsonPrimitive = boolean | number | string | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };

export type DemoWorkspace =
  | "dashboard"
  | "sourcing"
  | "pim"
  | "listings"
  | "oms"
  | "fulfillment"
  | "customer_service"
  | "growth"
  | "profit";

export interface DemoStoreProjection {
  readonly store_id: string;
  readonly display_name: string;
  readonly market: string;
  readonly category: string;
  readonly connection_label: "场景店铺已连接";
}

export interface DemoSkuProjection {
  readonly sku_id: string;
  readonly store_id: string;
  readonly title: string;
  readonly category: string;
  readonly stock_units: number;
  readonly listing_state: "draft" | "preview_ready" | "simulated_active";
}

export interface DemoOrderProjection {
  readonly order_id: string;
  readonly store_id: string;
  readonly sku_id: string;
  readonly quantity: number;
  readonly synthetic_revenue_minor: number;
  readonly currency: "RUB";
  readonly state: "awaiting_packaging" | "in_fulfillment" | "simulated_delivered";
}

export interface ScenarioWorkspaceProjections {
  readonly stores: readonly DemoStoreProjection[];
  readonly skus: readonly DemoSkuProjection[];
  readonly orders: readonly DemoOrderProjection[];
  readonly summary: {
    readonly scenario_stores: number;
    readonly scenario_skus: number;
    readonly scenario_orders: number;
    readonly demo_capacity: number;
  };
}

export interface ScenarioPackContent {
  readonly scenario_ref: string;
  readonly scenario_version: string;
  readonly locale: "zh-CN";
  readonly deterministic_clock: {
    readonly epoch: string;
    readonly tick_ms: number;
  };
  readonly synthetic_declaration: typeof DEMO_MARKERS;
  readonly workspace_projections: ScenarioWorkspaceProjections;
}

export interface ScenarioPack extends ScenarioPackContent {
  readonly scenario_sha256: string;
}

export interface DemoTransition {
  readonly transition_id: string;
  readonly sequence: number;
  readonly workspace: DemoWorkspace;
  readonly action: string;
  readonly subject_ref: string;
  readonly canonical_payload_sha256: string;
  readonly previous_state_sha256: string;
  readonly state_sha256: string;
  readonly occurred_at: string;
  readonly network_invoked: false;
  readonly external_side_effect_allowed: false;
}

export interface DemoSessionSnapshot {
  readonly session_id: string;
  readonly scenario_ref: string;
  readonly scenario_version: string;
  readonly scenario_sha256: string;
  readonly opened_at: string;
  readonly expires_at: string;
  readonly ttl_minutes: 60;
  readonly sequence: number;
  readonly state_sha256: string;
  readonly transition_log: readonly DemoTransition[];
  readonly demo: true;
  readonly synthetic: true;
  readonly non_billable: true;
  readonly external_side_effect_allowed: false;
  readonly real_principal_ref: null;
  readonly real_entitlement_ref: null;
  readonly real_quota_ledger_ref: null;
  readonly real_approval_ref: null;
  readonly real_permit_ref: null;
}

export class LocalDemoDomainError extends Error {
  readonly code: string;
  readonly http_status: number;

  constructor(code: string, httpStatus: number) {
    super(code);
    this.name = "LocalDemoDomainError";
    this.code = code;
    this.http_status = httpStatus;
  }
}
