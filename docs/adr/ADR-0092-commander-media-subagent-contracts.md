# ADR-0092: Commander and media subagent contract freeze

- Status: Accepted for contract-only implementation
- Date: 2026-08-03
- Work item: BAS-180
- Owners: Agent Platform, Media, Evidence and Risk
- Depends on: BAS-172, BAS-176 and BAS-178
- Machine-readable authorities:
  - `docs/project/registries/media_agent_source_adoption.json`
  - `docs/project/registries/media_agent_contracts.json`

## Context

KJDS already owns governed Agent run envelopes, `AgentHarnessService`,
`ContentAsset`, immutable Evidence/Lineage, Media QA, Delivery Manifest and a
fixed-template ComfyUI/FFmpeg execution seam. The new product direction adds a
Commander that delegates media work to typed subagents while keeping model
reasoning separate from credential custody and durable execution.

The contract must support image generation/editing, reference-video analysis,
video rendering and Windows tutorial production. It must also leave room for a
Codex app-server connector deployed either beside a customer or on an isolated
hosted node. BAS-180 freezes those interfaces only. It introduces no database
table, API route, Worker, Provider, OpenAPI surface or MCP runtime.

## Decision

### One Commander, five deep tools

`AgentHarnessService` remains the owner of goals, graph tasks, responsibility
and verifier bindings. A Commander compiles an approved brief and invokes one
of exactly five versioned tools:

1. `media.image_generate`
2. `media.image_edit`
3. `media.video_blueprint`
4. `media.video_render`
5. `tutorial.build`

The immediate tool result contains only a durable `job_ref`, contract version
and initial status. Tool responses do not contain OAuth material, cookies,
browser storage or generated Blob bytes. The Commander subsequently reads the
job projection and governed asset references.

Authenticated scope is derived by the control plane. Caller supplied
`tenant_ref`, `entity_ref`, `store_ref`, `authority_sha256` and actor identity
are not accepted as authority. A Connector and a Job both freeze the derived
tenant binding before dispatch.

### Durable asynchronous Job contract

The canonical state machine is:

```text
QUEUED -> DISPATCHED -> RUNNING -> UPLOADING -> SUCCEEDED
   |          |           |           |
   +----------+-----------+-----------+-> CANCELLED | FAILED
              +-----------> LOGIN_REQUIRED
              +-----------> LIMITED
              +-----------> UNKNOWN_OUTCOME
```

`LOGIN_REQUIRED` and `LIMITED` pause the same Connector. Resumption requires an
explicit control-plane decision after fresh status readback. `UNKNOWN_OUTCOME`
is readback-only: it may resolve to upload, success, failure or cancellation,
but never to a new dispatch. This prevents an uncertain external result from
creating duplicate media or duplicate usage.

Idempotency is scoped to derived tenant, tool name and idempotency key. The
default concurrency is one active Job per Connector and the default queue cap
is 100 Jobs per tenant. A Provider is selected explicitly at admission. There
is no automatic cross-Provider retry and no automatic Connector identity
rotation.

### Connector contract

A Connector is a capability and health descriptor, not a credential store.
The only deployment modes are:

- `customer_local`: the customer completes Codex authentication locally and
  the connector pulls Jobs belonging to its frozen tenant binding;
- `hosted_isolated`: an operator completes authentication in an isolated OS
  identity and isolated `CODEX_HOME` owned by that Connector.

The registry may store `connector_ref`, provider, deployment mode, tenant
binding hash, capability list, concurrency limit, protocol version, health,
rate-limit summary timestamps and last heartbeat. Secret material, raw OAuth
tokens, cookies, browser local storage, passwords and browser-profile archives
are forbidden fields.

Codex app-server is the preferred Codex protocol seam because it owns its login
and account lifecycle. Production image work does not depend on ChatGPT web DOM
selectors. ComfyUI remains an explicit alternative Provider using only admitted
workflow templates and parameters.

### Asset and Evidence ownership

Every successful Job must produce immutable artifact Evidence with SHA-256,
MIME type, byte size, dimensions/duration where applicable, source Job,
Connector reference, Provider contract and timestamps. A governed commerce
result also references its `ContentAsset`. Standalone proposal output remains
ineligible for Listing use until attached to a scoped `ContentAsset` and passed
through the existing Media QA lifecycle.

