import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const consoleSource = fs.readFileSync(
  path.join(
    root,
    "features/customer-service/customer-service-console.tsx",
  ),
  "utf8",
);
const css = fs.readFileSync(
  path.join(
    root,
    "features/customer-service/customer-service.module.css",
  ),
  "utf8",
);

test("customer service consumes one server projection without client state logic", () => {
  assert.match(consoleSource, /\/backend\/v1\/customer-service\/workspace/);
  assert.match(consoleSource, /workspace\.cases/);
  assert.match(consoleSource, /workspace\.counts\.verified_sends/);
  assert.doesNotMatch(consoleSource, /reduce\s*\(/);
  assert.doesNotMatch(consoleSource, /backend\/v1\/returns/);
  assert.doesNotMatch(consoleSource, /backend\/v1\/approvals/);
  assert.doesNotMatch(consoleSource, /backend\/v1\/limited-execution/);
});

test("customer service renders truth, privacy and execution boundaries", () => {
  for (const state of [
    "loading",
    "error",
    "no_data",
    "ready",
    "partial",
    "blocked",
  ]) {
    assert.match(consoleSource, new RegExp(state));
  }
  for (const boundary of [
    "raw_message_body_exposed",
    "raw_pii_read_allowed",
    "self_approval_allowed",
    "permit_issue_allowed",
    "message_adapter_enabled",
    "private_erp_interface_allowed",
    "external_write_allowed",
  ]) {
    assert.match(consoleSource, new RegExp(boundary));
  }
  assert.match(consoleSource, /\/oms/);
  assert.match(consoleSource, /\/returns/);
  assert.match(consoleSource, /\/evidenceops/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /overflow-x: clip/);
});
