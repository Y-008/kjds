# C0-003 Commercial Lifecycle Ledger Evidence

- Date: 2026-08-02
- Status: PARTIAL
- Scope: internal commercial lifecycle ledger only

## What was implemented

- A database-backed commercial lifecycle ledger at `apps/control_plane/commercial_lifecycle.py`.
- Exact-scope append-only event rows for plan, subscription, entitlement, invoice, payment attempt, refund, and tax evidence.
- Append-only evidence lineage rows linked to each event.
- Fail-closed idempotency, scope isolation, bounded currency handling, and refund upper-bound checks.
- Internal-only FastAPI routes under `/v1/commercial-lifecycle/*`.
- Focused tests covering replay, entitlement derivation, evidence lineage, and refund over-collection rejection.

## What remains unknown

- Real Stripe, bank, or PSP connectivity: not implemented.
- Real tax workflow, statutory filing, or accountant-reviewed tax policy: not implemented.
- Production billing semantics for invoices, dunning, chargebacks, and settlement timing: still unknown.
- Contract, legal, and data-processing documents for selling a live software subscription: still unknown.

## Verification

- Focused commercial lifecycle tests passed locally.
- The new migration advances Alembic head from `20260802_0087` to `20260802_0088`.

## Evidence statement

This change makes the commercial shell auditable and durable, but it does not claim a live payment rail, bank settlement, or tax-filing integration. It is therefore an internal commercial ledger, not a production billing completion claim.
