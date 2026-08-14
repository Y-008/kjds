# BAS-186 Governed Editing Blueprint and FFmpeg Execution

## Status

- Work item: `BAS-186`
- State: `IN_PROGRESS`
- Scope: exact25 feature slice under Lane J
- Provider admission: runtime-owned local `ffmpeg` only for `media.video_render`
- Engineering status: internal execution and durable readback validated
- Production admission: `false`
- Representative live customer render: not run
- Remotion: `watch_not_admitted`
- External write: `false`
- Listing eligibility: `false` until existing Media QA and delivery-manifest authorities pass
- G1: not run

This Evidence is an engineering contract and test receipt. It is not a customer
result, RFQ, quotation, production execution, revenue, or business-readiness
claim. The isolated automated-commerce/RFQ worktree is outside this slice.

## Authority Boundaries

`GovernedEditingBlueprintWorkspace.process(principal, store_ref, job_ref)`
accepts no caller-supplied tenant, entity, authority, raw blob, prompt, provider
command, or result state. Production runtime composition injects one
`GovernedMediaJobWorkspace`, the existing `ScopedProductContentAuthority`,
`MediaWorkbenchService`, and a fixed local `FfmpegMediaWorker` adapter.

The module does not create a second truth source:

- `GovernedMediaJobWorkspace` owns Job headers, attempts, events, worker input,
  terminal state, result receipts, and same-connector readback.
- `ScopedProductContentAuthority` derives source receipts from current-scope
  Product, approved ContentAsset, rights metadata, and scoped Evidence.
- `EvidenceService` owns immutable worker-input, transition, and artifact bytes.
- `ContentAsset` and `MediaWorkbenchService` own generated media and QA handoff.
- Delivery manifests continue to consume exact ContentAsset generation seals;
  BAS-186 does not grant QA, Listing eligibility, or platform-write authority.
- Legacy `MediaExecutionRow` is not a Job truth source and uses a separate
  legacy Evidence source that cannot impersonate governed Job artifacts.

## Worker Input and Source Receipt

Migration `20260809_0098_media_job_result_readback` adds the immutable
`media_job_worker_inputs` relation. App and PostgreSQL validate the same exact
13-field payload, ref/hash bounds, unique arrays, and blueprint/render matrices.
Only the reserved `governed-media-job-worker-input` Evidence adapter may create
the matching source/ref/blob/metadata seal.

`ScopedProductContentAuthority.read_editing_source` rechecks server current
scope, reads the immutable worker input, resolves approved ContentAssets and
their Evidence under the exact tenant/entity/store/current-authority binding,
requires one canonical Product, validates rights, and separately scope-checks
subtitle Evidence. The source receipt contains refs, hashes, safe timelines,
target channels, and scope bindings only; it does not contain media bytes or
provider-private payloads.

## Deterministic FFmpeg Handoff

- Scenes are ordered, contiguous, non-overlapping, bounded, and duplicate-free.
- Every scene binds one approved source ContentAsset and one scoped caption
  Evidence ref. Every declared source is consumed; no first-source fallback is
  permitted.
- The fixed FFmpeg adapter compiles scene `trim`/`setpts`, per-scene captions,
  deterministic `concat`/`fade`/`xfade`, and the exact governed audio/subtitle
  inputs into the command graph for all three output ratios.
- Blueprint and render-plan hashes contain governed refs, hashes, versions, and
  safe flags only. The execution boundary independently recomputes the exact
  render-plan SHA before reading bytes or invoking FFmpeg.
- `media.video_render` is bound to the server-owned local FFmpeg descriptor:
  `internal://local-ffmpeg-renderer-v1`, its fixed binding/protocol,
  deterministic zero-external-call and zero-cost contract. Tenant-enrolled
  FFmpeg connectors are future vocabulary and are not admitted by this slice.
  Gateway checks the exact descriptor before Job submission, Editing checks it
  again before claim, and runtime requires the concrete `FfmpegMediaWorker`
  implementation. Remotion remains blocked pending an independent license and
  measured-gap Gate.
- Provider attempt claim remains the canonical MediaJob transition and uses
  the same scope-authority advisory lock as grant rotation/revoke.
- The production worker CLI requires explicit Job, actor, and store refs and
  routes to the runtime-owned governed workspace; it never polls or creates a
  legacy `MediaExecutionRow` for this path.
- The worker writes deterministic GENERATED ContentAssets and reserved
  `kjds-ffmpeg-media-worker` Evidence in one scoped transaction.
- Generated assets remain `listing_eligible=false`; no Fact, Finance, Approval,
  Permit, Pilot, Listing, Outbox, procurement, payment, or external system write
  is created.

## Crash and Result Readback

