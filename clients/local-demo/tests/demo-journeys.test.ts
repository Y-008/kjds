import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { LocalDemoGateway } from "../src/application/local-demo-gateway.ts";
import type {
  DemoWorkspace,
  JsonValue,
  ScenarioHeroFlow,
  ScenarioHeroStep,
} from "../src/domain/contracts.ts";
import {
  computeScenarioSha256,
  loadScenarioPack,
} from "../src/domain/scenario-pack.ts";

const V2_URL = new URL("../src/scenarios/enterprise-overview.zh-CN.v2.json", import.meta.url);

function rawV2(): Record<string, JsonValue> {
  return JSON.parse(readFileSync(V2_URL, "utf8")) as Record<string, JsonValue>;
}

function fixedGateway() {
  const pack = loadScenarioPack(rawV2());
  return {
    gateway: new LocalDemoGateway(pack, {
      gateway_scope_token: "demo-test-scope-v2",
      session_id_factory: () => "demo-session-journey-v2",
    }),
    pack,
  };
}

function open(gateway: LocalDemoGateway) {
  const response = gateway.open_session({
    scenario_ref: "enterprise-overview.zh-CN",
    locale: "zh-CN",
  });
  assert.equal(response.error, null);
  return response;
}

function runFlow(gateway: LocalDemoGateway, flow: ScenarioHeroFlow) {
  let state = open(gateway).state_sha256;
  const responses = [];
  for (const [index, step] of flow.steps.entries()) {
    const response = gateway.apply({
      session_id: "demo-session-journey-v2",
      action: step.action,
      subject_ref: step.subject_ref,
      payload: step.payload,
      idempotency_key: `${flow.flow_id}-${index + 1}`,
      expected_state_sha256: state,
    });
    assert.equal(response.error, null, `${flow.flow_id}:${step.step_id}`);
    state = response.state_sha256;
    responses.push(response);
  }
  return responses;
}

test("v2 pack is content addressed and validates action/workspace/subject ownership", () => {
  const raw = rawV2();
  const pack = loadScenarioPack(raw);
  assert.equal(pack.scenario_version, "v2");
  assert.equal(pack.hero_flows?.length, 3);
  assert.equal(pack.scenario_sha256, computeScenarioSha256(raw));

  const invalid = rawV2();
  const flows = invalid.hero_flows as Array<Record<string, JsonValue>>;
  const steps = flows[0]?.steps as Array<Record<string, JsonValue>>;
  if (!steps?.[0]) throw new Error("fixture_missing");
  steps[0].workspace = "profit";
  invalid.scenario_sha256 = computeScenarioSha256(invalid);
  assert.throws(
    () => loadScenarioPack(invalid),
    (error: unknown) =>
      error instanceof Error && error.message === "demo_scenario_reference_invalid",
  );
});

test("v2 requires expected state and rejects terminal jumps without mutation", () => {
  const { gateway } = fixedGateway();
  const opened = open(gateway);
  const missing = gateway.apply({
    session_id: "demo-session-journey-v2",
    action: "advance_sourcing",
    subject_ref: "demo-sku-001",
    payload: { target: "qualified" },
    idempotency_key: "expected-missing-v2",
  });
  assert.equal(missing.error?.code, "demo_expected_state_required");
  const mismatch = gateway.apply({
    session_id: "demo-session-journey-v2",
    action: "advance_sourcing",
    subject_ref: "demo-sku-001",
    payload: { target: "qualified" },
    idempotency_key: "expected-mismatch-v2",
    expected_state_sha256: "0".repeat(64),
  });
  assert.equal(mismatch.error?.code, "demo_expected_state_mismatch");
  const jump = gateway.apply({
    session_id: "demo-session-journey-v2",
    action: "generate_listing_preview",
    subject_ref: "demo-sku-001",
    payload: { target: "preview_ready" },
    idempotency_key: "terminal-jump-v2",
    expected_state_sha256: opened.state_sha256,
  });
  assert.equal(jump.error?.code, "demo_action_precondition_failed");
  assert.equal(jump.sequence, 0);
  assert.equal(jump.state_sha256, opened.state_sha256);
});

