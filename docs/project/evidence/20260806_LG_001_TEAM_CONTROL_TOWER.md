# LG-001 Exact-scope 团队总控塔工程 Evidence

| 字段 | 值 |
|---|---|
| task | LG-001 |
| date | 2026-08-06 |
| status | DONE_ENGINEERING |
| business status | HUMAN_BINDING_AND_REAL_OUTCOMES_PENDING |
| scope | Team control coordination only; no external write |

## 1. 交付结果

- 版本化 `team_control_tower_registry.json` 冻结用户指定四条主线、优先级、老板五问、WIP、
  升级链和零外写边界。
- 深模块 `TeamControlTower` 对外只有 `brief/advance`；任何 OperatingTask 读取前先复验
  authenticated exact tenant/entity/store/authority hash。
- `brief` 组合权威 A–L 泳道、既有 OperatingTask/Event 和全球专家路由，输出恰好一个
  状态绑定 continuation；注册表或泳道变化会使旧 continuation 失效。
- `advance` 只接受 take/done/blocked/escalate/stop，强制角色、理由、Evidence、幂等和
  stale/drift 失败关闭；写入只复用 OperatingTask/Event。
- `/team-control` 老板工作台展示总负责人、12 名专家、5 个控制角色、四条主线、阻断与
  唯一下一动作；Web 不自行计算状态或模拟成功。

## 2. Design It Twice 记录

比较了三种可行 Interface：

| 方案 | 优点 | 未选原因/吸收点 |
|---|---|---|
| `pursue/contribute/project` 事务生命周期 | 状态机、Evidence、幂等、WIP 与职责分离最强 | 外部概念过多；其控制规则全部吸收到内部实现 |
| 通用 `submit/view` Command/Query | 后续扩展任务类型方便 | 容易形成第二命令总线，老板操作复杂 |
| `brief/advance` 老板型接口 | 每天只看一张摘要和一个动作，最符合总控目的 | 选用；continuation 冻结状态，内部仍复用权威任务事件 |

最终设计保持“外部窄、内部深”：没有新 Task/Fact/Finance/Approval/Permit 真源，也没有
数据库迁移或迁移租约占用。

## 3. 负向控制证明

- scope 不 ready 时不公开 continuation，也不读经营任务；
- 跨 store 身份、角色越权、未知泳道、注册表外写边界漂移、旧 continuation、同幂等键
  内容漂移全部失败关闭；
- done/stop 无 Evidence 失败，Evidence 必须由 exact-scope authority 投影为 current；
- Operator 不能因此获得 Approval、Permit、凭据、Fact/Finance 晋升或 provider write；
- `POST /v1/team-control/advance` 不在 Kill Switch 安全控制白名单。

## 4. 验证

| 验证 | 结果 |
|---|---|
| Team Control + Global Expert 定向测试 | `22 passed` |
| API/OpenAPI + OperatingTask/Event 回归 | `62 passed, 1 warning` |
| 非 PostgreSQL 全量回归 | `2432 passed, 1 skipped, 37 warnings` |
| Web 契约测试 | `145 passed` |
| Next.js 生产构建 | PASS；63 routes，包含 `/team-control` |
| `uv run ruff check .` | PASS |
| `uv run python scripts/verify_secrets.py` | PASS；1397 worktree files、1376 historical paths |
| `git diff --check` | PASS；只有现有 LF→CRLF 提示 |

本切片没有数据库 schema 变更，因此没有声明 PostgreSQL 迁移验收；OperatingTask/Event 的
已有数据库能力由现有权威与回归覆盖。上述全量测试显式排除 `tests/*_postgres.py`，避免把
共享本地数据库的外部状态误写成 LG-001 的工程证明。

## 5. 未被证明的事项

本 Evidence 不证明真人 Business Owner/持证专家已到岗，不证明真实俄罗斯订单、平台结算、
银行到账、Actual Cash CM3、C0 付费客户、合同/DPA/SLA、生产托管、付款或平台写入已通过。
这些事项仍由现有动态计划、实名 Owner、原始 Evidence 和对应 Gate 决定。
