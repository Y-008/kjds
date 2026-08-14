# ADR-0042: Scoped Market Radar and Candidate Normalization

Date: 2026-07-28<br>
Status: Accepted for BAS-118<br>
Requirements: BR-094<br>
Depends on: ADR-0031, ADR-0038, ADR-0039, ADR-0041

## Context

BAS-117 admits official, authorized and allowed-public sources into the existing Catalog and
Marketplace Observation truth modules. M1 still needs one truthful market-analysis projection that
does not:

- count several sellers/listings as several products;
- mix an own Listing price with an external competitor cohort;
- mix different exact variants or currencies;
- treat an observed 1688 price as a Supplier Offer or actual cost;
- infer sales from comments, reviews or public page signals;
- scan another tenant/store before filtering current facts;
- duplicate the matching and economics rules already owned by Batch Opportunity.

The Ultimate Product Blueprint requires Market Radar to expose unique exact identities,
competitor/supplier cohort sizes, price bands, source Evidence, freshness and drilldown. Research
must remain available when later economics/content/execution authorities are absent, while Pilot
approval and publication remain fail-closed.

## Decision

Extend `ScopedBatchOpportunityAuthority` with a read-only `market_radar` projection. It will reuse
the existing scoped Observation and Catalog authorities and the exact-identity rules from
`BatchOpportunityWorkspace`; no second candidate repository or client-side matcher is introduced.

The query contract freezes:

```text
tenant + entity + store + as_of + timezone + display_currency
+ accepted_source_grades + max_age_hours + target_purchase_quantity
+ bounded page_size/max_rows
```

The service:

1. resolves the authenticated tenant/store and one current entity grant before reading;
2. reads Ozon and 1688 current facts through `ScopedMarketplaceObservationAuthority`, so scope
   filtering and independent Evidence binding occur before projection;
3. reads own Listing identity only through `ScopedMarketplaceCatalogAuthority`;
4. groups by the server-owned `candidate_key`, which is the canonical exact product identity plus
   exact variant;
5. separates `own_listing_current_facts`, external Ozon competitors and 1688 supplier options;
6. reports currency-isolated p25/p50/p75 price bands, never cross-currency arithmetic;
7. reports exact-identity listings, unique competitor sellers, unique supplier identities,
   checkout-comparable supplier rows and unresolved rows as separate funnel counts;
8. freezes Evidence IDs, source grade/semantic authority, freshness and source gaps on each cohort;
9. returns `ready`, `partial`, `no_data` or `blocked` with Owner/SLA/next action;
10. performs no candidate scoring, Offer creation, formal CM3, Approval allocation, Permit or
    external write.

`target_purchase_quantity` comes from the request/policy. Supplier checkout rows are comparable
only when the exact observed quantity equals the target and MOQ does not exceed it. A 100-unit
checkout price cannot be used for a 3-unit first Pilot. Other supplier rows remain visible as
alternatives/RFQ evidence without entering the comparable price band.

`display_currency` is a display/request attribute in BAS-118. The radar does not convert
currencies. A cohort returns one price band per source currency and a source gap when a requested
single-currency rollup would require an Evidence-bound FX row. Formal CNY economics remain owned by
the scoped Batch Opportunity/Profit modules.

## API and UI

`GET /v1/market-radar` is authenticated and read-only. The Commerce OS adds a Market Radar section
fed only by this response. It displays:

- observed listings versus unique exact identities;
- own Listing, competitor and supplier cohort counts;
- price bands by currency;
- freshness and source-grade coverage;
- unresolved/no-data/blocked reasons;
- Evidence drilldown references and the next governed workspace.

The 390px and desktop UI must not create synthetic trends or locally calculate prices, candidate
keys, ranks or CM3.

## Authority boundary

- Observation remains Observation.
- Public 1688 price is not a Supplier Offer, purchase order or actual cost.
- Public Ozon price/review/comment is not an order, sale or settlement.
- Candidate identity does not imply economics readiness.
- Research readiness does not imply content, approval, publish or scale readiness.
- All Agent outputs are read-only research artifacts.
- Ozon, supplier, purchase, payment, price, inventory and advertising writes remain false.

## Acceptance

1. Same identity and exact variant across three Ozon sellers produces one cohort and three
   competitor listings, not three candidates.
2. Same product with two variants produces two cohorts and two candidate keys.
3. Own Catalog Listing is separated from competitors and its price never becomes competitor p50.
4. Duplicate supplier rows from one supplier count as one supplier identity while preserving row
   Evidence.
5. Target quantity 3 excludes a 100-unit checkout row from the comparable supplier band.
6. Different currencies produce separate price bands; the client never converts them.
7. Stale or disallowed-grade rows remain disclosed as gaps and cannot become ready research input.
8. Missing entity authority performs no Observation/Catalog read and returns `no_data`.
9. Anonymous and cross-store requests return 401/403.
10. Fixed `as_of` produces a deterministic snapshot hash.
11. Bad or cross-scope Evidence produces `blocked`/`partial` without details leakage.
12. OpenAPI, Web composition, desktop and 390px browser acceptance prove the server-owned
    projection and closed external-write boundary.

## Consequences

This slice provides a usable M1 market lens over real scoped data without claiming nationwide/full
market coverage or profitability. A later slice may add Seller API/official-export demand fields,
incremental schedules and Evidence-bound FX display conversion, but it must consume this same
identity/cohort contract.
