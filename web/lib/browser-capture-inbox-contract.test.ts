import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("capture inbox keeps promotion decisions on the authenticated server", () => {
  const page = read("../app/capture-inbox/page.tsx");
  const consoleSource = read(
    "../features/browser-capture-inbox/browser-capture-inbox-console.tsx",
  );
  const css = read(
    "../features/browser-capture-inbox/browser-capture-inbox.module.css",
  );

  assert.match(page, /BrowserCaptureInboxConsole/);
  assert.match(consoleSource, /\/backend\/v1\/browser-capture-inbox\/preflight/);
  assert.match(consoleSource, /\/backend\/v1\/browser-capture-inbox\/submissions/);
  assert.match(consoleSource, /服务端预检/);
  assert.match(consoleSource, /独立点击，不自动晋级 Observation/);
  assert.match(consoleSource, /Supplier Offer \/ actual cost · false/);
  assert.match(consoleSource, /Approval \/ Permit · false \/ false/);
  assert.match(consoleSource, /external write · false/);
  assert.match(consoleSource, /entity_ref \?\? "null · authority missing"/);
  assert.match(consoleSource, /SKU \/ SPEC \/ PRICE MATRIX/);
  assert.match(consoleSource, /exact_variant_staged/);
  assert.match(consoleSource, /requires_detail_enrichment/);
  assert.match(consoleSource, /source_observation/);
  assert.match(consoleSource, /ERP: MOQ=/);
  assert.match(consoleSource, /mapping\.supply_signals\.stock_count/);
  assert.match(consoleSource, /mapping\.market_signals\.sku_sale_count_signal/);
  assert.match(consoleSource, /comparison_dimensions/);
  assert.match(consoleSource, /跨供应商同维度比价/);
  assert.match(consoleSource, /reference_quantity_below_moq/);
  assert.match(consoleSource, /搜索卡价格不进入最低价排行/);
  assert.doesNotMatch(
    consoleSource,
    /Math\.random|displayed_price\s*[-+*/]|\/commands|\/write-attempt|\/receipt/,
  );
  assert.match(css, /@media \(max-width: 430px\)/);
  assert.match(css, /max-width:/);
  assert.match(css, /overflow-wrap:/);
});

test("browser helper uses explicit active-tab capture and a bounded handshake", () => {
  const manifest = JSON.parse(
    read("../../extensions/kjds-browser-capture/manifest.json"),
  );
  const background = read("../../extensions/kjds-browser-capture/background.js");
  const popup = read("../../extensions/kjds-browser-capture/popup.js");
  const extractor = read("../../extensions/kjds-browser-capture/extract-page.js");

  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(
    [...manifest.permissions].sort(),
    ["activeTab", "scripting", "storage"].sort(),
  );
  assert.equal("host_permissions" in manifest, false);
  assert.equal("content_scripts" in manifest, false);
  assert.deepEqual(manifest.externally_connectable.matches, [
    "http://127.0.0.1:3000/*",
    "http://localhost:3000/*",
  ]);
  assert.match(background, /ALLOWED_KJDS_ORIGINS/);
  assert.match(background, /pending\.idempotency_key !== message\.idempotency_key/);
  assert.match(popup, /chrome\.tabs\.query\(\{ active: true, currentWindow: true \}\)/);
  assert.match(popup, /chrome\.scripting\.executeScript/);
  assert.match(popup, /files: \["extract-page\.js"\]/);
  assert.match(popup, /chrome\.storage\.session/);
  assert.match(extractor, /active_tab_visible_dom/);
  assert.match(extractor, /unverified_external_reference/);
  assert.match(extractor, /没有生成猜测价格|未退化为猜价/);
  assert.match(extractor, /skuMapOriginal/);
  assert.match(extractor, /offerLoginId/);
  assert.match(extractor, /product_detail_variant_matrix/);
  assert.match(extractor, /search_result_candidates/);
  assert.match(extractor, /candidate_requires_detail_enrichment/);
  assert.doesNotMatch(
    `${JSON.stringify(manifest)}${background}${popup}${extractor}`,
    /<all_urls>|chrome\.cookies|localStorage|XMLHttpRequest|webRequest|fetch\(/,
  );
});
