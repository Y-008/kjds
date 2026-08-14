import { createHash } from "node:crypto";
import { lstat, readFile, readdir, realpath } from "node:fs/promises";
import path from "node:path";

export const PORTABLE_PACKAGE_ID = "KJDS-Local-Demo-v2";
export const PORTABLE_PAYLOAD_ALLOWLIST = Object.freeze([
  ".kjds-portable-demo-root",
  "README.md",
  "app/assets/app.css",
  "app/assets/app.js",
  "app/icons/icon-192.png",
  "app/icons/icon-512.png",
  "app/index.html",
  "app/manifest.webmanifest",
  "app/sw.js",
  "cleanup.mjs",
  "launcher.mjs",
  "package-contract.mjs",
  "reset.mjs",
  "start.cmd",
  "start.ps1",
]);

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

export async function validateRegularFile(candidate, boundaryRoot) {
  const info = await lstat(candidate);
  if (info.isSymbolicLink() || !info.isFile()) throw new Error("portable_package_file_kind_invalid");
  const resolved = await realpath(candidate);
  if (!resolved.startsWith(`${boundaryRoot}${path.sep}`)) throw new Error("portable_package_realpath_escape");
  return resolved;
}

export async function validatePackageContract(packageRoot) {
  const realRoot = await realpath(packageRoot);
  const discovered = [];
  async function walk(directory, prefix = "") {
    const names = (await readdir(directory)).sort((left, right) => left.localeCompare(right, "en"));
    for (const name of names) {
      if (prefix === "" && name === ".runtime") continue;
      const absolute = path.join(directory, name);
      const info = await lstat(absolute);
      if (info.isSymbolicLink()) throw new Error("portable_package_symlink_rejected");
      const relative = path.posix.join(prefix, name);
      if (info.isDirectory()) await walk(absolute, relative);
      else if (info.isFile()) discovered.push(relative);
      else throw new Error("portable_package_file_kind_invalid");
    }
  }
  await walk(realRoot);
  const expectedDiscovered = [...PORTABLE_PAYLOAD_ALLOWLIST, "PORTABLE_MANIFEST.json"]
    .sort((left, right) => left.localeCompare(right, "en"));
  if (JSON.stringify(discovered) !== JSON.stringify(expectedDiscovered)) {
    throw new Error("portable_package_inventory_invalid");
  }
  const manifestPath = await validateRegularFile(path.join(realRoot, "PORTABLE_MANIFEST.json"), realRoot);
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  if (manifest.package_id !== PORTABLE_PACKAGE_ID || !Array.isArray(manifest.files)) {
    throw new Error("portable_manifest_identity_invalid");
  }
  const paths = manifest.files.map((file) => file.path);
  const unique = new Set(paths);
  const actual = [...unique].sort((left, right) => left.localeCompare(right, "en"));
  const expected = [...PORTABLE_PAYLOAD_ALLOWLIST].sort((left, right) => left.localeCompare(right, "en"));
  if (unique.size !== paths.length || JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error("portable_manifest_allowlist_invalid");
  }
  for (const record of manifest.files) {
    if (
      typeof record.path !== "string" ||
      typeof record.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/u.test(record.sha256) ||
      !Number.isSafeInteger(record.bytes) ||
      record.bytes < 0
    ) throw new Error("portable_manifest_record_invalid");
    const candidate = path.resolve(realRoot, ...record.path.split("/"));
    if (!candidate.startsWith(`${realRoot}${path.sep}`)) throw new Error("portable_manifest_path_escape");
    const resolved = await validateRegularFile(candidate, realRoot);
    const buffer = await readFile(resolved);
    if (buffer.length !== record.bytes || sha256(buffer) !== record.sha256) {
      throw new Error(`portable_manifest_hash_mismatch:${record.path}`);
    }
  }
  const appRoot = await realpath(path.join(realRoot, "app"));
  if (!appRoot.startsWith(`${realRoot}${path.sep}`)) throw new Error("portable_app_realpath_escape");
  await validateRegularFile(path.join(appRoot, "index.html"), appRoot);
  return { packageRoot: realRoot, appRoot, manifest };
}
