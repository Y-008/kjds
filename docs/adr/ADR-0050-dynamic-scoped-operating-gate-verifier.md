# ADR-0050 — Dynamic Scoped Operating Gate Verifier

## Status

Accepted for BAS-126 on 2026-07-28.

## Context

The first M0→M4 seed froze a correct zero-data PostgreSQL snapshot, but deliberately
raised an exception as soon as any source count became non-zero. It could expose the
initial blocker but could not verify genuine progression. Counting global rows alone
also cannot establish tenant/entity/store authority or the business meaning of a
completed operating stage.

KJDS already has two complementary authorities:

- `CommerceOperatingSystem.workspace()` projects the current authenticated scope and
  thirteen server-owned operating stages from governed domain modules;
- PostgreSQL provides supporting material-record counts and the migration revision.

Neither a model nor the Agent Harness should duplicate their business rules.

## Decision

Add one pure deep module, `OperatingStageVerifier`, with one public interface:

```python
evaluate(
    *,
    workspace: dict,
    support_counts: dict[str, int],
    observation_bucket: str,
) -> dict
```

The module owns validation, M0→M4 grouping, sequential dependency propagation,
failure semantics, deterministic hashes, Owner and next-action selection. It owns no
I/O and no business mutation.

The runtime observer is the adapter. Once per hourly bucket it:

1. asks the authenticated Commerce OS for an exact-store snapshot at the bucket
   boundary;
2. reads bounded aggregate support counts and requires Alembic `20260728_0067`;
3. calls the pure verifier;
4. records five append-only Agent Harness observations through the registered
   `m0m4-commerce-os@1` verifier;
5. updates only the observed Graph projections and their content hashes.

`completed` plus a positive qualified-record count is the only Commerce OS stage
state that may contribute to `passed`. `ready_for_internal_action` is not completion.
The Gate groups are:

- M0: observe, identity, current grant and native Product;
- M1: qualify, item draft, native Import and formal Fact;
- M2: content, listing approval, ContentAsset, ProfitScenario and ListingDraft;
- M3: publish, order, procurement review, fulfill, settle, native Pilot, governed
  execution receipt and Order;
- M4: reconcile, learn, FinanceEntry, ReconciliationRun and the Commerce OS real
  profit-loop claim.

Every later Gate additionally requires every earlier Gate to pass. Missing or
duplicate stages, contract drift, invalid counts, a non-read-only projection or any
open external-write/self-approval control fails all five Gates closed. M0 alone may
be `no_data` when both authority and candidate data are absent.

Input hashes include the observation bucket, semantic workspace state, source
snapshots, scoped stage values and relevant support counts. Replaying the same inputs
within a bucket is idempotent; changed source facts, counts or bucket create a new
observation.

## Consequences

- A real grant, candidate, Fact, content, Pilot, settlement or reconciliation can
  advance the Graph without editing the seed.
- A row count cannot bypass scoped Commerce OS authority, and a Commerce OS label
  cannot bypass material database support.
- The Agent Harness remains an observer. It cannot write Facts, approve its own
  output, issue a Permit or perform an external commerce action.
- The hourly boundary trades sub-hour progression latency for stable, replayable
  observations. A later scheduler may shorten the bucket only through a new verifier
  version and Evidence.

## Rejected alternatives

- Keep the zero-only seed: it makes true progress an error.
- Reuse the legacy unscoped readiness endpoint: it does not cover M0→M4 or native
  tenant/entity/store authority.
- Put all rules in the seed: it creates a shallow script seam that cannot be tested
  independently.
- Let the model interpret stage text: it permits self-certification.
- Open a new Graph database: it adds a second authority without solving verification.
