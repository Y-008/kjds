import { randomBytes } from "node:crypto";
import { createServer } from "node:http";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  PORTABLE_PACKAGE_ID,
  validatePackageContract,
  validateRegularFile,
} from "./package-contract.mjs";

const PACKAGE_ID = PORTABLE_PACKAGE_ID;
const HOST = "127.0.0.1";
const PORT = 43195;
const PACKAGE_ROOT = path.dirname(fileURLToPath(import.meta.url));
const RUNTIME_ROOT = path.join(PACKAGE_ROOT, ".runtime");
const STATE_PATH = path.join(RUNTIME_ROOT, "server-state.json");
const cleanupChallenge = randomBytes(24).toString("hex");

const MIME_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".webmanifest", "application/manifest+json; charset=utf-8"],
]);

function loopbackHostAllowed(value) {
  if (typeof value !== "string" || value.length > 128) return false;
  try {
    const parsed = new URL(`http://${value}`);
    const hostname = parsed.hostname.toLowerCase();
    const port = parsed.port || "80";
    return port === String(PORT) && ["127.0.0.1", "localhost", "[::1]"].includes(hostname);
  } catch {
    return false;
  }
}

function decodedRequestPath(requestTarget) {
  if (typeof requestTarget !== "string" || requestTarget.length > 2_048) return null;
  const rawPath = requestTarget.split(/[?#]/u, 1)[0] ?? "/";
  let decoded;
  try {
    decoded = decodeURIComponent(rawPath);
  } catch {
    return null;
  }
  if (
    decoded.includes("\\") ||
    decoded.includes("\0") ||
    /(^|\/)\.{1,2}(\/|$)/u.test(decoded) ||
    /^[a-zA-Z]:/u.test(decoded)
  ) return null;
  return decoded;
}

function send(response, status, body, headers = {}) {
  const payload = Buffer.from(body);
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-length": String(payload.length),
    "x-content-type-options": "nosniff",
    ...headers,
  });
  response.end(response.req.method === "HEAD" ? undefined : payload);
}

async function resolveStaticFile(decodedPath) {
  const relative = decodedPath.replace(/^\/+/, "") || "index.html";
  const lowerSegments = relative.toLowerCase().split("/");
  if (lowerSegments.includes("backend")) return { rejected: true };
  const candidate = path.resolve(APP_REAL_ROOT, ...relative.split("/"));
  if (candidate !== APP_REAL_ROOT && !candidate.startsWith(`${APP_REAL_ROOT}${path.sep}`)) {
    return { rejected: true };
  }
  try {
    const resolved = await validateRegularFile(candidate, APP_REAL_ROOT);
    return { path: resolved };
  } catch {
    if (path.extname(relative) === "") {
      try {
        return { path: await validateRegularFile(path.join(APP_REAL_ROOT, "index.html"), APP_REAL_ROOT) };
      } catch {
        return { rejected: true };
      }
    }
    return { missing: true };
  }
}

const packageContract = await validatePackageContract(PACKAGE_ROOT);
const PACKAGE_REAL_ROOT = packageContract.packageRoot;
const APP_REAL_ROOT = packageContract.appRoot;

await mkdir(RUNTIME_ROOT, { recursive: false }).catch((error) => {
  if (error?.code !== "EEXIST") throw error;
});

const server = createServer(async (request, response) => {
  try {
    if (!loopbackHostAllowed(request.headers.host)) {
      send(response, 421, "Loopback Host required.\n");
      return;
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      response.setHeader("allow", "GET, HEAD");
      send(response, 405, "Read-only portable demo.\n");
      return;
    }
    const decodedPath = decodedRequestPath(request.url);
    if (decodedPath === null) {
      send(response, 403, "Path rejected.\n");
      return;
    }
    if (decodedPath === "/__kjds_status") {
      if (request.headers["x-kjds-cleanup-challenge"] !== cleanupChallenge) {
        send(response, 404, "Not found.\n");
        return;
      }
      send(response, 200, JSON.stringify({ package_id: PACKAGE_ID, package_root: PACKAGE_ROOT, pid: process.pid, port: PORT }), {
        "content-type": "application/json; charset=utf-8",
      });
      return;
    }
    const target = await resolveStaticFile(decodedPath);
    if (target.rejected) {
      send(response, 403, "Path rejected.\n");
      return;
    }
    if (!target.path || target.missing) {
      send(response, 404, "Not found.\n");
      return;
    }
    const body = await readFile(target.path);
    const extension = path.extname(target.path).toLowerCase();
    const headers = { "content-type": MIME_TYPES.get(extension) ?? "application/octet-stream" };
    if (extension === ".html") {
      headers["content-security-policy"] = "default-src 'self'; base-uri 'none'; connect-src 'none'; font-src 'self'; form-action 'none'; frame-ancestors 'none'; img-src 'self' data:; manifest-src 'self'; object-src 'none'; script-src 'self'; style-src 'self'; worker-src 'self'";
    }
    send(response, 200, body, headers);
  } catch {
    send(response, 500, "Portable demo request failed closed.\n");
  }
});

async function removeStateFile() {
  await rm(STATE_PATH, { force: true });
}

async function shutdown(signal) {
  server.close(async () => {
    await removeStateFile();
    process.stdout.write(`KJDS_LOCAL_DEMO_STOPPED ${signal}\n`);
    process.exit(0);
  });
}

server.on("error", async (error) => {
  await removeStateFile();
  process.stderr.write(`KJDS_LOCAL_DEMO_START_FAILED ${error.code ?? "unknown"}\n`);
  process.exitCode = 1;
});

server.listen(PORT, HOST, async () => {
  const state = {
    schema: "KJDS-portable-runtime/v1",
    package_id: PACKAGE_ID,
    package_root: PACKAGE_REAL_ROOT,
    pid: process.pid,
    host: HOST,
    port: PORT,
    cleanup_challenge: cleanupChallenge,
  };
  await writeFile(STATE_PATH, `${JSON.stringify(state, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  process.stdout.write(`KJDS_LOCAL_DEMO_READY http://${HOST}:${PORT}/#/dashboard\n`);
});

process.once("SIGINT", () => void shutdown("SIGINT"));
process.once("SIGTERM", () => void shutdown("SIGTERM"));
