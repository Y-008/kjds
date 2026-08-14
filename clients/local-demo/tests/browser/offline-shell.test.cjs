const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const PORT = Number(process.env.LOCAL_DEMO_E2E_PORT || "43292");
const ORIGIN = `http://127.0.0.1:${PORT}`;
const PACKAGE_ROOT = path.resolve(__dirname, "../..");
const VITE = path.join(PACKAGE_ROOT, "node_modules", "vite", "bin", "vite.js");
const ROUTES = [
  "dashboard", "sourcing", "pim", "listings", "oms", "fulfillment",
  "customer-service", "growth", "profit",
];

async function waitForServer() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      if ((await fetch(ORIGIN)).ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("demo_preview_not_ready");
}

async function verifyViewport(browser, spec) {
  const context = await browser.newContext({ serviceWorkers: "allow", viewport: spec });
  const page = await context.newPage();
  const cspViolations = [];
  const outsideRequests = [];
  const offline503 = [];
  let offline = false;
  page.on("console", (message) => {
    const text = message.text();
    if (text.includes("Refused to") || text.includes("violates the following Content Security Policy")) {
      cspViolations.push(text);
    }
  });
  page.on("request", (request) => {
    const url = request.url();
    if (!url.startsWith(`${ORIGIN}/`) || url.includes("/backend")) outsideRequests.push(url);
  });
  page.on("response", (response) => {
    if (offline && response.status() === 503) offline503.push(response.url());
  });

  await page.goto(`${ORIGIN}/#/dashboard`, { waitUntil: "load" });
  await page.waitForFunction(() => document.querySelector("[data-sw-state]")?.textContent === "离线壳已缓存（7/7）");
  await page.reload({ waitUntil: "load" });
  await page.waitForFunction(() => document.querySelector("[data-sw-state]")?.textContent === "离线壳已缓存（7/7）");
  const controlled = await page.evaluate(() => Boolean(navigator.serviceWorker.controller));
  assert.equal(controlled, true);

  const routeResults = [];
  for (const route of ROUTES) {
    await page.evaluate((nextRoute) => { location.hash = `#/${nextRoute}`; }, route);
    await page.waitForFunction((nextRoute) => location.hash === `#/${nextRoute}` && document.querySelectorAll("[data-query-item]").length > 0, route);
    const beforeHash = await page.locator(".runtime-strip > div").nth(2).locator("strong").textContent();
    await page.click("[data-advance]");
    await page.waitForFunction(() => document.querySelector("[data-operation]")?.textContent?.includes("模拟推进完成"));
    const afterHash = await page.locator(".runtime-strip > div").nth(2).locator("strong").textContent();
    const sequence = await page.locator("[data-sequence]").textContent();
    assert.notEqual(afterHash, beforeHash, route);
    assert.notEqual(sequence, "SEQ 0", route);
    assert.equal(await page.locator("[data-operation]").getAttribute("class"), "operation-state");
    routeResults.push(route);
  }

  await page.click('[data-hero-flow="demo-flow-opportunity-listing"]');
  await page.waitForFunction(() => document.querySelector("[data-operation]")?.textContent?.includes("机会发现 → 商品建档 → Listing 预览"));
  await page.evaluate(() => { location.hash = "#/listings"; });
  await page.waitForFunction(() => document.querySelector(".query-list")?.textContent?.includes("generated"));
  const beforeErrorSequence = await page.locator("[data-sequence]").textContent();
  await page.click("[data-error-replay]");
  await page.waitForFunction(() => document.querySelector("[data-operation]")?.textContent?.includes("错误已确定性重放"));
  assert.equal(await page.locator("[data-sequence]").textContent(), beforeErrorSequence);
  assert.ok((await page.locator("[data-operation]").textContent()).includes("demo_expected_state_mismatch"));

  await page.click("[data-reset]");
  await page.waitForFunction(() => document.querySelector("[data-operation]")?.textContent?.includes("哈希已恢复"));
  assert.equal(await page.locator("[data-sequence]").textContent(), "SEQ 0");
  assert.equal(await page.locator(".runtime-strip > div").nth(3).locator("strong").textContent(), "HASH RESTORED");

  await page.click('[data-hero-flow="demo-flow-settlement-profit"]');
  await page.waitForFunction(() => document.querySelector("[data-operation]")?.textContent?.includes("结算 → 费用 → 现金利润 → 决策"));
  await page.evaluate(() => { location.hash = "#/profit"; });
  await page.waitForFunction(() => document.querySelector(".query-list")?.textContent?.includes("allocated"));
  const profitText = await page.locator(".query-list").textContent();
  for (const decision of ["stop", "fix", "continue", "no_data"]) assert.ok(profitText.includes(decision), decision);

  const metrics = await page.evaluate(() => ({
    bodyWidth: document.body.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    htmlWidth: document.documentElement.scrollWidth,
    markers: Array.from(document.querySelectorAll(".demo-rail strong"), (node) => node.textContent),
    workspaces: document.querySelectorAll(".workspace-link").length,
  }));
  assert.equal(metrics.bodyWidth, spec.width);
  assert.equal(metrics.htmlWidth, spec.width);
  assert.equal(metrics.clientWidth, spec.width);
  assert.deepEqual(metrics.markers, ["LOCAL DEMO", "合成数据", "不计费"]);
  assert.equal(metrics.workspaces, 9);

  if (process.env.LOCAL_DEMO_ARTIFACT_DIR) {
    fs.mkdirSync(process.env.LOCAL_DEMO_ARTIFACT_DIR, { recursive: true });
    await page.screenshot({
      fullPage: true,
      path: path.join(process.env.LOCAL_DEMO_ARTIFACT_DIR, `bas194-${spec.width}.png`),
    });
  }

  offline = true;
  await context.setOffline(true);
  await page.reload({ waitUntil: "load" });
  await page.waitForFunction(() => document.querySelector("[data-sw-state]")?.textContent === "离线壳已缓存（7/7）");
  assert.equal(await page.locator("h1").textContent(), "合成利润场景");
  assert.ok(await page.locator("[data-query-item]").count());
  assert.deepEqual(offline503, []);
  assert.deepEqual(outsideRequests, []);
  assert.deepEqual(cspViolations, []);
  await context.setOffline(false);
  await context.close();
  return { width: spec.width, controlled, routesApplied: routeResults.length, cspViolations: 0, offline503: 0, outsideRequests: 0 };
}

(async () => {
  const server = spawn(process.execPath, [VITE, "preview", "--host", "127.0.0.1", "--port", String(PORT), "--strictPort"], {
    cwd: PACKAGE_ROOT,
    stdio: "ignore",
    windowsHide: true,
  });
  let browser;
  try {
    await waitForServer();
    const launchOptions = { headless: true };
    if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) launchOptions.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
    browser = await chromium.launch(launchOptions);
    const results = [];
    for (const spec of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      results.push(await verifyViewport(browser, spec));
    }
    console.log(JSON.stringify({ viewports: results, heroFlows: 3, markers: ["LOCAL DEMO", "合成数据", "不计费"] }));
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
