# KJDS Active Goal Checkpoint — 2026-07-28

## Status

- Goal status: `active`; this checkpoint is a context handoff, not completion Evidence.
- Workspace: `D:\KJDS\kjds`
- Branch: `feature/batch-opportunity-mining-059`
- Baseline HEAD: `b34a3a7`
- Current release line: `0.59.0`
- Current engineering slice: `BAS-123 Native scoped Ozon official import staging`
- Next committed slice: `BAS-124 Native scoped formal Fact promotion`
- Ultimate execution remains limited to the approved `M0 → M4` implementation waves.
- The `0.59` PM/RA Release Gates, Pilot Gate, and Final Gate remain open/rejected as
  recorded in their authoritative artifacts. Start Gate approval is not Release approval.

## Original outcome

Build KJDS as a native cross-border commerce ERP and AI Agent Team, using Wuyouyishou,
Miaoshou, Mango ERP, Maozi ERP, Lizhi ERP, Linkfox and other products as capability
benchmarks rather than runtime dependencies. KJDS owns one tenant-scoped operating
kernel across:

- PIM, exact product and variant identity, Product Passport and content/media;
- Ozon market intelligence, opportunity scoring, pricing and controlled listing plans;
- OMS, sale-triggered procurement, supplier sourcing, inventory and fulfillment;
- fifteen-item landed-cost and CM3, accrual, settlement and actual-cash ledgers;
- BI, anomaly/task operations, portfolio management and store-cluster operations;
- Rules-as-Code, Evidence, lineage, RBAC/SoD, Approval, one-time Permit, Readback,
  Kill Switch and Compensation;
- a governed AI Agent Team that proposes and assists but never promotes inference to
  fact, self-approves, self-issues a Permit or bypasses platform controls.

The business success condition is not automatic listing count. It is a controlled,
evidence-bound path from real market and supply observations through exact-SKU
downside CM3, compliant content and a small Pilot to orders, returns, settlement and
reconciled actual-cash profit.

## Immutable operating boundaries

- All Ozon, supplier, purchasing, payment, advertising, inventory and price external
  writes remain closed until their exact action Gate is satisfied.
- No CAPTCHA bypass, rate-limit bypass, cookie/localStorage copying, internal API use,
  IP infringement, fake sales, fake profit, fake Supplier Offer or guessed allocation.
- Public/checkout prices remain observations, not formal supplier offers or actual cost.
- Missing or restricted sources remain `no_data`/`blocked`; never fabricate throughput.
- Pricing plans remain `hypothesis` and `not_for_sale`.
- Never modify or stage:
  - `docs/project/STRATEGY_AND_ARCHITECTURE_2026.md`
  - `docs/project/evidence/20260723_P0_CURRENT_HEAD_VERIFICATION.md`
  - `wuliu/`
  - `深入理解AI Agent(1).pdf`
  - `D:\KJDS\ozon`
  - the unrelated untracked file named `''product_type''`

## Completed slices in the current continuation

### BAS-121 — Native scoped Ozon read Pilots/Runs

- Native tenant/entity/store/grant-scoped read Pilot and Run contracts are implemented.
- Release Evidence:
  `docs/project/evidence/20260728_BAS_121_NATIVE_SCOPED_READ_PILOTS.md`
- The browser, OpenAPI, database and full test observations are frozen in that Evidence.

### BAS-122 — Native scoped ReadOnly Claims

- Claims freeze tenant/entity/store/grant/Evidence/as-of authority.
- Accepted claims remain `formal_fact=false` and `external_write=false`.
- Claim → Run → Pilot lineage is joined by scoped SQL authority.
- Migration `20260728_0064` was applied forward-only to the real database.
- Full backend result: `737 passed`; Web: `50 passed`, build green, `0` vulnerabilities.
- Release Evidence:
  `docs/project/evidence/20260728_BAS_122_NATIVE_SCOPED_READ_ONLY_CLAIMS.md`

