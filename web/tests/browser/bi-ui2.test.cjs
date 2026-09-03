const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { AxeBuilder } = require("@axe-core/playwright");
const { chromium } = require("playwright");

const PORT = Number(process.env.KJDS_BI_E2E_PORT || "43319");
const ORIGIN = `http://127.0.0.1:${PORT}`;
const WEB_ROOT = path.resolve(__dirname, "../..");
const NEXT = path.join(WEB_ROOT, "node_modules", "next", "dist", "bin", "next");
const SHA = "a".repeat(64);
const SOURCE_AS_OF = "2026-08-19T10:30:00+00:00";

function session(storeRefs = ["store-a", "store-b"]) {
  return {
    authenticated: true,
    auth_mode: "legacy",
    email: null,
    actor_id: "browser-reviewer",
    roles: ["monitor"],
    tenant_ref: "tenant-a",
    store_refs: storeRefs,
    default_store_ref: storeRefs[0] ?? "",
  };
}

function workItem() {
  return {
    id: "work-1",
    item_type: "runtime_operation",
    source_type: "operating_task",
    source_id: "task-1",
    agent_id: "agent-1",
    agent_name: "经营 Agent",
    title: "补齐当前店铺增长权威",
    status: "waiting_for_upstream",
    priority: "high",
    risk: "high",
    next_action: "绑定当前店铺的真实增长 Evidence",
    human_required: true,
    evidence_ids: ["evd-browser-1"],
    gate: null,
    progress: null,
    due_at: null,
    overdue: null,
    escalation_level: null,
    automatic_execution: false,
    platform_write_allowed: false,
  };
}

function analytics(storeRef, asOf) {
  const sourceGaps = [
    "scoped_growth_authority_missing",
    "scoped_rfq_authority_missing",
    "scoped_procurement_authority_missing",
    "scoped_execution_authority_missing",
    "scoped_finance_authority_missing",
    "scoped_media_authority_missing",
    "scoped_readiness_authority_missing",
  ];
  return {
    contract_id: "kjds-operating-flow-analytics-v1",
    store_ref: storeRef,
    scope: {
      tenant_ref: "tenant-a",
      entity_ref: "entity-a",
      store_ref: storeRef,
      scope_authority_sha256: SHA,
      status: "ready",
    },
    status: "partial",
    source_as_of: asOf || SOURCE_AS_OF,
    snapshot_sha256: SHA,
    summary: {
      catalog_items: 2,
      bound_listings: 1,
      available_stock: 3,
      external_image_references: 2,
      external_video_references: 0,
      gate_blockers: 0,
      growth_snapshot_skus: 0,
      rfq_packages: 0,
      verified_dispatch_proofs: 0,
      formal_finance_entries: 0,
      ready_execution_plans: 0,
    },
    recommended_playbook: {
      id: "scoped_catalog_refinement",
      label: "作用域目录核验",
      reasons: ["目录事实已通过 tenant/entity/store 与 Evidence authority"],
      advisory_only: true,
      automatic_mode_switch: false,
    },
    focal_listing: {
      offer_id: "offer-a",
      marketplace_sku: "sku-a",
      canonical_product_id: "product-a",
      name: "Browser verified listing",
      currency_code: "RUB",
      price: "990.00",
      min_price: null,
      old_price: null,
      available_stock: 3,
      status: "active",
      status_name: "Active",
      moderation_status: null,
      observed_at: SOURCE_AS_OF,
      source_evidence_id: "evd-browser-1",
      item_hash: SHA,
      image_references: [],
      video_reference_count: 0,
      image_reference_count: 0,
      document_reference_count: 0,
      media_rights_status: "unverified_external_reference",
      approved_media_roles: 0,
      required_media_roles: 7,
      passports_ready: false,
      supplier_count: 0,
      complete_profit_scenario_count: 0,
      growth_observation: null,
    },
    stages: [
      {
        id: "catalog",
        step: "01",
        label: "Ozon 店铺同步",
        workspace: "growth",
        status: "verified",
        current: 2,
        target: 1,
        progress_percent: 100,
        next_action: "核对作用域内 Listing",
        source_ids: ["evd-browser-1"],
        facts: ["2 个作用域内目录商品"],
      },
      {
        id: "growth",
        step: "07",
        label: "价格 / 内容 / 广告实验",
        workspace: "growth",
        status: "no_data",
        current: 0,
        target: 1,
        progress_percent: 0,
        next_action: "等待原生作用域 Evidence",
        source_ids: [],
        facts: [],
      },
    ],
    coverage: [
      { id: "official_catalog", label: "店铺目录", current: 2, target: 1, percent: 100, unit: "Ozon 目录原件" },
      { id: "growth_truth", label: "增长真源", current: 0, target: 1, percent: 0, unit: "有证据增长快照" },
    ],
    pipeline: [
      { id: "catalog", label: "店铺目录", value: 2, unit: "商品" },
      { id: "growth", label: "有增长快照", value: 0, unit: "SKU" },
    ],
    priority_items: [workItem()],
    data_gaps: sourceGaps,
    source_gaps: sourceGaps,
    excluded_sources: ["legacy_global_catalog", "legacy_global_finance"],
    guardrails: {
      advisory_only: true,
      browser_gate_recalculation: false,
      synthetic_business_data_allowed: false,
      automatic_product_selection: false,
      automatic_supplier_contact: false,
      automatic_procurement: false,
      automatic_pricing: false,
      automatic_listing: false,
      automatic_ad_spend: false,
      platform_write_allowed: false,
    },
  };
}

