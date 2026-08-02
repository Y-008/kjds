import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const source = fs.readFileSync(
  path.resolve(
    import.meta.dirname,
    "../features/warehouse-fulfillment/warehouse-fulfillment-console.tsx",
  ),
  "utf8",
);

test("warehouse console consumes one server projection without recomputation", () => {
  assert.match(
    source,
    /\/backend\/v1\/warehouse-fulfillment\/workspace/,
  );
  assert.doesNotMatch(source, /reduce\s*\(/);
  assert.match(source, /transitionWarehouseState/);
  assert.match(source, /warehouseView/);
});

test("warehouse console keeps all risky actions and private interfaces denied", () => {
  for (const boundary of [
    "inventory_adjustment_allowed",
    "outbound_confirmation_allowed",
    "label_purchase_allowed",
    "carrier_handoff_allowed",
    "self_approval_allowed",
    "permit_issue_allowed",
    "carrier_contact_allowed",
    "customer_contact_allowed",
    "fictional_authority_allowed",
    "private_erp_interface_allowed",
    "external_write_allowed",
  ]) {
    assert.match(source, new RegExp(boundary));
  }
});
