# DATA-COV-001 — Global Source Domain Coverage Contracts

- Date: 2026-08-04
- Base commit: `36041d0b31d0b4cfdbf072f2fec7ca3cc4fa411c`
- Contract: `kjds-global-data-coverage-observation-v1`
- Delivery class: deterministic contract and synthetic fixture only
- Database/API/network/provider changes: none

## Objective and claim boundary

DATA-COV-001 establishes one global source-domain taxonomy and two machine-readable
contracts for measuring source coverage. It does not collect a source and it does not
create a second Evidence, Graph, retrieval, Product, Order, Finance, Fact, customer, or
operating-data authority.

`global` is a desired dimensional scope, not a completeness claim. `full coverage` is
valid only for an explicitly bounded and evidenced denominator:

`source-defined dataset × declared partition × requested time window × declared fields`.

When a source does not expose a denominator, the observation is `unknown`. A URL,
official document, CLI, SDK, connector candidate, contract-only adapter, or upstream
Observation never proves implementation, collection, or complete coverage.

## Architecture

```text
Source contract / NativeCaps / immutable Evidence
                    |
                    v
         SourceCoverageManifest
                    |
                    v
 GlobalDataCoverageWorkspace.validate(...)
                    |
                    v
 CoverageObservation (hash-addressed, no write authority)
```

The workspace is a pure deterministic validator. It reads the supplied objects,
validates their schemas, versions, hashes, chronology, lineage, native capabilities,
coverage counts and claim conditions, then returns one `CoverageObservation`. It has no
engine, repository, scheduler, network client, provider, connector or runtime binding.

## Global source-family matrix

The registry freezes all nine dimensions — region, country, language, industry,
platform, subject, event, time and data level — across thirteen source families:

| Family | Principal coverage | Example registered contracts | Current status meaning |
|---|---|---|---|
| `marketplace` | catalog, demand, order, fulfillment, settlement | Amazon SP-API Reports, eBay Sell Feed, Walmart, Mercado Libre, TikTok Shop, Ozon, Wildberries, Yandex Market, Alibaba.com, Temu, Shopee, Lazada | contract or blocked candidate only |
| `customs_trade` | reporter, partner, commodity, flow, tariff, period | UN Comtrade, WTO TTD, Eurostat Comext, US Census, UK HMRC, USITC, EU TARIC | contract only |
| `company_registry` | legal entity, filing, relationship, registration and verification | GLEIF Golden Copy, Companies House, SEC EDGAR, SAM.gov, VIES | contract only |
| `web_search` | bounded query, public page, owner domain and change observation | bounded public observation and owner export | contract only |
| `social_content` | content, comments, creators, topics and account metrics | official account API, owner export, bounded public observation | contract only |
| `ads_traffic` | campaign, creative, impression, click, conversion, spend and owned traffic | official reporting and owner analytics export | contract only |
| `supplier_catalog` | supplier, catalog, offer, RFQ and product identity | authorized B2B export, GS1 verification, owner quote export | contract only |
| `logistics` | shipment, package, route, milestone and exception | DHL, FedEx, Maersk | contract or blocked candidate only |
| `payments_fx_macro` | payment, settlement, balance, FX, macro series and revision | Stripe, PayPal, Adyen, Wise, ECB, Bank of Russia, BIS, World Bank | contract only |
| `regulation_standards` | regulation, standard, measure, effective interval and revision | official publication, WTO documents, EU TARIC measures | contract only |
| `ip_patents_research` | patents, trademarks, publications, citations and technology signals | WIPO, USPTO, OpenAlex, Crossref | contract only |
| `talent_jobs` | occupation, skill, wage, employment and job-demand observations | official statistics, bounded job-board observation, owner export | contract only |
| `crm_erp_finance_operations` | first-party lifecycle, product, order, inventory, finance, service and operations | owner CRM/ERP/finance/operations exports | contract only |

No registry entry is marked `implemented` in this delivery. Each future DATA-ADP ticket
must provide immutable implementation Evidence before changing that state.

## SourceCoverageManifest contract

The manifest freezes:

- source/family/contract/version/status and content-addressed NativeCaps;
- region/country/language/industry/platform/subject/event/time/data-level scope;
- bounded/enumerable/query-bounded/sample-only universe and denominator Evidence;
- capture, record, effective, expiry, freshness and review times;
- page expected/received/failed/duplicate counts, failed-page register and checkpoint;
- required field present/missing/unparseable/conflicting partitions;
- requested/effective UTC windows, gaps, overlaps and late arrivals;
- expected/observed/source totals and accepted/quarantined/failed/duplicate/suppressed
  conservation;
- conflict groups containing only opaque subject/value/interval hashes;
- access-contract and lineage references;
- requested claim scope and invalidation conditions.

Unknown page totals are not added to `source_total`. A known denominator without its
Evidence, a sample-only full claim, field overlap, page imbalance, record imbalance,
future/expired Evidence, hash drift, schema drift or cross-family source/capability
binding fails closed.

## NativeCaps contract

