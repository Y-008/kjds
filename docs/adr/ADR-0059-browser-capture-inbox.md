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

## Consequences

KJDS can accumulate real page observations before entity admission without
lying about authority. The inbox is intentionally not yet a nationwide
scanner, Supplier Offer, CM3 calculation or Ozon listing pipeline; those are
separate M1–M3 capabilities and Release Gate facts.