## BAS-123 implementation already present

### Decision and documentation

- ADR:
  `docs/adr/ADR-0047-native-scoped-ozon-import-staging.md`
- `MASTER_SPEC.md` includes `BR-099`.
- `03_REMAINING_WORK_AND_PARALLEL_PLAN.md` tracks `BAS-123` as in progress.

### Database

- Migration:
  `migrations/versions/20260728_0065_native_scoped_ozon_imports.py`
- Native ImportJob rows require a complete tuple:
  `tenant_ref + entity_ref + store_ref + scope_grant_authority_sha256 +
  source_evidence_sha256 + scope_as_of`.
- Legacy rows remain all-null and are not inferred into a tenant scope.
- Content idempotency is scoped; the same file may exist independently across tenants.
- Isolated PostgreSQL verification already passed:
  - base → `0065`;
  - `0065 → 0064 → 0065`;
  - same-scope duplicate rejected;
  - cross-tenant same file accepted independently;
  - partial scope tuple rejected;
  - duplicate legacy SHA rejected.
- The real database remains at `20260728_0064` at this checkpoint. Do not downgrade it.

### Service/API

- Native authority:
  `apps/control_plane/scoped_ozon_imports.py`
- Scoped integration:
  - `apps/control_plane/imports.py`
  - `apps/control_plane/runtime.py`
  - `apps/control_plane/routers/finance_imports.py`
  - `apps/control_plane/commerce_operating_system.py`
- Official CSV/XLSX upload is staging only:
  - `formal_fact_promotion_allowed=false`
  - `external_write_allowed=false`
- The native promotion endpoint is fail-closed until BAS-124.
- Import detail, review, mapping and accrual routes preflight the authenticated
  principal, current entity and exact authorized store.
- Missing entity must fail before file read or database mutation.

### Web

- Commerce OS includes the `Ozon 官方导入 staging` projection and explicitly displays
  that formal promotion and external writes are false.

### Tests

- New contract suite:
  `tests/test_scoped_ozon_imports.py`
- Existing API and Commerce OS tests were updated to use scoped import authority.
- Focused backend and Web suites have passed.
- A final full backend run was started in the background with logs:
  - `output/pytest/bas123-full-20260728-0950.stdout.log`
  - `output/pytest/bas123-full-20260728-0950.stderr.log`
- Last observed progress before this checkpoint: `38%`. Read the process/log to obtain
  the real final result; never infer the result from the expected count.

## Exact BAS-123 resume sequence

1. Read the full Pytest process/log and record the actual result.
2. Run:
   - `uv run ruff check .`
   - `uv run python scripts/verify_secrets.py`
   - `git diff --check`
   - Web `npm ci`, `npm test`, `npm run build`
   - `uv run python scripts/export_openapi.py`
3. Before touching the real database, freeze:
   - Alembic current revision;
   - the existing ImportJob ID/SHA/Evidence/status/type/scope-null tuple;
   - Claim, Pilot, Run, Evidence, lineage, Catalog and handoff counts/hashes.
4. Apply only real forward migration `0064 → 0065`; never downgrade the real database.
5. Verify the legacy ImportJob remains all-null and every frozen row/count/hash is
   unchanged.
6. Rebuild API, media-worker and Web, then wait for PostgreSQL/API/media-worker/Web to
   become healthy.
7. Verify live API:
   - anonymous import/detail/review `401`;
   - exact-store authenticated reads;
   - cross-store `403`;
   - missing entity `422` before any mutation;
   - legacy imports are not exposed as tenant resources;
   - Commerce OS returns scoped `no_data`, zero native imports, no formal promotion and
     no external write.
8. Capture desktop and `390px` Commerce OS browser Evidence, with no overflow and no
   console error.
9. Write:
   `docs/project/evidence/20260728_BAS_123_NATIVE_SCOPED_OZON_IMPORT_STAGING.md`
