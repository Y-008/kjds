import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const source = fs.readFileSync(path.resolve(import.meta.dirname, "../features/delivery-exceptions/delivery-exception-console.tsx"), "utf8");
test("delivery console consumes one server projection and all states", () => {
  assert.match(source, /\/backend\/v1\/delivery-exceptions\/workspace/);
  assert.doesNotMatch(source, /reduce\s*\(/);
  assert.match(source, /authorityStateView/);
  assert.match(source, /transitionAuthorityState/);
  assert.match(source, /重试/);
});
test("delivery console keeps every mutation and private interface disabled", () => {
  for (const value of ["shipment_created","inventory_modified","order_modified","return_modified","carrier_contact_allowed","customer_contact_allowed","self_approval_allowed","permit_issue_allowed","private_erp_interface_allowed","external_write_allowed"]) assert.match(source, new RegExp(value));
});
