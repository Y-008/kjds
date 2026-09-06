import assert from "node:assert/strict";
import test from "node:test";

import { parseOzonProductionAcceptance } from "../features/ozon-production-acceptance/contracts.ts";

const SHA = "a".repeat(64);

function accepted(overrides: Record<string, unknown> = {}) {
  return {
    contract_id: "kjds-ozon-production-acceptance-v1",
    contract_version: "1.0.0",
    status: "accepted",
    gate_status: "PASS",
    accepted: true,
    scope: {
      tenant_ref: "tenant-a",
      entity_ref: "entity-a",
      store_ref: "store-a",
      scope_grant_authority_sha256: SHA,
    },
    run: null,
    checks: { exact_scope: true, official_adapter_contract: true },
    blockers: [],
    evidence_ids: ["evidence-1"],
    source_contract: { platform: "ozon", operation: "ozon.product.read" },
    runtime_identity: {
      platform: "ozon",
      account_ref: "account-a",
      adapter: { adapter_id: "official", adapter_version: "v1", read_only: true },
      state: "ready",
      runtime_status: "fresh_passed",
      required_capability: "ozon.product.read",
      capabilities_match: true,
      provider_readback_fresh_passed: true,
      external_verifier_fresh_passed: true,
    },
    next_action: "replay",
    external_write_allowed: false,
    formal_fact_promotion_allowed: false,
    production_release_allowed: false,
    credential_values_returned: false,
    snapshot_sha256: SHA,
    ...overrides,
  };
}

test("acceptance contract admits a guarded PASS projection", () => {
  const value = parseOzonProductionAcceptance(accepted());
  assert.equal(value.gate_status, "PASS");
  assert.equal(value.external_write_allowed, false);
});

test("acceptance contract preserves a blocked evidence state", () => {
  const value = parseOzonProductionAcceptance(accepted({
    status: "blocked",
    gate_status: "BLOCKED_EVIDENCE",
    accepted: false,
    blockers: ["OZON_HTTP_403"],
  }));
  assert.equal(value.accepted, false);
  assert.deepEqual(value.blockers, ["OZON_HTTP_403"]);
});

test("acceptance contract rejects contradictory or unsafe projections", () => {
  assert.throws(() => parseOzonProductionAcceptance(accepted({ accepted: false })));
  assert.throws(() => parseOzonProductionAcceptance(accepted({ external_write_allowed: true })));
  assert.throws(() => parseOzonProductionAcceptance(accepted({ checks: { exact_scope: "true" } })));
  assert.throws(() => parseOzonProductionAcceptance(accepted({ snapshot_sha256: "unknown" })));
});
