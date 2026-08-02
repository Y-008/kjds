import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const source = fs.readFileSync(
  path.resolve(
    import.meta.dirname,
    "../features/channel-accounts/channel-account-console.tsx",
  ),
  "utf8",
);
const contracts = fs.readFileSync(
  path.resolve(import.meta.dirname, "../features/channel-accounts/contracts.ts"),
  "utf8",
);
const styles = fs.readFileSync(
  path.resolve(
    import.meta.dirname,
    "../features/channel-accounts/channel-account.module.css",
  ),
  "utf8",
);
const commerceOs = fs.readFileSync(
  path.resolve(
    import.meta.dirname,
    "../features/commerce-os/commerce-os-console.tsx",
  ),
  "utf8",
);

test("channel account console consumes the exact-scope server projection", () => {
  assert.match(source, /\/backend\/v1\/channel-accounts\/workspace/);
  assert.match(source, /transitionChannelAccountState/);
  assert.match(source, /channelAccountView/);
  assert.match(source, /workspace\.filters/);
  assert.match(source, /workspace\.counts/);
  assert.match(source, /workspace\.source_gaps/);
  assert.match(source, /workspace\.snapshot_sha256/);
  assert.match(source, /workspace\.agent_artifact/);
  assert.match(contracts, /credential_fingerprint_sha256/);
  assert.match(contracts, /latest_event_type/);
  assert.match(contracts, /rate_limit_state/);
  assert.match(contracts, /capabilities: string\[\]/);
});

