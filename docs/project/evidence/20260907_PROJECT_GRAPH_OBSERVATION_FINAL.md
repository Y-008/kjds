# 2026-09-07 KJDS 项目图谱与 Ozon 观察最终证据

本记录是 2026-09-07 的本地控制平面验收探针。`source_code_head_before_evidence_commit` 是本次探针绑定的源码 HEAD；本文件随后产生的文档提交不属于该源码快照。记录描述工程、证据和经济状态，不把本地通过解释为 Ozon 生产、利润或发布就绪。

## 绑定范围

| 字段 | 值 |
| --- | --- |
| captured_at | 2026-09-07T05:40:09.000000+00:00 |
| source_code_head_before_evidence_commit | `d138aef6ed364097653f36d4381852aefefefa56` (`docs: record graph error closure evidence`) |
| API / schema | `0.59.0` / `v1` |
| OpenAPI canonical SHA-256 | `5c70476f2d87ad24b4ad5d5adca5eb0a9063df0a2280ef481ff150be95e8793e` |
| OpenAPI paths | 398 |
| migration head | `20260907_0120` |
| evidence contract | `kjds-ozon-acceptance-snapshot-binding-v1` |

探针只使用本地 monitor 身份，未记录或输出凭据。`external_write_allowed=false`、`formal_fact_allowed=false`，托管租约仍是 shadow/unknown；控制平面不允许把本地观察升级为外部写入。

## 运行回执

- `/health/ready`：HTTP 200，数据库 `ok`，事件数 231；响应 SHA-256 为 `98d005022e36932bca55d5e79e95dc9815c243fc51d788a60192e5b7635f8b6f`。
- `/version`：HTTP 200，服务 `kjds-control-plane`，版本 `0.59.0`，数据库 `local-postgres`，`shadow_mode=true`。
- `POST /v1/agent-control/projects/kjds-059-bas123/observe?store_ref=ozon-primary`：HTTP 200，状态 `blocked`，本次响应 SHA-256 为 `3f2ccfaefef845ad66d70241b50bcef6a5e4be5224ff131cc6ee7307f3e48fb9`。
- 观察 `result_sha256=268479694adff4e9eed73bce6162713f6610b9d49b205128c5c89198688e2076`；计数为 `tasks=133`、`observations=948`、`nodes=267`、`edges=260`。
- 本轮新增四条当前 HEAD 绑定的工程回执：API `passed`（`.runtime/bas123-api-20260907-133608.json`，SHA-256 `8fe8855a71d78b95d8a1ff82449ced7a69ae2a43348749a2453188edb880ac06`）、PostgreSQL `passed`（`.runtime/bas123-database-20260907-133748.json`，SHA-256 `7e536da88113799c9e8749c8d4a4e73dfc17868d2a04f45504767ff927200665`）、容器 `passed`（`.runtime/bas123-containers-20260907-133624.json`，SHA-256 `cce46b5dfe5924ce0ab7f6d3ac7bc75dd29d04286a5530206a3692b65a65bd20`）。全量后端回归回执为 `4111 passed, 11 failed, 174 errors, 160 skipped`（`.runtime/pytest-full-20260907-133056.log`，SHA-256 `0786b595b3d5f0936de7b4347e870691895897765a098f42746782f9b0079e90`），已如实记录为 `failed`；失败集中在 PostgreSQL 生命周期测试期待 `20260803_0094`，而当前受管数据库为 `20260907_0120`。
- 观察工作区快照仍为 `693edfbf27fdb5a654b505c113fdf0155a28b94e7ca8ce4dd16d2f336011bba8`。
- 同一小时重复观察返回相同响应/结果哈希和计数，证明小时桶回放不会重复写入观察事实。

## 图谱前沿、关键路径和回放

