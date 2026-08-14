# BAS-141 Native scoped OMS 当前态与时间线 Evidence

## 1. 结论

KJDS AI ERP 已新增一个原生、只读、作用域绑定的 OMS 工作台。唯一
`ScopedOmsWorkspace` 只从 exact tenant/entity/store/grant 下已经正式晋升的
`ozon_order` 与 `ozon_return` Fact 建立当前订单与不可变时间线；legacy
`orders`、页面观察、同行数据和模型推断均不进入当前态。

本切片为 `DONE_ENGINEERING`，不是经营闭环完成。真实 PostgreSQL 当前
Order/Return Fact 为 `0`，授权运行结果真实显示 `no_data` 和
`entity_scope_authority_missing`。没有供应商下单、付款、客户消息、Approval、
Permit 或任何 Ozon 外部写。

## 2. 深模块与共享事实 seam

- 需求：`BR-115`
- ADR：`docs/adr/ADR-0061-native-scoped-oms-timeline.md`
- 服务端深模块：`apps/control_plane/scoped_oms.py`
- 订单 Fact 公共语义：
  `apps/control_plane/order_fact_semantics.py`
- API：认证 `GET /v1/oms/workspace`
- Web：`/oms`
- 上游权威：`FactRecordRow`、exact-scope `ProductRow`、immutable
  `EvidenceRecord/Blob` 与当前 `ScopeGrant`。
- Agent 权限：`decision_support_only`；输入绑定快照 hash，只能返回内部
  Owner/SLA/next-workspace 建议，不得自批、自发 Permit 或执行。

`SaleTriggeredProcurementPolicy` 与 OMS 共用同一订单时间、正数、正整数与显式
币种语义模块，避免采购与订单工作台各自解释同一 Ozon Fact。

## 3. 当前态、坏 Evidence 与分页合同

- cutoff 同时约束 `scope_as_of/effective_at/recorded_at`。
- Order 通过 external order identity 聚合；Return 只能通过显式
  `order_external_id` 关联。
- Product、SKU、store、合同版本、payload hash、Evidence bytes 与
  source Evidence hash 必须一致。
- 订单金额使用 Decimal 字符串并要求显式三位大写币种；数量必须为正整数。
- unknown 平台状态保持 `unknown/partial`，不会猜成已发货、签收、取消或退货。
- 若同一订单最新候选 Fact 的合同/hash/Evidence 失败，该订单当前态成为
  `blocked/unknown`；上一条有效状态只保留在历史时间线，绝不复用为 current。
- 分页游标为完整服务端排序键
  `(current_event.effective_at, external_order_id)` 的 opaque cursor；同时间订单
  不跳过、不重复，客户端不重排。

## 4. 服务端与安全测试

聚焦回归：

- `tests/test_sale_triggered_procurement.py`
- `tests/test_scoped_oms.py`
- `tests/test_api_contract.py`
- `tests/test_security.py`

结果：`69 passed`。覆盖 missing entity、legacy exclusion、latest-state、
return link、跨租户、确定性 as-of、未来 Fact、坏 Evidence、未知状态、坏最新
Fact 不复用旧状态、同时间 opaque cursor、输入校验、匿名 401、越权 403、
OpenAPI 与 endpoint role。

全门禁：

- `uv run python scripts/verify_secrets.py`：
  `805` 个非忽略工作树文件、`581` 个历史路径通过。
- `uv run ruff check .`：通过。
- 全量后端：`825 passed`，`9` 个已知依赖弃用 warning。
- `git diff --check`：通过；只有现有 CRLF 提示，无 whitespace error。
- Web `npm ci`：`0 vulnerabilities`。
- Web `npm test`：`68 passed`。
- Web `npm run build`：`37` 路由生产构建通过，包含 `/oms`。
- OpenAPI 快照与运行合同一致，包含 `/v1/oms/workspace`。

## 5. 真实运行验收

重建并切换 API/Web/media-worker 镜像后：

- PostgreSQL、API、Web、media-worker 四容器均 `healthy`。
- Alembic current/head：单一 `20260729_0072`；本切片无新迁移。
- `/health/ready`：HTTP `200`、database `ok`、version `0.59.0`。
- 匿名 OMS：HTTP `401`。
- 认证 exact store：HTTP `200`、`status=no_data`、
  `entity_ref=null`、current orders `0`、legacy orders read `0`、
  external write `false`。
- 越权 store：HTTP `403`。
- 正式 Ozon Order/Return Fact：`0`。
- OMS GET 前后 `operating_tasks=2`，证明读取未创建任务。
- 运行 OpenAPI 包含 `/v1/oms/workspace`。

运行镜像构建耗时约 272 秒，主要时间用于重新下载 Python 镜像依赖；构建成功后
才替换容器，旧健康容器未被失败构建提前覆盖。

## 6. Web 与 390px 浏览器验收

真实 Supabase operator 会话在运行 Web/API/PostgreSQL 上打开 `/oms`。页面直接
显示服务端的 `no_data`、source gap、scope、计数和 Agent 权限；没有 demo 订单
或客户端 current-state 计算。

| Artifact | SHA-256 | 结果 |
|---|---|---|
| `output/playwright/release-0.59.0/native-oms-desktop.png` | `1eafede55ea7ff7bd70ebc7735eb2b7ca67f400b8f6eb27c3c4712bc33007a68` | `innerWidth=clientWidth=scrollWidth=1440` |
| `output/playwright/release-0.59.0/native-oms-mobile-390.png` | `17e2dc88d4e4eac186edcb8608debb52c113b4a90ff7c22431daf1003fde79c2` | `innerWidth=clientWidth=scrollWidth=390`，主要内容边界 `11..379` |

移动端首次截图命令前会话异步跳回登录页，该错误图片未作为证据；重新认证后在同一
Playwright 原子测量/截图动作中确认 URL `/oms`、390px media query、无横向溢出
并覆盖原文件。最终 OMS 页面浏览器控制台为 `0 errors`。

## 7. Graph/Harness 外部观测

`scripts/seed_bas141_agent_graph.py` 不接受模型自报，重新执行聚焦 pytest、
PostgreSQL/容器/API 探针并复验两张截图 hash，随后把 BR-115→ADR-0061→共享
订单语义→OMS 服务→测试→运行 API→Web→本 Evidence→BAS-141 计划写入现有
Project/Engineering/Runtime/Evidence Graph。

最终 canonical project `kjds-059-bas123`：

- tasks `40`
- nodes `130`
- edges `141`
- append-only observations `>=268`；每次复验只追加、不覆盖
- BAS-141 四项 verifier task 均 `passed/fresh`
- business state `no_data`
- external write `false`

Graph 仍可因为其他历史/运行节点显示 stale 或 blocked；BAS-141 不覆盖、伪造或
口头抹除其他任务状态。

## 8. 明确未关闭的 Gate

- 真实 Ozon Order/Return Fact：`0`。
- 当前 entity grant：缺失；OMS 真实状态为 `no_data`。
- 真实供应商采购、付款、履约、退货、结算和 actual cash CM3：未发生。
- 0.59 PM/RA Release Gates：继续 `REJECTED`。
- Pilot/Final Gates：未通过。
- Pricing：`not_for_sale`。
- Ozon、供应商、采购、付款、客户消息和广告 external write：全部关闭。

因此本 Evidence 证明的是原生 AI ERP 的 OMS 事实投影、失败关闭、Agent 边界和
可见工作台，不证明已经出单、采购、上架或盈利。
