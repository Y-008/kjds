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
    "batch",
    "pilot",
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

test("portfolio pilot renders only server-owned screening economics", () => {
  const panel = read("../features/dashboard/portfolio-pilot-panel.tsx");
  const workspaces = read("../features/dashboard/dashboard-workspaces.ts");

  assert.match(workspaces, /id: "pilot"/);
  assert.match(panel, /\/backend\/v1\/marketplace-observations\?\$\{query\.toString\(\)\}/);
  assert.match(panel, /kjds-scoped-marketplace-observation-v1/);
  assert.match(panel, /payload\.items/);
  assert.match(panel, /store_ref: storeRef/);
  assert.match(panel, /暂无通过作用域 Evidence/);
  assert.match(panel, /candidateScoringAllowed/);
  assert.match(panel, /!candidateScoringAllowed/);
  assert.match(panel, /\/backend\/v1\/portfolio-pilot\/prepare/);
  assert.match(panel, /target_specification: targetSpecification/);
  assert.match(panel, /policy_id: "ozon-cny-research-screening-v1"/);
  assert.match(panel, /max_loss_cny: "500\.00"/);
  assert.match(panel, /公开展示价 · observed · 非 Offer · 非实际成本/);
  assert.match(panel, /实际利润可用：否/);
  assert.match(panel, /自动联系供应商：否/);
  assert.match(panel, /自动上架：否/);
  assert.doesNotMatch(panel, /Math\.random|\/commands|\/write-attempt|\/receipt/);
  assert.doesNotMatch(panel, /listing_price\s*[-+*/]|displayed_price\s*[-+*/]/);
});

test("batch opportunity workbench uses only server-owned scans and safety contracts", () => {
  const panel = read("../features/dashboard/batch-opportunity-panel.tsx");
  const workspaces = read("../features/dashboard/dashboard-workspaces.ts");

  assert.match(workspaces, /id: "batch"/);
  assert.match(panel, /\/backend\/v1\/batch-opportunities\/latest/);
  assert.match(panel, /\/backend\/v1\/batch-market-scans/);
  assert.match(panel, /observed_checkout_price/);
  assert.match(panel, /downside/);
  assert.match(panel, /Passport/);
  assert.match(panel, /24h\/72h\/7d/);
  assert.match(panel, /70% 已验证精品/);
  assert.match(panel, /Permit/);
  assert.match(panel, /Ozon 写入/);
  assert.match(panel, /cn-ozon-observed-cost-v1/);
  assert.match(panel, /OZON GLOBAL CN/);
  assert.match(panel, /official_rule_ready/);
  assert.match(panel, /exact_identity_matched/);
  assert.match(panel, /checkout_cost_eligible/);
  assert.match(panel, /同款已找到，待结算成本 Evidence/);
  assert.match(panel, /target_purchase_quantity: 1/);
  assert.match(panel, /pilot_limit: 3/);
  assert.match(panel, /不向供应商下单/);
  assert.match(panel, /sale-triggered JIT/);
  assert.match(panel, /sale_triggered_procurement/);
  assert.match(panel, /出单前采购/);
  assert.match(panel, /\/backend\/v1\/erp\/profit-items/);
  assert.match(panel, /利润款写入 ERP/);
  assert.match(panel, /opening_stock=0/);
  assert.match(panel, /不会把观察价写成 ERP 利润商品/);
  assert.doesNotMatch(
    panel,
    /Math\.random|listing_price\s*[-+*/]|observed_checkout_price\s*[-+*/]|\/commands|\/write-attempt|\/receipt/,
  );
});

test("seller operating system retains four operating routes over one fact kernel", () => {
  const consoleSource = read("../features/seller-os/seller-os-console.tsx");
  const routes = [
    ["seller-os", "seller-os"],
    ["rule-advantage", "rule-advantage"],
    ["store-matrix", "store-matrix"],
    ["growth-command", "growth-command"],
  ];

  for (const [directory, surface] of routes) {
    const page = read(`../app/${directory}/page.tsx`);
    assert.match(page, new RegExp(`surface="${surface}"`));
    assert.match(page, /SellerOsConsole/);
  }
  assert.match(consoleSource, /\/backend\/v1\/seller-os\/strategy-packs/);
  assert.match(consoleSource, /\/backend\/v1\/seller-os\/evaluate/);
  assert.match(consoleSource, /\/backend\/v1\/batch-opportunities\/latest/);
  assert.match(consoleSource, /同一真实候选的 5 档经营决策/);
  assert.match(consoleSource, /自动上品数量不是成功指标/);
  assert.match(consoleSource, /不降低真实性/);
  assert.match(consoleSource, /no_data/);
  assert.match(consoleSource, /Permit 均未创建/);
  assert.doesNotMatch(
    consoleSource,
    /Math\.random|\/commands|\/write-attempt|\/receipt/,
  );
});

