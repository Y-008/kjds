import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("finance uploads are handed to a different reviewer without automatic posting", () => {
  assert.match(page, /ozon_accrual/);
  assert.match(page, /ozon_fee/);
  assert.match(page, /ozon_return/);
  assert.match(page, /ozon_settlement/);
  assert.match(page, /\/backend\/v1\/imports\/\$\{encodeURIComponent\(importId\)\}\/finance-review/);
  assert.match(page, /尚未入账/);
  assert.match(page, /上传人不能复核自己的文件/);
  assert.match(page, /不会自动入账、批准会计字段或启动对账/);
  assert.match(page, /report_period_start/);
  assert.match(page, /report_period_end/);
  assert.match(page, /结构化交接期间/);
  assert.match(page, /提交前核验包/);
  assert.match(page, /review_packet\.source\.sha256/);
  assert.match(page, /review_packet\.source\.submitted_by/);
  assert.match(page, /review_packet\.import\.accepted_count/);
  assert.match(page, /review_packet\.aggregates\.currency_totals/);
  assert.match(page, /原件、哈希、血缘和行号连续性均通过/);
  assert.match(page, /只展示只读聚合，不返回商品、订单或客户原始行/);
  assert.match(page, /不会自动接受、分类或入账/);
  assert.match(page, /\/backend\/v1\/imports\/ozon\/preflight/);
  assert.match(page, /请保留原文件，不要手工改列名/);
  assert.ok(
    page.indexOf('/backend/v1/imports/ozon/preflight') < page.indexOf('/backend/v1/imports/ozon"'),
  );
});

test("accepted accrual reports remain outside profit until accounting classification", () => {
  assert.match(page, /来源已核验，仍禁止计入利润/);
  assert.match(page, /独立、版本化的会计分类合同/);
  assert.match(page, /销售、折扣、佣金、物流、补偿/);
  assert.match(page, /不得把整份报告当作平台费用/);
  assert.match(page, /\/accrual-classifications/);
  assert.match(page, /不生成财务分录/);
  assert.match(page, /不替代订单收入/);
  assert.match(page, /name="accrual_pair"/);
  assert.match(page, /name="accrual_accounting_class"/);
  assert.match(page, /name="accrual_expected_sign"/);
  assert.match(page, /currency_totals\.map/);
  assert.match(page, /实际符号/);
  assert.match(page, /合同符号/);
  assert.match(page, /批准版本化控制分类/);
  assert.doesNotMatch(page, /approveAccrualClassification[\s\S]*?\/facts\/promote/);
});

test("finance review UI is role-gated and submits all four source checks", () => {
  for (const role of ["reviewer", "compliance", "admin"]) assert.match(page, new RegExp(`"${role}"`));
  for (const check of [
    "authentic_account_export",
    "period_matches",
    "not_public_sample",
    "complete_export",
  ]) {
    assert.match(page, new RegExp(check));
  }
  assert.match(page, /保存不可变复核记录/);
  assert.doesNotMatch(page, /finance-review[^\n]+facts\/promote/);
});

test("accepted fee reports expose only observed codes for separate versioned approval", () => {
  assert.match(page, /\/fee-codes/);
  assert.match(page, /\/fee-mappings/);
  assert.match(page, /只显示该已接受文件中真实出现的代码/);
  assert.match(page, /仍未自动入账/);
  assert.match(page, /批准版本化映射/);
  assert.doesNotMatch(page, /approveFeeMapping[\s\S]*?\/facts\/promote/);
});
