# BAS-162 Store/category profit growth OS evidence

- Date: 2026-08-02
- Requirement: BR-137
- Status: COMPLETED_ENGINEERING
- ADR: `docs/adr/ADR-0085-store-category-profit-growth-operating-system.md`

## Delivered

- `StoreCategoryStrategyWorkspace` with evidence-backed append-only store
  profile events and immutable operating-plan snapshots.
- Registry-backed store positioning, assortment mode, price band, official
  category roles, derived archetypes, routing precedence and safety envelope.
- Exact official leaf/product type/hierarchy matching, explicit exclusion and
  fail-closed treatment of derived-only labels.
- Per-SKU research/Pilot/growth/exit lifecycle with listing, traffic, inventory,
  channel, budget and stop-loss proposals.
- Cross-store route alternatives and governed handoff indication without
  automatic duplicate publishing.
- Profit Command portfolio, analytics, candidate pagination/filtering and
  Evidence lineage projections.
- Five Web pages: profit overview, SKU collection, SKU detail, store/category
  routing and full Evidence lineage, plus the main dashboard navigation entry.

## Database and migration

Migration `20260802_0086` creates:

- `store_operating_profile_events`
- `store_operating_plan_snapshots`

Both tables have exact-scope/idempotency constraints and PostgreSQL immutable
triggers. Isolated replay passed:

```text
base -> 20260802_0086 -> 20260802_0085 -> 20260802_0086
append-only UPDATE/DELETE probes: rejected
current local database head: 20260802_0086
```

## Verification snapshot

```text
Python store/profit focused tests: 13 passed
Python full regression: 1311 passed
Web contract tests: 137 passed
Next.js production build: passed, 59 routes generated
OpenAPI new Profit Command/Seller OS paths: present
Authenticated runtime projections: 7/7 HTTP 200
Desktop browser width: 1440 = 1440 scroll width
Mobile browser width: 390 = 390 scroll width
```

Browser captures are retained at
`output/playwright/bas162-profit-command-desktop.png` and
`output/playwright/bas162-profit-command-390.png`. The isolated browser did not
carry a Supabase session and therefore correctly rendered the authenticated API
boundary as HTTP 401/no_data; separate server-side authenticated runtime probes
returned HTTP 200 for workspace, analytics, candidates, lineage, portfolio,
operating plan and store routing, with 18 persisted SKU candidates.

The current `ozon-primary` store profile intentionally remains `no_data`:
positioning and official L1/L2/L3 category paths have not been independently
confirmed. KJDS therefore does not fabricate a category tree merely to fill
the UI. Raw Product leaf category and product type observations remain stored
and will be re-projected immediately after an Evidence-backed profile is
recorded.
