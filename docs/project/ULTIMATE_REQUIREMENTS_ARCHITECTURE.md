# KJDS Ultimate Requirements Architecture

Status: Start-Gate source of truth  
Baseline: `b34a3a7`, `feature/batch-opportunity-mining-059`  
Observed at: 2026-07-27 Asia/Shanghai

## 1. Canonical semantics

六层严格隔离：

1. Observation：公开页/API/导出的时间点观察，不是事实或销量；
2. Fact：自然键、作用域、Evidence 与有效期完整的当前事实；
3. Inference：模型/规则计算，带版本、置信度和输入哈希；
4. Decision：Owner、预算、理由、替代方案与独立审批；
5. Execution：冻结计划、one-time Permit、Readback、Kill Switch、Compensation；
6. Settlement：应计、结算和到账三本账。

四种贡献视图不可互换：一个情景估算 + 三本实际账：

- Scenario CM3：预上市/实验的 evidence-bound estimate；
- Actual accrual：delivered/returned 后的订单与费用应计；
- Settled contribution：平台结算单已对账但尚未确认银行到账的结算贡献；
- Actual Cash CM3：对账且到账后的现金贡献。

无完整证据不得显示“实际利润”。

## 2. Bounded contexts 与 deep modules

| Context | Deep module / authority | 不负责 |
|---|---|---|
| Identity | Exact Product + Variant Identity | 模糊匹配升级事实 |
| Market Intelligence | Observation/Cohort/Price Index | 把评论伪装销量 |
| Supply Intelligence | Checkout/RFQ/Pareto/Landed Cost | 最低展示价即最优 |
| Profit | 15-component CM3 / FX / erosion | 前端重算、猜分摊 |
| Passport | Product/Quality/Compliance | 绕过禁限售/品牌权利 |
| Content & Media | Draft/Lineage/QA/Manifest | 复制竞品素材 |
| Rule Advantage | Registry Compiler/Impact | 硬编码与 registry 双真源 |
| Seller OS | Axes/Strategy/Envelope/Portfolio | 套餐降低真相 |
| Operations | OperationsQueue/OperatingTask/Event | 第二套工作流引擎 |
| Execution Authority | Approval/Permit/Readback/Kill/Compensation | 默认自动发布 |
| Orders & Settlement | Order/Return/Accrual/Cash | 用预估替代到账 |
| Evidence & Audit | immutable Evidence/Lineage/Audit | 可变证明 |

## 3. Rule Compiler 决策

选择方案 A：effective Rule Registry 是规则唯一真源，Evaluator 从当期 facts
编译；代码只实现通用解释器和类型约束。`as_of` 必须选择完整且无重叠的有效域。
缺域、未来未生效、已过期或来源 Evidence binding 缺失时 fail-closed。

每条规则绑定 country/locale/domain/category/mode、effective interval、
source URL、source observed_at、source content SHA256、Evidence ID、confidence。
read-only research 可在来源待复核时标 partial；candidate score 不得精确化；
Pilot Approval 和 external publish 都必须阻止。

Rule Impact 使用同一 `as_of` 编译 previous/current effective sets：

- 当期差异 → changed domains → 仅命中绑定域的 affected SKU；
- 未来规则 → `scheduled_change/effective_at`，不提前改变当前 readiness；
- 原 run 固化 registry hash、compiled policy hash 与 inputs，可重放不漂移。

Ozon Global CN 与 RU local registry 物理/逻辑隔离。

## 4. Exact identity、市场和供应

Market cohort key = canonical product identity + exact variant。先去重当前事实，
再聚合 external competitor cohort。Own listing 与 external competitor 永不混合：

- 已有 SKU 收入场景取 own listing/buyer price 当前观察；
- 新 SKU 输出 `proposed_price_scenario`，明确 estimate，以可比价格带和利润底线验证；
- competitor 只用于行情与 Price Index。

供应保留全集。`observed_checkout_price` 必须冻结 `price_scope`：

- `unit_price`：displayed = unit；
- `checkout_total`：unit = displayed / observed quantity；
- DB 约束正数及数量守恒。

比较数量来自冻结 Pilot Policy/request（首批 1–3），不是供应样本投票。只有精确
数量可购买、MOQ 允许、税费与国内运费边界完整的选项进入 risk-adjusted landed
cost/Pareto。未知运费/税费为 no_data 或保守区间，绝不按 0。RFQ、checkout
观察、Supplier Offer 与 actual procurement cost 保持不同 authority。

## 5. Profit kernel

