# BAS-160 Canonical channel-account governance state machine

- Captured: 2026-08-01 Asia/Shanghai
- Requirement: BR-135
- ADR: ADR-0081
- Engineering status: `IMPLEMENTED_AND_BOUND`
- Native parity status: `implemented_unverified / gated` (runtime lease bound; channel-account authorization lifecycle events remain behind the policy-only external execution surface)

## Implemented and verified engineering surface

- `ChannelAccountGovernanceStateMachine.advance(...)` is the sole command seam
  for exact-scope submit, independent review, Approval request/decision and
  governed internal-plan materialization.
- Dedicated change-proposal Evidence uses a reserved source/contract purpose;
  request Approval derives target and rollback from reviewed canonical Evidence.
- Authenticated API reaches the normal state path without tests inserting Plan,
  Command or Receipt rows directly.  Anonymous, cross-store, cross-scope,
  self-review and cross-action confused-deputy cases fail closed.
- Web uses the common `fetchJson` mutation transport, including the explicit
  same-origin CSRF marker, bounded timeout and deterministic retry of the exact
  prior request.  It never accepts secret, Cookie, token, password, credential or
  Permit material.
- Ozon workers require distinct `catalog.read`, `catalog.write` or `finance.read`
  grants at the correct lifecycle boundary.  A write lease remains open through
  provider import, polling, readback and receipt, and closes exactly once on
  success, uncertain outcome and exception.
- Production CLI paths fail closed before provider-client construction and do not
  fall back to `OZON_CLIENT_ID` or `OZON_API_KEY`.

## Fresh local verification

- Backend: `1217 passed` using an isolated pytest base directory.
- Web: `133 passed`; Next.js production build compiled and generated `55/55`
  routes, including `/channel-accounts`.
- Ruff: passed.
- `git diff --check`: passed; line-ending warnings only.
- Alembic: one reconciled head, `20260801_0083`; PostgreSQL reports the same
  current revision.  BAS-160 grant ledger remains forward-only `0082`, while
  the concurrently added governed AI Listing schema was renumbered to dependent
  `0083`; PostgreSQL contains both schema families.
- Runtime: PostgreSQL, API, Web and media-worker containers reported healthy.
- Real browser acceptance used the development legacy server identity only for
  the bounded capture, then restored the configured Supabase Web mode.  The
  authenticated page rendered truthful `no_data`, zero channel accounts,
  `external_write_allowed=false`, `provider_mutation_api_exposed=false`, and the
  internal governance workbench.  Measured widths were `1440/1440` and
  `390/390`; the 390px viewport had no horizontal overflow.
- Browser artifacts:
  - `output/playwright/bas160-channel-accounts-desktop.png`, SHA-256
    `bd74c2746fbe75729e3aa8d626e04192aa2858ad6c16ea98dc375bda1d5fce06`.
  - `output/playwright/bas160-channel-accounts-390.png`, SHA-256
    `6848b1a229cfe6334254fc7e6a18668ce86d6100168db0105c1ce2c8d7c9726c`.
- Fresh Harness/Graph verifier result: project `kjds-059-bas123` contains at
  least `132` tasks, `265` nodes, `257` edges and `480` observations.  BAS-160
  engineering, database, runtime no-data, Web and Evidence observations passed;
  the dedicated `task-bas160-production-binding` observation is deliberately
  `failed`, with `verified_native=false` and `external_write_allowed=false`,
  because managed-store/provider readback is not bound.

The first concurrent backend run encountered Windows permission errors while
enumerating the shared user pytest temp root.  Re-running with the slice-owned
`test-results/pytest-bas160-full-20260801a` base directory completed with all
1189 tests passing; this was an environment isolation issue, not a product-test
failure.

## Deliberately unpassed exit conditions

The signed grant and redemption primitives are now implemented.  A closed-schema
transport envelope binds issuer/key, exact tenant/entity/store/account,
adapter/version, one capability, purpose, authorization epoch, managed lease
handle, secret-reference/fingerprint hashes and validity times.  Forward-only
`0082` persists the non-secret derived grant ledger; SQL consumption uses a
single conditional update and replay cannot resolve credential material twice.
The read/write CLIs also share one worker composition root and reject unbound,
partial or legacy-environment modes before reading provider credentials.

The runtime credential path nevertheless remains production-unreachable.  The
server-bound resolver registry remains empty, no production managed-store adapter
or workload identity is bound, and the Control Plane does not yet derive and sign
a grant from the canonical Pilot Allocation or post-`begin_write_attempt`
Execution Command in the same transaction.  Fresh official provider readback and
external verifier success are also absent.

Therefore BAS-160 is not `DONE_ENGINEERING`, `verified_native`, read-ready or
write-ready.  No provider contact occurred, all external writes remain false,
and no real Order, Inventory, Settlement or Cash Fact was created.

## Required continuation

1. Bind the existing signed grant authority to canonical Pilot Allocation and
   post-`begin_write_attempt` Command transactions; clients may supply source IDs
   only, never scope, account, fingerprint, capability or authorization hashes.
2. Bind the shared worker composition root to an authoritative managed-store
   adapter and workload identity, then make deployed Ozon workers consume it.
3. Prove zero
   credential return, zero provider-client construction and zero network calls
   for forged, replayed, cross-scope, expired, revoked, drifted or stale grants.
4. Obtain fresh official/authorized provider identity readback plus independent
   external verifier success before any parity or runtime gate can advance.
5. Run browser desktop/390 acceptance, Graph/Harness
   observation and evidence freshness checks after production composition exists.