test("three deterministic hero flows update transition-derived read models", () => {
  const firstRun = fixedGateway();
  const flows = firstRun.pack.hero_flows ?? [];
  const opportunity = runFlow(firstRun.gateway, flows[0] as ScenarioHeroFlow);
  const listing = firstRun.gateway.query({
    session_id: "demo-session-journey-v2",
    workspace: "listings",
  });
  const listingItem = listing.data?.items.find(
    (item) => typeof item === "object" && item !== null && !Array.isArray(item) && item.sku_id === "demo-sku-001",
  ) as Record<string, JsonValue>;
  assert.equal(listingItem.preview_state, "generated");
  assert.equal(listing.sequence, 3);

  const secondRun = fixedGateway();
  const orderResponses = runFlow(secondRun.gateway, flows[1] as ScenarioHeroFlow);
  const fulfillment = secondRun.gateway.query({
    session_id: "demo-session-journey-v2",
    workspace: "fulfillment",
  });
  const fulfillmentItem = fulfillment.data?.items[0] as Record<string, JsonValue>;
  assert.equal(fulfillmentItem.inventory_state, "reserved");
  assert.equal(fulfillmentItem.return_state, "exception");

  const thirdRun = fixedGateway();
  runFlow(thirdRun.gateway, flows[2] as ScenarioHeroFlow);
  const profit = thirdRun.gateway.query({
    session_id: "demo-session-journey-v2",
    workspace: "profit",
  });
  const profitItem = profit.data?.items[0] as Record<string, JsonValue>;
  const summary = profit.data?.summary as Record<string, JsonValue>;
  const decisionCounts = summary.decision_counts as Record<string, JsonValue>;
  assert.equal(profitItem.settlement_state, "allocated");
  assert.equal(profitItem.fee_minor, 15_000);
  assert.equal(profitItem.cash_profit_minor, 12_000);
  assert.equal(profitItem.decision, "continue");
  for (const decision of ["stop", "fix", "continue", "no_data"]) {
    assert.ok(Number(decisionCounts[decision]) > 0, decision);
  }

  const deterministic = fixedGateway();
  const repeated = runFlow(deterministic.gateway, flows[0] as ScenarioHeroFlow);
  assert.deepEqual(repeated, opportunity);
  assert.equal(orderResponses.at(-1)?.sequence, 4);
});

test("all nine workspaces query data and reset restores scenario/state/read-model hashes", () => {
  const { gateway, pack } = fixedGateway();
  const opened = open(gateway);
  const workspaces: DemoWorkspace[] = [
    "dashboard", "sourcing", "pim", "listings", "oms", "fulfillment",
    "customer_service", "growth", "profit",
  ];
  const baseline = new Map<DemoWorkspace, string>();
  for (const workspace of workspaces) {
    const query = gateway.query({ session_id: "demo-session-journey-v2", workspace });
    assert.equal(query.error, null);
    assert.ok((query.data?.items.length ?? 0) > 0, workspace);
    baseline.set(workspace, query.data?.read_model_sha256 ?? "");
  }
  const responses = runFlowAfterOpen(gateway, pack.hero_flows?.[0] as ScenarioHeroFlow, opened.state_sha256);
  assert.equal(responses.length, 3);
  const reset = gateway.reset({ session_id: "demo-session-journey-v2" });
  assert.equal(reset.data?.reset, true);
  const reopened = open(gateway);
  assert.equal(reopened.scenario_sha256, opened.scenario_sha256);
  assert.equal(reopened.state_sha256, opened.state_sha256);
  for (const workspace of workspaces) {
    const query = gateway.query({ session_id: "demo-session-journey-v2", workspace });
    assert.equal(query.data?.read_model_sha256, baseline.get(workspace), workspace);
  }
});

