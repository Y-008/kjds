import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(
  new URL("../app/frontend-toolkit/page.tsx", import.meta.url),
  "utf8",
);
const source = readFileSync(
  new URL(
    "../features/frontend-toolkit/frontend-toolkit-page.tsx",
    import.meta.url,
  ),
  "utf8",
);
const css = readFileSync(
  new URL(
    "../features/frontend-toolkit/frontend-toolkit.module.css",
    import.meta.url,
  ),
  "utf8",
);

test("frontend toolkit remains an internal not-for-sale research route", () => {
  assert.match(page, /internal_preview \/ not_for_sale/);
  assert.match(source, /内部设计研究 \/ internal_preview \/ not_for_sale/);
  assert.match(source, /结构示意，非实测数据/);
  assert.match(source, /不代表真实转化结果/);
  assert.doesNotMatch(source, /立即购买|现在下单|联系客服|保证盈利|稳赚/);

  const hardCodedAnchorHrefs = [
    ...source.matchAll(/<a[^>]*href="([^"]+)"/g),
  ].map((match) => match[1]);
  assert.ok(hardCodedAnchorHrefs.length > 0);
  assert.ok(hardCodedAnchorHrefs.every((href) => href.startsWith("#")));
});

test("frontend toolkit exposes accessible tier state and motion controls", () => {
  assert.match(source, /aria-pressed=\{isActive\}/);
  assert.match(source, /aria-label=\{`内部预览：\$\{tier\.title\}`\}/);
  assert.match(source, /<MotionConfig reducedMotion="user">/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
});
