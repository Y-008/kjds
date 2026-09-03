# ADR-0105：KJDS UI 2.0 经营可视化层

- 状态：accepted for scoped implementation
- 日期：2026-08-19
- Owner：web_platform / operating_product
- 关联需求：BR-067、BR-074、BR-088
- frontier_review：not_required（复用已登记的 Next.js/React 基线，不新增运行时依赖）

## 背景

KJDS 已有 `OperatingAnalyticsSnapshot`、`OperatingWorkbenchBriefing`、`profit-command` 和
`operating-intelligence`。问题不是缺少图表，而是 KPI、阶段、覆盖和异常在不同页面中缺少统一的
口径、时点、freshness、状态和 Evidence 表达。BR-074 要求缺历史时显示 `no_data/blocked`，禁止演示数、插值或静态图冒充经营事实。

## 选项

1. 继续在各业务页面局部增加图表：改动小，但会继续产生不同的空态、状态和证据表达，无法形成可迁移的 BI/大屏语言。
2. 引入独立 BI 数据仓库或分析引擎：可提供更多历史分析能力，但会违反当前 PostgreSQL/Evidence 单一经营真源边界并增加同步、权限和恢复成本。
3. 建立 namespaced UI token 与共享数据表达组件，包装现有只读服务端快照，先做 BI Overview + Wallboard 试点：可回滚、无需新事实库，能直接验证数据可读性。

## 决策

采用选项 3。UI 2.0 仅提供展示与交互层：

- `tokens.css` 使用 primitive → semantic 两层 token；组件 API 保持状态、口径、时点和证据为显式字段。
- `AppShell`、`ScopeBar`、`MetricCard`、`ChartFrame`、`DataTable`、`EvidenceDrawer`、`WallboardFrame` 和 `BriefingFrame` 位于 `web/features/ui2`。
- `/bi/overview` 与 `/bi/wallboard` 只消费 `/backend/v1/operating-analytics/snapshot` 和 `/backend/v1/operating-workbench/briefing`，不修改 API、利润口径、Gate 或事实库。
- 没有历史序列时 `change_abs`、`change_pct`、`target_gap` 及趋势保持 `no_data`；浏览器不推导经营利润或放行规则。
- 大屏为 16:9、只读、异常置顶、可暂停轮播；所有业务动作仍回到既有审批与执行链。

### UI 2.1：可信作用域与简报闭环

试点在进入多店铺和历史时点之前，必须先完成以下失败关闭约束：

- 浏览器先读取 `/auth/session`，只允许使用 `store_refs` 中的店铺；URL 中未授权的
  `store_ref` 显示 `forbidden`，且不得发送经营快照请求。缺省店铺只来自
  `default_store_ref`，不再硬编码 `ozon-primary`。
- `/operating-analytics/snapshot` 与 `/operating-workbench/briefing` 必须使用同一份
  `store_ref/as_of` 查询；切换作用域或刷新时立即清空旧投影并终止旧请求。响应中的
  tenant/store scope 与当前会话不一致时显示 `conflicted`，不得渲染数字。
- Web 运行时合同必须接受 scoped 投影的 `ready/partial/blocked/no_data`、`scope`、
  `source_gaps` 和 `excluded_sources`。服务端用零表示“该作用域尚无权威来源”时，页面按
  `no_data` 呈现，禁止把占位零标成 `READY`。
- Evidence 抽屉只允许钻取当前 scoped 投影已经返回的 Evidence ID，按需读取 metadata、
  integrity verification 与直接 lineage；不自动读取 Blob、不提供任意 Evidence ID 搜索，
  也不把 snapshot hash 或阶段 source ID 冒充原始 Evidence。
- `/bi/briefing` 使用同一作用域投影生成手动翻页的确定性简报，不自动翻页、不生成 AI
  补全结论、不获得导出文件写入或外部平台权限。
- Command menu、Evidence/Detail drawer 使用现有 Radix Dialog 基线，必须具备焦点约束、
  Escape 关闭、背景不可交互、关闭后焦点恢复；表格、skip link、颜色对比、触控目标和
  reduced-motion 按 WCAG 2.2 AA 验收。

## 验收与回滚

- `npm test`、`npm run build` 和 `git diff --check` 通过；页面在桌面与 390px 下可键盘操作，存在 skip link、语义表头、图表数据表切换和 reduced-motion 规则。
- 任一快照接口失败时，页面显示 `partial/error/no_data`，不生成替代数据。
- 未授权 URL 店铺的经营接口请求数必须为 0；快速切换店铺、响应 scope 漂移或刷新失败时，
  旧数据不得继续以当前店铺或 `READY` 展示。
- scoped `no_data/blocked` 中的摘要零值不得冒充经营事实；Evidence 完整性失败显示
  `conflicted`。
- 回滚只需移除 `/bi/*` 路由、`web/features/ui2` 和 DashboardShell 的 BI 入口；不涉及数据库迁移、业务 API 或外部系统。

## 未解决边界

当前 OperatingAnalytics 合同不提供历史时间序列与每个摘要 KPI 的独立 Evidence ID，因此试点会明确显示
`no_data` 或快照级 SHA-256。真正的同比、趋势、归因和可导出明细需先由服务端扩展版本化合同并完成作用域、权限和证据验收。

通用 Evidence GET 路由尚未成为任意 ID 搜索的 exact-scope 权威。本 ADR 只授权从当前 scoped
投影返回的 ID 进行单层钻取；未来开放全局搜索或递归血缘前，必须先补齐后端 Evidence 双端
scope guard 与独立安全验收。
