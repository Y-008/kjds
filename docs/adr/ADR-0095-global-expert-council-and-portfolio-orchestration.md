# ADR-0095：全球跨境专家委员会与组合调度

| 元数据 | 值 |
|---|---|
| status | Accepted for incremental implementation |
| date | 2026-08-06 |
| task | BAS-205 |
| affects | BR-007 / BR-117 / BR-139 / BR-140 |
| decision owner | 经营负责人 |
| implementation owner | Agent Platform + Product + Risk |

## 背景

KJDS 已有十二个 Commerce OS 责任 Agent、全球来源覆盖合同、俄罗斯市场雷达、
Evidence、Approval、Permit、执行回读和 TeamAgent 演进门，但尚缺一份统一、机器可读的
全球专家编制与任务路由合同。已有角色名称不能证明专家已经在岗，也不能让单一
“超级 Agent”同时承担研究、复核、批准与外部执行。

经营负责人在 2026-08-06 冻结三项选择：AI 核心团队配真人专业复核；全球市场持续
研究、俄罗斯/Ozon 作为首个实战战区；总负责人拥有业务优先级与方案拍板权，高风险
动作继续双签并保持职责分离。

## 决策

1. 建立一名 `global_chief_commerce_officer` 与十二个有界专家席位。总负责人负责目标、
   优先级、内部预算、WIP、冲突裁决、继续/暂停/退出和最终业务取舍；它可以随时 Stop，
   但不能在硬 Gate 失败时强制 Go。
2. 团队采用 `ai_core_human_professional_review`。AI 席位形成研究、分析、方案、草稿和
   任务路由；法务、税务、认证、财务、关务、母语、质量、安全与发布等专业结论按任务
   和风险级别绑定真人复核。未绑定当前真人 Owner 的席位只能处于 proposal/shadow。
3. 全球范围采用 `global_research_russia_ozon_execution_first`：任何国家和平台均可进入
   L0/L1 研究；俄罗斯/Ozon 是唯一可申请 L2 受控只读和后续 L3 Gate 的组合；
   Wildberries、Yandex Market 及其他区域在独立准入前不得继承 Ozon 身份、字段或权限。
4. 新增深模块 `GlobalPortfolioOrchestrator`。外部 Interface 只有：
   - `snapshot()`：返回版本化团队、权责、俄罗斯战区和控制边界；
   - `route(...)`：把已存在的任务引用编译为 `ExpertTaskContract` 与决策/复核路线。
5. `ExpertTaskContract` 固定包含任务引用、任务类型、market/platform、风险等级、
   Evidence 引用、总负责人、唯一 Accountable 专家、咨询席位、独立复核、人类专业复核、
   SLA、业务决定与动作批准边界、阻断和确定性哈希。模块不接收或保存凭证、客户原始
   数据、银行资料或平台正文。
6. L0/L1 内部研究、草稿与可回滚建议可由总负责人拍板；L2 只允许既有授权下的受控
   读取；L3 外部写必须有人类 Business Owner 与独立 Approver 双签，并重新通过相关
   财务/合规/风险 Gate；L4 付款、合同、法律结论、账户权限与密钥只能由相应人类权威
   决定。协调者永不签发 Permit，也不持有平台凭证。
7. 本模块只做确定性路由，不建立第二套 Product、Fact、Finance、Evidence、Task、
   Approval、Permit 或审计账。持久调度继续复用既有 OperatingTask/Decision/Gate/Outbox；
   首个切片不自动创建任务、不记录决定、不执行外部动作。

## 十二个专家席位

1. 全球市场与国家策略；2. 商品与类目组合；3. 平台与渠道运营；4. 采购、供应商与质量；
5. 物流、关务与履约；6. 财务、资金与真实利润；7. 法务、税务、合规与知识产权；
8. 本地化、内容与客户体验；9. 增长、广告与商业；10. 产品管理与客户成功；
11. 数据、Evidence 与 AI；12. 系统架构、工程、安全与发布。

