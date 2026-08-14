# BAS-163-166 parallel profit/growth/Agent delivery evidence

- Date: 2026-08-02
- Status: COMPLETED_ENGINEERING
- ADR: `docs/adr/ADR-0086-parallel-profit-remediation-profile-growth-agent-runtime.md`

## ZiAgent delivery map

| Delivery | Deep module | Engineering result |
|---|---|---|
| BAS-163 | `ProfitDataRemediationWorkspace` | Full source conservation, blocker grouping, ranked repair queue, stable hashes, no guessing or currency mixing |
| BAS-164 | `StoreProfileIntake` | Evidence-graded proposal, official category roles, review gates and proposal-only authority |
| BAS-165 | `GrowthChannelPort` | VK/Telegram capabilities, attribution funnel, reward lifecycle, fraud controls, one-time Permit and incremental cash CM3 |
| BAS-166 | `GovernedAgentRuntime` | Capability/eval/latency/cost/profit routing, fallback, budgets, redaction, trace/eval linkage and authority denial |

The four modules were implemented concurrently with disjoint write scopes,
then composed through `RuntimeServices`, Profit Command, Seller OS, growth and
Agent Control routers. All ZiAgents were closed after integration.

## Runtime truth snapshot

- Real Ozon Profit Command candidate count: 18.
- Store-profile proposal input: 36 retained listing/category observations from
  the 18 Product Info records.
- Store-profile gaps remain explicit for order, profit, traffic and exact
  variant evidence; no profile is auto-published or activated.
- Growth capability ports: VK and Telegram; optimization objective is
  `incremental_cash_cm3`.
- No model adapter is configured in the current container, so Agent Runtime
  correctly returns `no_data` rather than fabricating a model result.
- External write, fact promotion, self-approval and Permit creation remain
  disabled across all four slices.

## Authorization rotation correction

Runtime verification initially found HTTP 403 for ordinary users because the
2026-08-02 bundle retained its import-time Scope Grant hash while the user's
current same-store grant had rotated. The composition now uses:

- current exact tenant/entity/store authority to authorize the read;
- historical bundle authority to validate every retained source item and to
  preserve data lineage;
- separate `access_authority` fields to show whether rotation occurred.

The change does not relax tenant, entity or store isolation and does not mutate
the historical bundle.

## Verification snapshot

```text
ZiAgent module tests before integration: 51 passed
Integrated focused Python tests: 63 passed
Backend full regression: 1368 passed, 10 warnings
Ruff focused checks: passed
Git diff whitespace checks: passed
Web contract tests: 137 passed
Next.js production container build: passed, 61 routes generated
Profit repair page: /profit-command/remediation
```

The first full run used the shared Windows pytest temp root and reported 38
fixture setup errors after 1330 tests had passed because another process denied
directory enumeration. Re-running the unchanged suite with a new project-local
`--basetemp` produced the authoritative `1368 passed` result above.

Authenticated container probes returned HTTP 200 for all five projections:

```text
remediation: 374 total / 49 accepted / 325 quarantined / conserved=true
remediation queue: 776 total, server-paginated 50 rows per page
store profile proposal: 36 observations / 10 category roles / 2 explicit gaps
growth channels: vk + telegram / 9 funnel steps / incremental_cash_cm3
Agent runtime: no_data / 0 configured adapters
Profit workspace: 18 candidates / 18 needs_data / 0 Pilot / cash=no_data
```

Desktop and 390px browser acceptance is performed against a temporary legacy
auth container that uses the same built image and API but no production user
session. The normal Supabase Web correctly returns HTTP 401 without a login.

Browser acceptance results:

```text
desktop page 1: 50 rows, priority ranks 1-50, total 776
desktop next page: 50 rows, priority ranks 51-100
desktop document width: 1265 client / 1265 scroll
desktop document height: about 7,298px after pagination (about 100,442px before)
390px viewport: 375 client / 375 document scroll, no page-level horizontal overflow
390px table: 306px client / 870px scroll, overflow-x=auto
390px pager: column layout
final Compose: API, Web, PostgreSQL and media worker healthy
```

## Deliberate boundaries

- The growth capability endpoint is not a claim that official VK/Telegram
  credentials or production transports are configured.
- Growth events are not yet persisted through a public ingestion API in this
  slice; the deterministic ledger and adapter contracts are ready for that Gate.
- The governed runtime uses the existing OpenAI-compatible inference seam.
  Direct OpenAI Agents SDK binding remains a replaceable adapter task and is not
  allowed to become a business truth source.
- Real order, settlement, bank receipt and fifteen-cost Evidence are still
  required before Actual Cash Profit or a positive downside Pilot can exist.
