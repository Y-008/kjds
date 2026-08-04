import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import yauzl from "yauzl";

const ZIP_ROOT = "KJDS-Local-Demo-v2";

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

export function assertSafeEntryName(name) {
  if (
    typeof name !== "string" ||
    name.length === 0 ||
    name.includes("\\") ||
    name.includes("\0") ||
    name.startsWith("/") ||
    /^[a-zA-Z]:/u.test(name) ||
    name.split("/").some((segment) => segment === ".." || segment === ".")
  ) throw new Error(`portable_zip_path_rejected:${name}`);
  if (!name.startsWith(`${ZIP_ROOT}/`)) throw new Error(`portable_zip_root_rejected:${name}`);
}

export function assertRegularEntry(name, externalFileAttributes) {
  const mode = (externalFileAttributes >>> 16) & 0xffff;
  if ((mode & 0o170000) === 0o120000) throw new Error(`portable_zip_symlink_rejected:${name}`);
  if (name.endsWith("/")) throw new Error(`portable_zip_directory_entry_rejected:${name}`);
  return mode;
}

export function assertUniqueNames(names) {
  const exact = new Set();
  const folded = new Set();
  for (const name of names) {
    const lower = name.toLowerCase();
    if (exact.has(name) || folded.has(lower)) throw new Error(`portable_zip_duplicate:${name}`);
    exact.add(name);
    folded.add(lower);
  }
}

export async function readZipEntries(zipPath) {
  return new Promise((resolve, reject) => {
    yauzl.open(zipPath, {
      autoClose: true,
      decodeStrings: true,
      lazyEntries: true,
      strictFileNames: true,
      validateEntrySizes: true,
    }, (openError, zipfile) => {
      if (openError || !zipfile) return reject(openError ?? new Error("portable_zip_open_failed"));
      const entries = [];
      zipfile.on("error", reject);
      zipfile.on("end", () => resolve(entries));
      zipfile.on("entry", (entry) => {
        try {
          assertSafeEntryName(entry.fileName);
          const mode = assertRegularEntry(entry.fileName, entry.externalFileAttributes);
          if ((entry.generalPurposeBitFlag & 1) !== 0) throw new Error("portable_zip_encryption_rejected");
          zipfile.openReadStream(entry, (streamError, stream) => {
            if (streamError || !stream) return reject(streamError ?? new Error("portable_zip_stream_failed"));
            const chunks = [];
            stream.on("data", (chunk) => chunks.push(chunk));
            stream.on("error", reject);
            stream.on("end", () => {
              entries.push({
                name: entry.fileName,
                relative: entry.fileName.slice(`${ZIP_ROOT}/`.length),
                buffer: Buffer.concat(chunks),
                mode,
                lastModFileDate: entry.lastModFileDate,
                lastModFileTime: entry.lastModFileTime,
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

export async function verifyPortableZip(zipPath, companionPath) {
  const entries = await readZipEntries(zipPath);
  const names = entries.map((entry) => entry.name);
  assertUniqueNames(names);
  const sorted = [...names].sort((left, right) => left.localeCompare(right, "en"));
  if (JSON.stringify(names) !== JSON.stringify(sorted)) throw new Error("portable_zip_order_invalid");
  const dateTimes = new Set(entries.map((entry) => `${entry.lastModFileDate}:${entry.lastModFileTime}`));
  if (dateTimes.size !== 1) throw new Error("portable_zip_timestamp_drift");

  const manifestEntry = entries.find((entry) => entry.relative === "PORTABLE_MANIFEST.json");
  if (!manifestEntry) throw new Error("portable_manifest_missing");
  const manifest = JSON.parse(manifestEntry.buffer.toString("utf8"));
  const expectedNames = [
    ...manifest.files.map((file) => `${ZIP_ROOT}/${file.path}`),
    `${ZIP_ROOT}/PORTABLE_MANIFEST.json`,
  ].sort((left, right) => left.localeCompare(right, "en"));
  if (JSON.stringify(names) !== JSON.stringify(expectedNames)) throw new Error("portable_inventory_mismatch");
  if (manifest.expected_entry_count !== entries.length) throw new Error("portable_entry_count_mismatch");
  const byRelative = new Map(entries.map((entry) => [entry.relative, entry]));
  for (const file of manifest.files) {
    const entry = byRelative.get(file.path);
    if (
      !entry ||
      sha256(entry.buffer) !== file.sha256 ||
      entry.buffer.length !== file.bytes ||
      entry.mode.toString(8) !== file.mode
    ) throw new Error(`portable_inventory_file_mismatch:${file.path}`);
  }
  const forbiddenPaths = names.filter((name) =>
    /(^|\/)(?:node_modules|src|tests?|\.env|cookies?|secrets?|credentials?)(\/|$)/iu.test(name),
  );
  if (forbiddenPaths.length) throw new Error(`portable_forbidden_inventory:${forbiddenPaths.join(",")}`);

  const zipBuffer = await readFile(zipPath);
  const companion = JSON.parse(await readFile(companionPath, "utf8"));
  if (
    companion.zip_sha256 !== sha256(zipBuffer) ||
    companion.zip_bytes !== zipBuffer.length ||
    companion.embedded_manifest_sha256 !== sha256(manifestEntry.buffer) ||
    companion.entry_count !== entries.length
  ) throw new Error("portable_companion_mismatch");
  return {
    zip_sha256: companion.zip_sha256,
    zip_bytes: companion.zip_bytes,
    entry_count: entries.length,
    entry_names: names,
    manifest,
    entries,
  };
}

function requiredArgument(name) {
  const index = process.argv.indexOf(name);
  const value = index >= 0 ? process.argv[index + 1] : undefined;
  if (!value || value.startsWith("--")) throw new Error(`portable_verify_argument_missing:${name}`);
  return path.resolve(value);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = await verifyPortableZip(requiredArgument("--zip"), requiredArgument("--manifest"));
  process.stdout.write(`${JSON.stringify({
    zip_sha256: result.zip_sha256,
    zip_bytes: result.zip_bytes,
    entry_count: result.entry_count,
    entry_names: result.entry_names,
  })}\n`);
}
