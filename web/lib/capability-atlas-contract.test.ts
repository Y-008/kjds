import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("capability atlas is a server-owned read-only tree with truthful status boundaries", () => {
  const page = read("../app/capability-atlas/page.tsx");
  const atlas = read("../features/capability-atlas/capability-atlas.tsx");
  const graph = read("../features/capability-atlas/operating-graph-explorer.tsx");
  const contracts = read("../features/capability-atlas/contracts.ts");
  const shell = read("../features/dashboard/dashboard-shell.tsx");

  assert.match(page, /<CapabilityAtlas\s*\/>/);
  assert.doesNotMatch(page, /\/backend\//);
  assert.match(atlas, /\/backend\/v1\/capability-atlas\/snapshot/);
  assert.match(atlas, /atlas\?\.release_version/);
  assert.match(atlas, /atlas\?\.registry_version/);
  assert.doesNotMatch(atlas, /KJDS 0\.\d+\.\d+/);
  assert.match(atlas, /atlas\.domains/);
  assert.match(atlas, /domain\.capabilities/);
  assert.match(atlas, /selected\.linkfox/);
  assert.match(atlas, /selected\.surpass/);
  assert.match(atlas, /selected\.russia/);
  assert.match(atlas, /selected\.global/);
  assert.match(atlas, /selected\.technology/);
  assert.match(atlas, /LinkFox 始终是 C 级公开工作流参考/);
  assert.match(atlas, /受门禁能力不会被包装成已接入/);
  assert.match(atlas, /useState<ExplorerMode>\("point"\)/);
  assert.match(atlas, /点 · 原子功能/);
  assert.match(atlas, /线 · 端到端流/);
  assert.match(atlas, /面 · 经营控制/);
  assert.match(atlas, /counts\.atomic_points/);
  assert.match(atlas, /counts\.value_streams/);
  assert.match(atlas, /counts\.operating_surfaces/);
  assert.match(graph, /operating_graph\.atomic_points/);
  assert.match(graph, /operating_graph\.value_streams/);
  assert.match(graph, /operating_graph\.operating_surfaces/);
  assert.match(graph, /point\.evidence_gate/);
  assert.match(graph, /point\.failure_queue/);
  assert.match(graph, /point\.readback/);
  assert.match(graph, /stream\.entry_gate/);
  assert.match(graph, /stream\.exit_gate/);
  assert.match(graph, /stream\.human_takeover/);
  assert.match(graph, /surface\.truth_owner/);
  assert.match(graph, /surface\.write_boundary/);
  assert.match(contracts, /"implemented" \| "ready" \| "gated" \| "research_only"/);
  assert.match(contracts, /release_version: string/);
  assert.match(contracts, /registry_version: string/);
  assert.match(contracts, /contract_id: "kjds-cross-border-operating-graph-v1"/);
  assert.match(contracts, /marketing_claims_are_business_facts: false/);
  assert.match(contracts, /linkfox_ozon_integration_verified: false/);
  assert.match(contracts, /client_can_promote_status: false/);
  assert.match(contracts, /external_write_allowed: false/);
  assert.match(contracts, /operating_graph_is_execution_authority: false/);
  assert.match(shell, /href="\/capability-atlas"/);
  assert.doesNotMatch(
    atlas,
    /\/commands|\/write-attempt|\/receipt|Math\.random|localStorage|sessionStorage/,
  );
  assert.doesNotMatch(
    graph,
    /fetchJson|\/commands|\/write-attempt|Math\.random|localStorage|sessionStorage/,
  );
});

test("capability atlas keeps interactive filters, semantic state and responsive tree layout", () => {
  const atlas = read("../features/capability-atlas/capability-atlas.tsx");
  const styles = read("../features/capability-atlas/capability-atlas.module.css");
  const graph = read("../features/capability-atlas/operating-graph-explorer.tsx");
  const graphStyles = read("../features/capability-atlas/operating-graph-explorer.module.css");

  assert.match(atlas, /aria-label="搜索能力"/);
  assert.match(atlas, /aria-expanded=\{!isCollapsed\}/);
  assert.match(atlas, /aria-pressed=\{selectedId === capability\.id\}/);
  assert.match(atlas, /scope === "ALL" \|\| capability\.markets\.includes\(scope\)/);
  assert.match(atlas, /status === "all" \|\| capability\.status === status/);
  assert.match(styles, /\.domainTree::before/);
  assert.match(styles, /\.domainBranch::before/);
  assert.match(styles, /\.leafConnector/);
  assert.match(styles, /@media \(max-width: 980px\)/);
  assert.match(styles, /@media \(max-width: 680px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(graph, /aria-pressed=\{point\.id === selectedId\}/);
  assert.match(graph, /visiblePointIds/);
  assert.match(graph, /scope === "ALL" \|\| point\.markets\.includes\(scope\)/);
  assert.match(graph, /status === "all" \|\| point\.status === status/);
  assert.match(graphStyles, /\.stageLane/);
  assert.match(graphStyles, /\.surfaceMatrix/);
  assert.match(graphStyles, /@media \(max-width: 980px\)/);
  assert.match(graphStyles, /@media \(max-width: 680px\)/);
});
