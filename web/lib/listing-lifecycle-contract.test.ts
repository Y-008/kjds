import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(
  new URL("../features/listing-lifecycle/listing-lifecycle-console.tsx", import.meta.url),
  "utf8",
);
const page = readFileSync(new URL("../app/listings/page.tsx", import.meta.url), "utf8");
const css = readFileSync(
  new URL("../features/listing-lifecycle/listing-lifecycle.module.css", import.meta.url),
  "utf8",
);

test("Listing lifecycle consumes one exact-scope projection and server-owned diff", () => {
  assert.match(page, /<ListingLifecycleConsole\s*\/>/);
  assert.match(source, /\/backend\/v1\/listing-lifecycle\/workspace\?/);
  assert.match(source, /URLSearchParams/);
  assert.match(source, /field_diffs/);
  assert.match(source, /source_missing/);
  assert.match(source, /desired_missing/);
  assert.match(source, /服务端 opaque cursor/);
  assert.match(source, /页面只呈现，不重算阶段或差异/);
  assert.doesNotMatch(
    source,
    /Math\.random|localStorage|document\.cookie|\/commands|\/write-attempt|\/receipt/,
  );
});

test("Listing lifecycle renders governed state, failure modes, detail and 390px safety", () => {
  assert.match(source, /OBSERVED ≠ DESIRED ≠ APPROVED ≠ READBACK/);
  assert.match(source, /Draft create · false/);
  assert.match(source, /Permit \/ Publish · false \/ false/);
  assert.match(source, /External write · false/);
  assert.match(source, /真实 no_data/);
  assert.match(source, /Listing 权威链已失败关闭/);
  assert.match(source, /data-state=\{data\.status\}/);
  assert.match(source, /role="status"/);
  assert.match(source, /role="alert"/);
  assert.match(source, />重试</);
  assert.match(source, /<details/);
  assert.match(source, /Review/);
  assert.match(source, /Listing Approval/);
  assert.match(source, /Execution Plan/);
  assert.match(source, /Readback/);
  assert.match(source, /不能创建 Draft\/Approval/);
  assert.match(source, /不能自批/);
  assert.match(source, /不能发 Permit/);
  assert.match(source, /href="\/media-factory"/);
  assert.match(source, /进入内容媒体工厂 →/);
  assert.match(css, /@media \(max-width: 420px\)/);
  assert.match(css, /overflow-x: hidden/);
});