10. Link Evidence from `MASTER_SPEC.md`, mark BAS-123 engineering complete in the
    Remaining Plan, then continue immediately to BAS-124.

## New horizontal requirement — KJDS Agent Harness

The user requires a live edge-of-screen Agent status instrument, a persistent TODO
contract and an execution/dependency Graph. This is not a cosmetic progress widget.

### Authority model

- Status must come from real external observations: test processes, static checks,
  Git state, migration revision, database probes, container health, API responses,
  browser layout/console/network, queue state, Evidence integrity and Gate decisions.
- Every observation carries:
  `source + scope + observed_at + freshness + verifier_version + input_hash +
  result_hash + authority + Evidence/trace reference`.
- Model narration is `reported`, never `verified`.
- Plan state and observed state remain separate.
- A changed upstream input invalidates dependent downstream observations.

### TODO contract

Each item freezes:

- original objective and user constraint;
- scope and owner;
- dependency IDs;
- verification condition and verifier;
- observed state (`pending/running/blocked/passed/failed/stale/no_data`);
- blockers and missing Evidence;
- next safe action and workspace link;
- timestamps, SLA and stable fingerprint.

Only a verifier may move an item to `passed`; the model cannot self-certify.

### Execution Graph

The graph must expose causal/dependency edges, not merely navigation:

`change → static checks → tests → migration → image → container → API → browser →
Evidence → Gate`.

It must also represent operating loops:

`observe → match → evaluate → content → approval allocation → independent approval →
one-time Permit → publish/readback → order → procurement → fulfillment → settlement →
actual-cash CM3 → scale/stop`.

### Graph engineering and project system

`Graph` is a first-class KJDS engineering and operating capability, not one visual
component and not a synonym for a graph database. The first implementation uses a
canonical node/edge contract and the existing PostgreSQL authority; a separate graph
database is introduced only after measured query/scale requirements justify its
operational cost.

The Graph system has seven connected projections:

1. **Project Graph**
   - Goal, milestone, release, workstream, task, owner, SLA, dependency, blocker and
     acceptance criterion.
   - Supports multiple projects while preserving one canonical goal contract per run.
2. **Requirements Graph**
   - User objective → JTBD → requirement → invariant → ADR → API/schema/UI contract →
     acceptance scenario.
   - A requirement is not covered merely because a similarly named page or module
     exists.
3. **Engineering Graph**
   - Repository, module, symbol, migration, API route, event, test, image, container and
     deployment.
   - Edges come from parsers and runtime manifests where possible; model-inferred edges
     remain explicitly `inferred`.
4. **Runtime/Verification Graph**
   - Change/input hash → verifier run → observation → artifact → environment → result.
   - Upstream hash or environment changes mark downstream observations `stale`.
5. **Evidence/Decision Graph**
   - Source → immutable Evidence → lineage → formal Fact/observation → inference →
     decision → approval → Permit → execution → Readback/Compensation.
   - Authority class and scope are mandatory on every promotion edge.
6. **Commerce Operating Graph**
   - Tenant/entity/store → Product/exact Variant → supplier option → landed cost →
     Listing/Pilot → order/return → settlement → actual-cash contribution → portfolio
     decision.
   - Estimated, accrual, settlement and actual-cash views remain separate.
7. **Authority/Risk Graph**
   - Principal, role, grant, tenant/entity/store scope, Evidence authority, policy
     envelope, separation-of-duties conflict, Kill Switch and external-write boundary.
   - There is no path from recommendation to external execution without the required
     independent authority nodes.

Canonical Graph objects include:

- `GraphProject`: project identity, goal contract, tenant scope, lifecycle and baseline;
- `GraphNode`: stable typed identity, authority, source, scope, version and content hash;
- `GraphEdge`: typed direction, derivation method, effective interval, confidence and
  Evidence reference;