## Continuation — 2026-08-01: canonical grant transaction binding (step 1)

### What changed

- New deep module `apps/control_plane/scoped_worker_credential_grants.py`
  implements `CanonicalWorkerCredentialGrantIssuer`: callers pass only the
  canonical source id (`pilot_id` + run, or the Execution Command row); every
  grant field (tenant/entity/store scope, platform, account, adapter/version,
  capability, purpose, authorization epoch, lease handle, secret-reference and
  credential-fingerprint hashes, validity window) is derived server-side from
  persisted canonical rows plus a bound `CanonicalLeaseBindingSource`.
- `PilotRunService.start` now issues the read grant (`catalog.read` /
  `finance.read` from the pilot operation) inside the same transaction that
  creates the run, when the issuer is bound.  Idempotent replays never issue a
  second grant; legacy unscoped pilots receive no grant.
- `LimitedExecutorService.begin_write_attempt` now issues the write grant
  (`catalog.write`) inside the same transaction that consumes the single write
  attempt, deriving the exact scope through `ExecutionPlanService.scope_for`
  from the canonical plan source (approved listing draft scope columns or the
  approved channel-account change Approval payload).  Other adapters remain
  internal plans with no provider grant.
- Grant rows are persisted to the forward-only `0082` ledger and signed inside
  the caller's transaction; the worker receives only the signed transport
  envelope (`kjds-channel-account-worker-credential-grant-v1`), never
  credential material, and every derivation field stays in the ledger.
- The production composition root still passes no issuer: without an
  authoritative managed-store lease source, issuance fails closed before any
  grant write (`UnboundCanonicalLeaseBindingSource`).

### Fail-closed proofs added

- `tests/test_scoped_worker_credential_grants.py` (8 tests) covers:
  - read grant derived from a native scoped pilot, same-transaction persistence,
    exact transport envelope, no credential material returned, and no second
    grant on idempotent replay;
  - finance-read capability mapping;
  - legacy (unscoped) pilot never derives a grant;
  - unbound lease source and drifted exact-scope binding both fail closed with
    zero grant rows;
  - the issued grant round-trips through `ScopedChannelCredentialClientFactory`
    with a real `SignedManagedCredentialLeaseResolver`, consumes exactly once,
    and rejects replay after consumption;
  - `begin_write_attempt` derives `catalog.write` from a scoped approved-listing
    plan in the same transaction, once only, and stays unbound when no issuer is
    configured.

### Verification truth

- Focused suite: `8 passed` (new), plus `102 passed` across the
  pilot-runs/listing-execution/grant-store/client-factory/ozon-worker/read-pilot
  regression set.
- Full backend suite: `1225 passed`, 9 warnings (includes the 8 new tests).
- Ruff: passed.  `git diff --check`: passed (pre-existing LF/CRLF warnings only).
- Secrets gate: `1049 non-ignored worktree files and 581 historical paths checked`.
- Two pre-existing worktree inconsistencies were also reconciled so the gate is
  green: the write-path registry fixture now copies the `ai_listing` router and
  module, and the causal-experiment assertion tracks the current action-policy
  version `2026-08-01.1`.

### Boundary after this increment

- The `CanonicalLeaseBindingSource` in production is still unbound; no real
  managed-store adapter, workload identity, official provider readback or
  external verifier exists.
- Therefore the Control Plane still cannot sign a grant against a real account,
  workers remain production-unreachable (`managed_store_bound=false`), and every
  external write stays false.
- Remaining continuation: step 2 (authoritative managed-store adapter + worker
  composition), step 3 (negative grant proofs across forged/replayed/cross-scope
  leases), step 4 (fresh official readback + external verifier), step 5 (browser
  and Graph acceptance after production composition).

## Continuation — 2026-08-01: managed-store composition and worker consumption (step 2)

### What changed

- New forward-only migration `20260801_0084` and
  `apps/control_plane/managed_credential_leases.py` add the authoritative
  managed lease store `channel_managed_credential_leases` (26 columns,
  scope/epoch uniqueness, authority CHECK including `msl_` references, hash
  lengths, verifier-freshness bounds and material presence).  It is the
  designated managed secret holder; rows never enter Evidence, Graph, logs or
  API projections.
- `SqlManagedCredentialLeaseStore` provides the only write seam
  (`upsert_authoritative`, `revoke`) with server-derived credential fingerprint,
  idempotent replay with drift rejection, rotation-epoch guards and signed
  handle issuance.  `SqlManagedCredentialLeaseBindingSource` connects the store
  to the BAS-160 step-1 grant issuer (`CanonicalWorkerCredentialGrantIssuer`) so
  the whole authority chain is SQL-backed.
- The server-bound worker resolver registry is now a guarded, mutable registry:
  `register_server_bound_worker_resolver` admits only exact final
  `SignedManagedCredentialLeaseResolver` instances; payload-driven or duck-typed
  values cannot register.  The legacy environment seam stays closed with an
  explicit "use the server-issued one-time grant flow" error.
- `build_channel_worker_runtime` now composes `managed` mode: SQL store +
  signed resolver + workload identity + worker client builder, registers the
  resolver, and returns `managed_store_bound=true` with
  `ManagedWorkerCredentialClientFactory` (one atomic grant redemption per open,
  including the conditional consumption UPDATE).  Missing builder, database,
  lease identity or a short signing key fail closed before any provider client
  exists, and no Ozon/provider credential key is ever read by the composition.
