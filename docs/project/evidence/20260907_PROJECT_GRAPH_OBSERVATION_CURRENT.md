# 2026-09-07 KJDS 项目图谱与 Ozon 观察当前证据

本记录绑定一次同一时点的本地控制平面观察。它描述工程和证据状态，不把本地通过误报为 Ozon 生产、利润或发布就绪。

## 绑定快照

| 字段 | 值 |
| --- | --- |
| captured_at | 2026-09-07T04:14:50.378595+00:00 |
| canonical HEAD | `5427faf29b51f1880f86f8e4655cb8e181143924` |
| API / schema | `0.59.0` / `v1` |
| OpenAPI canonical SHA-256 | `cd8f5a0fd98379f121635390339c6ac7a88093334db14731b878144d57088d2f` |
| migration head | `20260907_0120` |
| acceptance snapshot SHA-256 | `72838d0732134d881e4dbb326a35c651a6177e58d3d47f5761bdf4f7875f7cb8` |
| snapshot validation | `valid=true`, `drifts=[]`, `secret_free=true` |

快照契约为 `kjds-ozon-acceptance-snapshot-binding-v1`。它固定 `external_write_allowed=false`、`credential_values_returned=false` 和 `immutable=true`；托管租约投影为 `UNKNOWN/shadow`，不包含凭据或可用授权材料。

## 运行回执

- `/health/ready`：HTTP 200，数据库状态 `ok`，事件数 231。
- `POST /v1/agent-control/projects/kjds-059-bas123/observe?store_ref=ozon-primary`：HTTP 200，观察桶 `2026-09-07T04:00:00+00:00`，状态 `blocked`。
- 观察回执 `result_sha256=ee626c00ee6c15a818217a61fef168d53de0e7ec6a1701a4f0b12f81a4fda2e5`；响应 SHA-256 为 `eeeb823cb1352266e3e0e3ba6e0e54704b83ded46ba8091667c8ac60403efa60`。
- 观察计数为 `tasks=133`、`observations=937`、`nodes=267`、`edges=260`，`workspace_snapshot_sha256=693edfbf27fdb5a654b505c113fdf0155a28b94e7ca8ce4dd16d2f336011bba8`。
- 同一小时重复调用返回相同响应 SHA、相同结果 SHA 和相同计数，证明小时桶回放不会重复写入观察事实。

图谱前沿回执：

- `status=BLOCKED`，`frontier=224`，`blockers=606`，关键路径长度 17，目标为 `task-m4-actual-cash`。
- 前沿快照 SHA-256 为 `c9bebd9ab435b68fec5c6d5294fffb991c6745d7576b119a06f12f39db9c3722`；响应 SHA-256 为 `453b6caa9af6a268156e0b16c7c12e7ecf697b3432b4b605ab115265c3825d11`。
- 主要原因是 `freshness_stale`、M0–M3 上游阻断，以及 API、容器、数据库、浏览器和测试证据过期。工程回放接口返回 `integrity.status=VALID`，但业务状态仍为 `BLOCKED`。

经济护栏当前返回 `status=UNKNOWN`、`quality_state=NO_DATA`，没有经济快照，且 `external_write_allowed=false`。未知经济结果不得触发调价、补货、广告或发布。

## 浏览器证据

本地浏览器文件 `output/playwright/ozon-products-evidence.json` 被验证为 `QUARANTINED`：

- 文件 SHA-256：`f8e7781fdf7ba384d69f548dc08cf59aa36f6aacb62fbb9a8295ecbc2d0b4ae4`。
- 原始可见文本 SHA-256：`7bc71947f9d786d0b8e4982c7ca0b4d39a2d61e7f136e3d8d406e6e87dc943ed`。
- 校验报告 SHA-256：`4d48f552810e23a765c5dd4c49fd3c264cd9fdd558b08aec287b42c89d2f69fb`。
- 17/17 行可解析，但存在 21 个问题：跨行混入其他商品 ID、页脚和分页内容；17 个货币代码未解析。
- `promotion_allowed=false`、`formal_observation_allowed=false`。该文件只能作为待清洗的浏览器线索，不能升级为正式商品、价格、库存或利润事实。

官方 Ozon 商品读回仍受 `403` 授权阻断；没有生成可接受的官方 response bundle，也没有执行价格、库存、广告、商品发布或其他外部写入。恢复顺序仍是官方只读回读、原始响应完整性、精确租约和独立验证器，然后才重新评估生产验收。

## 回放与恢复

- 图谱 replay 响应的 `integrity.status=VALID`、`snapshot_hash_verified=true`，说明当前图谱快照可重算。
- 旧的 `20260907_OPERATING_GATE_OBSERVATION.md` 和 `20260907_OZON_BROWSER_CAPTURE_CURRENT.md` 保留为历史回执；其中较早的计数和哈希不代表本记录的当前值。
- 下一步由项目经理心跳优先刷新关键路径上的过期工程证据和官方 Ozon 读回阻断；在证据新鲜、经济护栏通过、外部读回成功并且存在回滚路径前，系统保持只读。