test("strategic surfaces use one read-only server-owned dashboard projection", () => {
  const source = read(
    "../features/strategic-capital-dashboard/strategic-capital-dashboard.tsx",
  );
  const strategy = read("../app/strategy-center/page.tsx");
  const portfolio = read("../app/portfolio-cockpit/page.tsx");
  const sessionRoute = read("../app/auth/session/route.ts");
  const identity = read("./web-identity.ts");
  const contract = read(
    "../features/strategic-capital-dashboard/contract.ts",
  );

  assert.match(strategy, /StrategicCapitalDashboard surface="strategy-center"/);
  assert.match(portfolio, /StrategicCapitalDashboard surface="portfolio-cockpit"/);
  assert.doesNotMatch(strategy, /SellerOsConsole/);
  assert.doesNotMatch(portfolio, /SellerOsConsole/);
  assert.match(source, /fetchJson<WebSession[^>]*>\(\s*["']\/auth\/session/);
  assert.match(source, /session\.default_store_ref/);
  assert.match(source, /session\.store_refs\.includes\(storeRef\)/);
  assert.match(source, /encodeURIComponent\(storeRef\)/);
  assert.match(source, /isStrategicCapitalDashboardProjection\(payload, storeRef\)/);
  assert.match(source, /status === 401/);
  assert.match(source, /status === 428/);
  assert.doesNotMatch(source, /store_ref=ozon-primary/);
  assert.match(sessionRoute, /store_refs:\s*identity\.storeRefs/);
  assert.match(sessionRoute, /default_store_ref:\s*identity\.storeRefs\[0\]/);
  assert.match(identity, /storeRefs:\s*credential\.storeRefs/);
  assert.match(source, /dashboard\.sections\.map/);
  assert.match(source, /section\.display_order/);
  assert.match(source, /section\.display_items\.map/);
  assert.match(contract, /not_connected/);
  assert.match(contract, /no_data/);
  assert.match(contract, /UNKNOWN/);
  assert.match(source, /global_top1=false/);
  assert.match(source, /production_admission=false/);
  assert.match(source, /budget_authority=false/);
  assert.doesNotMatch(
    source,
    /method:\s*["']POST|\/impact|\.sort\(|\.reduce\(|\bsum\b|\bNumber\b|\bMath\b|\bFX\b|percentage|\?\?\s*0|candidates\[0\]/,
  );
});

test("commerce os exposes native ERP, content factory, and governed agent team", () => {
  const page = read("../app/commerce-os/page.tsx");
  const consoleSource = read("../features/commerce-os/commerce-os-console.tsx");
  const shell = read("../features/dashboard/dashboard-shell.tsx");

  assert.match(page, /<CommerceOsConsole\s*\/>/);
  assert.match(shell, /href="\/commerce-os"/);
  assert.match(consoleSource, /\/backend\/v1\/commerce-os\/workspace/);
  assert.match(consoleSource, /\/backend\/v1\/seller-os\/strategy-packs/);
  assert.match(
    consoleSource,
    /毛子、荔枝、芒果店长、店小秘、妙手、无忧易售、Seerfar 与 LinkFox/,
  );
  assert.match(consoleSource, /Must-have 能力基准/);
  assert.match(consoleSource, /安全能力不可省略/);
  assert.match(consoleSource, /项工作流已映射/);
  assert.match(consoleSource, /映射 ≠ 实现 · 外部写关闭/);
  assert.match(consoleSource, /workflow_mapping\.capabilities/);
  assert.match(consoleSource, /NATIVE INTELLIGENCE INGESTION/);
  assert.match(consoleSource, /href="\/oms"/);
  assert.match(consoleSource, /打开原生 OMS/);
  assert.match(consoleSource, /href="\/pim"/);
  assert.match(consoleSource, /打开商品主数据 PIM/);
  assert.match(consoleSource, /href="\/listings"/);
  assert.match(consoleSource, /打开 Listing 生命周期/);
  assert.match(consoleSource, /href="\/media-factory"/);
  assert.match(consoleSource, /打开内容媒体工厂/);
  assert.match(consoleSource, /href="\/sourcing-intelligence"/);
  assert.match(consoleSource, /打开原生供应智能/);
  assert.match(consoleSource, /href="\/seller-erp-bridge"/);
  assert.match(consoleSource, /打开授权 Seller ERP Bridge/);
  assert.match(consoleSource, /Cookie、localStorage、内部 API 与验证码绕过均被禁止/);
  assert.match(consoleSource, /公开价格 ≠ Supplier Offer/);
  assert.match(consoleSource, /评论\/页面信号 ≠ 销量/);
  assert.match(consoleSource, /来源等级 ≠ 业务事实升级/);
  assert.match(consoleSource, /Ozon 只读 Pilot \/ Run/);
  assert.match(consoleSource, /Ozon 只读 Claim 复核账/);
  assert.match(consoleSource, /formal fact false/);
  assert.match(consoleSource, /Ozon 官方导入 staging/);
  assert.match(consoleSource, /formal promotion false/);
  assert.match(consoleSource, /legacy 不推断 · external write false/);
  assert.match(consoleSource, /Run 通过 Pilot FK 在 SQL/);
  assert.match(consoleSource, /SCOPED MARKET RADAR · EXACT IDENTITY/);
  assert.match(consoleSource, /同一商品先聚合 cohort，再进入候选/);
  assert.match(consoleSource, /listing 数不冒充 SKU/);
  assert.match(consoleSource, /100 件价不能筛 3 件 Pilot/);
  assert.match(consoleSource, /Observation ≠ Offer \/ actual cost/);
  assert.match(consoleSource, /销量推断：关闭/);
  assert.match(consoleSource, /竞品标题和图片不可复制/);
  assert.match(consoleSource, /SCOPED PIM · PASSPORT · CONTENT/);
  assert.match(consoleSource, /审批计划 ≠ 独立 Approval/);
  assert.match(consoleSource, /Approval ≠ 一次性 Permit/);
  assert.match(consoleSource, /Ozon 外部写入：关闭/);
  assert.match(consoleSource, /Agent 可归一、复算、生成草稿与内部任务/);
  assert.match(consoleSource, /不可自批、自发 Permit 或外部写/);
  assert.match(consoleSource, /自动上品数量不是成功指标/);
  assert.doesNotMatch(
    consoleSource,
    /Math\.random|\/commands|\/write-attempt|\/receipt/,
  );
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
  const sellerTier = read("../features/dashboard/seller-tier-panel.tsx");
  const contracts = read("../features/dashboard/contracts.ts");
  const view = read("../features/dashboard/dashboard-view.tsx");

  assert.match(controller, /\/backend\/v1\/operating-analytics\/snapshot/);
  assert.match(controller, /operatingAnalytics/);
  assert.match(view, /SellerTierPanel/);
  assert.match(contracts, /contract_id: "kjds-operating-flow-analytics-v1"/);
  assert.match(contracts, /synthetic_business_data_allowed: false/);
  assert.match(panel, /analytics\.stages\.map/);
  assert.match(panel, /analytics\.coverage\.map/);
  assert.match(panel, /analytics\.pipeline\.map/);
  assert.match(panel, /暂无可复验历史序列/);
  assert.match(panel, /Ozon 外部引用 · 未核权/);
  assert.match(panel, /不等于同行市场价/);
  assert.match(panel, /AI 不能自动选品、联系供应商、采购、改价、发布或投放/);
  assert.match(sellerTier, /\/backend\/v1\/seller-os\/strategy-packs/);
  assert.match(sellerTier, /同一事实核，不同商业包络/);
  assert.match(sellerTier, /打开 Seller OS/);
  assert.match(sellerTier, /打开策略中心/);
  assert.match(sellerTier, /COMMERCIAL PACKS/);
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
  assert.match(contracts, /"approved_customer_service_reply"/);
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
