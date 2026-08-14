# BAS-154 native exact-scope customer-service authority

- Date: 2026-07-30
- Branch: `feature/batch-opportunity-mining-059`
- Status: `DONE_ENGINEERING`
- Business state: `no_data`
- External write: `false`
- Requirement: `BR-128`
- ADR: [ADR-0074](../../adr/ADR-0074-native-exact-scope-customer-service-authority.md)

## Implemented boundary

`ScopedCustomerServiceWorkspace.project(...)` is the only Customer Service
composition seam. It combines immutable exact-scope Case/Event authority,
Canonical Product, BAS-153 Returns, Evidence and the governed execution
authority without creating a second Product, Order, Return, Approval, Permit
or message truth.

Canonical surfaces are Case/Event intake,
`GET /v1/customer-service/workspace`, `/customer-service` and the matching
OpenAPI snapshot. Migration `20260730_0079` creates the only exact-scope
Customer Service Case/Event ledger. Message body and PII remain only in the
governed Evidence Blob; tables, list responses, Agent artifact, Graph, log and
cursor contain only redacted structure and hashes.

## Security completion-audit correction

The completion audit found that a normal successful command receipt could have
been mistaken for authoritative `message_sent` Readback. The implementation
now requires a separate versioned customer-message readback authority. The
production runtime remains unbound and therefore cannot project a sent
message.

A sent projection now fails closed unless all of the following bind exactly:

- allowed official/authorized customer-message adapter identity and version;
- approved message action, Case/Event and body SHA-256;
- command, receipt, remote operation and worker;
- success semantics, as-of and revocation;
- independent versioned message Readback Evidence;
- separate adapter-authorization, Kill Switch release and Compensation-plan
  Evidence with exact scope, immutable hash and purpose metadata.

The intake Event Evidence cannot be the only Readback Evidence. Ordinary
successful receipts, an unbound authority, an intake-only Evidence claim,
cross-scope/as-of/hash drift, a revoked adapter, missing Kill Switch release or
missing Compensation all block. Test doubles prove the contract only; they do
not establish a production message source.

The L3 action remains `policy_only` in the Write Path Registry.
`message_adapter_enabled=false`; customer contact, self approval, Permit issue,
refund, dispute, RMA mutation and external write all remain false.

## Current verification

The current full gate was executed after the completion-audit changes:

- full backend command:
  `uv run pytest -q -p no:cacheprovider --basetemp .runtime/pytest-full-bas157-freeze`;
- full backend result: `979 passed`, `9 warnings`;
- combined BAS-154/155/156 audit command: `86 passed`, `1 warning`;
- Ruff: all checks passed;
- Web executable contracts: `107 passed`;
- Web production build: `52` routes;
- OpenAPI snapshot matches runtime;
- `verify_secrets`: `970` non-ignored worktree files and `581` historical
  paths passed;
- `git diff --check`: passed, with line-ending notices only;
- Alembic current/head: single `20260730_0079`;
- empty PostgreSQL replay: `base → 0079 → 0078 → 0079`;
- PostgreSQL, API, Web and media-worker: rebuilt and healthy.

No claim is made that a test fake is an external authority. The reviewed
engineering boundary is fail-closed; production message sending remains
disabled.

## Live runtime

Authenticated runtime verification returned anonymous `401`, authorized exact
store `200`, unauthorized store `403`, readiness `200`, status `no_data`,
Case/Event counts `0`, `scoped_input_read=false`,
`message_adapter_enabled=false`, `raw_message_body_exposed=false`,
`external_write_allowed=false` and
`private_erp_interface_allowed=false`.

This is not a real customer conversation, dispute, RMA, refund or
Order-to-Cash closed loop.

## Browser

The existing authenticated live capture remains valid because this audit
changed the server execution-readback authority, not the no-data UI. Temporary
browser authentication state was deleted.

- desktop `inner/scrollWidth = 1440/1440`;
- mobile `inner/scrollWidth = 390/390`;
- mobile `clientWidth = 390`;
- console errors `0`.

Screenshots:

- `output/playwright/bas154-customer-service-desktop.png`
  - SHA-256:
    `d0b1fecbf686080c6da30ab14aea904d25dfd30f4769f933f252af4a41d05724`
- `output/playwright/bas154-customer-service-mobile-390.png`
  - SHA-256:
    `370ba790a1cd620fb68463af46d34843168064be424825b91bcb2326545ffb40`

## Harness and Graph

`scripts/seed_bas154_agent_graph.py` executes the focused Customer Service,
API and Write Path tests, migration replay, live runtime and container-health
probes, checks browser hashes and records this Evidence hash. Its test
observation reports only the focused command it executes; the full-suite output
above is a separate current gate, not a marker substituted for execution.

Only the five registered verifier categories can advance the task chain. The
Customer Service Agent cannot certify itself.

After the chained BAS-154→155→156 hash-settlement materialization, the canonical
Graph contains `111 tasks / 233 nodes / 229 edges / 397 observations`; the
latest BAS-154 tests/database/runtime/web/evidence states are fresh `passed`.

`DONE_ENGINEERING` does not claim a real Case, sent message, refund, dispute,
RMA, Settlement, bank Readback or Actual Cash CM3. Business state remains
`no_data`.
