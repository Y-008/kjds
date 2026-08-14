# 2026-07-27 Real Operation Screen — Low-Risk Standard Products

## Scope and authority

- Store scope: `ozon-primary`; public-market observations use `store_ref=external`.
- Operation type: authenticated/read-only Ozon Seller review plus allowed public Ozon and 1688 page observation.
- No Ozon listing, price, inventory, promotion, advertising, supplier message, cart, order, payment, Approval, Permit, or other external write was created.
- Ozon review counts are demand proxies only. Public 1688 prices are observations, not Supplier Offers, checkout totals, or actual procurement cost.

## Webcam privacy slider screen

The Ozon public cohort for a black three-piece webcam privacy slider contained five observed listings at 47, 52, 55, 61, and 83 RUB. Review counts ranged from 798 to 10,011 and remain proxies rather than sales facts.

1688 offer `604826964138` exposed an exact black three-piece blister-card variant at 1.20 CNY, MOQ 1. The supplier page also exposed black six-piece and single-piece variants; they were not merged into the three-piece cohort. The freight destination was not the target consolidation warehouse and a freight-service slider appeared. It was not bypassed. Tax, target freight, exact three-piece package weight, media rights, and the authoritative Ozon fee row were not established.

Ozon SKU `3559701750` also exposed incompatible camera-resolution attributes on a physical privacy slider. Those attributes are retained as a Content/Passport QA failure and must not be copied into a KJDS draft.

- Ozon cohort Evidence: `evd_3003f2e137aa4907992097f5ae0dc9b1`
- 1688 three-piece Evidence: `evd_22acfea0741e4b37ad464850089830ee`
- Screening run: `bor_83dda1d0adc475ea728470c5`
- Run Evidence: `evd_8df7578489f34fae8e300180ab499feb`
- Snapshot SHA-256: `83dda1d0adc475ea728470c53cdfb97423d4f6de9f4c077a42ebc3b3b0126d8a`

## Under-desk cable tray screen

Ozon SKU `1776438646` exposed a black, metal, 40 cm, single-piece under-desk cable tray at a buyer-visible 1,760 RUB. The page showed rating 5.0, 2,149 reviews, and two visible units. It did not expose a reliable mounting method or complete dimensions, so `mounting=unknown` is part of the exact variant identity.

1688 offer `676956427639`, supplied by `潮州市潮安区小小馨家居用品厂`, exposed a different exact variant:

- black, 40 cm, carbon steel, clamp-mounted;
- public unit price 18.62 CNY and MOQ 1;
- product dimensions 40 x 13.5 x 19 cm;
- independent package 43.5 x 14.8 x 5.9 cm and 918 g;
- public stock 95,581 units;
- six-year supplier tenure, 100% quality-compliance rate, 99% dispatch-within-48-hours rate, and 48% repeat-buyer rate as displayed by 1688.

The page displayed freight from 6 CNY to Foshan, not the target consolidation warehouse. Tax and target domestic-freight boundaries remain unknown. The 1688 item is therefore a public supply observation, not a Supplier Offer or actual cost. Because the Ozon mounting method is unknown while the 1688 variant is clamp-mounted, the service correctly keeps them as separate exact identities instead of manufacturing a cross-market match.

- Ozon tray Evidence: `evd_2748261a1ae048e7ba18a82920ec78d0`
- 1688 tray Evidence: `evd_aa7cc78576984a1fa26086c692905276`
- One-unit screening run: `bor_f8c7dabd3834055eeb13ad3e`
- Run Evidence: `evd_6f92a93595f145f6b41c36e00f37ad06`
- Snapshot SHA-256: `f8c7dabd3834055eeb13ad3e3357120b6ca790e8d53ccd15b002542e01450fe5`

## Exact 40 cm dual-clamp Ozon cohort and supplier mismatch replay

A second Ozon search established a comparable public-market cohort for the exact black, single-piece,
solid-steel, dual-clamp tray with product dimensions `400 x 185 x 100 mm`. The seven observed buyer
prices were 647, 678, 716, 716, 878, 951, and 1,469 RUB. Ozon SKU `1797878213` exposed 345 reviews,
rating 4.9, and 107 visible units at 1,469 RUB. SKU `3705258745` exposed the same dimensions, material,
mounting, color, and quantity, with 2 reviews, rating 4.5, and 1,000 visible units at 716 RUB. Review
counts remain demand proxies rather than sales facts, and public listing prices are not the target
store's current or proposed selling price.

