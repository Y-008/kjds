import assert from "node:assert/strict";
import test from "node:test";

import {
  credentialsByActor,
  parseWebActorBindings,
} from "./identity-config.ts";
import {
  verifyAuthorityWorkflowTopology,
} from "./authority-workflow-topology.ts";

const credentials = credentialsByActor(
  JSON.stringify({
    "subject-key": {
      actor: "subject",
      roles: ["operator"],
      tenant: "tenant-a",
      stores: ["store-a"],
    },
    "owner-key": {
      actor: "owner",
      roles: ["reviewer"],
      tenant: "tenant-a",
      stores: ["store-a"],
    },
    "review-key": {
      actor: "reviewer",
      roles: ["risk"],
      tenant: "tenant-a",
      stores: ["store-a"],
    },
    "recorder-key": {
      actor: "recorder",
      roles: ["admin"],
      tenant: "tenant-a",
      stores: ["store-a"],
    },
  }),
);

function verify(
  authMode: "legacy" | "supabase",
  bindings = parseWebActorBindings("{}"),
) {
  return verifyAuthorityWorkflowTopology({
    authMode,
    credentials,
    bindings,
    currentActorId: "subject",
    currentRoles: ["operator"],
    tenantRef: "tenant-a",
    storeRef: "store-a",
    environment: "production",
    observedAt: new Date("2026-07-29T00:00:00Z"),
  });
}

test("four-party API topology does not make a legacy Web workflow ready", () => {
  const result = verify("legacy");
  assert.equal(result.state, "blocked");
  assert.equal(result.api_chain_ready, true);
  assert.equal(result.web_chain_ready, false);
  assert.deepEqual(result.selected_api_chain, {
    subject_actor_id: "subject",
    owner_actor_id: "owner",
    reviewer_actor_id: "reviewer",
    recorder_actor_id: "recorder",
  });
  assert.ok(result.blocker_codes.includes("web_auth_mode_not_supabase"));
  assert.equal(result.external_write_allowed, false);
  assert.equal(result.role_switch_allowed, false);
});

test("four distinct Supabase bindings make the observed Web topology ready", () => {
  const result = verify(
    "supabase",
    parseWebActorBindings(
      JSON.stringify({
        "user-subject": "subject",
        "user-owner": "owner",
        "user-reviewer": "reviewer",
        "user-recorder": "recorder",
      }),
    ),
  );
  assert.equal(result.state, "passed");
  assert.equal(result.web_chain_ready, true);
  assert.equal(
    new Set(Object.values(result.selected_web_chain!.user_refs_sha256)).size,
    4,
  );
  assert.doesNotMatch(JSON.stringify(result), /user-subject|subject-key/);
});

test("unknown Web binding and external-write drift fail closed", () => {
  const result = verifyAuthorityWorkflowTopology({
    authMode: "supabase",
    credentials,
    bindings: parseWebActorBindings('{"unknown-user":"unknown-actor"}'),
    currentActorId: "subject",
    currentRoles: ["operator"],
    tenantRef: "tenant-a",
    storeRef: "store-a",
    environment: "production",
    observedAt: new Date("2026-07-29T00:00:00Z"),
    externalWriteAllowed: true,
  });
  assert.equal(result.state, "failed");
  assert.ok(result.blocker_codes.includes("web_binding_actor_unknown"));
  assert.ok(result.blocker_codes.includes("external_write_enabled"));
});

test("identity configuration parse failures remain standard failed verifier results", () => {
  const result = verifyAuthorityWorkflowTopology({
    authMode: "legacy",
    credentials: new Map(),
    bindings: new Map(),
    currentActorId: "unresolved",
    currentRoles: [],
    tenantRef: "tenant-a",
    storeRef: "store-a",
    environment: "production",
    observedAt: new Date("2026-07-29T00:00:00Z"),
    configurationBlockers: ["ambiguous_actor_profile"],
  });
  assert.equal(result.state, "failed");
  assert.ok(result.blocker_codes.includes("ambiguous_actor_profile"));
  assert.equal(result.external_write_allowed, false);
});

test("hashes are stable across observation time and change with topology input", () => {
  const first = verify("legacy");
  const later = verifyAuthorityWorkflowTopology({
    authMode: "legacy",
    credentials,
    bindings: parseWebActorBindings("{}"),
    currentActorId: "subject",
    currentRoles: ["operator"],
    tenantRef: "tenant-a",
    storeRef: "store-a",
    environment: "production",
    observedAt: new Date("2026-07-29T01:00:00Z"),
  });
  const changed = verify("supabase");
  assert.equal(first.input_sha256, later.input_sha256);
  assert.equal(first.result_sha256, later.result_sha256);
  assert.notEqual(first.input_sha256, changed.input_sha256);
});
