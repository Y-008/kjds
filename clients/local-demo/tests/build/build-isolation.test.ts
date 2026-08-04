import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import { extname } from "node:path";
import test from "node:test";

const DIST = new URL("../../dist/", import.meta.url);
const EXPECTED_FILES = [
  "index.html",
  "manifest.webmanifest",
  "sw.js",
  "assets/app.css",
  "assets/app.js",
  "icons/icon-192.png",
  "icons/icon-512.png",
] as const;

function built(path: string): Buffer {
  return readFileSync(new URL(path, DIST));
}

test("build contains the complete deterministic PWA shell", () => {
  for (const path of EXPECTED_FILES) {
    const stats = statSync(new URL(path, DIST));
    assert.ok(stats.isFile(), path);
    assert.ok(stats.size > 0, path);
  }
  assert.ok(built("icons/icon-192.png").length > 1_000);
  assert.ok(built("icons/icon-512.png").length > 3_000);
});

test("built text has no external URL, backend route, secret or production import", () => {
  const text = EXPECTED_FILES.filter((path) =>
    [".html", ".webmanifest", ".js", ".css"].includes(extname(path)),
  )
    .map((path) => built(path).toString("utf8"))
    .join("\n");

  for (const forbidden of [
    "http://",
    "https://",
    "/backend",
    "apps/control_plane",
    "web.app.backend",
    "KJDS_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_KEY",
    "client_secret",
    "access_token",
    'style="',
    "node:crypto",
  ]) {
    assert.equal(text.includes(forbidden), false, forbidden);
  }
  for (const marker of ["LOCAL DEMO", "合成数据", "不计费"]) {
    assert.ok(text.includes(marker), marker);
  }
});
