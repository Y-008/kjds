import { request } from "node:http";
import { lstat, readFile, realpath, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const PACKAGE_ID = "KJDS-Local-Demo-v2";
const PORT = 43195;
const PACKAGE_ROOT = path.dirname(fileURLToPath(import.meta.url));
const RUNTIME_ROOT = path.join(PACKAGE_ROOT, ".runtime");
const STATE_PATH = path.join(RUNTIME_ROOT, "server-state.json");

async function runtimeIsAbsent() {
  try {
    await lstat(RUNTIME_ROOT);
    return false;
  } catch (error) {
    if (error?.code === "ENOENT") return true;
    throw error;
  }
}

async function statusFromServer(state) {
  return new Promise((resolve, reject) => {
    const call = request({
      host: "127.0.0.1",
      port: PORT,
      path: "/__kjds_status",
      method: "GET",
      headers: {
        host: `127.0.0.1:${PORT}`,
        "x-kjds-cleanup-challenge": state.cleanup_challenge,
      },
      timeout: 2_000,
    }, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => {
        if (response.statusCode !== 200) return reject(new Error("portable_cleanup_identity_rejected"));
        try { resolve(JSON.parse(Buffer.concat(chunks).toString("utf8"))); }
        catch { reject(new Error("portable_cleanup_status_invalid")); }
      });
    });
    call.on("timeout", () => call.destroy(new Error("portable_cleanup_status_timeout")));
    call.on("error", reject);
    call.end();
  });
}

async function safeRemoveRuntime(packageRoot) {
  if (await runtimeIsAbsent()) return;
  const info = await lstat(RUNTIME_ROOT);
  if (info.isSymbolicLink() || !info.isDirectory()) throw new Error("portable_runtime_boundary_invalid");
  if (path.dirname(RUNTIME_ROOT) !== packageRoot || path.basename(RUNTIME_ROOT) !== ".runtime") {
    throw new Error("portable_runtime_boundary_invalid");
  }
  await rm(RUNTIME_ROOT, { recursive: true, force: true, maxRetries: 3 });
  if (!(await runtimeIsAbsent())) throw new Error("portable_runtime_cleanup_incomplete");
}

export async function cleanupPortableRuntime(label = "CLEANUP") {
  const packageRoot = await realpath(PACKAGE_ROOT);
  if (await runtimeIsAbsent()) {
    process.stdout.write(`${label}_OK already_clean\n`);
    return;
  }
  let state;
  try {
    state = JSON.parse(await readFile(STATE_PATH, "utf8"));
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
    await safeRemoveRuntime(packageRoot);
    process.stdout.write(`${label}_OK stale_runtime_removed\n`);
    return;
  }
  if (
    state.package_id !== PACKAGE_ID ||
    state.package_root !== packageRoot ||
    state.port !== PORT ||
    !Number.isSafeInteger(state.pid) ||
    state.pid <= 0 ||
    typeof state.cleanup_challenge !== "string" ||
    !/^[0-9a-f]{48}$/u.test(state.cleanup_challenge)
  ) throw new Error("portable_cleanup_state_invalid");

  try {
    const status = await statusFromServer(state);
    if (
      status.package_id !== PACKAGE_ID ||
      status.package_root !== packageRoot ||
      status.pid !== state.pid ||
      status.port !== PORT
    ) throw new Error("portable_cleanup_process_mismatch");
    process.kill(state.pid, "SIGTERM");
    await waitForProcessExit(state.pid);
  } catch (error) {
    if (!["ECONNREFUSED", "ECONNRESET"].includes(error?.code)) throw error;
  }
  await safeRemoveRuntime(packageRoot);
  process.stdout.write(`${label}_OK server_stopped_runtime_removed\n`);
}

export async function waitForProcessExit(
  pid,
  {
    timeoutMs = 5_000,
    isAlive = (candidate) => {
      try { process.kill(candidate, 0); return true; }
      catch { return false; }
    },
    sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  } = {},
) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!isAlive(pid)) return;
    await sleep(50);
  }
  if (isAlive(pid)) throw new Error("portable_cleanup_process_refused_exit");
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (invokedPath === import.meta.url) {
  cleanupPortableRuntime().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
