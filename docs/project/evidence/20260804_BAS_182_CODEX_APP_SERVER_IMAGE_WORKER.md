# BAS-182 — Codex app-server Image Worker protocol Gate

## Verdict

`BAS-182` implements a provider-neutral protocol adapter and immutable Worker
Observation for Codex app-server image generation. It does **not** create a Job
ledger, public API, approval, Fact, FinanceEntry, Pilot, Outbox, platform write,
or a second media artifact truth.

The admitted protocol is pinned to `codex-cli 0.142.5`. The admitted transports
are `stdio` and Unix-domain socket. WebSocket remains experimental and is not
admitted. The repository fixture is schema-valid synthetic protocol evidence;
it is not represented as a captured production session.

## Authoritative boundaries

### Identity and roles

- Tenant identity is derived only from `Principal.tenant_ref`.
- Connector identity, provider, capability, binding hash, current health, and
  protocol version are projected by the existing `MediaConnectorRegistry`.
- `operator` and `admin` are the only Worker dispatch/readback roles.
- `reviewer`, `compliance`, `monitor`, `approver`, `risk`, `pilot_reader`,
  `executor`, and an empty role set are rejected before durable peek, claim, or
  transport invocation.
- Connector currentness is evaluated at the trusted Worker clock. Job
  `data_as_of` cannot rewind a revoked, rotated, or paused connector.

### Protocol authority

Raw output from `codex app-server generate-json-schema` is not a deterministic
byte artifact because definition order can vary. The contract therefore pins
canonical parsed JSON hashes:

- v2 aggregate: `064f4e66f3f9efa34601039e80e1c57a5593fdd77bad7a6562ec014cf7452dc2`
- `ItemCompletedNotification`: `0ebc5cf18b3e4e37b3e5813c7f20faea64682c5b322bdc358d391d3900891b89`
- `TurnCompletedNotification`: `ece1a0743df0ea913f259bdb747557d812a3e6e45aed222fa70ebeb996a57a44`
- canonical bundle observation: `004e2846436659b58b9ce4d71ab7e5a862e4756dc52dc4651d6bef368131f377`

The durable claim binds a stable runtime protocol authority hash containing
the connector reference/binding, CLI/schema pins, and the server-owned actual
transport kind, adapter version, and adapter hash. The transport descriptor is
re-read before every durable peek; a caller cannot label WebSocket or shell
execution as `stdio`. Each invocation also
requires a fresh independently verified receipt containing `checked_at`,
`recorded_at`, `effective_at`, and `fresh_until`. Trusted-clock progress does
not invalidate the stable authority; a binding, schema, version, currentness,
or receipt-integrity drift fails before claim or transport.

### Durable execution order

The Worker uses a BAS-183-owned durability seam and does not keep process-local
Job truth:

1. validate request, tenant, and Worker role;
2. read-only peek of the prospective durable claim;
3. validate current connector and runtime protocol receipt;
4. atomic claim using the exact peek token and exact peek state/resume snapshot;
5. invoke either dispatch or readback once;
6. append the safe transition through the durable port;
7. re-peek and atomically claim the durable terminal projection;
8. return terminal state only after independent transition-seal and Evidence
   verification.

Missing/non-ready new work, connector rotation/revocation, authority drift, or
a peek-token race leaves local reserve and transport counts at zero. A hard
stop after durable claim leaves `UNKNOWN_OUTCOME`; a new Worker instance reads
back the existing claim and does not dispatch again.

`LOGIN_REQUIRED` and `LIMITED` require a fresh same-connector readback. A known
still-paused result remains paused. Resume requires both a successful readback
and explicit caller intent, followed by a new current READY check. Timestamp
evidence for rate-limit recovery is bound to the durable dispatch/readback
window and rejects booleans, stale values, and future values.
Any Turn or item activity in a pause readback makes the outcome unknown and
cannot unlock resume; this prevents a second dispatch while an earlier Turn is
unresolved.

### Image protocol semantics

The authoritative successful artifact event is `item/completed` with a
`ThreadItem::ImageGeneration` bound to the exact thread, turn, item, and claim
time window. `turn/completed` is a terminal summary and must contain the exact
completed item when `itemsView=full`; it cannot independently prove an image.

Turn `startedAt` and `completedAt` are Unix seconds. Item timestamps and
`durationMs` are milliseconds. Duration validation permits the quantization
window implied by second-resolution Turn timestamps instead of requiring false
millisecond equality. Item start/completion are monotonic and remain inside the
quantized Turn interval.

Known failure requires `status=failed`, empty `result`, omitted `savedPath`, and
schema-valid `revisedPrompt` (`string` or `null`). The prompt is never projected.
Malformed/unknown item, Turn, error, event order, timestamp, or identity shapes
produce a safe `UNKNOWN_OUTCOME`.

### Protocol resource and confidentiality budget