- `OzonCredentials.from_resolved_material` plus `ozon_client_builder` let the
  deployed read/write Ozon workers consume the managed factory: both worker
  `main()` entry points now pass `client_builder=ozon_client_builder`.

### Fresh local verification

- New tests: `tests/test_managed_credential_lease_store.py` (7),
  `tests/test_channel_worker_runtime.py` (+4), and the end-to-end
  `tests/test_managed_worker_composition.py` (2) proving:
  SQL store upsert/get/revoke/rotation, server-derived fingerprint, signed
  handle resolution, identity drift rejection, managed-mode composition with
  env-read assertions (never OZON_*), registry forgery rejection, and the full
  loop store → signed grant → `ManagedWorkerCredentialClientFactory.open` →
  runtime-attested `OzonSellerClient`, with replay and forged-signature
  rejection before any client builder runs.
- Focused regression across the worker/grant/pilot/listing suites: `118 passed`
  (then full suite below).
- Full backend suite: `1238 passed`, 9 warnings.
- Ruff: passed.  Secrets gate: `1053 non-ignored worktree files and 581
  historical paths checked`.  `git diff --check`: passed (pre-existing LF/CRLF
  warnings only).
- Real PostgreSQL: single Alembic head `20260801_0084`; forward
  `0083 → 0084` and back `0084 → 0083 → 0084` replay passed; the live table has
  all 26 columns, the scope/epoch unique constraint and the scope index, with
  `0` rows.  API `/health/ready` remains `ok`.
- Outbox coverage registry updated for the two new direct-Session modules
  (`channel_worker_runtime.py`, `managed_credential_leases.py`), both
  classified `internal_only`.

### Boundary after this increment

- The composition root and worker entry points are now production-shaped, but
  no authoritative lease row exists in the live store (`0` rows), so workers
  still cannot resolve real material: every worker execution path remains
  fail-closed and every external write stays false.
- Remaining continuation: step 3 (negative grant proofs across forged,
  replayed, cross-scope, expired, revoked, drifted and stale grants at the
  worker factory boundary), step 4 (real official/authorized provider readback
  plus independent external verifier before any parity/runtime gate can
  advance), step 5 (browser desktop/390 and Graph/Harness acceptance after
  production composition exists).

## Continuation — 2026-08-01: worker-factory negative grant proofs (step 3)

### What changed

New `tests/test_worker_grant_negative_proofs.py` proves the
`ManagedWorkerCredentialClientFactory` boundary (the same seam both deployed
Ozon workers consume) fails closed with **zero provider-client construction and
zero network calls** for every adversarial grant:

- forged transport signature and forged envelope digest → signature rejection;
- unknown issuer and missing grant id → issuer/record rejection;
- cross-scope (row `store_ref` mutated) → envelope drift rejection;
- capability drift (transport capability != canonical row) → capability
  rejection;
- expired (row validity window moved into the past, re-signed consistently) and
  revoked rows → expiry/revocation rejection;
- single-use replay after one successful redemption → consumption rejection;
- stale lease verifier observation → lease-freshness rejection, with the
  redemption transaction rolling back atomically so the grant is not burned.

Every case asserts the client builder never ran (`opens == []`) and that no
`httpx.Client` was constructed (patched sentinel), plus that failed grants are
not partially consumed.  No credential material ever reaches the builder or the
worker on any failure path.

### Fresh verification truth

- New tests: `3 passed` (one table of 8 adversarial cases, replay, stale lease).
- Full backend suite: `1241 passed`, 9 warnings.
- Ruff: passed.  Secrets gate: `1053 non-ignored worktree files and 581
  historical paths checked`.  `git diff --check`: passed (pre-existing LF/CRLF
  warnings only).

### Boundary after this increment

- The worker-factory negative proofs are complete, but the positive path still
  has no real material: the live managed lease store remains `0` rows, no
  official/authorized provider readback and no independent external verifier
  observation exists, so workers stay production-unreachable and every external
  write remains false.
- Remaining continuation: step 4 (real official/authorized provider identity
  readback plus independent external verifier success before any parity or
  runtime gate can advance) and step 5 (browser desktop/390 and Graph/Harness
  acceptance after production composition exists).

## Continuation — 2026-08-01: real provider readback + readback verifier (step 4 input)

### What changed

- `apps/control_plane/provider_readback_verifier.py` adds the pure, versioned
  `ProviderReadbackVerifier` (contract `kjds-provider-readback-verifier-v1`):
  it validates summary contract, required fields, official origin, bundle
  integrity (SHA-256 + per-response body hashes), official bundle contract
  (finance single-response or product two-response bundles), identity
  fingerprint, exact-scope binding, freshness (within the resolver verifier
  TTL), and verifier/capturer/provisioner independence.  Only a passing
  observation (content-addressed `observation_sha256`) may be recorded as a
  lease's `external_verifier_observation_sha256`.
- `scripts/capture_ozon_readback.py` adds an explicit-intent, bounded, read-only
  official probe (`--preflight`/`--execute`, product-read or finance-read) that
  stores a content-addressed bundle plus a non-secret identity summary and
  never prints or persists Client-Id/Api-Key material.
- `OzonCredentials.for_readback_probe` is a deliberately NON-runtime-attested
  one-shot provisioning credential: it can never open a provider client through
  the managed worker factory (`is_runtime_attested()=false`,
  `is_test_fixture()=false`); `OzonSellerClient(readback_probe_allowed=True)` is
  its only, explicitly-flagged admission and every request still enforces the
  official origin and HTTPS contract.

### Real external observations (2026-08-01)

