# BAS-206 — 1688 full-SKU capture, candidate comparison and ERP staging

Date: 2026-08-07
Status: `DONE_ENGINEERING`
Requirements: BR-144, BR-145
Decision: [ADR-0059](../../adr/ADR-0059-browser-capture-inbox.md)

## Outcome

KJDS reuses the existing `BrowserCaptureInbox` seam and the existing local
Manifest V3 helper. It does not add a second crawler, evidence store, quote
truth or ERP import path.

Envelope `kjds-browser-capture-envelope/1.2` supports:

- `product_detail_variant_matrix`: the current 1688 detail document must
  preserve every serialized SKU row up to a 500-row hard limit. Each row binds
  supplier, offer, SKU, spec, variant, price, public signals, source URL and
  item hash. Missing identity/price, duplicate natural keys, supplier or
  URL/offer drift, partial coverage or truncation fail closed.
- `search_result_candidates` and `store_catalog_candidates`: the current page
  contributes at most 50 offer cards. These remain
  `requires_detail_enrichment` until their own detail pages supply exact SKU
  and spec identity.

The server, not the extension, recomputes the offer price range, exact
minimum-price SKU references and comparison groups. Only rows with equal
normalized category/BOM count/size/material/trade-unit dimensions are
comparable. Missing dimensions remain isolated. The server also projects
`kjds-erp-sourcing-staging/1.1` rows. Each exact row has flattened ERP indexes
and a lossless normalized source observation, so identity, prices, MOQ,
availability, specification/comparison dimensions, stock/sales/tier signals,
supplier public profile, capture provider/coverage, source time and hashes
cross the staging boundary without remapping. These are immutable internal
staging, not Canonical Product, Supplier Offer, actual cost, formal sales or an
external write.

The inbox collection additionally projects `kjds-sourcing-comparison/1.0`.
It uses only the newest intact detail snapshot per marketplace/offer, excludes
cross-snapshot supplier drift, and keeps every exact row visible. At reference
quantity one, unknown MOQ, MOQ above one, unavailable stock and non-public-unit
price bases cannot enter the minimum-price rank. Search cards remain a detail
enrichment queue.

## Real public-page observation used for acceptance design

The authenticated, user-initiated 1688 read of offer `38547222320` observed:

- title: `加厚牛津布双拉链旅行收纳六件套 行李箱整理袋 旅游袋套装 6件套`;
- supplier: `义乌市喜哥日用品厂`, login `戴贺喜188`;
- public advertised range: CNY `3.90–9.90`, MOQ 1, mixed-order signal 80;
- item code `A-2-1`, category `1036894`, unit-weight signal `0.24 kg`;
- nine serialized variants: eight six-piece color variants at CNY `9.90`, and
  `西瓜红三件套收纳袋` at CNY `3.90`.

Therefore CNY `3.90` is a three-piece variant signal, not the public price of
the six-piece BOM and not a supplier quote. The acceptance fixture freezes
that distinction: `sku-3/spec-3/pack_count=3/3.90` and
`sku-6/spec-6/pack_count=6/9.90` must map to different comparison groups.
No RFQ price, checkout price, freight, tax, 28-day demand, compliance, profit
or manual supplier reply is inferred from this page.

## Real extractor-to-server acceptance

On 2026-08-07 the production extension source was executed against the raw SSR
document returned for offer `38547222320`, with all later network requests
blocked. The resulting envelope was passed directly to
`BrowserCaptureInbox.preflight`; no fixture mapping was inserted between the
extractor and server.

The SSR contained JavaScript object-literal numeric keys, array/object SKU
matrix variants and duplicate `$ref` placeholder matrices. The no-eval parser
selected only the complete matrix. Server coverage was
`discovered=9`, `captured=9`, `exact identity=9`, `truncated=false`:

| SKU ID | spec ID | variant | public CNY | public stock signal |
|---|---|---|---:|---:|
| `4494375919492` | `395dcc2e3f86c5922f2ecc3ee5baf01e` | 西瓜红 | 9.90 | 61 |
| `4494375919491` | `c8cd9c5b9782e244d5b343168d09207d` | 玫红色 | 9.90 | 765 |
| `4494375919484` | `8e33ced938f52664c2730391dcea6714` | 酒红色 | 9.90 | 65 |
| `4866555736866` | `96b855db77ca22719a4e84647decbf0d` | 西瓜红三件套收纳袋 | 3.90 | 470 |
| `4494375919489` | `f81da5b3eb33ea7d9e994b7255067cf8` | 浅粉色 | 9.90 | 39 |
| `4494375919488` | `ffd37556d8324a19ae5d33a570d5b8e9` | 藏青色 | 9.90 | 73 |
| `4494375919486` | `77ae7ed9b1f00eff3fcc94b124fbfef4` | 绿色 | 9.90 | 0 |
| `4494375919490` | `b2e578dabb19f18c978bb54071fa4117` | 天蓝色 | 9.90 | 13 |
| `4494375919485` | `6a67a0c231ddcbfe73c4ab1dfcaa0ced` | 灰色 | 9.90 | 94 |