NativeCaps records what a source actually supports, rather than what a product page
claims: fields, dimensions, pagination mode and limit, checkpoint and ordering,
reported totals, historical/window depth, timezone semantics, stable identifiers,
tombstones, delta, export, bounded search, rate-limit knowledge, authentication mode,
unsupported fields, terms hash, purpose, retention and lineage.

The only source states are:

- `implemented`: requires immutable implementation Evidence;
- `contract_only`: a frozen integration candidate, not a collected source;
- `blocked`: a known contract whose implementation gate is closed;
- `unsupported`: the native source cannot supply the capability.

## CoverageObservation semantics

- `complete`: bounded denominator, complete page/field/window coverage, conservation,
  closed checkpoint, fresh data and no unresolved conflict;
- `partial`: records exist but a known page, field, window, conflict or quality gap
  remains;
- `unknown`: the source denominator is not exposed or evidenced;
- `missing`: a known denominator exists but expected records are absent;
- `blocked`: adapter, contract, freshness or integrity gate is closed;
- `unsupported`: native capability is absent;
- `not_applicable`: the source family does not apply to the declared scope.

`full_coverage_claim=true` is emitted only for `complete`, and its scope is always the
bounded source partition/window represented by the manifest. Every observation fixes
Fact, Decision, Approval, Permit, Pilot, Outbox, canonical Graph and external-write
flags to false.

## Privacy and source-of-truth controls

- No Cookie, credential, secret, personal contact, customer row or raw source payload is
  permitted in either schema or the synthetic fixture.
- Conflict entries retain opaque hashes and preserve all candidate observations.
- The module cannot promote Evidence to a business fact or mutate a canonical graph.
- Existing BAS-178/BAS-179 observations may later be referenced through Evidence and
  lineage; their source registries remain authoritative for social and Russia domains.
- BAS-173 may later consume a frozen corpus projection; it does not call these source
  adapters directly.

## Deterministic verification

The focused Gate verifies:

1. thirteen source families, nine dimensions and globally unique source IDs;
2. bounded denominator and full-claim requirements;
3. record and page conservation;
4. page, field, window, conflict, freshness, checkpoint and content-hash failures;
5. candidate-versus-implemented state separation;
6. schema/status/version/native-capability and cross-family drift rejection;
7. two identical validations produce the same observation hash;
8. all promotion and write-authority flags remain false;
9. both JSON schemas are valid Draft 2020-12 documents;
10. the fixture contains no customer or secret material.

Verification on the isolated worktree at base
`36041d0b31d0b4cfdbf072f2fec7ca3cc4fa411c`:

```text
uv run python -m pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-data-cov-001 tests/test_global_data_coverage.py tests/test_global_source_domain_registry.py
.................................                                        [100%]
33 passed in 0.27s

uv run ruff check apps/control_plane/global_data_coverage.py tests/test_global_data_coverage.py tests/test_global_source_domain_registry.py
All checks passed!

Draft 2020-12 schema + fixture validation
JSON_FILES=4 PARSE=PASS SCHEMAS=PASS FIXTURE=PASS
REPLAY_HASH_1=7cf7b5af962983e7fe4d21a7798c77e817d3f0194b9050dd660f853b1a9db995
REPLAY_HASH_2=7cf7b5af962983e7fe4d21a7798c77e817d3f0194b9050dd660f853b1a9db995
REPLAY_MATCH=True
VERDICT=blocked FULL=False

uv run python scripts/verify_secrets.py
Secret scan passed: 1275 non-ignored worktree files and 1304 historical paths checked

git diff --check
exit 0
```

## Independent-review remediation

The follow-up review identified two trust inversions that are now closed:

- Runtime validation pins the caller-supplied snapshot to the repository-owned
  canonical registry by exact canonical content and hash. A constructor-injected
  registry exists only as an explicit trusted test seam and is defensively copied.
  Registry contract ID and cutoff chronology are fixed, and the selected source
  contract must equal the frozen trusted contract.
- A known denominator binds the universe and claim to the same Evidence ID and
  SHA-256. That ID must resolve exactly once in the manifest Evidence list. Duplicate
  IDs, conflicting hashes, substituted Evidence, Grade C/D full-claim support,
  `effective_at > recorded_at`, future recording and expired Evidence all fail closed.

The original independent repro—rehashed caller registry, fabricated implementation
reference and missing denominator Evidence—now produces:

```text
REHASHED_REGISTRY_AND_MISSING_DENOMINATOR=REJECTED
ERROR=registry snapshot is not the trusted canonical registry
```

## Next tickets

- `DATA-COV-002`: after the current migration lease is released, design the append-only
  coverage ledger. The reviewed candidate has separate manifest, NativeCaps, field,
  page, window, conflict, lineage and event relations; it stores hashes/counts rather
  than domain payloads and uses populated downgrade fail-closed.
- `DATA-ADP-*`: one independently gated source-family adapter per ticket.
- `DATA-COV-003`: preserve multi-source conflict observations and independent
  resolutions without automatic Fact promotion.
- `RET-COV-*`: expose only frozen eligible corpus hashes to retrieval benchmarking.
- `VIS-COV-001`: read-only source → field → page → window → Evidence coverage console.

Rollback for this ticket is removal of the eight new contract/test artifacts. It has no
database state, runtime composition, API route, scheduler, dependency or external side
effect.
