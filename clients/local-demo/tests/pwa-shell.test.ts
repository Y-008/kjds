import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { renderAppShell } from "../src/ui/app-shell.ts";
import { APP_SHELL_PATHS, APP_SHELL_READY_LABEL } from "../src/ui/offline-cache.ts";
import {
  WORKSPACES,
  WORKSPACE_IDS,
  workspaceFromHash,
} from "../src/ui/workspace-catalog.ts";

const ROOT = new URL("../", import.meta.url);

function source(path: string): string {
  return readFileSync(new URL(path, ROOT), "utf8");
}

test("PWA shell exposes exactly nine stable hash workspaces", () => {
  assert.equal(WORKSPACES.length, 9);
  assert.deepEqual(
    WORKSPACES.map((workspace) => workspace.id),
    WORKSPACE_IDS,
  );
  assert.equal(new Set(WORKSPACES.map((workspace) => workspace.route)).size, 9);
  for (const workspace of WORKSPACES) {
    assert.equal(workspaceFromHash(`#/${workspace.route}`), workspace);
    assert.equal(workspace.shellState, "shell_ready");
    assert.equal(workspace.scenarioState, "ready");
  }
  assert.equal(workspaceFromHash("#/not-a-workspace").id, "dashboard");
});

test("every shell route keeps all demo markers and all workspace links visible", () => {
  for (const workspace of WORKSPACES) {
    const html = renderAppShell(workspace, "离线壳已缓存");
    for (const marker of ["LOCAL DEMO", "合成数据", "不计费"]) {
      assert.ok(html.includes(marker), `${workspace.id}:${marker}`);
    }
    assert.equal((html.match(/class="workspace-link/g) ?? []).length, 9);
    assert.equal((html.match(/class="matrix-card/g) ?? []).length, 9);
    assert.ok(html.includes('aria-current="page"'));
    assert.ok(html.includes("模拟推进"));
    assert.ok(html.includes("错误重放"));
    assert.ok(html.includes("重置场景"));
    assert.equal(html.includes("本地模拟完成"), false);
    assert.equal(/\sstyle=/u.test(html), false);
  }
});

test("manifest, service worker and CSP freeze the local-only shell boundary", () => {
  const manifest = JSON.parse(source("public/manifest.webmanifest")) as {
    display: string;
    start_url: string;
    scope: string;
    icons: Array<{ sizes: string; src: string }>;
  };
  assert.equal(manifest.display, "standalone");
  assert.equal(manifest.start_url, "./#/dashboard");
  assert.equal(manifest.scope, "./");
  assert.deepEqual(
    manifest.icons.map((icon) => icon.sizes),
    ["192x192", "512x512"],
  );

  const index = source("index.html");
  assert.ok(index.includes("connect-src 'none'"));
  assert.ok(index.includes("worker-src 'self'"));
  assert.ok(index.includes('./manifest.webmanifest'));

  const worker = source("public/sw.js");
  assert.equal(APP_SHELL_PATHS.length, 7);
  assert.equal(APP_SHELL_READY_LABEL, "离线壳已缓存（7/7）");
  for (const asset of APP_SHELL_PATHS.filter((path) => path.length > 0)) {
    assert.ok(worker.includes(`\"${asset}\"`), asset);
  }
  assert.ok(worker.includes("url.origin !== self.location.origin"));
  assert.ok(worker.includes("assertAppShellCached"));
  assert.ok(worker.includes("self.registration.scope"));
  assert.ok(worker.includes('event.data?.type !== "CACHE_STATUS"'));
  assert.ok(worker.includes("all_cached: cachedCount === urls.length"));
});

test("BAS-194 UI imports only its local gateway/domain/scenario and no production modules", () => {
  const ui = [
    source("src/ui/main.ts"),
    source("src/ui/app-shell.ts"),
    source("src/ui/workspace-catalog.ts"),
  ].join("\n");
  for (const forbiddenImport of [
    "apps/control_plane",
    "web/app",
    "web.app.backend",
  ]) {
    assert.equal(ui.includes(forbiddenImport), false, forbiddenImport);
  }
  assert.ok(ui.includes("local-demo-gateway.ts"));
  assert.ok(ui.includes("enterprise-overview.zh-CN.v2.json"));
  assert.equal(ui.includes("process.env"), false);
  assert.equal(ui.includes("XMLHttpRequest"), false);
});
