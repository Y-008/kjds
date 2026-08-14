# ADR-0068: Native exact-scope content media factory

- Status: Accepted for BAS-148 implementation
- Date: 2026-07-29
- Owners: PIM, Content, Evidence, Media Worker, Listing and Agent Team

## Context

KJDS already has Canonical Product, ContentAsset, scoped Product/content
Evidence, fixed admitted image/video workflows, PostgreSQL media executions,
append-only execution events and immutable Delivery Manifests. The existing
read route composes scope in Router code and then calls a shallow media
snapshot. That snapshot can read executions and manifests outside the selected
Product, has no exact `as_of` reconstruction, does not validate event or
manifest integrity, and requires callers to infer readiness.

Seller ERP and content tools commonly provide image/video generation, batch
execution, QA and listing-delivery workspaces. Copying their screens, private
interfaces or session state would neither preserve KJDS authority nor make the
workflow auditable.

## Decision

Add one deep module, `ScopedContentMediaFactoryWorkspace`, with the primary
public interface:

`project(principal, entity_scope, store_ref, as_of, ...)`.

The module composes, but does not replace:

1. `ScopedProductContentAuthority` for exact Canonical Product, ContentAsset,
   rights/source/artifact/QA Evidence and Product scope;
2. the existing fixed `TEMPLATE_CATALOG` admission policy;
3. `MediaExecutionRow` and append-only `MediaExecutionEventRow` as the
   execution ledger;
4. `MediaDeliveryManifestRow` as the listing-delivery record.

`MediaWorkbenchService` receives one narrow read-source interface that accepts
only the already authorized ContentAsset IDs and a timezone-aware cutoff. It
must filter Asset, Execution, Event and Manifest rows before materialization
and report truncation; it must never infer tenant or entity from a caller
supplied asset ID. API, Web, Commerce OS and Agent tools consume the same deep
projection. The legacy `/v1/media/workbench` route remains compatible but
delegates to the same module; `/v1/media-factory/workspace` is canonical.

The aggregate key is Canonical Product + ContentAsset. The module owns
deterministic stage classification, role/ratio coverage, latest execution
selection, temporal event reconstruction, retry readiness, manifest
eligibility, filtering, pagination, counts, blockers, Owner/SLA/next and
stable snapshot/artifact hashes. Stages are `brief`,
`source_rights_ready`, `queued`, `executing`, `generated`, `qa_pending`,
`qa_failed`, `delivery_ready` and `blocked`.

The module resolves exact entity authority before reading any upstream. A
missing or invalid entity returns `no_data`/`blocked` with zero Product,
Asset, Execution, Event and Manifest reads. Bad current Evidence, scope/hash
drift, a mutable ContentAsset state that post-dates the cutoff, execution
input/template mismatch, broken event sequence/transition/time, a current row
that disagrees with its latest event, manifest asset/execution/state/hash/time
mismatch, or truncated source projection fails closed and withholds the
affected payload. Historical state that cannot be proven from append-only
records is not guessed.

This projection is read-only. It does not create or modify ContentAsset,
execution, QA, Delivery Manifest, Listing, Approval or Permit records. Its
versioned Agent artifact may only suggest internal work. It cannot invoke
ComfyUI, FFmpeg, an external provider, marketplace publish or any other
external write. Existing mutation routes keep their exact-scope preflight and
remain separate from projection.

No new table is required because exact read composition can use the current
ContentAsset rows and append-only media ledgers. A forward-only `0075` is
allowed only if PostgreSQL verification proves a missing authority or index
that cannot be obtained safely from existing records.

## Rejected alternatives

- Keep scope selection in Router or React: rejected because API, Web and Agent
  consumers would calculate different authority and readiness.
- Read all executions/manifests and filter after projection: rejected because
  cross-tenant rows would already have crossed the trust boundary.
- Infer historical ContentAsset state from the current mutable row: rejected
  because an unrecorded future mutation is not an as-of Fact.
- Add a second Product/media/QA truth store: rejected because it would break
  PIM and Listing authority.
- Reuse a private Seller ERP endpoint, Cookie, internal Token or copied media:
  rejected because owner authorization, Evidence, revocation and rights cannot
  be proven.
- Let an Agent queue media, approve QA, create a Manifest or publish from this
  workspace: rejected because a read projection cannot grant execution
  authority.

## Verification

Tests cover missing/invalid entity zero reads, exact tenant/store/as-of
filtering, multiple Products, deterministic replay, filtering/cursor/counts,
bad/latest-bad Evidence, future mutable asset state, input/template drift,
event gaps/illegal transition/time drift/latest-state mismatch, manifest
asset/execution/state/hash/time drift, truncation and suggestion-only Agent
output.

API/OpenAPI must return anonymous `401` and forbidden `403`. Web must implement
ready/no_data/partial/blocked/error/retry, real list/detail drilldown and
desktop/390 layouts without horizontal overflow. PostgreSQL/runtime, Alembic
single head, full backend/Web gates and fresh Harness/Graph verifier
observations are required before BAS-148 becomes `DONE_ENGINEERING`.
