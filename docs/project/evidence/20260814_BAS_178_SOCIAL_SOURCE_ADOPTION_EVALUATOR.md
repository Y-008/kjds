# BAS-178 Social Source Adoption Evaluator Evidence (First Slice)

## Scope and result

- Task: `BAS-178`
- Deep module: `GovernedSourceAdoptionEvaluator` (`evaluate` / `readback` /
  `zero_authority`)
- Result type: immutable, content-addressed `SourceAdoptionDecision`
- Public API, router, runtime wiring, migration, OpenAPI and dependency changes: none
- Real adapter runtime installation, account binding and platform writes: `not_admitted`

This slice freezes the ADR-0090 source-rank ladder and deterministic adapter
evaluation. A candidate adapter is validated against the ladder and its declared
decision, and an exact unauthenticated state is reported. No adapter runtime is
installed or executed here, and cross-account credentials never mix.

## Contract surface

- `evaluate(candidate) -> SourceAdoptionDecision` — validates `candidate_ref`,
  `version`, `license_id`, `commit_sha256` (64-bit hex), `source_rank`,
  `decision` and `authenticated`, then emits a content-addressed decision.
- `readback(decision, observed?)` — `PENDING` without an observed hash,
  `VERIFIED` on hash match, `INVALIDATED` on mismatch.
- `zero_authority()` — every conservation key is literal `false`.

## Admission model

- Source rank ladder (frozen, 5 ranks): `official_authorized_api`,
  `official_operator_export`, `operator_cli_or_browser`, `public_official_page`,
  `manual_evidence`.
- Decision vocabulary: `preferred_path`, `adopt_pattern`, `pilot_isolated`,
  `watch`, `reject_runtime`.
- `preferred_path` requires `official_authorized_api`; an unauthenticated
  preferred path records `preferred_path_unauthenticated` instead of failing.
- `reject_runtime` conflicts with `apache-2.0` / `mit` / `bsd-3-clause`
  licenses and is rejected (deterministic guard, never subjective judgment).
- Sensitive values (credential fields, tokens, cookies, private keys, `sk-`)
  are rejected before hashing; input nesting, key type and value type are
  bounded and validated.

## Zero-authority conservation

Every outcome preserves literal `false` for: Fact, FinanceEntry, Approval,
Permit, Pilot, Outbox, canonical Graph write, dependency install, network and
external write.

## Verification record

Working directory: `D:\KJDS\kjds`

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_source_adoption.py --basetemp D:\KJDS\pytest-source-adoption
............ [100%]
12 passed in 0.10s

.\.venv\Scripts\ruff.exe check --no-cache apps/control_plane/source_adoption.py tests/test_source_adoption.py
All checks passed!
```

Broader social/delivery focused group (source adoption, social commerce,
delivery manifest, source adoption registry, opencli read-only contract,
delivery readback, scoped delivery exceptions): `78 passed`.

Covered negative contracts include unknown source rank, unknown decision,
preferred path without official API, reject runtime license conflict,
unauthenticated preferred path, bad commit SHA, sensitive candidate value,
non-boolean authenticated flag, readback verify/invalidate, and zero-authority
flags.

## Artifact hashes

- module `apps/control_plane/source_adoption.py` (git blob)
  `bdbebc9ea94bbc32040e827345ac508430488a2a`
- tests `tests/test_source_adoption.py` (git blob)
  `794023cf928b0064873e43aa7ca2188cc2769da5`

## Known boundary (P2, no runtime defect)

The evaluator freezes its own 5-rank `SOURCE_LADDER` id vocabulary
(`operator_cli_or_browser`, `public_official_page`, `manual_evidence`).
`docs/project/registries/social_commerce_source_adoption.json` uses a parallel
operational ladder with distinct rank-3/4/5 ids
(`dedicated_visible_browser_observation`, `public_official_or_indexed_page`,
`manual_observation`). Both are semantically aligned to the ADR-0090 ladder
(official API > operator export > operator CLI / visible browser > public
official / indexed page > manual Evidence), and the decision vocabulary matches
exactly. A future integration slice must map registry rank ids to evaluator
rank ids rather than assuming string identity.

## UNKNOWN retained

- real platform account binding and authentication;
- real adapter runtime installation and execution;
- upstream license classification beyond the declared `license_id`;
- production adapter latency, availability and operating cost.

No production collection or external execution is implied by this contract slice.