The Job ledger does not become a second Blob, Evidence, Product, ContentAsset,
QA, Approval or Delivery Manifest owner. It stores references and sanitized
execution metadata only. The Commander may request work and evaluate returned
references; it does not approve an asset or publish it.

## Source adoption

GitHub repositories and official specifications are evaluated through the
machine-readable Source Adoption registry. The decisions are intentionally
different:

- Codex app-server: preferred protocol candidate for BAS-182 after a pinned
  protocol replay and isolation test;
- ComfyUI and FFmpeg: existing isolated runtimes, still governed by their
  current admitted-template and build-manifest rules;
- third-party Codex/image gateway projects: interface and event-parsing
  patterns only; upstream runtimes are not imported by BAS-180;
- model and media tool candidates: isolated evaluation only after license,
  checksum, VRAM and representative-fixture gates.

Video-site tutorials may help discover workflows, but source code, an official
specification and reproducible fixtures remain the implementation authority.

## Ownership boundaries

| Authority | Remains the sole owner of | BAS-180 interaction |
|---|---|---|
| BAS-178 | social collection, campaign grant, platform action, readback, revocation and kill switch | consumes only approved Delivery Manifest references in BAS-188 |
| COM-002 | KJDS Access Token lifecycle, plans, balance, metering, refunds, SLA, DPA, export and deletion | future Job records carry an opaque `usage_ref`; no token or billing implementation here |
| ContentAsset/Evidence | media fact, Blob, hash, lineage, QA, approval and Delivery Manifest | Job success references these authorities; it never replaces them |
| AgentHarness | goals, graph tasks, operating subject and verifier status | Commander and tools compile into existing tasks and observations |
| Connector Registry | tenant-bound capability and health descriptor | introduced by BAS-181; stores no credential material |

## Public contract freeze

The machine-readable contract freezes:

- the five tool names and their allowed inputs;
- server-derived scope and forbidden sensitive keys;
- Job states, legal transitions, pause/readback behavior and idempotency scope;
- Connector deployment modes, descriptor fields and health states;
- artifact/Evidence references and Listing-ineligibility defaults;
- ownership handoffs to BAS-178, COM-002, ContentAsset/Evidence and
  AgentHarness;
- default retention of raw artifact bytes for 30 days, subject to the stronger
  COM-002 customer lifecycle and Evidence retention policy when implemented.

Changing a tool name, adding a state, widening a Connector field, allowing an
automatic reroute or changing an Owner requires a new contract version and an
ADR review.

## Rejected alternatives

- Shared round-robin account pool: rejected because it breaks tenant identity,
  rate-limit attribution and deterministic readback.
- Browser fingerprint mutation as a reliability mechanism: rejected because it
  creates a second uncontrolled execution surface.
- Synchronous image response as canonical truth: rejected because provider
  duration and uncertain completion require a durable Job.
- Allowing the Commander to hold credentials or Blob bytes: rejected because it
  expands the model data boundary and weakens redaction.
- Automatic retry after `UNKNOWN_OUTCOME`: rejected because it can duplicate
  results and usage.
- New Agent or media truth store: rejected because KJDS already owns the needed
  graph, ContentAsset, Evidence and QA authorities.

## Consequences and follow-on work

- BAS-181 may implement only the Connector registry and exact-tenant binding
  defined here.
- BAS-182 may add a pinned Codex app-server protocol adapter and Worker after
  BAS-181 passes.
- BAS-183 owns Job persistence, API/SSE/idempotency and COM-002 usage wiring.
- BAS-184 exposes the versioned tools through the existing AgentHarness and MCP
  facade.
- BAS-185 through BAS-188 add admitted ComfyUI templates, EditingBlueprint,
  TutorialGraph and the BAS-178 Delivery Manifest handoff.
- BAS-189 remains gated by COM-002 commercial completion and independent Pilot
  acceptance.

## BAS-180 acceptance

- Both JSON registries parse and expose unique versioned identifiers.
- Exactly five tools exist and all return only a Job reference immediately.
- Caller-controlled scope and credential-shaped fields are forbidden.
- The Job graph has one start state, explicit terminal states and no execution
  transition out of `UNKNOWN_OUTCOME`.
- Provider selection is explicit; automatic Provider failover and identity
  rotation are false.
- Connector records contain only descriptors and sanitized status.
- Ownership tests preserve BAS-178, COM-002, ContentAsset/Evidence and
  AgentHarness as external authorities.
- This work item changes only this ADR, the two registries and their contract
  test.
