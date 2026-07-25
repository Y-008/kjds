import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panel = readFileSync(
  new URL("../features/dashboard/sourcing-panel.tsx", import.meta.url),
  "utf8",
);
const controller = readFileSync(
  new URL("../features/dashboard/use-dashboard-controller.tsx", import.meta.url),
  "utf8",
);

test("logistics workspace versions evidence-backed rates and calculates chargeable weight", () => {
  assert.match(panel, /LOGISTICS COST INTELLIGENCE/);
  assert.match(panel, /logistics_volumetric_divisor/);
  assert.match(panel, /logistics_weight_increment/);
  assert.match(panel, /logistics_evidence_id/);
  assert.match(controller, /\/backend\/v1\/logistics\/rate-cards/);
  assert.match(controller, /\/backend\/v1\/logistics\/calculations/);
});

test("supplier comparison can use a logistics calculation without granting automatic actions", () => {
  assert.match(panel, /logistics_rate_card_id/);
  assert.match(controller, /comparison_logistics_currency_to_cny_rate/);
  assert.match(panel, /AI 只解释异常和建议比价/);
  assert.match(panel, /actual 需承运商最终账单/);
  assert.doesNotMatch(panel, /自动采购物流/);
});