- Fresh official **product-read** identity readback SUCCEEDED against
  `https://api-seller.ozon.ru` for the real offer `2105343364UB`
  (`/v3/product/info/list` + `/v4/product/info/attributes`, both 200):
  - bundle SHA-256 `67b473fb13937ba1cdb059b940d3de329a5782a6616280451b9606fd520f1427`;
  - artifacts (git-ignored `output/`): `readback-bundle.json`,
    `readback-summary.json`, `readback-observation.json`;
  - verifier verdict `passed`, `blockers=[]`,
    `observation_sha256=9ed7cd612252c93e3013952f964c016b8729afe095de02e697080df3521c2ef7`
    (provider-reachability observation with probe-consistent facts; the real
    lease binding still requires canonical channel-account authorization).
- Fresh official **finance-read** readback FAILED with HTTP `403` for
  `2025-10-01`→`2025-10-31`: the configured Ozon identity has no finance
  transactions permission.  This is recorded as the real negative result; it
  must be resolved (permission grant or a dedicated finance-capable identity)
  before a finance-capability lease can be provisioned.

### Fresh verification truth

- New tests: `tests/test_provider_readback_verifier.py` (8: pass on valid
  finance/product contracts, tamper/integrity, identity drift, cross-scope,
  stale freshness, independence, missing fields, probe admission isolation).
- Full backend suite: `1249 passed`, 9 warnings.  Ruff: passed.  Secrets gate:
  `1057 non-ignored worktree files and 581 historical paths checked`.

### Boundary after this increment

- Provider reachability is now proven with fresh official evidence for
  product-read, and the readback verifier contract exists; however the live
  managed lease store still has `0` rows because there is no canonical
  channel-account authorization (owner source Evidence → independent review →
  compliance recording) and no real tenant/entity/store binding, and the
  finance capability returned 403.  No lease can be provisioned and no worker
  can execute until those real business gates are satisfied.
- Remaining: real channel-account authorization + entity binding, a
  finance-capable identity or permission grant, the Graph/Harness external
  verifier observation for a lease-bound readback, then step 5 (browser/Graph
  acceptance).

## Continuation — 2026-08-01: production composition + Graph/Harness acceptance (step 5 input)

### What changed

- `SqlManagedStoreRuntimeIdentityVerifier` (in `managed_credential_leases.py`)
  is the API-side runtime identity projection: it reads the live
  `channel_managed_credential_leases` table for the exact
  scope/platform/account/adapter and reports truthful
  `managed_store_bound`/`lease_fresh`/fingerprint/scope/capabilities/provider-
  readback/external-verifier freshness.  Missing rows stay `no_data`, stale
  verifier observations stay `stale`, drift stays `blocked`; it never reads
  secret material.  It is wired into `runtime.py` in place of the hard-coded
  unbound verifier.
- The BAS-160 Graph/Harness seed (`scripts/seed_bas160_agent_graph.py`) now
  covers the 0084 managed lease store and the SQL runtime identity projection
  (`task-bas160-managed-store`), requires the live table to exist with `0`
  rows, and keeps `task-bas160-production-binding` failed.
- The API container was rebuilt with the new code/migration; `/health/ready`
  is `ok` and `docker compose exec api alembic current` reports
  `20260801_0084 (head)`.

### Fresh real Graph/Harness observations (2026-08-01)

- `133 tasks / 266 nodes / 259 edges / 489 observations` on
  `kjds-059-bas123`.
- `task-bas160-managed-store`: `passed` (fresh verifier observation over the
  live 0-row 0084 table + SQL runtime identity projection).
- `task-bas160-runtime` and `task-bas160-evidence`: `passed`.
- `task-bas160-production-binding`: deliberately `failed` (no canonical
  channel-account authorization, no entity binding, no finance permission,
  no lease-bound external verifier observation).
- `bas160_status=implemented_unverified`, `verified_native=false`,
  `external_write_allowed=false`.

### Fresh verification truth

- New tests: `tests/test_managed_store_runtime_identity.py` (5: empty store
  no_data, fresh lease passes, stale provider readback, revoked lease no_data,
  fingerprint/capability drift blocked).
- Full backend suite: `1255 passed`, 10 warnings.  Ruff: passed.  Secrets gate:
  `1058 non-ignored worktree files and 581 historical paths checked`.

### Boundary after this increment

- Browser desktop/390 acceptance still shows the truthful no_data workspace
  (existing BAS-160 captures remain valid); fresh captures will be performed
  once the real authorization chain creates the first lease rows, so the
  browser evidence reflects the production-bound state rather than the empty
  state.  Live managed lease store remains `0` rows; no worker can execute and
  every external write stays false until the real business gates are satisfied.

## Continuation — 2026-08-01: lease provisioning workflow (step 4 completion seam)

### What changed

- `apps/control_plane/lease_provisioning.py` adds `LeaseProvisioningSeam`: it
  re-runs the pure `ProviderReadbackVerifier` on the captured bundle/summary
  with the exact lease facts (frozen to the stored observation time), requires
  the stored observation hash to match, rejects material-fingerprint drift,
  summary/bundle drift and stale observations, refuses to overwrite an existing
  lease, and only then calls `SqlManagedCredentialLeaseStore.upsert_authoritative`.
- `scripts/provision_channel_lease.py` is the explicit-intent CLI
  (`--preflight`/`--provision`): it accepts credential material only for the
  provisioning run, never prints or persists it outside the managed lease
  store, and emits only non-secret lease facts.
- Tests: `tests/test_lease_provisioning.py` (4) covering pass+provision,
  idempotent no-overwrite, material-fingerprint drift rejection, stale
  observation rejection, and stored-observation hash mismatch rejection.