The two strongest additional 1688 results were independently inspected and deliberately kept outside
that exact identity:

- offer `1005365476141`, `永清县皓越家居用品有限公司`: carbon-steel, hanging/no-drill 40 cm fixed
  versions in white or gray only; the white fixed version displayed 13.96 CNY, MOQ 1, package
  `43 x 16 x 5 cm`, 650 g, and public stock 9,999,971. The page displayed 68% on-time dispatch and a
  public 2.8 CNY freight starting point to Foshan, not the target consolidation warehouse;
- offer `941571668484`, `廊坊木博科技发展有限公司`: carbon-steel 40 cm fixed versions in gunmetal or
  white only; the gunmetal fixed version displayed 19.11 CNY, MOQ 1, 500 g, and public stock
  19,999,900. Product/package dimensions were absent. The page displayed 99% quality compliance,
  91% dispatch within 48 hours, 43% repeat buyers, and an 8 CNY freight starting point to Foshan.

An exact-dimension search then returned no exact related goods. Its strongest desk-tray result,
offer `807971841821` from `江门市优享家居用品有限公司`, had a black large variant at 20.50 CNY,
MOQ 2, package `38 x 21 x 7.5 cm`, 740 g, and public stock 78,304. The page did not expose product
dimensions or mounting, and the frozen one-unit screen is below its MOQ. It was therefore retained as
a third mismatch rather than promoted to the exact cohort.

All three 1688 pages triggered the freight-service slider. It was not bypassed. None established
the exact black `400 x 185 x 100 mm` dual-clamp variant, target-warehouse freight, tax boundary, media
rights, or a formal Supplier Offer. Treating any page as the Ozon SKU's cost would therefore be an
incorrect exact-variant match.

- Exact Ozon cohort Evidence: `evd_20a49eda8bfb4511aedab5571bc23b9b`
- Similar-but-mismatched 1688 Evidence: `evd_7954d517880c4088a319c2b4b071a172`
- Third mismatch Evidence: `evd_1ebbf71a36dd456289529c3fd41a2213`
- Final one-unit deterministic replay: `bor_6dfcee135ea5bcd75ab4c355`
- Run Evidence: `evd_722749e02aa94fa6a4188f25806b06ed`
- Snapshot SHA-256: `6dfcee135ea5bcd75ab4c355fd67d69d703d0050cad9fe1adb7cc12073a200c1`

## Latest service-side funnel

Contract `batch-opportunity/1.2.0` separates exact cross-market identity from checkout-cost readiness.
This corrects the prior `bor_6dfcee135ea5bcd75ab4c355` projection, which treated missing checkout
Evidence as if no exact identity match existed. The corrected deterministic one-unit replay reported:

- 31 observed listings/facts: 17 Ozon and 14 supplier observations;
- 5 unique exact Ozon identities and 2 exact Ozon/1688 identity+variant matches;
- 0 checkout-cost-eligible matches because the matched supplier rows remain public display
  observations without target-warehouse freight/tax/checkout verification;
- 0 fully costed candidates;
- 0 downside-positive or content-ready candidates;
- 0 eligible for Approval and 0 Approval allocations;
- 0 Pilot ready, published, ordered, or settled/proven.

The two identity matches are the black three-piece webcam privacy slider and the black 16 mm x 5 m
spiral cable wrap. This identity result does not establish profit. The current blocker is
`observed_checkout_cost_evidence_missing`; the next action is explicitly **not to order**. While the
supplier page still shows stock, KJDS may only observe the one-unit checkout boundary and bind MOQ,
tax, and target consolidation-warehouse freight. It must then bind authoritative Ozon fees,
international logistics, returns, advertising, FX, loss, Product Passport, and licensed/owned media
before a downside CM3 decision. A CAPTCHA appeared on the cable-wrap freight/checkout flow and was
not bypassed.

