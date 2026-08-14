# ADR-0065: Native exact-scope sourcing intelligence workspace

- Status: Accepted for BAS-145 implementation
- Date: 2026-07-29
- Owners: Sourcing, Market Intelligence, PIM, Evidence, Profit and Agent Team

## Context

Accio's current official public surface groups product discovery, supplier
matching, hot-selling analysis, AI-assisted inquiries and business research
into one sourcing workflow. This is a market JTBD benchmark, not an authority
for KJDS operating facts:

- <https://www.accio.com/about-us>
- <https://www.accio.com/blog/getting-started-with-accio>
- <https://www.accio.com/blog/a-step-by-step-guide-to-searching-products-and-suppliers-with-accio>

KJDS already has scoped market observations, marketplace Catalog, Canonical
Product/PIM, versioned Batch Opportunity research, governed RFQ packages,
dispatch proof, supplier quote authority and fifteen-component downside CM3.
Exposing them as unrelated APIs or recomputing them in a page would create a
shallow integration surface and competing readiness rules.

## Decision

Add one deep read module, `ScopedSourcingIntelligenceWorkspace`, with one public
projection interface:

`project(principal, entity_scope, store_ref, as_of, ...)`.

It composes, but does not replace:

- `ScopedPimWorkspace`;
- `ScopedBatchOpportunityAuthority.market_radar(...)`;
- `ScopedBatchOpportunityAuthority.latest(...)`;
- `ScopedEvidenceAuthority`;
- existing governed RFQ package, RFQ dispatch and supplier quote authorities.

The module owns exact-scope admission, upstream contract/hash/as-of checks,
bounded raw artifact scan after scope admission, Evidence binding validation,
deterministic filters/cursors/counts, Canonical Product association, exact
identity research cohorts, three-quote/RFQ readiness, native candidate and
fifteen-component downside CM3 projection, source gaps, blockers,
Owner/SLA/next, and stable snapshot/artifact hashes.

Missing or invalid entity authority performs zero upstream/raw reads. Any bad
latest Evidence, upstream scope/hash drift or unbound/conflicting RFQ/quote
Evidence fails closed and discloses no affected business payload. Observation,
estimate, formal quote, downside screening and actual settled cost remain
different authority levels.

The Agent artifact may suggest research or create internal task proposals. It
cannot contact suppliers, dispatch RFQs, accept quotes, create Supplier Offers,
purchase orders, payments, Products, Listings, Approval or Permit, and cannot
write externally.

Accio is an optional public/authorized Adapter source and a market benchmark.
KJDS will not use private endpoints, cookies, internal tokens, CAPTCHA bypass,
or third-party UI/code. Removing Accio must leave all Canonical Facts,
Evidence, decisions and outcomes intact.

## Rejected alternatives

- Treat Accio as the runtime sourcing brain: rejected because it would make a
  third party the operating authority.
- Reverse engineer Accio, 1688, Ozon or Seller ERP private interfaces:
  rejected for authorization, security, stability and provenance reasons.
- Join RFQ, quote, PIM and opportunity data in the Router, Agent prompt or Web:
  rejected because callers would duplicate scope and readiness logic.
- Add a new supplier/product truth store or a progress-only migration:
  rejected because the slice is a read composition over existing authorities.

## Verification

Interface tests cover missing entity/zero reads, unauthorized store, upstream
contract/scope/as-of/hash drift, latest bad Evidence, unbound RFQ/quote
Evidence, exact identity association, three-quote readiness, fifteen-component
downside projection, deterministic filtering/cursor/counts/hash and the
no-write Agent envelope. API/OpenAPI, anonymous 401, forbidden 403, Web
ready/no_data/blocked/error/retry, PostgreSQL, desktop/390 browser Evidence and
Harness/Graph observation complete BAS-145 engineering evidence.
