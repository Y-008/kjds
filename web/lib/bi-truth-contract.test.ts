import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../features/bi/truth.ts", import.meta.url),
  "utf8",
);

test("BI truth adapter separates authority gaps from numeric zero", () => {
  for (const gap of [
    "scoped_catalog_authority_missing",
    "scoped_readiness_authority_missing",
    "scoped_growth_authority_missing",
    "scoped_rfq_authority_missing",
    "scoped_execution_authority_missing",
    "scoped_finance_authority_missing",
  ]) {
    assert.match(source, new RegExp(gap));
  }
  assert.match(source, /status === "ready"/);
  assert.match(source, /return snapshot\?\.summary\[key\] \?\? "no_data"/);
  assert.doesNotMatch(source, /Math\.random|ready_for_review.*\?\s*0/);
});

test("BI truth adapter preserves explicit projection states", () => {
  for (const state of ["ready", "partial", "no_data", "blocked", "forbidden", "conflicted"]) {
    assert.match(source, new RegExp(state));
  }
});
