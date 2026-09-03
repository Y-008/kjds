import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const briefing = read("../features/bi/briefing.tsx");
const styles = read("../features/bi/briefing.module.css");

test("BI briefing is a four-page manual, scoped and evidence-aware projection", () => {
  for (const title of ["当前结论与授权 Scope", "六项经营指标", "Top 3 异常与下一动作", "数据缺口、Evidence 与权威边界"]) {
    assert.match(briefing, new RegExp(title));
  }
  assert.match(briefing, /useBiProjection/);
  assert.match(briefing, /summaryMetricStatus/);
  assert.match(briefing, /requestAsOf/);
  assert.match(briefing, /source_gaps/);
  assert.match(briefing, /stage source ID 不自动当作 Evidence/);
  assert.match(briefing, /上一页/);
  assert.match(briefing, /下一页/);
  assert.match(briefing, /window\.print/);
  assert.doesNotMatch(briefing, /setInterval|setTimeout|Math\.random/);
  assert.doesNotMatch(briefing, /POST|PUT|PATCH|DELETE/);
});

test("BI briefing print contract renders every manually reviewable page", () => {
  assert.match(styles, /@media print/);
  assert.match(styles, /size: A4 landscape/);
  assert.match(styles, /\.briefingPage\[hidden\]/);
  assert.match(styles, /break-after: page/);
});

test("BI briefing route is reviewable", () => {
  assert.match(read("../app/bi/briefing/page.tsx"), /BiBriefing/);
});
