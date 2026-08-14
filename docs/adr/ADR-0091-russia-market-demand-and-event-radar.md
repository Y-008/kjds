# ADR-0091: 俄罗斯市场需求与热点事件雷达

- Status: Accepted for staged implementation
- Date: 2026-08-03
- Owners: Russia Market Intelligence, Commerce, Evidence, Risk

## Decision

Introduce one `RussiaMarketIntelligenceWorkspace` behind the existing Evidence, exact-scope and market-radar authorities. It composes official authorized marketplace data, Yandex search demand, public or authorized Russian social signals, official platform changes and economic/trade/logistics events. It does not replace Product, Order, Finance, Profit, Campaign or Fact owners.

Collection walks every available page, field and requested time window without a KJDS sample cap, records source-native caps and permissions, supports checkpoint/resume and historical backfill, and conserves `accepted + quarantined = source_total`. Raw observations, normalized entities, analytical signals, experiments, actions and outcomes remain separate.

Demand and hot-event projections expose decomposed dimensions and source lineage. A single post, search spike or platform press release cannot become a sales, profit or purchase fact. Cross-source corroboration, expiry/review times and actual marketplace response are required for escalation. Campaign actions stay available through campaign-scoped grants and readback, not through unrestricted Agent credentials.

## Consequences

- Russia market intelligence becomes a separate lane while sharing the social collection and TeamAgent problem-solving Loop.
- Ozon remains first execution marketplace; Wildberries and Yandex Market data can be collected after their own account and scope are available without changing that execution priority.
- Current public macro/platform observations can inform risk and research immediately, while seller analytics truth remains `no_data` until real authorization exists.
- The registry lists capabilities and next gates; it does not claim connectors, subscriptions or accounts are live.

## Acceptance

1. Official source registry covers marketplace, search, social, platform and macro event classes.
2. Every connector reports pagination, source cap, coverage, checkpoint, failed pages and conservation.
3. A frozen fixture proves Russian morphology/query expansion, cross-source deduplication, event-time ordering and decomposed scoring.
4. Real authorized fixtures prove account isolation and reconcile search/funnel totals to provider exports.
5. No signal directly creates Fact, FinanceEntry, Purchase, Campaign write or Profit result.
