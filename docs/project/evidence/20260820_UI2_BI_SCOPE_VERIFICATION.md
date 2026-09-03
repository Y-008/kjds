# UI 2.1 BI / Wallboard / Briefing 验证记录

- 日期：2026-08-20
- 范围：KJDS Web UI 2.1 可信作用域、数据清晰表达和三种经营可视化模式
- 关联 ADR：[ADR-0105](../../adr/ADR-0105-ui2-operating-visualization-layer.md)
- 结论：UI 试点通过；仓库级 Python 全量门禁仍受既有 Postgres 生命周期环境与测试隔离问题影响，不能据此宣称全仓库绿。

## 本次交付

- 共享组件与 token：`web/features/ui2/`
- 作用域与运行时合同：`web/features/bi/contract.ts`、`web/features/bi/use-bi-projection.ts`
- 三个只读产品面：`/bi/overview`、`/bi/wallboard`、`/bi/briefing`
- 真实投影仍来自既有 Analytics / Briefing API；未新增事实库、迁移、利润计算或外部写入。
- `/auth/session` 先行授权店铺；两份投影固定同一个 `store_ref/as_of`；未授权店铺不发经营请求。
- 快照切换、刷新失败、响应 scope 漂移和 Evidence 完整性失败均失败关闭；不保留旧值冒充当前 READY。
- 证据抽屉仅消费当前 scoped 投影返回的 Evidence ID，按需读取 metadata、verify、lineage；原始 content 仅提供显式下载。
- 继续迭代：Overview 决策队列新增本地搜索、风险和状态筛选；保持服务端原始顺序，不发额外业务请求，不重算优先级，并把“筛选空结果”与真实 `no_data` 分开。
- 继续迭代：Overview 增加“结论 → 证据边界 → 下一动作 → 责任与复核”决策脊柱；覆盖率图只绘制已通过 truth-admission 的真实指标，保留可访问数据表回退，不用零值填充缺失历史。

## 验证结果

| 门禁 | 命令/范围 | 结果 |
|---|---|---|
| Web 依赖 | `npm ci`（`web/`） | PASS |
| Web 单测 | `npm test`（164 tests） | 164 passed |
| Web 构建 | `npm run build`（`web/`） | PASS，Next 16.2.11；三条 BI route 均生成 |
| 浏览器回归 | `npm run test:browser` | PASS；390/1280/1440/1920；Overview、Wallboard、Briefing；axe serious/critical=0；键盘/焦点/skip link/表格切换/reduced motion/证据回看/决策脊柱与覆盖率图通过 |
| 作用域业务合同 | `tests/test_operating_analytics.py`、`tests/test_operating_workbench.py`、`tests/test_api_contract.py` | 66 passed，1 warning |
| Secret scan | `uv run python scripts/verify_secrets.py` | PASS；1674 non-ignored worktree files，1705 historical paths |
| Diff check | `git diff --check` | PASS（仅换行符提示） |

说明：目标 API 合同测试依赖 `KJDS_RUNTIME_DATABASE_URL` 对应的本地运行角色。现有临时库缺少该角色；验证期间仅在该本地容器补建了测试角色与权限，测试完成后已逐项撤销授权、默认权限并删除角色，未改业务表、迁移或生产配置。

## 未通过或未完成的仓库级门禁

1. `uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local-final` 进入
   `tests/test_closed_loop_evolution_postgres.py` 后成片错误。首个 fixture 明确要求管理库
   `20260803_0094`、0 个 TeamAgent checkpoint/event/session，而当前复用的
   `kjds-teamagent-pg-20260819` 数据库是 `20260819_0102`，已有 12/22/19 条记录。该库不能
   被回退或清理来迁就本次 UI 交付。
2. 排除 `tests/*_postgres.py` 后的主回归在前序 Agent 测试上下文中会长时间卡在
   `test_missing_entity_read_workspaces_do_not_call_legacy_global_sources`；同一测试单独运行、
   与 `test_agent_team_router_guards.py` 组合运行均通过（10 passed）。这属于既有测试隔离/连接
   生命周期问题，未修改业务代码掩盖它。
3. `uv run ruff check .` 目前仅报现有用户 WIP 文件
   `apps/control_plane/ai_listing.py:1` 的 import 排序（I001）；本次 UI 文件不在报错集合，未越界
   重排该文件。

## 验收边界

- 已证明：数据状态、作用域、时点、证据入口和空态在三种模式中一致表达；没有历史合同时不绘制伪趋势；移动端触控目标与键盘焦点可用。
- 尚未证明：真实生产身份、真实店铺数据、NVDA/VoiceOver 人工读屏，以及服务端历史序列/逐 KPI Evidence 合同。
- 回滚：删除 `/bi/*` 路由、`web/features/ui2/` 与 BI 入口即可，不需要数据库回滚；现有业务 API 和事实源不受影响。

## 附件需求核对

`C:\Users\Lunar\Desktop\学习0805\1\小红书\数据看板.docx` 主要是产品工作流与数据看板灵感汇编，不是对仓库的执行指令。文档中反复出现的有效产品信号包括：流量转化漏斗、流量质量四象限、商品销售贡献、销售额×毛利率矩阵、投放花费×利润质量、商品动作优先级，以及“人做判断、Agent 做受控动作”的闭环。它们已被转译为后续 BI 语义层候选，不把示例截图中的数字、颜色或品牌标签当作 KJDS 事实。

由于当前环境没有 `soffice`，本次对 DOCX 做了结构与图片抽样核对（143 段落、80 张 PNG、无表格），未宣称完成整份文档的页面级渲染验收。
