# 2026-07-27 Real Operation Screen — Cable Wrap

## Scope and authority

- Store scope: `ozon-primary`; external market observations remain `store_ref=external`.
- Operation type: authenticated/read-only Ozon Seller review plus allowed public Ozon and 1688 page observation.
- No Ozon listing, price, inventory, promotion, advertising, supplier message, cart, order, payment, Approval, Permit, or other external write was created.
- Review counts are demand proxies only. Public 1688 prices are observations, not Supplier Offers or actual procurement cost.

## Store diagnosis

The authenticated Ozon Seller pages reported:

- product list: 18 total, 15 selling, 3 preparing for sale;
- 2026-07-20 through 2026-07-26: 52 impressions, 3 product-card visits, 0 cart additions, and 0 ordered units;
- favorable price index coverage: 8%;
- no store sales data suitable for claiming product demand or actual profit.

## Exact market cohort

The first public cohort was a black spiral cable wrap, 2 m, 16–24 mm. Three Ozon buyer-visible listings were observed at 180, 197, and 324 RUB. The exact 1688 identity was not available, so the system correctly kept this cohort unmatched.

A second identity was normalized at the material-family level:

- Ozon SKU `1803890415`: black, 5 m, 16 mm, plastic; buyer-visible price 622 RUB; rating 4.9; 6,992 reviews; visible stock 497.
- 1688 offer `768661982763`: black, about 5 m, 16 mm, PE; public unit price 2.80 CNY per package; MOQ 1.

PE is retained as the supplier's raw material and normalized only to the `plastic` family. Ozon does not expose the exact polymer in the observed product facts. The 1688 page displayed freight from 6 CNY to a non-authoritative destination, did not establish the target consolidation warehouse or tax boundary, and triggered a freight-service slider. The slider was not bypassed.

## Evidence and replay

- Ozon 2 m cohort Evidence: `evd_911b858945c64463ad32eaaa52e1dccf`
- 1688 variant-family Evidence: `evd_9d176f5a007346d583bea7b725940236`
- Ozon 5 m / 16 mm Evidence: `evd_4ee1a65a9525421aa1413eb80acba378`
- 1688 5 m / 16 mm Evidence: `evd_77ca29378fde40518720c051826aeb6f`
- Three-unit screening run: `bor_1144f062331ef1cbf7f98ba6`
- Three-unit run Evidence: `evd_9accb70ffb5c426aabc709cec556a56d`
- Three-unit snapshot SHA-256: `1144f062331ef1cbf7f98ba6f2519e5b4b0297a87236c5b7679eb64e1fa9c29e`
- One-unit screening run: `bor_8dd861249042a0be78f0b536`
- One-unit run Evidence: `evd_dc058586ccb2457bb9ef806966df5dcc`
- One-unit snapshot SHA-256: `8dd861249042a0be78f0b5364d0b005a92bb1048805376ee24e157de721ad182`

Observed result at the latest replay:

- 13 observed listings/facts;
- 2 unique exact identities;
- 4 Ozon competitor listings;
- 9 supplier observations;
- 0 fully costed candidates;
- 0 downside-positive candidates;
- 0 content-ready candidates;
- 0 eligible for Approval;
- 0 Approval allocation selected;
- 0 Pilot ready, published, ordered, or settled/proven.

The internal task `tsk_461a7559dbd64b74af475c95bd0d251e` remains open. Its next action is to obtain exact-quantity checkout evidence tied to the real consolidation destination, explicit tax and domestic-freight boundaries, authoritative category/mode/price-band fees, product weight and cross-border logistics, Product Passport evidence, and owned/licensed media. Until those facts exist, no precise CM3 or external execution is authorized.
