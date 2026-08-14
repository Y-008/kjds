import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const component = read("../features/profit-command/profit-command-console.tsx");
const contracts = read("../features/profit-command/contracts.ts");
const styles = read("../features/profit-command/profit-command.module.css");

test("profit command exposes six real pages over server-owned projections", () => {
  for (const [path, surface] of [
    ["profit-command", "overview"],
    ["profit-command/products", "products"],
    ["profit-command/routing", "routing"],
    ["profit-command/truth", "truth"],
    ["profit-command/remediation", "remediation"],
    ["profit-command/lineage", "lineage"],
  ]) {
    const page = read(`../app/${path}/page.tsx`);
    assert.match(page, new RegExp(`surface="${surface}"`));
    assert.match(page, /ProfitCommandConsole/);
  }
  const detail = read("../app/profit-command/products/[candidateId]/page.tsx");
  assert.match(detail, /surface="product-detail"/);
  assert.match(detail, /candidateId=/);
});

test("profit command consumes all read projections without client profit math", () => {
  for (const endpoint of [
    "/backend/v1/profit-command/workspace",
    "/backend/v1/profit-command/analytics",
    "/backend/v1/profit-command/candidates",
    "/backend/v1/profit-command/portfolio",
    "/backend/v1/profit-command/truth-readiness",
    "/backend/v1/profit-command/remediation",
    "/backend/v1/profit-command/lineage",
    "/backend/v1/seller-os/operating-plan",
    "/backend/v1/seller-os/store-profile-proposal",
    "/backend/v1/seller-os/store-routing",
    "/backend/v1/growth-channels/capabilities",
  ]) {
    assert.match(component, new RegExp(endpoint));
  }
  assert.match(component, /五套利润口径/);
  assert.match(component, /币种不一致且无汇率证据时/);
  assert.match(component, /proposal-only/);
  assert.match(component, /accepted \+ quarantined = source_total/i);
  assert.match(component, /按赚钱与止损价值排队/);
  assert.match(component, /queue_page_size=50/);
  assert.match(component, /服务端分页保留全部任务/);
  assert.match(contracts, /previous_offset: number \| null/);
  assert.match(contracts, /next_offset: number \| null/);
  assert.match(component, /店铺画像草案/);
  assert.match(component, /从曝光到现金 CM3/);
  assert.match(component, /从源证据到现金利润的真实状态/);
  assert.match(component, /多 SKU Posting 不按比例猜分/);
  assert.match(component, /UNBOUND LOGISTICS EVIDENCE/);
  assert.match(component, /不计入 SKU 成本覆盖/);
  assert.match(component, /不形成金额、reviewed\/actual、15-cost covered/);
  assert.match(component, /surface === "truth"/);
  assert.match(component, /truthReadiness\?\.status/);
  assert.match(component, /truthReadiness\?\.snapshot_sha256/);
  assert.match(contracts, /legacy_records_decision_eligible: false/);
  assert.match(contracts, /unbound_cost_evidence/);
  assert.match(contracts, /sku_cost_coverage_incremented: false/);
  assert.match(component, /synthetic=false/);
  assert.match(component, /window\.location\.search/);
  assert.match(component, /\.get\("query"\)/);
  assert.match(component, /!selectedStore \|\| !queryInitialized/);
  assert.doesNotMatch(component, /Math\.random/);
  assert.doesNotMatch(component, /amount\s*[-+*/]|downside_cm3\s*[-+*/]|expected_cm3\s*[-+*/]/);
  assert.doesNotMatch(component, /\/commands|\/write-attempt|\/receipt/);
});

test("profit and routing contracts preserve truth and authority boundaries", () => {
  assert.match(contracts, /scenario_profit: ProfitBasis/);
  assert.match(contracts, /accrual_profit: ProfitBasis/);
  assert.match(contracts, /settlement_profit: ProfitBasis/);
  assert.match(contracts, /cash_profit: ProfitBasis/);
  assert.match(contracts, /risk_adjusted_profit: ProfitBasis/);
  assert.match(contracts, /derived_tags_are_official_taxonomy: false/);
  assert.match(contracts, /external_write_allowed: false/);
  assert.match(contracts, /raw_data_deleted: false/);
  assert.match(contracts, /missing_values_guessed: false/);
  assert.match(contracts, /synthetic_points_created: false/);
});

test("profit command is explicitly bounded for desktop and mobile", () => {
  assert.match(styles, /@media \(max-width: 650px\)/);
  assert.match(styles, /minmax\(0, 1fr\)/);
  assert.match(styles, /overflow-x: auto/);
  assert.match(styles, /grid-column: 1 \/ -1/);
});
