# BAS-187 Governed TutorialGraph & Windows Agent Evidence

## Scope and result

- Task: `BAS-187`
- Deep module: `GovernedTutorialGraphWorkspace.compile(application_ref, feature_nodes, capture_policy, narration_profile, idempotency_key)`
- Result type: deterministic, content-addressed `TutorialGraphOutcome` (with `TutorialStep`, `TutorialReadback`, `TutorialLecture`)
- Provider admission: `tutorial.build` repointed from `windows_agent` to the internal deterministic compiler `kjds_internal_tutorial_compiler`
- Public API, router, runtime job loop, migration, OpenAPI and dependency changes: none
- External/network/platform writes: zero

This Gate establishes a deterministic internal tutorial-graph compiler. Software
feature nodes are compiled into operations, UI anchors, screenshots, narration
and lecture artifacts; every step is readback/restore-capable. Sensitive windows
and credential regions are masked by default and raw credential payloads are
rejected. The real Windows desktop capture provider (`windows_agent`) stays
`not_admitted`.

## Compiler semantics

- `compile(...)` deterministically sorts feature nodes (stable topological
  order), rejects duplicate ids, unknown dependencies, self-loops and cycles,
  and seals the graph with a canonical `graph_sha256` bound to the idempotency
  key.
- `readback(outcome, feature_id, observed_placeholder)` projects
  `PENDING` / `VERIFIED` / `INVALIDATED`; masked steps are not verifiable against
  a raw placeholder.
- `invalidate(outcome, feature_id, reason_code)` and
  `mark_stale(outcome)` project `INVALIDATED` / `STALE`.
- `assemble_lecture(outcome, language)` yields a deterministic, hash-bound
  lecture artifact (`content`, `lecture_sha256`, `step_count`).
- Sensitive region policy: `mask_sensitive_regions` defaults true; a sensitive
  step without masking is rejected; credential-looking payloads
  (`password:`, `token=`, `bearer `, `authorization:`, `api_key=`, `secret=`)
  are rejected before hashing or projection.

## Zero-authority conservation

Every outcome preserves literal zero authority for: `Fact`, `FinanceEntry`,
`Approval`, `Permit`, `Pilot`, `Outbox`, canonical Graph write, dependency
install, network and external write. `external_write_allowed` and
`listing_eligible` are both `False`; `windows_agent_admitted` is `False`.

## Provider admission

- `tutorial.build` accepted provider: `kjds_internal_tutorial_compiler`.
- Required capabilities: `["tutorial_graph", "structured_output"]`.
- Cost ceiling: 0 USD, basis `internal_deterministic_compiler_no_provider_charge`.
- External side effect: `internal_deterministic_compile_only`.
- Binding SHA-256: `d0a0eb549be5a81cadb249bac37efce7a71768d49898c0c690dd7fd745f01a79`
  (`sha256(b"kjds-internal-tutorial-graph-compiler-v1")`).
- `windows_agent` remains a registerable connector provider (`not_admitted` for
  real desktop capture) and is no longer the accepted provider for
  `tutorial.build`.

## Verification record

Working directory: `D:\KJDS\kjds`

```text
.venv\Scripts\python.exe -m pytest -q tests/test_tutorial_graph.py --basetemp D:\KJDS\pytest-bas187-verify
27 passed

.venv\Scripts\python.exe -m pytest -q tests/test_media_connectors.py tests/test_media_connectors_api.py tests/test_media_agent_contracts.py tests/test_editing_blueprint.py tests/test_editing_blueprint_runtime_composition.py tests/test_commander_tool_gateway.py tests/test_tutorial_graph.py --basetemp D:\KJDS\pytest-bas187-verify5
136 passed

.venv\Scripts\ruff.exe check --no-cache apps/control_plane/tutorial_graph.py apps/control_plane/media_connectors.py apps/control_plane/commander_tool_gateway.py tests/test_tutorial_graph.py tests/test_media_connectors.py tests/test_media_agent_contracts.py
All checks passed!
```

Negative contracts covered include duplicate/self/unknown/cyclic dependency
rejection, stable topological ordering, unsupported operation/anchor, sensitive
region masking, sensitive-without-masking rejection, raw credential rejection,
forbidden field keys, invalid policy/profile, readback PENDING/VERIFIED/
INVALIDATED, masked-step non-verifiability, invalidation, staleness,
deterministic lecture assembly, zero-authority flags, and `windows_agent`
not-admitted.

## UNKNOWN retained

- real Windows desktop capture admission and authority;
- production source latency, availability and operating cost;
- real tutorial narration coverage and quality uplift;
- human review throughput and production action thresholds.

## Remaining (next slice, not part of this commit)

- a `record_tutorial_result(...)` recorder in `media_jobs.py`;
- `runtime.py` / `media_worker.py` routing of `tutorial.build` to the compiler.

These remain for the BAS-183 media-job execution slice; `windows_agent` real
capture is intentionally `not_admitted`.
