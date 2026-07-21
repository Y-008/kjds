import assert from "node:assert/strict";
import test from "node:test";

import {
  approverMfaRequired,
  credentialsByActor,
  mutationOriginIsAllowed,
  parseWebActorBindings,
  validateWebApprovalTopology,
  webAuthMode,
} from "./identity-config.ts";

test("legacy mode is limited to non-production environments", () => {
  assert.equal(webAuthMode({}), "legacy");
  assert.throws(
    () => webAuthMode({ KJDS_ENVIRONMENT: "production", KJDS_WEB_AUTH_MODE: "legacy" }),
    /Production Web requires/,
  );
  assert.equal(webAuthMode({ KJDS_ENVIRONMENT: "production", KJDS_WEB_AUTH_MODE: "supabase" }), "supabase");
});

test("identity bindings contain actor names but never duplicate API key material", () => {
  const bindings = parseWebActorBindings(
    JSON.stringify({
      "operator-user": { actor: "operator-actor" },
      "approver-user": "approver-actor",
    }),
  );
  assert.equal(bindings.get("operator-user")?.actorId, "operator-actor");
  assert.equal(bindings.get("approver-user")?.actorId, "approver-actor");
  assert.throws(() => parseWebActorBindings("[]"), /must be an object/);
  assert.throws(() => parseWebActorBindings('{"user":{"actor":""}}'), /non-empty actor/);
});

test("actor lookup reuses the control-plane credential map and rejects ambiguous actors", () => {
  const credentials = credentialsByActor(
    JSON.stringify({
      "operator-key": { actor: "operator-actor", roles: ["operator"] },
      "approver-key": { actor: "approver-actor", roles: ["approver"] },
    }),
  );
  assert.equal(credentials.get("operator-actor")?.apiKey, "operator-key");
  assert.deepEqual(credentials.get("approver-actor")?.roles, ["approver"]);
  assert.throws(
    () =>
      credentialsByActor(
        JSON.stringify({
          "first-key": { actor: "same-actor", roles: ["operator"] },
          "second-key": { actor: "same-actor", roles: ["approver"] },
        }),
      ),
    /more than one API credential/,
  );
});

test("Supabase topology requires independently bound operator and approver users", () => {
  const credentials = credentialsByActor(
    JSON.stringify({
      "operator-key": { actor: "operator-actor", roles: ["operator"] },
      "approver-key": { actor: "approver-actor", roles: ["approver"] },
    }),
  );
  validateWebApprovalTopology(
    parseWebActorBindings(
      JSON.stringify({
        "operator-user": "operator-actor",
        "approver-user": "approver-actor",
      }),
    ),
    credentials,
  );
  assert.throws(
    () => validateWebApprovalTopology(parseWebActorBindings('{"operator-user":"operator-actor"}'), credentials),
    /independently bound operator and approver/,
  );
  assert.throws(
    () =>
      validateWebApprovalTopology(
        parseWebActorBindings('{"same-user":"combined-actor"}'),
        credentialsByActor(
          JSON.stringify({
            "combined-key": { actor: "combined-actor", roles: ["operator", "approver"] },
          }),
        ),
      ),
    /same Supabase user/,
  );
});

test("only approvers require an AAL2 session", () => {
  assert.equal(approverMfaRequired(["operator"], "aal1"), false);
  assert.equal(approverMfaRequired(["approver"], "aal1"), true);
  assert.equal(approverMfaRequired(["approver"], "aal2"), false);
});

test("mutations require an exact same-origin Origin header", () => {
  assert.equal(mutationOriginIsAllowed(new Request("https://kjds.example/backend/v1/health")), true);
  assert.equal(
    mutationOriginIsAllowed(
      new Request("https://kjds.example/backend/v1/approvals/a/decision", {
        method: "POST",
        headers: { origin: "https://kjds.example" },
      }),
    ),
    true,
  );
  assert.equal(
    mutationOriginIsAllowed(new Request("https://kjds.example/backend/v1/approvals/a/decision", { method: "POST" })),
    false,
  );
  assert.equal(
    mutationOriginIsAllowed(
      new Request("https://kjds.example/backend/v1/approvals/a/decision", {
        method: "POST",
        headers: { origin: "https://attacker.example" },
      }),
    ),
    false,
  );
});
