# LG-002 90 天 Top1 大型团队总控工程 Evidence

| 字段 | 值 |
|---|---|
| task | LG-002 |
| baseline | 2026-08-07 → 2026-11-04 |
| engineering status | DONE_ENGINEERING |
| operating status | HUMAN_CASH_SKU_CUSTOMER_TOP1_EVIDENCE_PENDING |
| scope | Team Control projection and internal OperatingTask/Event coordination only |
| schema change | none |

## 1. 交付物与哈希

| 交付物 | SHA-256 |
|---|---|
| `docs/project/registries/team_control_tower_registry.json` | `358c7e9f625ee51e029feb6b1d8aa2e7fd14ec93b20ec4255b177ad5fc62fedc` |
| `apps/control_plane/team_control_tower.py` | `294212c92c76c994c6838b7dad51e2a476057ec6f71114cb510dcadbbcca8154` |
| `web/features/team-control-tower/team-control-tower.tsx` | `243918a46f18f132eae059a70dedb095aa2199a2160d72e4ed98834d1d61e0b5` |

注册表 v1.1 冻结 18 个唯一核心角色、现有 12 个 AI 专家席位、20–40 人专家池容量、
5 个独立控制角色、四阶段 90 天 Campaign、A–E/I/L/M 主战泳道、F–H 准备态泳道、
12 个既有 Benchmark selector、13 周现金输入合同、五个 Delivery Gate 和完整
build/buy/partner/defer/no_action 比较。任命 Evidence 合同当前为 `UNKNOWN`，已验证绑定为空。

## 2. Interface 与权威边界

- 外部 Interface 仍只有 `brief/advance`，没有 Campaign CRUD、第二任务系统或第二组织账。
- exact-scope 校验在 OperatingTask、Evidence、StrategicBenchmark 和任何财务投影之前；
  scope 不可用时零业务读取、零 continuation，五类投影均 `UNKNOWN`。
- `brief` 新增 `organization_readiness`、`critical_path`、`top1_scorecard`、`cash_at_risk`、
  `delivery_gate`，统一带 truth state、reason code、source ref、as-of 和 SHA-256。
- StrategicBenchmark 依赖注入只读并遍历权威分页；只选择最新唯一同 scope snapshot 与精确
  selector group，不重排 leader。至少五个 eligible peer 且既有 leader refs 包含 KJDS current
  observation 才显示 `METRIC_LEADER`；`global_top1_claim=false` 固定。
- opening bank balance、CashPlan、FX、signed cash floor 或 maximum loss 缺失时不调用现金
  预测；零不被当作缺失值替代，财务 withheld projection 不变造金额。
- 日历、泳道或 OperatingTask 状态不能产生 Gate PASS。当前五个 Gate 均无正式 PASS。
- 五类投影、scope、四条 flow、A–M 泳道和冲突共同进入 `decision_basis_sha256`；变化使旧
  continuation 失效。`advance` 仍只写 OperatingTask/Event，Receipt 不创建 Fact、
  FinanceEntry、Approval、Permit 或 provider write。

## 3. 老板工作台与 Coding Agent 流程

`/team-control` 已形成五层信息：组织/现金/阶段/Top1 差距/Gate 首屏、唯一下一动作、90 天
关键路径、12 维评分卡、组织缺口/专家池/四条业务主线。`UNKNOWN/STALE/BLOCKED/CONFLICTED`
显式显示，客户端不计算排名、现金或 Gate。推进请求在网络结果未知时冻结完整请求和幂等键，
成功或 continuation 变化后才生成新键；输入具有语义 label，390px 栅格无横向溢出。

`AGENTS.md` 新增复杂任务八步工程流：项目认知、任务分级、文档先行、双设计比较、增量实现、
持续验证、独立审查、文档/代码共同演进。新增外部权限、真实付款/合同/平台写、真人任命或
重大范围变化才请求决定。

## 4. 负向控制

- 18/12/20–40/5 数量、唯一性、必填字段、Reviewer/控制角色引用和 30/60/90 结果失败关闭；
- `verified_active` 缺主责、不同替补、任命/专业 Evidence、冲突证明、预算和最大损失失败；
- 未知 Benchmark selector、重复阶段、未知泳道、重复最新 group/snapshot、多个 KJDS current、
  不足五个 peer、stale、invalidated 与 authority drift 均不能生成 Top1 成功；
- 无 exact scope 不读 OperatingTask 或 Benchmark；无真人 Evidence 不显示“已组建”；
- 无现金权威不预测；无 kickoff 不计算实际战役日；缺正式 Gate Evidence 不显示 PASS；
- Benchmark、人员、现金、Gate 或泳道投影变化使旧 continuation 失效；
- done/stop 缺 Evidence、跨 scope、职责越权、同幂等键内容漂移和 Kill Switch 继续失败关闭。

## 5. 验证结果

| 验证 | 结果 |
|---|---|
| Team Control 定向（含 API、注册表与 Benchmark shape 负向） | `24 passed` |
| StrategicBenchmark / strategic contracts | `68 passed, 1 warning` |
| Team Control + Global Expert + Operating Scope/Task 分组 | `46 passed` |
| OpenAPI runtime snapshot 精确比较 | `1 passed, 1 warning` |
| Web 契约测试 | `146 passed` |
| Next.js 生产构建 | PASS；63 routes，包含 `/team-control` |
| `uv run ruff check .` | PASS |
| secret scan | PASS；1398 non-ignored worktree files、1376 historical paths |
| `git diff --check` | PASS；只有既有 LF→CRLF 提示 |
| Alembic heads | 唯一 head `20260804_0095`；LG-002 无 migration |
| PostgreSQL regression | NOT RUN；本机 Docker Engine 未运行，本切片也无 schema 变更 |
| 非 PostgreSQL 全量回归 | UNKNOWN；15 分钟工具上限终止，未返回失败或完成摘要，不能记录 PASS |
| `tests/test_api_contract.py` 全文件 | UNKNOWN；5 分钟工具上限终止；其中 OpenAPI 精确快照已单独 PASS |

全量和 API 文件超时没有被伪装成通过；本切片相关的最小权威、Benchmark、Operating/API 与
Web 分组均取得可归因 PASS。PostgreSQL 生产回放仍须在 Docker/PostgreSQL 可用环境执行。

## 6. 工程完成不证明的事项

以下全部保持 `UNKNOWN/BLOCKED_EVIDENCE`：18 个真人主责与替补、持证专业资质、20–40 人
专家池名册、13 周现金/现金底线/最大损失、一个 SKU 的订单→结算→银行→Actual Cash CM3、
C0 与真实设计伙伴/SOW/DPA/SLA、RPO 24h、RTO 4h、p95 <2s、99.9% 生产观测，以及任何
Top1 市场宣传结论。Owner 的唯一下一业务动作仍是补齐实名组织、现金与真实 SKU/C0 Evidence，
再由既有 Gate 决定继续、缩小、转向或停止。
