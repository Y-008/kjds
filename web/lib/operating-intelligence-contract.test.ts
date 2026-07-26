import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const component = readFileSync(
  new URL("../features/operating-intelligence/operating-intelligence.tsx", import.meta.url),
  "utf8",
);
const contracts = readFileSync(
  new URL("../features/operating-intelligence/contracts.ts", import.meta.url),
  "utf8",
);
const styles = readFileSync(
  new URL("../features/operating-intelligence/operating-intelligence.module.css", import.meta.url),
  "utf8",
);

test("operating intelligence reads all server-owned workspaces without demo data", () => {
  for (const path of [
    "/backend/v1/profit-ledger?",
    "/backend/v1/profit-ledger/erosion?",
    "/backend/v1/metrics",
    "/backend/v1/operating-tasks?",
    "/backend/v1/media/workbench",
  ]) {
    assert.match(component, new RegExp(path.replaceAll("?", "\\?")));
  }
  assert.match(component, /实际利润不可显示/);
  assert.match(component, /禁止按销售额猜分摊/);
  assert.match(component, /零平台副作用/);
  assert.doesNotMatch(component, /Math\.random/);
});

test("profit, anomaly, and media contracts keep blockers and evidence visible", () => {
  assert.match(contracts, /actual_profit: string \| null/);
  assert.match(contracts, /unallocated:/);
  assert.match(contracts, /minimum_sample: number/);
  assert.match(contracts, /cooldown_minutes: number/);
  assert.match(contracts, /automatic_business_action: false/);
  assert.match(contracts, /input_sha256: string/);
  assert.match(component, /侵蚀守恒/);
  assert.match(component, /不可变处理记录/);
  assert.match(component, /Delivery Manifest/);
});

test("mobile layout is explicitly bounded at 390px", () => {
  assert.match(styles, /@media \(max-width: 600px\)/);
  assert.match(styles, /overflow-x: hidden/);
  assert.match(styles, /minmax\(0, 1fr\)/);
});
