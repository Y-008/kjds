# 动作授权与短期执行许可运行证据（2026-07-21）

## 结论

KJDS 已完成第一条 L3 真实副作用运行切片：`listing_publish` 从治理计划、独立审批、排队、Worker claim 到 Ozon 外部写调用，均绑定同一动作政策、不可变决定摘要、精确额度和短期单次许可。该结论只覆盖现有 Ozon 商品导入适配器，不代表采购、付款、广告、补货、`actual` 晋升或正式财务入账已经放行。

## 已实现合同

1. `action_policy_registry.json`（`policy_version=2026-07-21.1`）是动作风险等级、作用域、许可、复验、幂等、回读、回滚、所需 readiness 和爆炸半径字段的唯一机器合同。
2. `ExecutionPlanService` 在计划创建和每次读取时调用同一个 phase-aware `authorize_action()`，重新绑定动作、政策版本、风险额度和当前 readiness，并生成不新增数据表的 `DecisionPacket` 投影与决定哈希。
3. `LimitedExecutorService` 在排队和 Worker claim 时调用同一授权服务再次验证；请求者、批准者和 Worker 身份必须分离。
4. 许可包含动作、目标、策略版本、决定哈希、授权哈希、精确限额、精确本次值、币种和过期时间；旧命令迁移后立即过期，不能继承新权限。
5. Ozon Worker 只使用 claim 后返回的命令，不使用 claim 前的旧对象；外部写前再次检查许可时效、哈希、动作、数量和预期损失。
6. 同一幂等 token 不能产生第二个命令；同一命令不能被另一个 Worker 重复 claim；超出额度、过期许可和篡改许可均失败关闭。

## 验证结果

| 检查 | 结果 |
|---|---|
| Python 静态检查 | `uv run ruff check .` 通过 |
| Python 全量回归 | 329 passed；另有 1 条第三方 Starlette/httpx 弃用警告 |
| Web 合同测试 | 19 passed |
| Web 生产构建 | Next.js build 通过 |
| OpenAPI v1 快照 | 已由运行时契约重新导出，契约测试通过 |
| Alembic 迁移头 | `20260721_0039` |
| 0038 → 0039 离线 SQL 编译 | 通过，PostgreSQL 事务型 DDL 可生成 |
| 差异空白检查 | `git diff --check` 通过 |

## 当前未完成与失败关闭

- 本机 Docker daemon 未运行，当前数据库连接也在 60 秒内无响应，因此尚未取得真实 PostgreSQL `upgrade head` 和 `/health/ready` 证据。上线前必须补齐，不能用离线 SQL 编译代替。
- L4 要求 MFA，统一授权器现已在缺失 MFA 证明时失败关闭；当前仍没有 L4 生产适配器和真实 MFA 会话绑定，因此 L4 动作保持不可执行。
- 当前授权摘要是控制面内部完整性绑定，不是可跨信任域验证的数字签名。若执行器跨越独立信任域，再评审签名或工作负载身份，不提前建设 PKI。
- 组合级风险预算、13 周现金硬约束、Champion/Challenger 晋升和自动化经济性门仍是后续阶段；单动作安全不等于全局资本安全。
- 现有外部执行默认由 `KJDS_LIMITED_EXECUTION_ENABLED=false` 关闭。只有真实数据库迁移、健康检查、凭证和先锋 SKU 门禁全部复验后，才能进行受控小流量演练。

## 下一验证顺序

1. 恢复可用 PostgreSQL，执行 `alembic upgrade head` 并验证 `/health/ready`。
2. 在一次性测试 SKU 上完成“请求者 → 批准者 → Worker → Ozon readback”的沙箱或非发布演练。
3. 将广告、样品付款等动作接入同一共享副作用入口；不为它们复制 Gate。
4. 在 L3 授权前增加 SKU、店铺和全局额度聚合，并将 13 周最低现金余额作为硬阻塞条件。
5. 用第二、第三 SKU 验证 DecisionPacket、人工修改率、运行成本和回滚，再决定是否晋升 Skill。
