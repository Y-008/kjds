import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { readDashboardSource } from "./dashboard-source.ts";
import { fetchJson, settleJsonRequests } from "./fetch-json.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("page delegates to the dashboard composition root", () => {
  const page = read("../app/page.tsx");
  const dashboard = read("../features/dashboard/kjds-dashboard.tsx");

  assert.match(page, /<KjdsDashboard\s*\/>/);
  assert.doesNotMatch(page, /\/backend\//);
  assert.match(dashboard, /useDashboardController\(\)/);
  assert.match(dashboard, /<DashboardView model=/);
});

test("sidebar navigation targets real dashboard sections", () => {
  const source = readDashboardSource();
  const shell = read("../features/dashboard/dashboard-shell.tsx");
  const targets = [...shell.matchAll(/"(#[a-z][a-z0-9-]+)"/g)].map((match) => match[1]);

  assert.equal(targets.length, 9);
  for (const target of targets) assert.match(source, new RegExp(`id="${target.slice(1)}"`));
  assert.match(shell, /<a href=\{href\}/);
});

test("approved listings expose only the minimal execution-plan handoff", () => {
  const controller = read("../features/dashboard/use-dashboard-controller.tsx");
  const productPanel = read("../features/dashboard/product-content-panel.tsx");
  const decisionPanel = read("../features/dashboard/decision-science-panel.tsx");
  const contracts = read("../features/dashboard/contracts.ts");
  const presentation = read("../features/dashboard/listing-execution-presentation.ts");

  assert.match(controller, /\/backend\/v1\/listings\/ozon\/drafts\/\$\{draftId\}\/execution-plan/);
  assert.match(controller, /idempotency_key/);
  assert.match(controller, /precondition_state_hash/);
  assert.match(controller, /evidence_ids/);
  assert.match(controller, /risk_limits/);
  const handoff = controller.slice(controller.indexOf("async function prepareListingExecutionPlan"), controller.indexOf("async function dryRunExecutionPlan"));
  assert.doesNotMatch(handoff, /adapter_id|target:|intended_patch|rollback_patch|item:/);
  assert.match(controller, /item\.action === "listing\.publish" && item\.status === "approved"/);
  assert.match(productPanel, /准备执行计划/);
  assert.doesNotMatch(productPanel, /立即发布/);
  assert.match(productPanel, /Listing Approval/);
  assert.match(productPanel, /Execution Approval/);
  assert.match(presentation, /authorization_blocking_reasons/);
  assert.match(presentation, /current_readiness_snapshot/);
  assert.match(presentation, /evidence_ids/);
  assert.match(productPanel, /selectListingExecutionPresentations/);
  assert.match(productPanel, /补偿生命周期/);
  assert.doesNotMatch(productPanel, /source_type === "limited_execution_command"/);
  assert.doesNotMatch(productPanel, /backend_blockers|evidence_references|lifecycle_status/);
  assert.match(presentation, /rollbackCommand\?\.status === "succeeded"/);
  assert.match(presentation, /: executeCommand\?\.status \?\? "preflight"/);
  assert.match(presentation, /rollbackLifecycle: rollbackCommand\?\.status/);
  assert.match(decisionPanel, /causalPolicyExecutionPlans\.find/);
  assert.match(contracts, /source_kind: "causal_policy_handoff" \| "approved_listing_draft"/);
  assert.match(contracts, /handoff_id: string \| null; policy_id: string \| null; release_id: string \| null/);
  assert.match(contracts, /"queued" \| "claimed" \| "write_started" \| "succeeded" \| "failed" \| "uncertain" \| "expired" \| "precondition_failed"/);
});

test("listing execution authority reviews are role-gated evidence-only handoffs", () => {
  const controller = read("../features/dashboard/use-dashboard-controller.tsx");
  const productPanel = read("../features/dashboard/product-content-panel.tsx");

  assert.match(controller, /\["reviewer", "compliance", "admin"\]/);
  assert.match(controller, /canReviewExecutionAuthority/);
  assert.match(controller, /\/russian-native-review/);
  assert.match(controller, /\/operations\/ozon\/execution-identities\/\$\{evidenceId\}\/authority-review/);
  for (const check of [
    "native_russian_verified",
    "listing_snapshot_reviewed",
    "terminology_accepted",
    "claims_grounded",
    "ozon_policy_checked",
    "inventory_complete",
    "credential_material_absent",
    "owner_verified",
    "caller_system_verified",
    "scope_minimized",
    "dedicated_executor",
  ]) {
    assert.match(controller, new RegExp(check));
    assert.match(productPanel, new RegExp(check));
  }
  assert.match(productPanel, /ozon_execution_identity_inventory/);
  assert.match(productPanel, /不会开启运行开关/);
  assert.match(productPanel, /接受结论不会直接发布/);
  const russianReview = controller.slice(
    controller.indexOf("async function reviewListingRussianNative"),
    controller.indexOf("async function reviewOzonExecutionIdentity"),
  );
  const identityReview = controller.slice(
    controller.indexOf("async function reviewOzonExecutionIdentity"),
    controller.indexOf("async function dryRunExecutionPlan"),
  );
  for (const review of [russianReview, identityReview]) {
    assert.doesNotMatch(review, /\/commands|\/claim|\/write-attempt|\/receipt/);
  }
});

test("request failures settle without rejecting sibling dashboard loads", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error("offline"); };
  try {
    const [failed, healthy] = await settleJsonRequests([
      fetchJson("https://optional.invalid"),
      Promise.resolve({ ok: true, status: 200, json: async () => ({ status: "ok" }) }),
    ]);
    assert.equal(failed.ok, false);
    assert.equal(failed.status, 0);
    assert.equal(healthy.ok, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Agent status comes from the governed operating-workbench briefing", () => {
  const controller = read("../features/dashboard/use-dashboard-controller.tsx");
  const summary = read("../features/dashboard/operations-summary-panel.tsx");

  assert.match(controller, /\/backend\/v1\/operating-workbench\/briefing/);
  assert.match(summary, /operatingWorkbench\?\.agents\.map/);
  assert.doesNotMatch(summary, /\["市场分析", "商品策略"/);
  assert.match(summary, /页面不会自行猜测 Agent 状态/);
});
