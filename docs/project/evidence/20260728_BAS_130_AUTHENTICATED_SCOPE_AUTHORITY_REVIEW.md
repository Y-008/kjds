# BAS-130 Authenticated Scope Authority Review — Engineering Evidence

## Decision

`BAS-130` is the next bounded M0 deep slice after BAS-129. It closes the gap between
uploader-authored reviewer metadata and a real independently authenticated review.
It does not create owner authority or advance the Release Gate.

## Gap audit

- BAS-106 already owned append-only grant/revoke projection.
- BAS-129 already owned zero-write preflight and verifier-driven Authority Graph.
- The old admission contract could read `reviewed_by` from the uploader's metadata;
  no independently authenticated review record or source→review lineage was
  required.
- The real identity inventory has separate owner/reviewer/admin/subject-capable
  actors, but the real database has no account-owner artifact. Engineering therefore
  must prove the happy path in isolated tests and keep the live path fail-closed.

## Implemented slice

- `ScopeGrantAuthority.submit_source(...)` captures exact-scope grade B owner source
  Evidence with a stable idempotent source reference.
- `ScopeGrantAuthority.review_source(...)` records accepted/rejected grade A review
  Evidence under the authenticated reviewer and appends immutable source lineage.
- Preflight/current/record require current intact source and review hashes, exact
  scope/decision/effective time, accepted complete checks and four distinct
  owner/reviewer/recorder/subject identities.
- Any matching independent rejection blocks admission.
- Generic Evidence upload rejects reserved authority sources and metadata; dedicated
  authenticated source/review routes are exported in OpenAPI.
- Alembic `20260728_0069` adds partial unique source-reference indexes without
  backfill.
- Authority Graph `next_safe_action` now names the executable chain:
  owner source → accepted independent review → non-mutating preflight.

## Migration verification

An isolated PostgreSQL database completed upgrade to 0069, downgrade to 0068 and
re-upgrade to head. A separate upgraded probe showed both real partial unique indexes
on `public.evidence_records`; both temporary databases were force-dropped by exact
name.

The existing real database was then migrated forward only:

- revision: `20260728_0068 → 20260728_0069`;
- Evidence: `58 → 58`;
- scope grant events: `0 → 0`;
- GoalTasks: `24 → 24`;
- Observations: `54 → 54`;
- Graph nodes/edges/bindings: `66/71/33 → 66/71/33`;
- real `scope_authority_source` and `scope_authority_review`: both `0`;
- both partial unique indexes present.

No synthetic owner source, review or grant was written.

## Automated and delivery verification

- focused scope/Truth/API/observer tests: `29 passed`;
- final full backend: `772 passed, 9 warnings in 32.39s`;
- full Ruff: clean;
- Web contract tests: `55 passed`;
- production Web build: `33/33` pages;
- OpenAPI regenerated with dedicated source/review routes;
- secret scan: `747` non-ignored worktree files and `581` historical paths;
- `git diff --check`: no whitespace error; existing CRLF conversion warnings only.

Final resolved images:

- API:
  `sha256:9ded0c7ffe9318680d9aac3db399bd9f1d3b0f9507b5410bf91b79bb24067d96`;
- media worker:
  `sha256:a2b601ddd0df7c67b45cb67647bd7804afbdbe197900013e207a7505dabd6b24`;
- Web:
  `sha256:e8b70b97ee41acaf34b72dc0fddd0bda3a8195f01127f2313d0aef8a8ad407b4`.

API, media worker, PostgreSQL and Web were all healthy.

## Live API and Graph acceptance

- authority source without a credential: `401`;
- operator attempting owner-source submission: `403`;
- generic Evidence upload using reserved `scope_authority_source`: `422`;
- missing-owner-Evidence preflight: `200/blocked` with
  `scope_authority_evidence_missing`,
  `event_recorded=false` and `external_write_allowed=false`;
- observer at revision 0069: `200`, same-hour result hash stable, Observation count
  remains `54`;
- states: `scope_authority=no_data`, `M0=no_data`, `M1–M4=blocked`;
- Authority node: `fresh/no_data`, verifier `scope-grant-current@1`, Observation
  `obs_7e4d73931cc097df151cdf18ff1859d6`, artifact
  `/v1/scope-grants/current`, owner and `SLA 86400s`;
- model self-certification and external writes: both `false`.

## Browser acceptance

The rebuilt `/authority-graph` was inspected in the real in-app browser:

- desktop `innerWidth=1280`, `clientWidth=scrollWidth=1265`;
- mobile override `390×844`, `clientWidth=scrollWidth=375`;
- no page-level horizontal overflow at either width;
- the current Authority card retained fresh/no_data, why, owner, SLA, verifier,
  Observation, artifact and the new source→review→preflight next action;
- Project/Requirements/Engineering/Runtime/Evidence/Commerce/Authority navigation and
  verifier/TODO drill links remained present;
- browser logs were empty.

## Current operating truth

- Current scope grant: `no_data`.
- M0: `no_data`; M1–M4: `blocked`.
- Real owner source/review/grant rows: `0/0/0`.
- Dedicated monitor identity and Windows Task: not deployed.
- Release Gate: `REJECTED`.
- External commerce writes: closed.
