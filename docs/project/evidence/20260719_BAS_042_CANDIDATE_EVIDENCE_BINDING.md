# BAS-042 候选观测绑定不可变 Evidence 验证

| 字段 | 值 |
|---|---|
| 日期 | 2026-07-19 |
| 状态 | DONE_ENGINEERING |
| Gate | G0 |
| 业务放行 | 否 |

## 目标

关闭“填写任意 `source_ref` 就能让候选进入三报价”的证据伪装路径。候选研究观测只有绑定 Evidence Ledger 中存在且哈希复验通过的原件，才可参与 BAS-041 预检。

## 实现边界

- 复用 `EvidenceService.require_valid/get` 和 `MarketObservation.dimensions`，没有新增表、迁移、队列或依赖。
- 每条候选观测必须提供 `dimensions.evidence_id`。
- 原件 `source/source_ref` 必须与观测完全一致；来源独立性按原件而非用户填写的观测文本计算。
- 观测 `observed_at`、原件 `effective_at` 和可选 `effective_until` 同时受 `as_of/max_age_days` 约束。
- 缺失、未知、损坏、过期或来源不匹配的原件均从有效观测中排除，并返回 `collect_evidence`。
- 返回值区分 `observation_ids` 与 `evidence_ids`；仍不会创建 Product、采购单或 Listing。
- 来源族暂按末两级域名归并，覆盖当前 `ozon.ru/1688.com`；若引入多段公共后缀市场，再以已验证需求决定是否采用 Public Suffix List。

## 验证

```text
uv run pytest tests/test_core.py tests/test_api_contract.py -q
21 passed

uv run pytest -q --basetemp .runtime/pytest-bas042-<timestamp>
212 passed

uv run ruff check .
All checks passed

uv run ruff format --check apps/control_plane/intelligence.py apps/control_plane/api.py tests/test_core.py
3 files already formatted

uv run python scripts/verify_secrets.py
Secret scan passed: 289 non-ignored worktree files checked

pwsh -NoProfile -File scripts/verify-g1.ps1
G-1 PASS; migration 20260718_0036; database cleanup passed
```

## 尚未证明

- 尚未采集任何真实新上新候选的原始 Ozon 市场数据、供应商页面快照或官方合规原件。
- 尚未形成三个真实候选池，三报价、样品、物流、关税、退货准备金和 CM3 仍为空。
- 本工程门只阻止伪证据进入报价，不替代商品负责人、合规负责人或财务负责人的批准。
