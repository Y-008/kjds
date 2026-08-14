# BAS-176 PostgreSQL 18 隔离演练证据

- 日期：2026-08-03
- 实施提交：`c6220c2b359387cc18ce7d9ae16f34bc45df28c2`
- 迁移单头：`20260803_0090`
- 工程演练：`PASS`
- 生产 Exit Gate：`not_passed`
- PostgreSQL 18 基线晋级：`false`

## 1. 运行边界

命令：

```powershell
uv run python scripts/verify_postgres18_pilot.py `
  --output-dir .runtime/postgres18-pilot-bas176-fourteenth
```

演练使用三个随机命名的一次性容器和独立 Docker 网络：PostgreSQL 17
源库、PostgreSQL 18 候选库、PostgreSQL 17 回滚库。端口仅绑定 loopback，
数据目录仅使用 tmpfs；未创建 named volume，未执行 `docker compose up/down`，
未连接生产数据库。运行前后的 `compose.yaml` 哈希及现有
`kjds-postgres-1` 容器 ID 均相同，最终容器、网络和临时 dump 均已删除。

固定镜像与结果：

| 角色 | 镜像 | 服务端版本 | image SHA-256 |
|---|---|---|---|
| 基线 | `postgres:17.10-alpine` | 17.10 | `742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193` |
| 候选 | `postgres:18.4-alpine` | 18.4 | `9a8afca54e7861fd90fab5fdf4c42477a6b1cb7d293595148e674e0a3181de15` |

声明的 Compose/验证基线仍是 `postgres:17-alpine`，本次结果不修改默认依赖。

## 2. 迁移、Schema 与恢复

- PG17 空库升级：`head=20260803_0090`。
- PG18 空库升级：`head=20260803_0090`。
- PG18 降级到 `20260717_0024` 后重放：`head=20260803_0090`。
- 三次语义 Schema SHA-256 均为
  `9a071c740f652a300bb6ca2a53bcc9157b61a560c10647e456ecccb5d29e8489`。
- Inventory：122 tables、1951 columns、611 非 NOT NULL constraints、420 indexes。
- PostgreSQL 18 将列级 `NOT NULL` 单独存入 `pg_constraint`；比较器排除该跨版本
  catalog 表示差异，但继续比较列名、完整类型/typmod、nullable、identity、
  generated，以及 PK/UK/FK/CHECK/EXCLUDE 和索引清单。
- downgrade/re-upgrade 会改变部分列的物理 `attnum`；合同按列语义而非物理布局
  比较。去除 `attnum` 后 fresh/replay 差异为 0。

冻结的 PG17 custom-format dump：

- 大小：1,607,427 bytes
- SHA-256：`009116666889b48d1a4028df68df80832e5045b737d33d261128bd2d1460cd13`
- PG18 前向恢复：PASS
- 第二个 PG17 回滚恢复：PASS
- 三方 20,000 行数据 SHA-256：
  `eb67fdd3cd9bc36728d2af99a07f158541dde96219e4b0f10757fff26fd43aed`
- 候选切换期间业务写入：未允许
- 原地跨大版本 downgrade：未宣称

## 3. 查询与锁预算

每个查询先预热 2 次，再测量 7 次。Gate 为候选中位数不超过基线 3 倍，且
绝对值不超过 75 ms；三组结果集哈希逐项相同。

| 查询 | PG17 median ms | PG18 median ms | 比率 | 结果 |
|---|---:|---:|---:|---|
| exact_scope_latest | 0.082 | 0.073 | 0.890 | PASS |
| status_scope_aggregate | 0.059 | 0.052 | 0.881 | PASS |
| tenant_time_aggregate | 0.678 | 1.037 | 1.529 | PASS |

锁冲突在两代数据库均返回 SQLSTATE `55P03`，均观察到未授予锁；PG17 等待
1207.345 ms，PG18 等待 1205.445 ms。阻塞事务均回滚，目标行保持未改变。

## 4. PostgreSQL 18 特性探针

- `uuidv7()`：可用。
- temporal `WITHOUT OVERLAPS`：可用，重叠写入被拒绝。
- `pg_aios`：可见，`io_method=worker`。
- OAuth 服务端能力：可见；运行时 OAuth 配置：关闭。

这些探针只证明候选能力可见，不证明 KJDS 已采用相应业务语义或认证路径。

## 5. 可验证产物

| 产物 | 文件 SHA-256 |
|---|---|
| `20260803_BAS_176_POSTGRES18_PILOT_REPORT.json` | `d34725cbb5a7b3b997d13f9b5ccb00766b3cd281d312785eb18b7b28b894b040` |
| `20260803_BAS_176_POSTGRES18_PILOT_VERIFICATION.json` | `8cba72155bcdaa0a01e6901a84d3b9896e68e3ccc66dae70f0dc9b2a95825641` |

Authority 对 canonical report 的 SHA-256 为
`2c2b75f88135e5e86b6de8a8a9fc74ac00d63600a822f19f12ad1790a8163f26`。
回执同时确认 migration replay、extension/driver compatibility、forward restore、
rollback restore、benchmark、lock、feature probe、cleanup 全部为 `true`。

## 6. 未关闭的生产 Gate

以下状态保持 `UNKNOWN`：

- 生产迁移 runbook 的审批与演练结果；
- 独立恢复负责人对恢复证据的批准；
- 真实生产工作负载、扩展、collation、维护窗口和容量结论。

因此 `production_dependency_allowed=false`、`baselinePromotionAllowed=false`、
`externalWriteAllowed=false`、`formalFactPromotionAllowed=false`。本证据只关闭
BAS-176 工程演练，不关闭 PostgreSQL 18 生产 Exit Gate。

## 7. 上游依据

- PostgreSQL 18 总体变更：<https://www.postgresql.org/docs/18/release-18.html>
- PostgreSQL 18.4 发布说明：<https://www.postgresql.org/docs/release/18.4/>
- `pg_dump` 跨版本传输约束：<https://www.postgresql.org/docs/18/app-pgdump.html>
- `pg_upgrade` 与回滚注意事项：<https://www.postgresql.org/docs/18/pgupgrade.html>
- PG18 `pg_constraint`（含 `contype=n`）：<https://www.postgresql.org/docs/18/catalog-pg-constraint.html>
