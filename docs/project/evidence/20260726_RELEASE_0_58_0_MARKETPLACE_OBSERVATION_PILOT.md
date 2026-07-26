# KJDS 0.58.0 Marketplace Observation / Portfolio Pilot Evidence

## 1. Release claim

KJDS 0.58.0 adds an Evidence-backed, read-only marketplace observation seam and
a server-owned Portfolio Pilot screen. It can use public marketplace page values
as research signals, but cannot promote those values into a Supplier Offer,
actual cost, actual profit, procurement action, Listing publish action, or Ozon
write authority.

The release implements BR-081 / BAS-103 and ADR-0030.

## 2. Real operating scope

- Store scope: `ozon-primary`
- Canonical Product:
  `prd_2215304aca03f42ab0921102a2d58de9`
- Product SKU: `ozon:ozon-primary:2105343364UB`
- Ozon Offer ID: `2105343364UB`
- Ozon marketplace SKU: `2216781923`
- Bound catalog item hash:
  `8631d985815528f7eec912dd73d48f40e2cd10bc6e472fba265a98c21f4fa55d`
- Observed Ozon page price: `2291.00 CNY`
- Observed sellable stock: `9`

The Ozon price and stock are current bound catalog observations. The price is not
an order, settlement, receivable, or actual-profit result.

## 3. 1688 observation capture

One immutable browser-observation snapshot contains three independently
identified items:

| Supplier | 1688 item | Observed variant | Public displayed price | Key gap |
| --- | --- | --- | ---: | --- |
| 河北东奥起重机械制造有限公司 | `921731932361` | `500#12米` | `335.00 CNY` | 12 m, 1050 W, wireless-only wording; plug and duty cycle unknown |
| 河北隆祥起重机械制造有限公司 | `972517194260` | `PA500*12米无线两用款` | `393.12 CNY` | 12 m, 1000 W, 5 mm; Russian plug and duty cycle unverified |
| 河北九鸣起重机械制造有限公司 | `1067394114846` | `500KG7.6米绳无线+线控+手动` | `500.00 CNY` | page shows `150` under a kW-labelled field; 1500 W, 6 mm, Russian plug and duty cycle unverified |

Capture records:

- Snapshot ID: `mos_893969993df54dc9ab0ead01c588a215`
- Snapshot SHA-256:
  `91c1c4114830b249abe9183d9ed1702ab9623e6b4039e9831850aae5be02a4e1`
- Evidence ID: `evd_294c9c496acb4c25bd74bccd92b18780`
- Evidence grade: `C`
- Idempotency key: `browser-hoist-suppliers-20260726-v1`
- `formal_fact_promoted=false`
- `supplier_offer_created=false`
- `actual_cost_created=false`
- `external_write_allowed=false`

The first PostgreSQL replay exposed a real FK ordering defect: the parent
snapshot and child items were being flushed together without an ORM relationship.
The capture now flushes the immutable parent before inserting children. SQLite
tests explicitly enable FK enforcement so the regression is reproducible.

## 4. Server-owned screening result

Frozen target:

- rated load `500 kg`
- `220 V`
- rated motor power `1500 W`
- lift height `7.6 m`
- wire rope `6 mm`
- wireless + wired + manual control
- Russian plug
- continuous-duty operation

Policy `ozon-cny-research-screening-v1` owns both screening cases. The browser
only renders returned values.

| Supplier | Observed spread | Base screening contribution | Downside screening contribution | Actual CM3 / profit |
| --- | ---: | ---: | ---: | --- |
| 河北东奥 | `1956.00 CNY` | `708.33 CNY` | `-218.60 CNY` | unavailable |
| 河北隆祥 | `1897.88 CNY` | `650.21 CNY` | `-276.72 CNY` | unavailable |
| 河北九鸣 | `1791.00 CNY` | `543.33 CNY` | `-383.60 CNY` | unavailable |

Deterministic replay:

- Run ID: `ppr_ee5f440d35a5bbbd088919c5`
- observed: `3`
- screened: `3`
- positive downside lower bound: `0`
- full-cost draft ready: `0`
- Pilot ready: `0`

All three candidates are blocked by one or more specification gaps, a
non-positive downside screening contribution, and the absence of a released
fifteen-component full-cost scenario. No actual profit is displayed.

## 5. Existing queue integration

The screen reused the 0.57 OperatingTask/event module and the existing
OperationsQueueService:

- OperatingTask: `tsk_ec8dcffbba864e02b1d54e491c967a62`
- Fingerprint:
  `770c942351df0a471e3e30018bc4960f546b6080a86f6481610cd787155ebb8f`