function briefing(storeRef, asOf) {
  return {
    contract_id: "kjds-operating-workbench-briefing-v1",
    mode: "scoped_shadow_advisory",
    status: "partial",
    scope: {
      tenant_ref: "tenant-a",
      entity_ref: "entity-a",
      store_ref: storeRef,
      scope_authority_sha256: SHA,
    },
    as_of: asOf || SOURCE_AS_OF,
    snapshot_sha256: SHA,
    summary: {
      gate_blockers: 0,
      runtime_items: 1,
      recommendations: 0,
      visible_items: 1,
      candidate_count: 0,
      selection_ready_count: 0,
    },
    agents: [{
      agent_id: "agent-1",
      name: "经营 Agent",
      status: "needs_attention",
      work_item_count: 1,
      current_focus: "补齐当前店铺增长权威",
      automatic_execution: false,
    }],
    work_items: [workItem()],
    candidate_portfolio: {
      status: "no_data",
      candidate_count: 0,
      selection_ready_count: 0,
      rows: [],
      source_gap: "scoped_readiness_authority_missing",
      advisory_only: true,
    },
    source_gaps: ["scoped_readiness_authority_missing"],
    excluded_sources: ["legacy_global_gate_readiness"],
    guardrails: {
      advisory_only: true,
      automatic_execution: false,
      automatic_product_selection: false,
      automatic_procurement: false,
      automatic_pricing: false,
      automatic_listing: false,
      platform_write_allowed: false,
      third_party_fact_promotion_allowed: false,
    },
  };
}