- Frontier HTTP 200，`status=BLOCKED`，`frontier=223`，`blockers=395`，`graph_errors=0`；快照 SHA-256 `1328e401c1aacefa8c453c089c7f40cdc959c6384d4b772c1c01d2ef71d76ab3`，响应 SHA-256 `c1f740657f9957d76d7ec6506ded26bbdbb54eca5720380ac29acb52bfe0a61b`。
- 关键路径目标仍为 `task-m4-actual-cash`，长度 17，状态 `BLOCKED`；完整前置集合仍包含 API、数据库、容器、浏览器、证据、测试及 M0–M3 节点。
- 主要阻断原因包括 `freshness_stale`、M0–M3 上游阻断，以及 BAS-124 派生链、浏览器、证据和全量回归失败。基础 API、PostgreSQL、容器回执已刷新为 `passed`，但不能越过失败的测试与 M0–M3 前置；项目经理应继续处理这些节点，而不是派发无依赖的外部写入。
- Replay HTTP 200，`integrity.status=VALID`、`snapshot_hash_verified=true`，业务状态仍为 `BLOCKED`；结果 SHA-256 `d4f34536412e1c8b537f3c58b21fbd4c3665e16e47ed9cfa8a7967f68fee2fa0`，回放快照 SHA-256 `8f5110564c6009bffa160c4f5bc3e6c5642060ac352b98cfa886104c9e5bef8b`，响应 SHA-256 `b191bc6e4313d5ec8e5ec6ff6c3e897f443d0f85c32951d444c5b40cfbb6108a`。

## 经济护栏

`GET /v1/economics/guard-status?store_ref=ozon-primary` 返回 HTTP 200、`status=UNKNOWN`、`quality_state=NO_DATA`、`admission_state=HOLD`、`status_source=unavailable`，原因 `cash_snapshot_missing`，且 `external_write_allowed=false`。未知或无数据经济状态不能触发调价、补货、广告、发布或其他平台写入。

## 控制回路 HTTP 烟测

- `GET /v1/control-loop/status`：HTTP 200，`status=VALID`、`execution=proposal_only`，响应 SHA-256 `6b606df9a3afee13fe2128df2ba8138d8f0d8425ec4269b8abb0e5ead2446f03`。
- `POST /v1/control-loop/metrics/compile`：HTTP 200，`status=COMPILED`、`execution=read_only`，`plan_hash=4498db8802aaeb5fa7fc0cd814de050980793313e865bd6eb5823cd5bafe552e`，响应 SHA-256 `e4476a267db66882f9b3ca787d7a342449851cba4f428f8b87143460eb664b63`。
- `POST /v1/control-loop/objectives/evaluate`：HTTP 200，`status=PROPOSED`、`execution=proposal_only`，响应 SHA-256 `d191d2d23818c58a0efcabfae97fe98de2efb76aef6e3c13fd6dfab487fce0e2`。
- 三个端点均返回 `external_write_allowed=false`；烟测未调用 Ozon、银行或其他外部写接口。

## Ozon 浏览器与官方读回

现有 `output/playwright/ozon-products-evidence.json` 仍为 `QUARANTINED`：17 行可解析但有 21 个问题，包含跨行混入其他商品 ID、页脚/分页污染和货币代码缺失；`promotion_allowed=false`、`formal_observation_allowed=false`。该文件只作为待清洗线索，不能升级为商品、价格、库存或利润事实。

官方 Ozon 读回仍被 `403` 授权阻断；没有可接受的官方 response bundle，也没有执行调价、改库存、广告、商品发布或其他外部写入。Chrome 登录会话未关闭、未重启、未切换账号。

## 验收结论和下一步

当前可交付级别为：工程控制平面、证据协议、图谱前沿、回放完整性和 AI ERP 只读工作台已具备可验证实现；Ozon 生产写入、真实利润、现金闭环和 SaaS 商业化仍保持阻断。下一波由 heartbeat 继续刷新过期工程证据、收敛剩余 395 个阻断节点、取得官方只读回读并重新计算经济护栏；在证明、证据新鲜度、数据质量、外部读回和回滚路径同时满足前，系统保持只读。