The immutable `media_job_result_receipts` relation binds the terminal event,
scope/authority, tool version, provider, connector, connector binding,
ContentAsset, and artifact Evidence. The Job authority lock, fresh-current
check, Job row lock, terminal chain, ContentAsset generation seal, and result
receipt are one database transaction. A deferred PostgreSQL trigger requires
exactly one receipt for each governed worker terminal event. Rotation/revoke
that wins the authority lock leaves terminal events, transition Evidence,
ContentAsset receipt seals, and result receipts unchanged. `SUCCEEDED` requires
the exact governed artifact chain. This slice does not connect an independent
typed provider-result authority, so `FAILED` and `UNKNOWN_OUTCOME` remain state
vocabulary only and are not admitted as result receipts or terminal events.
`CANCELLED` cannot be represented as a result receipt.

After a crash, a new worker may replay only an atomically committed terminal
receipt and its exact scoped ContentAsset/Evidence chain, without rerender. An
orphan artifact or ContentAsset lacking the unique receipt seal is rejected and
cannot be attached or repaired into success. A recent active `DISPATCHED`
attempt remains blocked as `provider_attempt_in_progress`; it is not rewritten
to `UNKNOWN_OUTCOME` by a concurrent worker. A timer, local executor exception,
or absent receipt cannot self-certify `FAILED` or `UNKNOWN_OUTCOME`; those cases
remain blocked as `provider_attempt_outcome_unverified`, with no second dispatch,
retry, failover, terminal event, or fabricated result receipt. Only an existing,
independently durable typed provider receipt could enable that future path; no
such producer is connected or claimed verified in BAS-186. Existing untyped
`FAILED`/`UNKNOWN_OUTCOME` rows are rejected on read.
Populated 0098 downgrade fails closed with `SQLSTATE 55000`.

Every admitted public database writer takes the shared
`kjds-media-jobs-0098-result-readback` advisory transaction lock before scope,
table, Job, Evidence, or idempotency locks. Upgrade and downgrade take the
exclusive form of the same lock before catalog or preflight work. Real
two-connection tests cover submit-first/upgrade-first and
render-result-first/downgrade-first ordering. Both downgrade races terminate
without `40P01` or timeout, fail closed with `55000`, preserve the 0098 head and
catalog, and allow only the exact nine-domain delta of one atomic successful
render result.

## Verification State

Current focused receipts after the exact25 red-team closure and before the new
byte freeze:

- Commander, Evidence, media registry/connector, and Job suites: `142 passed`
- Workbench suite: `20 passed, 1 skipped` (the skipped live executable case is
  not reported as pass)
- Worker, Editing Blueprint, runtime composition, and complete production
  editing-source authority/API slice: `56 passed`. The three authenticated API
  cases explicitly use a test kill-switch seam so they exercise store/entity
  fail-closed behavior without consulting an unrelated configured database.
- Real PostgreSQL 0096→0097→0098 lifecycle, shared-advisory writer/migration
  serialization, atomic result, target-attributed 23514 attack matrix,
  deferred conservation, empty/populated downgrade and replay suite:
  `74 passed`
- Active workstream assignment/control invariants: `20 passed`
- Ruff and Python compile checks: pass for the changed implementation and tests
- Registry and fixture JSON parsing: pass
- Secret scan: `1456` non-ignored worktree files and `1577` historical paths
  checked
- Worktree and cached diff checks: pass; staged path count is zero

The PostgreSQL suite ran against a dedicated BAS-186 container on local port
`55439`, with the historical 0095/0096 role contracts provisioned exactly. It
was not skipped and did not use the automated-commerce database.

During implementation, migration `0098` was accidentally truncated twice (one
zero-byte incident and one 2044-byte grep-output incident). All pre-incident PG
and candidate receipts were invalidated. Recovery used the protected CPython
3.12 artifact whose original anchor SHA was
`8B7D1F206CBBF9EB984B219AED3DD3657421528037D7E460390366C1F7C99360`
and the newer 04:03:18 artifact plus independently equal 39-operation upgrade
and downgrade transcripts. The recovered source was then replayed with every
post-snapshot fix, compiled, and the complete lifecycle above rerun on a fresh
database. No `.pyc` or private recovery artifact is part of this feature set.

The prior exact23 v2 candidate
`E416D48B7644020CEF3C30183E8924C1EFF7389539DAB92ECF08477A34C52DA1`
is superseded and must not be staged or committed. Its mechanical freeze was
valid, but independent semantic review found first-source-only rendering,
non-atomic terminal/asset/receipt writes, an unreachable governed worker entry,
and missing execution-boundary render-plan revalidation. The current bytes
close those findings and require a new candidate.

Not claimed:

- No representative customer media, live connector, external platform write,
  production throughput/cost benchmark, independent human QA, or G1 was run.
- No feature candidate, feature commit, release candidate, or release commit is
  authorized by this Evidence alone.

## Required Next Gate

Run the complete exact25 focused group, JSON, secret, Ruff, compile, and
diff-check gates; remove the run-owned PostgreSQL container; freeze all exact25
bytes for six seconds with staged0 and a complete outside-WIP inventory. Only
after two independent current-byte signoffs may an atomic feature commit and a
later independent BAS-186 release exact3 be created.
