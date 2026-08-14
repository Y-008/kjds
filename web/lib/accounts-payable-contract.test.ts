import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL(
    "../features/accounts-payable/accounts-payable-console.tsx",
    import.meta.url,
  ),
  "utf8",
);
const page = readFileSync(
  new URL("../app/accounts-payable/page.tsx", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL(
    "../features/accounts-payable/accounts-payable.module.css",
    import.meta.url,
  ),
  "utf8",
);

test("accounts payable renders one deep-module projection without client finance logic", () => {
  assert.match(page, /<AccountsPayableConsole\s*\/>/);
  assert.match(source, /\/backend\/v1\/accounts-payable\/workspace\?/);
  assert.equal(
    (source.match(/\/backend\/v1\/accounts-payable\/workspace/g) ?? []).length,
    1,
  );
  assert.match(source, /页面不重算金额、余额、匹配或阶段/);
  assert.match(source, /client recalculation false/);
  assert.match(source, /服务端 opaque cursor/);
  assert.doesNotMatch(
    source,
    /reduce\s*\(|parseFloat|Number\s*\(|Math\.random|localStorage|document\.cookie/,
  );
});

test("accounts payable renders truth states and complete authority chain", () => {
  assert.match(source, /role="status"/);
  assert.match(source, /role="alert"/);
  assert.match(source, /重试/);
  assert.match(source, /真实 no_data/);
  assert.match(source, /最新权威记录失败关闭/);
  assert.match(source, /Invoice review/);
  assert.match(source, /Three-way match/);
  assert.match(source, /Approval \/ Permit \/ Readback/);
  assert.match(source, /BANK_PAYMENT/);
  assert.match(source, /Adapter disabled · payment false/);
  assert.match(source, /private ERP|私有 ERP/);
  assert.match(source, /external write false/);
  assert.match(css, /@media \(max-width: 420px\)/);
  assert.match(css, /overflow-x: hidden/);
});

test("accounts payable links adjacent native ERP workspaces", () => {
  for (const href of [
    "/commerce-os",
    "/procurement",
    "/finance-control",
    "/profit-ledger",
    "/inventory",
  ]) {
    assert.match(source, new RegExp(`href="${href}"`));
  }
});

test("Commerce OS, procurement and finance drill into accounts payable", () => {
  for (const path of [
    "../features/commerce-os/commerce-os-console.tsx",
    "../features/procurement/procurement-console.tsx",
    "../features/finance-control/finance-control-console.tsx",
  ]) {
    const upstream = readFileSync(new URL(path, import.meta.url), "utf8");
    assert.match(upstream, /href="\/accounts-payable"/);
  }
});
