const assert = require("node:assert/strict");
const { spawn } = require("node:child_process");
const path = require("node:path");
const { chromium } = require("playwright");

const PORT = Number(process.env.LOCAL_DEMO_E2E_PORT || "43292");
const ORIGIN = `http://127.0.0.1:${PORT}`;
const PACKAGE_ROOT = path.resolve(__dirname, "../..");
const VITE = path.join(PACKAGE_ROOT, "node_modules", "vite", "bin", "vite.js");

async function waitForServer() {
  const deadline = Date.now() + 15_000;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(ORIGIN);
      if (response.ok) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error("demo_preview_not_ready");
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
    if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) {
      launchOptions.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
    }
    browser = await chromium.launch(launchOptions);
    const context = await browser.newContext({ serviceWorkers: "allow", viewport: { width: 390, height: 844 } });
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

    await page.goto(`${ORIGIN}/#/profit`, { waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("[data-sw-state]")?.textContent === "离线壳已缓存（7/7）");
    await page.reload({ waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("[data-sw-state]")?.textContent === "离线壳已缓存（7/7）");
    const controlled = await page.evaluate(() => Boolean(navigator.serviceWorker.controller));
    assert.equal(controlled, true);

    offline = true;
    await context.setOffline(true);
    await page.reload({ waitUntil: "load" });
    await page.waitForFunction(() => document.querySelector("[data-sw-state]")?.textContent === "离线壳已缓存（7/7）");
    const result = await page.evaluate(() => ({
      cards: document.querySelectorAll(".matrix-card").length,
      h1: document.querySelector("h1")?.textContent,
      markers: Array.from(document.querySelectorAll(".demo-rail strong"), (node) => node.textContent),
      workspaces: document.querySelectorAll(".workspace-link").length,
    }));
    assert.deepEqual(result, {
      cards: 9,
      h1: "合成利润场景",
      markers: ["LOCAL DEMO", "合成数据", "不计费"],
      workspaces: 9,
    });
    assert.deepEqual(offline503, []);
    assert.deepEqual(outsideRequests, []);
    assert.deepEqual(cspViolations, []);
    await context.setOffline(false);
    await context.close();
    console.log(JSON.stringify({ controlled, cspViolations: 0, offline503: 0, outsideRequests: 0, ...result }));
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
