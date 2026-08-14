import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const source = fs.readFileSync(
  path.resolve(import.meta.dirname, "../features/growth-experiments/growth-experiment-console.tsx"),
  "utf8",
);

test("growth experiment console consumes one server projection", () => {
  assert.match(source, /\/backend\/v1\/growth-experiments\/workspace/);
  assert.doesNotMatch(source, /\/backend\/v1\/marketplace-growth/);
  assert.doesNotMatch(source, /reduce\s*\(/);
});

test("growth experiment console uses the executable state model and keeps authority denials", () => {
  assert.match(source, /authorityStateView/);
  assert.match(source, /transitionAuthorityState/);
  for (const boundary of [
    "price_changed", "promotion_created", "advertising_spend_created",
    "self_approval_allowed", "permit_issue_allowed",
    "private_erp_interface_allowed", "external_write_allowed",
  ]) assert.match(source, new RegExp(boundary));
});
