const assert = require("node:assert/strict");
const { existsSync } = require("node:fs");
const { readFile, rm } = require("node:fs/promises");
const path = require("node:path");
const test = require("node:test");

const PACKAGE_ROOT = path.resolve(__dirname, "../..");
const OUTPUT = path.join(PACKAGE_ROOT, ".runtime", "delivery-test");

test("delivery output is bounded and currency/synthetic evidence is complete", async () => {
  const delivery = await import("../../scripts/verify-delivery.mjs");
  assert.throws(() => delivery.assertDeliveryOutputDirectory(PACKAGE_ROOT), /delivery_output_boundary_invalid/u);
  assert.throws(() => delivery.assertDeliveryOutputDirectory(path.resolve(PACKAGE_ROOT, "..", "escape")), /delivery_output_boundary_invalid/u);
  assert.throws(() => delivery.assertEphemeralProfileRoot(PACKAGE_ROOT), /delivery_profile_boundary_invalid/u);
  const scenario = JSON.parse(await readFile(path.join(PACKAGE_ROOT, "src/scenarios/enterprise-overview.zh-CN.v2.json"), "utf8"));
  const boundary = delivery.verifyCurrencyAndSyntheticBoundary(scenario);
  assert.ok(boundary.monetary_fields_with_currency > 0);
  assert.deepEqual(boundary.currencies, ["RUB"]);
  assert.equal(boundary.non_demo_identifiers, 0);
});

test("two gateways remain exact-isolated and reset restores the scenario hash", async () => {
  const delivery = await import("../../scripts/verify-delivery.mjs");
  const result = await delivery.verifySessionIsolation("contract");
  assert.deepEqual({
    sessions: result.sessions,
    foreign_and_missing_same_404: result.foreign_and_missing_same_404,
    reset_scoped_to_owner: result.reset_scoped_to_owner,
    peer_state_unchanged: result.peer_state_unchanged,
    external_write_count: result.external_write_count,
  }, {
    sessions: 2,
    foreign_and_missing_same_404: true,
    reset_scoped_to_owner: true,
    peer_state_unchanged: true,
    external_write_count: 0,
  });
  assert.match(result.scenario_sha256_restored, /^[0-9a-f]{64}$/u);
  assert.match(result.state_sha256_restored, /^[0-9a-f]{64}$/u);
});

test("two clean delivery rounds produce identical deterministic package evidence", { timeout: 90_000 }, async () => {
  const delivery = await import("../../scripts/verify-delivery.mjs");
  await rm(OUTPUT, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  try {
    const result = await delivery.verifyDelivery(OUTPUT);
    assert.equal(result.deterministic.rounds_equal, true);
    assert.match(result.deterministic.portable_zip_sha256, /^[0-9a-f]{64}$/u);
    assert.match(result.deterministic.delivery_zip_sha256, /^[0-9a-f]{64}$/u);
    assert.match(result.deterministic.evidence_sha256, /^[0-9a-f]{64}$/u);
    assert.equal(result.external_write_count, 0);
    assert.deepEqual(result.cleanup, {
      runs: 2,
      idempotent_each_round: true,
      port_43190_residual: 0,
      port_43195_residual: 0,
      owned_child_process_residual: 0,
      ephemeral_profile_residual: 0,
    });
    for (const artifact of [result.delivery_zip, result.delivery_manifest, result.evidence, ...result.screenshots]) {
      assert.equal(existsSync(artifact), true, artifact);
    }
    console.log(JSON.stringify({
      portable_zip_sha256: result.deterministic.portable_zip_sha256,
      delivery_zip_sha256: result.deterministic.delivery_zip_sha256,
      deterministic_evidence_sha256: result.deterministic.evidence_sha256,
      rounds_equal: result.deterministic.rounds_equal,
      external_write_count: result.external_write_count,
      cleanup: result.cleanup,
    }));
  } finally {
    await rm(OUTPUT, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
});
