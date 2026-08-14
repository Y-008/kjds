# ADR-0088: Minimal commercial lifecycle ledger

Status: Accepted for engineering

Date: 2026-08-02

Owner: Commercialization control plane

## Context

The project already had a pure in-memory commercial lifecycle kernel for exact-scope authorization and usage control. The next step is a durable, auditable ledger for the commercial shell without importing external payment-provider complexity into the business layer.

The commercialization contract requires a minimal, fail-closed database path for plan, subscription, entitlement, invoice, payment-attempt, refund, and tax-evidence records. The ledger must remain internal-record-only: no Stripe, bank, or external processor integration is implied by the API.

## Decision

Add one append-only commercial lifecycle ledger keyed by the exact commercial scope:

- `customer_ref`
- `deployment_ref`
- `tenant_ref`
- `entity_ref`
- `store_ref`

Persist each commercial action as an immutable event row with request hash, decision hash, state, idempotency key, and evidence lineage. Evidence lineage is stored append-only in a companion table and remains visible in snapshots.

The subscription record is the authorization anchor. Entitlement is derived from a valid subscription plus settlement evidence and then materialized as an internal lifecycle event. The API only records internal commercial facts; it does not claim processor connectivity or perform external writes.

## Consequences

- Idempotency and scope isolation are enforced in the database.
- Refunds cannot exceed collected payment.
- Currency and amount handling stays bounded and fail-closed.
- The ledger can be replayed and audited without mutating prior rows.
- Business code does not need to know anything about Stripe or bank transport details.

## Alternatives rejected

- Keep only the in-memory kernel: too ephemeral for audit and replay.
- Store mutable current-state rows only: loses lineage and makes replay ambiguous.
- Add vendor-specific payment abstractions in the core module: leaks external complexity into the business layer.
- Permit unrestricted currencies or floating-point money: would weaken the audit trail.
