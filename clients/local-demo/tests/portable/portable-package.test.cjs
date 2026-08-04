const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const { createHash } = require("node:crypto");
const { once } = require("node:events");
const { existsSync } = require("node:fs");
const { mkdir, readFile, realpath, rm, writeFile } = require("node:fs/promises");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const test = require("node:test");
const { chromium } = require("playwright");

const PACKAGE_ROOT = path.resolve(__dirname, "../..");
const TEST_ROOT = path.join(PACKAGE_ROOT, ".runtime", "portable-test-copy");
const BUILD_A = path.join(TEST_ROOT, "build-a");
const BUILD_B = path.join(TEST_ROOT, "build-b");
const EXTRACT = path.join(TEST_ROOT, "extract");
const ZIP_NAME = "KJDS-Local-Demo-v2.zip";
const MANIFEST_NAME = "KJDS-Local-Demo-v2.manifest.json";
const ORIGIN = "http://127.0.0.1:43195";

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

function runNode(args, options = {}) {
  return spawnSync(process.execPath, args, {
    cwd: PACKAGE_ROOT,
    encoding: "utf8",
    timeout: 15_000,
    windowsHide: true,
    ...options,
  });
}

function request(pathname, { method = "GET", host = "127.0.0.1:43195" } = {}) {
  return new Promise((resolve, reject) => {
    const call = http.request({ hostname: "127.0.0.1", port: 43195, path: pathname, method, headers: { host } }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => resolve({ status: response.statusCode, body: Buffer.concat(chunks) }));
    });
    call.on("error", reject);
    call.end();
  });
}

function rawRequest(target) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: "127.0.0.1", port: 43195 });
    let response = "";
    socket.setEncoding("utf8");
    socket.on("connect", () => socket.write(`GET ${target} HTTP/1.1\r\nHost: 127.0.0.1:43195\r\nConnection: close\r\n\r\n`));
    socket.on("data", (chunk) => { response += chunk; });
    socket.on("end", () => resolve(Number(/^HTTP\/1\.1 (\d{3})/u.exec(response)?.[1])));
    socket.on("error", reject);
  });
}

function waitForReady(child) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("portable_launcher_timeout")), 10_000);
    let output = "";
    child.stdout.on("data", (chunk) => {
      output += chunk.toString();
      if (output.includes("KJDS_LOCAL_DEMO_READY")) {
        clearTimeout(timer);
        resolve(output.trim());
      }
    });
    child.stderr.on("data", (chunk) => { output += chunk.toString(); });
    child.once("exit", (code) => {
      if (!output.includes("KJDS_LOCAL_DEMO_READY")) {
        clearTimeout(timer);
        reject(new Error(`portable_launcher_exit:${code}:${output}`));
      }
    });
  });
}