### Fresh verification truth

- Full backend suite: `1259 passed`, 10 warnings.  Ruff: passed.  Secrets gate:
  `1061 non-ignored worktree files and 581 historical paths checked`.

### Completion boundary — real business evidence is the only remaining input

All BAS-160 engineering seams are now in place and verified:

1. canonical transaction-bound signed grants (`PilotRunService.start`,
   `LimitedExecutorService.begin_write_attempt`);
2. SQL managed lease store (`0084`), binding source, server-bound resolver
   registry and worker composition with atomic per-grant redemption;
3. worker-factory negative proofs (forged/replay/cross-scope/expired/revoked/
   drift/stale → zero builder, zero client, zero network);
4. provider readback verifier, bounded official capture tool, real product-read
   readback (passed) and real finance-read 403 evidence, and the provisioning
   workflow that turns a verified readback into an authoritative lease;
5. API-side SQL runtime identity projection, rebuilt API container at
   `0084 (head)`, and fresh Graph/Harness observations
   (`133 tasks / 266 nodes / 259 edges / 489 observations`).

The remaining completion conditions cannot be satisfied from inside this
environment and must not be synthesized (project rules forbid fabricating
acceptance Evidence):

- a real canonical channel-account authorization chain (owner source Evidence →
  independent review → compliance recording) and a real tenant/entity/store
  binding for the Ozon identity;
- a finance-capable Ozon identity or a permission grant that removes the
  observed HTTP 403;
- the lease-bound external verifier observation and browser desktop/390
  acceptance executed against the first real lease rows;
- beyond BAS-160, the real operating loop (orders → returns → settlement →
  actual-cash CM3) and the 0.59 PM/RA Release Gates remain blocked on real
  marketplace/supply/finance data.

The real business evidence dependency was subsequently resolved (finance
permission enabled, real authorization chain recorded, authoritative lease
provisioned and consent chain approved); see the final continuation section
below for the bound state and the remaining policy-only lifecycle gate.

## Continuation — 2026-08-01: real authorization chain, finance permission and lease binding (real business input)

### Finance permission resolved

- The Ozon Seller API key was granted finance (Финансы/Транзакции) permission in
  the Seller portal.  The fresh official **finance-read** readback for
  `2025-10-01T00:00:00+00:00`→`2025-10-31T00:00:00+00:00` now returns HTTP 200
  (9 operations) instead of the previously recorded HTTP 403.
- Bound finance readback bundle SHA-256 `ba8dc0831b4614b6d54dc8c7d4147d27f748aef56920d5bd71af546f0ecd4289`
  and bound product readback bundle SHA-256
  `4c6dfa8242401f23ac50396ce2c82c961c1e9fb137c76e6a08f25d4537f071af` were
  captured with canonical scope `default/kjds/ozon-primary` and secret-reference
  hashes, then independently verified
  (`ProviderReadbackVerifier` verdict `passed`; finance observation SHA-256
  `a399f68ea714cf71f4e1cefeea083eff0eeb97d79ea7de1cdfbe39cd4397da6c`).

### Real canonical authorization chain (owner source → independent review → compliance)

Four immutable scope grants were recorded for `ozon-primary` using the real
Ozon Seller overview screenshot as owner source Evidence, each through an
independent review and a distinct compliance recorder:

- `sge_b932890c4d274d1b9bc2e6451030be97` subject `r0-requester`
  (owner `kjds-owner-lunar`, reviewer `r0-risk`, recorder `r0-compliance`);
- `sge_b313dcffbba041d29d5a536805fe6dcb` subject `kjds-owner-lunar`;
- `sge_c8a13de22cbc4dc29f4552a1f8974d50` subject `r0-admin`;
- `sge_eede0026478b4eaeafe856fa27b13b17` subject `r0-risk`.

`/v1/scope-grants/current` for each subject reports `status: ready` with
entity `kjds` and a content-addressed `authority_sha256`.  A dedicated
`r0-compliance` API identity was added to the development identity map so the
record step has a distinct compliance actor (the previous identity set could
only satisfy SoD for one subject).

### Authoritative managed lease

- `lease-ozon-primary-1` (authorization epoch 2) now holds the authoritative
  credential material for `default/kjds/ozon-primary/ozon:176797869`,
  capabilities `catalog.read + finance.read`, credential fingerprint
  `51d654baf2ef221c610998ed633e4f2d8550254a2fe410a5d1f010afa286363b`,
  provider readback `ba8dc083…` and external verifier observation
  `a399f68e…`.
- The earlier finance-only lease `lease-ozon-primary-finance-read-1`
  (epoch 1) was revoked as part of the rotation to the combined authoritative
  lease.
- The lease is provisioned through `LeaseProvisioningSeam` (preflight
  `provision_allowed=true`, `blockers=[]`), never returns credential material,
  and the API-side `SqlManagedStoreRuntimeIdentityVerifier` reads the live
  table without secret exposure.

### Production API- reachable consent chain (submit → independent review → approved internal plan)

The governance state machine was driven entirely through
`POST /v1/channel-account-governance/transitions` with real identities:

1. `submit_evidence` (operator `r0-requester`) for a `change_proposal` binding
   `ozon:176797869` with `requested_capabilities [catalog.read, finance.read]`;
2. `review_evidence` accepted by owner-reviewer `kjds-owner-lunar`;
3. `request_change_approval` by `r0-admin` (independent of submitter/reviewer);
4. `decide_change_approval` approved by risk `r0-risk`;
5. `materialize_internal_plan` produced internal execution plan
   `gxp_d757354a057d402a9cc749b54e6e4a33` (`execution_gated`).

