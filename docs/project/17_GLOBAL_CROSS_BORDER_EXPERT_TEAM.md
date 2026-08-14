# 全球跨境电商专家团队运行合同

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-OPS-017 |
| owner | 全球跨境经营总负责人（待绑定真人） |
| status | Active contract; proposal/shadow until human bindings pass |
| version | 1.0 |
| reviewed_at | 2026-08-06 |
| related_adr | ADR-0095 |

## 1. 组织模型

团队采用“全球职能中枢 + 国家战区 Cell”：全球中枢维护共同 Product、Evidence、Profit、
Approval、Permit、Agent 与平台 Adapter 规则；国家 Cell 只增加当地市场、平台、语言、
税务、认证、支付和物流适配，不复制经营真源。

当前组合固定为：全球市场均可研究；俄罗斯/Ozon 是首个实战战区；Wildberries 与
Yandex Market 只进入来源合同和准入研究；其他国家/平台在独立 Owner、规则包、身份、
样本、财税物流与回读 Gate 齐备前保持 research-only。

## 2. 总负责人

`global_chief_commerce_officer` 是全局调度与业务裁决角色：

- 决定北极星、季度结果、内部预算、最大损失、优先级和每泳道 WIP；
- 指派唯一 Accountable 专家，解决跨职能冲突，决定继续、暂停、降级、转向或退出；
- 汇总事实、推断、备选方案、反方意见、UNKNOWN、失效时间和最大损失；
- 可随时 Stop/Kill；只有所有硬 Gate 通过后才能签署业务 Go。

总负责人不得自提自审、自行晋升 Fact、修改财务账或 Evidence、签发 Permit、持有平台
凭证、替代律师/税务/认证/财务结论，或绕过独立 Approver/Executor。总负责人在系统中
以 AI coordinator 运行时，必须绑定当前人类 Business Owner 才可进入 active；未绑定时
只能形成 proposal/shadow 产物。

## 3. 专家委员会

| 专家席位 | 唯一责任 | 典型真人复核 |
|---|---|---|
| 全球市场与国家策略 | 国家、需求、竞争、宏观、进入/退出假设 | Country Lead、当地市场专家 |
| 商品与类目组合 | SKU、类目、价格带、商品身份与组合去留 | 类目负责人、商品负责人 |
| 平台与渠道运营 | Ozon/WB/Yandex 等平台规则、店铺、Listing 与运营日历 | 平台 Account Owner |
| 采购、供应商与质量 | 三报价、样品、验厂、包装、质检与供应风险 | 采购负责人、质检人 |
| 物流、关务与履约 | TN VED/HS、清关、FBO/FBS、仓配、退货与逆向物流 | 报关/物流专家 |
| 财务、资金与真实利润 | 十五项成本、FX、结算、银行、现金与 Actual CM3 | 财务 Controller、资金负责人 |
| 法务、税务、合规与 IP | 主体、合同、税、EAEU/EAC、标签、制裁、隐私、商标 | 执业律师、税务/认证专家 |
| 本地化、内容与客户体验 | 俄语/当地语言、Listing、媒体、客服和消费者表达 | 母语复核、客服负责人 |
| 增长、广告与商业 | 定位、流量、广告实验、销售、伙伴与商业转化 | Growth/平台投放负责人 |
| 产品管理与客户成功 | JTBD、路线、工作区、Pilot、交付、采用、续费与退出 | 产品负责人、客户成功负责人 |
| 数据、Evidence 与 AI | 来源、覆盖、血缘、指标、模型、Skill、eval 与时效 | Data Steward、独立 AI Reviewer |
| 架构、工程、安全与发布 | 系统 Interface、Adapter、IAM、SRE、QA、恢复和发布 | 架构、安全、Release Auditor |

独立 Verifier、Approver、Risk、Executor 不计入上述席位，必须与产物作者和总负责人保持
独立身份。法务/合规、财务、风险安全、QA/Release 和战区执行条件拥有“只可阻止、不可
强制放行”的硬 Gate 权。

## 4. 俄罗斯首战区

俄罗斯 Cell 由 Russia Theater Lead 负责，至少绑定 Ozon Channel、Russia Market
Intelligence、RU Legal/Tax/Customs、EAEU/EAC/标签、Finance Controller、Supply &
Fulfillment、Native Russian Content、Growth & Customer Operations 八类职责。

首要退出条件仍是：三个真实候选五指标与双来源、三报价、三类 Passport；至少一个 SKU
完成订单—平台费用/结算—银行到账—人民币 Actual Cash CM3；随后完成 14 天 Shadow、
独立复核、有限 Permit、回读、回滚与人工接管。未满足时任何专家结论都只是建议。

## 5. 决策与协作节奏

| 节奏 | 输出 |
|---|---|
| 每日 15 分钟 | Gate、blocker、Owner、SLA、预算/最大损失和下一唯一动作 |
| 每周一 | 总负责人冻结不超过三项核心结果及停止条件 |
| 每周中 | 俄罗斯准入、利润真相和商业 C0 Gate Clinic |
| 每周五 | Evidence、失败、UNKNOWN、结果回写与下周取舍 |
| 每月 | 全球国家/平台组合、规则、产品和资本配置复审 |
| 事件触发 | 制裁、法规、平台费率、安全或供应中断即时升级 |

所有 Agent handoff 通过同一 `ExpertTaskContract`，不得用自然语言头衔替代任务引用、
作用域、Evidence、预算、时限、验收人和独立 Reviewer。所有决定包必须保留反方意见、
未知项、最大损失、停止条件、失效时间和确定性哈希。

## 6. 当前状态

- 团队编制与机器合同：已冻结。
- AI 专家席位：可用于 proposal/shadow 路由。
- 真人 Business Owner 与持证/专业复核：待实名绑定。
- 俄罗斯准入、真实订单、结算、银行到账和 Actual Cash CM3：沿用现有 Gate，未被本合同放行。
- 第二国家/第二正式平台：research-only。

## 7. 团队总控塔

`TeamControlTower` 把本合同从“专家名册与任务路由”加深为工程可操作的协作闭环。老板端
只看 `brief`，其中固定显示四条主线、当前阻断、责任人、WIP/写域冲突与唯一下一动作；
Operator 只通过 `advance` 领取、开始、完成、阻断、升级或停止该动作。每次推进绑定当前
tenant/entity/store/authority hash、opaque continuation、理由、Evidence 和幂等键。

它复用 OperatingTask/Event，不证明真人到岗，不代替总负责人或专业权威，也不批准预算、
合同、支付、采购、发布和平台写入。完整老板运行节奏、企业搭建次序与商业化路线见
[18_TEAM_CONTROL_TOWER.md](18_TEAM_CONTROL_TOWER.md)。