维度：tenant/entity/store/product/SKU/order/accounting_date/currency/FX date。
仅按明确自然键/绑定归集；无法映射进入 unallocated/blocked，禁止按销售额猜分摊。

侵蚀桥覆盖采购、采购缓冲、国内物流、包装、国际物流、关税、佣金、末端履约、
仓储/库龄、广告、退货退款、折扣促销、税费、FX、损耗和未分摊。Decimal、
显式币种、汇率日期；组件和 CM3 守恒且不重复计入。

佣金按 category + Global CN mode + price band + order date 的有效 Evidence row。
缺精确行只能做宽区间 screening，不输出精确优势。

## 6. Tenant/entity/store 与权限

所有 business object 的首级作用域为 tenant，随后 entity/store。Principal 由
服务端认证映射 tenant/store scope；URL/body 不能扩大。跨店 external market
观察可共享但 own listing、决策、执行、订单、结算严格隔离。

主体 scope 采用 ADR-0034 的 append-only grant/revoke authority：Principal 不携带也不
推断 entity；只有独立治理身份依据 A 级 Evidence 建立的有效 tenant/entity/store/actor
grant 才能在 `as_of` 解析 `entity_ref`。事件保留 Evidence hash、request hash、
effective/recorded time 和撤销历史；缺失、歧义、损坏或撤销均 fail-closed。grant 只能
补充主体权威，不能扩大 Principal 的 tenant/store 边界。

RBAC + SoD：

- operator 不能批准自己的外部写；
- approver 不持有执行密钥；
- executor 只消费 frozen command + one-time Permit；
- finance reviewer 独立确认 accrual/cash；
- API key 按最小角色和 IP CIDR 拆分；
- 禁止 Cookie/localStorage/internal API 作为平台连接权威。

## 7. Strategy/Entitlement registry

Strategy Pack 采用 append-only version artifacts + index：有效区间不重叠，
`as_of` lookup、artifact SHA256 和 run hash 固化。过期/未来版本不可用于当前决策。
商业价格标 `hypothesis_internal_preview_not_for_sale`。

安全不变量与商业 entitlement 分离。全套餐共享：

- initial Pilot units max = 3；
- independent approval、one-time Permit、Readback、Kill Switch、Compensation；
- 相同事实、利润和 Evidence 内核。

套餐只提供 post-readback/settlement 的 scale envelope。

## 8. API、事件与失败恢复

写 API 要求 idempotency key + request fingerprint；同 key 不同 payload 返回 conflict。
分页使用稳定 keyset cursor；大扫描使用 page/shard + cheap conservative prescore →
full evaluate top-K。任何 prescore unknown 不得因 0 成本乐观进入前列。

关键事件 append-only：ObservationCaptured、CandidateEvaluated、
ApprovalAllocationSelected、ApprovalDecided、PermitIssued/Consumed、
ExternalCommandReadBack、Order/ReturnObserved、AccrualRecorded、
SettlementReconciled、CashReceived、RuleVersionActivated。

事务边界使用 outbox；consumer 以 event id/aggregate version 幂等。Lease 任务支持
超时回收，失败保留 Evidence、attempt、error code 和 compensation state。
不引入第二队列、Redis/Kafka/Temporal 作为 0.59 前置。

## 9. Evidence、审计与 AI authority

Evidence 记录 source、source_ref、content hash、observed/effective time、grade、
retention、tenant/store scope 和 lineage。Decision/Execution/Settlement 引用冻结
Evidence IDs，坏 Evidence fail-closed。审计不可变，所有 override 有 actor/reason。

AI 可以：摘要、匹配建议、俄语 draft、异常解释、替代方案与测试生成。
AI 不可以：把 Observation 升级成 Offer/actual、编造销量/成本/权利、绕过验证码/
条款/限流/IP、批准自身建议、生成 Permit 或跳过 Readback。

内容工厂权威链：

`Passport + rights-bound supply facts → category schema → terminology/forbidden`
`→ versioned draft → fact/Russian/IP/similarity/media QA → independent approval`

当前简单拼接仅 `draft_capability/blocked`。

## 10. no_data、失败和 NFR

每个 workspace 返回 loading/ready/partial/no_data/blocked/error/forbidden/stale；
全局状态不能吞掉动作级 readiness。失败提供 Owner、SLA、missing Evidence、
retry 与下一 workspace。离线不使用演示数据。

NFR：

- 金额 Decimal，确定性时钟和 as_of 重放；
- PostgreSQL 单一 Alembic head、空库 base→head；
- immutable ledger/event，RLS/tenant scope；
- API 匿名 401、越权 403；
- 390px `scrollWidth === innerWidth`；
- OpenAPI snapshot 与运行时一致；
- secret scan、ruff、全 pytest、Web test/build、diff-check；
- 容器 PostgreSQL/API/Web/worker 健康。

