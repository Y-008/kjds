# BAS-155 native exact-scope growth experiments

- Date: 2026-07-30
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Business state: `no_data`
- External write: `false`
- Requirement: `BR-129`
- ADR: [ADR-0075](../../adr/ADR-0075-native-exact-scope-growth-experiment-authority.md)

## Implemented boundary

`ScopedGrowthExperimentWorkspace.project(...)` is the only growth experiment
composition seam. After exact tenant/entity/store/as-of admission it combines
Canonical PIM/Listing, Listing lifecycle, Inventory, OMS, the fifteen-leg
downside/Actual CM3 ledger, formal marketplace observations and redacted
Customer Service signals. The server owns filters, counts, opaque pagination,
stable snapshot and Agent artifact; the client does not recalculate them.

Canonical surfaces are `GET /v1/growth-experiments/workspace`,
`/growth-experiments` and the runtime OpenAPI snapshot. Legacy 0042 and
`/v1/marketplace-growth/*` remain isolated and are never used by the deep
module. No 0080 was required.

## Completion-audit corrections

A canonical PIM empty result is now unconditional `no_data` even when another
upstream reports ready. A contradictory PIM no-data result with nonempty groups
is blocked, and an empty page after a valid opaque cursor returns honest
no-data. Tests cover canonical PIM empty, mixed ready/no_data and empty
pagination; the service cannot emit `ready` with `experiments=[]`.

Production composition-root integration tests construct `build_runtime()` with
the real service classes and a temporary real SQLAlchemy repository. They
exercise ready composition, blocked latest authority, schema drift and snapshot
drift through those production instances. Upstream envelopes are controlled
fixtures and therefore do not claim real business facts.

Adversarial Agent inputs containing prompt injection, self approval, fake
Permit, customer contact or fictional authority cannot change the fixed
permissions or enter the authoritative artifact.

## Current verification

- full backend command:
  `uv run pytest -q -p no:cacheprovider --basetemp .runtime/pytest-full-bas157-freeze`;
- full backend result: `979 passed`, `9 warnings`;
- combined completion-audit command: `86 passed`, `1 warning`;
- Web executable contracts: `107 passed`;
- Web production build: `52` routes;
- executable Web state model covers
  `error → retry/loading → success` and distinct blocked/no_data/ready DOM
  models;
- Ruff: all checks passed;
- `verify_secrets`: `970` non-ignored worktree files and `581` historical
  paths passed;
- `git diff --check`: passed, with line-ending notices only;
- OpenAPI snapshot matches runtime;
- Alembic current/head: single `20260730_0079`; no 0080;
- four rebuilt containers: healthy.

The live runtime returned anonymous `401`, authorized `200`, unauthorized
`403`, readiness `200`, deterministic replay `true`, status `no_data`, total
`0`, upstream read `false`, legacy growth used `false`,
`external_write_allowed=false` and
`private_erp_interface_allowed=false`.

## Browser

The rebuilt production Web rendered the real server `no_data` response. The
page does not synthesize market, PIM, Order, Inventory, profit, review,
Approval or Permit data.

- desktop inner/scroll width: `1440/1440`;
- mobile inner/scroll/client width: `390/390/390`;
- console errors: `0`;
- temporary authentication state deleted;
- visual inspection: passed.

Screenshots:

- `output/playwright/bas155-growth-experiments-desktop.png`
  - SHA-256:
    `fd715746a2d70f65d9e15d254eb01011cdbdcc14ced198123308203b8b8b103c`
- `output/playwright/bas155-growth-experiments-mobile-390.png`
  - SHA-256:
    `c293ee845f04892481afe3212dbd308e70852b72d683d81926408c391c2b4378`

## Harness, permissions and truth

`scripts/seed_bas155_agent_graph.py` executes the focused growth,
production composition-root and API tests, all executable Web tests, the
single-head check, live runtime and four-container probes, browser hashes and
this Evidence hash. Its test observation reports its actual focused count; the
full-suite result above remains a separate executed gate.

Price change, promotion creation, advertising spend, customer contact, self
approval, Permit issue, external write and private ERP interface remain false.
Only the five external verifier categories can advance the chain.

After the chained BAS-154→155→156 hash-settlement materialization, the canonical
Graph contains `111 tasks / 233 nodes / 229 edges / 397 observations`; the
latest BAS-155 tests/database/runtime/web/evidence states are fresh `passed`.

`DONE_ENGINEERING` does not claim a real price, promotion, ad, Order, Inventory,
Actual CM3, review or Customer Service Fact. All remain `0/no_data`; there is no
operating or profit closed loop.