async function installApiMocks(page, options = {}) {
  const calls = [];
  const storeRefs = options.storeRefs ?? ["store-a", "store-b"];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (url.pathname === "/auth/session") {
      calls.push({ kind: "session", method, url: url.href });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(session(storeRefs)) });
    }
    if (url.pathname === "/backend/v1/operating-analytics/snapshot") {
      calls.push({ kind: "analytics", method, url: url.href });
      if (options.businessFailure?.active) {
        return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "simulated_refresh_failure" }) });
      }
      const storeRef = url.searchParams.get("store_ref") || "";
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(analytics(storeRef, url.searchParams.get("as_of"))) });
    }
    if (url.pathname === "/backend/v1/operating-workbench/briefing") {
      calls.push({ kind: "briefing", method, url: url.href });
      if (options.businessFailure?.active) {
        return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "simulated_refresh_failure" }) });
      }
      const storeRef = url.searchParams.get("store_ref") || "";
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(briefing(storeRef, url.searchParams.get("as_of"))) });
    }
    if (url.pathname === "/backend/v1/evidence/evd-browser-1") {
      calls.push({ kind: "evidence", method, url: url.href });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        id: "evd-browser-1", sha256: SHA, byte_size: 128, filename: "catalog.json",
        content_type: "application/json", source: "ozon_product_read", source_ref: "offer-a",
        grade: "A", effective_at: SOURCE_AS_OF, effective_until: null, recorded_at: SOURCE_AS_OF,
        created_by: "browser-reviewer", metadata: {},
      }) });
    }
    if (url.pathname === "/backend/v1/evidence/evd-browser-1/verify") {
      calls.push({ kind: "verify", method, url: url.href });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        evidence_id: "evd-browser-1", expected_sha256: SHA, actual_sha256: SHA, byte_size: 128, valid: true,
      }) });
    }
    if (url.pathname === "/backend/v1/evidence/evd-browser-1/lineage") {
      calls.push({ kind: "lineage", method, url: url.href });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify([{
        id: "lin-1", from_type: "evidence", from_id: "evd-browser-1", to_type: "marketplace_listing",
        to_id: "offer-a", relationship: "catalog_basis", created_by: "browser-reviewer", recorded_at: SOURCE_AS_OF,
      }]) });
    }
    if (url.pathname.includes("/backend/v1/agent-control/projects/")) {
      calls.push({ kind: "agent", method, url: url.href });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status_rail: [] }) });
    }
    return route.continue();
  });
  return calls;
}