## 11. 迁移、兼容与回滚

Observation 1.1 新增 price_scope/unit_price；升级先回填 legacy displayed=unit，
移除 server default，再加正数与守恒 CHECK。候选 key 新版包含 exact variant；
旧记录保留原 Evidence，但必须重新 capture/derive 才可进入 1.1 cohort。

旧 `pilot_eligible/pilot_selected/eligible_waitlist` 仅保留 deprecated read alias，
canonical 为 `eligible_for_approval/approval_allocation_selected/approval_waitlist`，
不得双写或独立漂移。

迁移必须支持 downgrade→upgrade 回放；失败时停止新 run，保留旧 Evidence/export，
不删除账本或让在途外部命令继续。

## 12. E2E acceptance matrix

Start Gate 必须证明合同可实施：

1. 同 identity 错 variant 不聚合；Store B 新数据不覆盖 Store A；
2. own price 不被 competitor median 冒充；
3. 100/100/3 数量时三件 Pilot 不使用百件阶梯价；
4. 运费/税未知不按 0 排序；
5. 价格 index 阈值变更实际改变 evaluator；
6. 未来规则生效前仅 scheduled，生效日才影响绑定 SKU；
7. 同规模不同 ops/brand/risk 改变策略而 scale 不变；
8. 无 Portfolio snapshot 四桶 no_data；
9. allocation selected 不等于 Approval/Permit/Pilot；
10. 租户/店铺越权 403、匿名 401；
11. 规则来源 Evidence 缺失阻止 Pilot Approval/publish；
12. 失败/空数据/移动端不造演示事实。

Closed contract evidence: `_portfolio()` keeps incomplete Actual Cash CM3,
confidence, return, fulfillment or settlement facts in `unclassified/no_data`;
unclassified items receive no allocation and cannot establish a Portfolio snapshot.

Release Gate 另要求真实 Pilot、订单、退货、结算、到账 CM3；Start APPROVED 不代表
实现、商业化或盈利已完成。

## 13. Implementation dependency waves

依赖顺序为 M0 Truth/Governance → M1 Intelligence/Candidate →
M2 Content/Approval/Pilot → M3 Order/Settlement/Portfolio →
M4 Enterprise/Commercial。后波不得复制或绕过前波 authority。

每个 read model 的最小 query contract：

`tenant_ref + entity_ref? + store_ref(s) + from/to + timezone +`
`display_currency + fx_policy/date + source grades + freshness`.

Source adapter 等级：Seller API、official export、authorized connector、
allowed public observation。每个 adapter 声明 ToS/robots/rate/region/privacy/
revocation；不可访问时返回 no_data。禁用 Cookie/localStorage/internal API、
验证码绕过、评论→销量、跨店 own fact 混合、客户端 CM3 和无 Evidence 趋势。

Agent port 必须声明 input fact types、output artifact schema、允许的自动动作、
required human gate、eval dataset/metric 和 fail semantics。Approval 与 Permit
authorities 不能作为 Agent tool 暴露给 proposer；execution Agent 只能消费已签发
且精确绑定 frozen plan hash 的一次性 Permit。

## 14. 市场基线完整性与 AI 化合同

竞争能力 Registry 必须把毛子、荔枝、芒果店长、店小秘、妙手、无忧易售、
Seerfar 与 LinkFox 标为 `must_have_native_parity`。每个观察能力只能处于：

- `verified_native`：原生深模块已通过代码/DB/API/Web/权限/运行 Evidence；
- `implemented_unverified`：已实现但尚未取得完整运行或业务验收；
- `planned`/`gated`：明确缺口，进入 M0→M4 依赖图；
- `prohibited_with_safe_replacement`：旧实现方式被拒绝，但同一 JTBD 有安全替代。

禁止 `mapped` 自动升级为 `implemented`，禁止以供应商数量、营销口号、页面菜单或
Agent 自述作为市场事实。Provider 只贡献 C/D 级能力观察；KJDS runtime 不能依赖
其 Cookie、localStorage、私有 API、宽域扩展、静态费率或未核权媒体。

每个原生 ERP bounded context 必须暴露 Agent port 与 verifier port。Agent 输出先是
版本化 artifact，经 deterministic/schema/rule/Evidence/Harness verifier 后才可进入
下一状态；状态栏和 Graph 节点只接受 verifier Observation。基础功能覆盖率与 AI
增强质量是两个独立指标，后者不得掩盖前者缺口。
