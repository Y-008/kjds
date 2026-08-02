import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const consoleSource = fs.readFileSync(path.resolve(import.meta.dirname, "../features/native-parity/native-parity-console.tsx"), "utf8");
const contracts = fs.readFileSync(path.resolve(import.meta.dirname, "../features/native-parity/contracts.ts"), "utf8");
const styles = fs.readFileSync(path.resolve(import.meta.dirname, "../features/native-parity/native-parity.module.css"), "utf8");
const commerce = fs.readFileSync(path.resolve(import.meta.dirname, "../features/commerce-os/commerce-os-console.tsx"), "utf8");

test("native parity console consumes one server projection without promotion", () => {
  assert.match(consoleSource, /\/backend\/v1\/native-parity-acceptance\/workspace/);
  assert.match(consoleSource, /workspace\.counts\.states/);
  assert.match(consoleSource, /params\.set\("as_of", frozenAsOf\)/);
  assert.match(consoleSource, /load\(workspace\.next_cursor, undefined, workspace\.as_of\)/);
  assert.match(consoleSource, /item\.acceptance_artifact\.blockers/);
  assert.match(consoleSource, /client_can_recalculate_or_promote=false/);
  assert.doesNotMatch(consoleSource, /every\([^)]*status[^)]*passed/);
  assert.match(contracts, /external_graph_verifier/);
});

test("native parity page has desktop and 390-safe overflow rules", () => {
  assert.match(styles, /overflow-x: hidden/);
  assert.match(styles, /@media \(max-width:420px\)/);
  assert.match(styles, /overflow-wrap:anywhere/);
});

test("Commerce OS drills into native parity acceptance", () => {
  assert.match(commerce, /href="\/native-parity"/);
  assert.match(commerce, /原生同等能力验收权威/);
});