async function waitForServer() {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try {
      if ((await fetch(ORIGIN)).ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("bi_next_server_not_ready");
}

async function assertNoSeriousAxeViolations(page, contextLabel) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const violations = results.violations.filter((item) => item.impact === "critical" || item.impact === "serious");
  assert.deepEqual(violations.map((item) => ({ id: item.id, impact: item.impact, targets: item.nodes.map((node) => node.target) })), [], contextLabel);
}

async function assertNoHorizontalOverflow(page, contextLabel) {
  const widths = await page.evaluate(() => ({
    body: document.body.scrollWidth,
    html: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  assert.ok(widths.body <= widths.client + 1, `${contextLabel}: body overflow`);
  assert.ok(widths.html <= widths.client + 1, `${contextLabel}: html overflow`);
}

function assertNoAgentRequests(calls, contextLabel) {
  assert.equal(calls.filter((item) => item.kind === "agent").length, 0, `${contextLabel}: unexpected agent-control request`);
}

async function verifyOverviewViewport(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const calls = await installApiMocks(page);
  await page.goto(`${ORIGIN}/bi/overview?store_ref=store-a`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "BI Overview" }).waitFor();
  await page.getByText("Browser verified listing").waitFor();
  await page.getByRole("heading", { name: "从结论到动作" }).waitFor();
  for (const label of ["01 · 结论", "02 · 证据边界", "03 · 下一动作", "04 · 责任与复核"]) {
    await page.getByText(label).waitFor();
  }
  await page.getByRole("img", { name: /覆盖率/ }).waitFor();
  assertNoAgentRequests(calls, `overview ${viewport.width}`);
  await assertNoHorizontalOverflow(page, `overview ${viewport.width}`);
  assert.deepEqual(errors, []);

  const analyticsCall = calls.find((item) => item.kind === "analytics");
  const briefingCall = calls.find((item) => item.kind === "briefing");
  assert.ok(analyticsCall && briefingCall);
  const analyticsQuery = new URL(analyticsCall.url).searchParams;
  const briefingQuery = new URL(briefingCall.url).searchParams;
  assert.equal(analyticsQuery.get("store_ref"), "store-a");
  assert.equal(briefingQuery.get("store_ref"), "store-a");
  assert.equal(analyticsQuery.get("as_of"), briefingQuery.get("as_of"));
  const wallboardHref = await page.getByRole("link", { name: "打开大屏" }).getAttribute("href");
  const briefingHref = await page.getByRole("link", { name: "经营简报" }).getAttribute("href");
  assert.ok(wallboardHref);
  assert.ok(briefingHref);
  assert.equal(new URL(wallboardHref, ORIGIN).searchParams.get("store_ref"), "store-a");
  assert.equal(new URL(wallboardHref, ORIGIN).searchParams.get("as_of"), analyticsQuery.get("as_of"));
  assert.equal(new URL(briefingHref, ORIGIN).searchParams.get("store_ref"), "store-a");
  assert.equal(new URL(briefingHref, ORIGIN).searchParams.get("as_of"), analyticsQuery.get("as_of"));

  await page.keyboard.press("Control+K");
  const commandDialog = page.getByRole("dialog", { name: "全局跳转" });
  await commandDialog.waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.tagName), "INPUT");
  for (let index = 0; index < 8; index += 1) await page.keyboard.press("Tab");
  assert.equal(await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]'))), true);
  await page.keyboard.press("Escape");
  assert.equal(await page.evaluate(() => document.activeElement?.textContent?.includes("跳转") ?? false), true);

  const tableToggle = page.getByRole("button", { name: "查看数据表" }).first();
  await tableToggle.click();
  const table = page.getByRole("table").first();
  await table.waitFor();
  assert.equal(await table.locator("xpath=..").getAttribute("tabindex"), "0");

  const queueSearch = page.getByRole("search", { name: "优先工作项筛选" });
  await queueSearch.getByRole("searchbox", { name: "搜索优先工作项" }).fill("不存在的事项");
  await page.getByText("本地筛选匹配 0 项 · 表格展示 0 项").waitFor();
  assert.equal(await queueSearch.getByRole("button", { name: "清除筛选" }).isEnabled(), true);
  await queueSearch.getByRole("button", { name: "清除筛选" }).click();
  await page.getByText("当前作用域返回 1 项 · 表格展示前 1 项").waitFor();
  await queueSearch.getByRole("combobox", { name: "按风险筛选" }).selectOption("high");
  await page.getByText("本地筛选匹配 1 项 · 表格展示 1 项").waitFor();
  await queueSearch.getByRole("button", { name: "清除筛选" }).click();

  await page.getByRole("button", { name: /回看原始 Evidence/ }).click();
  const evidenceDialog = page.getByRole("dialog", { name: "证据回看" });
  await evidenceDialog.waitFor();
  await evidenceDialog.getByText("catalog.json").waitFor();
  assert.equal(calls.filter((item) => item.kind === "evidence").length, 1);
  assert.equal(calls.filter((item) => item.kind === "verify").length, 1);
  assert.equal(calls.filter((item) => item.kind === "lineage").length, 1);
  assert.equal(calls.some((item) => item.url.endsWith("/content")), false);
  for (let index = 0; index < 6; index += 1) await page.keyboard.press("Tab");
  assert.equal(await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]'))), true);
  await assertNoSeriousAxeViolations(page, `overview dialog ${viewport.width}`);
  await page.keyboard.press("Escape");
  assert.equal(await page.evaluate(() => document.activeElement?.textContent?.includes("回看原始 Evidence") ?? false), true);

  const skipLink = page.getByRole("link", { name: "跳转到主内容" });
  await skipLink.focus();
  await page.keyboard.press("Enter");
  assert.equal(await page.evaluate(() => document.activeElement?.id), "main-content");
  await assertNoSeriousAxeViolations(page, `overview ${viewport.width}`);

  if (process.env.KJDS_BI_ARTIFACT_DIR) {
    fs.mkdirSync(process.env.KJDS_BI_ARTIFACT_DIR, { recursive: true });
    await page.screenshot({
      fullPage: true,
      path: path.join(process.env.KJDS_BI_ARTIFACT_DIR, `bi-overview-${viewport.width}.png`),
    });
  }
  await context.close();
}

async function verifyWallboardViewport(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const calls = await installApiMocks(page);
  await page.goto(`${ORIGIN}/bi/wallboard?store_ref=store-a`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "经营流转大屏" }).waitFor();
  await assertNoAgentRequests(calls, `wallboard ${viewport.width}`);
  await assertNoHorizontalOverflow(page, `wallboard ${viewport.width}`);
  await assertNoSeriousAxeViolations(page, `wallboard ${viewport.width}`);

  const frameBox = await page.locator("#wallboard-content").evaluate((node) => {
    const parent = node.parentElement;
    if (!parent) return null;
    const rect = parent.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  });
  assert.ok(frameBox);
  if (viewport.width >= 720) {
    const ratio = frameBox.width / frameBox.height;
    assert.ok(Math.abs(ratio - 16 / 9) < 0.08, `wallboard frame ratio at ${viewport.width}: ${ratio}`);
  }

  await page.getByRole("button", { name: "阶段覆盖" }).click();
  await page.getByText("阶段与覆盖").waitFor();
  await assertNoHorizontalOverflow(page, `wallboard flow ${viewport.width}`);

  await page.getByRole("button", { name: "异常优先" }).click();
  await page.getByText("异常优先级").waitFor();
  await page.getByRole("button", { name: /查看 Evidence/ }).first().click();
  const evidenceDialog = page.getByRole("dialog", { name: "证据回看" });
  await evidenceDialog.waitFor();
  await evidenceDialog.getByText("catalog.json").waitFor();
  assert.equal(calls.filter((item) => item.kind === "agent").length, 0);
  assert.equal(calls.filter((item) => item.kind === "evidence").length, 1);
  assert.equal(calls.filter((item) => item.kind === "verify").length, 1);
  assert.equal(calls.filter((item) => item.kind === "lineage").length, 1);
  await assertNoSeriousAxeViolations(page, `wallboard dialog ${viewport.width}`);
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: /查看 Evidence/ }).first().waitFor();
  await context.close();
}

