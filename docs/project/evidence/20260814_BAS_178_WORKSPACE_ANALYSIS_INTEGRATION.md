# BAS-178 Workspace Analysis Integration Evidence

## Scope and result

- Task: `BAS-178`
- Change: wire the deep `GovernedSocialIntelligenceAnalysis` into
  `GovernedSocialCommerceIntelligenceWorkspace.analyze`
- Public API, router, runtime wiring, migration, OpenAPI and dependency changes: none
- Real platform adapters, account bindings and platform writes: `not_admitted`

This slice closes the ADR-0090 acceptance #4 gap in the workspace: `analyze`
now delegates to the deep analyzer when conserved records are available, so
each requested dimension carries real derived analysis (seller segments,
comment intents, content structure, product demand, calendar) instead of only
per-dimension record counts.

## Change surface

- `analyze(spec, batch)` is backward compatible: each pattern keeps `dimension`,
  `record_count` and `derived` and now also carries `analysis` (the real derived
  output for that dimension) and `analysis_gaps` when records exist.
- Empty batches still produce the truthful placeholder with no analysis.
- The dimension-to-output mapping is fixed: `actor` -> `seller_segments`,
  `conversation` -> `comment_intents`, `content` -> `content_structures`,
  `seller_product` -> `product_demands`, `time` -> `calendar`.

## Verification record

Working directory: `D:\KJDS\kjds`

```text
.\.venv\Scripts\python.exe -m pytest -q tests/test_social_commerce.py tests/test_social_analysis.py --basetemp D:\KJDS\pytest-sc-integ
................................... [100%]
35 passed in 0.09s

.\.venv\Scripts\ruff.exe check --no-cache apps/control_plane/social_commerce.py tests/test_social_commerce.py
All checks passed!
```

Full social lane regression: `119 passed`.

## Artifact hashes

- module `apps/control_plane/social_commerce.py` (git blob)
  `401f11851410ee18503d5b2609ee98473e9a85f1`
- tests `tests/test_social_commerce.py` (git blob)
  `79d4a73e39766ffa88d3d4f1d2f4a1c1e90d1dd3`

No production collection or external execution is implied by this integration.
