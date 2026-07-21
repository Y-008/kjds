import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("best solution mode captures constraints and criteria without execution rights", () => {
  assert.match(page, /best_solution/);
  assert.match(page, /name="decision_hard_constraints"/);
  assert.match(page, /name="decision_criteria"/);
  assert.match(page, /长期风险调整价值/);
  assert.match(page, /总拥有成本/);
  assert.match(page, /可逆性与回滚/);
  assert.match(page, /提交后生成不可变合同/);
  assert.match(page, /该合同没有经营执行权/);
});

test("best solution analysis records full comparison and requires a counterargument", () => {
  assert.match(page, /name={`best_constraint_/);
  assert.match(page, /name={`best_evidence_quality_/);
  assert.match(page, /name={`best_tco_/);
  assert.match(page, /name={`best_maximum_loss_/);
  assert.match(page, /name={`best_rollback_/);
  assert.match(page, /name="best_invalidation_conditions"/);
  assert.match(page, /name="best_review_at"/);
  assert.match(page, /required={contract\?\.profile_id === "best_solution"}/);
  assert.match(page, /不会把“最新”或“最复杂”自动当成最好/);
});