async function verifyBriefingViewport(browser, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const calls = await installApiMocks(page);
  await page.goto(`${ORIGIN}/bi/briefing?store_ref=store-a`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "经营简报" }).waitFor();
  await assertNoAgentRequests(calls, `briefing ${viewport.width}`);
  await assertNoHorizontalOverflow(page, `briefing ${viewport.width}`);
  await assertNoSeriousAxeViolations(page, `briefing ${viewport.width}`);

  const wallboardHref = await page.getByRole("link", { name: "打开大屏" }).getAttribute("href");
  const overviewHref = await page.getByRole("link", { name: "返回总览" }).getAttribute("href");
  assert.ok(wallboardHref);
  assert.ok(overviewHref);
  assert.equal(new URL(wallboardHref, ORIGIN).searchParams.get("store_ref"), "store-a");
  assert.equal(new URL(overviewHref, ORIGIN).searchParams.get("store_ref"), "store-a");

  await page.getByRole("tab", { name: "2. 六项经营指标" }).click();
  await page.getByText("变化、同比、目标差与趋势没有服务端历史合同时统一保持 no_data").waitFor();
  await assertNoHorizontalOverflow(page, `briefing metrics ${viewport.width}`);

  await page.getByRole("tab", { name: "3. Top 3 异常" }).click();
  await page.getByText("严格保留 OperatingWorkbench 的服务端顺序").waitFor();
  await page.getByRole("button", { name: /Evidence/ }).first().click();
  const evidenceDialog = page.getByRole("dialog", { name: "证据回看" });
  await evidenceDialog.waitFor();
  await evidenceDialog.getByText("catalog.json").waitFor();
  assert.equal(calls.filter((item) => item.kind === "evidence").length, 1);
  assert.equal(calls.filter((item) => item.kind === "verify").length, 1);
  assert.equal(calls.filter((item) => item.kind === "lineage").length, 1);
  await assertNoSeriousAxeViolations(page, `briefing dialog ${viewport.width}`);
  await page.keyboard.press("Escape");

  await page.getByRole("tab", { name: "4. 缺口与 Evidence" }).click();
  await page.getByRole("heading", { name: "数据缺口", exact: true }).waitFor();
  await page.getByRole("button", { name: /查看 Evidence/ }).first().waitFor();
  await assertNoHorizontalOverflow(page, `briefing governance ${viewport.width}`);
  await context.close();
}

