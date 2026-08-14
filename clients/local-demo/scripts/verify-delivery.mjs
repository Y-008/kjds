import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { createWriteStream } from "node:fs";
import {
  copyFile,
  lstat,
  mkdtemp,
  mkdir,
  readFile,
  readdir,
  realpath,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";
import yauzl from "yauzl";
import yazl from "yazl";

import { InMemorySessionStore } from "../src/application/in-memory-session-store.ts";
import { LocalDemoGateway } from "../src/application/local-demo-gateway.ts";
import { loadScenarioPack } from "../src/domain/scenario-pack.ts";
import { buildPortable } from "./build-portable.mjs";
import { extractPortable } from "./extract-portable.mjs";
import { verifyPortableZip } from "./verify-portable.mjs";

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const RUNTIME_ROOT = path.join(PACKAGE_ROOT, ".runtime");
const PORTABLE_ZIP = "KJDS-Local-Demo-v2.zip";
const PORTABLE_MANIFEST = "KJDS-Local-Demo-v2.manifest.json";
const DELIVERY_ROOT = "KJDS-Local-Demo-Delivery-v1";
const DELIVERY_ZIP = `${DELIVERY_ROOT}.zip`;
const DELIVERY_COMPANION = `${DELIVERY_ROOT}.manifest.json`;
const ORIGIN = "http://127.0.0.1:43195";
const FIXED_MTIME = new Date("2000-01-01T00:00:00.000Z");
const FIXED_TIMESTAMP = FIXED_MTIME.toISOString();
const PROFILE_PREFIX = "kjds-b196-";
const PROFILE_MARKER = ".kjds-bas196-profile-root";
const TEXT_PATH = /(?:^|\/)(?:[^/]+\.(?:cmd|css|html|js|json|md|mjs|ps1|ts|webmanifest)|\.kjds-portable-demo-root)$/u;

export function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(",")}]`;
  if (value !== null && typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function inside(parent, candidate) {
  const relative = path.relative(parent, candidate);
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

export function assertDeliveryOutputDirectory(outputDirectory) {
  const output = path.resolve(outputDirectory);
  if (!inside(RUNTIME_ROOT, output)) throw new Error("delivery_output_boundary_invalid");
  return output;
}

export function assertEphemeralProfileRoot(profileRoot) {
  const profile = path.resolve(profileRoot);
  if (!inside(path.resolve(tmpdir()), profile) || !path.basename(profile).startsWith(PROFILE_PREFIX)) {
    throw new Error("delivery_profile_boundary_invalid");
  }
  return profile;
}

async function createEphemeralProfileRoot() {
  const profile = assertEphemeralProfileRoot(await mkdtemp(path.join(tmpdir(), PROFILE_PREFIX)));
  await writeFile(path.join(profile, PROFILE_MARKER), "KJDS-BAS-196\n", "utf8");
  return profile;
}

async function removeEphemeralProfileRoot(profileRoot) {
  const profile = assertEphemeralProfileRoot(profileRoot);
  const info = await lstat(profile);
  if (info.isSymbolicLink() || !info.isDirectory()) throw new Error("delivery_profile_kind_invalid");
  const marker = await readFile(path.join(profile, PROFILE_MARKER), "utf8");
  if (marker !== "KJDS-BAS-196\n") throw new Error("delivery_profile_marker_invalid");
  await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}

async function pathExists(candidate) {
  try {
    await lstat(candidate);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

async function boundedRemove(outputDirectory) {
  const output = assertDeliveryOutputDirectory(outputDirectory);
  try {
    const info = await lstat(output);
    if (info.isSymbolicLink() || !info.isDirectory()) throw new Error("delivery_output_kind_invalid");
  } catch (error) {
    if (error?.code === "ENOENT") return;
    throw error;
  }
  await rm(output, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
}

async function collectRegularFiles(root, prefix = "") {
  const files = [];
  for (const name of (await readdir(root)).sort((left, right) => left.localeCompare(right, "en"))) {
    const absolute = path.join(root, name);
    const info = await lstat(absolute);
    const relative = path.posix.join(prefix, name);
    if (info.isSymbolicLink()) throw new Error(`delivery_scan_symlink:${relative}`);
    if (info.isDirectory()) files.push(...await collectRegularFiles(absolute, relative));
    else if (info.isFile()) files.push({ absolute, relative, bytes: info.size });
    else throw new Error(`delivery_scan_special:${relative}`);
  }
  return files;
}

function textFindings(relative, buffer) {
  if (!TEXT_PATH.test(relative)) return { external: [], backend: [], secret: [] };
  const text = buffer.toString("utf8");
  const external = [];
  for (const match of text.matchAll(/https?:\/\/[^\s)`"'<>]+/gu)) {
    if (match[0].includes("${")) continue;
    const url = new URL(match[0]);
    if (!["127.0.0.1", "localhost", "[::1]"].includes(url.hostname)) external.push(match[0]);
  }
  const backendPath = ["", "backend"].join("/");
  const backend = text.includes(backendPath) ? [backendPath] : [];
  const secretPatterns = [
    /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/u,
    /\bAKIA[0-9A-Z]{16}\b/u,
    /\bgh[pousr]_[A-Za-z0-9_]{30,}\b/u,
    /\bBearer\s+[A-Za-z0-9._~+\/-]{20,}/u,
    /(?:api[_-]?key|password|client[_-]?secret)\s*[:=]\s*["'][^"']{8,}["']/iu,
  ];
  return { external, backend, secret: secretPatterns.some((pattern) => pattern.test(text)) ? [relative] : [] };
}

