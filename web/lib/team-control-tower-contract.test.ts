import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const component = readFileSync(
  new URL("../features/team-control-tower/team-control-tower.tsx", import.meta.url),
  "utf8",
);
const contracts = readFileSync(
  new URL("../features/team-control-tower/contracts.ts", import.meta.url),
  "utf8",
);
const styles = readFileSync(
  new URL("../features/team-control-tower/team-control-tower.module.css", import.meta.url),
  "utf8",
);

test("team control renders one server-owned next action for the four flows", () => {
  assert.match(component, /\/backend\/v1\/team-control\/brief\?/);
  assert.match(component, /\/backend\/v1\/team-control\/advance\?/);
  assert.match(component, /ONE EXECUTIVE NEXT ACTION/);
  assert.match(component, /四条主线、一个唯一下一动作/);
  assert.match(component, /brief\.flows\.map/);
  assert.match(component, /brief\.critical_path\.phases/);
  assert.match(component, /brief\.top1_scorecard\.dimensions/);
  assert.match(component, /brief\.delivery_gate\.gates/);
  assert.match(component, /global_top1_claim = false/);
  assert.match(component, /brief\.next_action\.evidence_required/);
  assert.match(component, /actual_cash_truth/);
  assert.match(component, /formal Gate PASS = false/);
  assert.doesNotMatch(component, /Math\.random/);
});

test("client cannot submit exact scope, actors, credentials, approvals, or permits", () => {
  assert.match(contracts, /continuation: string/);
  assert.match(contracts, /external_write_allowed: false/);
  assert.doesNotMatch(component, /tenant_ref:/);
  assert.doesNotMatch(component, /entity_ref:/);
  assert.doesNotMatch(component, /scope_authority_sha256:/);
  assert.doesNotMatch(component, /actor_id:/);
  assert.doesNotMatch(component, /approved:/);
  assert.doesNotMatch(component, /permit:/);
  assert.doesNotMatch(component, /approval_id:/);
});

test("all five executive projections are server-owned and retries keep one idempotency key", () => {
  for (const field of [
    "organization_readiness",
    "critical_path",
    "top1_scorecard",
    "cash_at_risk",
    "delivery_gate",
  ]) {
    assert.match(contracts, new RegExp(`${field}:`));
  }
  assert.match(component, /retryCommand\.current/);
  assert.match(component, /网络失败；再次提交会复用同一幂等键/);
  assert.doesNotMatch(component, /排名.*sort/);
});

test("team control has an explicitly bounded mobile layout", () => {
  assert.match(styles, /@media \(max-width: 680px\)/);
  assert.match(styles, /overflow-x: hidden/);
  assert.match(styles, /minmax\(220px, 1fr\)/);
  assert.match(styles, /\.scoreGrid/);
});
