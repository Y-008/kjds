import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const component = readFileSync(new URL("../features/agent-control/project-manager-console.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../features/agent-control/project-manager-console.module.css", import.meta.url), "utf8");

test("project manager console reads WBS and heartbeat replay only", () => {
  assert.match(component, /project-graph\/.+\/task-contract/);
  assert.match(component, /heartbeat\/latest/);
  assert.match(component, /project-graph\/.+\/next-wave/);
  assert.match(component, /下一波任务候选/);
  assert.match(component, /PROJECTION ONLY/);
  assert.match(component, /external_write_allowed/);
  assert.match(component, /proof_state/);
  assert.match(component, /evidence_state/);
  assert.match(component, /operational_state/);
  assert.match(component, /economic_state/);
  assert.doesNotMatch(component, /method:\s*["'](?:POST|PUT|PATCH|DELETE)/);
});

test("next-wave projection remains optional and visibly read-only", () => {
  assert.match(component, /nextWaveError/);
  assert.match(component, /nextWaveResponse\.ok/);
  assert.match(component, /task_brief/);
  assert.match(component, /definition_of_ready/);
  assert.match(component, /projection_only/);
  assert.match(component, /dispatch_allowed/);
  assert.match(component, /不会派发 Agent/);
  assert.match(component, /unresolved_dependencies/);
});

test("project manager console exposes bounded mobile and focus styles", () => {
  assert.match(styles, /@media \(max-width: 520px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /overflow-wrap: anywhere/);
});
