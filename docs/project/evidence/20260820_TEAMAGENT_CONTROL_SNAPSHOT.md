# TeamAgent 控制快照 — 2026-08-20

运行 `uv run python scripts/compile_teamagent_control_snapshot.py --compact`，以只读方式编译
`GlobalPortfolioOrchestrator`、`LoopEngineeringService` 与可用的 Harness 投影。

## 结果

- contract: `kjds-teamagent-control-snapshot-v1`
- `snapshot_sha256`: `d7527d78a86c82ce54ff83f70467a08ee650703c38aa22cea690a0bb08087a8f`
- Harness: `unavailable`（本次未提供 `harness_project_id`，没有伪造在线项目结果）
- `external_write_allowed=false`
- `formal_fact_promotion_allowed=false`
- `runtime_dependency_allowed=false`

## 当前执行队列

1. `BAS-223 / current-head G1`
2. `D10 供应、checkout、CM3 证据`
3. `AI 编排内核 shadow hardening`

Portfolio 状态仍为 `proposal_shadow`；快照不证明人类专家任命、市场 Gate、业务事实、财务结果或外部写入。

`snapshot_sha256` 绑定稳定的控制投影，明确排除仅用于审计的 `captured_at`。
同一投影连续两次只读编译产生不同捕获时间但相同哈希，避免把观测时钟误判为控制状态变化。
