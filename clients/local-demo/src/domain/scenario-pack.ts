import { createHash } from "node:crypto";

import {
  DEMO_MARKERS,
  FORBIDDEN_SCOPE_KEYS,
  LocalDemoDomainError,
  type JsonValue,
  type ScenarioPack,
  type ScenarioPackContent,
} from "./contracts.ts";

const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const SYNTHETIC_ID_PATTERN = /^demo-[a-z0-9][a-z0-9._-]*$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function assertJsonValue(value: unknown, path: string): asserts value is JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new LocalDemoDomainError("demo_scenario_non_finite_number", 400);
    }
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertJsonValue(item, `${path}[${index}]`));
    return;
  }
  if (isRecord(value)) {
    for (const [key, child] of Object.entries(value)) {
      assertJsonValue(child, `${path}.${key}`);
    }
    return;
  }
  throw new LocalDemoDomainError(`demo_scenario_non_json_value:${path}`, 400);
}

export function canonicalJson(value: JsonValue): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  }
  const keys = Object.keys(value).sort();
  return `{${keys
    .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key] as JsonValue)}`)
    .join(",")}}`;
}

export function sha256Hex(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

export function computeScenarioSha256(raw: unknown): string {
  if (!isRecord(raw)) {
    throw new LocalDemoDomainError("demo_scenario_invalid", 400);
  }
  const content = { ...raw };
  delete content.scenario_sha256;
  assertJsonValue(content, "scenario");
  return sha256Hex(canonicalJson(content));
}

function assertSyntheticIdentifiers(value: unknown, path = "scenario"): void {
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertSyntheticIdentifiers(item, `${path}[${index}]`));
    return;
  }
  if (!isRecord(value)) {
    return;
  }
  for (const [key, child] of Object.entries(value)) {
    if (FORBIDDEN_SCOPE_KEYS.includes(key as (typeof FORBIDDEN_SCOPE_KEYS)[number])) {
      throw new LocalDemoDomainError("demo_scope_override_rejected", 400);
    }
    if ((key.endsWith("_id") || key === "subject_ref") && typeof child === "string") {
      if (!SYNTHETIC_ID_PATTERN.test(child)) {
        throw new LocalDemoDomainError(
          `demo_non_synthetic_identity:${path}.${key}`,
          400,
        );
      }
    }
    assertSyntheticIdentifiers(child, `${path}.${key}`);
  }
}

function assertScenarioShape(raw: Record<string, unknown>): asserts raw is Record<
  string,
  unknown
> &
  ScenarioPack {
  if (
    typeof raw.scenario_ref !== "string" ||
    raw.scenario_ref.length === 0 ||
    typeof raw.scenario_version !== "string" ||
    raw.scenario_version.length === 0 ||
    raw.locale !== "zh-CN" ||
    typeof raw.scenario_sha256 !== "string" ||
    !SHA256_PATTERN.test(raw.scenario_sha256)
  ) {
    throw new LocalDemoDomainError("demo_scenario_invalid", 400);
  }
  if (!isRecord(raw.deterministic_clock)) {
    throw new LocalDemoDomainError("demo_scenario_clock_invalid", 400);
  }
  const epoch = raw.deterministic_clock.epoch;
  const tickMs = raw.deterministic_clock.tick_ms;
  if (
    typeof epoch !== "string" ||
    !Number.isFinite(Date.parse(epoch)) ||
    !Number.isSafeInteger(tickMs) ||
    (tickMs as number) <= 0
  ) {
    throw new LocalDemoDomainError("demo_scenario_clock_invalid", 400);
  }
  if (!isRecord(raw.synthetic_declaration)) {
    throw new LocalDemoDomainError("demo_synthetic_declaration_invalid", 400);
  }
  for (const [key, expected] of Object.entries(DEMO_MARKERS)) {
    if (raw.synthetic_declaration[key] !== expected) {
      throw new LocalDemoDomainError("demo_synthetic_declaration_invalid", 400);
    }
  }
  if (!isRecord(raw.workspace_projections)) {
    throw new LocalDemoDomainError("demo_workspace_projections_invalid", 400);
  }
  const projections = raw.workspace_projections;
  if (
    !Array.isArray(projections.stores) ||
    !Array.isArray(projections.skus) ||
    !Array.isArray(projections.orders) ||
    !isRecord(projections.summary)
  ) {
    throw new LocalDemoDomainError("demo_workspace_projections_invalid", 400);
  }
  if (
    projections.stores.length !== projections.summary.scenario_stores ||
    projections.skus.length !== projections.summary.scenario_skus ||
    projections.orders.length !== projections.summary.scenario_orders
  ) {
    throw new LocalDemoDomainError("demo_scenario_count_mismatch", 400);
  }
  if (
    !Number.isSafeInteger(projections.summary.demo_capacity) ||
    (projections.summary.demo_capacity as number) <= 0
  ) {
    throw new LocalDemoDomainError("demo_scenario_capacity_invalid", 400);
  }
  const storeIds = new Set<string>();
  for (const store of projections.stores) {
    if (!isRecord(store) || typeof store.store_id !== "string" || storeIds.has(store.store_id)) {
      throw new LocalDemoDomainError("demo_scenario_identity_duplicate", 400);
    }
    storeIds.add(store.store_id);
  }
  const skuStoreIds = new Map<string, string>();
  for (const sku of projections.skus) {
    if (
      !isRecord(sku) ||
      typeof sku.sku_id !== "string" ||
      typeof sku.store_id !== "string" ||
      skuStoreIds.has(sku.sku_id)
    ) {
      throw new LocalDemoDomainError("demo_scenario_identity_duplicate", 400);
    }
    if (!storeIds.has(sku.store_id)) {
      throw new LocalDemoDomainError("demo_scenario_reference_invalid", 400);
    }
    skuStoreIds.set(sku.sku_id, sku.store_id);
  }
  const orderIds = new Set<string>();
  for (const order of projections.orders) {
    if (
      !isRecord(order) ||
      typeof order.order_id !== "string" ||
      typeof order.store_id !== "string" ||
      typeof order.sku_id !== "string" ||
      orderIds.has(order.order_id)
    ) {
      throw new LocalDemoDomainError("demo_scenario_identity_duplicate", 400);
    }
    if (
      skuStoreIds.get(order.sku_id) !== order.store_id ||
      !Number.isSafeInteger(order.quantity) ||
      (order.quantity as number) <= 0 ||
      !Number.isSafeInteger(order.synthetic_revenue_minor) ||
      (order.synthetic_revenue_minor as number) < 0
    ) {
      throw new LocalDemoDomainError("demo_scenario_reference_invalid", 400);
    }
    orderIds.add(order.order_id);
  }
}

function deepFreeze<T>(value: T): T {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) {
    return value;
  }
  Object.freeze(value);
  for (const child of Object.values(value)) {
    deepFreeze(child);
  }
  return value;
}

export function loadScenarioPack(raw: unknown): ScenarioPack {
  if (!isRecord(raw)) {
    throw new LocalDemoDomainError("demo_scenario_invalid", 400);
  }
  assertJsonValue(raw, "scenario");
  assertSyntheticIdentifiers(raw);
  assertScenarioShape(raw);
  const actualSha256 = computeScenarioSha256(raw);
  if (actualSha256 !== raw.scenario_sha256) {
    throw new LocalDemoDomainError("demo_scenario_hash_mismatch", 409);
  }
  return deepFreeze(structuredClone(raw) as unknown as ScenarioPack);
}

export function deterministicTimestamp(pack: ScenarioPackContent, tick: number): string {
  if (!Number.isSafeInteger(tick) || tick < 0) {
    throw new LocalDemoDomainError("demo_clock_tick_invalid", 400);
  }
  const epochMs = Date.parse(pack.deterministic_clock.epoch);
  return new Date(epochMs + tick * pack.deterministic_clock.tick_ms).toISOString();
}

export class ScenarioPackCatalog {
  readonly #packs = new Map<string, ScenarioPack>();

  register(raw: unknown): ScenarioPack {
    const candidate = loadScenarioPack(raw);
    const key = `${candidate.scenario_ref}\u0000${candidate.scenario_version}`;
    const current = this.#packs.get(key);
    if (current && current.scenario_sha256 !== candidate.scenario_sha256) {
      throw new LocalDemoDomainError("demo_scenario_hash_drift", 409);
    }
    if (current) {
      return current;
    }
    this.#packs.set(key, candidate);
    return candidate;
  }

  get(scenarioRef: string, scenarioVersion: string): ScenarioPack | undefined {
    return this.#packs.get(`${scenarioRef}\u0000${scenarioVersion}`);
  }
}
