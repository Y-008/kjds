# M0→M4 Verifier-owned Gate Status — Observation Evidence

## Decision

The current M0→M4 operating path is not ready. This is a real observed state, not a
model estimate and not a static roadmap graphic.

The Agent Harness must expose five current TODOs:

| Stage | Current state | Verifier-owned reason |
|---|---|---|
| M0 Governance/Candidate | `no_data` | no current entity/store grant and no native candidate Product |
| M1 Intelligence/Formal Fact | `blocked` | no native scoped ImportJob, Product or formal Fact |
| M2 Content/Profit/Listing | `blocked` | no real ProfitScenario or ListingDraft |
| M3 Pilot/Order/Settlement | `blocked` | no native scoped Pilot, order or formal finance fact |
| M4 Actual cash/Reconciliation | `blocked` | no finance entry or reconciliation run |

Downstream stages remain blocked even if their own verifier is accidentally reported
as passed; changed or non-passed upstream observations make downstream tasks stale.

## External observation

Observed from the real PostgreSQL database on 2026-07-28:

| Observation | Count/value |
|---|---:|
| Alembic revision | `20260728_0067` |
| `scope_grant_events` | 0 |
| native scoped `import_jobs` | 0 |
| native scoped `products` | 0 |
| native scoped `fact_records` | 0 |
| `profit_scenarios` | 0 |
| `listing_drafts` | 0 |
| `orders` | 0 |
| native scoped `read_only_pilots` | 0 |
| `finance_entries` | 0 |
| `reconciliation_runs` | 0 |

The observation query returns counts only and does not copy business payloads or
credentials. Its verifier contract has a one-hour freshness window. After that
window the UI must display `stale` until the database is re-observed.

## Authority boundary

- A registered PostgreSQL observation verifier owns these states.
- The model cannot mark a stage passed.
- A dependency change invalidates a downstream pass.
- The five tasks appear in the persistent status rail and Goal/TODO workspace.
- The nodes and edges are canonical, stable-keyed and content-hashed.
- Inferred edges remain exploration-only and cannot satisfy a Gate.
- No task, observation or Graph edge grants Approval, Permit, accounting or external
  commerce write authority.

The absent entity grant, real demand export, three new candidates, supplier offers,
independent reviews, settlement and bank records require their actual owners and
source artifacts. Their absence is recorded; it is not replaced with fixtures or
synthetic completion.