function summarizeScan(scope, entries, { inspectProductionApp = false } = {}) {
  const inventory = [];
  const externalUrls = [];
  const backendPaths = [];
  const secretValues = [];
  const productionImports = [];
  const productionWrites = [];
  for (const entry of entries) {
    const buffer = entry.buffer;
    inventory.push({ path: entry.relative, bytes: buffer.length, sha256: sha256(buffer) });
    const finding = textFindings(entry.relative, buffer);
    externalUrls.push(...finding.external.map((value) => ({ path: entry.relative, value })));
    backendPaths.push(...finding.backend.map((value) => ({ path: entry.relative, value })));
    secretValues.push(...finding.secret.map((value) => ({ path: entry.relative, value })));
    if (inspectProductionApp && TEXT_PATH.test(entry.relative)) {
      const text = buffer.toString("utf8");
      for (const pattern of ["apps/control_plane", "web.app.backend", "process.env", "node:https", "node:tls", "XMLHttpRequest"]) {
        if (text.includes(pattern)) productionImports.push({ path: entry.relative, pattern });
      }
      for (const pattern of [
        /\bmethod\s*:\s*["'](?:POST|PUT|PATCH|DELETE)["']/iu,
        /\bWebSocket\s*\(/u,
        /\bsendBeacon\s*\(/u,
      ]) {
        if (pattern.test(text)) productionWrites.push({ path: entry.relative, pattern: pattern.source });
      }
    }
  }
  inventory.sort((left, right) => left.path.localeCompare(right.path, "en"));
  const result = {
    scope,
    regular_files: inventory.length,
    symlinks: 0,
    special_files: 0,
    inventory_sha256: sha256(canonicalJson(inventory)),
    external_urls: externalUrls,
    backend_paths: backendPaths,
    secret_values: secretValues,
    production_imports: productionImports,
    production_writes: productionWrites,
  };
  assert.deepEqual(externalUrls, []);
  assert.deepEqual(backendPaths, []);
  assert.deepEqual(secretValues, []);
  assert.deepEqual(productionImports, []);
  assert.deepEqual(productionWrites, []);
  return result;
}

async function scanDirectory(scope, root, options) {
  const files = await collectRegularFiles(root);
  const entries = await Promise.all(files.map(async (file) => ({
    relative: file.relative,
    buffer: await readFile(file.absolute),
  })));
  return summarizeScan(scope, entries, options);
}

async function scanProductSource() {
  const entries = [];
  for (const [rootName, inspectProductionApp] of [["src", true], ["public", false], ["portable", false], ["delivery", false]]) {
    const files = await collectRegularFiles(path.join(PACKAGE_ROOT, rootName), rootName);
    for (const file of files) entries.push({
      relative: file.relative,
      buffer: await readFile(file.absolute),
      inspectProductionApp,
    });
  }
  for (const name of ["index.html", "package.json"]) entries.push({
    relative: name,
    buffer: await readFile(path.join(PACKAGE_ROOT, name)),
    inspectProductionApp: false,
  });
  const basic = summarizeScan("source", entries);
  const appEntries = entries.filter((entry) => entry.inspectProductionApp);
  const app = summarizeScan("source-app", appEntries, { inspectProductionApp: true });
  return { ...basic, app_inventory_sha256: app.inventory_sha256 };
}

export function verifyCurrencyAndSyntheticBoundary(rawScenario) {
  let monetaryFields = 0;
  const currencies = new Set();
  const identifiers = [];
  function visit(value, location = "scenario") {
    if (Array.isArray(value)) return value.forEach((item, index) => visit(item, `${location}[${index}]`));
    if (value === null || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      if (key.endsWith("_minor")) {
        monetaryFields += 1;
        assert.equal(typeof child, "number", `${location}.${key}`);
        assert.match(value.currency, /^[A-Z]{3}$/u, `${location}.currency`);
        currencies.add(value.currency);
      }
      if (key.endsWith("_id") && typeof child === "string") identifiers.push({ key, value: child });
      visit(child, `${location}.${key}`);
    }
  }
  visit(rawScenario);
  assert.ok(monetaryFields > 0);
  assert.deepEqual(rawScenario.synthetic_declaration, {
    demo: true,
    synthetic: true,
    non_billable: true,
    external_side_effect_allowed: false,
  });
  assert.ok(identifiers.length > 0);
  assert.ok(identifiers.every((item) => item.value.startsWith("demo-")), JSON.stringify(identifiers.filter((item) => !item.value.startsWith("demo-"))));
  return {
    monetary_fields_with_currency: monetaryFields,
    currencies: [...currencies].sort(),
    synthetic_declaration: true,
    synthetic_identifier_count: identifiers.length,
    non_demo_identifiers: 0,
  };
}

export async function verifySessionIsolation(roundLabel = "normalized") {
  const raw = JSON.parse(await readFile(path.join(PACKAGE_ROOT, "src/scenarios/enterprise-overview.zh-CN.v2.json"), "utf8"));
  const pack = loadScenarioPack(raw);
  const shared = new InMemorySessionStore();
  const firstId = "demo-session-delivery-a";
  const secondId = "demo-session-delivery-b";
  const first = new LocalDemoGateway(pack, { store: shared, gateway_scope_token: "delivery-scope-a", session_id_factory: () => firstId });
  const second = new LocalDemoGateway(pack, { store: shared, gateway_scope_token: "delivery-scope-b", session_id_factory: () => secondId });
  const missing = new LocalDemoGateway(pack, { store: new InMemorySessionStore(), gateway_scope_token: "delivery-scope-missing", session_id_factory: () => "demo-session-delivery-missing" });
  const firstOpen = first.open_session({ scenario_ref: pack.scenario_ref, locale: pack.locale });
  const secondOpen = second.open_session({ scenario_ref: pack.scenario_ref, locale: pack.locale });
  assert.equal(firstOpen.error, null);
  assert.equal(secondOpen.error, null);
  const secondBefore = second.query({ session_id: secondId, workspace: "dashboard" });
  const step = pack.hero_flows[0].steps[0];
  const applied = first.apply({
    session_id: firstId,
    action: step.action,
    subject_ref: step.subject_ref,
    payload: step.payload,
    idempotency_key: `delivery-isolation-${roundLabel}`,
    expected_state_sha256: firstOpen.state_sha256,
  });
  assert.equal(applied.error, null);
  const foreign = second.query({ session_id: firstId, workspace: "dashboard" });
  const absent = missing.query({ session_id: firstId, workspace: "dashboard" });
  assert.deepEqual(foreign, absent);
  assert.equal(foreign.error?.http_status, 404);
  const reset = first.reset({ session_id: firstId });
  assert.equal(reset.error, null);
  assert.equal(first.query({ session_id: firstId, workspace: "dashboard" }).error?.http_status, 404);
  const secondAfter = second.query({ session_id: secondId, workspace: "dashboard" });
  assert.deepEqual(secondAfter, secondBefore);
  const reopened = first.open_session({ scenario_ref: pack.scenario_ref, locale: pack.locale });
  assert.equal(reopened.scenario_sha256, firstOpen.scenario_sha256);
  assert.equal(reopened.state_sha256, firstOpen.state_sha256);
  for (const response of [firstOpen, secondOpen, secondBefore, applied, foreign, absent, reset, secondAfter, reopened]) {
    assert.equal(response.network_invoked, false);
    assert.equal(response.external_side_effect_allowed, false);
  }
  return {
    sessions: 2,
    foreign_and_missing_same_404: true,
    reset_scoped_to_owner: true,
    peer_state_unchanged: true,
    scenario_sha256_restored: reopened.scenario_sha256,
    state_sha256_restored: reopened.state_sha256,
    external_write_count: 0,
  };
}

function waitForReady(child) {
  return new Promise((resolve, reject) => {
    let output = "";
    const timer = setTimeout(() => reject(new Error(`delivery_launcher_timeout:${output}`)), 10_000);
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
        reject(new Error(`delivery_launcher_exit:${code}:${output}`));
      }
    });
  });
}

