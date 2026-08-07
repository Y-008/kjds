# LG-003 权威驱动的 Campaign 管控调度工程 Evidence

| 字段 | 值 |
|---|---|
| task_id | LG-003 |
| requirement | BR-143 |
| baseline | 2026-08-07 |
| engineering_state | DONE_ENGINEERING |
| operating_state | BLOCKED_EVIDENCE |
| migration | LG-003/follow-up 无 migration；合流后的仓库代码迁移 head 为 BAS-204 独占的 `20260805_0096_governed_closed_loop_evolution`；本 follow-up 未运行 DB/G1 |

## 1. 本切片证明的结果

- `TeamControlTower` 外部仍只有 `brief/advance`；没有 Campaign CRUD、第二任务账、Fact、
  FinanceEntry、Approval、Permit 或外部写 Interface。
- 四阶段 Campaign 按需编译为既有 exact-scope OperatingTask/Event。首阶段只有带当前
  exact-scope Evidence 的 `start` Event 才形成 kickoff 并开始计算实际战役日。
- 阶段 `resolve` 只形成 Evidence-backed handoff，所有正式 Gate 继续
  `formal_gate_pass=false`；无 canonical Gate PASS 时不会自动打开下一阶段。
- 运行时只读注入现有 `ScopedSettlementCashWorkspace`。只有同一 cycle 同时具备订单 Fact、
  平台结算、银行现金、`reconciled`、Actual Cash CM3 available、当前 exact-scope Evidence
  且无 blocker 时，“至少一个真实 SKU 现金闭环”才为 `VERIFIED`。
- 老板摘要只投影闭环状态、计数和语义哈希，不投影订单号、结算号、银行标识或金额；该
  闭环不会补造 13 周现金、现金底线、最大损失或正式俄罗斯经营 Gate。
- 完整审计投影哈希保留 `as_of`；continuation 使用去除 cutoff 噪声、保留任务/Event、现金、
  Benchmark 与 Gate 业务语义的稳定决定哈希。单纯时钟变化不使动作过期，权威内容变化会。
- exact scope 失败时 Router 仍调用一次 `TeamControlTower.brief` 生成稳定的
  `scope_invalid` 投影；Tower 在 OperatingTask、StrategicBenchmark 与 Settlement Cash 等
  经营适配器读取前短路，经营数据读取为零且不返回 continuation。“零读取”不表示 Tower
  Interface 零调用。
- 客户端 `as_of` 只控制数据投影截止时间；ScopeGrant 权威每次均按可信 UTC 当前时间读取。
  revoke 或 rotation 后传入旧历史时间不能恢复旧 authority。

## 2. 负向控制

| 控制 | 结果 |
|---|---|
| 无 kickoff Evidence 启动阶段 | 失败关闭 |
| 日期到期、任务完成或泳道状态产生 Gate PASS | 禁止 |
| 完成阶段后自动打开下一阶段 | 禁止；焦点返回现有冻结 flow |
| Settlement Cash contract/scope/hash/envelope/count 漂移 | 失败关闭或 `CONFLICTED` |
| 不同 cycle 的订单、结算、现金计数拼成一个闭环 | 禁止；逐 cycle 验证 |
| 原始现金金额/订单标识进入总控摘要 | 禁止 |
| 观测时间变化导致 continuation 永久 stale | 已修复并有回归测试 |
| 现金或 Benchmark 权威变化继续使用旧 continuation | 失败关闭 |
| scope-invalid 投影被描述为 Tower 零调用 | 禁止；Tower `brief` 调用一次，经营适配器读取零次 |
| revoke/rotation 后用历史 `as_of` 回绕旧 authority | 禁止；当前权威拒绝旧绑定且经营适配器读取零次 |
| 注册表允许任务/日历替代 Gate、现金闭环替代 13 周预测 | schema 校验失败 |

## 3. 当前源码哈希