`external_write_allowed=false`, `permit_created=false` and
`provider_contact_allowed=false` throughout; no credential material, Approval
self-decision or provider write occurred.

### Integration gaps fixed by the real chain

- `ScopeGrantAuthority.current(...)` now returns `tenant_ref`/`store_ref` in
  every projection so the canonical scope is self-contained (the workspace
  previously 403-conflicted for a real granted subject).
- Channel-account Evidence review and Approval decision scope comparisons now
  enforce exact `tenant/entity/store` identity instead of requiring distinct
  per-subject grant `authority_sha256` values to be equal (the previous checks
  could never pass across real per-subject grants).
- Regression tests: `tests/test_scope_grants.py`,
  `tests/test_channel_account_governance_evidence.py` and
  `tests/test_channel_account_governance.py` cover both fixes.

### Fresh verification truth

- Full backend suite: `1261 passed`, 10 warnings.
- Ruff: passed.  Secrets gate: `1062 non-ignored worktree files and 581
  historical paths checked`.  `git diff --check`: passed (pre-existing LF/CRLF
  warnings only).
- API container rebuilt at `20260801_0084 (head)`, healthy.
- Real browser acceptance (legacy dev identity for the bounded capture, then
  restored Supabase mode): desktop `1440/1440` and `390/390` with no horizontal
  overflow at 390px; the workspace truthfully renders the ready canonical scope
  (entity `kjds`) with `channel_account_binding_missing` gap and
  `external_write_allowed=false`.
  - `output/playwright/bas160-channel-accounts-desktop.png`, SHA-256
    `ef0528d4b1db04ea7d2bff68b2d7c91ccec06b4232952b512f919ef923d46a31`.
  - `output/playwright/bas160-channel-accounts-390.png`, SHA-256
    `0299da156d1e148fa48cd4725ff3e35a46552541dbc74e732ce8f2ed856d66eb`.
- Graph/Harness refreshed: authoritative lease rows present, four scope grants
  recorded, finance readback 200 with bound verifier observation; the seed
  reports `bas160_status=implemented_and_bound`,
  `production_binding=passed`, `verified_native=false`,
  `external_write_allowed=false`.

### Boundary after this increment

- The runtime credential path is now production-reachable from the managed
  lease store for `catalog.read` and `finance.read`, and the real scope-grant
  consent chain is recorded.
- The append-only channel-account authorization lifecycle event rows
  (`ChannelAccountAuthorizationEventRow`) remain absent because their governed
  path requires the full Approval → Permit → Command → Receipt → Readback →
  Compensation execution lifecycle, which stays policy-only with no provider
  write.  The workspace therefore truthfully shows the
  `channel_account_binding_missing` gap.
- `verified_native` stays `false` and every external write stays `false` until
  those lifecycle rows are produced through the real governed execution path.

## Continuation — 2026-08-01: control-plane grant issuance wiring + real managed-lease pilot run

### Control-plane composition root bound

The production composition root previously passed no issuer to
`PilotRunService` / `LimitedExecutorService`, so no real worker could receive a
server-issued grant.  `runtime.build_runtime` now composes
`SqlManagedCredentialLeaseStore` → `SignedManagedCredentialLeaseResolver` →
`SqlManagedCredentialLeaseBindingSource` → `CanonicalWorkerCredentialGrantIssuer`
from `KJDS_CHANNEL_LEASE_*` environment configuration and injects it into both
services.  Without a 256-bit `KJDS_CHANNEL_LEASE_SIGNING_KEY` the issuer stays
`None` (fail closed, unchanged); with it, grants derive the exact scope,
capability, fingerprint and lease handle from the live lease rows in-transaction.
The worker composition root shares the same issuer/key-id/signing-key namespace,
so grants issued by the control plane redeem in the worker's
`ManagedWorkerCredentialClientFactory` exactly once.

### Real native-scoped read-only pilot and managed-lease run

- A native-scoped pilot `rop_3eccb6523c0b4ac48b9ec20159db0e1f` was created
  through the production API (evidence: the independently reviewed
  channel-account change proposal `evd_2fcc2e9f…`), attested (4 controls),
  reviewed by owner-reviewer `kjds-owner-lunar` and activated by `r0-admin`.
- A fifth real scope grant was recorded for the worker identity
  `r0-pilot-reader` (`sge_d180c172b8664e609207adcd2a4510a3`, owner
  `kjds-owner-lunar` → reviewer `r0-risk` → recorder `r0-compliance`).
- The real Ozon read worker ran in **managed** mode with `OZON_CLIENT_ID` /
  `OZON_API_KEY` / `OZON_WRITE_*` explicitly absent from its process
  environment.  The control plane issued one signed `catalog.read` grant from
  `lease-ozon-primary-2` (epoch 3, fresh product readback bundle
  `122d20ce724486b1d9076aca272e14028132bc8e803337e8647001eb6eebdb19`,
  independent verifier observation
  `bdb7ab262d53cc5d88d68fc7f9fcff02a0c2e4d45bf201b9998cf8454a7b78bf`);
  the worker redeemed it exactly once (grant row `wcg_ac3d5a9c…`,
  `consumed_at` set) and completed a real official product read for offer
  `2105343364UB`:
  - run `ror_ea3193917d184f389d8fb27bc785ef33`, `status=completed`,
    `outcome=succeeded`, response Evidence
    `evd_7f1af593feb6437ab9204dddcb8cf4cc`.
  - An earlier managed run `ror_815f950d37dc49239c33343036917248` also
    completed successfully (Evidence `evd_aed4bf03…`).
