import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

const source = fs.readFileSync(
  path.join(
    process.cwd(),
    "features/seller-erp-bridge/seller-erp-bridge-console.tsx",
  ),
  "utf8",
);

test("Seller ERP Bridge consumes one server Canonical Diff and exposes every state", () => {
  assert.match(source, /\/backend\/v1\/seller-erp-bridge\/reconcile/);
  assert.match(source, /matched/);
  assert.match(source, /source_only/);
  assert.match(source, /canonical_only/);
  assert.match(source, /conflict/);
  assert.match(source, /真实 no_data/);
  assert.match(source, /对账已失败关闭/);
});

test("Seller ERP Bridge preserves governance and no-write boundaries", () => {
  assert.match(source, /Private endpoint · false/);
  assert.match(source, /Cookie \/ Token · never stored/);
  assert.match(source, /formal_fact_promoted: false/);
  assert.match(source, /private_interface_used: false/);
  assert.match(source, /permit_issue_allowed: false/);
  assert.match(source, /external_write_allowed: false/);
  assert.match(source, /三方权威链/);
});

test("Seller ERP Bridge uses server filters, opaque cursor and retry", () => {
  assert.match(source, /source_evidence_id/);
  assert.match(source, /next_cursor/);
  assert.match(source, /服务端 opaque cursor/);
  assert.match(source, /重试/);
});
