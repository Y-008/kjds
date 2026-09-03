import type {
  OperatingAnalyticsSnapshot,
  OperatingWorkbenchBriefing,
  WebSession,
} from "../dashboard/contracts";

export const BI_ANALYTICS_CONTRACT_ID = "kjds-operating-flow-analytics-v1";
export const BI_BRIEFING_CONTRACT_ID = "kjds-operating-workbench-briefing-v1";

export type ScopedProjectionStatus = "ready" | "partial" | "blocked" | "no_data";
export type BiProjectionStatus =
  | "loading"
  | ScopedProjectionStatus
  | "forbidden"
  | "conflicted"
  | "error";

export type BiScopeQuery = {
  storeRef: string | null;
  asOf: string | null;
};

export type BiScopeParseResult =
  | { ok: true; value: BiScopeQuery }
  | { ok: false; reason: string };

export type ContractValidation<T> =
  | { ok: true; value: T }
  | { ok: false; reason: string };

export type ExpectedBiScope = {
  tenantRef: string;
  storeRef: string;
  asOf: string;
};

export type BiJsonResponse<T = unknown> = {
  ok: boolean;
  status: number;
  json: () => Promise<T>;
};

export type BiJsonRequest = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<BiJsonResponse<unknown>>;

export type BiProjectionSlot<T> = {
  status: BiProjectionStatus;
  data: T | null;
  error: string;
};

export type BiScopeState = {
  status: BiProjectionStatus;
  authorityStatus: ScopedProjectionStatus | null;
  tenantRef: string | null;
  storeRef: string;
  storeRefs: string[];
  asOf: string | null;
  requestAsOf: string | null;
  authoritySha256: string | null;
};

export type BiProjectionRoundResult = {
  scope: BiScopeState;
  analytics: BiProjectionSlot<OperatingAnalyticsSnapshot>;
  workbench: BiProjectionSlot<OperatingWorkbenchBriefing>;
  status: BiProjectionStatus;
  error: string;
  redirectTo: "/login" | "/mfa" | null;
};

export type LoadBiProjectionOptions = {
  search: string;
  request: BiJsonRequest;
  signal?: AbortSignal;
  allowedUrlParams?: readonly string[];
  now?: () => Date;
};

const SCOPED_STATUSES = new Set<ScopedProjectionStatus>([
  "ready",
  "partial",
  "blocked",
  "no_data",
]);

const ANALYTICS_SUMMARY_KEYS = [
  "catalog_items",
  "bound_listings",
  "available_stock",
  "external_image_references",
  "external_video_references",
  "gate_blockers",
  "growth_snapshot_skus",
  "rfq_packages",
  "verified_dispatch_proofs",
  "formal_finance_entries",
  "ready_execution_plans",
] as const;

const ANALYTICS_FALSE_GUARDRAILS = [
  "browser_gate_recalculation",
  "synthetic_business_data_allowed",
  "automatic_product_selection",
  "automatic_supplier_contact",
  "automatic_procurement",
  "automatic_pricing",
  "automatic_listing",
  "automatic_ad_spend",
  "platform_write_allowed",
] as const;

const BRIEFING_FALSE_GUARDRAILS = [
  "automatic_execution",
  "automatic_product_selection",
  "automatic_procurement",
  "automatic_pricing",
  "automatic_listing",
  "platform_write_allowed",
  "third_party_fact_promotion_allowed",
] as const;

