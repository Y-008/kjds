import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { LocalDemoGateway } from "../src/application/local-demo-gateway.ts";
import { InMemorySessionStore } from "../src/application/in-memory-session-store.ts";
import { denyNetworkRequest } from "../src/application/network-policy.ts";
import { LocalDemoDomainError } from "../src/domain/contracts.ts";
import { loadScenarioPack } from "../src/domain/scenario-pack.ts";

const FIXTURE_URL = new URL(
  "../src/scenarios/enterprise-overview.zh-CN.v1.json",
  import.meta.url,
);

function pack() {
  return loadScenarioPack(JSON.parse(readFileSync(FIXTURE_URL, "utf8")));
}

function fixedGateway(
  sessionId: string,
  scope: string,
  store = new InMemorySessionStore(),
) {
  return new LocalDemoGateway(pack(), {
    store,
    gateway_scope_token: scope,
    session_id_factory: () => sessionId,
  });
}

function assertMarkers(value: Record<string, unknown>): void {
  assert.equal(value.demo, true);
  assert.equal(value.synthetic, true);
  assert.equal(value.non_billable, true);
  assert.equal(value.external_side_effect_allowed, false);
  assert.equal(value.network_invoked, false);
  assert.equal(value.real_principal_ref, null);
  assert.equal(value.real_entitlement_ref, null);
  assert.equal(value.real_quota_ledger_ref, null);
  assert.equal(value.real_approval_ref, null);
  assert.equal(value.real_permit_ref, null);
}

test("open_session returns the only synthetic authority-free envelope", () => {
  const gateway = fixedGateway("demo-session-open-001", "scope-a");
  const response = gateway.open_session({
    scenario_ref: "enterprise-overview.zh-CN",
    locale: "zh-CN",
  });

  assertMarkers(response as unknown as Record<string, unknown>);
  assert.equal(response.error, null);
  assert.equal(response.session_id, "demo-session-open-001");
  assert.equal(response.sequence, 0);
  assert.equal(response.data?.transition_log.length, 0);
  assert.ok(Object.isFrozen(response));
  assert.ok(Object.isFrozen(response.data));
});

test("scope overrides are rejected before opening or mutating a session", () => {
  let sessionFactoryCalls = 0;
  const gateway = new LocalDemoGateway(pack(), {
    gateway_scope_token: "scope-override",
    session_id_factory: () => {
      sessionFactoryCalls += 1;
      return "demo-session-override-001";
    },
  });
  const response = gateway.open_session({
    scenario_ref: "enterprise-overview.zh-CN",
    locale: "zh-CN",
    tenant_ref: "demo-tenant-001",
  });

  assertMarkers(response as unknown as Record<string, unknown>);
  assert.equal(response.error?.code, "demo_scope_override_rejected");
  assert.equal(response.error?.http_status, 400);
  assert.equal(response.data, null);
  assert.equal(sessionFactoryCalls, 0);
});

test("query paginates immutable projections without advancing the session", () => {
  const gateway = fixedGateway("demo-session-query-001", "scope-query");
  gateway.open_session({
    scenario_ref: "enterprise-overview.zh-CN",
    locale: "zh-CN",
  });
  const first = gateway.query({
    session_id: "demo-session-query-001",
    workspace: "pim",
  });
  const second = gateway.query({
    session_id: "demo-session-query-001",
    workspace: "pim",
    cursor: first.data?.next_cursor,
  });

  assert.equal(first.error, null);
  assert.equal(first.sequence, 0);
  assert.equal(first.data?.items.length, 20);
  assert.equal(first.data?.next_cursor, "demo-cursor-20");
  assert.equal(second.data?.items.length, 20);
  assert.equal(second.data?.next_cursor, "demo-cursor-40");
  assert.equal(second.sequence, 0);
  assert.ok(Object.isFrozen(first.data?.items));
});

test("foreign and missing sessions return the same non-enumerable 404", () => {
  const sharedStore = new InMemorySessionStore();
  const owner = fixedGateway("demo-session-hidden-001", "scope-owner", sharedStore);
  const foreign = fixedGateway("demo-session-unused-001", "scope-foreign", sharedStore);
  const empty = fixedGateway(
    "demo-session-unused-002",
    "scope-empty",
    new InMemorySessionStore(),
  );
  owner.open_session({
    scenario_ref: "enterprise-overview.zh-CN",
    locale: "zh-CN",
  });

  const foreignResponse = foreign.query({
    session_id: "demo-session-hidden-001",
    workspace: "dashboard",
  });
  const missingResponse = empty.query({
    session_id: "demo-session-hidden-001",
    workspace: "dashboard",
  });

  assert.deepEqual(foreignResponse, missingResponse);
  assert.equal(foreignResponse.error?.code, "demo_session_not_found");
  assert.equal(foreignResponse.error?.http_status, 404);
  assert.equal(foreignResponse.scenario_ref, null);
  assert.equal(foreignResponse.scenario_sha256, null);
  assert.equal(foreignResponse.data, null);
});

