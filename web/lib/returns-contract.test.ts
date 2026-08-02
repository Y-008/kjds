import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const consoleSource = fs.readFileSync(
  path.join(root, "features/returns/returns-console.tsx"),
  "utf8",
);
const css = fs.readFileSync(
  path.join(root, "features/returns/returns.module.css"),
  "utf8",
);

test("returns consumes one server projection without client refund logic", () => {
  assert.match(consoleSource, /\/backend\/v1\/returns\/workspace/);
  assert.match(consoleSource, /workspace\.returns/);
  assert.match(consoleSource, /workspace\.counts\.returned_units/);
  assert.doesNotMatch(consoleSource, /reduce\s*\(/);
  assert.doesNotMatch(consoleSource, /backend\/v1\/finance-control/);
});

test("returns renders truth states and immutable authority boundaries", () => {
  for (const state of ["loading", "error", "no_data", "partial", "blocked"]) {
    assert.match(consoleSource, new RegExp(state));
  }
  for (const boundary of [
    "customer_service_case_authority_available",
    "private_erp_interface_allowed",
    "self_approval_allowed",
    "permit_issue_allowed",
    "external_write_allowed",
  ]) {
    assert.match(consoleSource, new RegExp(boundary));
  }
  assert.match(consoleSource, /\/oms/);
  assert.match(consoleSource, /\/finance-control/);
  assert.match(consoleSource, /\/profit-ledger/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /overflow-x: clip/);
});