export function parseBiScopeSearch(
  search: string,
  allowedExtraParams: readonly string[] = [],
): BiScopeParseResult {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const allowed = new Set(["store_ref", "as_of", ...allowedExtraParams]);

  for (const key of params.keys()) {
    if (!allowed.has(key)) {
      return { ok: false, reason: `不支持的 BI 查询参数：${key}` };
    }
  }
  for (const key of allowed) {
    if (params.getAll(key).length > 1) {
      return { ok: false, reason: `BI 查询参数不可重复：${key}` };
    }
  }

  const storeRef = params.get("store_ref");
  if (storeRef !== null && (!storeRef.trim() || storeRef.length > 160)) {
    return { ok: false, reason: "store_ref 必须是 1 至 160 个字符" };
  }
  const asOf = params.get("as_of");
  if (asOf !== null && !isTimezoneIsoTimestamp(asOf)) {
    return { ok: false, reason: "as_of 必须是包含时区的 ISO-8601 时间" };
  }

  return {
    ok: true,
    value: {
      storeRef: storeRef?.trim() || null,
      asOf,
    },
  };
}

export function buildBiScopeSearch(
  currentSearch: string,
  next: BiScopeQuery,
  allowedExtraParams: readonly string[] = [],
): string {
  const current = new URLSearchParams(
    currentSearch.startsWith("?") ? currentSearch.slice(1) : currentSearch,
  );
  const result = new URLSearchParams();
  if (next.storeRef) result.set("store_ref", next.storeRef);
  if (next.asOf) result.set("as_of", next.asOf);
  for (const key of allowedExtraParams) {
    const values = current.getAll(key);
    if (values.length === 1) result.set(key, values[0]);
  }
  const encoded = result.toString();
  return encoded ? `?${encoded}` : "";
}

export function isTimezoneIsoTimestamp(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}T.+(?:Z|[+-]\d{2}:\d{2})$/.test(value)) return false;
  return Number.isFinite(Date.parse(value));
}

export function createEmptyBiScope(): BiScopeState {
  return {
    status: "loading",
    authorityStatus: null,
    tenantRef: null,
    storeRef: "",
    storeRefs: [],
    asOf: null,
    requestAsOf: null,
    authoritySha256: null,
  };
}

export function createEmptyProjectionSlot<T>(
  status: BiProjectionStatus = "loading",
): BiProjectionSlot<T> {
  return { status, data: null, error: "" };
}

export function createEmptyBiProjectionRound(): BiProjectionRoundResult {
  return {
    scope: createEmptyBiScope(),
    analytics: createEmptyProjectionSlot(),
    workbench: createEmptyProjectionSlot(),
    status: "loading",
    error: "",
    redirectTo: null,
  };
}

export function createBiProjectionFailure(
  status: "blocked" | "forbidden" | "conflicted" | "error",
  error: string,
  scope: BiScopeState = createEmptyBiScope(),
): BiProjectionRoundResult {
  return {
    scope: { ...scope, status },
    analytics: createEmptyProjectionSlot(status),
    workbench: createEmptyProjectionSlot(status),
    status,
    error,
    redirectTo: null,
  };
}

