# ADR-0054 — Authenticated Scope Authority Review Lineage

## Status

Accepted for BAS-130 on 2026-07-28.

## Context

BAS-129 made scope-grant admission non-mutating and observable, but the inherited
Evidence contract still trusted `reviewed_by` inside uploader-authored metadata.
That string was not proof that another authenticated actor had inspected the owner
material. A forged grade A upload could therefore satisfy the apparent
owner/reviewer split without an independent review event.

Creating a second mutable grant-request state machine would duplicate
`ScopeGrantAuthority`. The existing Evidence and Lineage modules already provide the
local-substitutable seam for immutable source material and review decisions.

## Decision

Keep submission, review, preflight and record inside the existing
`ScopeGrantAuthority` deep module:

1. `submit_source(...)` captures a grade B immutable owner artifact using
   `kjds-scope-authority-source-v1`. Its authenticated `created_by` is the owner.
2. `review_source(...)` captures an append-only grade A JSON decision using
   `kjds-scope-authority-review-v1`. Its authenticated `created_by` is the reviewer,
   and an immutable `scope_authority_review` lineage edge points to the exact source
   ID/hash.
3. An accepted review requires `authentic_original`,
   `owner_authority_verified` and `scope_matches` to be true, plus a non-empty
   rationale.
4. Preflight and record revalidate the current review, source, blob hashes, exact
   tenant/entity/store/subject/decision/effective time and lineage at their cutoff.
5. Owner, reviewer, recorder and subject must be four distinct authenticated actors.
   A matching independent rejection blocks admission.

The generic `POST /v1/evidence` endpoint rejects the two reserved source names and
reserved contract metadata. Dedicated routes own submission and review:

- `POST /v1/scope-grants/evidence`;
- `POST /v1/scope-grants/evidence/reviews`.

Both source and review use stable source references and partial unique indexes in
Alembic `20260728_0069`; exact retries are idempotent and payload drift conflicts.
No path creates Approval, Permit or an external commerce write.

## Consequences

- Review authority comes from an authenticated actor and append-only record, not a
  model or uploader claim.
- `as_of` replay can prove which source and review existed at the grant cutoff.
- Graph/TODO can expose the truthful next chain: owner source → independent review →
  non-mutating preflight.
- The real database remains at zero source/review/grant rows until account-owner
  material is supplied; engineering acceptance does not invent it.
- Release remains `REJECTED`, dedicated monitor/Windows Task remains a configuration
  blocker, and all external commerce writes remain closed.

## Rejected alternatives

- Trust `reviewed_by` metadata: not authenticated review.
- Let compliance/admin upload and review the same artifact: violates separation of
  duty.
- Mutate the owner source with a review status: destroys append-only history.
- Create synthetic owner Evidence for live acceptance: crosses the external-authority
  boundary.
