# BAS-125 Agent Harness and Canonical Graph — Release Evidence

## Decision

`BAS-125` engineering acceptance is `PASS`. Release/Pilot/Final Gates remain open.
The Harness has no business Fact, Approval, Permit, repository mutation, connector or
external-write authority.

## Contract

- Requirement: `BR-100`
- Architecture: `ADR-0048`
- Migration: `20260728_0066`
- Deep module: `apps/control_plane/agent_harness.py`
- Authenticated API: `apps/control_plane/routers/agent_control.py`
- Verifier seed: `scripts/seed_bas123_agent_graph.py`
- UI: persistent status rail, `/agent-control`, `/goal-todo`, and Project,
  Requirements, Engineering, Runtime, Evidence, Commerce and Authority Graph routes.

Canonical state is PostgreSQL-backed. Verifier observations are append-only and bind
source, scope, observed/fresh time, verifier version, input/result hashes, authority
and artifact/Evidence. A model cannot move a TODO to passed. Inferred edges are
exploration-only and return `can_satisfy_gate=false`.

## Database verification

Isolated PostgreSQL:

- empty database → `0066`;
- `0066 → 0065 → 0066`;
- isolated database removed after verification.

Real PostgreSQL:

- forward-only `0065 → 0066`;
- real ImportJob count/hash before and after: `1 /
  6e865e5152a9b6420b2a3ef530c8f38d`;
- real Evidence count/hash before and after: `58 /
  c9cf4bd695bf653f9ea9ea90e80c32b2`;
- final revision: `20260728_0066 (head)`.

## External observations

`scripts/seed_bas123_agent_graph.py` re-observed the completed Pytest log, real
PostgreSQL revision, Docker health, live API readiness and BAS-123 Evidence before
writing six append-only observations for project `kjds-059-bas123`.

Live authenticated API:

| Probe | Result |
|---|---|
| anonymous project | `401` |
| cross-store project | `403` |
| exact-store project | `200` |
| seven Graph projections | seven × `200` |
| TODO | 6 |
| fresh passed | 6 |
| failed / blocked / stale / no_data | 0 / 0 / 0 / 0 |
| stable nodes / edges | 13 / 12 |
| external write | `false` |
| model self-certification | `false` |

Snapshot observed during live API acceptance:
`3923af89df63609995eb4793ff48fecf13c4fa9d09dfcf58138f0ffef04d6b1a`.
Snapshots are deterministic for an exact `as_of`; a later `as_of` intentionally
changes the snapshot hash.

## Fault injection and quality

- Missing/unregistered model verifier cannot record a passing task.
- Wrong task/verifier binding fails closed.
- Expired success becomes `stale`, not passed.
- Cross-tenant/store read fails closed.
- Inferred edge cannot satisfy a Gate.
- Observation replay is idempotent.
- Full backend: `747 passed`, 9 third-party deprecation warnings.
- Focused API/Harness: `36 passed`, 1 third-party warning.
- Web: `53 passed`.
- Ruff, secret scan and `git diff --check`: exit `0`.
- Web production build: 32 routes, passed.
- OpenAPI and Outbox coverage machine registries match runtime source.

## Browser acceptance

Rebuilt delivery containers were used.

- Desktop `/agent-control`: 6/6 fresh passed, 13 nodes, 12 edges, external write
  false; document/client widths matched; no console warning/error.
- `390x844` `/agent-control`: document/client width `375`, no document horizontal
  overflow; persistent rail bounded at left `12` and right `362.8`; six passed tasks
  rendered; no console warning/error.
- Desktop `/engineering-graph`: connected ADR→migration→test nodes and two
  evidence-derived causal edges rendered; referenced boundary node was included;
  document/client widths matched; no console warning/error.

## Remaining boundary

The first Graph path proves BAS-123 engineering traceability. It does not prove a real
SKU operating loop, formal Fact promotion, Ozon write, order, settlement, bank
reconciliation or actual-cash CM3. BAS-124 remains the next semantic authority slice.

## 2026-07-28 BAS-124 and M0→M4 closure addendum

BAS-124 now contributes six additional fresh verifier-owned tasks and twelve
canonical nodes. The current project has:

- `17` tasks and `17` append-only observations;
- `37` stable nodes and `34` evidence/runtime edges;
- `12` fresh passed engineering tasks;
- top-level project status `blocked`;
- M0 `no_data`;
- M1–M4 `blocked`;
- model self-certification `false`;
- external write `false`.

The M0→M4 source observation is frozen in
`docs/project/evidence/20260728_M0_M4_VERIFIER_STATUS_GRAPH.md`. It is owned by a
registered PostgreSQL verifier with a one-hour freshness window and reports the real
absence of current grant, native candidate/import/Product/Fact, ProfitScenario,
ListingDraft, native Pilot, order, finance entry and reconciliation records.

During this extension, a P0 contract gap was found and fixed: workspace projection
previously declared task dependencies but did not invalidate a passed dependent when
an upstream observation changed. `AgentHarnessService.workspace` now propagates
missing/non-passed upstream state and marks a downstream pass `stale` when the latest
upstream observation is newer. The regression test records a new independently
passed upstream hash and proves the old dependent pass becomes stale.

Final verification after the change:

- full backend: `755 passed`, 9 third-party deprecation warnings;
- Agent Harness focused regression: `5 passed`;
- Web: `55 passed`; dependency audit `0 vulnerabilities`;
- Ruff, secret scan (`731` worktree / `581` history) and `git diff --check`: pass;
- both BAS-124 and M0→M4 seeds replay idempotently at
  `17 / 17 / 37 / 34`;
- all seven authenticated Graph projections return `200`;
- rebuilt API image:
  `3db8e741d760dca79e5404ebc32f173bcd85c268679090a33350e407cf513e1d`;
- rebuilt media-worker image:
  `66f773e9e8166472a90f9e14ccc154312570daf4299f8d23c9439cd8d3e78892`;
- PostgreSQL, API, media-worker and Web are healthy; API reports
  `20260728_0067 (head)`.

In-app Browser acceptance of `/agent-control`:

- desktop `1440x1000`: task/node/edge counts `17/37/34`, all M0→M4 cards and
  persistent status rail present; document scroll width equals client width; no
  console warning/error;
- mobile `390x844`: document/client/scroll width `375`, no page horizontal overflow;
  status rail bounded at `12..362.8px`; M0 `no_data` and five attention items
  visible; no console warning/error.

This addendum does not change the remaining boundary: the Graph now exposes those
real blockers instead of hiding them, but only their actual owners and source
artifacts can move Release/Pilot/Final Gates.