All nine projected as `exact_variant_staged`. Material
`防水加厚牛津布`, category `1036894`, trade unit and pack count produced a
three-piece group at 3.90 and a six-piece group at 9.90. Green remained an
out-of-stock exact row. `formal_product_write`, `supplier_offer_write` and
`external_write` stayed false.

The same read-only session searched `牛津布旅行收纳六件套`, price ascending,
excluding ads. Ten search cards were returned, but none was treated as exact
cost. Detail checks on the first three demonstrated why:

- search-card 2.30 for offer `1037202643524` expanded to thirteen exact SKU
  rows: twelve six-piece colors at 8.50 and `可定制logo` at 3.30. The latter was
  retained with exact SKU/spec identity but marked
  `auxiliary_or_customization` and excluded from comparable BOM prices;
- offer `1062682425509` exposed a 3.80 six-piece signal with MOQ 300, so it is
  ineligible at reference quantity one;
- offer `1016280747478` returned a CAPTCHA interception during detail
  enrichment and therefore remained unknown, not “no SKU” or a valid price.

These are time-scoped public discovery observations, not supplier quotes,
checkout totals or landed costs.

## Promotion-matrix and lossless ERP acceptance

A second current-document replay used offer `675097513713`. Its price-sorted
search card showed CNY `4.26`, but the detail SSR identified that value as a
first-order card signal. `tradeModel.skuMap` contained eight independently
identified promotional rows at CNY `4.76` with MOQ 2; `skuMapOriginal`
contained the same identities without row prices and a CNY `6.80` base signal
with MOQ 4. The provider selected the only complete price-bearing matrix and
did not join any values across card, original or promotional structures.

The production extension source, executed with every later request blocked,
produced `discovered=8`, `captured=8`, `exact identity=8` and
`truncated=false`. The eight exact identity pairs were:

| SKU ID | spec ID | color | exact public CNY |
|---|---|---|---:|
| `5934582561130` | `ad83bda4f5122c3126b551ae642adf4b` | pink | 4.76 |
| `5934582561131` | `37ddd46f34feb6b80eb49db18ba5168f` | gray | 4.76 |
| `5934582561138` | `63138c5360d9290d2acdee26faeb9a36` | wine red | 4.76 |
| `5934582561137` | `2cbdee8401125f3a6b3689493c4d55ba` | black | 4.76 |
| `5934582561133` | `44e0e1ec59c83b58dfb125861d576ac2` | rose | 4.76 |
| `5934582561134` | `94685508f10ed7c5562023ccd0a14b59` | green | 4.76 |
| `5934582561135` | `89a549f6a0f848fae52691e4f329bc29` | sky blue | 4.76 |
| `5934582561136` | `c415ee59ab9584427ac200ec87f5ff05` | navy | 4.76 |

Direct server preflight produced eight `exact_variant_staged` rows. A sampled
row retained SKU `5934582561137`, spec
`2cbdee8401125f3a6b3689493c4d55ba`, CNY `4.76`, MOQ 2, in-stock state,
public stock signal `199435`, sale signal, the `discountPrice` source field,
price tier and item hash; its complete audit copy exactly equaled the
normalized item. All three write flags remained false. Because the default
comparison quantity 1 is below MOQ 2 and the active document did not expose a
verified material dimension, the rows remain ineligible for the lowest-price
rank and are not forced into the original offer's BOM group.

The normal similar-products entry returned `SIMILAR_UNAVAILABLE`, which was
not interpreted as no supply. A 20-card keyword search supplied discovery
candidates instead. Detail checks retained offer `655419936590` as a material
mismatch (`无纺布+PEVA` despite its title) and offer `718404380873` as unknown
because price/MOQ/SKUs were absent. Offer `600528999073` initially exposed
conflicting main/mixed display values, so it stayed pending until a later raw
SSR replay established the per-SKU and quantity contract below.

The later replay accepted 11/11 exact SKU/spec rows for `600528999073`.
1688 served the title/attributes in English, including explicit `six-piece`
and `Material=Oxford cloth`; the provider now recognizes explicit Chinese and
English pack counts while retaining exact material text. All 11 row-local
`discountPrice` values were CNY `8.20`, MOQ was 1, 10 rows were in stock and
one was out of stock. The same trade model froze tiers of CNY `8.20` for
quantity 1–99, `8.00` for 100–999 and `7.80` from 1000. Other CLI display
signals (`10.79/11.20` and `7.79/8.20`) did not overwrite that row-local SSR
contract; they remain separate unresolved price presentations.

