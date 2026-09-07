# 2026-09-07 KJDS 项目图谱与 Ozon 观察最终证据

本记录是 2026-09-07 的本地控制平面验收探针。`source_code_head_before_evidence_commit` 是本次探针绑定的源码 HEAD；本文件随后产生的文档提交不属于该源码快照。记录描述工程、证据和经济状态，不把本地通过解释为 Ozon 生产、利润或发布就绪。

## 绑定范围

| 字段 | 值 |
| --- | --- |
| captured_at | 2026-09-07T04:37:52.083153+00:00 |
| source_code_head_before_evidence_commit | `d1961b7c14e73f79ad7c0fc404d5ad5c60d616e5` (`fix: derive scoped graph reads safely`) |
| API / schema | `0.59.0` / `v1` |
| OpenAPI canonical SHA-256 | `cd8f5a0fd98379f121635390339c6ac7a88093334db14731b878144d57088d2f` |
| OpenAPI paths | 394 |
| migration head | `20260907_0120` |
| evidence contract | `kjds-ozon-acceptance-snapshot-binding-v1` |

探针只使用本地 monitor 身份，未记录或输出凭据。`external_write_allowed=false`、`formal_fact_allowed=false`，托管租约仍是 shadow/unknown；控制平面不允许把本地观察升级为外部写入。

## 运行回执

- `/health/ready`：HTTP 200，数据库 `ok`，事件数 231；响应 SHA-256 为 `98d005022e36932bca55d5e79e95dc9815c243fc51d788a60192e5b7635f8b6f`。
- `/version`：HTTP 200，服务 `kjds-control-plane`，版本 `0.59.0`，数据库 `local-postgres`，`shadow_mode=true`。
- `POST /v1/agent-control/projects/kjds-059-bas123/observe?store_ref=ozon-primary`：HTTP 200，观察桶 `2026-09-07T04:00:00+00:00`，状态 `blocked`。
- 观察 `result_sha256=ee626c00ee6c15a818217a61fef168d53de0e7ec6a1701a4f0b12f81a4fda2e5`，响应 SHA-256 为 `eeeb823cb1352266e3e0e3ba6e0e54704b83ded46ba8091667c8ac60403efa60`。
- 观察计数：`tasks=133`、`observations=937`、`nodes=267`、`edges=260`，`workspace_snapshot_sha256=693edfbf27fdb5a654b505c113fdf0155a28b94e7ca8ce4dd16d2f336011bba8`。
- 同一小时重复观察返回相同响应/结果哈希和计数，证明小时桶回放不会重复写入观察事实。

## 图谱前沿、关键路径和回放

- Frontier HTTP 200，`status=BLOCKED`，`frontier=224`，`blockers=606`；快照 SHA-256 `f6cebc3838f44f3a1e2d69c1b736fcb60b37a34fbe3d6bd614da29665e38a869`，响应 SHA-256 `6d6068a36b594d17f8aa719c3472eaed16972bb555f9c69f22149c3723a8ff14`。
- 关键路径 HTTP 200，目标 `task-m4-actual-cash`，长度 17，状态 `BLOCKED`；结果 SHA-256 `c78abfba9f7ad9454abc4ead860b5b5ccec4174af7b756c219a19e707c01134b`，响应 SHA-256 `79598546e2c3dbc3c645d0b46e3e72fb352955d9b410c1a4b60e76943b762943`。
- 主要阻断原因包括 `freshness_stale`、M0–M3 上游阻断，以及 API、容器、数据库、浏览器、测试证据过期。项目经理应优先刷新这些前置节点，而不是派发无依赖的外部写入。
- Replay HTTP 200，`integrity.status=VALID`、`snapshot_hash_verified=true`，业务状态仍为 `BLOCKED`；结果 SHA-256 `2f9c9b30c7a7b27c4fe1cd68bcbe009d09708897bfeb1fe6c5049984c7aaf56f`，回放快照 SHA-256 `6b0007a326793fcffa14d46c8e5b3a0c631447635c1e2392de576ca2c102717b`。

## 经济护栏

`GET /v1/economics/guard-status?store_ref=ozon-primary` 返回 HTTP 200、`status=UNKNOWN`、`quality_state=NO_DATA`、`admission_state=HOLD`、`status_source=unavailable`，原因 `cash_snapshot_missing`，且 `external_write_allowed=false`。未知或无数据经济状态不能触发调价、补货、广告、发布或其他平台写入。

## Ozon 浏览器与官方读回

现有 `output/playwright/ozon-products-evidence.json` 仍为 `QUARANTINED`：17 行可解析但有 21 个问题，包含跨行混入其他商品 ID、页脚/分页污染和货币代码缺失；`promotion_allowed=false`、`formal_observation_allowed=false`。该文件只作为待清洗线索，不能升级为商品、价格、库存或利润事实。

官方 Ozon 读回仍被 `403` 授权阻断；没有可接受的官方 response bundle，也没有执行调价、改库存、广告、商品发布或其他外部写入。Chrome 登录会话未关闭、未重启、未切换账号。

## 验收结论和下一步

当前可交付级别为：工程控制平面、证据协议、图谱前沿、回放完整性和 AI ERP 只读工作台已具备可验证实现；Ozon 生产写入、真实利润、现金闭环和 SaaS 商业化仍保持阻断。下一波由 heartbeat 继续刷新过期工程证据、修复图谱未知边关系、取得官方只读回读并重新计算经济护栏；在证明、证据新鲜度、数据质量、外部读回和回滚路径同时满足前，系统保持只读。
