import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("candidate research UI keeps the evidence-first five-metric preflight", () => {
  assert.match(page, /\/backend\/v1\/evidence/);
  assert.match(page, /\/backend\/v1\/market\/research-signals/);
  assert.match(page, /\/backend\/v1\/market\/candidates\/intake/);
  assert.match(page, /\/backend\/v1\/market\/candidates\/sourcing-handoff/);
  for (const metric of [
    "demand_signal",
    "competition_gap",
    "supplier_available",
    "compliance_redline",
    "return_risk",
  ]) {
    assert.match(page, new RegExp(metric));
  }
  assert.match(page, /不会自动创建商品、采购或 Listing/);
  assert.match(page, /建立报价工作区/);
  assert.match(page, /不代表采购或上架批准/);
  assert.match(page, /观察窗口（天）/);
  assert.match(page, /样本量/);
  assert.match(page, /询价线 ≥50/);
  assert.match(page, /询价线 ≤30%/);
  assert.match(page, /\/startup\/candidate-research\.csv/);
  assert.match(page, /secondaryTemplate: "\/startup\/sku-passports\.csv"/);
  assert.match(page, /G0 前需经营负责人复核/);
  assert.match(page, /candidate_demand_report_evidence_id/);
  assert.match(page, /请先完成需求报告独立复核/);
  assert.match(page, /demand_report_evidence_id: candidateAssessment\.demand_report_evidence_id/);
  assert.match(page, /A\/B 只能按原始账户、供应商或官方规则依据声明/);
  assert.match(page, /权威等级不足，不能推动三报价/);
  assert.match(page, /不自动生成商品或上架/);
  assert.match(page, /provider_record_id/);
  assert.match(page, /license_status/);
  assert.match(page, /raw_fields_json/);
  assert.match(page, /cost_evidence/);
  assert.match(page, /查看 15 项成本来源/);
  assert.match(page, /无证据/);
});

test("startup path separates research readiness from real execution readiness", () => {
  const demandGate = page.indexOf('id: "SKU-000"');
  const candidateGate = page.indexOf('id: "SKU-001"');
  assert.ok(demandGate >= 0);
  assert.ok(candidateGate > demandGate);
  assert.match(page, /https:\/\/data\.ozon\.ru\/app/);
  assert.match(page, /取得合格需求研究依据/);
  assert.match(page, /body\.append\("requirement_id", "SKU-000"\)/);
  assert.match(page, /body\.append\("source_system", sourceSystem\)/);
  assert.match(page, /body\.append\("source_locator", sourceLocator\)/);
  assert.match(page, /name="demand_report_source_system"/);
  assert.match(page, /value="ozon_data"/);
  assert.match(page, /value="ozon_category_analytics"/);
  assert.match(page, /value="ozon_trends"/);
  assert.match(page, /value="ozon_what_to_sell"/);
  assert.match(page, /value="ozon_competitor_compare"/);
  assert.match(page, /value="fixed_test_data"/);
  assert.match(page, /name="demand_report_window_days"/);
  assert.match(page, /测试数据最多放行研究闭环/);
  assert.match(page, /真实经营要求 Ozon Data，或至少两个独立 Ozon 官方分析入口/);
  assert.match(page, /研究闭环/);
  assert.match(page, /真实经营/);
  assert.match(page, /\/backend\/v1\/operations\/demand-report-review/);
  assert.match(page, /复核身份必须与上传者不同/);
  assert.match(page, /研究与真实执行将按来源组合分别判定/);
  assert.match(page, /历史结论不可覆盖/);
  assert.match(page, /Passport 模板/);
});

test("candidate A or B authority requires an independent metric-scoped review", () => {
  assert.match(page, /candidate-evidence\/\$\{encodeURIComponent\(evidenceId\)\}\/authority-review/);
  assert.match(page, /authentic_original/);
  assert.match(page, /source_scope_matches/);
  assert.match(page, /authority_basis_verified/);
  assert.match(page, /Reviewer\/Compliance/);
  assert.match(page, /上传人不能复核自己的证据/);
  assert.match(page, /原件自报等级未被修改/);
  assert.match(page, /每份原件还必须有该指标的独立 A\/B 复核/);
});

test("operations center keeps gate blockers separate from real SLA work", () => {
  assert.match(page, /gateReadiness\?\.exception_workspace\.items/);
  assert.match(page, /Gate 阻断来自服务端 readiness，不伪造 SLA/);
  assert.match(page, /责任角色：\{item\.owner_role\}/);
  assert.match(page, /截止 \{new Date\(item\.due_at\)/);
  assert.match(page, /不会自动补证、关事故或写平台/);
});
