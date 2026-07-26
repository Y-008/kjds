import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
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

test("task navigation exposes every unified operating workspace", () => {
  const workspaces = read("../features/dashboard/dashboard-workspaces.ts");
  const shell = read("../features/dashboard/dashboard-shell.tsx");
  const view = read("../features/dashboard/dashboard-view.tsx");
  const targets = [...workspaces.matchAll(/\bid: "([a-z][a-z0-9-]+)"/g)].map((match) => match[1]);

  assert.deepEqual(targets, [
    "overview",
    "growth",
    "finance",
    "data",
    "research",
    "products",
    "sourcing",
    "science",
    "governance",
    "system",
  ]);
  assert.match(shell, /workspaceDefinitions\.filter/);
  assert.match(shell, /onNavigate\(item\.id\)/);
  assert.match(shell, /const selected = activeWorkspace === item\.id/);
  assert.match(shell, /aria-current=\{selected \? "page" : undefined\}/);
  for (const target of targets.filter((target) => target !== "overview")) {
    assert.match(view, new RegExp(`case "${target}"`));
  }
  assert.match(view, /window\.location\.hash/);
  assert.match(view, /history\.pushState/);
  assert.match(view, /addEventListener\("popstate"/);
  assert.doesNotMatch(view, /history\.replaceState/);
});

test("marketplace growth stays recommendation-only while using governed evidence", () => {
  const controller = read("../features/dashboard/use-dashboard-controller.tsx");
  const panel = read("../features/dashboard/marketplace-growth-panel.tsx");

  assert.match(controller, /\/backend\/v1\/marketplace-growth\/snapshots/);
  assert.match(controller, /\/backend\/v1\/marketplace-growth\/portfolio-plan\/latest/);
  assert.match(controller, /\/backend\/v1\/marketplace-growth\/observations\/latest/);
  assert.match(controller, /\/backend\/v1\/marketplace-catalog\/ozon\/import-evidence/);
  assert.match(controller, /\/backend\/v1\/marketplace-catalog\/items\/latest/);
  assert.match(controller, /\/backend\/v1\/marketplace-catalog\/items\/bind-existing/);
  assert.match(controller, /expected_item_hash: item\.item_hash/);
  assert.match(controller, /confirmed: true/);
  assert.match(panel, /建立已有 Listing 运营档案/);
  assert.match(panel, /不计入新选品，不改价、不发布、不采购、不投广告/);
  assert.match(panel, /unverified_external_reference|未核权外部引用/);
  assert.match(controller, /competitor_prices_rub/);
  assert.match(controller, /Number\.isFinite\(item\) && item > 0/);
  assert.match(controller, /scenario_id/);
  assert.match(controller, /evidence_ids/);
  assert.match(panel, /自动改价：关闭/);
  assert.match(panel, /自动投广告：关闭/);
  assert.match(panel, /自动发布：关闭/);
  assert.match(panel, /至少 3 个，用逗号或换行分隔/);
  assert.match(panel, /保存事实并生成全店方案/);
  assert.doesNotMatch(panel, /\/commands|\/write-attempt|\/receipt/);
});

test("overview dashboard renders the server-owned operating snapshot without synthetic business data", () => {
  const controller = read("../features/dashboard/use-dashboard-controller.tsx");
  const panel = read("../features/dashboard/unified-overview-panel.tsx");
  const contracts = read("../features/dashboard/contracts.ts");

  assert.match(controller, /\/backend\/v1\/operating-analytics\/snapshot/);
  assert.match(controller, /operatingAnalytics/);
  assert.match(contracts, /contract_id: "kjds-operating-flow-analytics-v1"/);
  assert.match(contracts, /synthetic_business_data_allowed: false/);
  assert.match(panel, /analytics\.stages\.map/);
  assert.match(panel, /analytics\.coverage\.map/);
  assert.match(panel, /analytics\.pipeline\.map/);
  assert.match(panel, /暂无可复验历史序列/);
  assert.match(panel, /Ozon 外部引用 · 未核权/);
  assert.match(panel, /不等于同行市场价/);
  assert.match(panel, /AI 不能自动选品、联系供应商、采购、改价、发布或投放/);
  assert.doesNotMatch(panel, /\/commands|\/write-attempt|\/receipt|Math\.random/);
});

test("supplier RFQ workspace freezes current listing requirements without sending", () => {
  const controller = read("../features/dashboard/use-dashboard-controller.tsx");
  const panel = read("../features/dashboard/supplier-quote-workspace.tsx");
  const contracts = read("../features/dashboard/contracts.ts");

  assert.match(controller, /\/backend\/v1\/sourcing\/rfq-packages/);
  assert.match(controller, /expected_item_hash: catalogItem\.item_hash/);
  assert.match(controller, /required_specifications: requiredSpecifications/);
  assert.match(controller, /confirmed: true/);
  assert.match(controller, /navigator\.clipboard\.writeText\(item\.package\.message_text\)/);
  assert.match(controller, /body\.append\("rfq_package_evidence_id"/);
  assert.match(panel, /已绑定 Ozon Listing/);
  assert.match(panel, /名称=要求/);
  assert.match(panel, /复制 ≠ 已发送 ≠ 已报价/);
  assert.match(panel, /商品标题、重量和尺寸只是 Ozon 目录观察/);
  assert.match(panel, /未自动联系供应商、未采购、未付款、未创建正式报价、未写入 Ozon/);
  assert.match(contracts, /contract_version: "supplier-rfq-package-v1"/);
  assert.match(contracts, /automatic_supplier_contact: false/);
  const createRfq = controller.slice(
    controller.indexOf("async function createSupplierRfq"),
    controller.indexOf("async function copySupplierRfqMessage"),
  );
  assert.doesNotMatch(createRfq, /1688|supplier\/contact|\/commands|\/write-attempt|\/receipt/);
});

test("supplier RFQ dispatch requires exact proof, independent review, and response lineage", () => {
  const controller = read("../features/dashboard/use-dashboard-controller.tsx");
  const panel = read("../features/dashboard/supplier-quote-workspace.tsx");
  const contracts = read("../features/dashboard/contracts.ts");

  assert.match(controller, /\/backend\/v1\/sourcing\/rfq-dispatches/);
  assert.match(controller, /body\.append\("sent_message_text", rfq\.package\.message_text\)/);
  assert.match(controller, /body\.append\("confirmed", "true"\)/);
  assert.match(controller, /body\.append\("file", proof\)/);
  assert.match(controller, /\/rfq-dispatches\/\$\{evidenceId\}\/authority-review/);
  assert.match(controller, /body\.append\("rfq_dispatch_evidence_id"/);
  for (const check of [
    "dispatch_authentic_platform_proof",
    "dispatch_supplier_identity_matches",
    "dispatch_frozen_message_matches",
    "dispatch_timestamp_and_conversation_match",
  ]) {
    assert.match(controller, new RegExp(check));
    assert.match(panel, new RegExp(check));
  }
  assert.match(panel, /复制不等于发送，发送不等于送达或回复/);
  assert.match(panel, /仅在你已经实际发送后上传/);
  assert.match(panel, /本按钮不会替你联系供应商/);
  assert.match(panel, /送达、供应商回复、有效报价、采购、付款与 Ozon 写入仍全部为 false/);
  assert.match(panel, /对应已核验发送证明/);
  assert.match(contracts, /contract_version: "supplier-rfq-dispatch-v1"/);
  assert.match(contracts, /delivery_confirmed: false/);
  assert.match(contracts, /supplier_replied: false/);
  assert.match(contracts, /counts_as_supplier_quote: false/);

  const captureDispatch = controller.slice(
    controller.indexOf("async function captureSupplierRfqDispatch"),
    controller.indexOf("async function reviewSupplierRfqDispatch"),
  );
  assert.doesNotMatch(
    captureDispatch,
    /supplier\/contact|\/commands|\/write-attempt|\/receipt|automatic_supplier_contact.*true/,
  );
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