test("channel account console exposes no sensitive credential input", () => {
  assert.doesNotMatch(
    source,
    /<input[^>]+(?:name|placeholder)=["'][^"']*(?:secret|cookie|token|password|credential)[^"']*["']/i,
  );
  assert.match(source, /NON-SECRET · READ ONLY/);
  assert.match(source, /reference value returned: false/);
  assert.match(source, /non-secret SHA-256 only/);
});

test("channel account console renders every prohibited action", () => {
  for (const boundary of [
    "reauthorization_allowed",
    "credential_rotation_allowed",
    "secret_read_allowed",
    "scope_expansion_allowed",
    "authorization_change_allowed",
    "self_approval_allowed",
    "permit_issue_allowed",
    "external_verification_allowed",
    "customer_contact_allowed",
    "platform_contact_allowed",
    "fictional_authority_allowed",
    "secret_reference_returned",
    "plaintext_secret_stored",
    "cookie_allowed",
    "internal_token_allowed",
    "device_session_allowed",
    "private_endpoint_allowed",
    "captcha_bypass_allowed",
    "access_control_bypass_allowed",
    "projection_grants_permission",
    "provider_mutation_api_exposed",
    "provider_mutation_enabled",
    "external_write_allowed",
  ]) {
    assert.match(source, new RegExp(`${boundary}=false`));
  }
});

test("channel account console has explicit responsive overflow protection", () => {
  assert.match(styles, /overflow-x: hidden/);
  assert.match(styles, /@media \(max-width: 760px\)/);
  assert.match(styles, /@media \(max-width: 420px\)/);
  assert.match(styles, /overflow-wrap: anywhere/);
});

test("Commerce OS drills into the native channel account authority", () => {
  assert.match(commerceOs, /href="\/channel-accounts"/);
  assert.match(commerceOs, /渠道账户与运行身份权威/);
});

test("channel account mutation workflow is visibly gated and contract only", () => {
  assert.match(contracts, /production_workflow_status: "mutation_gated"/);
  assert.match(contracts, /policy_mode: "policy_only"/);
  assert.match(contracts, /internal_governance_api_exposed: true/);
  assert.match(contracts, /provider_mutation_api_exposed: false/);
  assert.match(contracts, /provider_mutation_enabled: false/);
  assert.match(source, /contract_only/);
});

test("channel account governance workbench consumes only the frozen internal transition seam", () => {
  assert.match(source, /\/backend\/v1\/channel-account-governance\/transitions/);
  for (const command of [
    "submit_evidence",
    "review_evidence",
    "request_change_approval",
    "decide_change_approval",
    "materialize_internal_plan",
  ]) assert.match(source, new RegExp(command));
  assert.match(source, /kjds-channel-account-change-proposal-v1/);
  assert.match(source, /execution_gated/);
  assert.match(source, /按相同 payload 重试/);
  assert.match(contracts, /ChannelAccountGovernanceTransition/);
  assert.match(contracts, /external_write_allowed: false/);
  assert.match(contracts, /permit_created: false/);
  assert.doesNotMatch(source, /type:\s*["'](?:issue_permit|execute_provider|rotate_credential)["']/);
});

test("governance forms contain no secret cookie token or credential material inputs", () => {
  assert.doesNotMatch(
    source,
    /<input[^>]+(?:name|placeholder)=?["'][^"']*(?:secret|cookie|token|password|credential|api.?key)[^"']*["']/i,
  );
  assert.match(source, /permit_created=false/);
  assert.match(source, /credential_created_or_read=false/);
  assert.match(source, /provider_contact_allowed=false/);
  assert.match(source, /external_write_allowed=false/);
});

test("governance workbench remains bounded at desktop and 390px", () => {
  assert.match(styles, /\.governanceWorkbench/);
  assert.match(styles, /min-width: 0/);
  assert.match(styles, /\.governanceForm/);
  assert.match(styles, /\.governanceSteps/);
  assert.match(styles, /@media \(max-width: 420px\)/);
});

test("governance POST uses the shared same-origin CSRF transport", () => {
  assert.match(source, /import \{ fetchJson \} from "\.\.\/\.\.\/lib\/fetch-json"/);
  assert.match(
    source,
    /fetchJson<ChannelAccountGovernanceTransition>\("\/backend\/v1\/channel-account-governance\/transitions", \{/,
  );
  assert.match(source, /method: "POST"/);
  assert.match(source, /body: JSON\.stringify\(request\)/);
  assert.doesNotMatch(
    source,
    /fetch\("\/backend\/v1\/channel-account-governance\/transitions"/,
  );
});

test("governance retry reuses the exact frozen request object", () => {
  assert.match(source, /setLastRequest\(request\)/);
  assert.match(source, /lastRequest \? <button[\s\S]*?send\(lastRequest\)/);
  assert.doesNotMatch(
    source,
    /lastRequest \? <button[^>]+submitProposal/,
  );
  assert.doesNotMatch(
    source,
    /lastRequest \? <button[^>]+new Date\(/,
  );
});

test("governance draft and form schema contain no credential material fields", () => {
  const draftStart = source.indexOf("const initialGovernanceDraft");
  const draftEnd = source.indexOf("type GovernanceRequest", draftStart);
  const governanceDraft = source.slice(draftStart, draftEnd);
  const contractStart = contracts.indexOf("export type ChannelAccountGovernanceDraft");
  const governanceContract = contracts.slice(contractStart);
  for (const forbidden of [
    "secret",
    "cookie",
    "token",
    "password",
    "credential",
    "apiKey",
    "clientSecret",
    "permit",
  ]) {
    assert.doesNotMatch(governanceDraft, new RegExp(`${forbidden}\\s*:`, "i"));
    assert.doesNotMatch(governanceContract, new RegExp(`${forbidden}\\s*:`, "i"));
  }
  assert.doesNotMatch(source, /<input[^>]+type="password"/i);
});

test("governance grids collapse and receipts wrap before 390px", () => {
  assert.match(
    styles,
    /@media \(max-width: 760px\)[\s\S]*?\.governanceForm,[\s\S]*?\.governanceSteps,[\s\S]*?\.transitionReceipt > div[\s\S]*?grid-template-columns: 1fr/,
  );
  assert.match(
    styles,
    /@media \(max-width: 420px\)[\s\S]*?\.governanceWorkbench[\s\S]*?padding: 15px/,
  );
  assert.match(styles, /\.transitionReceipt code \{ min-width: 0; overflow-wrap: anywhere; \}/);
});