- Corrected one-unit replay: `bor_3e3902ed8bac026b42d49e2e`
- Run Evidence: `evd_dc97d627aa2141ceaa0812b16ba6e9a8`
- Snapshot SHA-256: `3e3902ed8bac026b42d49e2e1e9d86b8a5a2db6327ebba1ed5a6d9474e25640b`
- API version: `0.59.0`; `/health/ready=ok`; anonymous latest-run access=`401`
- Authority: `permit_created=false`, `ozon_write_performed=false`; no supplier cart, order, purchase,
  payment, message, or advertising write was created.

## Sale-triggered JIT procurement contract replay

After the operator policy was frozen as “do not buy before a real Ozon order”, contract
`batch-opportunity/1.3.0` replayed the same 31 observations through a single server-owned
`SaleTriggeredProcurementPolicy` seam. The run preserved the two exact identity matches and zero
checkout-cost/full-cost candidates, while adding an explicit procurement contract:

- mode: `sale_triggered_jit`;
- pre-order purchase quantity: `0`;
- only a valid formal `ozon_order` FactRecord bound to the same Product/SKU and authorized
  `store_ref`, with internal trigger status `awaiting_packaging`, may open
  `eligible_for_procurement_review`;
- even that state remains review-only: supplier order, payment and external purchase write are all
  `false`;
- unknown/cancelled/returned/cross-store/bad-Evidence or manually created orders cannot trigger it.

This replay did not create an Ozon listing or represent profit as proven. It only makes the intended
post-sale procurement sequence machine-verifiable and prevents a pre-sale supplier purchase.

- Replay: `bor_2dee522a4426071187f86331`
- Run Evidence: `evd_2bb0908796744eb69feaae8105e98f11`
- Snapshot SHA-256: `2dee522a4426071187f863319265e983b2deb17704806f4968b7f96136733378`
- Runtime: API `0.59.0`, `/health/ready=ok`, anonymous latest access=`401`, all four Compose
  containers healthy.
- Current formal order ledger: `0` `ozon_order` facts (`0` store-scoped,
  `0` `awaiting_packaging`), so no procurement review trigger exists.
- Verification: `verify_secrets` passed; Ruff passed; backend `593 passed`; Web clean `npm ci`,
  `49 passed`, and production build passed.

## 40 cm tray identity fail-closed replay

A fresh operator-confirmed read of 1688 offer `676956427639` recorded the black 40 cm variant at
18.62 CNY, MOQ 1 and visible stock 95,581. Its page described the installation as `卡扣式`; the
new observation preserves that raw meaning as `mounting=clip`. It does not silently overwrite the
older `mounting=clamp` normalization. More importantly, Ozon SKU `1776438646` still exposes no
authoritative mounting method, so its `mounting=unknown` identity cannot be treated as exact.

Marketplace Observation contract `1.2.0` now refuses to generate a match key when any identity or
variant value is an unresolved placeholder such as `unknown/unspecified/pending/未确认`. The batch
scanner repeats the same check for historical observations so a previously persisted key cannot
reintroduce the false match. This preserves the high visible spread as a research lead, not a profit
claim or publishable SKU.

- Fresh 1688 item: `moi_10068f86830e4f5b86811f2de777c05e`
- Snapshot: `mos_27f0a15530eb4fc6adab059c6d469b52`
- Observation Evidence: `evd_fc8852bf459c4fd6bfcad485a42173bb`
- Price authority: `public_display_price`, `checkout_verified=false`, `supplier_offer_created=false`,
  `actual_cost_created=false`
- Deterministic three-unit replay: `bor_1466544d158347ac607aa6b7`
- Run Evidence: `evd_b69c2e17bf5a43ccb780f60ee9766510`
- Snapshot SHA-256: `1466544d158347ac607aa6b7adc0c707d60c1c4547df3141bf5fff346beeb679`
- Actual funnel: 40 observations; 3 unique exact Ozon identities; 2 identity matches; 1
  checkout-cost candidate; 0 fully costed; 0 downside-positive; 0 content-ready; 0 eligible for
  Approval; 0 Pilot-ready/published/ordered/settled.
- Current tray blockers: exact Ozon mounting/dimensions, target-warehouse checkout freight and tax
  boundary, authoritative fee/logistics/returns/advertising/FX/loss rows, Passport, and owned or
  licensed media. No supplier cart/order/payment or Ozon write was made.
- Regression: secrets `623/581`, Ruff clean, backend `607 passed`, `git diff --check` clean; all four
  Compose services returned healthy after rebuilding the API with the fail-closed projection.
