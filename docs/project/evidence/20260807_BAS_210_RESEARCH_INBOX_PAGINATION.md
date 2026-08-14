# BAS-210 scoped Research Inbox pagination Evidence

- Status: expanded current-byte implementation under focused verification;
  independent freeze review pending.
- Trigger: `ResearchInboxService.list` previously loaded the newest 500 global
  Evidence records and filtered `research_signal` rows in Python. Reserved
  closed-loop Evidence and unrelated roles could therefore consume the bounded
  window, hide valid research signals, and expose load-dependent availability.
  The initial BAS-210 implementation removed that first-page starvation but
  left ordinary research Evidence globally visible and did not expose a real
  continuation cursor.
- Boundary: Evidence query, Research Inbox service, its existing route, API
  contract snapshot, tests, and this Evidence only. No migration, runtime,
  database schema, Fact, Approval, Permit, finance entry, or external-write
  change.

## Contract

- `EvidenceService.list_for_governance` applies exact four-field scope,
  `evidence_role`, `research_capture_contract_id`, and candidate lineage
  `EXISTS`/subquery predicates in SQL before `recorded_at DESC, id ASC`
  ordering and `LIMIT`. Candidate IDs are not materialized into an unbounded
  Python or SQL parameter list.
- Research Inbox passes `closed_loop_scopes=()`, so every source in
  `CLOSED_LOOP_RESERVED_SOURCES` is excluded before the bounded page regardless
  of metadata or foreign scope values.
- Ordinary `research_signal` rows must match current `tenant_ref`, `entity_ref`,
  `store_ref`, and `scope_grant_authority_sha256`; foreign-scope research rows
  cannot consume the page or become visible.
- Capture uses a server-generated source reference derived from canonical
  provider-record ID plus exact scope. The original provider ID remains in
  metadata. This keeps same-scope replay idempotent while preventing the global
  Evidence dedup key from returning or linking another scope's winner. A
  canonical `kjds-research-capture-request-v1` SHA freezes content hash,
  filename, content type, provider and record ID, source URL, canonical
  observed time, declared grade, license state, normalized raw fields, and the
  exact four-field scope. Candidate references are deliberately outside that
  immutable request so an exact replay may add lineage; every other request
  drift fails before any new candidate link. A changed provider export must
  carry a new stable provider record ID rather than silently widening an old
  winner.
- Research role and capture-contract metadata are reserved by
  `EvidenceService`; generic capture cannot mint either. The dedicated Research
  adapter has its own capability token and therefore cannot bypass channel,
  team-agent, coverage, or closed-loop reserved-source ownership. Every row is
  revalidated against the exact Research metadata key set, canonical
  `captured_at`, scope binding, source reference, blob hash, grade, license,
  and immutable request SHA before it is projected. Stored `raw_fields` are
  also re-run through the canonical capture validator and must remain exactly
  equal, so a self-consistently rehashed legacy or direct row cannot smuggle a
  server-only key into readback.
- Public capture/list require an explicit authorized `store_ref`. ScopeGrant
  authority is resolved from server trusted-now, never from the pagination
  timestamp. A missing authority returns no list data; blocked authority fails
  closed. Capture rechecks the current exact scope after file and JSON parsing,
  then before and after Evidence/blob/lineage writes inside one SQLAlchemy
  transaction. Revoke or rotation at either transaction guard rolls back all
  three domains; list also rechecks current authority before returning rows.
  PostgreSQL capture takes the same transaction advisory-lock key as the 0094
  append-only ScopeGrant trigger (`tenant_ref`, `store_ref`, subject actor), so
  authority mutation cannot commit between the final guard and Evidence
  commit. Non-string scope components are rejected before query or write.
- Candidate lineage remains additive only within one immutable signal, and the
  transaction checks the union of existing plus requested targets. The
  cumulative set may never exceed 20 even across exact replays.
- Keyset continuation uses the existing response's last
  `evidence.recorded_at` and `evidence.id`. The timestamp must be canonical UTC
  `+00:00`; both cursor components are required. Cursor admission reuses the
  same scope, role, and candidate-lineage predicate and checks the database
  timestamp before applying the second-page boundary.
