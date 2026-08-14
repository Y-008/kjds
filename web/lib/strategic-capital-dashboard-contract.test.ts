import assert from "node:assert/strict";
import test from "node:test";

import {
  DASHBOARD_SECTION_ORDER,
  isStrategicCapitalDashboardProjection,
} from "../features/strategic-capital-dashboard/contract.ts";

const sha = "a".repeat(64);

function projection() {
  return {
    contract_id: "kjds-strategic-capital-dashboard-v1",
    contract_version: "1.0.0",
    registry_content_sha256: sha,
    dashboard_ref: "dash_fixture",
    scope_binding_sha256: sha,
    store_ref: "store-authorized",
    data_as_of: "2026-08-05T00:00:00Z",
    authority_checked_at: "2026-08-05T00:00:00Z",
    overall_state: "no_data",
    reason_codes: ["production_projection_not_connected"],
    sections: DASHBOARD_SECTION_ORDER.map((section_id, display_order) => ({
      section_id,
      display_order,
      scope_binding_sha256: sha,
      source_contract_id: `contract-${section_id}`,
      source_contract_version: "1.0.0",
      source_contract_sha256: sha,
      status: "not_connected",
      reason_codes: ["production_projection_not_connected"],
      projection_ref: null,
      projection_sha256: null,
      data_as_of: null,
      recorded_at: null,
      effective_at: null,
      review_due_at: null,
      citations: [],
      display_items: [],
      invalidation_conditions: [],
      global_top1_claim: false,
      production_admission: false,
      actionable_proposal: false,
    })),
    global_top1_claim: false,
    production_admission: false,
    budget_authority: false,
    side_effects: {
      evidence_writes: 0,
      fact_writes: 0,
      finance_entry_writes: 0,
      graph_writes: 0,
      approval_writes: 0,
      permit_writes: 0,
      pilot_writes: 0,
      outbox_writes: 0,
      external_writes: 0,
      network_writes: 0,
    },
    observation_sha256: sha,
  };
}

test("strict dashboard projection accepts only the exact read-only matrix", () => {
  assert.equal(
    isStrategicCapitalDashboardProjection(projection(), "store-authorized"),
    true,
  );
});

test("authority, section, side-effect and store drift all fail closed", () => {
  const mutations: Array<(value: any) => void> = [
    (value) => { value.global_top1_claim = true; },
    (value) => { value.production_admission = true; },
    (value) => { value.budget_authority = true; },
    (value) => { value.side_effects.outbox_writes = 1; },
    (value) => { value.sections[0].actionable_proposal = true; },
    (value) => { value.sections[0].scope_binding_sha256 = "b".repeat(64); },
    (value) => { value.sections[1] = value.sections[0]; },
    (value) => {
      value.sections[0].status = "invalidated";
      value.sections[0].projection_ref = "projection-one";
      value.sections[0].projection_sha256 = sha;
      value.sections[0].data_as_of = "2026-08-05T00:00:00Z";
      value.sections[0].recorded_at = "2026-08-05T00:00:00Z";
      value.sections[0].effective_at = "2026-08-05T00:00:00Z";
      value.sections[0].review_due_at = "2026-08-06T00:00:00Z";
      value.sections[0].display_items = [
        { item_ref: "leak", label: "leak", display_text: "leak" },
      ];
    },
    (value) => {
      value.sections[0].status = "ready";
      value.sections[0].projection_ref = "projection-one";
      value.sections[0].projection_sha256 = sha;
      value.sections[0].data_as_of = "2026-08-05T00:00:00Z";
      value.sections[0].recorded_at = "2026-08-05T00:00:00Z";
      value.sections[0].effective_at = "2026-08-05T00:00:00Z";
      value.sections[0].review_due_at = "2026-08-06T00:00:00Z";
      value.sections[0].display_items = [
        { item_ref: "one", label: "one", display_text: "one" },
      ];
      value.sections[0].invalidation_conditions = ["source_changed"];
      value.sections[0].citations = [];
    },
    (value) => {
      value.sections[0].status = "ready";
      value.sections[0].projection_ref = "projection-one";
      value.sections[0].projection_sha256 = sha;
      value.sections[0].data_as_of = "2026-08-05T00:00:00Z";
      value.sections[0].recorded_at = "2026-08-05T00:00:00Z";
      value.sections[0].effective_at = "2026-08-05T00:00:00Z";
      value.sections[0].review_due_at = "2026-08-06T00:00:00Z";
      value.sections[0].display_items = [
        { item_ref: "one", label: "one", display_text: "one" },
      ];
      value.sections[0].invalidation_conditions = ["source_changed"];
      value.sections[0].citations = [
        { token: "evd_raw-uuid", summary_sha256: sha },
      ];
    },
    (value) => { value.sections[0].reason_codes = []; },
  ];
  for (const mutate of mutations) {
    const value = projection();
    mutate(value);
    assert.equal(
      isStrategicCapitalDashboardProjection(value, "store-authorized"),
      false,
    );
  }
  assert.equal(
    isStrategicCapitalDashboardProjection(projection(), "other-store"),
    false,
  );
});
