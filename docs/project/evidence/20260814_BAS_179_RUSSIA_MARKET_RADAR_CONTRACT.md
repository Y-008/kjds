# BAS-179 俄罗斯市场需求与热点事件雷达契约 Evidence

## 1. 结论

BAS-179 建立了一个只读、prep-only、exact-scope 的俄罗斯市场情报深模块 `GovernedRussiaMarketRadar`，冻结 ADR-0091 Acceptance #3：俄语词形/查询展开、跨源 content-addressed 去重、事件时间排序与分解评分，并输出按原始维度分解的需求投影。不接入任何 marketplace adapter、账号绑定、搜索身份或外部写；缺失数据以 `UNKNOWN`/`no_data` 报告，绝不以 0 或模型估计替代；任何 signal 都不直接生成 Fact、FinanceEntry、Purchase、Campaign 或 Profit 写。

- 唯一外部模块接口：`apps/control_plane/russia_market_radar.py`。
- 输出类型：`RussiaRadarObservation`、`DemandSignal`、`HotEventCandidate`、`ExpandedQuerySet`。
- 无迁移、无公共 API、无 OpenAPI 变化、无 runtime 聚合、无新依赖、无 outbox。
- 真源仅复用既有只读输入：`docs/project/registries/russia_market_intelligence_sources.json`、ADR-0091、`docs/project/evidence/20260803_RUSSIA_MARKET_DEMAND_AND_EVENT_SOURCE_RESEARCH.md`。

本结果只证明契约确定性，不代表真实俄罗斯搜索/销售需求。

## 2. 冻结契约

| 字段 | 冻结值 |
|---|---|
| 模块 | `GovernedRussiaMarketRadar` |
| 雷达契约 | `kjds-russia-market-radar-v1` |
| 查询分类法契约 | `kjds-russia-demand-query-taxonomy-v1` |
| 热点事件契约 | `kjds-russia-hot-event-taxonomy-v1` |
| 观测契约 | `kjds-russia-market-observation-v1` |
| 市场 | `ru` |
| 真实 adapter admitted | `false` |
| 信号域 | 8 类（与源注册表一致） |
| 来源 id | 8 个（与源注册表一致） |

## 3. 四个 Acceptance #3 证明

1. **俄语词形/查询展开**：`expand_queries` 对 seed 执行 lowercase、`ё→е`、去组合重音、空白归一；内建 synthetic 词典覆盖 `word_form`/`synonym`/`category`/`question`/`scenario`/`brand` 六维，支持调用方扩展并严格校验维度与 seed 归属。
2. **跨源 content-addressed 去重**：`collect` 以 `content_hash` 为键，同内容不同来源合并为一条观测并累计 `source_ids`/`cross_source_count`，非法记录进 quarantine，守恒 `conserved + dedup + quarantined == source_total`。
3. **事件时间排序**：`order_events` 按 `effective_at → first_seen_at → event_id` 全序排列；非法时间 fail-closed。
4. **分解评分**：`score_event` 输出 7 维 components（`source_authority`/`recency`/`velocity`/`cross_source_count`/`entity_relevance`/`profit_or_supply_exposure`/`observed_market_response`），缺失维 `UNKNOWN` 不记 0；escalation 需跨源 ≥2 且存在 `observed_market_response`；`external_action_allowed` 恒 `false`。

## 4. 控制边界

- `zero_authority()` 全部 `false`：`formal_fact`/`finance_entry`/`approval`/`permit`/`pilot`/`outbox`/`canonical_graph_write`/`dependency_install`/`network`/`external_write`。
- 单条社媒帖、单次搜索 spike、单条平台新闻都不能直接触发采购、广告、发布、库存动作。
- 公共宏观/平台观察只作风险与研究上下文，不冒充 SKU 销量或利润。

## 5. UNKNOWN / 外部阻断

- Ozon Analytics 真实账号 scope、Wildberries 商家账号与 Analytics Token、Yandex Search API service account/role/key、Telegram/VK 专用身份与种子尚未提供。
- 真实站内搜索、加购、订单、利润 Evidence 不足，无法据此排名真实 SKU 机会。
- 当前仅冻结 fixture，不声称 connector、订阅、账号已 live。

## 6. 验证

- `tests/test_russia_market_radar.py` 29 passed。
- Ruff check（E/F/I/UP/B/SIM，忽略 E501）PASS。
- Secret scan PASS。
- 社会电商 lane 回归 99 passed；requirements traceability 25 passed（隔离 basetemp 后）。
- 源注册表反漂移：模块 `SOURCE_CLASS_BY_ID`、`ALLOWED_SIGNAL_DOMAINS` 与 `russia_market_intelligence_sources.json` 一致。