function waitForExit(child, timeoutMs = 5_000) {
  if (child.exitCode !== null) return Promise.resolve();
  return Promise.race([
    once(child, "exit"),
    new Promise((_, reject) => setTimeout(() => reject(new Error("delivery_child_exit_timeout")), timeoutMs)),
  ]);
}

async function isPortFree(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.unref();
    server.once("error", () => resolve(false));
    server.listen({ host: "127.0.0.1", port, exclusive: true }, () => server.close(() => resolve(true)));
  });
}

async function assertShell(page, viewport) {
  await page.waitForFunction(() => document.querySelector("[data-sw-state]")?.textContent === "离线壳已缓存（7/7）", undefined, { timeout: 10_000 });
  assert.equal(await page.locator(".workspace-link").count(), 9);
  assert.equal(await page.locator("[data-hero-flow]").count(), 3);
  assert.deepEqual(await page.locator(".demo-rail strong").allTextContents(), ["LOCAL DEMO", "合成数据", "不计费"]);
  const widths = await page.evaluate(() => ({
    body: document.body.scrollWidth,
    html: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }));
  assert.deepEqual(widths, { body: viewport.width, html: viewport.width, client: viewport.width });
}

async function launchPersistent(profile, viewport) {
  const options = { headless: true, viewport, serviceWorkers: "allow" };
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) options.executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  return chromium.launchPersistentContext(profile, options);
}

