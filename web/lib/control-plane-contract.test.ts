import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const surface = read("../features/control-tower/control-plane.tsx");
const styles = read("../features/control-tower/control-plane.module.css");

test("control-plane surfaces keep the five product planes explicit", () => {
  for (const token of [
    "CapabilityAssertion",
    "Journey",
    "Authority Scope",
    "Commercial Scope",
    "Operational Scope",
    "evidence_backed_decisions_completed",
    "ActionSafetyEnvelope",
    "scenario_",
    "Readback",
    "Kill Switch",
  ]) {
    assert.match(surface, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  for (const state of ["documented", "designed", "implemented", "tested", "replayed", "pilot_ready", "production_ready", "blocked", "deprecated"]) {
    assert.match(surface, new RegExp(state));
  }
  assert.match(surface, /useBiProjection\(\)/);
  assert.doesNotMatch(surface, /Math\.random/);
  assert.doesNotMatch(surface, /POST|PUT|PATCH|DELETE/);
});

test("control-plane UI remains responsive and accessible", () => {
  assert.match(styles, /@media \(max-width: 720px\)/);
  assert.match(styles, /grid-template-columns: 1fr/);
  assert.match(surface, /role="status"/);
  assert.match(surface, /role="alert"/);
  assert.match(surface, /caption=/);
});

test("control-plane routes expose read-only review surfaces", () => {
  for (const route of [
    "../app/bi/capabilities/page.tsx",
    "../app/bi/journeys/[journey_ref]/page.tsx",
    "../app/bi/sources/page.tsx",
    "../app/bi/enterprise/page.tsx",
    "../app/bi/product-value/page.tsx",
    "../app/bi/scenarios/page.tsx",
    "../app/bi/agent-control/page.tsx",
    "../app/bi/reliability/page.tsx",
  ]) {
    assert.match(read(route), /ControlPlanePage/);
  }
});