- `GraphObservation`: verifier result bound to the exact node/edge/input/environment;
- `GraphSnapshot`: deterministic `as_of` projection with snapshot hash;
- `GraphDiff`: added/removed/changed/stale nodes and affected downstream paths;
- `GraphPolicy`: allowed node/edge types, promotion rules, freshness and fail-closed
  behavior.

Initial project workspaces:

- `/agent-control`: compact real-observation status rail and current critical path;
- `/goal-todo`: objective, constraints, verifier-owned TODOs, blockers and next actions;
- `/project-graph`: cross-project milestones, dependencies, owners and Release Gates;
- `/engineering-graph`: requirement-to-code-to-test-to-runtime traceability;
- `/evidence-graph`: source/Evidence/fact/decision/execution lineage;
- `/commerce-graph`: product/supply/profit/listing/order/settlement operating chain;
- `/authority-graph`: grants, approvals, permits, external-write paths and SoD conflicts.

Every workspace requires server-derived counts and drilldowns, deterministic `as_of`,
fresh/stale/no_data/error/forbidden states, desktop and `390px` acceptance, and a link
back to the exact immutable observation or Evidence. A graph may show an inferred edge
for exploration, but inferred edges cannot satisfy a Gate, establish a Fact or authorize
an external action.

The first delivery wave proves one vertical path end to end:

`BAS-123 requirement → ADR-0047 → migration 0065/service/routes/tests → Pytest run →
real DB revision → rebuilt image/container → live API → browser screenshot → Evidence →
Release-plan status`.

Only after that path is real does the same graph contract expand across M0–M4 and
commerce operations.

### Status bar

- The compact status surface shows only changed, failed, blocked, stale or next-critical
  facts.
- Drilldown exposes the immutable observations and Evidence.
- It must distinguish `running` from `passed`, and `no_data` from success.
- Browser checks include desktop and `390px`, accessibility, overflow, console and
  request failures.
- Verifiers themselves are versioned and tested with fault injection/negative cases to
  reduce reward-hacking and false-green risk.

### Proposed implementation seam

Implement this after BAS-123 as a native `Agent Control Plane` deep module:

- append-only `HarnessObservation`;
- versioned `VerifierRegistry`;
- `GoalContract` and `GoalTask`;
- derived `ExecutionGraphSnapshot`;
- server-computed compact `AgentStatusProjection`;
- authenticated tenant/entity/store-scoped read APIs;
- a persistent dashboard status rail, TODO workspace and Graph drilldown;
- no new external write authority.

## BAS-124 next semantic boundary

Current global Fact APIs and Product lookup are not acceptable for native promotion.
BAS-124 should add scoped Fact and PromotionRun authority with:

- complete tenant/entity/store/grant/Evidence/as-of tuples;
- exact scoped Product/SKU mapping;
- independently reviewed current source Evidence and finance review;
- scoped uniqueness and idempotency;
- no Claim-to-Fact shortcut;
- no external write authority;
- authenticated list/detail/promotion with anonymous `401`, cross-scope `403`, bad
  Evidence and deterministic as-of tests.

## Working rules for the next context

- Read `AGENTS.md` before action.
- Preserve the dirty integrated worktree; do not reset or discard.
- Use `apply_patch` for source edits.
- Use `KJDS_DATABASE_URL` for Alembic operations.
- Use a unique workspace `--basetemp` for Pytest because the default Windows Temp
  directory can produce ACL failures.
- Do not claim green, healthy, migrated, rendered, profitable or published until an
  external verifier has observed it.
- Keep the user informed at least once per minute during long-running work.

## Authoritative continuation update — 2026-07-29

This later section supersedes the earlier BAS-123/BAS-124 resume boundary. Do not redo
completed BAS-123 through BAS-135 work.

### Completed engineering slices

