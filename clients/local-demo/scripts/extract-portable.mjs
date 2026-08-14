import { lstat, mkdir, readdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { readZipEntries } from "./verify-portable.mjs";

const PACKAGE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ALLOWED_ROOT = path.join(PACKAGE_ROOT, ".runtime");

export async function extractPortable(zipPath, targetDirectory) {
  const target = path.resolve(targetDirectory);
  const relative = path.relative(ALLOWED_ROOT, target);
  if (relative === "" || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("portable_extract_boundary_invalid");
  }
  await mkdir(target, { recursive: true });
  if ((await readdir(target)).length !== 0) throw new Error("portable_extract_target_not_empty");
  const entries = await readZipEntries(zipPath);
  for (const entry of entries) {
    const output = path.resolve(target, ...entry.name.split("/"));
    if (!output.startsWith(`${target}${path.sep}`)) throw new Error("portable_extract_path_rejected");
    const parent = path.dirname(output);
    await mkdir(parent, { recursive: true });
    const parentInfo = await lstat(parent);
    if (parentInfo.isSymbolicLink()) throw new Error("portable_extract_symlink_parent");
    await writeFile(output, entry.buffer, { flag: "wx", mode: entry.mode & 0o777 });
  }
  return path.join(target, "KJDS-Local-Demo-v2");
}
