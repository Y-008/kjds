import assert from "node:assert/strict";
import test from "node:test";
import { readDashboardSource } from "./dashboard-source.ts";

const page = readDashboardSource();

test("actual cost workbench reads one server catalog and never duplicates authority rules", () => {
  assert.match(page, /\/backend\/v1\/finance\/cost-authorities/);
  assert.match(page, /cost-actual-authority-v1/);
  assert.match(page, /costAuthorityCatalog\?\.items\.map/);
  assert.match(page, /actualCostAuthorityItem\?\.authorities\.map/);
  assert.doesNotMatch(page, /supplier_invoice_payment/);
  assert.doesNotMatch(page, /ozon_transaction_settlement/);
});

test("actual cost workbench supports read-only status and independent immutable review", () => {
  assert.match(page, /实际成本权威复核/);
  assert.match(page, /\/backend\/v1\/finance\/cost-evidence\/\$\{encodeURIComponent\(evidenceId\)\}\/authority-review/);
  for (const field of [
    "actual_cost_authentic_original",
    "actual_cost_scope_matches",
    "actual_cost_charging_party_matches",
    "actual_cost_amount_currency_period_matches",
  ]) assert.match(page, new RegExp(field));
  for (const role of ["reviewer", "compliance", "admin"]) assert.match(page, new RegExp(`"${role}"`));
  assert.match(page, /Operator 可以查询状态/);
  assert.match(page, /保存不可变实际成本复核/);
});

test("actual cost review remains evidence-only and has no business execution shortcut", () => {
  assert.match(page, /不会自动改写利润场景、入账、采购、定价或上架/);
  assert.doesNotMatch(page, /reviewActualCostAuthority[\s\S]*?\/facts\/promote/);
  assert.doesNotMatch(page, /reviewActualCostAuthority[\s\S]*?listing\/publish/);
  assert.doesNotMatch(page, /reviewActualCostAuthority[\s\S]*?procurement\/place_order/);
});
