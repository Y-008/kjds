# KJDS 利润优先跨境 Commerce OS：2026-08-02 完整沟通与决策记录

| 元数据 | 值 |
|---|---|
| record_id | KJDS-SESSION-20260802-PROFIT-FIRST |
| status | Active decision record |
| date | 2026-08-02 |
| scope | 战略、产品、数据、架构、研发、商业化与验收 |
| source | 当日连续沟通、仓库复核与最终实施授权 |
| authority | 需求与决策留存；运行事实仍以数据库、代码、迁移、测试和 Evidence 为准 |

> 本文保存今天所有具有实质意义的沟通内容和最终决策。重复的“继续”被归并为连续深化指令，不逐条制造无信息副本；凭证、Token、个人敏感信息以及未经证据验证的经营判断不写入文档。早先市场侦察记录保留用于审计，但其 CNY/RUB 混算结论已经失效。

## 1. 原始目标与连续深化轨迹

1. 以当前最新前沿技术重新梳理整体项目，从全链路、全方位、多维度、多层次、多角度设计战略方向，目标是形成利润可持续、适配不同量级卖家的跨境电商软件领先能力。
2. 不设置没有必要的数据入口限制。数据要全量采集、全量留存，再按质量、权威、时效、身份、币种和用途分级；低质量数据不删除，但不能未经验证参与高风险经营动作。
3. 优先复用成熟开源与现有模块，不为架构完整感自造 Kafka、Temporal、向量数据库、第二套 ERP 或第二套事实源；不按固定 90 天工程排期，按可验收 Gate 连续交付，先做能止损、能验证利润、能尽快产生现金价值的功能。
4. 全量数据进入数据库，ERP 明确展示有利润款、亏损款和证据缺口；历史数据持续留存，用于后续归因、模型评估、供应商评估、库存与现金周转分析。
5. 从多年跨境卖家、大卖、俄罗斯市场架构师、全球跨境架构师、AI Agent 专家、产品经理、市场研发、运营专家和企业经营者视角复核。共同优先级是：现金与真实利润、商品与变体身份、供应链确定性、库存周转、平台与合规风险、数据可信度、可执行的止损和小额试错，而不是功能数量或模型名称。
6. 数据大屏必须支持多模块树形结构和多页签，从集团/租户逐层穿透到国家、平台、店铺、类目、SPU、SKU、订单、费用、结算、库存、供应商、算法输入和原始 Evidence；前端不得自行计算利润或虚构趋势。
7. 大屏要覆盖转化率、ROI、现金利润、风险利润、库存占资、退货、广告、达人和优惠成本，并支持从经营总览进入单个利润商品详情、订单费用明细和供应商报价。
8. 增长侧增加俄罗斯多平台能力，特别是 VK 推流/引流、Telegram 会话与订阅触达、深链、优惠码、达人和福利螺旋；优化目标不是曝光或表面 ROAS，而是退款、结算和到账后的增量现金 CM3。
9. 产品采用同一经营内核覆盖个人、小白、小团队、中型卖家、大卖和企业。套餐只改变配额、自动化程度、审批复杂度、组织治理和 SLA，不通过维护多套业务代码制造分叉，也不限制用户导出自己的全量数据。
10. 输出形态需要同时具备可交付研发版、对外路演架构话术、内部决策路线图和面向大卖/企业的商业价值清单；最终指令是切换到目标开发模式并直接交付代码。
11. 对“是否最前沿、是否使用最强模型”再次复核后的结论：模型能力重要，但断层领先来自可信经营事实、利润闭环、执行治理和复盘学习。强模型只用于跨语言理解、规格匹配、竞争推演、风险反证和策略生成，金额、库存守恒、权限、审批、Permit 和平台写入必须由确定性代码控制。

## 2. 最终战略北极星

KJDS 的主链路确定为：

```text
全量原始数据
  -> 可信经营事实
  -> SKU 风险利润
  -> 止损 / 调价 / 选品
  -> 小额 Pilot
  -> 订单 / 退货 / 结算
  -> 实际现金利润
  -> VK / Telegram 增长复投
  -> 模型与规则复盘
```

系统不承诺“必然盈利”。系统必须保证：币种不一致、证据不足、变体冲突、悲观利润不达标或实际现金链路未闭合时，不建议扩大采购、广告、补货或自动上架。

## 3. 当日 P0 复核结论