test("all nine workspaces accept a legal apply and expose the derived change", () => {
  const workspaces: DemoWorkspace[] = [
    "dashboard", "sourcing", "pim", "listings", "oms", "fulfillment",
    "customer_service", "growth", "profit",
  ];
  for (const workspace of workspaces) {
    const { gateway, pack } = fixedGateway();
    let state = open(gateway).state_sha256;
    const before = gateway.query({ session_id: "demo-session-journey-v2", workspace });
    const flows = pack.hero_flows ?? [];
    let steps: readonly ScenarioHeroStep[];
    if (workspace === "dashboard") {
      steps = [{ step_id: "demo-test-dashboard", label: "refresh", workspace, action: "refresh_dashboard", subject_ref: "demo-store-001", payload: { target: "refreshed" } }];
    } else if (workspace === "customer_service") {
      steps = [{ step_id: "demo-test-service", label: "draft", workspace, action: "draft_customer_reply", subject_ref: "demo-order-001", payload: { target: "drafted" } }];
    } else if (workspace === "growth") {
      steps = [{ step_id: "demo-test-growth", label: "campaign", workspace, action: "simulate_campaign", subject_ref: "demo-store-001", payload: { target: "positive_signal" } }];
    } else if (workspace === "sourcing") steps = flows[0]?.steps.slice(0, 1) ?? [];
    else if (workspace === "pim") steps = flows[0]?.steps.slice(0, 2) ?? [];
    else if (workspace === "listings") steps = flows[0]?.steps ?? [];
    else if (workspace === "oms") steps = flows[1]?.steps.slice(0, 1) ?? [];
    else if (workspace === "fulfillment") steps = flows[1]?.steps ?? [];
    else steps = flows[2]?.steps ?? [];

    for (const [index, step] of steps.entries()) {
      const response = gateway.apply({
        session_id: "demo-session-journey-v2",
        action: step.action,
        subject_ref: step.subject_ref,
        payload: step.payload,
        idempotency_key: `nine-${workspace}-${index + 1}`,
        expected_state_sha256: state,
      });
      assert.equal(response.error, null, `${workspace}:${step.action}`);
      state = response.state_sha256;
    }
    const after = gateway.query({ session_id: "demo-session-journey-v2", workspace });
    assert.ok((after.sequence ?? 0) > 0, workspace);
    assert.notEqual(after.data?.read_model_sha256, before.data?.read_model_sha256, workspace);
    const first = after.data?.items[0] as Record<string, JsonValue>;
    if (workspace === "dashboard") assert.equal(first.signal_state, "refreshed");
    if (workspace === "customer_service") assert.equal(first.reply_state, "drafted");
    if (workspace === "growth") assert.equal(first.campaign_state, "simulated");
  }
});

function runFlowAfterOpen(
  gateway: LocalDemoGateway,
  flow: ScenarioHeroFlow,
  initialState: string,
) {
  let state = initialState;
  return flow.steps.map((step, index) => {
    const response = gateway.apply({
      session_id: "demo-session-journey-v2",
      action: step.action,
      subject_ref: step.subject_ref,
      payload: step.payload,
      idempotency_key: `after-open-${flow.flow_id}-${index + 1}`,
      expected_state_sha256: state,
    });
    assert.equal(response.error, null);
    state = response.state_sha256;
    return response;
  });
}

test("v2 idempotency replay is exact and drift/error replay never advances", () => {
  const { gateway, pack } = fixedGateway();
  const opened = open(gateway);
  const step = pack.hero_flows?.[0]?.steps[0] as ScenarioHeroStep;
  const request = {
    session_id: "demo-session-journey-v2",
    action: step.action,
    subject_ref: step.subject_ref,
    payload: step.payload,
    idempotency_key: "exact-replay-v2",
    expected_state_sha256: opened.state_sha256,
  };
  const first = gateway.apply(request);
  const replay = gateway.apply(request);
  assert.deepEqual(replay, first);
  const drift = gateway.apply({ ...request, payload: { target: "drift" } });
  assert.equal(drift.error?.code, "demo_idempotency_payload_drift");
  const badRequest = {
    ...request,
    idempotency_key: "expected-error-replay-v2",
    expected_state_sha256: "0".repeat(64),
  };
  const bad = gateway.apply(badRequest);
  const badReplay = gateway.apply(badRequest);
  assert.deepEqual(badReplay, bad);
  assert.equal(bad.error?.code, "demo_expected_state_mismatch");
  assert.equal(bad.sequence, first.sequence);
});