export async function loadBiProjectionRound({
  search,
  signal,
  allowedUrlParams = [],
  request,
  now = () => new Date(),
}: LoadBiProjectionOptions): Promise<BiProjectionRoundResult> {
  let sessionResponse: BiJsonResponse<unknown>;
  try {
    sessionResponse = await request("/auth/session", { cache: "no-store", signal });
  } catch (reason) {
    return createBiProjectionFailure(
      "error",
      errorMessage(reason, "Web 身份服务读取失败"),
    );
  }

  const sessionRedirect = authRedirect(sessionResponse.status);
  if (sessionRedirect) {
    return { ...createEmptyBiProjectionRound(), redirectTo: sessionRedirect };
  }
  if (sessionResponse.status === 403) {
    return createBiProjectionFailure("forbidden", "当前身份无权读取 BI 授权作用域");
  }
  let sessionBody: unknown;
  try {
    sessionBody = await sessionResponse.json();
  } catch (reason) {
    return createBiProjectionFailure(
      "error",
      errorMessage(reason, "Web 身份服务返回了不可解析的响应"),
    );
  }
  if (!sessionResponse.ok) {
    return createBiProjectionFailure(
      "error",
      detailFrom(sessionBody, "Web 身份服务尚未就绪"),
    );
  }
  const sessionValidation = validateWebSession(sessionBody);
  if (!sessionValidation.ok) {
    return createBiProjectionFailure("conflicted", sessionValidation.reason);
  }
  const session = sessionValidation.value;
  const parsed = parseBiScopeSearch(search, allowedUrlParams);
  const sessionScope: BiScopeState = {
    ...createEmptyBiScope(),
    status: "ready",
    tenantRef: session.tenant_ref,
    storeRefs: [...session.store_refs],
  };
  if (!parsed.ok) {
    return createBiProjectionFailure("blocked", parsed.reason, sessionScope);
  }
  if (session.store_refs.length === 0) {
    return createBiProjectionFailure(
      "blocked",
      "当前身份没有授权店铺；BI 不会回退读取 legacy 全局事实。",
      sessionScope,
    );
  }

  const storeRef = parsed.value.storeRef ?? session.default_store_ref ?? session.store_refs[0];
  const scopeWithQuery: BiScopeState = {
    ...sessionScope,
    storeRef,
    asOf: parsed.value.asOf,
  };
  if (!session.store_refs.includes(storeRef)) {
    return createBiProjectionFailure(
      "forbidden",
      `当前身份未获授权访问店铺 ${storeRef}；未发送任何经营数据请求。`,
      { ...scopeWithQuery, status: "forbidden" },
    );
  }

  const cutoff = parsed.value.asOf ?? now().toISOString();
  if (!isTimezoneIsoTimestamp(cutoff)) {
    return createBiProjectionFailure("blocked", "本轮查询 cutoff 不合法", scopeWithQuery);
  }
  const requestedScope: BiScopeState = {
    ...scopeWithQuery,
    requestAsOf: cutoff,
  };
  const params = new URLSearchParams({ store_ref: storeRef, as_of: cutoff });
  const requestInit: RequestInit = { cache: "no-store", signal };
  const responses = await Promise.allSettled([
    request(`/backend/v1/operating-analytics/snapshot?${params.toString()}`, requestInit),
    request(`/backend/v1/operating-workbench/briefing?${params.toString()}`, requestInit),
  ]);

  for (const result of responses) {
    if (result.status === "fulfilled") {
      const redirectTo = authRedirect(result.value.status);
      if (redirectTo) {
        return { ...createEmptyBiProjectionRound(), redirectTo };
      }
    }
  }

  const expected: ExpectedBiScope = {
    tenantRef: session.tenant_ref,
    storeRef,
    asOf: cutoff,
  };
  const analytics = await responseSlot(
    responses[0],
    (body) => validateScopedAnalyticsSnapshot(body, expected),
    "Analytics",
  );
  const workbench = await responseSlot(
    responses[1],
    (body) => validateScopedWorkbenchBriefing(body, expected),
    "Briefing",
  );

  if (analytics.status === "forbidden" || workbench.status === "forbidden") {
    return {
      ...createBiProjectionFailure("forbidden", "服务端拒绝当前 BI 作用域", {
        ...requestedScope,
        status: "forbidden",
      }),
      analytics: createEmptyProjectionSlot("forbidden"),
      workbench: createEmptyProjectionSlot("forbidden"),
    };
  }

  if (analytics.status === "conflicted" || workbench.status === "conflicted") {
    return createBiProjectionFailure(
      "conflicted",
      [analytics.error, workbench.error].filter(Boolean).join("；")
        || "Analytics 与 Briefing 至少有一个作用域合同无法验证；本轮数据已清空。",
      { ...requestedScope, status: "conflicted" },
    );
  }

  if (analytics.data && workbench.data) {
    const analyticsScope = analytics.data.scope;
    const workbenchScope = workbench.data.scope;
    if (
      !analyticsScope
      || !workbenchScope
      || analyticsScope.tenant_ref !== workbenchScope.tenant_ref
      || analyticsScope.store_ref !== workbenchScope.store_ref
      || analyticsScope.entity_ref !== workbenchScope.entity_ref
      || analyticsScope.scope_authority_sha256 !== workbenchScope.scope_authority_sha256
    ) {
      return createBiProjectionFailure(
        "conflicted",
        "Analytics 与 Briefing 的 tenant/entity/store 或 scope authority 不一致；本轮数据已清空。",
        { ...requestedScope, status: "conflicted" },
      );
    }
  }

  const status = combineSlotStatus(analytics, workbench);
  const errors = [analytics.error, workbench.error].filter(Boolean);
  const analyticsScope = analytics.data?.scope;
  const workbenchScope = workbench.data?.scope;
  const workbenchAuthorityStatus = isScopedStatus(workbench.data?.status)
    ? workbench.data.status
    : null;
  return {
    scope: {
      ...requestedScope,
      status: "ready",
      authorityStatus: analyticsScope?.status ?? workbenchAuthorityStatus,
      authoritySha256: (
        analyticsScope?.scope_authority_sha256
        ?? workbenchScope?.scope_authority_sha256
        ?? null
      ),
    },
    analytics,
    workbench,
    status,
    error: errors.join("；"),
    redirectTo: null,
  };
}

