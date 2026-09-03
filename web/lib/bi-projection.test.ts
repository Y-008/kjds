import assert from "node:assert/strict";
import test from "node:test";

import {
  buildBiScopeSearch,
  parseBiScopeSearch,
  validateScopedAnalyticsSnapshot,
  validateScopedWorkbenchBriefing,
  loadBiProjectionRound,
  type BiJsonRequest,
} from "../features/bi/contract.ts";
import { summaryMetricStatus } from "../features/bi/truth.ts";

const CUTOFF = "2026-08-19T04:30:00.000Z";
const SHA = "a".repeat(64);

const session = {
  authenticated: true,
  auth_mode: "legacy",
  email: null,
  actor_id: "operator-a",
  roles: ["operator"],
  tenant_ref: "tenant-a",
  store_refs: ["store-a", "store-b"],
  default_store_ref: "store-a",
};

function analytics(overrides: Record<string, unknown> = {}) {
  return {
    contract_id: "kjds-operating-flow-analytics-v1",
    store_ref: "store-a",
    scope: {
      tenant_ref: "tenant-a",
      entity_ref: "entity-a",
      store_ref: "store-a",
      scope_authority_sha256: SHA,
      status: "ready",
    },
    status: "partial",
    source_as_of: CUTOFF,
    snapshot_sha256: SHA,
    summary: {
      catalog_items: 1,
      bound_listings: 1,
      available_stock: 0,
      external_image_references: 0,
      external_video_references: 0,
      gate_blockers: 0,
      growth_snapshot_skus: 0,
      rfq_packages: 0,
      verified_dispatch_proofs: 0,
      formal_finance_entries: 0,
      ready_execution_plans: 0,
    },
    recommended_playbook: {
      id: "scoped_catalog_refinement",
      label: "作用域目录核验",
      reasons: ["scoped"],
      advisory_only: true,
      automatic_mode_switch: false,
    },
    focal_listing: null,
    stages: [],
    coverage: [],
    pipeline: [],
    priority_items: [],
    data_gaps: ["scoped_growth_authority_missing"],
    source_gaps: ["scoped_growth_authority_missing"],
    excluded_sources: ["legacy_global_growth"],
    guardrails: {
      advisory_only: true,
      browser_gate_recalculation: false,
      synthetic_business_data_allowed: false,
      automatic_product_selection: false,
      automatic_supplier_contact: false,
      automatic_procurement: false,
      automatic_pricing: false,
      automatic_listing: false,
      automatic_ad_spend: false,
      platform_write_allowed: false,
    },
    ...overrides,
  };
}

function briefing(overrides: Record<string, unknown> = {}) {
  return {
    contract_id: "kjds-operating-workbench-briefing-v1",
    mode: "scoped_shadow_advisory",
    status: "no_data",
    scope: {
      tenant_ref: "tenant-a",
      entity_ref: "entity-a",
      store_ref: "store-a",
      scope_authority_sha256: SHA,
    },
    as_of: CUTOFF,
    snapshot_sha256: SHA,
    summary: {
      gate_blockers: 0,
      runtime_items: 0,
      recommendations: 0,
      visible_items: 0,
      candidate_count: 0,
      selection_ready_count: 0,
    },
    agents: [],
    work_items: [],
    candidate_portfolio: {
      status: "no_data",
      candidate_count: 0,
      selection_ready_count: 0,
      rows: [],
      source_gap: "scoped_readiness_authority_missing",
      advisory_only: true,
    },
    source_gaps: ["scoped_readiness_authority_missing"],
    excluded_sources: ["legacy_global_gate_readiness"],
    guardrails: {
      advisory_only: true,
      automatic_execution: false,
      automatic_product_selection: false,
      automatic_procurement: false,
      automatic_pricing: false,
      automatic_listing: false,
      platform_write_allowed: false,
      third_party_fact_promotion_allowed: false,
    },
    ...overrides,
  };
}