- 当前 `output/market_recon/full_product_info.json` 中 18 个 Ozon 商品售价为 CNY，市场参考价为 RUB。
- 旧 `scripts/build_market_recon_report.py` 将商品价格直接命名为 `retail_rub` 并与 RUB 市场价比较，导致旧报告的利润、调价和机会排序结论失效。
- `finance_by_month.json` 的部分金额没有随记录提供可验证币种字段；不得仅凭平台或文件名猜测为 RUB。
- 1688 供应数据保留了完整价格信息，但部分记录缺显式币种和精确变体语义；必须入库并进入 quarantine，不能直接形成 SupplierOffer、actual cost 或 Pilot 依据。
- 原始文件继续保留。错误报告标记 `invalidated`，不得作为 Dashboard、Agent 或经营决策输入。

## 4. 已批准的产品与研发范围

### 4.1 利润真相

- 引入 `MoneyAmount(amount, currency, occurred_at, evidence_id)`，裸金额不得进入新利润计算链路。
- 引入 `FxBasis(source_currency, target_currency, rate, effective_at, evidence_id)`，转换结果可回查汇率时间和证据。
- 商品售价、市场价、采购价、物流费、佣金、结算和银行到账保留原币种。
- `scenario_profit`、`accrual_profit`、`settlement_profit`、`cash_profit` 永久分开。

### 4.2 全量数据入库

- 唯一深模块为 `MarketReconBundleIngestion`，复用现有 Evidence、Observation、Catalog、Fact 和 Import 权威，不建设第二套数据真相。
- 首批目标：18 个 Catalog SKU、18 个商品详情、2 个 Analytics 窗口、12 个 Finance 月度窗口、322 个 1688 供应品类及现有 Browser Capture。
- 五级状态：`raw_evidence -> normalized_observation -> reviewed_observation -> formal_fact -> decision_snapshot`。
- 解析失败、币种缺失、变体不明和身份冲突统一进入 quarantine，并保留原始文件、记录位置、错误码和修复入口。
- 永久守恒：`accepted + quarantined = source_total`；导入幂等，相同幂等键发生内容漂移必须冲突。

### 4.3 利润指挥中心与大屏

- 唯一 `ProfitCommandWorkspace` 组合现有批量机会、利润账本、库存、OMS、采购供应、结算和增长实验，不复制其算法。
- 每个 SKU 输出原币金额、展示币种、FX 证据、十五项成本覆盖、baseline/downside/CVaR、现金占用、退货风险、实际/预测/风险调整利润、数据等级、身份可信度、动作、责任人、预算上限、止损条件和 Evidence 下钻。
- 决策分类：`stop_loss / reprice / pilot / hold / exit / needs_data`。
- 每次可执行决策保存不可变 `ProfitDecisionSnapshot`，冻结输入哈希、算法版本、FX、证据、输出和失效时间，用于回放模型是否真的增加利润。
- Pilot 仅为 proposal；只有真实正 downside CM3 和必要证据齐全时才能提出。否则明确返回 `no_data` 或 `blocked`，不得伪造机会。

### 4.4 Agent 与可观测性

- 保留现有 OpenAI-compatible adapter 作为回退，在其后增加可替换 Runtime Adapter。
- 模型按任务能力、准确率、延迟、成本和单位利润贡献路由，不在业务代码硬编码某个模型名。
- OpenAI Agents SDK 只承担工具调用、Guardrail、Tracing 和 Evals；不成为业务事实源，敏感输入输出默认不进入 trace。
- OpenTelemetry GenAI 记录 Agent、工具调用、Token、成本、延迟、错误和业务结果，工具参数脱敏。
- MCP 继续作为工具边界；实验任务机制不能替代 PostgreSQL 任务权威和现有 Agent Harness。

### 4.5 VK、Telegram 与福利螺旋

- 建立统一 `GrowthChannelPort`，分别提供测试 Adapter 与官方生产 Adapter。
- 统一归因链：`impression -> click -> deep_link -> conversation -> add_to_cart -> order -> refund -> settlement -> cash_cm3`。
- 每个用户、创意、渠道、SKU、深链和优惠码使用稳定归因 ID。
- 奖励先计提，退货窗口结束且结算后确认；奖励、广告、达人和渠道费用全部进入 SKU 实际利润。
- 防自买、重复设备、批量账号、退款套利和跨渠道重复归因；达到止损、退款或投诉阈值自动暂停并进入人工复核。
- Telegram 仅向主动订阅或已发起会话的用户触达，生产 Adapter 缺少授权、凭证或同意记录时失败关闭。

