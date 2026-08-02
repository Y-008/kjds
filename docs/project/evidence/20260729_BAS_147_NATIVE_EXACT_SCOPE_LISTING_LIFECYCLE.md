# BAS-147 原生 exact-scope Listing 变更与刊登生命周期 Evidence

## 1. 工程结论

KJDS 已交付唯一深模块
`ScopedListingLifecycleWorkspace.project(...)`。它在同一
`tenant/entity/store/as_of` 下组合既有 `ScopedPimWorkspace`、
exact-scope frozen Listing Draft、Russian-native review Evidence、独立
Approval 以及 governed Execution Plan/Dry Run，以 Canonical Product +
offer 为中心输出可回放的 Listing 生命周期。

本切片为 `DONE_ENGINEERING`，不是刊登发布或经营闭环。当前真实 entity
authority、Product 与 Listing Draft 均未形成，运行态如实为 `no_data`；
Listing Draft 0、Russian-native Review Evidence 0、Order Facts 0、
Inventory Facts 0。没有为了测试或截图创建 Product、Draft、Review、
Approval、Execution Plan、Permit、平台任务或 Readback。

## 2. 权威分层与深模块边界

- Requirement / Decision：BR-121、ADR-0067。
- 状态严格分层：
  `observed platform Listing ≠ desired frozen draft ≠ independent approval ≠
  platform readback`。
- 字段 Diff 固定为服务端
  `same / changed / source_missing / desired_missing`；未知平台字段不会被
  页面或 Agent 当作相同。
- `project(...)` 组合现有权威，不建立第二套 Product、Listing、Approval、
  Permit 或平台状态真源。
- Router、Web 与 Agent 不重算 stage、Diff、counts、Owner/SLA/next、
  cursor 或 hash。
- Agent artifact 仅允许建议和内部任务；不得创建 Draft/Review/Approval/
  Execution Plan，不得 self-approve、发 Permit、发布、改价、改库存或外部写。

`ScopedPimWorkspace` 的 Listing 投影增加 `observed_fields` 与原始平台状态，
但仍沿用同一 Catalog authority。`SqlRepository.get_approval_at(...)` 依据
append-only `approval.decided` Outbox event 做 exact `as_of` 截断；决定发生前
返回 pending，缺事件不把当前状态伪装为历史状态。
`ExecutionPlanService.list_for_listing_drafts(...)` 只读取给定 Draft ID 且
不晚于 cutoff 的 plan/dry-run，不扫描或拼接无关执行对象。

## 3. 失败关闭与时间语义

- 缺失或无效 entity authority 时，PIM、Listing Draft、Approval 与
  Execution Plan 原始读取均为 0。
- PIM contract/scope/as_of/hash 漂移或投影截断时，在读取 Draft 前失败关闭。
- Draft 的 tenant/entity/store/grant、时间、Product snapshot、approval-plan
  hash、Evidence set 或平台不一致时，隐藏 observed/desired payload。
- 所有 Draft Evidence 必须 current 且具备 exact-scope binding。
- Russian-native review 必须为 grade A、由不同 Reviewer 完成、精确绑定
  Listing snapshot，并完整通过五项检查；最新坏记录不能回退旧 accepted。
- Approval 与 Execution Plan 均按 cutoff 读取并重验目标、snapshot、独立性
  与 Evidence；future/scope/hash/product/approval drift 均失败关闭。
- stable filter、opaque cursor、全结果 counts、item/snapshot/artifact hash
  由服务端生成，可确定性重放。

## 4. API、Web 与工程门

- API：`GET /v1/listing-lifecycle/workspace`。
- Web：`/listings`；可从 `/commerce-os` 和 `/pim` 下钻。
- Web 覆盖 loading、ready、partial、blocked、真实 no_data、error、retry、
  list/detail、server cursor 与 390px。
- 聚焦 deep module/PIM/Approval temporal/Execution Plan/API/OpenAPI：
  `61 passed`。
- 全量后端：`876 passed`，9 个已知依赖弃用 warning。
- Secret scan：860 个非忽略工作树文件与 581 个历史路径通过。
- `uv run ruff check .`：通过。
- Web `npm ci`：0 vulnerabilities。
- Web `npm test`：`79 passed`。
- Web `npm run build`：成功，43 个 route 含 `/listings`。
- OpenAPI 0.59.0 包含 `/v1/listing-lifecycle/workspace`。
- `git diff --check`：退出 0，仅有工作树既有 LF/CRLF 提示。

## 5. PostgreSQL、Alembic 与真实运行

- 本切片是纯读组合与现有 append-only event 的 temporal 投影，没有 schema
  变化，因此没有强造 `0075`、也没有修改已应用的 `0074`。
- PostgreSQL current/head 均为唯一 `20260729_0074`；四容器均以最终源码重建
  且 healthy。
- 接口匿名 401；认证 exact store 200；越权 store 403。
- 固定 `as_of=2026-07-29T00:00:00Z` 连续投影产生相同
  `snapshot_sha256`：
  `a13d77ff74116fac2f44c193f1ebb8f3c3847460abeb3333d951f4674faf05ff`。
- 同一输入 Agent artifact hash：
  `ff84dc3232174d7b49ed2506ee1b86fb3eb732b19f3f0442b7c56263522ee967`。
- 当前响应：`status=no_data`、`entity_ref=null`、全部 counts 为 0、
  `scoped_input_read=false`、Draft/Review/Approval/Plan/Permit/平台任务/
  Readback created 均为 false、`publish_allowed=false`、
  `external_write_allowed=false`。
- PostgreSQL 实际计数：Listing Draft 0、Russian-native Review Evidence 0、
  native Order Facts 0、native Inventory Facts 0。

## 6. 浏览器实测

真实 Supabase operator session、运行容器和 PostgreSQL：

| Artifact | SHA-256 | 结果 |
|---|---|---|
| `output/playwright/bas147-listing-lifecycle-desktop.png` | `8935444d2998a6f00823c15b869530d504cef5861d42c6ce1b6476e8dcc59c59` | 1440px full-page，inner/client/scrollWidth = 1440/1440/1440 |
| `output/playwright/bas147-listing-lifecycle-mobile-390.png` | `3d30121e2fdf12b02daa0fd6cb269e912c60e7492c578fc33ad5a769b47ea631` | 390px full-page，inner/client/scrollWidth = 390/390/390 |

桌面与 390px 均显示真实 `no_data`、五项 0 counts、六阶段权威链与全部
no-write 边界，Console Error 与 Page Error 均为 0。`/commerce-os` 的
“打开 Listing 生命周期”真实导航到 `/listings`，`/pim` 同样存在直接下钻。

## 7. Graph 与仍未关闭 Gate

- `task-bas147-pytest/database/runtime/web/evidence` 由独立 verifier 记录为
  `passed/fresh`；canonical Graph 为 66 tasks、169 nodes、174 edges、
  至少 308 条 append-only observations。
- Graph passed 只证明工程合同、temporal authority、PostgreSQL、运行、
  浏览器与 Evidence，不会把 `no_data` 晋升为 Listing 覆盖或发布完成。
- 真实 entity、三个 SKU、Product/Passport、Listing Draft、Russian-native
  review、独立 Approval、一次性 Permit、Ozon publish/readback、Order、
  Settlement 与 Cash 仍未形成。
- 0.59 PM/RA Release Gates、Pilot Gate 与 Final Gate 均未通过。
- Ozon、Seller ERP、供应商、采购、付款、库存、履约、广告和客户消息 external
  write 继续关闭。
