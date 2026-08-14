import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../features/formal-facts/formal-facts-console.tsx", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL("../features/formal-facts/formal-facts.module.css", import.meta.url),
  "utf8",
);

test("formal Facts workspace uses the authenticated scoped API and never falls back to legacy", () => {
  assert.match(source, /\/backend\/v1\/facts\?store_ref=ozon-primary/);
  assert.match(source, /legacy inferred · false/);
  assert.match(source, /Claim source · false/);
  assert.match(source, /accounting posted · false/);
  assert.match(source, /Approval \/ Permit · false \/ false/);
  assert.match(source, /external write · false/);
  assert.doesNotMatch(source, /runtime\.facts|\/v1\/legacy/);
});

test("formal Facts workspace distinguishes blocked, no_data, ready, and 390px layout", () => {
  assert.match(source, /"loading" \| "ready" \| "blocked" \| "error"/);
  assert.match(source, /No native Facts/);
  assert.match(source, /BLOCKED BY AUTHORITY/);
  assert.match(css, /@media \(max-width: 420px\)/);
  assert.match(css, /overflow-x: hidden/);
});
