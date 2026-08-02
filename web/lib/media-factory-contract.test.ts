import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../features/media-factory/media-factory-console.tsx", import.meta.url),
  "utf8",
);
const page = readFileSync(
  new URL("../app/media-factory/page.tsx", import.meta.url),
  "utf8",
);
const css = readFileSync(
  new URL("../features/media-factory/media-factory.module.css", import.meta.url),
  "utf8",
);

test("media factory consumes one exact-scope server projection without client recomputation", () => {
  assert.match(page, /<MediaFactoryConsole\s*\/>/);
  assert.match(source, /\/backend\/v1\/media-factory\/workspace\?/);
  assert.match(source, /URLSearchParams/);
  assert.match(source, /product_groups/);
  assert.match(source, /execution_timeline/);
  assert.match(source, /delivery_manifest/);
  assert.match(source, /missing_roles/);
  assert.match(source, /missing_ratios/);
  assert.match(source, /服务端 opaque cursor/);
  assert.match(source, /页面不重算阶段、成本、资格或覆盖/);
  assert.doesNotMatch(
    source,
    /Math\.random|localStorage|document\.cookie|\/commands|\/write-attempt|\/receipt/,
  );
});

test("media factory renders governed lifecycle and every failure mode at 390px", () => {
  assert.match(source, /Asset \/ Job create · false \/ false/);
  assert.match(source, /Manifest create · false/);
  assert.match(source, /External provider \/ platform write · false \/ false/);
  assert.match(source, /真实 no_data/);
  assert.match(source, /媒体权威链已失败关闭/);
  assert.match(source, /data-state=\{data\.status\}/);
  assert.match(source, /role="status"/);
  assert.match(source, /role="alert"/);
  assert.match(source, />重试</);
  assert.match(source, /<details/);
  assert.match(source, /Source rights/);
  assert.match(source, /Listing media ready/);
  assert.match(source, /不能创建 Asset\/Job/);
  assert.match(source, /不能决定 QA/);
  assert.match(source, /不能创建 Manifest/);
  assert.match(source, /不能自批/);
  assert.match(source, /不能发 Permit/);
  assert.match(css, /@media \(max-width: 420px\)/);
  assert.match(css, /overflow-x: hidden/);
});

test("PIM Listing and Commerce OS drill into the same native media factory", () => {
  const pim = readFileSync(
    new URL("../features/pim/pim-console.tsx", import.meta.url),
    "utf8",
  );
  const listings = readFileSync(
    new URL(
      "../features/listing-lifecycle/listing-lifecycle-console.tsx",
      import.meta.url,
    ),
    "utf8",
  );
  const commerce = readFileSync(
    new URL("../features/commerce-os/commerce-os-console.tsx", import.meta.url),
    "utf8",
  );

  for (const upstream of [pim, listings, commerce]) {
    assert.match(upstream, /href="\/media-factory"/);
  }
  assert.match(commerce, /打开内容媒体工厂/);
});
