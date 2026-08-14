import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const consoleSource = readFileSync(
  new URL("../features/agent-control/graph-console.tsx", import.meta.url),
  "utf8",
);
const railSource = readFileSync(
  new URL("../features/agent-control/agent-status-rail.tsx", import.meta.url),
  "utf8",
);
const styles = readFileSync(
  new URL("../features/agent-control/graph-console.module.css", import.meta.url),
  "utf8",
);
const intakeSource = readFileSync(
  new URL(
    "../features/agent-control/authority-intake-workbench.tsx",
    import.meta.url,
  ),
  "utf8",
);
const intakeStyles = readFileSync(
  new URL(
    "../features/agent-control/authority-intake-workbench.module.css",
    import.meta.url,
  ),
  "utf8",
);

test("Agent status is server-observed and not model self-certified", () => {
  assert.match(railSource, /agent-control\/projects\/kjds-059-bas123/);
  assert.match(consoleSource, /只有注册 Verifier 的 fresh observation/);
  assert.match(consoleSource, /external write false/);
  assert.doesNotMatch(consoleSource, /setData\(\{.*passed/s);
  assert.match(consoleSource, /node\.verification\.verifier/);
  assert.match(consoleSource, /node\.verification\.why/);
  assert.match(consoleSource, /node\.verification\.next_safe_action/);
  assert.match(consoleSource, /node\.verification\.dependencies/);
  assert.match(consoleSource, /打开 verifier \/ TODO/);
  assert.match(consoleSource, /no verifier-owned runtime status/);
});

test("seven Graph projections and verifier-owned TODO are navigable", () => {
  for (const kind of [
    "project",
    "requirements",
    "engineering",
    "runtime",
    "evidence",
    "commerce",
    "authority",
  ]) {
    assert.match(consoleSource, new RegExp(`"${kind}"`));
  }
  assert.match(consoleSource, /Verifier-owned TODO/);
  assert.match(consoleSource, /cannot satisfy Gate/);
  assert.match(consoleSource, /href="\/authority-intake"/);
});

test("Graph workspaces are explicitly bounded at 390px", () => {
  assert.match(styles, /@media \(max-width: 420px\)/);
  assert.match(styles, /overflow-x: hidden/);
  assert.match(styles, /overflow-wrap: anywhere/);
  assert.match(styles, /\.edgeList article \{ grid-template-columns: 1fr; \}/);
});

test("Authority Intake is endpoint-backed, role-aware, and never records a grant", () => {
  assert.match(intakeSource, /\/auth\/session/);
  assert.match(intakeSource, /\/auth\/authority-topology/);
  assert.match(intakeSource, /\/backend\/v1\/scope-grants\/intake/);
  assert.match(intakeSource, /\/backend\/v1\/scope-grants\/evidence/);
  assert.match(
    intakeSource,
    /\/backend\/v1\/scope-grants\/evidence\/reviews/,
  );
  assert.match(intakeSource, /\/backend\/v1\/scope-grants\/preflight/);
  assert.match(intakeSource, /allowed_actions\.submit_source/);
  assert.match(intakeSource, /can_current_actor_review/);
  assert.match(intakeSource, /can_current_actor_preflight/);
  assert.match(intakeSource, /grant endpoint exposed false/);
  assert.match(intakeSource, /role switch allowed false/);
  assert.match(intakeSource, /selected_api_chain/);
  assert.match(intakeSource, /input_sha256/);
  assert.match(intakeSource, /result_sha256/);
  assert.match(intakeSource, /external write/);
  assert.doesNotMatch(intakeSource, /scope-grants\/events/);
  assert.match(intakeStyles, /@media \(max-width: 420px\)/);
  assert.match(intakeStyles, /overflow-x: hidden/);
  assert.match(intakeStyles, /overflow-wrap: anywhere/);
});
