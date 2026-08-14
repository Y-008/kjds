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
  assert.match(source, /source_lineage/);
  assert.match(source, /竞标与货源映射/);
  assert.match(source, /未同步第三方 ERP/);
  assert.match(source, /href=\{`\/profit-command\?query=/);
  assert.match(source, /进入该 SKU 十五项成本与利润补证/);
  assert.match(source, /href=\{`\/sourcing-intelligence\?query=/);
  assert.match(source, /查看三家 RFQ、回复与报价状态/);
  assert.match(css, /@media\s*\(max-width:\s*420px\)/);
  assert.match(css, /overflow-x:\s*hidden/);
});