## 5. 卖家分层与商业包络

| 客群 | 交付包络 |
|---|---|
| 新手/个人 | 手工确认、小批量、六项基础证据、单店利润、选品助手 |
| 小团队 | 多角色、批量导入、库存采购、增长实验、基础审批 |
| 中型卖家 | 多店矩阵、补货建议、供应商协同、渠道归因 |
| 大卖/企业 | 多主体、RLS、SoD、多级审批、预算中心、开放接口、审计、SLA |

所有层级共享商品、订单、利润、证据和执行治理内核；低价套餐不牺牲数据所有权和全量导出。

## 6. 基础设施与复用决定

- 当前盈利闭环继续使用 PostgreSQL 17、FastAPI、SQLAlchemy、Next.js 和现有 Graph/Harness。
- PostgreSQL 18 的时态约束、UUIDv7 和 AIO 作为后续升级候选，迁移回放和性能证据通过前不阻塞本轮。
- 不立即增加 Kafka、Temporal、向量数据库、Kubernetes 或第二套 ERP。
- 原始数据达到容量/查询阈值后通过对象存储 Adapter 做冷热分层，不改变 Evidence 上层合同。
- 优先复用现有 `BatchOpportunityWorkspace`、利润账本、OMS、库存、采购、供应、增长实验、Evidence 和 Agent inference seam。

## 7. 首批 API 与验收

```text
POST /v1/intelligence-ingestion/bundles/preflight
POST /v1/intelligence-ingestion/bundles
GET  /v1/intelligence-ingestion/bundles/{bundle_id}
GET  /v1/intelligence-ingestion/bundles/{bundle_id}/quality

GET  /v1/profit-command/workspace
GET  /v1/profit-command/candidates/{candidate_id}
POST /v1/profit-command/candidates/{candidate_id}/pilot-proposals
```

验收标准：

- 18 + 18 + 2 + 12 + 322 及 Browser Capture 全部有数据库留存或 quarantine 记录。
- 不存在新链路无币种金额或 CNY/RUB 直接运算。
- SKU 可从大屏穿透到利润组成、FX、订单、供应、风险和原始 Evidence。
- 实际、预测和风险利润在数据库、API 和 UI 中严格区分。
- 全量导入幂等；同键内容漂移冲突；精确变体冲突不得自动匹配但原始数据保留。
- 跨租户、跨主体、跨店铺在读取业务数据前隔离。
- Agent 不能晋升正式事实、批准自己、签发 Permit 或直接执行平台写入。
- 后端全量测试、迁移回放、OpenAPI、Web 测试/构建、桌面和 390px 下钻验收通过。

## 8. 默认决策与实施授权

- 第一战场继续为俄罗斯 Ozon，先恢复店铺盈利能力，再扩展 VK、Telegram 和其他平台/国家。
- 采用“全量采集、分级使用”，不以质量问题拒绝数据进入系统，只限制其决策权限。
- 不采用固定 90 天排期；按 Gate 连续交付，每个 Gate 验收后立刻进入下一闭环。
- 首个开发目标为“币种真相修复 + 全量数据入库 + 利润指挥中心”。
- 用户已明确授权直接开发上述计划，并要求把今天全部沟通保存。本记录是该授权和后续验收的项目内入口。

## 9. 外部技术依据

- OpenAI Agents SDK: <https://developers.openai.com/api/docs/guides/agents>
- OpenTelemetry GenAI semantic conventions: <https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/>
- Model Context Protocol Tasks: <https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks>
- PostgreSQL 18 release notes: <https://www.postgresql.org/docs/18/release-18.html>
- Telegram Bots: <https://core.telegram.org/bots>

这些链接只支持技术方向判断，不替代平台账户合同、结算、供应商报价或实际经营 Evidence。

## 10. 合并交付：数据全链路大屏与全量级卖家利润增长 OS

本轮把“数据全链路与全维利润可视化”和“全量级卖家利润增长操作系统”合并为同一
交付，不建设两个驾驶舱或两套利润算法。统一读链为：

```text
集团/租户 -> 国家 -> 平台 -> 店铺 -> 官方 L1/L2/L3/叶子类目
-> SPU/SKU -> 订单 -> 十五项费用 -> 平台结算 -> 银行到账 -> Evidence
```

