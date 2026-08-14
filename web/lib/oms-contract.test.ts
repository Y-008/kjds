import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../features/oms/oms-console.tsx", import.meta.url),
  "utf8",
);
const page = readFileSync(
  new URL("../app/oms/page.tsx", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL("../features/oms/oms.module.css", import.meta.url),
  "utf8",
);

test("native OMS reads the authorized exact-scope server projection", () => {
  assert.match(page, /<OmsConsole\s*\/>/);
  assert.match(source, /\/backend\/v1\/seller-os\/strategy-packs/);
  assert.match(source, /authorized_scope\.store_refs/);
  assert.match(source, /\/backend\/v1\/oms\/workspace\?\$\{query\.toString\(\)\}/);
  assert.match(source, /encodeURIComponent|URLSearchParams/);
  assert.match(source, /legacy inferred · false/);
  assert.match(source, /client recalculation · false/);
  assert.match(source, /supplier order \/ payment · false \/ false/);
  assert.match(source, /Approval \/ Permit · false \/ false/);
  assert.match(source, /external write · false/);
  assert.doesNotMatch(source, /\/v1\/orders|Math\.random|localStorage|document\.cookie/);
});

test("native OMS exposes measured states, immutable lineage, Agent limits, and mobile recovery", () => {
  assert.match(source, /"ready" \| "partial" \| "blocked" \| "no_data"/);
  assert.match(source, /不复用旧状态/);
  assert.match(source, /Fact \{event\.fact_id\} · Evidence \{event\.evidence_id\}/);
  assert.match(source, /decision_support_only/);
  assert.match(source, /模型可建议，不能自批、自发 Permit 或执行/);
  assert.match(source, /role="status"/);
  assert.match(source, /role="alert"/);
  assert.match(source, />重试</);
  assert.match(css, /@media \(max-width: 420px\)/);
  assert.match(css, /overflow-x: hidden/);
});
