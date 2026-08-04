import { createHash } from "node:crypto";
import { createWriteStream } from "node:fs";
import { lstat, mkdir, readFile, readdir, rename, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import yazl from "yazl";

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DIST_ROOT = path.join(PACKAGE_ROOT, "dist");
const PORTABLE_SOURCE = path.join(PACKAGE_ROOT, "portable");
const ZIP_ROOT = "KJDS-Local-Demo-v2";
const ZIP_NAME = `${ZIP_ROOT}.zip`;
const COMPANION_NAME = `${ZIP_ROOT}.manifest.json`;
const FIXED_MTIME = new Date("2000-01-01T00:00:00.000Z");
const FIXED_TIMESTAMP = FIXED_MTIME.toISOString();
const PORTABLE_TEXT_PATH = /(?:^|\/)(?:\.kjds-portable-demo-root|[^/]+\.(?:cmd|css|html|js|json|md|mjs|ps1|webmanifest))$/u;

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

export function canonicalizePortableEntry(relative, buffer) {
  if (!PORTABLE_TEXT_PATH.test(relative)) return buffer;
  return Buffer.from(buffer.toString("utf8").replace(/\r\n?/gu, "\n"), "utf8");
}

function assertOutputDirectory(outputDirectory) {
  const relative = path.relative(PACKAGE_ROOT, outputDirectory);
  if (relative === "" || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("portable_output_boundary_invalid");
  }
}

async function collectFiles(root, prefix = "") {
  const output = [];
  const names = (await readdir(root)).sort((left, right) => left.localeCompare(right, "en"));
  for (const name of names) {
    const absolute = path.join(root, name);
    const info = await lstat(absolute);
    if (info.isSymbolicLink()) throw new Error(`portable_source_symlink:${absolute}`);
    const relative = path.posix.join(prefix, name);
    if (info.isDirectory()) output.push(...await collectFiles(absolute, relative));
    else if (info.isFile()) output.push({ absolute, relative });
    else throw new Error(`portable_source_kind_invalid:${absolute}`);
  }
  return output;
}

function modeFor(relative) {
  return /(?:\.mjs|\.ps1|\.cmd)$/u.test(relative) ? 0o100755 : 0o100644;
}

async function writeDeterministicZip(zipPath, entries) {
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
  for (const entry of entries) {
    zipfile.addBuffer(entry.buffer, `${ZIP_ROOT}/${entry.path}`, {
      compress: true,
      mtime: FIXED_MTIME,
      mode: entry.mode,
    });
  }
  zipfile.end({ forceZip64Format: false });
  await completion;
  await rm(zipPath, { force: true });
  await rename(temporary, zipPath);
}

function parseOutputDirectory(argv) {
  const index = argv.indexOf("--output-dir");
  const value = index >= 0 ? argv[index + 1] : undefined;
  if (index >= 0 && !value) throw new Error("portable_output_argument_missing");
  return path.resolve(PACKAGE_ROOT, value ?? path.join(".runtime", "portable-dist"));
}

export async function buildPortable(outputDirectory) {
  assertOutputDirectory(outputDirectory);
  const sources = [
    ...(await collectFiles(PORTABLE_SOURCE)),
    ...(await collectFiles(DIST_ROOT, "app")),
  ];
  const payloadEntries = [];
  for (const source of sources) {
    const buffer = canonicalizePortableEntry(source.relative, await readFile(source.absolute));
    payloadEntries.push({ path: source.relative, buffer, mode: modeFor(source.relative) });
  }
  payloadEntries.sort((left, right) => left.path.localeCompare(right.path, "en"));
  const inventory = {
    schema: "KJDS-portable-manifest/v1",
    package_id: ZIP_ROOT,
    package_version: "v2",
    created_at: FIXED_TIMESTAMP,
    deterministic_zip: {
      entry_order: "UTF-8 lexical ascending",
      mtime: FIXED_TIMESTAMP,
      compression: "deflate level 6 (yazl@3.3.1 fixed default)",
      file_mode: "0644 data / 0755 launchers",
      text_eol: "LF",
    },
    launcher: { host: "127.0.0.1", port: 43195, methods: ["GET", "HEAD"] },
    expected_entry_count: payloadEntries.length + 1,
    files: payloadEntries.map((entry) => ({
      path: entry.path,
      sha256: sha256(entry.buffer),
      bytes: entry.buffer.length,
      mode: entry.mode.toString(8),
    })),
  };
  const inventoryBuffer = Buffer.from(`${JSON.stringify(inventory, null, 2)}\n`, "utf8");
  const entries = [
    ...payloadEntries,
    { path: "PORTABLE_MANIFEST.json", buffer: inventoryBuffer, mode: 0o100644 },
  ].sort((left, right) => left.path.localeCompare(right.path, "en"));

  await mkdir(outputDirectory, { recursive: true });
  const zipPath = path.join(outputDirectory, ZIP_NAME);
  const companionPath = path.join(outputDirectory, COMPANION_NAME);
  await writeDeterministicZip(zipPath, entries);
  const zipBuffer = await readFile(zipPath);
  const companion = {
    schema: "KJDS-portable-zip-record/v1",
    package_id: ZIP_ROOT,
    zip_file: ZIP_NAME,
    zip_sha256: sha256(zipBuffer),
    zip_bytes: zipBuffer.length,
    embedded_manifest_sha256: sha256(inventoryBuffer),
    entry_count: entries.length,
    deterministic_timestamp: FIXED_TIMESTAMP,
  };
  await writeFile(companionPath, `${JSON.stringify(companion, null, 2)}\n`, "utf8");
  return { zipPath, companionPath, ...companion };
}

const invoked = path.resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url);
if (invoked) {
  buildPortable(parseOutputDirectory(process.argv.slice(2)))
    .then((result) => process.stdout.write(`${JSON.stringify(result)}\n`))
    .catch((error) => {
      process.stderr.write(`${error.message}\n`);
      process.exitCode = 1;
    });
}
