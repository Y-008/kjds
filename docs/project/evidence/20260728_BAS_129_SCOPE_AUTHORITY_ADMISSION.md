# BAS-129 Scope Authority Admission — Engineering Evidence

## Decision

`BAS-129` is a bounded M0 engineering slice. It adds a non-mutating scope-authority
admission verifier and connects exact current authority to verifier-owned Graph/TODO
state. It does not create or imply owner authority. The real release remains
`REJECTED`.

## Gap audit

- BAS-106 already provided append-only grant/revoke authority and deterministic
  `as_of` resolution.
- BAS-127/128 already provided monitor observations, stable Graph nodes and immutable
  Node→GoalTask status bindings.
- The real database has no scope grant.
- There was no safe pre-commit verifier artifact for an owner/reviewer/compliance
  grant packet.
- Authority Graph did not have an exact-current-grant task independent of generic M0
  stage readiness.

## Implemented slice

- `ScopeGrantAuthority.preflight(...)` and `record(...)` share the same frozen request,
  Evidence, separation-of-duty, scope and idempotency validation.
- `POST /v1/scope-grants/preflight` is restricted to compliance/admin and performs no
  write.
- The operating observer records `scope-grant-current@1` from the exact principal,
  store and `as_of` projection.
- Stable task `task-m0-scope-authority-admission` and node
  `authority:current-scope-grant` expose fresh/no_data/blocked/passed, why, next,
  Owner, SLA, verifier, Observation and artifact through the existing Graph kernel.
- Missing owner Evidence remains `no_data`; no synthetic grant is created.
- `external_write_allowed=false`, `approval_created=false` and
  `permit_created=false`.

## Automated and delivery verification

- focused scope/Truth/observer/Graph regression: `21 passed`;
- post-live-defect focused regression: `11 passed`;
- final full backend: `769 passed, 9 warnings in 30.24s`;
- full Ruff: clean;
- Web contract tests: `55 passed`;
- production Web build: `33/33` pages and 33 routes;
- OpenAPI regenerated with protected
  `POST /v1/scope-grants/preflight`;
- secret scan: `746` non-ignored worktree files and `581` historical paths;
- `git diff --check`: no whitespace error; existing CRLF conversion warnings only.

The final resolved delivery images are:

- API
  `sha256:c3637da572570f7c2db599d8a0a2462b330b8e1b2b456f85b5bfd3899264da28`;
- media worker
  `sha256:ee2dbcc5ad42095d712ab4c43e6a312aaafbeff4c7c1ae97340f32dd45cd91a7`;
- Web
  `sha256:bc92ffe7d1547e7b1b3f3d6686d60af8df5252ca1b774b583a8ac2efdacd5539`.

API, media worker, PostgreSQL and Web were all externally `healthy`.

## Real PostgreSQL and live API acceptance

The existing real database remained at revision `20260728_0068`; BAS-129 adds no
schema and does not rewrite BAS-124–128.

The canonical seed replay produced:

- `24` GoalTasks;
- `66` Graph nodes;
- `71` edges;
- `33` immutable node-status bindings;
- `53` pre-observation append-only Observations.

The first live observation found a real integration defect: the observer expected the
new canonical Authority node to have mutable `authority=observed`, returned `404` and
correctly wrote no Observation. The implementation was corrected so canonical node
content stays immutable and only the bound GoalTask Observation advances status.

The rebuilt live endpoint then returned `200` and appended exactly one new
scope-authority Observation:

- final Observation count: `54`;
- `scope_authority=no_data`;
- `M0=no_data`;
- `M1–M4=blocked`;
- Authority observation:
  `obs_7e4d73931cc097df151cdf18ff1859d6`;
- Authority node status: `no_data · fresh`;
- artifact: `/v1/scope-grants/current`;
- verifier: `scope-grant-current@1`;
- release status: `blocked`.

Two additional same-hour observer replays both returned `200` with the identical
result hash and kept the Observation count at `54`.

The live missing-owner-Evidence preflight returned `200/blocked` with
`scope_authority_evidence_missing`. `scope_grant_events` was `0` before and `0`
after. The same route returned `401` anonymously and `403/PERMISSION_DENIED` to an
operator. No key or private Evidence content was printed.

## Browser acceptance

The rebuilt Authority Graph was inspected in a real in-app Chromium tab.

Desktop:

- page title `KJDS · Ozon 统一经营平台`;
- `clientWidth=1265`, `scrollWidth=1265`;
- 25 rendered cards;
- the current-scope node showed `NO_DATA · FRESH`, exact Owner, `SLA 86400s`,
  `scope-grant-current@1`, the Observation ID and current-scope artifact;
- no error banner and browser logs were empty.

CDP device emulation then set an actual `390×844` mobile viewport:

- `innerWidth=390`;
- `clientWidth=390`, `scrollWidth=390`;
- `matchMedia("(max-width: 420px)")=true`;
- node card width `324.4px`;
- the same fresh/no_data verifier drilldown remained visible;
- no error banner and no horizontal overflow.

## Current operating truth

- BAS-130 subsequently hardened the reviewed-Evidence contract to require an
  authenticated owner source, an independently authenticated append-only review and
  immutable source→review lineage; see
  [BAS-130 Evidence](20260728_BAS_130_AUTHENTICATED_SCOPE_AUTHORITY_REVIEW.md).
- Current scope grant: `no_data`.
- M0: `no_data`.
- M1–M4: `blocked`.
- Dedicated monitor identity and Windows Task: not deployed.
- Release Gate: `REJECTED`.
- External commerce writes: closed.
