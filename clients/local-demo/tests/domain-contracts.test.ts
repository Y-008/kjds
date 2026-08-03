import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  DEMO_MARKERS,
  LocalDemoDomainError,
  type JsonValue,
} from "../src/domain/contracts.ts";
import { DemoSession } from "../src/domain/demo-session.ts";
import {
  ScenarioPackCatalog,
  computeScenarioSha256,
  deterministicTimestamp,
  loadScenarioPack,
} from "../src/domain/scenario-pack.ts";

const FIXTURE_URL = new URL(
  "../src/scenarios/enterprise-overview.zh-CN.v1.json",
  import.meta.url,
);

function rawScenario(): Record<string, JsonValue> {
  return JSON.parse(readFileSync(FIXTURE_URL, "utf8")) as Record<string, JsonValue>;
}

function expectDomainError(
  operation: () => unknown,
  code: string,
  status: number,
): void {
  assert.throws(operation, (error: unknown) => {
    assert.ok(error instanceof LocalDemoDomainError);
    assert.equal(error.code, code);
    assert.equal(error.http_status, status);
    return true;
  });
}

test("scenario pack is content-addressed, deeply immutable and visibly synthetic", () => {
  const raw = rawScenario();
  const pack = loadScenarioPack(raw);

  assert.equal(pack.scenario_sha256, computeScenarioSha256(raw));
  assert.deepEqual(pack.synthetic_declaration, DEMO_MARKERS);
  assert.ok(Object.isFrozen(pack));
  assert.ok(Object.isFrozen(pack.workspace_projections));
  assert.ok(Object.isFrozen(pack.workspace_projections.skus));
  assert.equal(pack.workspace_projections.stores.length, 3);
  assert.equal(pack.workspace_projections.skus.length, 48);
  assert.equal(pack.workspace_projections.orders.length, 36);
  assert.equal(pack.workspace_projections.summary.demo_capacity, 500);
});

test("scenario tampering is rejected before a session exists", () => {
  const raw = rawScenario();
  const projections = raw.workspace_projections as Record<string, JsonValue>;
  const stores = projections.stores as Array<Record<string, JsonValue>>;
  stores[0] = { ...stores[0], display_name: "tampered" };

  expectDomainError(() => loadScenarioPack(raw), "demo_scenario_hash_mismatch", 409);
});

test("catalog is idempotent for the same pack and rejects same identity hash drift", () => {
  const catalog = new ScenarioPackCatalog();
  const first = catalog.register(rawScenario());
  const replay = catalog.register(rawScenario());
  assert.equal(replay, first);

  const drift = rawScenario();
  const projections = drift.workspace_projections as Record<string, JsonValue>;
  const stores = projections.stores as Array<Record<string, JsonValue>>;
  stores[0] = { ...stores[0], display_name: "演示店铺 Delta" };
  drift.scenario_sha256 = computeScenarioSha256(drift);
  expectDomainError(() => catalog.register(drift), "demo_scenario_hash_drift", 409);
});

test("forbidden production scope and non-demo identities fail closed", () => {
  const forbidden = rawScenario();
  forbidden.tenant_ref = "demo-tenant-1";
  forbidden.scenario_sha256 = computeScenarioSha256(forbidden);
  expectDomainError(() => loadScenarioPack(forbidden), "demo_scope_override_rejected", 400);

  const identity = rawScenario();
  const projections = identity.workspace_projections as Record<string, JsonValue>;
  const stores = projections.stores as Array<Record<string, JsonValue>>;
  stores[0] = { ...stores[0], store_id: "real-store" };
  identity.scenario_sha256 = computeScenarioSha256(identity);
  expectDomainError(
    () => loadScenarioPack(identity),
    "demo_non_synthetic_identity:scenario.workspace_projections.stores[0].store_id",
    400,
  );
});

test("scenario references must conserve synthetic store, sku and order identity", () => {
  const raw = rawScenario();
  const projections = raw.workspace_projections as Record<string, JsonValue>;
  const orders = projections.orders as Array<Record<string, JsonValue>>;
  orders[0] = { ...orders[0], store_id: "demo-store-999" };
  raw.scenario_sha256 = computeScenarioSha256(raw);
  expectDomainError(
    () => loadScenarioPack(raw),
    "demo_scenario_reference_invalid",
    400,
  );
});

test("deterministic clock is explicit and rejects invalid ticks", () => {
  const pack = loadScenarioPack(rawScenario());
  assert.equal(deterministicTimestamp(pack, 0), "2026-08-03T00:00:00.000Z");
  assert.equal(deterministicTimestamp(pack, 1), "2026-08-03T00:00:01.000Z");
  assert.equal(deterministicTimestamp(pack, 500), "2026-08-03T00:08:20.000Z");
  expectDomainError(() => deterministicTimestamp(pack, -1), "demo_clock_tick_invalid", 400);
});