独立 Verifier、Approver、Risk、Executor 和真人专业复核是控制角色，不与十二个专家席位
合并，也不由总负责人代签。

## 首个可验收切片

- 机器注册表精确表达已选择的团队形态、全球/俄罗斯范围、十三个角色、决策等级、任务
  路由、真人复核与协作节奏。
- `GlobalPortfolioOrchestrator` 对注册表漂移、重复角色、缺少独立复核、总负责人越权、
  非俄罗斯高风险执行和未知任务类型失败关闭。
- 认证只读接口返回团队快照；认证路由接口只返回 proposal-only 的确定性任务合同，
  匿名/越权失败关闭。
- 单元测试覆盖全球研究、俄罗斯/Ozon L3 双签、非俄罗斯 L3 阻断、L4 人类权威、
  确定性哈希和注册表负向校验。

## 未被本 ADR 证明的事项

合同落地不证明真人专家已经聘任、任何持证意见已经取得、俄罗斯 Gate 已通过、第二国家
或第二平台已接入，也不证明真实订单、结算、银行到账或 Actual Cash CM3。上述状态继续
由实名 Owner、原始 Evidence 和现有 Gate 决定。

## 后续加深：LG-001 团队总控塔

在专家编制之上增加 `TeamControlTower` 深模块，外部只保留两个 Interface：

- `brief(principal, entity_scope, store_ref, as_of)`：在任何经营任务读取前复验 exact scope，
  把四条用户主线、当前 A–L 泳道、既有 OperatingTask 和专家路由编译成一张老板摘要；
- `advance(..., continuation, result, rationale, evidence_ids, idempotency_key)`：只推进当前摘要
  中唯一的状态绑定动作，结果限于 take/done/blocked/escalate/stop。

曾比较三种设计：内部事务型 `pursue/contribute/project`、通用 Command/Query、老板型
`brief/advance`。最终选择第三种作为外部接口，将第一种的状态机、Evidence、幂等、WIP、
职责分离与失败关闭规则放进模块内部；通用命令总线因增加第二调度抽象和老板操作复杂度
未采用。

LG-001 只复用现有 OperatingTask/Event，不占用新的数据库迁移租约，不建立 `team_tasks`
或另一套决定账。它不提供暂停权威、预算批准、Fact 晋升、Permit 或外部 Executor；真正
高风险动作仍须走既有 Approval/Permit/Outbox/Readback。首个切片的并发幂等依赖现有事件
账查询，未来若进入多进程高并发写入，必须在权威账内增加唯一约束与同事务 Outbox，不能
另起旁路账。

## 2026-08-07 决策加深：LG-002 Top1 大型团队总控

### Interface 再比较

| 设计 | 价值 | 代价/决定 |
|---|---|---|
| 最小 Interface：直接给 `brief` 增加五个投影 | 延续现有调用方、最少权限面、最深失败关闭 | 采用为外部合同 |
| 可扩展 Campaign：新增 `campaign_ref` 或 Campaign CRUD | 未来多国家/平台可复用 | 当前只有一个正式首战区；会提前制造第二调度概念，延后到第二个正式战区出现 |
| 老板 Command Deck：新增独立聚合 Wrapper | 首屏组织、现金、阶段、差距、Gate 很直观 | UI 信息架构被吸收；不新增后端 Module 或 Interface |

最终选择是“最小外部 Interface + 注册表驱动的内部 Campaign + Command Deck Web 布局”：
后端仍只有 `brief/advance`，Campaign 只是 `TeamControlTower` 的不可变投影定义，不接收
`campaign_ref`，不建立 Campaign 表、任务账或组织账。第二个正式国家/平台出现且有独立
规则、身份、财税物流与退出 Gate 后，再复审是否需要公开 campaign selector。

### 组织、Benchmark、现金与 Gate 依赖

- 组织注册表精确冻结 18 个核心角色、现有 12 个 AI 席位、20–40 人专家池容量目标和 5 个
  独立控制角色。注册表是组织合同，不是任命事实；`verified_active` 必须同时具备主责、
  不同替补、任命 Evidence、专业作用域 Evidence、冲突证明、预算上限与最大损失。