test("apply is exactly-once for one key and same canonical payload", () => {
  const gateway = fixedGateway("demo-session-apply-001", "scope-apply");
  gateway.open_session({
    scenario_ref: "enterprise-overview.zh-CN",
    locale: "zh-CN",
  });
  const request = {
    session_id: "demo-session-apply-001",
    action: "generate_listing_preview",
    subject_ref: "demo-sku-001",
    payload: { template: "listing-v1", tone: "neutral" },
    idempotency_key: "listing-preview-001",
  };
  const first = gateway.apply(request);
  const replay = gateway.apply({
    ...request,
    payload: { tone: "neutral", template: "listing-v1" },
  });

  assert.equal(first.error, null);
  assert.equal(first.sequence, 1);
  assert.equal(first.data?.transition.network_invoked, false);
  assert.deepEqual(replay, first);
});

test("idempotency payload drift is 409 and leaves sequence/state unchanged", () => {
  const gateway = fixedGateway("demo-session-drift-001", "scope-drift");
  gateway.open_session({
    scenario_ref: "enterprise-overview.zh-CN",
    locale: "zh-CN",
  });
  const first = gateway.apply({
    session_id: "demo-session-drift-001",
    action: "advance_order_timeline",
    subject_ref: "demo-order-001",
    payload: { target: "in_fulfillment" },
    idempotency_key: "order-timeline-001",
  });
  const drift = gateway.apply({
    session_id: "demo-session-drift-001",
    action: "advance_order_timeline",
    subject_ref: "demo-order-001",
    payload: { target: "simulated_delivered" },
    idempotency_key: "order-timeline-001",
  });

  assert.equal(first.sequence, 1);
  assert.equal(drift.error?.code, "demo_idempotency_payload_drift");
  assert.equal(drift.error?.http_status, 409);
  assert.equal(drift.sequence, 1);
  assert.equal(drift.state_sha256, first.state_sha256);
  assert.equal(drift.network_invoked, false);
});

test("nested credentials are rejected before a transition", () => {
  const gateway = fixedGateway("demo-session-secret-001", "scope-secret");
  gateway.open_session({
    scenario_ref: "enterprise-overview.zh-CN",
    locale: "zh-CN",
  });
  const response = gateway.apply({
    session_id: "demo-session-secret-001",
    action: "simulate_campaign",
    subject_ref: "demo-store-001",
    payload: { nested: { api_key: "not-stored" } },
    idempotency_key: "campaign-secret-001",
  });
  const query = gateway.query({
    session_id: "demo-session-secret-001",
    workspace: "dashboard",
  });

  assert.equal(response.error?.code, "demo_scope_override_rejected");
  assert.equal(response.sequence, 0);
  assert.equal(query.sequence, 0);
});

test("reset deletes only the scoped session and its replay records", () => {
  const sharedStore = new InMemorySessionStore();
  const first = fixedGateway("demo-session-reset-001", "scope-reset-a", sharedStore);
  const second = fixedGateway("demo-session-reset-002", "scope-reset-b", sharedStore);
  for (const gateway of [first, second]) {
    gateway.open_session({
      scenario_ref: "enterprise-overview.zh-CN",
      locale: "zh-CN",
    });
  }
  const reset = first.reset({ session_id: "demo-session-reset-001" });
  const gone = first.query({
    session_id: "demo-session-reset-001",
    workspace: "dashboard",
  });
  const intact = second.query({
    session_id: "demo-session-reset-002",
    workspace: "dashboard",
  });

  assert.equal(reset.data?.reset, true);
  assert.equal(gone.error?.code, "demo_session_not_found");
  assert.equal(intact.error, null);
  first.open_session({
    scenario_ref: "enterprise-overview.zh-CN",
    locale: "zh-CN",
  });
  const reopened = first.apply({
    session_id: "demo-session-reset-001",
    action: "refresh_dashboard",
    subject_ref: "demo-store-001",
    payload: { step: "reopened" },
    idempotency_key: "reset-replay-001",
  });
  assert.equal(reopened.error, null);
  assert.equal(reopened.sequence, 1);
});

test("invalid cursor fails without mutation", () => {
  const gateway = fixedGateway("demo-session-cursor-001", "scope-cursor");
  gateway.open_session({
    scenario_ref: "enterprise-overview.zh-CN",
    locale: "zh-CN",
  });
  const response = gateway.query({
    session_id: "demo-session-cursor-001",
    workspace: "oms",
    cursor: "foreign-cursor",
  });
  assert.equal(response.error?.code, "demo_cursor_invalid");
  assert.equal(response.sequence, 0);
});

test("network policy rejects every request and source has no network or production import", () => {
  assert.throws(
    () => denyNetworkRequest("https://example.invalid"),
    (error: unknown) =>
      error instanceof LocalDemoDomainError && error.code === "demo_network_forbidden",
  );
  const sourceUrls = [
    new URL("../src/application/local-demo-gateway.ts", import.meta.url),
    new URL("../src/application/in-memory-session-store.ts", import.meta.url),
    new URL("../src/application/network-policy.ts", import.meta.url),
  ];
  const source = sourceUrls.map((url) => readFileSync(url, "utf8")).join("\n");
  for (const forbidden of [
    "apps.control_plane",
    "web.app.backend",
    "/backend",
    "fetch(",
    "XMLHttpRequest",
    "node:http",
    "node:https",
    "node:net",
    "node:tls",
    "process.env",
    "dotenv",
    "SUPABASE_URL",
    "KJDS_API_KEY",
  ]) {
    assert.equal(source.includes(forbidden), false, forbidden);
  }
});
