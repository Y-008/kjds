# BAS-183 Governed Durable Media Jobs

## Decision

BAS-183 phase A introduces one durable media-job truth: an immutable header,
an append-only event stream, and exact Evidence links. It does not expose HTTP,
SSE, runtime wiring, provider dispatch, usage settlement, or an OpenAI-compatible
surface. Those remain separate phases with separate leases.

## Authority Boundaries

- `MediaConnectorRegistry` remains the connector identity, capability, and
  currentness authority.
- `EvidenceService` remains the immutable content and provenance authority.
- `ContentAsset` remains the artifact and QA authority.
- COM-002 remains the entitlement, balance, reservation, and settlement
  authority. This slice creates no substitute balance or usage ledger.
- `DurableImageDispatchPort` remains the BAS-182 worker protocol. Phase A only
  provides a fail-closed adapter seam; `claim` and `record` reject because
  settled entitlement and provider wiring are not admitted.

## Persisted Contract

- `media_jobs` is an immutable exact-scope header. It binds tenant, entity,
  store, current authority hash, actor-derived request fingerprint, tool,
  connector binding, idempotency, and request Evidence. The reserved request
  Evidence blob hash must equal the canonical request hash stored by the job.
- `media_job_events` is append-only and ordered by per-job ordinal. The database
  locks the header, validates exact scope, previous hash, transition matrix, and
  strict public projection before accepting an event. Event seals include the
  complete immutable event contract, and terminal Evidence content must equal
  the canonical public projection it attests.
- `media_job_evidence_links` binds request, terminal artifact, usage
  authorization, or usage settlement Evidence to the same exact job identity.
  A deferred PostgreSQL conservation trigger requires exactly one
  `artifact_terminal` link for every terminal event.
- request body and prompt content exist only in reserved immutable Evidence.
  Job and event projections contain references, states, ordinals, and safe
  reason codes, not prompt text or provider error bodies.

## State and Safety

The public state vocabulary is `QUEUED`, `DISPATCHED`, `RUNNING`, `UPLOADING`,
`SUCCEEDED`, `LOGIN_REQUIRED`, `LIMITED`, `FAILED`, `CANCELLED`, and
`UNKNOWN_OUTCOME`. Header state is never mutated; the latest validated event is
the state projection. Terminal states reject further transitions.
`LOGIN_REQUIRED` and `LIMITED` are paused/readback states, not terminal
states; they may resume through controlled `DISPATCHED`/`RUNNING` paths, while
direct terminal jumps remain blocked.

Application reads and PostgreSQL writes enforce the same state-specific safe
reason matrix. They also require `occurred_at <= recorded_at`, monotonic event
times, and a five-minute trusted-clock future tolerance. Self-consistently
resealed rows cannot bypass these checks.

Phase A admits only `QUEUED` creation and pre-dispatch cancellation. Provider
claim/record remains fail closed. In particular, no entitlement means no
provider call, and no terminal Evidence can be inferred from worker output.

## Conservation

This slice creates zero `Fact`, `FinanceEntry`, `Approval`, `Permit`, `Pilot`,
transactional outbox, listing eligibility, procurement, platform write, or
external contact action. A media-job success will not imply ContentAsset QA or
listing eligibility in later phases.

## Verification

The focused unit suite passed `34` tests. The dedicated PostgreSQL suite passed
`23` tests against a clean 0096-to-0097 replay, covering the 0097 relations and
triggers, real submit/replay/cancel, append-only mutation rejection, malformed
public projections, canonical request and terminal Evidence content binding,
five-dimensional request-Evidence metadata drift, state-specific safe reasons,
dual-time monotonicity and future tolerance, same-key concurrent winner/actor
conflict, paused-state resume and forbidden terminal jumps, deferred
terminal-Evidence conservation, and populated downgrade `55000`. Final
populated counts were `media_jobs=25`, `media_job_events=40`, and
`media_job_evidence_links=26`.

The PostgreSQL target was run-owned at `127.0.0.1:55497`; the run completed
with migration `20260808_0097`, and the run-owned database/container were
cleaned afterward. No unrelated host PostgreSQL service or container was
claimed by this phase.

No API, OpenAPI, runtime, worker, compose, COM-002, dependency, database
credential, G-1, or external system was modified or invoked by this phase-A
implementation step.