- BAS-123 through BAS-133 remain completed as recorded in Master/Plan/Evidence.
- BAS-134 `Verifier-owned Authority Workflow Topology` and BAS-135
  `Graph Dependency Re-verification Recovery` are
  `DONE_ENGINEERING`; see:
  `docs/project/evidence/20260729_BAS_134_AUTHORITY_WORKFLOW_TOPOLOGY.md` and
  `docs/project/evidence/20260729_BAS_135_GRAPH_DEPENDENCY_REVERIFICATION.md`.
- Master is version `8.36`; Remaining Plan is version `9.27`.
- Real database revision remains forward-only at `20260728_0070`.

### BAS-134 live truth

- The running `default / ozon-primary` API identity inventory contains six scoped
  actors and can form exactly one four-party chain:
  `r0-requester → kjds-owner-lunar → r0-risk → r0-admin`.
- The running Web is still `legacy`; Supabase Web user binding count is `0`.
- `task-bas134-verifier-tests` is `passed/fresh`.
- `task-bas134-authority-workflow-topology` is `blocked/fresh` with
  `web_auth_mode_not_supabase`.
- The exact content-addressed observation is:
  `output/graph/bas134-authority-workflow-topology/7f1918c507a5f6b232188ef5387c4e55b4cc6f849637eef616aadd741c6cdbd6.json`.
- Latest topology Observation ID:
  `obs_8c426ee5add9768bc98cdfb6a36a298f`.
- Source/review/grant counts remained `0/0/0` before and after observation.
- Graph totals after BAS-134:
  `32 tasks / 110 nodes / 123 edges / 164 observations / 77 bindings`.
- Full backend: `796 passed, 9 warnings`.
- Web after `npm ci`: `61 passed`, `35/35` build, `0` vulnerabilities.
- PostgreSQL/API/media-worker/Web are healthy.
- Desktop/390 and Project/Engineering/Authority/TODO browser Evidence is frozen under:
  `output/playwright/release-0.59.0/bas134/` and
  `output/playwright/release-0.59.0/bas135/`.

### BAS-135 dependency recovery truth

- The first fault replay correctly made BAS-133/134 stale after the BAS-132 verifier
  input changed, but exposed that downstream observations reused old idempotency
  inputs.
- The observer now hashes the complete BAS-128/132/133/134 direct dependency DAG into
  every emitted Observation input.
- The second real replay appended new observations and restored:
  - BAS-132 verifier tests `passed/fresh`;
  - BAS-133 verifier tests and live intake `passed/fresh`;
  - BAS-134 verifier tests `passed/fresh`;
  - BAS-134 runtime topology `blocked/fresh` only for
    `web_auth_mode_not_supabase`.
- Latest scheduler runtime Observation:
  `obs_42bdd8f2a815356d01b85967f49f2bb4`.
- BAS-135 verifier-owned Task:
  `task-bas135-verifier-tests = passed/fresh`,
  Observation `obs_1210b08d5c08d84dc9821674778a11d9`.
- The real Windows missing-task exception is now classified as the stable secret-free
  missing-task condition; no Task Install was run.

### Current blockers and next safe order

1. Account owner + identity engineering must provision Supabase Web auth and bind four
   different real users to subject, owner, reviewer and recorder actors. Do not add a
   role switch, synthesize users or record raw user IDs in Graph/Evidence.
2. Obtain a new external BAS-134 topology Observation. Only a fresh passed observation
   may advance its TODO/Graph nodes.
3. BAS-040 still requires a scheduler-visible dedicated monitor credential, explicit
   Windows Task Install and three consecutive result-0 completions. Do not borrow
   operator/admin credentials.
4. Only after the identity topology is real may the independently authenticated owner
   submit real authority source Evidence, followed by a different reviewer and a
   different compliance/admin recorder. Do not create synthetic source/review/grant
   rows for acceptance.
5. Refresh monitor-owned operating-subject, scope-authority and M0→M4 observations.
   Current M0→M4 observations are stale; Release `0.59` remains `REJECTED`.

### Immutable boundary at this checkpoint

