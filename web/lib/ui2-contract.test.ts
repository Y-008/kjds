import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const ui = read("../features/ui2/ui2.tsx");
const uiStyles = read("../features/ui2/ui2.module.css");
const tokens = read("../features/ui2/tokens.css");
const overview = read("../features/bi/bi-overview.tsx");
const wallboard = read("../features/bi/wallboard.tsx");
const briefing = read("../features/bi/briefing.tsx");
const projectionContract = read("../features/bi/contract.ts");
const projectionHook = read("../features/bi/use-bi-projection.ts");
const agentStatusRail = read("../features/agent-control/agent-status-rail.tsx");

test("UI 2.0 shared layer keeps metadata, evidence and truth states explicit", () => {
  for (const token of ["--kjds-text-primary", "--kjds-surface-elevated", "--kjds-border-default", "--kjds-focus-ring"]) {
    assert.match(tokens, new RegExp(token));
  }
  for (const component of ["AppShell", "ScopeBar", "CommandMenu", "PageHeader", "MetricCard", "ChartFrame", "DataTable", "EvidenceDrawer", "DetailDrawer", "WallboardFrame", "BriefingFrame"]) {
    assert.match(ui, new RegExp(`export function ${component}`));
  }
  for (const status of ["no_data", "blocked", "partial", "stale", "conflicted", "forbidden"]) {
    assert.match(ui, new RegExp(status));
  }
  assert.match(ui, /freshness|数据截止/);
  assert.match(ui, /snapshotHash/);
  assert.match(ui, /查看数据表/);
  assert.match(ui, /跳转到主内容/);
  assert.match(ui, /Ctrl K/);
  assert.match(tokens, /prefers-reduced-motion/);
  assert.match(uiStyles, /aspect-ratio: 16 \/ 9/);
  assert.match(uiStyles, /overflow-x: auto/);
});

test("BI Overview and wallboard consume only the existing read projections", () => {
  assert.match(projectionContract, /request\("\/auth\/session"/);
  assert.match(projectionContract, /\/backend\/v1\/operating-analytics\/snapshot\?/);
  assert.match(projectionContract, /\/backend\/v1\/operating-workbench\/briefing\?/);
  assert.match(projectionContract, /new URLSearchParams\(\{ store_ref: storeRef, as_of: cutoff \}\)/);
  for (const surface of [overview, wallboard, briefing]) {
    assert.match(surface, /useBiProjection/);
    assert.doesNotMatch(surface, /ozon-primary/);
    assert.doesNotMatch(surface, /Math\.random/);
    assert.doesNotMatch(surface, /POST|PUT|PATCH|DELETE/);
  }
  assert.match(projectionHook, /controller\.abort/);
  assert.match(agentStatusRail, /pathname\.startsWith\("\/bi\/"\)/);
  assert.match(overview, /占位 0 显示为 no_data/);
  assert.match(overview, /change_abs|变化/);
  assert.match(overview, /data_gaps/);
  assert.match(overview, /source_evidence_id/);
  assert.match(overview, /优先工作项筛选/);
  assert.match(overview, /不改变服务端优先级/);
  assert.match(overview, /Decision spine/);
  assert.match(overview, /ResponsiveContainer/);
  assert.match(overview, /accessibilityLayer/);
  assert.match(wallboard, /暂停轮播/);
  assert.match(wallboard, /每 12 秒轮换/);
  assert.match(wallboard, /只读/);
});

test("BI routes expose the three reviewable product surfaces", () => {
  assert.match(read("../app/bi/overview/page.tsx"), /BiOverview/);
  assert.match(read("../app/bi/wallboard/page.tsx"), /BiWallboard/);
  assert.match(read("../app/bi/briefing/page.tsx"), /BiBriefing/);
});
