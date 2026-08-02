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
  assert.match(popup, /chrome\.storage\.session/);
  assert.match(popup, /active_tab_visible_dom/);
  assert.match(popup, /unverified_external_reference/);
  assert.match(popup, /没有生成猜测价格/);
  assert.doesNotMatch(
    `${JSON.stringify(manifest)}${background}${popup}`,
    /<all_urls>|chrome\.cookies|localStorage|XMLHttpRequest|webRequest/,
  );
});