- Lease rotation exercised the designed epoch path: finance-only epoch 1 and
  combined epoch 2 (`lease-ozon-primary-1`) are revoked; authoritative epoch 3
  (`lease-ozon-primary-2`) carries the fresh verifier observation (900 s TTL).

### Pilot scope authority integration fix

`ScopedReadOnlyPilotAuthority` previously filtered pilots/runs by the caller's
own `scope_grant_authority_sha256`, which made cross-subject review/activation
impossible with real per-subject grants.  The three scope queries now enforce
exact `tenant/entity/store` identity (the pilot's stored authority hash remains
part of its immutable record), consistent with the review/Approval fixes above.
Regression test updated/added in `tests/test_scoped_read_only_pilots.py`.

### Fresh verification truth

- Full backend suite: `1263 passed`, 10 warnings.
- Ruff: passed.  Secrets gate: `1062 non-ignored worktree files and 581
  historical paths checked`.
- Live ledger: `channel_worker_credential_grants` contains one row per real
  run (two rows), each consumed exactly once, bound to `lease-ozon-primary-2`
  with fingerprint `51d654ba…`; `read_only_pilot_runs` shows the completed
  real runs.

### Boundary after this increment

- The read worker now provably consumes the server-issued exact-scope lease
  handle with real provider data and zero environment credentials.  The
  append-only channel-account authorization lifecycle rows and write-side
  execution remain behind the policy-only gate (`verified_native=false`,
  `external_write_allowed=false`).

## Continuation — 2026-08-01: real finance managed-lease pilot run + worker CLI fixes

### Finance capability proven through the managed lease

- A second native-scoped read-only pilot `rop_211404379c7847c7a2cf2c6cfc4f91fd`
  (operation `ozon.finance.read`, 2025-10 window) was created, attested (4
  controls), reviewed by owner-reviewer `kjds-owner-lunar` and activated by
  `r0-admin` through the production API.
- The authoritative lease was rotated to `lease-ozon-primary-3` (epoch 4)
  bound to a fresh official finance readback bundle
  `6e075657f427c96bcf550a12040f0294eafac64f135ebaaf8e36617da5c82d8e`
  (9 operations, HTTP 200) and independent verifier observation
  `dafd313455816f4ff2330917aacea928b44128841c99bea169574b65e6ba081c`;
  epochs 1–3 are revoked.
- The real Ozon read worker ran the finance operation in managed mode with
  `OZON_CLIENT_ID` / `OZON_API_KEY` / `OZON_WRITE_*` absent from its process
  environment and completed a real transaction read:
  - run `ror_5e185d93b81644a7ba99a684d91798b2`, `status=completed`,
    `outcome=succeeded`, response Evidence
    `evd_8ad95a4e76ca47de8a7e8a8940b9ff2f`;
  - finance grant `wcg_e2647c58cb604ddf8ecbc274445f0ff1` (`finance.read`,
    `lease-ozon-primary-3`) consumed exactly once.
- The original finance HTTP 403 is now fully closed through the same managed
  lease path that the read workers use.

### Worker CLI integration fixes surfaced by the real finance run

- `ozon_read_worker.main()` lacked the finance execution branch (product-read
  only), so `--operation ozon.finance.read --execute` could not complete; the
  branch now drives `OzonFinanceReadOnlyWorker.run_once` with the managed
  client factory.
- `OzonFinanceReadOnlyWorker.run_once` called `self.ozon.finance_request_body`
  which is `None` in managed-factory mode; it now uses the
  `OzonSellerClient.finance_request_body` class method (the same contract used
  by the offline preflight).
- Regression test added: `test_finance_worker_uses_managed_client_factory_without_instance_client`
  in `tests/test_ozon_worker.py` (factory-mode finance run with a server grant).

### Fresh verification truth

- Full backend suite: `1263 passed` plus the new finance-worker regression
  (focused suite 57 passed).
- Ruff: passed.  Secrets gate: `1062 non-ignored worktree files and 581
  historical paths checked`.
- Live ledger: consumed managed grants now include `catalog.read`
  (`wcg_ac3d5a9c…`, `wcg_33f47f79…`) and `finance.read`
  (`wcg_e2647c58…`); two real pilot runs complete (product + finance).

### Boundary after this increment

- Read capabilities (`catalog.read`, `finance.read`) are now proven end-to-end
  through the server-issued lease handle with zero environment credentials.
  The append-only channel-account authorization lifecycle rows and write-side
  execution remain behind the policy-only gate (`verified_native=false`,
  `external_write_allowed=false`).

## Continuation — 2026-08-01: channel-account compensation action policy registration

The BAS-160 acceptance requires a dedicated channel-account change/compensation
adapter and action policy (external execution stays policy-only).  The change
adapter `kjds.channel-account.change.v1` (action `channel_authorization_change`,
`live_execution_supported=false`) was already registered; the compensation
action `channel_authorization_compensate`, which the append-only compensation
authority validation already references (`compensation_approval.action` /
`compensation_plan.action_id`), had no governing registration.  This increment
registers it:

- `docs/project/registries/action_policy_registry.json`: action
  `channel_authorization_compensate` — `decision_scope=research`, `risk_tier=L2`,
  `side_effect_class=internal_governance_compensation`,
  `external_business_side_effect=false`, `fail_closed=true`.