export function validateWebSession(value: unknown): ContractValidation<WebSession> {
  if (!isRecord(value) || value.authenticated !== true) {
    return invalid("Web session 未认证");
  }
  if (!isNonEmptyString(value.tenant_ref)) return invalid("Web session 缺少 tenant_ref");
  if (value.auth_mode !== "legacy" && value.auth_mode !== "supabase") {
    return invalid("Web session auth_mode 合同不合法");
  }
  if (!isNonEmptyString(value.actor_id)) return invalid("Web session 缺少 actor_id");
  if (value.email !== null && typeof value.email !== "string") {
    return invalid("Web session email 合同不合法");
  }
  if (!isStringArray(value.store_refs)) return invalid("Web session store_refs 合同不合法");
  if (new Set(value.store_refs).size !== value.store_refs.length) {
    return invalid("Web session store_refs 含重复授权");
  }
  if (value.store_refs.some((store) => !store.trim() || store.length > 160)) {
    return invalid("Web session 含非法 store_ref");
  }
  if (!isNonEmptyString(value.default_store_ref) && value.store_refs.length > 0) {
    return invalid("Web session 缺少 default_store_ref");
  }
  if (
    isNonEmptyString(value.default_store_ref)
    && !value.store_refs.includes(value.default_store_ref)
  ) {
    return invalid("Web session default_store_ref 不在授权集合内");
  }
  if (!isStringArray(value.roles)) return invalid("Web session roles 合同不合法");
  return { ok: true, value: value as WebSession };
}