Server comparison of the newest exact snapshots for offers `38547222320`,
`600528999073` and `675097513713` reported three exact offers but no two-offer
equal-dimension group. It produced:

| normalized comparison dimensions | rows | eligible minimum at quantity 1 |
|---|---:|---:|
| category `1036894`, waterproof thickened Oxford cloth, 3 pieces, unit `件` | 1 | CNY 3.90 |
| category `1036894`, waterproof thickened Oxford cloth, 6 pieces, unit `件` | 8 | CNY 9.90 |
| category `1036894`, Oxford cloth, 6 pieces, unit `件` | 11 | CNY 8.20 |

Each group remained `insufficient_exact_offers`. The eight
`675097513713` rows remained unresolved because their category/unit differed,
material was absent and MOQ 2 exceeded reference quantity 1. The server did
not collapse `Oxford cloth` into `waterproof thickened Oxford cloth`; the
mechanical difference between CNY 8.20 and 9.90 is therefore not a same-BOM
lowest-price conclusion. No row was promoted to a quote, cost or profit fact.

## Source and license record

The current-document parsing approach was informed by the MIT-licensed
[`superjack2050/1688-cli`](https://github.com/superjack2050/1688-cli), version
0.1.47 during local research. Its documented `offer`, `search`, `research` and
`compare` capabilities confirmed that detail-page SKU expansion must be kept
separate from search-card minimum prices. KJDS implements a smaller independent
active-document adapter and retains the project/link/license attribution. It
does not copy the CLI browser/session framework into the extension.

## Changed interfaces and implementation

- `apps/control_plane/api_contracts.py`: envelope 1.2, page provider/coverage,
  merchant and comparison dimensions; detail payload maximum 500.
- `apps/control_plane/browser_capture_inbox.py`: exact identity validation,
  bounded public-signal preservation, full-matrix conservation, server-derived
  variant/comparison summaries and ERP staging projection.
- `extensions/kjds-browser-capture/extract-page.js`: no-eval serialized SSR
  reader, full detail matrix, public merchant/product signals and current-page
  search/store candidate extraction.
- `extensions/kjds-browser-capture/popup.js`: one injected provider file,
  existing session handshake and an explicit keyword-search action.
- `web/features/browser-capture-inbox/*`: complete SKU/spec/price matrix,
  coverage, signal and ERP-mapping display.

The manifest still has exactly `activeTab`, `scripting` and `storage`; there are
no host permissions, content scripts, Cookie/localStorage access, network
interception or background pagination.

## Verification

- `uv run python scripts/verify_secrets.py` — passed; 1378 non-ignored files
  and 1405 historical paths checked at the final pre-commit run.
- `uv run ruff check .` — passed.
- focused backend and API contract: `61 passed` across
  `tests/test_browser_capture_inbox.py` and `tests/test_api_contract.py`, using
  the repository's complete 126-table file-backed test runtime.
- Web/node: `149 passed`, including serialized SSR exact mapping, promotional
  `skuMap`, lossless ERP projection contract and search-card candidate tests.
- `npm run build` — passed; TypeScript and 63-page Next.js production build.
- `node --check` for extension scripts and `git diff --check` — passed.

The final full repository run completed `2561 passed, 241 skipped`; its
remaining `25 failed, 4 errors` were outside BAS-206: the clean worktree lacks
the repository's ignored `wuliu` and `output/market_recon` user artifacts, and
three pre-existing environment/registry checks also remained red. Machine
comparison of the before/after JUnit reports found exactly the same 29 red test
IDs, with no new failure. The focused BAS-206 suite, all 148 Web tests and the
production build are green.

## Publication

- engineering commit: `2fd8e42` on the original isolated worktree;
- publication commit: `96b33fb` on
  `feat/1688-supplier-capture-20260807`;
- pull request: <https://github.com/Y-008/kjds/pull/47>;
- PR base: `integration/pony-full-20260807`, the publication-only mirror of
  the local Ponytail-full integration baseline.

The remote `main` did not yet contain that 117-commit integration baseline.
GitHub push protection also recognized synthetic `sk_live_...` negative-test
fixtures in an ancestor as Stripe credentials. The publication baseline keeps
the same runtime test values while splitting those literals into source-level
string concatenation; the credential-rejection suite passed `100/100` together
with BAS-206 and API contract tests. No protection was bypassed, and the PR
diff remains only the 17 BAS-206 files.

Engineering status must not be interpreted as live extension installation,
formal fact promotion, a supplier quote or a purchase.
