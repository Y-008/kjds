# ADR-0059: Browser Capture Inbox

- Status: Accepted for BAS-138 implementation
- Date: 2026-07-29
- Owners: Market Intelligence, Evidence, Identity and Web Platform
- Requirements: BR-003–004, BR-007, BR-081–086, BR-093, BR-112
- Depends on: ADR-0038, ADR-0041, ADR-0053–0058

## Context

KJDS already admits an authenticated Marketplace Observation only after one
current tenant/entity/store grant exists. That is correct for a native
Observation, but the real operating scope currently has no entity authority.
Discarding a user-initiated 1688/Ozon page capture until that grant exists
loses useful original Evidence; copying `tenant_ref` into `entity_ref` would
invent authority.

Seller-tool references demonstrate convenient page-side capture, but their
broad host access, cookies, localStorage, internal API interception and
all-pages content scripts are not acceptable KJDS runtime patterns.

## Decision

### One deep staging seam

`BrowserCaptureInbox` owns admission, normalization, immutable Evidence,
idempotency, quarantine and promotion readiness behind one versioned capture
envelope. Callers do not write Marketplace Observation, Supplier Offer, actual
cost, Product, Listing or execution repositories.

The first contract is `kjds-browser-capture-envelope/1.0` and accepts only an
explicit user-initiated active-tab visible-DOM capture from an implemented
source adapter. It freezes:

- authenticated tenant and authorized store;
- `entity_ref=null` plus `entity_scope_status=no_data` when no current grant
  exists, never a tenant-derived entity;
- source URL/host, observed time, adapter/version/contract hash and acquisition
  policy;
- exact item identity/variant, quantity, MOQ and explicit unit versus checkout
  total price semantics where present;
- normalized payload hash, immutable C-grade Evidence ID/hash, actor and
  idempotency key.

Missing entity authority yields `quarantined`, not a failed capture. A current
entity grant yields `pending_independent_binding`; neither state is a formal
Observation or business fact.

### Promotion is a different capability

Promotion readiness is computed dynamically from the current entity grant,
immutable source Evidence integrity, independent exact-scope Evidence binding,
adapter drift and payload semantics. Until all are ready, the inbox returns
blockers, Owner, SLA and next workspace. This slice exposes no promotion write
route. A later slice may invoke the existing native Observation authority
through this module; it may not bypass it.

### Minimal browser permissions

The KJDS Manifest V3 helper uses only `activeTab`, `scripting` and
`storage` (session storage). It has no cookies, localStorage transfer,
`webRequest`, declarative network interception, broad host permissions,
`<all_urls>`, private/internal API calls or CAPTCHA behavior.

The user clicks the extension on the current 1688/Ozon tab. The helper reads a
bounded visible-DOM/structured-data projection, stores one pending envelope in
extension session memory and opens the authenticated KJDS inbox. The KJDS page
receives it through an explicit `externally_connectable` handshake, previews
the server semantics and requires a separate “save Evidence” click. Only the
same-origin KJDS page calls the authenticated control plane. A successful
receipt clears the extension session envelope.

### Truth and execution boundaries

- Public/displayed price is an observation, never Supplier Offer or actual
  procurement cost.
- Checkout price requires exact variant, purchase quantity, MOQ,
  checkout-verification and explicit tax/domestic-freight boundaries.
- Comments, ratings and page counters are not sales.
- Page media remains an unverified external reference and is not copied into
  owned ContentAsset.
- Capture does not create Product, SKU, Listing, Approval, Permit, purchase,
  payment, advertisement or any Ozon/1688 write.
- `external_write_allowed=false` is invariant.

## Data and compatibility

Forward-only migration 0071 adds an append-only
`browser_capture_inbox_submissions` table with complete-or-empty entity scope,
adapter and Evidence tuples, per-tenant/store idempotency, content hashes and
database checks. Existing Observation/Evidence rows are not changed.

Legacy `/v1/marketplace-observations` behavior remains unchanged. The new
routes are:

- `POST /v1/browser-capture-inbox/preflight` — zero-write normalization and
  dynamic authority projection;
- `POST /v1/browser-capture-inbox/submissions` — internal Evidence staging;
- `GET /v1/browser-capture-inbox/submissions` — exact tenant/store projection.

## Verification

BAS-138 must prove:

1. anonymous access is 401 and unauthorized store is 403;
2. missing entity scope persists `entity_ref=null` and status `quarantined`;
3. exact same request replays, while same-key payload drift conflicts;
4. source host, adapter policy, price scope, quantity and future/stale observed
   times fail closed;
5. immutable Evidence bytes/hash equal the normalized envelope;
6. bad Evidence or rule/adapter drift blocks promotion readiness;
7. PostgreSQL rejects partial entity/adapter/Evidence tuples;
8. no external write, Supplier Offer, actual cost, Product, Listing, Approval
   or Permit is created;
9. empty DB base→0071 and current real DB 0070→0071 preserve existing
   Observation/Evidence hashes;