export function validateScopedAnalyticsSnapshot(
  value: unknown,
  expected: ExpectedBiScope,
): ContractValidation<OperatingAnalyticsSnapshot> {
  if (!isRecord(value)) return invalid("Analytics 响应不是对象");
  if (value.contract_id !== BI_ANALYTICS_CONTRACT_ID) {
    return invalid("Analytics contract_id 不匹配");
  }
  if (!isScopedStatus(value.status)) return invalid("Analytics 不是 scoped 状态合同");
  if (value.store_ref !== expected.storeRef) return invalid("Analytics store_ref 与请求不匹配");
  const scopeCheck = validateResponseScope(value.scope, expected, true);
  if (!scopeCheck.ok) return scopeCheck;
  if (!sameInstant(value.source_as_of, expected.asOf)) {
    return invalid("Analytics source_as_of 与查询 cutoff 不匹配");
  }
  if (!isSha256(value.snapshot_sha256)) return invalid("Analytics snapshot_sha256 不合法");
  if (!isRecord(value.summary)) return invalid("Analytics summary 缺失");
  for (const key of ANALYTICS_SUMMARY_KEYS) {
    if (!isNonNegativeNumber(value.summary[key])) {
      return invalid(`Analytics summary.${key} 不合法`);
    }
  }
  if (!isRecord(value.recommended_playbook)) return invalid("Analytics playbook 缺失");
  if (
    value.recommended_playbook.id !== "scoped_catalog_refinement"
    && value.recommended_playbook.id !== "scoped_authority_foundation"
  ) {
    return invalid("Analytics 受保护页面只接受 scoped playbook");
  }
  if (
    value.recommended_playbook.advisory_only !== true
    || value.recommended_playbook.automatic_mode_switch !== false
  ) {
    return invalid("Analytics playbook 只读 guardrail 不匹配");
  }
  if (
    !isNonEmptyString(value.recommended_playbook.label)
    || !isStringArray(value.recommended_playbook.reasons)
  ) {
    return invalid("Analytics playbook 内容合同不合法");
  }
  if (!validateFocalListing(value.focal_listing)) {
    return invalid("Analytics focal_listing 合同不合法");
  }
  if (!validateStages(value.stages)) return invalid("Analytics stages 合同不合法");
  if (!validateCoverage(value.coverage)) return invalid("Analytics coverage 合同不合法");
  if (!validatePipeline(value.pipeline)) return invalid("Analytics pipeline 合同不合法");
  if (!validateWorkItems(value.priority_items)) {
    return invalid("Analytics priority_items 合同不合法");
  }
  if (!isStringArray(value.data_gaps)) {
    return invalid("Analytics data_gaps 合同不合法");
  }
  if (!isStringArray(value.source_gaps) || !isStringArray(value.excluded_sources)) {
    return invalid("Analytics scoped source 边界缺失");
  }
  const guardrailCheck = validateGuardrails(
    value.guardrails,
    ANALYTICS_FALSE_GUARDRAILS,
  );
  if (!guardrailCheck.ok) return guardrailCheck;
  return { ok: true, value: value as OperatingAnalyticsSnapshot };
}

export function validateScopedWorkbenchBriefing(
  value: unknown,
  expected: ExpectedBiScope,
): ContractValidation<OperatingWorkbenchBriefing> {
  if (!isRecord(value)) return invalid("Briefing 响应不是对象");
  if (value.contract_id !== BI_BRIEFING_CONTRACT_ID) {
    return invalid("Briefing contract_id 不匹配");
  }
  if (value.mode !== "scoped_shadow_advisory") {
    return invalid("Briefing 受保护页面只接受 scoped mode");
  }
  if (!isScopedStatus(value.status)) return invalid("Briefing 不是 scoped 状态合同");
  const scopeCheck = validateResponseScope(value.scope, expected, false);
  if (!scopeCheck.ok) return scopeCheck;
  if (!sameInstant(value.as_of, expected.asOf)) {
    return invalid("Briefing as_of 与查询 cutoff 不匹配");
  }
  if (!isSha256(value.snapshot_sha256)) return invalid("Briefing snapshot_sha256 不合法");
  if (!validateAgents(value.agents)) return invalid("Briefing agents 合同不合法");
  if (!validateWorkItems(value.work_items)) return invalid("Briefing work_items 合同不合法");
  if (!isRecord(value.summary)) return invalid("Briefing summary 缺失");
  for (const key of [
    "gate_blockers",
    "runtime_items",
    "recommendations",
    "visible_items",
    "candidate_count",
    "selection_ready_count",
  ]) {
    if (!isNonNegativeNumber(value.summary[key])) {
      return invalid(`Briefing summary.${key} 不合法`);
    }
  }
  if (!isRecord(value.candidate_portfolio) || !Array.isArray(value.candidate_portfolio.rows)) {
    return invalid("Briefing candidate_portfolio 合同不合法");
  }
  if (!isStringArray(value.source_gaps) || !isStringArray(value.excluded_sources)) {
    return invalid("Briefing scoped source 边界缺失");
  }
  const guardrailCheck = validateGuardrails(
    value.guardrails,
    BRIEFING_FALSE_GUARDRAILS,
  );
  if (!guardrailCheck.ok) return guardrailCheck;
  return { ok: true, value: value as OperatingWorkbenchBriefing };
}