| 文件 | SHA-256 |
|---|---|
| `apps/control_plane/team_control_tower.py` | `e45e361319ab46a62f620b1665cf7e68e81c86f8601414755737c88f4759bd52` |
| `docs/project/registries/team_control_tower_registry.json` | `707e8d766883df9bc2a4dd0d17da93be6dc0be78a6bee08a04f9aef01b5b2bc6` |
| `apps/control_plane/runtime.py` | `e1271905f330e2d64de2a26ad0da41a172a8587d614d49f8b001c92493782804` |
| `web/features/team-control-tower/team-control-tower.tsx` | `41b1e62f9d0a1d438941d44da0e1249c1458168cd8074ecd79496b760ed24abb` |
| `web/features/team-control-tower/contracts.ts` | `a73e86390dc4e96b4a6e652ca50e575c4ffbc346f7569bc8b09692cec77fe678` |
| `tests/test_team_control_tower.py` | `c97e5dc1f4edfed958d7a6eeed514288374ec016f8cf0690800a60ea639637b8` |
| `apps/control_plane/routers/system.py` | `7db494b2fc1da05356ceba644284b96bfd48ddde0cf4aa720814a7cbe514b8ee` |
| `tests/test_team_control_tower_api.py` | `942de31eb1b7f487bcb5dc7bcb962dd54be0714fb1f5e21f757712488e67b2fb` |

## 4. 验证记录

| 验证 | 结果 |
|---|---|
| 权威时间/revoke/rotation follow-up | API 负向 `4 passed`；六文件 focused `60 passed`；py_compile 与 Ruff 通过 |
| Team Control + API 定向 | 33 passed |
| Global Expert、Operating Intelligence、Settlement Cash、StrategicBenchmark 相邻回归 | 84 passed；1 个既有 Starlette deprecation warning |
| StrategicBenchmark PostgreSQL 17 回归 | 20 passed；12 个既有 SQLAlchemy `Column.copy()` deprecation warnings |
| Team Control OpenAPI 只含 `brief/advance` | passed |
| 完整 API contract | 49 passed；包含 OpenAPI v1 snapshot 精确匹配 |
| 全量非 PostgreSQL 回归 | 2443 passed，1 skipped，37 个既有 deprecation warnings |
| Web contract tests | 146 passed |
| Next.js production build | 63 routes generated；`/team-control` included |
| Ruff | all checks passed |
| Secret scan | 1398 non-ignored worktree files + 1376 historical paths passed |
| `git diff --check` / cached check | passed；仅现有 LF→CRLF 提示 |
| Migration/DB | 仓库代码迁移 head 已合流为 `20260805_0096_governed_closed_loop_evolution`；LG-003/follow-up 无 migration，且本 follow-up 未运行 Alembic、DB 或 G1 |

最初回归从本机 `.env` 继承了已失联的 PostgreSQL runtime 端口 `55432`，导致一个 Commerce OS
读取在连接超时后失败；切换到项目 Docker PostgreSQL `5432` 的独立 runtime principal 后，
该精确用例、完整 49 个 API contract 和全量非 PostgreSQL 套件全部通过。第一次全量运行还
暴露 `uv` 默认缓存不可写；按 G-1 既有合同把 `UV_CACHE_DIR` 定向到工作区 `.runtime` 后，
失败用例和完整套件均通过。上述均为测试环境修正，没有修改生产数据库配置。

## 5. 未被工程证明的经营事项

- 18 个核心真人主责/替补、五个独立控制真人及专业资质仍未绑定；
- 没有在真实租户上执行 Campaign kickoff；实际战役日仍应为 `UNKNOWN`；
- 当前仓库没有五个交付 Gate 的匹配 exact-scope canonical PASS authority；
- 13 周 opening balance、CashPlan、批准 FX、现金底线和最大损失仍未到达；
- 未证明任何真实 SKU 已完成订单—结算—银行—Actual Cash CM3；
- 未证明 C0、SOW/DPA/SLA、真实设计伙伴、生产 RPO/RTO/p95/99.9% 或任何 Top1 宣传结论。

上述事项继续保持 `UNKNOWN/BLOCKED_EVIDENCE`，不得因本工程 Evidence 升级为经营完成。
