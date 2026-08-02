import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL(
    "../features/procurement/procurement-console.tsx",
    import.meta.url,
  ),
  "utf8",
);
const page = readFileSync(
  new URL("../app/procurement/page.tsx", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL(
    "../features/procurement/procurement.module.css",
    import.meta.url,
  ),
  "utf8",
);

test("procurement renders one deep-module projection without client business logic", () => {
  assert.match(page, /<ProcurementConsole\s*\/>/);
  assert.match(source, /\/backend\/v1\/procurement\/workspace\?/);
  assert.equal(
    (source.match(/\/backend\/v1\/procurement\/workspace/g) ?? []).length,
    1,
  );
  assert.match(source, /页面不重算订单金额、数量守恒或阶段/);
  assert.match(source, /client recalculation/);
  assert.match(source, /服务端 opaque cursor/);
  assert.doesNotMatch(
    source,
    /reduce\s*\(|parseFloat|Number\s*\(|Math\.random|localStorage|document\.cookie/,
  );
});

test("procurement renders truth states, receiving timeline and immutable controls", () => {
  assert.match(source, /role="status"/);
  assert.match(source, /role="alert"/);
  assert.match(source, /重试/);
  assert.match(source, /真实 no_data/);
  assert.match(source, /最新权威记录失败关闭/);
  assert.match(source, /Evidence timeline/);
  assert.match(source, /数量不守恒会整单排除/);
  assert.match(source, /Approval \/ Permit/);
  assert.match(source, /AP \/ payment/);
  assert.match(source, /不能开票或付款/);
  assert.match(source, /external write/);
  assert.match(css, /@media \(max-width: 420px\)/);
  assert.match(css, /overflow-x: hidden/);
});

test("procurement links to adjacent native ERP workspaces", () => {
  for (const href of [
    "/commerce-os",
    "/sourcing-intelligence",
    "/pim",
    "/inventory",
    "/finance-control",
  ]) {
    assert.match(source, new RegExp(`href="${href}"`));
  }
});

test("Commerce OS, Sourcing, OMS and Inventory drill into procurement", () => {
  for (const path of [
    "../features/commerce-os/commerce-os-console.tsx",
    "../features/sourcing-intelligence/sourcing-intelligence-console.tsx",
    "../features/oms/oms-console.tsx",
    "../features/inventory/inventory-console.tsx",
  ]) {
    const upstream = readFileSync(new URL(path, import.meta.url), "utf8");
    assert.match(upstream, /href="\/procurement"/);
  }
});