export function isScopedStatus(value: unknown): value is ScopedProjectionStatus {
  return typeof value === "string" && SCOPED_STATUSES.has(value as ScopedProjectionStatus);
}

function validateResponseScope(
  value: unknown,
  expected: ExpectedBiScope,
  requireStatus: boolean,
): ContractValidation<never> | { ok: true } {
  if (!isRecord(value)) return invalid("响应缺少 scoped authority");
  if (value.tenant_ref !== expected.tenantRef) return invalid("响应 tenant_ref 不匹配");
  if (value.store_ref !== expected.storeRef) return invalid("响应 scope.store_ref 不匹配");
  if (value.entity_ref !== null && !isNonEmptyString(value.entity_ref)) {
    return invalid("响应 scope.entity_ref 不合法");
  }
  if (requireStatus && !isScopedStatus(value.status)) {
    return invalid("响应 scope.status 不合法");
  }
  if (
    value.scope_authority_sha256 !== null
    && !isSha256(value.scope_authority_sha256)
  ) {
    return invalid("响应 scope_authority_sha256 不合法");
  }
  return { ok: true };
}

function validateGuardrails(
  value: unknown,
  falseKeys: readonly string[],
): ContractValidation<never> | { ok: true } {
  if (!isRecord(value) || value.advisory_only !== true) {
    return invalid("只读 advisory guardrail 缺失");
  }
  for (const key of falseKeys) {
    if (value[key] !== false) return invalid(`只读 guardrail ${key} 不匹配`);
  }
  return { ok: true };
}

function validateFocalListing(value: unknown): boolean {
  if (value === null) return true;
  if (!isRecord(value)) return false;
  for (const key of ["offer_id", "name", "source_evidence_id", "item_hash"] as const) {
    if (!isNonEmptyString(value[key])) return false;
  }
  for (const key of [
    "video_reference_count",
    "image_reference_count",
    "document_reference_count",
    "approved_media_roles",
    "required_media_roles",
    "supplier_count",
    "complete_profit_scenario_count",
  ] as const) {
    if (!isNonNegativeNumber(value[key])) return false;
  }
  return isStringArray(value.image_references)
    && typeof value.passports_ready === "boolean"
    && value.media_rights_status === "unverified_external_reference";
}

function validateStages(value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  return value.every((item) => {
    if (!isRecord(item)) return false;
    for (const key of ["id", "step", "label", "workspace", "next_action"] as const) {
      if (!isNonEmptyString(item[key])) return false;
    }
    return ["verified", "in_progress", "blocked", "no_data"].includes(String(item.status))
      && isNonNegativeNumber(item.current)
      && isNonNegativeNumber(item.target)
      && isNonNegativeNumber(item.progress_percent)
      && item.progress_percent <= 100
      && isStringArray(item.source_ids)
      && isStringArray(item.facts);
  });
}

function validateCoverage(value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  return value.every((item) => isRecord(item)
    && isNonEmptyString(item.id)
    && isNonEmptyString(item.label)
    && isNonEmptyString(item.unit)
    && isNonNegativeNumber(item.current)
    && isNonNegativeNumber(item.target)
    && isNonNegativeNumber(item.percent)
    && item.percent <= 100);
}

function validatePipeline(value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  return value.every((item) => isRecord(item)
    && isNonEmptyString(item.id)
    && isNonEmptyString(item.label)
    && isNonEmptyString(item.unit)
    && isNonNegativeNumber(item.value));
}