- Kind: `internal:portfolio_pilot_blocked`
- Owner: `supply`
- Severity: `high`
- Status: `open`
- Next action:
  `完成精确规格询价并补齐版本化十五项成本场景`
- Queue key:
  `operating_task:tsk_ec8dcffbba864e02b1d54e491c967a62`

Repeated screen runs update the same fingerprinted task within its cooldown
window; they do not create a second workflow engine or external side effect.

## 6. Frozen RFQ

One governed RFQ package was generated from the bound Ozon catalog item:

- RFQ Evidence: `evd_6e90cefa66134582bc756f025515dae4`
- Package hash:
  `c9dd787198e365b3e63e7f1bb167d4ca765fa83736d845ed4f6a67526400c9a9`
- Idempotency key: `hoist-500kg-russia-rfq-20260726-v1`
- Quantity breaks: `1 / 10 / 50 / 100`
- Reply due: `2026-07-29T18:00:00+08:00`
- Required response includes MOQ, tier price, sample, packaging dimensions and
  weight, lead time, warranty, certification status, tax boundary and freight
  boundary.
- `counts_as_supplier_quote=false`
- `formal_offer_eligible=false`
- `automatic_supplier_contact=false`
- `automatic_procurement=false`
- `automatic_payment=false`
- `automatic_listing=false`
- `automatic_marketplace_write=false`

The same frozen Chinese message is intended for 河北九鸣、河北隆祥、河北东奥.
It may only be captured as dispatched when recipient, exact message, timestamp,
conversation and platform proof match.

## 7. Browser / contact state

On 2026-07-26 the existing signed-in Chrome session was rechecked:

- 河北九鸣 detail page remained readable.
- The targeted 1688 chat URL still showed multiple “Please drag the slider as
  instructed” challenges.
- The chat body also showed `您尚未选择联系人`.
- No CAPTCHA was bypassed and no message was sent.
- Public web search did not find a sufficiently verified official email or
  official website for all three exact legal entities. A third-party snapshot
  for 河北东奥 exists but is explicitly marked offline; it was not treated as a
  verified contact channel.

## 8. Runtime and browser proof

- PostgreSQL, API, Web and media-worker healthy.
- `/version` returns `0.58.0`.
- `/health/ready` returns `status=ok`, `version=0.58.0`, database `status=ok`.
- Alembic current/head: `20260726_0052`.
- Authenticated observation capture/list and Pilot prepare replayed against real
  PostgreSQL.
- Anonymous requests to protected endpoints are covered by API contract tests
  and runtime 401 checks.
- Desktop screenshot:
  `output/playwright/release-0.58.0/portfolio-pilot-desktop.png`
- 390 px screenshot:
  `output/playwright/release-0.58.0/portfolio-pilot-mobile-390.png`
- Mobile measurement:
  `innerWidth=390`, document `scrollWidth=390`, body `scrollWidth=390`.
- Browser console: `0` errors during the mobile Pilot flow.

Clean verification:

- `uv run python scripts/verify_secrets.py`: passed; `579` non-ignored
  worktree files and `574` historical paths scanned.
- `uv run ruff check .`: passed.
- full backend suite: `535 passed`, one upstream Starlette deprecation warning.
- `git diff --check`: passed.
- `web/npm ci`: passed; `0` vulnerabilities.
- Web contracts: `47 passed`.
- Web production build: passed, including `/`, `/capability-atlas`,
  `/evidenceops`, `/operating-intelligence` and operating-workspace routes.
- deterministic capability graph check: `143` points, `14` lines, `8`
  surfaces; registry current at `0.58.0`.
- independent temporary PostgreSQL database
  `kjds_migration_replay_058` upgraded from an empty database through all
  migrations to the single `20260726_0052 (head)` and was then removed.
- current production-like PostgreSQL reports the same single
  `20260726_0052 (head)`.
- protected API runtime checks:
  `GET /v1/marketplace-observations` anonymous `401`,
  `POST /v1/portfolio-pilot/prepare` anonymous `401`; authenticated
  observation read and Pilot prepare succeed.
- OpenAPI `info.version=0.58.0` exposes authenticated
  `GET/POST /v1/marketplace-observations` and
  `POST /v1/portfolio-pilot/prepare`.

## 9. Truthful result

This release does not claim that 100 profitable SKUs can be published today.
It establishes the first repeatable operating cell:

`market observation → Evidence → server screening → internal task → frozen RFQ`

For the current hoist SKU, the base screen is attractive but the downside
screen is negative and full-cost proof is absent. The next revenue-producing
action is supplier quote collection and full landed-cost reconciliation, not
automatic listing.