function response(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

test("BI scope parser allowlists, de-duplicates and validates timezone-aware as_of", () => {
  assert.deepEqual(
    parseBiScopeSearch("?store_ref=store-a&as_of=2026-08-19T12%3A30%3A00%2B08%3A00"),
    {
      ok: true,
      value: { storeRef: "store-a", asOf: "2026-08-19T12:30:00+08:00" },
    },
  );
  assert.match(
    (parseBiScopeSearch("?store_ref=a&store_ref=b") as { reason: string }).reason,
    /不可重复/,
  );
  assert.match(
    (parseBiScopeSearch("?as_of=2026-08-19T12:30:00") as { reason: string }).reason,
    /包含时区/,
  );
  assert.match(
    (parseBiScopeSearch("?debug=true") as { reason: string }).reason,
    /不支持/,
  );
  assert.equal(
    parseBiScopeSearch("?store_ref=store-a&scene=flow", ["scene"]).ok,
    true,
  );
  assert.equal(
    buildBiScopeSearch("?scene=flow&debug=true", { storeRef: "store-b", asOf: null }, ["scene"]),
    "?store_ref=store-b&scene=flow",
  );
});

test("protected BI validators reject legacy, scope drift and write guardrail drift", () => {
  const expected = { tenantRef: "tenant-a", storeRef: "store-a", asOf: CUTOFF };
  assert.equal(validateScopedAnalyticsSnapshot(analytics(), expected).ok, true);
  assert.equal(validateScopedWorkbenchBriefing(briefing(), expected).ok, true);

  assert.match(
    (validateScopedAnalyticsSnapshot(
      analytics({ status: "ready_for_review", scope: undefined }),
      expected,
    ) as { reason: string }).reason,
    /scoped/,
  );
  assert.match(
    (validateScopedAnalyticsSnapshot(
      analytics({ scope: { ...analytics().scope as object, tenant_ref: "tenant-other" } }),
      expected,
    ) as { reason: string }).reason,
    /tenant_ref/,
  );
  assert.match(
    (validateScopedWorkbenchBriefing(
      briefing({
        guardrails: {
          ...(briefing().guardrails as object),
          platform_write_allowed: true,
        },
      }),
      expected,
    ) as { reason: string }).reason,
    /platform_write_allowed/,
  );
});

test("projection round reads session first and pins one cutoff across both projections", async () => {
  const calls: string[] = [];
  const request: BiJsonRequest = async (input) => {
    const url = String(input);
    calls.push(url);
    if (url === "/auth/session") return response(200, session);
    if (url.startsWith("/backend/v1/operating-analytics/snapshot?")) return response(200, analytics());
    if (url.startsWith("/backend/v1/operating-workbench/briefing?")) return response(200, briefing());
    return response(404, {});
  };

  const result = await loadBiProjectionRound({
    search: "?store_ref=store-a",
    request,
    now: () => new Date(CUTOFF),
  });

  assert.equal(calls[0], "/auth/session");
  assert.equal(calls.length, 3);
  const queryStrings = calls.slice(1).map((url) => new URL(url, "https://kjds.test").search);
  assert.equal(queryStrings[0], queryStrings[1]);
  assert.equal(new URL(calls[1], "https://kjds.test").searchParams.get("as_of"), CUTOFF);
  assert.equal(result.scope.requestAsOf, CUTOFF);
  assert.equal(result.analytics.data?.store_ref, "store-a");
  assert.equal(result.status, "partial");
});

test("unauthorized URL scope is forbidden before any business request", async () => {
  const calls: string[] = [];
  const request: BiJsonRequest = async (input) => {
    calls.push(String(input));
    return response(200, session);
  };
  const result = await loadBiProjectionRound({
    search: "?store_ref=store-secret",
    request,
    now: () => new Date(CUTOFF),
  });
  assert.deepEqual(calls, ["/auth/session"]);
  assert.equal(result.status, "forbidden");
  assert.equal(result.analytics.data, null);
  assert.match(result.error, /未发送任何经营数据请求/);
});

test("auth redirect and response scope conflicts are explicit", async () => {
  const unauthorized = await loadBiProjectionRound({
    search: "",
    request: async () => response(401, {}),
  });
  assert.equal(unauthorized.redirectTo, "/login");

  const request: BiJsonRequest = async (input) => {
    const url = String(input);
    if (url === "/auth/session") return response(200, session);
    if (url.includes("operating-analytics")) {
      return response(200, analytics({
        scope: { ...analytics().scope as object, store_ref: "store-b" },
      }));
    }
    return response(200, briefing());
  };
  const conflicted = await loadBiProjectionRound({
    search: "?store_ref=store-a&as_of=2026-08-19T04%3A30%3A00.000Z",
    request,
  });
  assert.equal(conflicted.status, "conflicted");
  assert.equal(conflicted.analytics.data, null);
  assert.equal(conflicted.workbench.data, null);
});

test("metric truth never promotes a placeholder zero when its authority is missing", () => {
  const snapshot = analytics() as never;
  assert.equal(summaryMetricStatus(snapshot, "growth_snapshot_skus", "partial"), "no_data");
  assert.equal(summaryMetricStatus(snapshot, "catalog_items", "partial"), "ready");
});
