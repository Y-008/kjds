import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("EvidenceOps is an independent product entry backed by one server plan contract", () => {
  const page = read("../app/evidenceops/page.tsx");
  const copilot = read("../features/evidenceops/evidenceops-copilot.tsx");
  const contracts = read("../features/evidenceops/contracts.ts");
  const shell = read("../features/dashboard/dashboard-shell.tsx");

  assert.match(page, /<EvidenceOpsCopilot\s*\/>/);
  assert.doesNotMatch(page, /\/backend\//);
  assert.match(copilot, /\/backend\/v1\/evidenceops\/plan/);
  assert.match(copilot, /objective: nextObjective/);
  assert.match(copilot, /store_ref: "ozon-primary"/);
  assert.match(copilot, /plan\.truth_ledger\.verified_facts/);
  assert.match(copilot, /plan\.truth_ledger\.unknowns/);
  assert.match(copilot, /plan\.missions\.map/);
  assert.match(copilot, /plan\.agent_team\.map/);
  assert.match(copilot, /plan\.control_envelope\.forbidden_actions/);
  assert.match(copilot, /requestVersion/);
  assert.match(copilot, /现有计划不会被网络错误覆盖/);
  assert.match(contracts, /contract_id: "kjds-evidenceops-copilot-plan-v1"/);
  assert.match(contracts, /synthetic_business_data_allowed: false/);
  assert.match(contracts, /external_write_allowed: false/);
  assert.match(contracts, /automatic_execution: false/);
  assert.match(contracts, /objective_can_promote_fact: false/);
  assert.doesNotMatch(
    copilot,
    /\/commands|\/write-attempt|\/receipt|Math\.random|localStorage|sessionStorage/,
  );
  assert.match(shell, /href="\/evidenceops"/);
});

test("EvidenceOps product surface has explicit responsive states and truth messaging", () => {
  const copilot = read("../features/evidenceops/evidenceops-copilot.tsx");
  const styles = read("../features/evidenceops/evidenceops-copilot.module.css");

  assert.match(copilot, /正在读取真源/);
  assert.match(copilot, /计划暂不可用/);
  assert.match(copilot, /不知道，就明确写不知道/);
  assert.match(copilot, /不保存对话 · 不调用外部模型 · 不生成演示经营数据/);
  assert.match(copilot, /平台写入与自动执行/);
  assert.match(styles, /@media \(max-width: 980px\)/);
  assert.match(styles, /@media \(max-width: 680px\)/);
});
