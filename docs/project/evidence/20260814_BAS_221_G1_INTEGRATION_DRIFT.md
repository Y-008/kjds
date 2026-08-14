# BAS-221 G1 Integration Drift Closure

## Decision and scope

BAS-221 closes four current-main integration drifts discovered after BAS-220.
It changes no database schema, migration, API, OpenAPI, Web route, dependency,
runtime composition, external credential, platform write, payment, purchase,
listing, or production setting. `frontier_review=not_required`: these are local,
reversible contract-alignment fixes with no material technology selection.

The affected stable requirements are BR-002, BR-007, BR-011, and BR-060. The
authorities remain unchanged: Commercial Lifecycle owns entitlement state;
Evidence owns immutable dual-time records; the Outbox coverage registry owns
direct transaction-module classification; and the write-path registry owns the
repository outbound-HTTP boundary.

## Root causes and closure

1. A commercial lifecycle baseline used an invoice due date of 2026-08-12. It
   became a time bomb on 2026-08-14 and exercised the already-covered overdue
   branch instead of the intended post-refund outstanding-balance branch. The
   baseline now uses an explicit 2099 due date; the separate overdue test and
   production `read_only/invoice_overdue` behavior remain unchanged.
2. `media_jobs.py` directly owns SQLAlchemy transactions and exposes an explicit
   PostgreSQL provider-attempt claim plus immutable result-receipt contract. It
   is now classified as `polling_contract`; no duplicate Outbox event or new
   external consumer was invented.
3. Research Inbox's dedicated Evidence adapter required `recorded_at`, while
   its only caller omitted it. One server-owned `captured_at` is now passed
   through the reserved Research authority and stored as the exact Evidence
   `recorded_at`. The dedicated adapter rejects missing, non-canonical or
   unequal capture times before writing, and the read boundary revalidates the
   persisted equality. Ordinary callers still cannot set an explicit recorded time.
   The advisory-lock test now accepts the implementation's explicit PostgreSQL
   `CAST(... AS text)` typing without weakening exact-scope lock composition.
4. The inventory-only SellerSprite MCP module imports `httpx` but was absent
   from the outbound-HTTP machine boundary. The registry and its copied test
   fixture now include the module. Live admission remains false and no MCP tool
   call was made.

## Verification

The first focused run exposed the missing Research reserved-authority allowance;
after the narrow authority fix, the four affected suites passed `79 passed, 1
skipped`. After task-state reconciliation, the combined focused/governance run
passed `80 passed, 1 skipped`; targeted Ruff and `git diff --check` passed.

The final isolated G-1 run on 2026-08-14 produced authoritative
`.runtime/G1_VERIFICATION.json` status `PASS`:

- migration replay and the current Alembic head passed at `20260809_0098`;
- global data coverage PostgreSQL contracts: `84 passed, 12 warnings`;
- closed-loop 0096 PostgreSQL contracts: `101 passed, 12 warnings`;
- generic Python suite: `3189 passed, 76 skipped, 61 warnings`;
- Web tests: `146 passed`; Next.js production build passed;
- transactional Outbox, sourcing, finance, decision/experiment, policy and core
  numeric integrity all passed;
- runtime identity, secret scan, startup package, container import, signed
  release provenance, software SBOM, AI-BOM, API/Web health and auth, Kill
  Switch, Evidence ledger/monitor/health loop, Ozon credential isolation and
  explicit execution-intent gates all passed;
- run-owned processes, databases, contract database and files all cleaned with
  no cleanup error.

The harness used the already isolated PostgreSQL service, so the optional
`backup_restore` field remained false while the overall Gate was validly PASS.
No backup or production-readiness claim is inferred from that skipped substep.

## Cleanup and remaining business truth

The run-owned `kjdsgdc221` container, network, and volume were removed. The
pre-existing default `kjds-postgres-1` container was restored healthy at its
unchanged migration `20260803_0094`; its persistent volume was preserved.

This closes engineering integration only. Real SKU evidence, Ozon read access,
settlement, bank cash, supplier quotes, logistics/compliance originals and
signed operating thresholds remain business-input Gates. No customer result,
revenue, production admission, external write, RFQ dispatch, listing, purchase,
payment, or Top1 claim is created by this Evidence.
