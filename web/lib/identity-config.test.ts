import assert from "node:assert/strict";
import test from "node:test";

import {
  approverMfaRequired,
  credentialsByActor,
  mutationOriginIsAllowed,
  parseWebActorBindings,
  rejectedLoginResponse,
  resolveLegacyApiCredential,
  validateWebApprovalTopology,
  webAuthMode,
  webRedirect,
  webRequestUrl,
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

test("legacy Web can resolve its server identity from the shared credential map", () => {
  const fromMap = resolveLegacyApiCredential({
    KJDS_API_ACTOR: "container-operator",
    KJDS_API_KEYS_JSON: JSON.stringify({
      "container-key": { actor: "container-operator", roles: ["operator", "reviewer"] },
    }),
  });
  assert.equal(fromMap.apiKey, "container-key");
  assert.deepEqual(fromMap.roles, ["operator", "reviewer"]);

  const uniqueOperator = resolveLegacyApiCredential({
    KJDS_API_KEYS_JSON: JSON.stringify({
      "operator-key": { actor: "operator-actor", roles: ["operator"] },
      "approver-key": { actor: "approver-actor", roles: ["approver"] },
    }),
  });
  assert.equal(uniqueOperator.actorId, "operator-actor");

  const direct = resolveLegacyApiCredential({
    KJDS_API_ACTOR: "local-operator",
    KJDS_API_KEY: "direct-key",
    KJDS_API_ROLES: "operator,admin",
  });
  assert.equal(direct.apiKey, "direct-key");
  assert.deepEqual(direct.roles, ["operator", "admin"]);
  assert.throws(
    () =>
      resolveLegacyApiCredential({
        KJDS_API_ACTOR: "missing-actor",
        KJDS_API_KEYS_JSON: JSON.stringify({
          "another-key": { actor: "another-actor", roles: ["operator"] },
        }),
      }),
    /has no API credential/,
  );
  assert.throws(
    () =>
      resolveLegacyApiCredential({
        KJDS_API_KEYS_JSON: JSON.stringify({
          "first-key": { actor: "first-operator", roles: ["operator"] },
          "second-key": { actor: "second-operator", roles: ["operator"] },
        }),
      }),
    /requires KJDS_API_ACTOR/,
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

test("mutations require exact Origin or browser-controlled same-origin metadata", () => {
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
        headers: { "x-kjds-csrf": "same-origin-fetch" },
      }),
    ),
    true,
  );
  assert.equal(
    mutationOriginIsAllowed(
      new Request("https://kjds.example/backend/v1/approvals/a/decision", {
        method: "POST",
        headers: {
          referer: "https://kjds.example/growth",
          "sec-fetch-site": "same-origin",
        },
      }),
    ),
    true,
  );
  assert.equal(
    mutationOriginIsAllowed(
      new Request("https://kjds.example/backend/v1/approvals/a/decision", {
        method: "POST",
        headers: { referer: "https://kjds.example/growth" },
      }),
    ),
    true,
  );
  assert.equal(
    mutationOriginIsAllowed(
      new Request("https://kjds.example/backend/v1/approvals/a/decision", {
        method: "POST",
        headers: {
          referer: "https://attacker.example/",
          "sec-fetch-site": "cross-site",
        },
      }),
    ),
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
  assert.equal(
    mutationOriginIsAllowed(
      new Request("http://0.0.0.0:3000/auth/login", {
        method: "POST",
        headers: {
          host: "127.0.0.1:3000",
          origin: "http://127.0.0.1:3000",
          referer: "http://127.0.0.1:3000/login",
          "sec-fetch-site": "same-origin",
        },
      }),
    ),
    true,
    "the browser-visible Host must win over the container bind address",
  );
  assert.equal(
    mutationOriginIsAllowed(
      new Request("http://0.0.0.0:3000/auth/login", {
        method: "POST",
        headers: {
          host: "127.0.0.1:3000",
          origin: "https://attacker.example",
          "sec-fetch-site": "cross-site",
        },
      }),
    ),
    false,
  );
});

test("browser redirects and rejected login HTML use the public Host", async () => {
  const request = new Request("http://0.0.0.0:3000/auth/login", {
    method: "POST",
    headers: {
      host: "127.0.0.1:3000",
      origin: "http://127.0.0.1:3000",
    },
  });
  assert.equal(
    webRequestUrl(request, "/login?error=invalid").href,
    "http://127.0.0.1:3000/login?error=invalid",
  );
  const rejectedLogin = rejectedLoginResponse(request);
  assert.equal(rejectedLogin.status, 403);
  assert.match(
    rejectedLogin.headers.get("content-type") ?? "",
    /^text\/html/,
  );
  assert.match(
    await rejectedLogin.text(),
    /href="http:\/\/127\.0\.0\.1:3000\/login"/,
  );
});
