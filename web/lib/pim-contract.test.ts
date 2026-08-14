import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../features/pim/pim-console.tsx", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/pim/page.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../features/pim/pim.module.css", import.meta.url), "utf8");

test("PIM consumes one exact-scope server projection without client recomputation", () => {
  assert.match(page, /<PimConsole\s*\/>/);
  assert.match(source, /\/backend\/v1\/pim\/workspace\?/);
  assert.match(source, /URLSearchParams/);
  assert.match(source, /next_cursor/);
  assert.match(source, />下一页</);
  assert.match(source, /href="\/listings"/);
  assert.match(source, /Listing 生命周期 →/);
  assert.match(source, /href="\/media-factory"/);
  assert.match(source, /进入内容媒体工厂 →/);
  assert.match(source, /客户端不重算 readiness/);
  assert.doesNotMatch(source, /Math\.random|localStorage|document\.cookie/);
});

test("PIM renders list detail no-data error retry and governed Agent limits at mobile width", () => {
  assert.match(source, /<details/);
  assert.match(source, /真实 no_data/);
  assert.match(source, /权威链已阻断/);
  assert.match(source, /source_gaps/);
  assert.match(source, /data-state=\{data\.status\}/);
  assert.match(source, /role="status"/);
  assert.match(source, /role="alert"/);
  assert.match(source, />重试</);
  assert.match(source, /不能自批、发 Permit 或外部写/);
  assert.match(css, /@media\(max-width:420px\)/);
  assert.match(css, /overflow-x:hidden/);
});