- `external_write_allowed=false`
- `role_switch_allowed=false`
- `grant_created=false`
- no Approval or Permit was created
- Release/Pilot/Final Gates are not accepted
- keep this Codex goal `active`; do not mark complete until the full real operating
  loop and all authoritative Gates are satisfied

## Authoritative continuation update — 2026-07-29 BAS-136

This section supersedes the BAS-135 scheduler blocker state above. Do not redo
BAS-123 through BAS-136.

### BAS-040 is now externally accepted

- The ignored `.env` contains one exact-scope `r0-requester/operator` readiness
  credential and a distinct
  `kjds-monitor-scheduler-059/monitor` credential.
- The real `ControlPlaneOnly` preflight passed control plane, operations readiness,
  Evidence integrity and Agent Gate observation.
- `\KJDS-Evidence-Integrity-Health` is installed with exact
  `15m / 5m / IgnoreNew`, correct working directory and a secret-free action.
- The Windows Task Scheduler Operational channel is enabled.
- Three explicit native task executions returned result `0`.
- The Task audit reads Event `201` action-completion ResultCode, returns
  `status=accepted`, and reports `consecutive_successes=3`.
- Event `102` is no longer incorrectly treated as carrying a process exit code.
- `task-bas040-health-scheduler-deployment` is `passed/fresh`,
  Observation `obs_867f9f0bd1141506a8ede8792b285ea2`.
- Latest scheduler artifact:
  `output/graph/bas132-health-scheduler/5e0ed3f84f1f6d86c5055a364b7f4754894cfa19de75658a03e85f5f3795feaa.json`,
  SHA-256
  `ec65f7672f5b8465ace9fcbd7e411891682365ef5914725c52c30c6684645001`.

### Supabase bootstrap is real but incomplete

- A new healthy Free project named `KJDS-059` exists:
  ref `wqwjdxcpzzobptvholcy`,
  URL `https://wqwjdxcpzzobptvholcy.supabase.co`.
- The ignored `.env` contains the project ref, URL, publishable key and local
  database password; no secret is recorded in docs or desktop notes.
- Email auth and email confirmation are enabled; anonymous auth is disabled.
- Site URL is `http://localhost:3000`; automatic exposure of new tables is off;
  automatic RLS is on.
- The real Supabase Auth user inventory is still `0`.
- Therefore Web remains `legacy`, `KJDS_WEB_USER_ACTORS_JSON` remains empty and no
  synthetic user, raw user ID or role switch was created.
- `task-bas134-authority-workflow-topology` remains `blocked/fresh`,
  Observation `obs_4c3d58a056e11172be602265014c5b1e`.

### Current canonical truth

- Master `8.37`; Remaining Plan `9.28`.
- Database revision `20260728_0070`.
- `32 tasks / 110 nodes / 123 edges / 184 observations / 77 bindings`.
- `25 passed / 5 blocked / 2 no_data / 0 stale`.
- Evidence `67`; scope-grant events `0`; Approvals `0`.
- BAS-040 `passed/fresh`; BAS-134 `blocked/fresh`.
- Release `0.59` remains `REJECTED`.
- `external_write_allowed=false`.
- Evidence:
  `docs/project/evidence/20260729_BAS_136_SCHEDULER_ACTIVATION_AND_SUPABASE_BOOTSTRAP.md`.
- Desktop no-secret handoff:
  `C:\Users\Lunar\Desktop\KJDS配置记录_20260729.md`.

### Next safe order

1. Obtain four independently controlled real Supabase Auth users for
   `r0-requester`, `kjds-owner-lunar`, `r0-risk` and `r0-admin`.
2. Store only their non-secret UUID-to-actor bindings, set
   `KJDS_WEB_AUTH_MODE=supabase`, recreate Web and externally observe a passed
   BAS-134 topology.
3. Use the four independent sessions for owner source Evidence, independent
   review and compliance/admin recording; do not synthesize rows.
