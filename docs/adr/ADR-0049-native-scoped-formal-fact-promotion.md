# ADR-0049 — Native Scoped Formal Fact Promotion

## Status

Accepted for BAS-124 implementation on 2026-07-28.

## Context

The legacy `FactPromotionService` reads global ImportJob, Fact and Product rows. It
can match a bare SKU without tenant/entity/store authority. Native scoped Ozon staging
from BAS-123 must not use that path. Accepted ReadOnly Claims remain interpretations
and cannot be promoted directly.

## Decision

Add a native scope tuple to new FactRecord and PromotionRun rows:

`tenant_ref + entity_ref + store_ref + scope_grant_authority_sha256 +
source_evidence_sha256 + scope_as_of`.

Legacy rows keep all six fields null and are excluded from tenant APIs. Native
promotion:

1. authenticates Principal and exact store;
2. requires one current entity grant;
3. loads an ImportJob through BAS-123 scoped SQL authority;
4. revalidates original immutable Evidence and its exact scope binding;
5. requires an accepted independent source review; finance types additionally require
   the existing finance review/mapping/classification controls;
6. maps SKU only to an exact scoped Product with matching grant and `scope_as_of`;
7. writes Fact and PromotionRun in one transaction with the frozen tuple;
8. uses scoped uniqueness/idempotency and deterministic as-of;
9. creates lineage from the same scoped source Evidence;
10. grants no external write, Approval or Permit.

No Claim endpoint is accepted as a Fact source. Claim → Fact remains prohibited.

## Consequences

- Global Fact APIs remain legacy-only and cannot expose native tenant facts.
- Native list/detail/promotion APIs fail with anonymous `401`, cross-store `403`, and
  missing entity/bad Evidence/review/mapping `422`.
- Same payload may exist independently across tenants; same-scope replay is
  idempotent.
- Product mapping ambiguity or an unscoped Product fails closed.
