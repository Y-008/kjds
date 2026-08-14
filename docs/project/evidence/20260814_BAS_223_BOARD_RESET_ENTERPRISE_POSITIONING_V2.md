# BAS-223 Board Reset and Enterprise Positioning v2

## Decision and scope

BAS-223 implements BR-149 as one bounded engineering slice. The selected
solution keeps `EnterprisePositioningAdvisor.position(profile)` as the only
positioning Interface, exposes it through authenticated current/scenario HTTP
adapters, and renders the server projection inside the existing `/team-control`
page. It does not create a second owner page, database, Principal, Agent,
Appointment, task, Fact, budget, Approval, Permit, or external write path.

The current product position is frozen as an evidence-first, actual-cash-led,
controlled-automation operating control plane for cross-border commerce. The
commercial order is self-operation validation, bounded cash diagnosis, design
partner, SaaS/implementation, and only then an enterprise control platform.
World Model, Venture Federation, Synthetic Economy, new markets, new platforms,
multitenant SaaS, and long-horizon Agent expansion remain outside the 90-day
delivery promise.

## Best-solution comparison

Three options were evaluated:

1. **Separate deep positioning Interface plus the existing owner page** —
   selected. It keeps deterministic organization policy independent from the
   already broad Team Control brief while avoiding a duplicate UI or truth
   source.
2. **Merge positioning into `TeamControlTower.brief`** — rejected because it
   would couple enterprise-profile simulation to exact-scope operational
   projections and enlarge an already deep Module's public surface.
3. **Create a persisted profile workflow and a second owner page** — rejected
   before the first verified cash loop because it adds schema, migration,
   approval, identity, and navigation cost without evidence of a current
   operating bottleneck.

`frontier_review=not_required`: this change uses existing FastAPI, Pydantic,
React, CSS, authentication, and Kill Switch patterns. No new dependency,
provider, infrastructure, or technology bet is introduced. ADR-0098 records
the stable boundary and invalidation conditions.

## Authority and safety boundaries

- The 35 entries are capability templates with stable `role_template_ref`
  values, not employees, accounts, Principals, Agents, or production grants.
- `enterprise_ref` creates only a deterministic profile scope and grants no
  authority.
- The scenario POST is authenticated, requires an approved read role, is
  deterministic and non-persistent, and is excluded from the write-stop Gate.
  It cannot call a write service or create governance objects.
- Role order, status, seats, separation-of-duties conflicts, market/platform
  gaps, next activation, and Gate are server decisions. The Web adapter does
  not recompute them or save simulated input as current truth.
- Human bindings remain `UNKNOWN`; all identity, appointment, fact promotion,
  budget, approval, Permit, and external-write action flags remain false.

## Accessibility application

The owner-page adapter follows the repository accessibility review: native
labels and controls, semantic headings, keyboard-operable input, visible focus,
an announced request/error status, non-color-only status text, and a layout that
does not require horizontal scrolling at the 390px acceptance width. The
simulator is explicitly labeled as unsaved so its result cannot be mistaken for
the current enterprise profile.

## Current business-truth baseline

The private startup package was rechecked read-only on 2026-08-14 with:

```text
.venv/Scripts/python scripts/validate_startup_package.py .runtime/real-sku-startup --require-review-ready
```

The package contract is `kjds-startup-package-v4`, status is
`structurally_valid`, and `errors=[]`, but strict preflight remains non-zero.
Only `g0-ozon-api-identities.csv` is `ready_for_human_review`. Candidate
research, finance reconciliation, G0 governance, Ozon access, SKU media, SKU
passports, and supplier quotes are the seven `awaiting_inputs` sections.
`automatic_import=false` and `formal_fact_promoted=false`; structural validity
and one review-ready identity section do not make the package business-ready or
grant production admission. No real original, owner appointment, or cash fact
has been promoted.

Therefore BAS-223 proves no real SKU intake, owner appointment, supplier quote,
Ozon access, settlement, bank receipt, Actual Cash CM3, `CASH_VERIFIED` SKU,
commercial C0, customer outcome, payment, purchase, listing, advertising, or
production admission. The unique operating next action is to select and sign
one Truth SKU plus the four-seat accountability/maximum-loss fields in the
private G0 intake, then attach private Evidence references and hashes; blanks
remain `NOT_AUTHORIZED/BLOCKED_EVIDENCE`.

## Verification

Current integrated verification on 2026-08-14:

- owner control CAS `5eed3f7` restored Lane C `owner_thread_id` to the verified baseline `019ffd36-1417-7321-bacb-b3c9510ec970` (Plan/registry/assignment contract re-synchronized);

- role/API focused regression after currentness fixes: `29 passed`; this
  includes the jointly re-signed semantic-drift negative and the
  `qa_release_lead` independent-control-seat assertion;
- active assignment contract: `23 passed`;
- saved OpenAPI equals runtime contract: `1 passed` after snapshot export;
- combined focused Python regression (role/API + assignment + OpenAPI):
  `53 passed`;
- Web contract suite: `150 passed`; Next production build PASS;
- compile and JSON parse Gates PASS; Secret scan PASS (`1466` non-ignored
  worktree files, `1606` historical paths); `git diff --check` PASS;
- `npm ci` completed; npm reported one pre-existing high-severity dependency
  advisory, which is not auto-fixed in this slice because dependency changes
  require a separate reviewed upgrade decision.

A broader `tests/test_api_contract.py` diagnostic completed with `54 passed, 2
failed`: both failures were connection timeout/503 results from the inherited
runtime pointing at unavailable PostgreSQL `127.0.0.1:55432`, not accepted
product assertions. This diagnostic is not a green Gate and is not counted as
final G-1.

The isolated PostgreSQL G-1 receipt and the release-head rerun are recorded in
the Test-pass definition below. BAS-223 is `DONE_ENGINEERING`; real-person seat
binding and independent completion review are deferred to enterprise personnel
configuration, not to this automated gate.

## Test-pass definition (测试跑通)

`测试跑通` is the automated, machine-checkable gate only. It does not include
real-person seat binding or human completion review, which the enterprise
configures separately after this engineering slice.

Required automated gates:

- focused Python regression (`tests/test_active_workstream_assignments.py`,
  `tests/test_enterprise_positioning.py`,
  `tests/test_enterprise_positioning_api.py`) all pass on a clean basetemp;
- Web contract suite and Next production build pass;
- `ruff`, `py_compile`, JSON parse, secret scan, and `git diff --check` pass;
- isolated PostgreSQL G-1 receipt reports `status=PASS` via
  `verify-g1.ps1 -UseExistingPostgres -PostgresPort 55433` against a clean
  `postgres:17-alpine` slot, with `backup_restore=false` and no
  production/push/external-write claim.

Current receipt on release HEAD `ec37cf4`:

- focused Python regression: `52 passed`;
- `ruff`, `py_compile`, JSON parse, `git diff --check`: PASS;
- G-1 receipt `D:\KJDS\kjds\.runtime\G1_VERIFICATION.json`: `status=PASS`,
  `git_commit=e2d6ca35b6c7c16487b5d2f7ba4ca2bde306f80b`,
  `migration=20260809_0098`, `database_control_mode=existing-postgres`,
  `backup_restore=false`, `error=null`.

Out of scope for `测试跑通`: real-person seat bindings and independent
completion review. They are deferred to the enterprise personnel configuration
step and do not block this automated gate.
