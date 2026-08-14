# BAS-215C Enterprise AI ERP Team Control API/Web Evidence

## 1. Scope and claim boundary

- task: `BAS-215C`
- baseline: `1a1745e14054e77e40c8ed8d913b77f6fc96e187`
- claim: the existing Team Control `brief` exposes the six BAS-215B enterprise projections through
  a strict API/OpenAPI contract and a read-only, accessible owner workbench.
- not claimed: human staffing, active WIP, available capacity, achieved maturity, release candidate,
  Gate PASS, scheduled train, customer outcome or provider execution.
- excluded: `TeamControlTower`, `EnterpriseAiErpProgram`, runtime composition, `advance`, database,
  migration/0097, PostgreSQL/G-1, dependency upgrades and external writes.

## 2. Exact write set

1. `apps/control_plane/api_contracts.py`
2. `apps/control_plane/routers/system.py`
3. `docs/project/contracts/openapi-v1.json`
4. `tests/test_team_control_tower_api.py`
5. `web/features/team-control-tower/contracts.ts`
6. `web/features/team-control-tower/team-control-tower.tsx`
7. `web/features/team-control-tower/team-control-tower.module.css`
8. `web/lib/team-control-tower-contract.test.ts`
9. `docs/project/MASTER_SPEC.md`
10. `docs/adr/ADR-0095-global-expert-council-and-portfolio-orchestration.md`
11. `docs/project/18_TEAM_CONTROL_TOWER.md`
12. `docs/project/evidence/20260808_BAS_215C_ENTERPRISE_AI_ERP_TEAM_CONTROL_API_WEB.md`

## 3. Contract and negative controls

- `TeamControlBriefOutput` freezes the complete response, forbids undeclared top-level fields and
  requires all six enterprise projections.
- each projection accepts a detailed server-owned contract or its own strict minimal `UNKNOWN`
  variant; missing fields, a mismatched projection name and extra top-level values fail validation.
- both variants freeze current runtime status to `UNKNOWN`; capacity availability and registry
  schedule proof are literal false, and release Gate status is literal `UNKNOWN` until a separately
  versioned runtime-authority contract exists.
- OpenAPI 200 references the named response model rather than an arbitrary object.
- scope-invalid and missing Program states remain explicit; response serialization does not promote
  null observations or static contract integrity.
- the Web requires and renders all six fields. It does not sort the DAG, calculate SoD conflicts,
  capacity, candidates, Gate or schedules.
- static `VERIFIED` is visibly labelled as contract integrity only. Program runtime authority is
  displayed as disconnected.
- errors use an alert, loading/notice use live status, disclosure uses native `details`, keyboard
  focus is visible and the six-panel grid collapses at 680px/420px for 390px operation.
- the section label and low-emphasis panel text use the reviewed dark-on-light palette, and every
  disclosure summary has a 44px minimum target height.

## 4. Verification record

- focused Python after negative-control closure: `53 passed in 6.26s`
- focused Web contract: `4 passed, 0 failed`
- full Web contract suite: `146 passed, 0 failed`
- Next.js production build: PASS; 63 static pages generated and `/team-control` compiled.
- Ruff exact Python set: `All checks passed!`
- OpenAPI export: exit 0.
- OpenAPI runtime snapshot: `1 passed` (one upstream Starlette/httpx deprecation warning).
- test basetemps created by this task were removed and re-read as absent.
- DB/PostgreSQL/G-1: NOT RUN by this slice.

## 5. Frontier freshness and sources

This interface slice introduces no frontier runtime or provider dependency. The existing A2A, MCP
Tasks, GraphRAG and model-eval decisions are not used by the HTTP or Web implementation and their
registry dates were not refreshed. Accessibility was checked against the current project policy and
the official [W3C WCAG 2.2 Recommendation](https://www.w3.org/TR/WCAG22/); result:
`checked_no_change` for semantic structure, keyboard focus, status announcements and reflow scope.
No dependency, registry decision or ADR beyond this Interface choice changed.

## 6. Truthful completion

Engineering completion proves contract validation, saved OpenAPI parity, Web consumption and
production compilation. All six operating projections remain `UNKNOWN` until their named external
authorities are connected. This Evidence cannot create a Fact, FinanceEntry, Approval, Permit,
external write, staffing appointment, release Gate or market claim.

## 7. Frozen candidate (current worktree, pre-commit)

The exact-12 ordered manifest uses `sha256 + two spaces + repository path`, one LF-separated
record per path, hashed as UTF-8. The first eleven non-self SHA-256 values are:

```text
3e2635dd74af4a4cce770fdfbbb2c43b25ba30f57100d3d438ab329e43e13e08  apps/control_plane/api_contracts.py
9e49e939537ceb82d3cc230ab0bed652b2797ac825d19782888314f2357d593f  apps/control_plane/routers/system.py
9a6089dd5200f6baf2fb1f7f20ae4f2f4375906a7d0bb924b58b1369e7524fe9  docs/project/contracts/openapi-v1.json
ffc384a24f455ab6265d9a2d65e77f01a777c8fba847104c56d02de44dd09a1a  tests/test_team_control_tower_api.py
f9208595fde7ae86ff74999dd27456849ecb58e853ac691679feca946f9b0c81  web/features/team-control-tower/contracts.ts
2d9386ad07840ccbd77434d2de5fbad6061298204ab21c29f67ac504a9ff22cb  web/features/team-control-tower/team-control-tower.tsx
e65afaaa293c40bb77992c15dbf58561721db5276e534792c8fc3840bd5d9fde  web/features/team-control-tower/team-control-tower.module.css
4ff5d8b2ef6d46bbb4ff97d7bba3daff5fb441a88531479f8113f6324894dcd5  web/lib/team-control-tower-contract.test.ts
40fa409136d9cdb2b3ad100e2b28f655a11ab92b3e9a5bd7be1b0dc59ef99410  docs/project/MASTER_SPEC.md
a9ca77b9097943341ac631f7c2b6650fce82ba8d380a23163de918cd99a71939  docs/adr/ADR-0095-global-expert-council-and-portfolio-orchestration.md
04889536893086b46d649614ed86bff500ce515f4802373dfe2b9b8de290012c  docs/project/18_TEAM_CONTROL_TOWER.md
```

The Evidence file's own hash is intentionally not embedded in itself; the external freeze receipt
binds that twelfth value and the complete manifest. Independent hash-bound sign-off and exact-path
staging remain required. BAS-183 WIP, user files, migration `0097`, DB and G-1 are excluded.