async function verifyUnauthorizedScope(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();
  const calls = await installApiMocks(page, { storeRefs: ["store-a"] });
  await page.goto(`${ORIGIN}/bi/overview?store_ref=not-authorized`, { waitUntil: "networkidle" });
  await page.getByText(/FORBIDDEN|无权|未授权/).first().waitFor();
  assert.equal(calls.filter((item) => item.kind === "analytics" || item.kind === "briefing" || item.kind === "agent").length, 0);
  await context.close();
}

async function verifyRefreshFailureClearsSnapshot(browser) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
  const page = await context.newPage();
  const businessFailure = { active: false };
  await installApiMocks(page, { businessFailure });
  await page.goto(`${ORIGIN}/bi/overview?store_ref=store-a`, { waitUntil: "networkidle" });
  await page.getByText("Browser verified listing").waitFor();
  businessFailure.active = true;
  await page.getByRole("button", { name: "刷新快照" }).click();
  await page.getByText("simulated_refresh_failure").first().waitFor();
  await page.getByText("Browser verified listing").waitFor({ state: "detached" });
  assert.equal(await page.getByText("ERROR", { exact: true }).first().isVisible(), true);
  await context.close();
}

async function verifyReducedMotionWallboard(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  await installApiMocks(page);
  await page.goto(`${ORIGIN}/bi/wallboard?store_ref=store-a`, { waitUntil: "networkidle" });
  const live = page.getByRole("status").filter({ hasText: /当前场景/ });
  await live.waitFor();
  const before = await live.textContent();
  await page.waitForTimeout(13_000);
  const after = await live.textContent();
  assert.equal(after, before);
  assert.match(after || "", /减少动态|手动|关闭/);
  await assertNoSeriousAxeViolations(page, "wallboard reduced motion");
  await context.close();
}

(async () => {
  const server = spawn(process.execPath, [NEXT, "start", "--hostname", "127.0.0.1", "--port", String(PORT)], {
    cwd: WEB_ROOT,
    stdio: "ignore",
    windowsHide: true,
  });
  let browser;
  try {
    await waitForServer();
    const launchOptions = { headless: true };
    const executablePath = resolveChromiumExecutablePath();
    if (executablePath) {
      launchOptions.executablePath = executablePath;
    }
    browser = await chromium.launch(launchOptions);
    for (const viewport of [
      { width: 390, height: 844 },
      { width: 1280, height: 720 },
      { width: 1440, height: 900 },
      { width: 1920, height: 1080 },
    ]) {
      await verifyOverviewViewport(browser, viewport);
      await verifyWallboardViewport(browser, viewport);
      await verifyBriefingViewport(browser, viewport);
    }
    await verifyUnauthorizedScope(browser);
    await verifyRefreshFailureClearsSnapshot(browser);
    await verifyReducedMotionWallboard(browser);
    console.log(JSON.stringify({ routes: ["/bi/overview", "/bi/wallboard", "/bi/briefing"], viewports: [390, 1280, 1440, 1920], a11y: "axe+keyboard", unauthorizedBusinessRequests: 0, staleSnapshotAfterRefreshFailure: false, agentRequestsOnBiRoutes: 0 }));
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

function resolveChromiumExecutablePath() {
  const candidates = [
    process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return null;
}