- `StrategicBenchmarkKernel` 通过依赖注入只读。总控只选最新唯一同 scope snapshot 和与
  selector 精确匹配的既有 group，不重算 value、leader 或 rank；少于五个合格 peer 时只可
  `PARTIAL`，stale/duplicate/authority drift 分别显式失败关闭，所有输出固定
  `global_top1_claim=false`。
- 13 周现金在缺期初银行余额、CashPlan、批准 FX、签署现金底线或最大损失时不调用预测。
  财务 Benchmark 的 withheld projection 可以证明“存在受控来源”，不能变成可展示金额。
- 90 天日历、泳道 `state` 和 OperatingTask 完成均不能产生 Gate PASS。五个 Gate 只显示
  已有权威状态和缺口；正式 PASS 仍由现有组织、俄罗斯经营、工程发布、C0 和 Benchmark
  审计权威给出。

五类投影各自生成 SHA-256，并与 scope、A–M 泳道、四条 flow 和冲突一起形成
`decision_basis_sha256`。continuation 绑定该基线，人员、现金、Benchmark、Gate 或泳道任一
变化都会让旧动作失效。该设计不增加数据库表或迁移；BAS-204 继续独占迁移 `0096`。

### 失效条件

若第二正式战区需要同时运行、现有 OperatingTask/Event 无法在多进程下提供权威幂等、
Benchmark 公开新的稳定 selector 协议，或真人 Owner 批准不同组织形态，则重新提交 ADR。
在此之前不得以“可扩展”为由新增 Campaign CRUD、平行任务账、静态排名或猜测性现金层。

## 2026-08-07 决策加深：LG-003 权威驱动的 Campaign 调度

LG-002 证明了五类总控投影可以在同一 `brief/advance` Interface 内失败关闭，但四阶段关键
路径仍只是注册表日历，俄罗斯经营 Gate 也没有接入已存在的订单—结算—银行三账权威。
本次比较了三种运行设计：新增 Campaign CRUD/表、把阶段伪装成新 flow、以及在深模块内部
把阶段编译为现有 OperatingTask/Event。前两种分别制造第二调度真源和混淆经营 flow 与战役
阶段，因此选择第三种。

首阶段的 `start` Event 只有在 exact scope Evidence 已验证后才成为 kickoff 真源；实际战役
日从该 Event 的 `occurred_at` 计算。阶段任务的 `open/acknowledged/in_progress/resolved` 只表达
协作进展，日历到期和 `resolved` 均不能产生 Gate PASS。没有与五个交付 Gate 精确匹配、同
scope 的 canonical authority 时，总控保持 `formal_gate_pass=false`，也不自动打开下一阶段。

俄罗斯现金闭环通过构造注入只读 `ScopedSettlementCashWorkspace`。总控只消费其 exact-scope
控制合同、状态、计数和 cycle 状态；仅当同一 cycle 具备订单 Fact、平台结算、银行现金、
`reconciled` 与 Actual Cash CM3 时，投影“至少一个真实 SKU 现金闭环”为 `VERIFIED`。原始金额、
订单号、结算号和银行标识不进入老板摘要；该投影不构成 13 周现金、现金底线、最大损失或
正式 Gate 权威。

此次仍不新增 Interface、表或迁移。若未来出现精确匹配五个交付 Gate 的现有 authority，
通过新的只读依赖缝接入；不得把全局/非 exact-scope Gate、Harness M0–M4、任务完成或日期状态
重命名为正式 PASS。

运行时使用两类哈希：完整投影哈希保留 `as_of` 和原始权威快照引用用于审计；continuation
绑定的决定语义哈希去除纯观测时间和上游 cutoff 噪声，但保留任务/Event、状态、计数、
Benchmark leader refs、三账 reconciliation/profit snapshot 语义与 Gate readiness。否则两个
相邻 HTTP 请求只因毫秒时间差就会让 continuation 永久 stale。时钟刷新不得失效动作，业务
权威变化必须失效动作。