function validateAgents(value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  return value.every((item) => isRecord(item)
    && isNonEmptyString(item.agent_id)
    && isNonEmptyString(item.name)
    && (item.status === "needs_attention" || item.status === "waiting_for_upstream")
    && isNonNegativeNumber(item.work_item_count)
    && isNonEmptyString(item.current_focus)
    && item.automatic_execution === false);
}

function validateWorkItems(value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  return value.every((item) => {
    if (!isRecord(item)) return false;
    for (const key of [
      "id",
      "item_type",
      "source_type",
      "source_id",
      "agent_id",
      "agent_name",
      "title",
      "status",
      "priority",
      "risk",
      "next_action",
    ] as const) {
      if (!isNonEmptyString(item[key])) return false;
    }
    if (
      item.human_required !== true
      || item.automatic_execution !== false
      || item.platform_write_allowed !== false
      || !isStringArray(item.evidence_ids)
    ) {
      return false;
    }
    if (item.gate !== null && typeof item.gate !== "string") return false;
    if (item.progress !== null) {
      if (
        !isRecord(item.progress)
        || !isNonNegativeNumber(item.progress.current)
        || !isNonNegativeNumber(item.progress.target)
      ) return false;
    }
    if (item.due_at !== null && !isTimezoneIsoTimestamp(String(item.due_at))) return false;
    if (item.overdue !== null && typeof item.overdue !== "boolean") return false;
    return item.escalation_level === null || isNonNegativeNumber(item.escalation_level);
  });
}

function sameInstant(value: unknown, expected: string): boolean {
  return typeof value === "string"
    && isTimezoneIsoTimestamp(value)
    && Date.parse(value) === Date.parse(expected);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isNonNegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isSha256(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/i.test(value);
}

async function responseSlot<T>(
  result: PromiseSettledResult<BiJsonResponse<unknown>>,
  validate: (body: unknown) => ContractValidation<T>,
  label: string,
): Promise<BiProjectionSlot<T>> {
  if (result.status === "rejected") {
    return {
      status: "error",
      data: null,
      error: errorMessage(result.reason, `${label} 请求失败`),
    };
  }
  const response = result.value;
  if (response.status === 403) {
    return { status: "forbidden", data: null, error: `${label} 作用域被拒绝` };
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch (reason) {
    return {
      status: "error",
      data: null,
      error: errorMessage(reason, `${label} 返回了不可解析的响应`),
    };
  }
  if (!response.ok) {
    return {
      status: "error",
      data: null,
      error: detailFrom(body, `${label} API ${response.status}`),
    };
  }
  const validation = validate(body);
  if (!validation.ok) {
    return { status: "conflicted", data: null, error: validation.reason };
  }
  const candidate = validation.value as unknown as { status?: unknown };
  const status = isScopedStatus(candidate.status) ? candidate.status : "conflicted";
  return { status, data: validation.value, error: "" };
}

function combineSlotStatus(
  analytics: BiProjectionSlot<OperatingAnalyticsSnapshot>,
  workbench: BiProjectionSlot<OperatingWorkbenchBriefing>,
): BiProjectionStatus {
  const statuses = [analytics.status, workbench.status];
  if (statuses.includes("forbidden")) return "forbidden";
  if (statuses.includes("conflicted")) return "conflicted";
  const dataCount = Number(Boolean(analytics.data)) + Number(Boolean(workbench.data));
  if (dataCount === 0) return "error";
  if (dataCount === 1) return "partial";
  if (analytics.status === workbench.status) return analytics.status;
  return "partial";
}

function authRedirect(status: number): "/login" | "/mfa" | null {
  if (status === 401) return "/login";
  if (status === 428) return "/mfa";
  return null;
}

function detailFrom(value: unknown, fallback: string): string {
  return typeof value === "object"
    && value !== null
    && "detail" in value
    && typeof value.detail === "string"
    ? value.detail
    : fallback;
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback;
}

function invalid(reason: string): { ok: false; reason: string } {
  return { ok: false, reason };
}
