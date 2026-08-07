# KJDS Browser Capture

Load this directory as an unpacked Manifest V3 extension only for local KJDS
acceptance.

The helper has exactly three permissions:

- `activeTab`
- `scripting`
- `storage` (session-only pending envelope)

It has no `host_permissions`, content scripts, cookies, localStorage transfer,
network interception, internal API calls, `<all_urls>` access or CAPTCHA
behavior. A capture requires an explicit click on the current 1688/Ozon
product/search/store tab, followed by a separate authenticated save click in
`http://127.0.0.1:3000/capture-inbox`.

On a 1688 product detail page, provider 1.0 reads the serialized SSR
`window.context` text already present in the active document without executing
it. It accepts complete object/array matrices, safely normalizes JavaScript
numeric object keys and ignores `$ref` placeholder matrices. Every accepted
row binds `offer_id + sku_id + spec_id + variant_key` to its
own public price, stock/sold signals and source URL. Search/store pages stage at
most 50 offer-only candidates and explicitly require detail enrichment before
exact comparison or ERP use. KJDS recomputes minimum-price variants and only
compares rows whose normalized dimensions (for example pack count, size and
material) are equal. Auxiliary variants such as logo customization, samples,
freight and price-difference links remain exact rows but cannot inherit the
title BOM or enter a product-price rank.

The collection workspace compares the newest intact detail snapshot for each
offer across suppliers. At the default reference quantity of one it excludes
unknown/high MOQ, unavailable stock, supplier-identity drift and incomplete
dimensions from the minimum rank while keeping their rows visible.

The parsing approach was informed by the MIT-licensed `1688-cli` project
(`superjack2050/1688-cli`); KJDS keeps its own minimal current-document adapter
and the MIT attribution in repository Evidence.

The captured price remains a C-grade public observation. It is not a Supplier
Offer, actual cost, Product, Listing, Approval, Permit or external write. ERP
transfer here means immutable internal staging rows; formal records still need
the existing independent binding and promotion controls.