- Stored Research Evidence retains the exact scope, current authority, scope
  binding, immutable request, and capture-contract fields required for
  integrity verification. Those fields are server-only. Capture and list use
  an explicit public Evidence projection whose metadata is exactly
  `evidence_role`, `provider`, `provider_record_id`, `source_url`,
  `captured_at`, `raw_fields`, `license_status`, `review_status`,
  `declared_grade`, and `promotion_status`. The public `source_ref` preserves
  the prior provider-record value rather than exposing the scope-bound storage
  reference. Raw provider fields may not impersonate a server-only contract
  key. Both endpoints share a strict FastAPI response model that reuses the
  same raw-field validator; its OpenAPI metadata object forbids additional
  properties.
- The existing Research Inbox response remains a list of integrity-checked,
  auxiliary-only observations. Recursive API tests prove tenant, entity,
  store, authority, scope-binding, request-hash, and capture-contract fields
  never enter capture or list responses. The projection does not mutate the
  stored Evidence, promote it into a Fact, or authorize listing, procurement,
  finance, or any external action.

## Current-byte proof

- Expanded machine-CAS commit:
  `3080adf578a103c6a6092803bae227241c14004a`.
- Python `py_compile` and target Ruff: PASS.
- Research Inbox service tests: `38 passed in 0.90s`.
- Current-HEAD combined Evidence and Research Inbox regression:
  `54 passed in 1.17s`.
- Bounded API route, response-model, and runtime OpenAPI snapshot regression:
  `9 passed, 47 deselected, 1 warning in 2.39s`.
- An attempted whole `tests/test_api_contract.py` run produced no attributable
  test failure but exceeded the 120-second command limit. Its exact owned
  `uv`/`pytest`/Python process tree was terminated and all child processes plus
  ports `5432`, `8010`, and `3010` were confirmed clear; that run is not counted
  as a Gate.
- Final Python `py_compile`: exit `0`; target Ruff:
  `All checks passed!`; `git diff --check`: exit `0`; staged paths: `0`.
- Secret scan: `1411` non-ignored worktree files and `1410` historical
  paths checked, PASS.
- Adversarial fixtures place 505 newer rows ahead of a valid signal, spanning
  all reserved closed-loop sources, ordinary cross-role Evidence, and ordinary
  foreign-scope `research_signal` Evidence, plus a same-scope forged Research
  role without the capture contract. The valid same-scope signal remains
  visible and the decoys consume zero page slots.
- The pagination matrix traverses 105 equal-timestamp eligible rows across the
  100-row boundary without duplicates or omissions. Candidate, foreign-scope,
  authority-rotation, and timestamp-drift cursors fail closed.
- Cross-scope capture uses the same provider, provider record, content, and
  effective time yet produces independent Evidence IDs; same-scope replay keeps
  one ID. A deliberately drifted dedup winner fails before a new candidate
  lineage can be written.
- Eight request-drift cases cover content, filename, content type, source URL,
  observed time, declared grade, license status, and raw fields, including the
  literal `A` to `D` and `verified` to `restricted` attacks. Each raises a
  pre-link conflict while Evidence record/blob/lineage counts stay at the
  original `1/1/1`. A real service/SQLite rotation window fails the final guard
  and proves new record/blob/lineage residue remains `0/0/0` and the Inbox is
  empty.
- Generic Evidence capture cannot forge either the Research role or contract;
  the Research adapter cannot claim a closed-loop reserved source. Non-string
  exact-scope and candidate values fail before persistence. An exact replay may
  add candidates only up to the cumulative 20-target ceiling; the 21st target
  leaves the existing `1/1/20` record/blob/lineage baseline unchanged.
- Capture and list service responses freeze the prior ten-key public metadata
  contract while the stored record retains all seven server-only fields. API
  tests reject each internal-field injection both at metadata top level and
  beneath `raw_fields` through the strict response model. Seven independently
  self-consistent seeded rows with those keys nested in stored `raw_fields`
  fail list/readback while record/blob/lineage remains `1/1/0`; the OpenAPI
  snapshot freezes the same exact allowlist.
- The earlier exact4 candidate `581AA20B...E896` is superseded and must not be
  staged or released. Final combined regressions, snapshot equality, secret
  scan, exact7 hashes, and independent read-only signoffs follow this Evidence
  update.
