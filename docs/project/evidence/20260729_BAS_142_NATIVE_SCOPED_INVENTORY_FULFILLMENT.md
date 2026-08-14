# BAS-142 Native scoped 库存、仓储与履约 Evidence

## 1. 结论

KJDS AI ERP 已交付原生、只读、exact-scope 的库存/履约工作台。唯一
`ScopedInventoryFulfillmentWorkspace` 只从正式 `ozon_inventory` Fact 建立
SKU+warehouse+FBP/realFBS+cluster 当前快照，并与同一 `as_of` 的 Native OMS
open demand 组合。页面观察、legacy 库存、第三方静态表和 Agent 推断均为 0。

本切片为 `DONE_ENGINEERING`，不是经营完成。真实库 inventory/order Facts 均为
0，运行结果如实为 `no_data`；没有库存调整、预占、履约命令、采购、付款、
Approval、Permit 或 Ozon 写。

## 2. 实现与合同

- BR-116 / ADR-0062。
- 正式导入：`OzonRecordType.INVENTORY`，非负整数数量，模式只允许 FBP/realFBS。
- 自然键：exact SKU、warehouse、fulfillment mode、cluster。
- 服务：`apps/control_plane/scoped_inventory.py`。
- API：认证 `GET /v1/inventory/workspace`。
- Web：`/inventory`；`/scope-authority` 是到 `/authority-intake` 的兼容路由。
- 最新坏 Fact 使单元 blocked；旧有效快照只保留历史，不回退 current。
- OMS `no_data` 不当作零需求；客户端不计算 coverage/shortage。
- Agent 仅 `decision_support_only`，输入绑定服务端 snapshot hash。

## 3. PostgreSQL 迁移与业务行保全

独立临时 PostgreSQL：

- `base → 20260729_0073`：成功，库存索引计数 1；
- `0073 → 0072`：成功，索引计数 0；
- `0072 → 0073`：成功，索引计数 1；
- 显式临时库已删除。

真实库只执行 forward `0072→0073`。升级前建立 ignored output 逻辑回滚点：
`output/db-backups/bas142-pre0073-fact-records.sql`，SHA-256
`34dca3b43bd0056183dafc4965f7728cc976cb4e83b430f0fa33e8ea0c383715`。

下列行数与确定性内容 hash 升级前后完全一致：

| 表 | 行数 | SHA-256 |
|---|---:|---|
| fact_records | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| marketplace_observation_snapshots | 26 | `119c26df946c2d5a30be8563861b61f79139ee7990e3c4b4180cedd304ea78f0` |
| marketplace_observation_items | 49 | `391e2a0ada31883893335c66a3acf8f7110c1c05b9a0d49184389cd0ac76399b` |
| evidence_records | 117 | `8f0110c41a482ef7b9fd2ba7a017db1f61a0362e38cf7d26c293fe87ab7585a6` |
| products | 1 | `dcd4f767afe4e32481bf258716ed579c30810ef4bdfeb7ce554f9980d9c7307d` |
| operating_tasks | 2 | `49861ca6aa2315cb5050ccdc1d9eb299ed25e3896110219acb9e3a685172cd5e` |

真实 current/head 为单一 `20260729_0073`，索引计数 1。

## 4. 测试与交付门

- 聚焦服务/API/基线合同：`92 passed`。
- 全量后端：`836 passed`，9 个已知依赖弃用 warning。
- Secret scan：814 个非忽略工作树文件、581 个历史路径通过。
- `uv run ruff check .`：通过。
- Web `npm ci`：0 vulnerabilities。
- Web `npm test`：70 passed。
- Web `npm run build`：39 个路由通过，含 `/inventory` 与兼容路由。
- OpenAPI 0.59.0 包含 `/v1/inventory/workspace`。
- `git diff --check`：退出 0，仅现有 LF/CRLF 提示。

## 5. 真实运行

- PostgreSQL/API/Web/media-worker 四容器均 healthy。
- `/health/ready`：200、version 0.59.0、database ok。
- inventory 匿名 401；认证 exact store 200；越权 store 403。
- 认证响应：`status=no_data`、`entity_ref=null`、inventory Facts 0、
  legacy inferred 0、market inferred 0、external write false。
- GET 前后 operating_tasks 为 2/2，证明读取无副作用。
- 运行 OpenAPI 包含新路由。

## 6. 浏览器实测

真实 Supabase operator session、运行容器和 PostgreSQL：

| Artifact | SHA-256 | 结果 |
|---|---|---|
| `output/playwright/release-0.59.0/native-inventory-desktop.png` | `c1c5f901483c19399bb79f7d4dff3c8571ee386867e1a78b1bbc8ecade7406fe` | inner/client/scrollWidth = 1440/1440/1440 |
| `output/playwright/release-0.59.0/native-inventory-mobile-390.png` | `9b92198ce985f8bbcea315520ee6a748f32f7e19ce0552725bc443ffa1f1eb3d` | inner/client/scrollWidth = 390/390/390 |

两者均显示服务端 `no_data` 和 `external write · false`。最终原子导航/量测：
0 新 console error、0 failed response。测试期间先发现 `/scope-authority` 预取 404，
随后增加兼容路由；错误截图未作为最终 Evidence。

## 7. 未关闭 Gate

- Harness 重新执行聚焦测试、PostgreSQL、容器/API、截图 hash 与 Evidence
  verifier 后，BAS-142/143 六个新任务均 `passed/fresh`。
- canonical Graph：46 tasks、142 nodes、151 edges、append-only observations
  `>=283`。
- 全项目仍有 17 个更早的 stale 任务；本切片不覆盖或伪装其状态。
- 正式库存、订单、退货、采购、结算和到账事实仍为 no_data。
- 0.59 PM/RA Release Gates 继续 REJECTED。
- Pilot/Final Gates 未通过；pricing 仍 not_for_sale。
- Ozon、供应商、采购、付款、库存、履约、客户消息和广告 external write 全关闭。