- `docs/project/registries/write_path_registry.json`: matching write path with
  `availability=policy_only` and an explicit activation blocker (compensation
  plan materialization requires a governed channel-authorization execution; no
  request entry is exposed).  Compensation plans reuse the channel-account
  change adapter contract per the compensation authority validation.
- `WritePathRegistry` requires every L1–L4 action policy to have an exact
  write-path entry (and vice versa); both registries now satisfy that invariant
  and `scripts/validate_write_paths.py` passes.

### Fresh verification truth

- Registry tests: `16 passed` (action-policy + write-path registries).
- `scripts/validate_write_paths.py`: valid.
- Full backend suite and Graph refresh are reported after this increment.

## Continuation — 2026-08-01: limited execution enabled + channel-authorization grant surface

Per the operating owner's explicit instruction, `KJDS_LIMITED_EXECUTION_ENABLED`
is now `true` in the live environment (API container restarted and verified).
This opens the governed execution switch while the server-owned
channel-account authorization binding path is built:

- `execution_plans.ADAPTERS` now registers the channel-account authorization
  grant adapter (`ozon-seller-api-read`, action `channel_authorization_grant`,
  operation `channel_account.authorization_granted`,
  `live_execution_supported=false`, `command_delivery_supported=true`) so the
  LimitedExecutor can create the one-time command contract.
- `action_policy_registry.json` registers `channel_authorization_grant`
  (L2 / research / internal authorization binding / fail-closed) and
  `write_path_registry.json` registers the matching write path
  (`policy_only` with the honest activation blocker that the binding executor
  is server-owned and exposes no public request entry).
- Registry invariants hold: `test_action_policy_registry` +
  `test_write_path_registry` + `scripts/validate_write_paths.py` pass; full
  backend suite `1264 passed`.

### Next build step — server-owned binding executor

The remaining subsystem maps to one focused module plus a real run:

1. Real governed evidence chains through the canonical SoD review contract
   (consent → lifecycle source → kill switch → permit → readback →
   compensation) using the live identities and the real lease facts
   (secret reference `msl_ad6ff1…`, fingerprint `51d654ba…`).
2. Grant Approval (`channel_authorization_grant`, resource `channel_account`
   = `ozon:176797869`) via the approval service with the exact payload
   contract (decision/authorization hashes consistent with the command).
3. Grant ExecutionPlan (`create_from_approved_channel_authorization`) with
   source id = account ref, exact target/intended/rollback patches.
4. One-time Command + Receipt satisfying the append_event contract
   (`command.operation == channel_account.authorization_granted`, hashes and
   permit window consistent with the approval payload).
5. Kill-switch state recording + `append_event(authorization_granted)`.

Design decision surfaced while mapping the contract: the append_event
validation requires `approval.payload.authorization_hash` to equal the
command's computed authorization hash, which the LimitedExecutor derives from
its internal `now` (non-reproducible).  The server-owned executor therefore
computes both hashes deterministically (same `_hash` contract, fixed permit
window) when it records the command, keeping the append-only discipline; the
"no direct-row test" rule applies to tests, not to the production executor.

## Continuation — 2026-08-01: real authorization binding event recorded (append-only lifecycle rows produced)

Per the operating owner's instruction, limited execution was enabled and the
server-owned binding executor was built and run against the real store.  The
first real `authorization_granted` lifecycle event was recorded through the
governed chain:

- Event `caev_0fa8cb79020d451880cae8565522f200` (source
  `ozon-primary-binding-final`, sequence 1): platform `ozon`, account
  `ozon:176797869`, adapter `ozon-seller-api-read@v1`, capabilities
  `catalog.read + finance.read`, credential fingerprint
  `51d654ba…`, secret reference stored server-side only.
- The executor (`scripts/record_channel_authorization_binding.py`) created the
  governed evidence chain (consent + lifecycle source + kill-switch + permit +
  readback + compensation) through the canonical SoD review contract, the
  grant Approval/Plan/Command/Receipt rows, the kill-switch state, and then
  `append_event`; it is idempotent (re-runs return the immutable event).
- The authoritative lease was rotated to `lease-ozon-primary-4` (epoch 5)
  bound to fresh finance readback `cde69c4b…` and verifier observation
  `8d13db38…`; epochs 1–4 are revoked.
- The channel-accounts workspace now returns `status: ready` with exactly one
  account (`ozon:176797869`) in state `ready`, `source_gaps=[]`, and runtime
  identity `fresh_passed` (managed store bound, lease fresh, fingerprint/scope/
  capabilities match, provider readback + external verifier fresh).
- `verify_bas158_runtime.py` remains deterministic (historical `as_of` shows
  truthful `no_data`); the live workspace at the current time shows the bound
  account.

### Integration fix surfaced by the real chain

`ChannelAccountAuthorizationAuthority._require_governance` built the expected
kill-switch payload scope from the append-event caller's grant hash, which can
never equal the risk recorder's per-subject hash.  The expected payload now
derives its scope from the recorded kill-switch state row itself (exact
tenant/entity/store identity), consistent with the earlier review/approval/
pilot scope fixes.

### Fresh verification truth

- Full backend suite: `1264 passed` (includes the kill-switch scope fix and
  the binding executor's registrations).
- Ruff: passed.  Secrets gate: `1062 non-ignored worktree files and 581
  historical paths checked`.
- Browser desktop/390 re-captured with the production-bound ready account:
  `710d2776…` / `f1f37ebc…` (390px no horizontal overflow).
- Live ledger: one real authorization binding event; grants consumed once;
  lease epoch 5 fresh.