4. Continue M0→M4 only from those new external observations and real first-party
   operating Evidence.

## Authoritative continuation update — 2026-07-29 four-party Supabase activation

This section supersedes only the zero-user/legacy/BAS-134-blocked state in the
BAS-136 update above. Do not redo the scheduler, Supabase project bootstrap or
the four user creation.

### Four real project Auth identities now exist

- The account owner explicitly authorized creation and record retention.
- Four distinct auto-confirmed Supabase Auth users exist for:
  `r0-requester`, `kjds-owner-lunar`, `r0-risk`, `r0-admin`.
- Their identifiers use the RFC-reserved `kjds059.example.com` subdomain. They
  are independently authenticated Supabase users, not external mailboxes; no
  confirmation message was sent to a third party.
- Each user has a different strong password and completed a direct Supabase
  password-token exchange with HTTP `200`.
- Raw UUIDs and passwords exist only in the ignored local `.env` and the
  current-Windows-user DPAPI encrypted desktop backup. Graph/Evidence/docs
  contain only actor names and UUID hashes.
- `r0-risk` has `risk + approver`; it is distinct from the
  `r0-requester / operator` subject.
- All four actors have explicit `default / ozon-primary` scope.

### Web and BAS-134 are now externally accepted

- `KJDS_WEB_AUTH_MODE=supabase`.
- `KJDS_WEB_USER_ACTORS_JSON` has four UUID-to-actor bindings.
- API and Web were recreated; PostgreSQL/API/media-worker/Web are healthy.
- Real `r0-requester` Web login returned `303 → /`.
- Authenticated `/auth/authority-topology` returned:
  HTTP `200`, `state=passed`, four bindings, API/Web chain ready, no blockers.
- The external Graph observer now establishes that real login session before
  reading the secret-free topology; no credential enters its artifact.
- `task-bas134-authority-workflow-topology` is `passed/fresh`.
- Observation:
  `obs_e3029ad8452afd294f20ac93972fecdc`.
- Artifact:
  `output/graph/bas134-authority-workflow-topology/4dfc79fc1f4f09a8f6302b72835a245beb60353e1993a2fbc5dd6f12a80a9c79.json`.
- Artifact SHA-256:
  `8724a042c910f3e5bdeedd55da6a6d05966d8d57a34f8975f2f9fe06fda88d10`.

### Current canonical truth

- Master `8.38`; Remaining Plan `9.29`.
- Database revision `20260728_0070`.
- `32 tasks / 110 nodes / 123 edges / 204 observations / 77 bindings`.
- `26 passed / 4 blocked / 2 no_data / 0 stale`.
- `77` verified nodes.
- BAS-040 and BAS-134 `passed/fresh`.
- M0 current authority and scope authority remain `no_data`.
- M1–M4 remain blocked by missing real downstream facts.
- Evidence `67`; scope-grant events `0`; Approvals `0`.
- workspace remains `blocked`.
- Release `0.59` remains `REJECTED`.
- `external_write_allowed=false`.
- Desktop no-secret record:
  `C:\Users\Lunar\Desktop\KJDS配置记录_20260729.md`,
  SHA-256
  `54e16752524832ae874d4472512e6e654f992cd63a76dd40b747053aa35250ca`.
- Desktop DPAPI encrypted credential backup:
  `C:\Users\Lunar\Desktop\KJDS-Supabase-Auth-Credentials-20260729.clixml`,
  SHA-256
  `a48069d6e94f8afc34b1554743bbf4af7a0c267a0ea909b50cf944ad98304cbb`.

### Next safe order

1. Use the authenticated `kjds-owner-lunar` session to submit real authority
   source Evidence; do not synthesize it.
2. Use the distinct `r0-risk` session for independent review.
3. Use `r0-admin` for compliance/admin recording and zero-write preflight.
4. Only then admit the current scope authority and continue M0→M4 from new
   external observations. Keep all Ozon/supplier/payment/ads writes closed.
