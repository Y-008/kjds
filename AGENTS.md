# KJDS repository instructions

## Project source of truth

- Before changing code, read `docs/project/MASTER_SPEC.md` in full enough to identify the affected requirement, layer, Gate, Owner, and acceptance evidence.
- The master spec is the design source of truth; `apps/`, `migrations/`, `scripts/`, and `tests/` are the implementation and verification layers.
- Do not put architecture decisions, business rules, or API contracts only in a prompt or code comment. Update the master spec or a linked ADR first.
- Preserve the three-layer boundary: Architecture → Patterns & Abstractions → File-level Code.

## Runtime

- Use the project-local uv environment and Python 3.12.
- Run Python commands through `uv run`; do not use Codex bundled Python as the project interpreter.
- Keep PostgreSQL in Docker Compose. Do not install or start a second host/WSL PostgreSQL for this project.
- Do not add Redis, Kafka, Kubernetes, Temporal, vector databases, or local model runtimes until an accepted ADR introduces them.

## Architecture

- Keep business logic inside domain/application services; Agents and connectors may not write repositories directly.
- External providers must implement connector/provider protocols.
- High-risk actions require approval and audit records.
- Monetary calculations use `Decimal`, explicit currency, FX rate/date, and evidence references.
- Every schema change requires an Alembic migration.

## Quality gates

Before finishing a code change, run:

```text
uv run python scripts/verify_secrets.py
uv run ruff check .
uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local
git diff --check
```

For Web changes also run `npm ci`, `npm test`, and `npm run build` from `web/`.

For database/API changes also run PostgreSQL, verify there is one Alembic head, migrate to head, and verify `/health/ready`.

For every change, perform both review and verification:

- Review: requirement alignment, behavior boundaries, API/data contract, security/privacy, architecture, reliability, and delivery completeness.
- Verification: tests, lint/type/build checks, migration replay, smoke tests, and `git diff --check` as applicable.

Do not treat a passing test as proof that the requirement was implemented correctly; record unresolved findings as `P0/P1/P2/Info` with `auto-fix`, `ask-user`, `defer`, or `no-op` handling.

## GitHub delivery

- Put shared changes on a branch and merge them through a pull request; do not push directly to `main`.
- Do not merge while `backend-quality`, `web-quality`, or `postgres-smoke` is failing, or while review conversations remain unresolved.
- Use squash merge, then synchronize the local `main` with `origin/main`.
- GitHub branch protection is active on public repository `Y-008/kjds`: changes to `main` require a pull request, the three required CI checks, resolved review conversations, linear history, and no force push or branch deletion. Administrators do not bypass the rule.

## Safety

- Never commit `.env`, credentials, bank information, platform secrets, database dumps, or customer data.
- Do not delete or overwrite user documents and media in this repository.
- Preserve existing user changes and avoid destructive Git operations.

## Capability gap policy

- When a required capability is missing, first reuse an installed tool or project contract; then search official documentation and maintained official/GitHub skills or plugins before building a replacement.
- Install only the smallest capability that has a clear immediate KJDS use, reviewable source, compatible license, and bounded permissions. Record unavailable, unverified, abandoned, duplicated, or speculative candidates instead of installing them.
- A newly installed skill or plugin may not receive store credentials, payment authority, listing/purchase/price-write scopes, or canonical-data ownership without the existing architecture, security, approval, audit, rollback, and acceptance gates.
- Treat third-party feature claims and calculators as candidates until their API contract, provenance, terms, versioning, exportability, revocation, and reconciliation against original evidence are verified.

## Material solution selection

- Material product, architecture, provider, data-source, automation, and business choices must use the versioned `best_solution` decision profile instead of selecting by novelty, popularity, feature count, or implementation convenience.
- Eliminate any option that violates security, evidence, authority, legal/compliance, budget, acceptance, rollback, or source-of-truth constraints before comparing benefits.
- Among feasible options, compare evidence-backed long-term risk-adjusted value, total cost of ownership, maximum loss, reversibility, time to value, operational fit, maintenance, and replacement cost. Do not generate an equal-weight score when the dimensions are not commensurable.
- Include a no-action or defer option when feasible. Record the selected option, rejected alternatives and reasons, sensitivity, invalidation conditions, review date, and approval requirement.
- Ponytail/YAGNI may remove complexity only after the best feasible solution is identified; minimum code is not itself the objective.

## Frontier technology review

- Before every material product, architecture, dependency, security, privacy, data, automation,
  provider or commercial change, read `docs/project/registries/frontier_technology_adoption.json`
  and check the relevant candidates' `as_of`, `reviewed_on`, `review_due_on`, Owner and Gates.
- Verify only task-relevant candidates against current official documentation, formal specifications,
  official release notes or primary research. Simple, local and reversible fixes may record
  `frontier_review=not_required` instead of performing an unrelated scan.
- Record a dated review receipt in the task's engineering Evidence with exact scope, candidate IDs,
  official sources, observed changes, decision, registry/ADR references, unresolved items and next
  review. Use `checked_no_change` when the evidence does not change an adoption decision.
- When upstream facts or KJDS fit change materially, update the registry and linked research Evidence
  together, and update the affected ADR or stable requirement when its boundary changes. Never update
  only `as_of`, `reviewed_on` or `review_due_on` to simulate freshness.
- A newer release is not automatic authorization to install, upgrade or deploy. Continue to use
  `best_solution`, `adopt_now/pilot/watch/reject_now`, entry/exit Gates, independent review and
  rollback evidence; frontier review cannot grant external write, Fact, FinanceEntry, Approval or Permit.

## Coding Agent workflow for complex changes

Simple, local, reversible fixes may move directly from inspection to implementation and targeted
verification. Cross-Module, authority, data, commercial, privacy, security or architecture changes
must use this workflow without creating a second documentation center:

1. Build project context from `项目.md`, README, `MASTER_SPEC`, linked ADRs, the dynamic task plan,
   registries, test entry points, Git status and the current write-domain/migration leases.
2. Classify impact and record affected requirements, Modules, authorities, failure modes, Gates,
   Owners, acceptance Evidence and whether the frontier review is `required` or `not_required`.
3. Update stable requirements, ADR decisions, machine contracts and acceptance criteria before or
   with the implementation; prompts and code comments are not a durable source of truth.
4. For a material Interface or architecture decision, compare at least two feasible designs,
   including defer/no-action when relevant, and record rejection reasons and invalidation conditions.
5. Implement in independently testable and reversible slices: registry/schema validation first,
   server-side projection second, Web third and external authorities last.
6. Verify continuously with targeted tests, then run the applicable full regression, Web production
   build, secret scan and diff checks. A passing test is necessary but not proof of business truth.
7. Perform an independent completion review for requirement alignment, permissions, privacy,
   reliability, recovery, delivery completeness and false completion claims.
8. Evolve documentation and code together; finish by updating task status, engineering Evidence,
   unresolved business gaps and the one next action.

This workflow does not require approval after every step. Pause only for new external permissions,
real payment, contract signature, marketplace write, human appointment or a material scope change.
