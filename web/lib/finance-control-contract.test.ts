import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL(
    "../features/finance-control/finance-control-console.tsx",
    import.meta.url,
  ),
  "utf8",
);
const page = readFileSync(
  new URL("../app/finance-control/page.tsx", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL(
    "../features/finance-control/finance-control.module.css",
    import.meta.url,
  ),
  "utf8",
);

test("finance control consumes one exact-scope server projection without client finance logic", () => {
  assert.match(page, /<FinanceControlConsole\s*\/>/);
  assert.match(source, /\/backend\/v1\/finance-control\/workspace\?/);
  assert.equal(
    (source.match(/\/backend\/v1\/finance-control\/workspace/g) ?? []).length,
    1,
  );
  assert.match(source, /页面不重算金额、差异、/);
  assert.match(source, /client recalculation · false/);
  assert.match(source, /proportional allocation · false/);
  assert.match(source, /服务端 opaque cursor/);
  assert.doesNotMatch(
    source,
    /reduce\s*\(|parseFloat|Number\s*\(|Math\.random|localStorage|document\.cookie/,
  );
});

test("finance control renders all truth states, three books and immutable control boundary", () => {
  assert.match(source, /role="status"/);
  assert.match(source, /role="alert"/);
  assert.match(source, />重试</);
  assert.match(source, /真实 no_data/);
  assert.match(source, /最新权威记录失败关闭/);
  assert.match(source, /三本账尚未闭合/);
  assert.match(source, /BOOK 01 · ORDER \/ ACCRUAL/);
  assert.match(source, /BOOK 02 · PLATFORM SETTLEMENT/);
  assert.match(source, /BOOK 03 · BANK CASH/);
  assert.match(source, /ACTUAL CASH CM3/);
  assert.match(source, /Approval \/ Permit · false \/ false/);
  assert.match(source, /external write · false/);
  assert.match(source, /不能记账或动钱/);
  assert.match(css, /@media \(max-width: 420px\)/);
  assert.match(css, /overflow-x: hidden/);
});

test("Commerce OS, OMS and Inventory drill into finance control", () => {
  const commerce = readFileSync(
    new URL("../features/commerce-os/commerce-os-console.tsx", import.meta.url),
    "utf8",
  );
  const oms = readFileSync(
    new URL("../features/oms/oms-console.tsx", import.meta.url),
    "utf8",
  );
  const inventory = readFileSync(
    new URL("../features/inventory/inventory-console.tsx", import.meta.url),
    "utf8",
  );

  for (const upstream of [commerce, oms, inventory]) {
    assert.match(upstream, /href="\/finance-control"/);
  }
});
