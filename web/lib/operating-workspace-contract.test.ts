import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const workspace = readFileSync(
  new URL("../features/operating-workspace/operating-workspace.tsx", import.meta.url),
  "utf8",
);
const contracts = readFileSync(
  new URL("../features/operating-workspace/contracts.ts", import.meta.url),
  "utf8",
);
const route = readFileSync(
  new URL("../app/operations/[kind]/[itemId]/page.tsx", import.meta.url),
  "utf8",
);
const atlasExplorer = readFileSync(
  new URL("../features/capability-atlas/operating-graph-explorer.tsx", import.meta.url),
  "utf8",
);

test("point line and surface routes resolve one server-owned operating workspace", () => {
  assert.match(route, /params: Promise<\{ kind: string; itemId: string \}>/);
  assert.match(route, /OperatingWorkspace kind=\{kind\} itemId=\{itemId\}/);
  assert.match(
    workspace,
    /\/backend\/v1\/operating-workspaces\/\$\{encodeURIComponent\(kind\)\}\/\$\{encodeURIComponent\(itemId\)\}/,
  );
  assert.match(workspace, /\/auth\/session/);
  assert.match(workspace, /store_ref=ozon-primary/);
  assert.match(workspace, /snapshot\?\.release_version/);
  assert.match(workspace, /snapshot\?\.registry_version/);
  assert.doesNotMatch(workspace, /RELEASE 0\.\d+\.\d+/);
  assert.match(contracts, /release_version: string/);
  assert.match(contracts, /registry_version: string/);
});

test("workspace keeps contract status separate from runtime truth and exposes every drill path", () => {
  assert.match(contracts, /contract_status: ContractStatus/);
  assert.match(contracts, /runtime_status: RuntimeStatus/);
  assert.match(contracts, /contract_status_is_runtime_fact: false/);
  assert.match(contracts, /client_can_recalculate_runtime_status: false/);
  assert.match(workspace, /合同状态 ≠ 运行事实/);
  assert.match(workspace, /Evidence 缺口保持可见/);
  assert.match(workspace, /snapshot\.navigation\.related_lines/);
  assert.match(workspace, /snapshot\.navigation\.related_points/);
  assert.match(workspace, /snapshot\.navigation\.related_surfaces/);
  assert.match(atlasExplorer, /href=\{stream\.workspace\}/);
  assert.match(atlasExplorer, /href=\{surface\.workspace\}/);
  assert.match(atlasExplorer, /point\?\.workspace \?\? stream\.workspace/);
});

test("workspace exposes full-chain operations without introducing a write action", () => {
  assert.match(workspace, /全链路阶段/);
  assert.match(workspace, /DOMAIN RUNTIME SIGNALS/);
  assert.match(workspace, /CONTEXT CONTRACT/);
  assert.match(workspace, /EXCEPTION & DATA GAP/);
  assert.doesNotMatch(workspace, /method:\s*["']POST["']/);
  assert.doesNotMatch(workspace, /method:\s*["']PUT["']/);
  assert.doesNotMatch(workspace, /method:\s*["']DELETE["']/);
});
