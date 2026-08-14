# BAS-184 Commander Tool Gateway Engineering Evidence

## Scope

This slice adds an internal Commander-to-MediaJob intake contract. It does not add an API,
router, runtime composition, provider dispatcher, database migration, commerce action, or
external write. The only admitted operation is durable Job intake with safe public projection.

## Authority and brief binding

- `GovernedMediaJobWorkspace.current_scope()` derives tenant, entity, store, current authority,
  and subject from the server authority port and authenticated principal.
- `AgentHarnessService.compile_campaign_brief()` binds that exact scope, its canonical binding
  hash, and the governed graph snapshot into the brief content hash.
- Job intake resolves authority once before preparation and again inside the transaction after
  the idempotency lock. It compares the fresh scope with the initial scope, then validates every
  brief scope field, binding hash, content hash, reference, and request mirror before Evidence,
  Job, Event, or link creation.
- Rotation, revocation, cross-entity composition, and jointly re-signed scope drift fail closed
  with zero durable residue.

## Safe durable request

The immutable request Evidence stores only the contract id, tool and contract versions,
project/brief/connector references, canonical hashes, reference count, provider identifier, and
safe reason codes. Campaign text, prompt text, provider-private response bodies, inline blobs,
data URIs, credentials, and raw tool input objects are not persisted in the request Evidence.

Input validation recursively rejects the registry-frozen sensitive key set, provider-private/raw
body aliases, credential-shaped values, embedded raw JSON bodies, data URIs, and inline
base64-like bodies before Job submission. Opaque references must satisfy an explicit reference
format and do not bypass encoded-body detection. Errors use stable reason codes and do not
reflect rejected values.

## Immutable descriptor and replay

Each Job request seals the registry hash, tool name/version, capabilities, engineering cost
ceiling, output contract, provider, connector reference, and connector binding. Historical reads
reconstruct the currently registered descriptor and compare it with the immutable historical
seal. A legitimate registry v2 cannot relabel a v1 Job; the read fails closed instead.

An exact idempotency replay validates the request Evidence and event chain and returns the same
durable projection. Provider adapters must first call the transactional attempt claim; only a
`QUEUED` Job can atomically append the sole `DISPATCHED` winner. The claim transaction acquires
the same scope-authority advisory lock used by submit/cancel, revalidates current authority while
holding it, and only then locks the exact Job row and appends the event. A simulated provider attempt
that persists `UNKNOWN_OUTCOME` and then loses its response is replayed through a new workspace
and a new adapter over the same durable database. The restarted adapter inherits no in-memory
attempt state, yet receives `claimed=false` and does not create a second provider attempt,
failover, Evidence, Job, or Event. Same-key request drift conflicts, and authority rotation
cannot enumerate or rebind the old winner.

## Unified operating boundary

This work does not copy or replace the automated-commerce switch, SKU-to-listing-to-source
linkback, or profit Evidence work in `D:\KJDS\kjds-auto-commerce`. Store and action automation
remain default-off. Any future external write must continue through Policy, Approval, Permit,
Outbox, and Readback. Observations are not promoted to operating facts by this slice, and no
private `.runtime` material is part of the Git manifest.

## Verification

- Focused unit suite plus the authority-exception regression: `75 passed` for AgentHarness,
  Commander Gateway, MediaJob, and media-agent registry tests.
- SQLite tests cover fresh authority recheck, authority exceptions with zero residue,
  five-field jointly re-signed scope drift with zero
  residue, safe Evidence body, exact replay, historical descriptor drift, rotation isolation,
  and persisted-then-thrown `UNKNOWN_OUTCOME` restart behavior.
- Real PostgreSQL lifecycle suite: `25 passed` in a run-owned PostgreSQL 17 container with
  pre-provisioned 0095/0096 issuance roles. It covers empty 0096 to 0097 replay, append-only
  and deferred Evidence conservation, malformed projection/transition/time negatives, two-
  session idempotency and actor drift, both authority-lock orderings for rotation/revoke,
  and populated downgrade `55000`. The container and its database were test-only and are
  removed after the Gate.
- Ruff and `py_compile` passed; registry JSON parsed; `verify_secrets.py` passed with 1,437
  non-ignored worktree files and 1,443 historical paths; working and cached diff checks passed.
- G1, live provider execution, production admission, external writes, and push were not run or
  claimed.

Final hash stability and the exact nine-path manifest are recorded in the external freeze
candidate after all authorized files stop changing. This document alone
does not authorize staging, commit, release, production use, or external execution.