test("session binds scenario identity for life and exposes no real authority refs", () => {
  const pack = loadScenarioPack(rawScenario());
  const session = new DemoSession(pack, "demo-session-sales-001");
  const snapshot = session.snapshot();

  assert.equal(snapshot.scenario_ref, pack.scenario_ref);
  assert.equal(snapshot.scenario_version, pack.scenario_version);
  assert.equal(snapshot.scenario_sha256, pack.scenario_sha256);
  assert.equal(snapshot.ttl_minutes, 60);
  assert.equal(snapshot.sequence, 0);
  assert.equal(snapshot.real_principal_ref, null);
  assert.equal(snapshot.real_entitlement_ref, null);
  assert.equal(snapshot.real_quota_ledger_ref, null);
  assert.equal(snapshot.real_approval_ref, null);
  assert.equal(snapshot.real_permit_ref, null);
  assert.equal(snapshot.external_side_effect_allowed, false);
  assert.ok(Object.isFrozen(snapshot));
  assert.ok(Object.isFrozen(snapshot.transition_log));
});

test("session transition is deterministic, append-only and has zero network or side effect", () => {
  const pack = loadScenarioPack(rawScenario());
  const session = new DemoSession(pack, "demo-session-sales-002");
  const initial = session.snapshot();
  const transition = session.appendTransition({
    workspace: "listings",
    action: "generate_preview",
    subject_ref: "demo-sku-001",
    canonical_payload_sha256: "1".repeat(64),
    occurred_at: deterministicTimestamp(pack, 1),
  });
  const current = session.snapshot();

  assert.equal(transition.sequence, 1);
  assert.equal(transition.previous_state_sha256, initial.state_sha256);
  assert.notEqual(transition.state_sha256, initial.state_sha256);
  assert.equal(transition.network_invoked, false);
  assert.equal(transition.external_side_effect_allowed, false);
  assert.equal(current.sequence, 1);
  assert.deepEqual(current.transition_log, [transition]);
  assert.ok(Object.isFrozen(transition));
});

test("session rejects clock drift, bad identity and expiry without mutation", () => {
  const pack = loadScenarioPack(rawScenario());
  expectDomainError(
    () => new DemoSession(pack, "session-real"),
    "demo_session_id_invalid",
    400,
  );
  const session = new DemoSession(pack, "demo-session-sales-003");
  expectDomainError(
    () =>
      session.appendTransition({
        workspace: "profit",
        action: "advance",
        subject_ref: "demo-sku-001",
        canonical_payload_sha256: "2".repeat(64),
        occurred_at: deterministicTimestamp(pack, 2),
      }),
    "demo_transition_clock_drift",
    409,
  );
  assert.equal(session.snapshot().sequence, 0);
  assert.equal(session.isExpired("2026-08-03T00:59:59.999Z"), false);
  assert.equal(session.isExpired("2026-08-03T01:00:00.000Z"), true);
  expectDomainError(
    () =>
      session.appendTransition({
        workspace: "profit",
        action: "advance",
        subject_ref: "demo-sku-001",
        canonical_payload_sha256: "2".repeat(64),
        occurred_at: "2026-08-03T01:00:00.000Z",
      }),
    "demo_session_expired",
    410,
  );
  assert.equal(session.snapshot().sequence, 0);
});

test("session enforces the synthetic capacity without mutating on exhaustion", () => {
  const raw = rawScenario();
  const projections = raw.workspace_projections as Record<string, JsonValue>;
  const summary = projections.summary as Record<string, JsonValue>;
  summary.demo_capacity = 2;
  raw.scenario_sha256 = computeScenarioSha256(raw);
  const pack = loadScenarioPack(raw);
  const session = new DemoSession(pack, "demo-session-capacity-001");
  for (let sequence = 1; sequence <= 2; sequence += 1) {
    session.appendTransition({
      workspace: "dashboard",
      action: "advance",
      subject_ref: "demo-store-001",
      canonical_payload_sha256: String(sequence).repeat(64),
      occurred_at: deterministicTimestamp(pack, sequence),
    });
  }
  expectDomainError(
    () =>
      session.appendTransition({
        workspace: "dashboard",
        action: "advance",
        subject_ref: "demo-store-001",
        canonical_payload_sha256: "3".repeat(64),
        occurred_at: deterministicTimestamp(pack, 3),
      }),
    "demo_capacity_exhausted",
    409,
  );
  assert.equal(session.snapshot().sequence, 2);
});

test("domain package source has no production imports, backend calls or credential reads", () => {
  const sourceUrls = [
    new URL("../src/domain/contracts.ts", import.meta.url),
    new URL("../src/domain/scenario-pack.ts", import.meta.url),
    new URL("../src/domain/demo-session.ts", import.meta.url),
  ];
  const source = sourceUrls.map((url) => readFileSync(url, "utf8")).join("\n");
  for (const forbidden of [
    "apps.control_plane",
    "web.app.backend",
    "/backend",
    "fetch(",
    "XMLHttpRequest",
    "KJDS_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "process.env",
    "dotenv",
  ]) {
    assert.equal(source.includes(forbidden), false, forbidden);
  }
});
