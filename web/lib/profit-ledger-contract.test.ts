import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL(
    "../features/profit-ledger/profit-ledger-console.tsx",
    import.meta.url,
  ),
  "utf8",
);
const page = readFileSync(
  new URL("../app/profit-ledger/page.tsx", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL(
    "../features/profit-ledger/profit-ledger.module.css",
    import.meta.url,
  ),
  "utf8",
);

test("profit ledger consumes one native exact-scope server projection", () => {
  assert.match(page, /<ProfitLedgerConsole\s*\/>/);
  assert.match(source, /\/backend\/v1\/profit-ledger\?/);
  assert.equal(
    (source.match(/\/backend\/v1\/profit-ledger/g) ?? []).length,
    1,
  );
  assert.match(source, /页面不重算/);
  assert.match(source, /client recalculation · false/);
  assert.match(source, /proportional allocation · false/);
  assert.match(source, /服务端 opaque cursor/);
  assert.doesNotMatch(
    source,
    /reduce\s*\(|parseFloat|Number\s*\(|Math\.random|localStorage|document\.cookie/,
  );
});

test("profit ledger renders truth states, fifteen legs and immutable controls", () => {
  assert.match(source, /role="status"/);
  assert.match(source, /role="alert"/);
  assert.match(source, />重试</);
  assert.match(source, /真实 no_data/);
  assert.match(source, /最新权威记录失败关闭/);
  assert.match(source, /FIFTEEN ACTUAL COST LEGS/);
  for (const cost of [
    "采购成本",
    "国内物流",
    "国际头程",
    "包装",
    "仓储",
    "关税",
    "税费",
    "尾程",
    "平台佣金",
    "广告",
    "退款退货",
    "汇兑",
    "资金占用",
    "售后赔付",
    "损耗",
  ]) {
    assert.match(source, new RegExp(cost));
  }
  assert.match(source, /ACTUAL CASH CM3/);
  assert.match(source, /self Approval \/ Permit · false \/ false/);
  assert.match(source, /external write · false/);
  assert.match(source, /Agent 只能建议或建立内部任务/);
  assert.match(css, /@media \(max-width: 420px\)/);
  assert.match(css, /overflow-x: hidden/);
});

test("profit ledger links finance, OMS and Commerce OS without write routes", () => {
  for (const route of ["finance-control", "oms", "commerce-os"]) {
    assert.match(source, new RegExp(`href="/${route}"`));
  }
  assert.doesNotMatch(
    source,
    /\/commands|\/write-attempt|\/receipt|\/approval|\/permit/,
  );
});

test("Commerce OS, OMS and finance control drill into native profit ledger", () => {
  for (const upstream of [
    "../features/commerce-os/commerce-os-console.tsx",
    "../features/oms/oms-console.tsx",
    "../features/finance-control/finance-control-console.tsx",
  ]) {
    const content = readFileSync(new URL(upstream, import.meta.url), "utf8");
    assert.match(content, /href="\/profit-ledger"/);
  }
});
