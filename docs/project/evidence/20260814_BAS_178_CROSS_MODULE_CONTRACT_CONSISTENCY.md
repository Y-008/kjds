# BAS-178 Cross-Module Contract Consistency Evidence (Red-Team)

## Scope and result

- Task: `BAS-178`
- Kind: independent red-team anti-drift contract test
- Artifact: `tests/test_social_commerce_contract_consistency.py`
- Public API, router, runtime wiring, migration, OpenAPI and dependency changes: none

This audit freezes the mutual consistency of the five BAS-178 governed
social-commerce deep modules and their registries, so any future drift in
action, source-rank, platform, zero-authority or decision vocabularies fails
the suite.

## Audited modules

- `apps/control_plane/social_commerce.py` (contract kernel)
- `apps/control_plane/source_adoption.py` (adapter evaluation)
- `apps/control_plane/social_analysis.py` (derived analysis)
- `apps/control_plane/campaign_authority.py` (grant lifecycle)
- `apps/control_plane/delivery_manifest.py` (media handoff, BAS-188)

## Findings

- `ALLOWED_ACTIONS` identical across `social_commerce` and `campaign_authority`
  (11 actions).
- `ALLOWED_PLATFORMS` identical across `social_commerce` and `social_analysis`
  (`xiaohongshu`, `douyin`).
- `SOURCE_LADDER` / `ALLOWED_SOURCE_RANKS` identical across `source_adoption`
  and `social_commerce` (5 ranks).
- `ZERO_AUTHORITY_KEYS` identical across all five modules (10 keys).
- `DECISIONS` matches `social_commerce_source_adoption.json`
  `decision_vocabulary`.
- `social_commerce_contracts.json` platforms / source ladder / actions /
  dimensions match the module constants.

## Documented boundaries

- The operational registry `social_commerce_source_adoption.json` uses
  narrower rank-3/4/5 ids than the evaluator `SOURCE_LADDER`; ranks 1 and 2
  agree (`official_authorized_api`, `official_operator_export`). Both are
  aligned to ADR-0090; the evaluator ladder is the frozen input vocabulary.
- `delivery_manifest` exposes `_zero_authority()` (private) while the other four
  modules expose public `zero_authority()`; semantics and key set are identical.

## Verification record

Working directory: `D:\KJDS\kjds`

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_social_commerce_contract_consistency.py --basetemp D:\KJDS\pytest-consistency
......... [100%]
9 passed in 0.07s

.\.venv\Scripts\ruff.exe check --no-cache tests/test_social_commerce_contract_consistency.py
All checks passed!
```

## Artifact hashes

- test `tests/test_social_commerce_contract_consistency.py` (git blob)
  `d1a67a4f9c71e037a99f63939f611d9c311a706b`

No production collection or external execution is implied by this audit.
