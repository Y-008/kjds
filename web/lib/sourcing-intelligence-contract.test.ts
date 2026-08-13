import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const source = fs.readFileSync(
  path.join(process.cwd(), "features/sourcing-intelligence/sourcing-intelligence-console.tsx"),
  "utf8",
);

test("sourcing intelligence consumes one server projection and preserves authority levels", () => {
  assert.match(source, /\/backend\/v1\/sourcing-intelligence\/workspace/);
  assert.match(source, /真实 no_data/);
  assert.match(source, /供应权威链已阻断/);
  assert.match(source, /Actual Cash CM3 · no_data/);
  assert.match(source, /supplier_contacted: false/);
  assert.match(source, /rfq_dispatched: false/);
  assert.match(source, /purchase_order_created: false/);
  assert.match(source, /permit_issue_allowed: false/);
  assert.match(source, /external_write_allowed: false/);
  assert.match(source, /window\.location\.search/);
  assert.match(source, /\.get\("query"\)/);
});

test("sourcing intelligence uses opaque server pagination and retry", () => {
  assert.match(source, /next_cursor/);
  assert.match(source, /服务端 opaque cursor/);
  assert.match(source, /下一页/);
  assert.match(source, /重试/);
});