利润总览只展示服务端冻结的实际现金利润、风险机会、亏损暴露、库存占资、最高价值
动作和数据质量；商品页展示每个 SKU 五套利润口径；详情页穿透原币金额、FX、十五项
成本、类目路由、订单、库存、结算、供应与原始证据；血缘页展示五级数据状态和隔离区。
不存在可复验历史序列时返回 `no_data`，不为图表制造增长曲线。

## 11. 店铺属性、官方类目与衍生类目决定

店铺经营属性新增：定位、铺货/精铺模式、价格带、目标区域、履约模式、增长渠道、
客户群、运营能力和官方类目路径。官方类目必须独立保存 L1、L2、L3、叶子 category ID
和 product type；重货、配件、易碎、季节、复购、高客单、礼品、内容型、组合装等是
衍生经营标签，只决定内容、库存、物流、投放和证据门，不得伪装成 Ozon 官方类目。

路由顺序固定为：明确排除优先，其次 exact leaf、exact product type、exact hierarchy；
仍不匹配就返回 `needs_category_data`。core/adjacent/experimental 分别映射主店、相邻类目
限量和仅 Pilot。跨店路由只给建议和替代项，不自动复制发布。当前店铺属性没有独立
确认，因此运行态保持 `no_data/unbound`，没有为展示效果猜测定位。

## 12. 不同段位卖家的利润最大化工程逻辑

- 新手不默认选择“无脑铺货”或“纯精品”。系统先按资金、能力、类目复杂度、证据和
  downside CM3 决定 `research/pilot/hold/exit`，通常从少量可验证 SKU 的精铺 Pilot 开始。
- 具备标准化内容、供应、库存和客服能力后，才可在低复杂度、身份明确、成本稳定的
  类目使用受控铺货；铺货数量不是成功指标。
- 小团队重点提高证据吞吐、供应商备份、库存周转、批量复核和增长实验效率。
- 中型卖家重点做多店角色分工、官方类目深耕、资金桶、补货和渠道增量现金归因。
- 大卖/企业重点做多主体隔离、预算中心、SoD、多级审批、SLA、开放接口和模型复盘。
- 各层级共享事实、利润和执行内核；Agent 负责非确定性理解、反证与策略草案，确定性
  代码负责金额、库存守恒、类目精确匹配、权限、审批和执行。

## 13. 本轮工程落点

- 新增 ADR-0085、BR-137、BAS-162 和机器可读店铺类目策略 Registry。
- 新增 append-only 店铺属性和不可变经营计划迁移 `20260802_0086`。
- 新增 Profit Command portfolio/analytics/candidates/lineage 与 Seller OS profile/plan/routing API。
- 新增 `/profit-command`、`/products`、单品详情、`/routing`、`/lineage` 五页大屏。
- 当前真实 Bundle 已写入 PostgreSQL：374 条守恒留存，18 个 SKU 全部投影，0 个 Pilot，
  实际现金利润保持 `no_data`，所有外部写关闭。

## 14. ZiAgent 并行续交付决定

本轮采用四个不重叠写域的 ZiAgent 并行实现，并由主线程统一组合：

| 工作流 | 深模块 | 经营目标 |
|---|---|---|
| 利润修复 | `ProfitDataRemediationWorkspace` | 把 374 条全量留存转为按损失、VaR、严重度和解锁价值排序的补证队列 |
| 店铺画像 | `StoreProfileIntake` | 仅凭 Evidence 提出主/次/三级/衍生类目角色，不猜店铺定位和变体 |
| 渠道增长 | `GrowthChannelPort` | 用 VK/Telegram 完整归因与 `incremental_cash_cm3` 控制奖励、退款和止损 |
| Agent 判断 | `GovernedAgentRuntime` | 按能力、评测、延迟、成本和利润价值路由模型，同时禁止事实/审批/Permit/外部写权限 |

普通用户读取历史 Bundle 时，当前 Scope Grant 只负责证明其仍可访问同一租户、主体和
店铺；Bundle 导入时的历史 Grant 哈希继续冻结为源数据血缘。两者独立展示，授权轮换
不得改写历史 Evidence，也不得因此放宽跨租户、跨主体或跨店铺隔离。

当前店铺画像只有 36 条 listing/category 观察，实际订单、流量、利润、结算、银行到账
和精确变体 Evidence 仍不完整。当前容器也未配置模型、VK 或 Telegram 生产账号。因此
系统应展示修复优先级和安全能力边界，而不是宣称已经产生利润或已完成自动投放。