Before any canonical serialization, event-chain hash, or artifact file I/O,
the Worker enforces the repository-sealed limits: 32 messages, 16,384
characters per non-artifact field, 262,144 aggregate metadata characters,
1,024 container items, depth 12, signed-int64 integers, finite floats, and the
base64 size derived from the 25 MiB artifact cap. Handshake client/server shapes
are exact allowlists. The event chain hashes a bounded redacted projection, not
provider error text, revised prompts, saved paths, or image base64.

### Artifact admission

The saved path must be absolute and remain inside the connector-owned root.
Traversal, symlink/reparse components, non-regular files, file identity/size
changes, and over-limit data are rejected. The Worker performs bounded reading
from one no-follow descriptor where supported. It opens and holds the Connector
root before the final path walk, resolves the already-open file handle, and
proves that handle remains beneath the unchanged root handle. Root rename/swap
and intermediate symlink/junction races therefore fail after open. The same
frozen bytes are verified against the base64 result.

PNG admission verifies:

- signature, complete chunk walk, chunk names/reserved bit, and every CRC;
- known critical chunks only, ordered/unique IHDR, IDAT, terminal IEND;
- legal color type/bit depth, palette cardinality, and indexed PLTE;
- dimension, pixel, decoded-memory, file-size, and base64-size caps;
- bounded zlib completion, exact non-interlaced scanline length, and filter range;
- exact SHA-256 and byte equality with the protocol result.

Unknown well-formed ancillary chunks are allowed. Artifact bytes, filesystem
paths, revised prompts, OAuth data, provider request identifiers, and provider
error bodies are absent from the Observation.

## Primary evidence

All upstream links are pinned to `rust-v0.142.5`:

- `codex-rs/ext/image-generation/src/tool.rs`, SHA-256
  `8f6dc1e5f71e4b7ef2224adbb1c51b3dc2bcb749c272c375f1b9440bf8464021`
- `codex-rs/app-server-protocol/src/protocol/v2/item.rs`, SHA-256
  `5525e5d8b307c228ed4b1e4b48ef1e1e2903a50a7d523244658aa03213742b50`
- `codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs`, SHA-256
  `f6dd5ece89cdecfc0f5644bf37a2bc9a956b34394f85d049a9336a63c62d7665`, for Turn seconds and `durationMs` semantics
- `codex-rs/app-server/tests/suite/v2/imagegen_extension.rs`, SHA-256
  `0b9074ed408c197bc9361611155a23222eb3dd4192e6224659fea54f808f1caa`

The repository registry and fixture carry canonical semantic seals. Formatting
or key-order changes do not change request identity. A semantic modification,
including one followed by a caller-generated new seal, is rejected against the
server-owned expected seal.

## Verified negative contracts

- role denial and exact tenant/provider/capability/binding/version drift;
- current connector revoke, paused readback, explicit resume, and READY recovery;
- runtime authority/receipt field, time, freshness, and integrity drift;
- atomic peek-token race and idempotency fingerprint drift;
- hard crash after claim, disconnect, generic adapter exception, record failure,
  and process-restart readback;
- duplicate, late, unknown, malformed, wrong-identity, and wrong-time events;
- oversized/deep protocol payloads, non-finite numbers, unknown handshake
  fields, and pre-hash base64 rejection;
- actual transport masquerade and descriptor drift after Worker construction;
- dangling pause readbacks, cross-event timestamp reversal, and pause/error
  precedence;
- malformed Turn error and known image failure shapes;
- path escape, traversal, symlink/reparse, size/base64 cap, result mismatch;
- root rename/replacement and intermediate-directory symlink races between
  path validation and file open;
- PNG truncation, CRC/IEND/critical-chunk/reserved-bit/palette/pixel/decode errors;
- recursive canary absence and zero governance/external-write authority.

## Governance envelope

Every result remains an Observation. The following values are fixed false/zero:

- `fact_promoted`
- `finance_entry_persisted`
- `approval_granted`
- `permit_granted`
- `pilot_started`
- `outbox_emitted`
- `platform_write`
- automatic provider retry
- automatic identity rotation
- cross-scope leakage

## Validation and remaining UNKNOWN

Focused tests, target Ruff, deterministic seal checks, secret scan, and diff
checks are required on the final frozen five-file hash set before commit. The
final literal outputs are recorded in the handoff/commit verification record.

Still UNKNOWN and outside BAS-182:

- production BAS-183 durable SQL Job implementation and retention;
- real provider quality, latency, token/cost, rate-limit behavior, and uptime;
- production credential login state and real generated artifact Evidence;
- public Job API/SSE and usage ledger;
- any marketplace/social publishing or other platform write.

## Rollback

The slice has no migration or production configuration. Rollback is the exact
inverse of the five-file commit. It removes the new Worker module, registry,
fixture, focused tests, and this Evidence document without changing existing
MediaConnector, media artifact, runtime, API, or database truth.
