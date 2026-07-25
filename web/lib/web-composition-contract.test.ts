import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { readDashboardSource } from "./dashboard-source.ts";
import { fetchJson, settleJsonRequests } from "./fetch-json.ts";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("page delegates to the dashboard composition root", () => {
  const page = read("../app/page.tsx");
  const dashboard = read("../features/dashboard/kjds-dashboard.tsx");

  assert.match(page, /<KjdsDashboard\s*\/>/);
  assert.doesNotMatch(page, /\/backend\//);
  assert.match(dashboard, /useDashboardController\(\)/);
  assert.match(dashboard, /<DashboardView model=/);
});

test("sidebar navigation targets real dashboard sections", () => {
  const source = readDashboardSource();
  const shell = read("../features/dashboard/dashboard-shell.tsx");
  const targets = [...shell.matchAll(/"(#[a-z][a-z0-9-]+)"/g)].map((match) => match[1]);

  assert.equal(targets.length, 9);
  for (const target of targets) assert.match(source, new RegExp(`id="${target.slice(1)}"`));
  assert.match(shell, /<a aria-label=\{label\} href=\{href\}/);
  assert.match(shell, /title=\{label\}/);
});

test("request failures settle without rejecting sibling dashboard loads", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error("offline"); };
  try {
    const [failed, healthy] = await settleJsonRequests([
      fetchJson("https://optional.invalid"),
      Promise.resolve({ ok: true, status: 200, json: async () => ({ status: "ok" }) }),
    ]);
    assert.equal(failed.ok, false);
    assert.equal(failed.status, 0);
    assert.equal(healthy.ok, true);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Agent status comes from the governed operating-workbench briefing", () => {
  const controller = read("../features/dashboard/use-dashboard-controller.tsx");
  const summary = read("../features/dashboard/operations-summary-panel.tsx");

  assert.match(controller, /\/backend\/v1\/operating-workbench\/briefing/);
  assert.match(summary, /operatingWorkbench\.agents\.map/);
  assert.doesNotMatch(summary, /\["市场分析", "商品策略"/);
  assert.doesNotMatch(summary, /<span className="badge">影子模式<\/span>/);
  assert.match(summary, /页面不会自行猜测 Agent 状态/);
});

test("identity failure renders unknown state and hides mutation workspaces", () => {
  const boot = read("../features/dashboard/use-dashboard-boot.ts");
  const view = read("../features/dashboard/dashboard-view.tsx");
  const summary = read("../features/dashboard/operations-summary-panel.tsx");

  assert.match(boot, /setIdentityStatus\("unavailable"\)/);
  assert.match(view, /model\.identityStatus === "ready"/);
  assert.match(view, /依赖身份权限的上传、审批、采购、上架和执行操作已全部隐藏/);
  assert.match(summary, /identityReady \? `\$\{readySkuCount\} \/ 3` : "未知"/);
});

test("real SKU workbench stays read-only and exposes unknown fields", () => {
  const sourcing = read("../features/dashboard/sourcing-panel.tsx");
  const workbench = read("../features/dashboard/sku-workbench-panel.tsx");

  assert.match(sourcing, /<SkuWorkbenchPanel \/>/);
  assert.match(workbench, /\/backend\/v1\/workbench\/skus\//);
  assert.match(workbench, /系统不会用零或推测值填补未知字段/);
  assert.match(workbench, /采集商品快照/);
  assert.match(workbench, /待书面确认/);
  assert.doesNotMatch(workbench, /method: "POST"/);
});
