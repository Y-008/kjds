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

test("all executive projections are server-owned and retries keep one idempotency key", () => {
  for (const field of [
    "organization_readiness",
    "critical_path",
    "top1_scorecard",
    "cash_at_risk",
    "delivery_gate",
  ]) {
    assert.match(contracts, new RegExp(`${field}:`));
  }
  for (const field of [
    "squad_readiness",
    "role_conflicts",
    "parallel_execution",
    "integration_queue",
    "capacity_risk",
    "next_release_train",
  ]) {
    assert.match(contracts, new RegExp(`${field}:`));
    assert.match(component, new RegExp(`brief\\.${field}`));
  }
  assert.match(component, /静态合同完整性 VERIFIED 不代表真人到岗/);
  assert.match(component, /前端不计算晋级、依赖、候选或发布结论/);
  assert.match(component, /runtime authority connected = false/);
  assert.match(component, /retryCommand\.current/);
  assert.match(component, /网络失败；再次提交会复用同一幂等键/);
  assert.doesNotMatch(component, /\.sort\(/);
  assert.doesNotMatch(component, /排名.*sort/);
});

test("team control has an accessible and explicitly bounded mobile layout", () => {
  assert.match(styles, /@media \(max-width: 680px\)/);
  assert.match(styles, /@media \(max-width: 420px\)/);
  assert.match(styles, /overflow-x: hidden/);
  assert.match(styles, /minmax\(220px, 1fr\)/);
  assert.match(styles, /\.scoreGrid/);
  assert.match(styles, /\.enterpriseGrid/);
  assert.match(styles, /\.enterpriseFacts/);
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /\.enterpriseGrid summary \{ min-height: 44px/);
  assert.match(styles, /\.enterpriseSection > header span:not\(\.status\) \{ color: #53665c/);
  assert.match(styles, /\.enterpriseList small \{ color: #4f6258/);
  assert.match(styles, /\.enterpriseFacts dt \{ color: #4f6258/);
  assert.match(component, /role="alert"/);
  assert.match(component, /aria-live="polite"/);
  assert.match(component, /<details>/);
});

test("enterprise positioning v2 is a read-only server-owned projection", () => {
  assert.match(component, /\/backend\/v1\/enterprise-positioning\/current/);
  assert.match(component, /\/backend\/v1\/enterprise-positioning\/recommend/);
  assert.match(component, /Promise\.allSettled/);
  assert.match(component, /企业定位与角色建议服务不可用；团队总控仍保持独立可用/);
  assert.match(component, /角色状态、缺岗、Gate 与顺序全部由服务端返回/);
  assert.match(component, /未保存 \/ 不任命 \/ 不授权/);
  assert.match(component, /profile_scope\.grants_authority/);
  assert.match(component, /external_write_performed/);
  for (const field of [
    "contract_id",
    "profile_scope.scope_ref",
    "archetype_ref",
    "role_summary.unsupported_gap",
    "role_kind",
    "ai_templates_excluded",
    "sod_conflict_refs",
    "role_template_is_appointment_evidence",
    "same_principal_allowed",
    "role_bundle_mode",
    "source_bundle_sha256",
  ]) {
    assert.match(component, new RegExp(field.replace(".", "\\.")));
  }
  assert.doesNotMatch(component, /role_roster\.sort/);
  assert.doesNotMatch(component, /role_roster\.filter/);
  assert.doesNotMatch(component, /role_gaps\.sort/);
  assert.doesNotMatch(component, /required_gates\.sort/);
});

test("enterprise profile and recommendation contracts freeze all v2 inputs and outputs", () => {
  for (const field of [
    "enterprise_ref",
    "business_model",
    "stage",
    "headcount_band",
    "markets",
    "platforms",
    "risk_class",
    "primary_objective",
  ]) {
    assert.match(contracts, new RegExp(`${field}:`));
    assert.match(component, new RegExp(`name="${field}"`));
  }
  for (const field of [
    "profile_scope",
    "enterprise_positioning",
    "role_roster",
    "role_summary",
    "seat_plan",
    "minimum_human_accountability",
    "separation_of_duties",
    "role_gaps",
    "next_role_activation",
    "capacity_plan",
    "system_actions",
    "source_hashes",
    "source_bundle_sha256",
    "snapshot_sha256",
  ]) {
    assert.match(contracts, new RegExp(`${field}:`));
  }
  assert.match(contracts, /role_template_ref: string/);
  assert.match(contracts, /"required_now"/);
  assert.match(contracts, /"supporting_ai"/);
  assert.match(contracts, /"on_demand"/);
  assert.match(contracts, /"standby"/);
  assert.match(contracts, /recommendation_status: "unsupported_gap"/);
  assert.doesNotMatch(contracts, /test_principal_ref/);
});

test("enterprise positioning form and mobile rules meet the WCAG boundary", () => {
  assert.match(component, /<label htmlFor="positioning-enterprise-ref">/);
  assert.match(component, /<select id="positioning-business-model"/);
  assert.match(component, /aria-busy=\{busy \|\| simulating\}/);
  assert.match(component, /role="status" aria-live="polite"/);
  assert.match(component, /tabIndex=\{-1\}/);
  assert.match(component, /requestAnimationFrame\(\(\) => positioningHeadingRef\.current\?\.focus\(\)\)/);
  assert.match(component, /className=\{styles\.positioningError\} role="alert"/);
  assert.match(styles, /\.profileFields input, \.profileFields select \{[^}]*min-height: 44px/);
  assert.match(styles, /\.profileActions button \{[^}]*min-height: 44px/);
  assert.match(styles, /@media \(max-width: 680px\)[^{]*\{[^}]*overflow-x: hidden/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /:focus-visible/);
});

test("team advance retries only an identical uncertain logical payload", () => {
  assert.match(component, /const logicalPayload = JSON\.stringify/);
  assert.match(component, /retryCommand\.current\?\.logicalPayload !== logicalPayload/);
  assert.match(component, /else \{\s*retryCommand\.current = null;\s*\}/);
  assert.match(component, /网络失败；再次提交会复用同一幂等键/);
});
