import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { readDashboardSource } from "./dashboard-source.ts";

const page = readDashboardSource();
const controller = readFileSync(
  new URL("../features/dashboard/use-dashboard-controller.tsx", import.meta.url),
  "utf8",
);
const reviewHandler = controller.slice(
  controller.indexOf("async function reviewSupplierQuote"),
  controller.indexOf("async function uploadSupplierComparison"),
);

test("supplier prices pass through lead, independent review, and finalization stages", () => {
  assert.match(page, /SUPPLIER QUOTE AUTHORITY/);
  assert.match(page, /\/backend\/v1\/sourcing\/quote-evidence/);
  assert.match(page, /\/backend\/v1\/sourcing\/comparison-finalize/);
  assert.match(page, /public_display_price/);
  assert.match(page, /supplier_confirmed_quote/);
  assert.match(page, /proforma_invoice/);
  assert.match(page, /上传人与复核人必须是不同身份/);
});

test("supplier quote review checks frozen commercial terms and never adds external actions", () => {
  for (const field of [
    "quote_authentic_original",
    "quote_supplier_identity_matches",
    "quote_product_spec_matches",
    "quote_amount_currency_moq_matches",
    "quote_validity_and_delivery_terms_present",
  ]) assert.match(page, new RegExp(field));
  assert.match(page, /报价成本强制 estimate/);
  assert.match(page, /不会自动采购、联系供应商或上架/);
  assert.doesNotMatch(reviewHandler, /procurement\/place_order/);
  assert.doesNotMatch(reviewHandler, /listing\/publish/);
});
