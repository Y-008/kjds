import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const component = readFileSync(new URL("../features/agent-control/project-manager-console.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../features/agent-control/project-manager-console.module.css", import.meta.url), "utf8");

test("project manager console reads WBS and heartbeat replay only", () => {
  assert.match(component, /project-graph\/.+\/task-contract/);
  assert.match(component, /heartbeat\/latest/);
  assert.match(component, /external_write_allowed/);
  assert.match(component, /proof_state/);
  assert.match(component, /evidence_state/);
  assert.match(component, /operational_state/);
  assert.match(component, /economic_state/);
  assert.doesNotMatch(component, /method:\s*["'](?:POST|PUT|PATCH|DELETE)/);
});

test("project manager console exposes bounded mobile and focus styles", () => {
  assert.match(styles, /@media \(max-width: 520px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /overflow-wrap: anywhere/);
});