async function verifyViewport(viewport, profile, screenshotPath) {
  const outside = [];
  const csp = [];
  const nonGet = [];
  const serverErrors = [];
  const pageErrors = [];
  function observe(page) {
    page.on("request", (request) => {
      if (!request.url().startsWith(`${ORIGIN}/`) || request.url().includes(["", "backend"].join("/"))) outside.push(request.url());
      if (!["GET", "HEAD"].includes(request.method())) nonGet.push(`${request.method()}:${request.url()}`);
    });
    page.on("response", (response) => {
      if (response.status() >= 500) serverErrors.push(`${response.status()}:${response.url()}`);
    });
    page.on("console", (message) => {
      const text = message.text();
      if (text.includes("Refused to") || text.includes("violates the following Content Security Policy")) csp.push(text);
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
  }
  let onlineContext;
  try {
    onlineContext = await launchPersistent(profile, viewport);
    const page = onlineContext.pages()[0] ?? await onlineContext.newPage();
    observe(page);
    await page.goto(`${ORIGIN}/#/dashboard`, { waitUntil: "load" });
    await assertShell(page, viewport);
    await page.screenshot({ path: screenshotPath, fullPage: true, animations: "disabled" });
  } finally {
    if (onlineContext) await onlineContext.close();
  }

  let offlineContext;
  try {
    offlineContext = await launchPersistent(profile, viewport);
    await offlineContext.setOffline(true);
    const page = offlineContext.pages()[0] ?? await offlineContext.newPage();
    observe(page);
    await page.goto(`${ORIGIN}/#/dashboard`, { waitUntil: "load" });
    await assertShell(page, viewport);
  } finally {
    if (offlineContext) await offlineContext.close();
  }
  assert.deepEqual(outside, []);
  assert.deepEqual(csp, []);
  assert.deepEqual(nonGet, []);
  assert.deepEqual(serverErrors, []);
  assert.deepEqual(pageErrors, []);
  return {
    width: viewport.width,
    online_cold_start: true,
    offline_cold_start: true,
    horizontal_overflow: 0,
    workspaces: 9,
    hero_flows: 3,
    markers: 3,
    outside_requests: 0,
    non_get_requests: 0,
    server_5xx_responses: 0,
    csp_violations: 0,
    page_errors: 0,
  };
}

async function writeDeterministicZip(zipPath, rootName, entries) {
  const temporary = `${zipPath}.tmp`;
  await rm(temporary, { force: true });
  const zipfile = new yazl.ZipFile();
  const completion = new Promise((resolve, reject) => {
    const output = createWriteStream(temporary, { flags: "wx", mode: 0o600 });
    output.on("close", resolve);
    output.on("error", reject);
    zipfile.outputStream.on("error", reject);
    zipfile.outputStream.pipe(output);
  });
  for (const entry of [...entries].sort((left, right) => left.path.localeCompare(right.path, "en"))) {
    zipfile.addBuffer(entry.buffer, `${rootName}/${entry.path}`, { compress: true, mtime: FIXED_MTIME, mode: 0o100644 });
  }
  zipfile.end({ forceZip64Format: false });
  await completion;
  await rm(zipPath, { force: true });
  await rename(temporary, zipPath);
}

function assertDeliveryEntryName(name) {
  if (
    typeof name !== "string" ||
    name.includes("\\") ||
    name.includes("\0") ||
    name.startsWith("/") ||
    /^[A-Za-z]:/u.test(name) ||
    name.split("/").some((segment) => segment === "." || segment === "..") ||
    !name.startsWith(`${DELIVERY_ROOT}/`)
  ) throw new Error(`delivery_zip_path_rejected:${name}`);
}

function readDeliveryEntries(zipPath) {
  return new Promise((resolve, reject) => {
    yauzl.open(zipPath, {
      autoClose: true,
      decodeStrings: true,
      lazyEntries: true,
      strictFileNames: true,
      validateEntrySizes: true,
    }, (openError, zipfile) => {
      if (openError || !zipfile) return reject(openError ?? new Error("delivery_zip_open_failed"));
      const entries = [];
      zipfile.on("error", reject);
      zipfile.on("end", () => resolve(entries));
      zipfile.on("entry", (entry) => {
        try {
          assertDeliveryEntryName(entry.fileName);
          const mode = (entry.externalFileAttributes >>> 16) & 0xffff;
          if ((mode & 0o170000) === 0o120000) throw new Error(`delivery_zip_symlink_rejected:${entry.fileName}`);
          if ((mode & 0o170000) !== 0o100000) throw new Error(`delivery_zip_special_rejected:${entry.fileName}`);
          if (entry.fileName.endsWith("/")) throw new Error(`delivery_zip_directory_rejected:${entry.fileName}`);
          if ((entry.generalPurposeBitFlag & 1) !== 0) throw new Error(`delivery_zip_encrypted:${entry.fileName}`);
          zipfile.openReadStream(entry, (streamError, stream) => {
            if (streamError || !stream) return reject(streamError ?? new Error("delivery_zip_stream_failed"));
            const chunks = [];
            stream.on("data", (chunk) => chunks.push(chunk));
            stream.on("error", reject);
            stream.on("end", () => {
              entries.push({
                name: entry.fileName,
                relative: entry.fileName.slice(`${DELIVERY_ROOT}/`.length),
                mode,
                lastModFileDate: entry.lastModFileDate,
                lastModFileTime: entry.lastModFileTime,
                buffer: Buffer.concat(chunks),
              });
              zipfile.readEntry();
            });
          });
        } catch (error) {
          reject(error);
        }
      });
      zipfile.readEntry();
    });
  });
}

export async function verifyDeliveryBundle(zipPath, companionPath) {
  const entries = await readDeliveryEntries(zipPath);
  const names = entries.map((entry) => entry.name);
  const sorted = [...names].sort((left, right) => left.localeCompare(right, "en"));
  assert.deepEqual(names, sorted);
  assert.equal(new Set(names).size, names.length);
  assert.equal(new Set(names.map((name) => name.toLowerCase())).size, names.length);
  assert.equal(new Set(entries.map((entry) => `${entry.lastModFileDate}:${entry.lastModFileTime}`)).size, 1);
  const manifestEntry = entries.find((entry) => entry.relative === "DELIVERY_MANIFEST.json");
  assert.ok(manifestEntry);
  const manifest = JSON.parse(manifestEntry.buffer.toString("utf8"));
  assert.equal(manifest.package_id, DELIVERY_ROOT);
  const expected = [
    ...manifest.files.map((file) => `${DELIVERY_ROOT}/${file.path}`),
    `${DELIVERY_ROOT}/DELIVERY_MANIFEST.json`,
  ].sort((left, right) => left.localeCompare(right, "en"));
  assert.deepEqual(names, expected);
  const byRelative = new Map(entries.map((entry) => [entry.relative, entry]));
  for (const file of manifest.files) {
    const entry = byRelative.get(file.path);
    assert.ok(entry, file.path);
    assert.equal(entry.buffer.length, file.bytes, file.path);
    assert.equal(sha256(entry.buffer), file.sha256, file.path);
    assert.notEqual((entry.mode & 0o170000), 0o120000, file.path);
  }
  const zipBuffer = await readFile(zipPath);
  const companion = JSON.parse(await readFile(companionPath, "utf8"));
  assert.equal(companion.package_id, DELIVERY_ROOT);
  assert.equal(companion.zip_sha256, sha256(zipBuffer));
  assert.equal(companion.zip_bytes, zipBuffer.length);
  assert.equal(companion.embedded_manifest_sha256, sha256(manifestEntry.buffer));
  assert.equal(companion.entry_count, entries.length);
  assert.equal(companion.deterministic_evidence_sha256, sha256(byRelative.get("deterministic-evidence.json").buffer));
  assert.equal(companion.portable_zip_sha256, sha256(byRelative.get(PORTABLE_ZIP).buffer));
  return { ...companion, entry_names: names };
}

async function buildDeliveryBundle(output, deterministicEvidence, portable) {
  await mkdir(output, { recursive: true });
  const evidenceBuffer = Buffer.from(`${JSON.stringify(deterministicEvidence, null, 2)}\n`, "utf8");
  const readmeBuffer = Buffer.from((await readFile(path.join(PACKAGE_ROOT, "delivery/README.md"), "utf8")).replace(/\r\n?/gu, "\n"), "utf8");
  const payload = [
    { path: "DELIVERY_README.md", buffer: readmeBuffer },
    { path: "deterministic-evidence.json", buffer: evidenceBuffer },
    { path: PORTABLE_MANIFEST, buffer: await readFile(portable.companionPath) },
    { path: PORTABLE_ZIP, buffer: await readFile(portable.zipPath) },
  ].sort((left, right) => left.path.localeCompare(right.path, "en"));
  const embeddedManifest = {
    schema: "KJDS-delivery-manifest/v1",
    package_id: DELIVERY_ROOT,
    created_at: FIXED_TIMESTAMP,
    deterministic: true,
    files: payload.map((entry) => ({ path: entry.path, bytes: entry.buffer.length, sha256: sha256(entry.buffer) })),
  };
  const manifestBuffer = Buffer.from(`${JSON.stringify(embeddedManifest, null, 2)}\n`, "utf8");
  const entries = [...payload, { path: "DELIVERY_MANIFEST.json", buffer: manifestBuffer }];
  const zipPath = path.join(output, DELIVERY_ZIP);
  await writeDeterministicZip(zipPath, DELIVERY_ROOT, entries);
  const zipBuffer = await readFile(zipPath);
  const companion = {
    schema: "KJDS-delivery-zip-record/v1",
    package_id: DELIVERY_ROOT,
    zip_file: DELIVERY_ZIP,
    zip_sha256: sha256(zipBuffer),
    zip_bytes: zipBuffer.length,
    embedded_manifest_sha256: sha256(manifestBuffer),
    deterministic_evidence_sha256: sha256(evidenceBuffer),
    portable_zip_sha256: portable.zip_sha256,
    entry_count: entries.length,
    deterministic_timestamp: FIXED_TIMESTAMP,
  };
  const companionPath = path.join(output, DELIVERY_COMPANION);
  await writeFile(companionPath, `${JSON.stringify(companion, null, 2)}\n`, "utf8");
  const verified = await verifyDeliveryBundle(zipPath, companionPath);
  return { zipPath, companionPath, ...verified };
}

async function oneRound(roundId, root) {
  const started = Date.now();
  const packageDir = path.join(root, "package");
  const extractDir = path.join(root, "extract");
  const screenshots = path.join(root, "screenshots");
  const deliveryDir = path.join(root, "delivery");
  await mkdir(screenshots, { recursive: true });
  assert.equal(await isPortFree(43190), true, "port_43190_preexisting_listener");
  assert.equal(await isPortFree(43195), true, "port_43195_preexisting_listener");
  const portable = await buildPortable(packageDir);
  const verified = await verifyPortableZip(portable.zipPath, portable.companionPath);
  const extracted = await extractPortable(portable.zipPath, extractDir);
  assert.equal(await realpath(extracted), extracted);
  const sourceScan = await scanProductSource();
  const distScan = await scanDirectory("dist", path.join(PACKAGE_ROOT, "dist"), { inspectProductionApp: true });
  const zipFiles = await collectRegularFiles(extracted);
  const zipEntries = await Promise.all(zipFiles.map(async (file) => ({ relative: file.relative, buffer: await readFile(file.absolute) })));
  const zipScan = summarizeScan("portable-zip", zipEntries);
  const rawScenario = JSON.parse(await readFile(path.join(PACKAGE_ROOT, "src/scenarios/enterprise-overview.zh-CN.v2.json"), "utf8"));
  const boundary = verifyCurrencyAndSyntheticBoundary(rawScenario);
  const isolation = await verifySessionIsolation("stable-key");
  let launcher;
  let cleanupFirst = "";
  let cleanupSecond = "";
  let browser = [];
  const profileRoot = await createEphemeralProfileRoot();
  try {
    launcher = spawn(process.execPath, [path.join(extracted, "launcher.mjs")], { cwd: extracted, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    await waitForReady(launcher);
    assert.equal(await isPortFree(43195), false);
    for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
      const profile = path.join(profileRoot, `profile-${viewport.width}`);
      const screenshot = path.join(screenshots, `bas196-delivery-${viewport.width}.png`);
      browser.push(await verifyViewport(viewport, profile, screenshot));
    }
    const first = spawnSync(process.execPath, [path.join(extracted, "cleanup.mjs")], { cwd: extracted, encoding: "utf8", timeout: 15_000, windowsHide: true });
    assert.equal(first.status, 0, first.stderr);
    assert.match(first.stdout, /CLEANUP_OK/u);
    cleanupFirst = first.stdout.trim();
    await waitForExit(launcher);
    launcher = undefined;
    const second = spawnSync(process.execPath, [path.join(extracted, "cleanup.mjs")], { cwd: extracted, encoding: "utf8", timeout: 15_000, windowsHide: true });
    assert.equal(second.status, 0, second.stderr);
    assert.match(second.stdout, /already_clean/u);
    cleanupSecond = second.stdout.trim();
  } finally {
    if (launcher && launcher.exitCode === null) {
      spawnSync(process.execPath, [path.join(extracted, "cleanup.mjs")], { cwd: extracted, encoding: "utf8", timeout: 8_000, windowsHide: true });
      if (launcher.exitCode === null) launcher.kill("SIGTERM");
      if (launcher.exitCode === null) await Promise.race([once(launcher, "exit"), new Promise((resolve) => setTimeout(resolve, 5_000))]);
    }
    await removeEphemeralProfileRoot(profileRoot);
  }
  assert.equal(await pathExists(profileRoot), false, "ephemeral_profile_residual");
  assert.equal(await isPortFree(43190), true, "port_43190_residual_listener");
  assert.equal(await isPortFree(43195), true, "port_43195_residual_listener");
  const externalWriteCount = isolation.external_write_count + browser.reduce((total, item) => total + item.outside_requests, 0);
  assert.equal(externalWriteCount, 0);
  const deterministicEvidence = {
    schema: "KJDS-delivery-deterministic-evidence/v1",
    package_id: DELIVERY_ROOT,
    portable: { zip_sha256: verified.zip_sha256, zip_bytes: verified.zip_bytes, entry_count: verified.entry_count },
    scans: { source: sourceScan, dist: distScan, portable_zip: zipScan },
    currency_and_synthetic_boundary: boundary,
    session_isolation: isolation,
    browser,
    cleanup: { first: "server_stopped_runtime_removed", second: "already_clean", port_43190_residual: 0, port_43195_residual: 0, owned_child_process_residual: 0, ephemeral_profile_residual: 0 },
    external_write_count: externalWriteCount,
    excluded_run_observation_fields: ["round_id", "duration_ms", "screenshot_sha256"],
  };
  const deterministicEvidenceSha256 = sha256(canonicalJson(deterministicEvidence));
  const delivery = await buildDeliveryBundle(deliveryDir, deterministicEvidence, portable);
  const screenshotRefs = [];
  for (const width of [1440, 390]) {
    const screenshotPath = path.join(screenshots, `bas196-delivery-${width}.png`);
    const buffer = await readFile(screenshotPath);
    screenshotRefs.push({ width, path: screenshotPath, bytes: buffer.length, sha256: sha256(buffer) });
  }
  return {
    round_id: roundId,
    deterministic_evidence: deterministicEvidence,
    deterministic_evidence_sha256: deterministicEvidenceSha256,
    portable,
    delivery,
    screenshot_refs: screenshotRefs,
    cleanup_observation: { first: cleanupFirst, second: cleanupSecond },
    duration_ms: Date.now() - started,
  };
}

export async function verifyDelivery(outputDirectory) {
  const output = assertDeliveryOutputDirectory(outputDirectory);
  await boundedRemove(output);
  await mkdir(output, { recursive: true });
  const work = path.join(output, ".work");
  await mkdir(work, { recursive: true });
  try {
    const rounds = [];
    for (const roundId of ["round-1", "round-2"]) rounds.push(await oneRound(roundId, path.join(work, roundId)));
    assert.equal(rounds[0].portable.zip_sha256, rounds[1].portable.zip_sha256);
    assert.deepEqual(await readFile(rounds[0].portable.companionPath), await readFile(rounds[1].portable.companionPath));
    assert.equal(rounds[0].deterministic_evidence_sha256, rounds[1].deterministic_evidence_sha256);
    assert.equal(rounds[0].delivery.zip_sha256, rounds[1].delivery.zip_sha256);
    assert.deepEqual(await readFile(rounds[0].delivery.companionPath), await readFile(rounds[1].delivery.companionPath));
    await copyFile(rounds[1].delivery.zipPath, path.join(output, DELIVERY_ZIP));
    await copyFile(rounds[1].delivery.companionPath, path.join(output, DELIVERY_COMPANION));
    for (const screenshot of rounds[1].screenshot_refs) {
      await copyFile(screenshot.path, path.join(output, `bas196-delivery-${screenshot.width}.png`));
    }
    const observation = {
      schema: "KJDS-delivery-evidence/v1",
      package_id: DELIVERY_ROOT,
      deterministic: {
        portable_zip_sha256: rounds[1].portable.zip_sha256,
        delivery_zip_sha256: rounds[1].delivery.zip_sha256,
        evidence_sha256: rounds[1].deterministic_evidence_sha256,
        rounds_equal: true,
      },
      run_observations: rounds.map((round) => ({
        round_id: round.round_id,
        duration_ms: round.duration_ms,
        screenshot_sha256: Object.fromEntries(round.screenshot_refs.map((item) => [item.width, item.sha256])),
        excluded_from_deterministic_hash: true,
      })),
      external_write_count: 0,
      cleanup: { runs: 2, idempotent_each_round: true, port_43190_residual: 0, port_43195_residual: 0, owned_child_process_residual: 0, ephemeral_profile_residual: 0 },
    };
    const evidencePath = path.join(output, "delivery-evidence.json");
    await writeFile(evidencePath, `${JSON.stringify(observation, null, 2)}\n`, "utf8");
    return {
      output,
      delivery_zip: path.join(output, DELIVERY_ZIP),
      delivery_manifest: path.join(output, DELIVERY_COMPANION),
      evidence: evidencePath,
      screenshots: [1440, 390].map((width) => path.join(output, `bas196-delivery-${width}.png`)),
      ...observation,
    };
  } finally {
    await boundedRemove(work);
  }
}

function outputArgument(argv) {
  const index = argv.indexOf("--output-dir");
  const value = index >= 0 ? argv[index + 1] : undefined;
  if (index >= 0 && (!value || value.startsWith("--"))) throw new Error("delivery_output_argument_missing");
  return path.resolve(PACKAGE_ROOT, value ?? path.join(".runtime", "delivery-evidence"));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  verifyDelivery(outputArgument(process.argv.slice(2)))
    .then((result) => process.stdout.write(`${JSON.stringify(result)}\n`))
    .catch((error) => {
      process.stderr.write(`${error.stack ?? error.message}\n`);
      process.exitCode = 1;
    });
}
