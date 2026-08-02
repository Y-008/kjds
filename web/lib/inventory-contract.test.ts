import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../features/inventory/inventory-console.tsx", import.meta.url),
  "utf8",
);
const page = readFileSync(
  new URL("../app/inventory/page.tsx", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL("../features/inventory/inventory.module.css", import.meta.url),
  "utf8",
);
const scopeAuthorityAlias = readFileSync(
  new URL("../app/scope-authority/page.tsx", import.meta.url),
  "utf8",
);

test("native inventory reads the authorized exact-scope server projection", () => {
  assert.match(page, /<InventoryConsole\s*\/>/);
  assert.match(source, /\/backend\/v1\/seller-os\/strategy-packs/);
  assert.match(source, /authorized_scope\.store_refs/);
  assert.match(
    source,
    /\/backend\/v1\/inventory\/workspace\?\$\{query\.toString\(\)\}/,
  );
  assert.match(source, /URLSearchParams/);
  assert.match(source, /legacy \/ market inferred · false \/ false/);
  assert.match(source, /client recalculation · false/);
  assert.match(source, /adjust \/ reserve \/ fulfill · false \/ false \/ false/);
  assert.match(source, /Approval \/ Permit · false \/ false/);
  assert.match(source, /external write · false/);
  assert.doesNotMatch(
    source,
    /\/v1\/inventory(?!\/workspace)|Math\.random|localStorage|document\.cookie/,
  );
  assert.match(scopeAuthorityAlias, /redirect\("\/authority-intake"\)/);
});

test("native inventory exposes measured states, immutable lineage, Agent limits, and mobile recovery", () => {
  assert.match(source, /"ready" \| "partial" \| "blocked" \| "no_data"/);
  assert.match(source, /旧库存未复用为 current/);
  assert.match(
    source,
    /Fact \{current\.fact_id\} · Evidence \{current\.evidence_id\}/,
  );
  assert.match(source, /decision_support_only/);
  assert.match(source, /Agent 能解释缺货，不能自己改库存或下采购单/);
  assert.match(source, /role="status"/);
  assert.match(source, /role="alert"/);
  assert.match(source, />\s*重试\s*</);
  assert.match(css, /@media \(max-width: 420px\)/);
  assert.match(css, /overflow-x: hidden/);
});