async function verifyBrowser(browser, viewport, artifactDirectory) {
  const context = await browser.newContext({ serviceWorkers: "allow", viewport });
  const page = await context.newPage();
  const outside = [];
  const csp = [];
  const consoleMessages = [];
  const pageErrors = [];
  const localRequests = [];
  const offline503 = [];
  let offline = false;
  page.on("request", (call) => {
    localRequests.push(call.url());
    if (!call.url().startsWith(`${ORIGIN}/`) || call.url().includes("/backend")) outside.push(call.url());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    const text = message.text();
    consoleMessages.push(`${message.type()}:${text}`);
    if (text.includes("Refused to") || text.includes("violates the following Content Security Policy")) csp.push(text);
  });
  page.on("response", (response) => {
    if (offline && response.status() === 503) offline503.push(response.url());
  });
  await page.goto(`${ORIGIN}/#/dashboard`, { waitUntil: "load" });
  try {
    await page.waitForFunction(
      () => document.querySelector("[data-sw-state]")?.textContent === "离线壳已缓存（7/7）",
      undefined,
      { timeout: 8_000 },
    );
  } catch {
    const diagnostic = await page.evaluate(async () => {
      let manualRegister;
      try {
        manualRegister = await Promise.race([
          navigator.serviceWorker.register("./sw.js", { scope: "./" }).then((item) => `ok:${item.scope}`),
          new Promise((resolve) => setTimeout(() => resolve("pending"), 2_000)),
        ]);
      } catch (error) { manualRegister = `error:${error.message}`; }
      return {
        swState: document.querySelector("[data-sw-state]")?.textContent,
        readyState: document.readyState,
        controlled: Boolean(navigator.serviceWorker.controller),
        manualRegister,
        registrations: (await navigator.serviceWorker.getRegistrations()).map((item) => ({ scope: item.scope, active: item.active?.state })),
      };
    });
    throw new Error(`portable_sw_ready_timeout:${JSON.stringify({ diagnostic, consoleMessages, pageErrors, localRequests })}`);
  }
  assert.equal(await page.locator(".workspace-link").count(), 9);
  assert.equal(await page.locator("[data-hero-flow]").count(), 3);
  assert.deepEqual(await page.locator(".demo-rail strong").allTextContents(), ["LOCAL DEMO", "合成数据", "不计费"]);
  const widths = await page.evaluate(() => ({ body: document.body.scrollWidth, html: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
  assert.deepEqual(widths, { body: viewport.width, html: viewport.width, client: viewport.width });
  if (artifactDirectory) {
    await mkdir(artifactDirectory, { recursive: true });
    await page.screenshot({ fullPage: true, path: path.join(artifactDirectory, `bas195-portable-${viewport.width}.png`) });
  }
  offline = true;
  await context.setOffline(true);
  await page.reload({ waitUntil: "load" });
  await page.waitForFunction(() => document.querySelector("[data-sw-state]")?.textContent === "离线壳已缓存（7/7）");
  assert.equal(await page.locator(".workspace-link").count(), 9);
  assert.equal(await page.locator("[data-hero-flow]").count(), 3);
  assert.deepEqual(outside, []);
  assert.deepEqual(csp, []);
  assert.deepEqual(offline503, []);
  await context.setOffline(false);
  await context.close();
  return { width: viewport.width, offlineReload: true, outside: 0, csp: 0, offline503: 0 };
}

test("portable ZIP is reproducible, safe, cold-startable and cleanup is idempotent", async () => {
  const runtimeRoot = path.join(PACKAGE_ROOT, ".runtime");
  assert.equal(path.dirname(TEST_ROOT), runtimeRoot);
  await rm(TEST_ROOT, { recursive: true, force: true });
  await mkdir(TEST_ROOT, { recursive: true });
  let launcher;
  let extractedRoot;
  try {
    const builder = await import("../../scripts/build-portable.mjs");
    assert.deepEqual(
      builder.canonicalizePortableEntry("portable/start.cmd", Buffer.from("@echo off\r\nnode launcher.mjs\r\n")),
      builder.canonicalizePortableEntry("portable/start.cmd", Buffer.from("@echo off\nnode launcher.mjs\n")),
    );
    const binaryFixture = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a]);
    assert.equal(builder.canonicalizePortableEntry("app/icons/icon.png", binaryFixture), binaryFixture);

    const first = runNode(["scripts/build-portable.mjs", "--output-dir", BUILD_A]);
    const second = runNode(["scripts/build-portable.mjs", "--output-dir", BUILD_B]);
    assert.equal(first.status, 0, first.stderr);
    assert.equal(second.status, 0, second.stderr);
    const zipA = path.join(BUILD_A, ZIP_NAME);
    const zipB = path.join(BUILD_B, ZIP_NAME);
    const manifestA = path.join(BUILD_A, MANIFEST_NAME);
    const manifestB = path.join(BUILD_B, MANIFEST_NAME);
    const [bufferA, bufferB] = await Promise.all([readFile(zipA), readFile(zipB)]);
    assert.equal(sha256(bufferA), sha256(bufferB));
    assert.deepEqual(await readFile(manifestA), await readFile(manifestB));

    const verifier = await import("../../scripts/verify-portable.mjs");
    const verified = await verifier.verifyPortableZip(zipA, manifestA);
    assert.equal(verified.entry_count, 16);
    assert.equal(verified.entry_names.some((name) => name.includes("node_modules")), false);
    for (const invalid of ["/absolute", "C:/absolute", "KJDS-Local-Demo-v2/../escape", "KJDS-Local-Demo-v2\\file"]) {
      assert.throws(() => verifier.assertSafeEntryName(invalid));
    }
    assert.throws(() => verifier.assertUniqueNames(["KJDS-Local-Demo-v2/a", "KJDS-Local-Demo-v2/A"]));
    assert.throws(() => verifier.assertRegularEntry("KJDS-Local-Demo-v2/link", (0o120777 << 16) >>> 0));
    const cleanupModule = await import("../../portable/cleanup.mjs");
    await assert.rejects(
      () => cleanupModule.waitForProcessExit(42, { timeoutMs: 0, isAlive: () => true }),
      /portable_cleanup_process_refused_exit/u,
    );

    const text = verified.entries
      .filter((entry) => /\.(?:css|html|js|json|md|mjs|ps1|cmd|webmanifest)$/u.test(entry.relative))
      .map((entry) => entry.buffer.toString("utf8"))
      .join("\n");
    for (const forbidden of [
      "https://", "/backend", "apps/control_plane", "web.app.backend", "KJDS_API_KEY",
      "SUPABASE_URL", "SUPABASE_KEY", ["-----BEGIN", "PRIVATE", "KEY-----"].join(" "), "AKIA",
    ]) assert.equal(text.includes(forbidden), false, forbidden);
    const urls = text.match(/https?:\/\/[^\s)`"']+/gu) ?? [];
    assert.ok(
      urls.every((url) => url.startsWith("http://127.0.0.1:43195") || url.includes("${")),
      urls.join(","),
    );

    const extractor = await import("../../scripts/extract-portable.mjs");
    extractedRoot = await extractor.extractPortable(zipA, EXTRACT);
    assert.equal(await realpath(extractedRoot), extractedRoot);
    assert.equal(existsSync(path.join(extractedRoot, ".runtime")), false);

    launcher = spawn(process.execPath, [path.join(extractedRoot, "launcher.mjs")], {
      cwd: extractedRoot,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    const ready = await waitForReady(launcher);
    assert.match(ready, /127\.0\.0\.1:43195/u);
    assert.equal((await request("/")).status, 200);
    const head = await request("/assets/app.js", { method: "HEAD" });
    assert.equal(head.status, 200);
    assert.equal(head.body.length, 0);
    assert.equal((await request("/", { method: "POST" })).status, 405);
    assert.equal((await request("/", { host: "evil.example" })).status, 421);
    assert.equal((await request("/backend")).status, 403);
    assert.equal(await rawRequest("/%2e%2e/README.md"), 403);

    const launchOptions = { headless: true };
    if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) launchOptions.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
    const browser = await chromium.launch(launchOptions);
    const browserResults = [];
    try {
      for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
        browserResults.push(await verifyBrowser(browser, viewport, process.env.LOCAL_DEMO_ARTIFACT_DIR));
      }
    } finally {
      await browser.close();
    }

    const cleanup = runNode([path.join(extractedRoot, "cleanup.mjs")], { cwd: extractedRoot });
    assert.equal(cleanup.status, 0, cleanup.stderr);
    assert.match(cleanup.stdout, /CLEANUP_OK/u);
    if (launcher.exitCode === null) await once(launcher, "exit");
    launcher = undefined;
    assert.equal(existsSync(path.join(extractedRoot, ".runtime")), false);
    const repeatedCleanup = runNode([path.join(extractedRoot, "cleanup.mjs")], { cwd: extractedRoot });
    assert.equal(repeatedCleanup.status, 0, repeatedCleanup.stderr);
    assert.match(repeatedCleanup.stdout, /already_clean/u);

    await mkdir(path.join(extractedRoot, ".runtime"), { recursive: false });
    await writeFile(path.join(extractedRoot, ".runtime", "server-state.json"), `${JSON.stringify({
      schema: "KJDS-portable-runtime/v1",
      package_id: "KJDS-Local-Demo-v2",
      package_root: await realpath(extractedRoot),
      pid: 2_147_000_001,
      host: "127.0.0.1",
      port: 43195,
      cleanup_challenge: "a".repeat(48),
    }, null, 2)}\n`, "utf8");
    const staleCleanup = runNode([path.join(extractedRoot, "cleanup.mjs")], { cwd: extractedRoot });
    assert.equal(staleCleanup.status, 0, staleCleanup.stderr);
    assert.equal(existsSync(path.join(extractedRoot, ".runtime")), false);

    launcher = spawn(process.execPath, [path.join(extractedRoot, "launcher.mjs")], {
      cwd: extractedRoot,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    await waitForReady(launcher);
    const reset = runNode([path.join(extractedRoot, "reset.mjs")], { cwd: extractedRoot });
    assert.equal(reset.status, 0, reset.stderr);
    assert.match(reset.stdout, /RESET_COMPLETE/u);
    if (launcher.exitCode === null) await once(launcher, "exit");
    launcher = undefined;
    assert.equal(existsSync(path.join(extractedRoot, ".runtime")), false);

    const manifestPath = path.join(extractedRoot, "PORTABLE_MANIFEST.json");
    const originalManifest = await readFile(manifestPath, "utf8");
    const tamperedManifest = JSON.parse(originalManifest);
    tamperedManifest.files.push({ path: "extra.txt", sha256: "0".repeat(64), bytes: 0, mode: "100644" });
    await writeFile(manifestPath, `${JSON.stringify(tamperedManifest, null, 2)}\n`, "utf8");
    const rejectedLaunch = runNode([path.join(extractedRoot, "launcher.mjs")], { cwd: extractedRoot, timeout: 5_000 });
    assert.notEqual(rejectedLaunch.status, 0);
    assert.match(rejectedLaunch.stderr, /portable_manifest_allowlist_invalid|portable_package_inventory_invalid/u);
    await writeFile(manifestPath, originalManifest, "utf8");
    console.log(JSON.stringify({
      zipSha256: verified.zip_sha256,
      reproducible: true,
      entries: verified.entry_count,
      launcherSecurity: { loopback: true, methods: "GET_HEAD", hostRejected: true, traversalRejected: true, backendRejected: true },
      browser: browserResults,
      cleanup: "idempotent_no_runtime",
    }));
  } finally {
    if (launcher && launcher.exitCode === null) {
      if (extractedRoot && existsSync(path.join(extractedRoot, "cleanup.mjs"))) {
        runNode([path.join(extractedRoot, "cleanup.mjs")], { cwd: extractedRoot, timeout: 8_000 });
      }
      if (launcher.exitCode === null) launcher.kill("SIGTERM");
      if (launcher.exitCode === null) {
        await Promise.race([once(launcher, "exit"), new Promise((resolve) => setTimeout(resolve, 5_000))]);
      }
    }
    await rm(TEST_ROOT, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
});
