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

Both original and promotional SSR SKU matrices are considered. A promotional
`tradeModel.skuMap` is accepted only if every row contains its own exact
SKU/spec identity and price; values from search cards, base ranges or a
different incomplete matrix are never used to fill a row. ERP staging contract
1.1 retains the complete normalized per-SKU observation plus flattened
identity, price, MOQ, availability, specification, comparison, stock, sales,
tier, supplier public profile, capture provider/coverage, source-time and hash
fields so the browser-to-ERP projection is lossless and auditable.
Pack-count extraction accepts both Chinese product titles and the English
translations that 1688 may serve (`六件套`, `6-piece`, `six-piece`, `6 pcs`);
it never equates different materials or missing dimensions merely because the
count matches.
Oxford-cloth comparison uses a language-neutral `oxford_cloth` family and a
separate ordered finish signal. `防水加厚牛津布` and `thickened waterproof
Oxford cloth` can therefore align as `thickened+waterproof`, while plain
Oxford cloth remains a different dimension set. Raw supplier wording remains
unchanged in `specifications`.

The collection workspace compares the newest intact detail snapshot for each
offer across suppliers. Each SKU retains only quantity tiers that can be bound
to that row's own price; duplicate offer-level quantity buckets for different
SKU/BOM prices are isolated instead of copied across the matrix. A selected
reference quantity chooses the highest observed tier whose minimum quantity is
not greater than the requested quantity. Unknown/high MOQ, unavailable stock,
missing applicable tiers, supplier-identity drift and incomplete dimensions
remain visible but cannot enter the minimum rank.

The parsing approach was informed by the MIT-licensed `1688-cli` project
(`superjack2050/1688-cli`); KJDS keeps its own minimal current-document adapter
and the MIT attribution in repository Evidence.

The captured price remains a C-grade public observation. It is not a Supplier
Offer, actual cost, Product, Listing, Approval, Permit or external write. ERP
transfer here means immutable internal staging rows; formal records still need
the existing independent binding and promotion controls.