10. Web tests/build, API/OpenAPI, containers and desktop/390 acceptance pass;
11. a real user-initiated Chrome capture from an allowed 1688 page reaches the
    authenticated KJDS preview and immutable inbox receipt without ordering,
    messaging or bypassing CAPTCHA.

## 2026-08-07 amendment: 1688 full variant matrix

BR-144 extends the same inbox and extension; it does not introduce a second
crawler, Supplier source of truth or browser permission model. The accepted
`best_solution/1.0.0` comparison is:

- widening the extension to host permissions/network interception would make
  background crawling easier, but fails the existing permission, privacy,
  revocation and long-term maintenance constraints;
- installing a separate all-site crawler duplicates the ingestion envelope,
  Evidence, scope, retry and quarantine truth and has the highest replacement
  cost;
- deferring preserves code but leaves advertised-minimum price bait able to
  contaminate sourcing screens;
- selected: keep `activeTab+scripting+storage(session)`, parse only the current
  document's visible DOM and serialized SSR `window.context`, emit one item per
  SKU through the existing envelope, and have the server recompute the variant
  price summary. This is reversible, immediately useful and keeps the lowest
  operational/security cost among feasible options.

The extension may read only seller/product fields already delivered in the
active document. It must ignore buyer `loginId`, client IP, Cookie,
localStorage and network/API response bodies. For a 1688 product page it
records, when present:

- exact `offer_id`, `sku_id`, `spec_id`, variant text and public unit price;
- public stock/sold signals, MOQ, mix-order quantity, unit, category, weight,
  product attributes, main/variant image references and page price range;
- supplier company/login identity plus public card/service score, three-month
  repeat rate, goods grade, good-rate and review-count signals;
- capture provider/version, source kind, discovered/captured counts and
  truncation.

`BrowserCaptureInbox` contract 1.2 accepts the optional merchant and capture
coverage projection and derives per-offer variant groups, min/max price and
the exact minimum-price variant keys from normalized items. It never trusts a
client-supplied "cheapest SKU" conclusion. Store pages may contribute at most
50 current-page public product cards; any additional discovered cards are
reported as truncated and their variant remains `unselected`.

Unlike candidate pages, a product detail matrix is all-or-nothing up to 500
rows: `discovered_count = captured_count = item_count`, `truncated=false`, and
every row has stable offer/SKU/spec identity and price. A missing row or a
matrix above the hard limit fails instead of being labeled complete.

The decision is invalidated for review if 1688 removes the serialized SSR
state, the provider cannot bind SKU IDs to displayed variants, the 50-item
envelope no longer preserves source totals, or a permitted official export/API
offers better evidence at lower total risk. Review date: 2026-09-07. Any wider
browser permission, background pagination, supplier contact, purchase or
formal-fact promotion requires a separate approval and acceptance Evidence.

BR-145 adds no new seam. The same envelope exposes two capture kinds:
`product_detail_variant_matrix` produces exact internal ERP staging rows, while
`search_result_candidates` and `store_catalog_candidates` produce offer-only
rows with `requires_detail_enrichment`. The server includes `sku_id` and
`spec_id` in the natural key, verifies URL/offer, supplier and coverage
conservation, and recomputes all price summaries. It groups prices only when
server-normalized comparison dimensions are equal; missing dimensions create
isolated `requires_dimension_alignment` groups. Consequently a three-piece
3.90 CNY variant can be discovered as the offer minimum but cannot be compared
as a substitute for a six-piece 9.90 CNY BOM.

The keyword-search button only opens a normal 1688 search tab from the active
page title. It does not claim official same-product identity. Search cards are
discovery candidates until their own detail pages provide exact SKU evidence.

The list read model exposes `kjds-sourcing-comparison/1.0` across captured
offers. It selects only the newest intact detail snapshot for each
marketplace/offer tuple, so recaptures never inflate supplier count. If the
same offer has different supplier identities across snapshots, that offer is
excluded as supplier drift rather than represented as two suppliers.
Rows must have exact SKU/spec identity, category and trade unit plus at least
two discriminating dimensions from pack count, size and material. The default
reference quantity is one: out-of-stock rows, unknown MOQ, MOQ above one and
non-public-unit price bases remain visible but are ineligible for the minimum
rank. The result retains every exact row and source hash while explicitly
keeping freight, tax, formal cost and external write false.

The current SSR varies between strict JSON, JavaScript object literals with
unquoted numeric keys, array SKU matrices and duplicate `$ref` placeholders.
The provider never evaluates serialized page code. It quotes only numeric
object keys outside strings, parses JSON, considers every bounded matrix
candidate, and accepts only a matrix whose every row has SKU, spec and price.
Arrays and objects are equivalent containers; partial and `$ref` matrices fail
closed.
The current-document parsing approach was informed by the MIT-licensed
`superjack2050/1688-cli` project; KJDS retains a small independent adapter and
license/source attribution rather than copying its browser/session framework.

## Consequences

KJDS can accumulate real page observations before entity admission without
lying about authority. The inbox is intentionally not yet a nationwide
scanner, Supplier Offer, CM3 calculation or Ozon listing pipeline; those are
separate M1–M3 capabilities and Release Gate facts.
