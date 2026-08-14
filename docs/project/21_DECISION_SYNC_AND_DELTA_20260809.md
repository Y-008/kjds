# KJDS 决策同步与版本差异（2026-08-09）

## 结论

KJDS 的唯一产品目标保持不变：做成一个 AI-native 的跨境经营工作台，覆盖选品、货源、
利润、素材、Listing、订单、履约、退货、结算和现金回流；Ozon、1688、拼多多、闲鱼等
仍然是外部交易或货源平台。竞争产品只用于能力对照，不引入第二套 ERP、第二套事实账、
第二套任务队列或第二套发布状态机。

当前交付顺序被重新锁定为：先闭合第一个真实 SKU/RFQ 与 Ozon 读回的现金利润事实，再把
同一工作台的递归店铺挖掘、内容、广告、库存和自动化能力逐步接入。高级架构不降级，只有
执行权限按 Evidence、Approval、Permit、Readback 和 Kill Switch 逐层放行。

## 与先前方案的差异

| 维度 | 先前表达 | 当前同步决策 | 升级点 |
|---|---|---|---|
| 经营模型 | 常见的“选品 → 上架 → 广告”线性漏斗 | 开放式经营策略图：货源、试销、搜索内容、媒体、价格、广告、库存、履约、退货、现金复投、退出均是可组合打法 | 从单流程变成可解释、可重排、可回放的经营图 |
| AI 角色 | 生成建议和文案 | AI 负责候选发现、抽取、匹配、解释和动作编排；确定性代码负责 SKU、币种、Decimal 利润、权限和门槛 | 把模型不确定性显式化，避免 AI 生成事实 |
| 自动化 | 未来“一键自动化”的笼统目标 | 门店总开关 + 每个打法独立复选框 + `manual_each_action/supervised_batch/policy_bound_autonomous` + 额度/有效期；默认全部关闭 | 从“自动化口号”升级为可逐步授权的自动化 |
| 人工控制 | 资讯可能直接改价、改广告或发布 | 资讯只生成现有 OperatingTask/OperationsQueue 中的待处理、建议售价、待改广告、待改 Listing、待补货/暂停/退出动作 | 保留人工判断，同时为后续自治留接口 |
| 货源判断 | 单个平台或展示价 | 1688、拼多多、闲鱼等独立 Provider 多家比对；公开观察、聊天 `unknown`、正式 RFQ 分层 | 不因不报价而伪造价格或“无回复” |
| 经营闭环 | 上架后难以追溯来源 | Ozon 数字 SKU/seller offer 精确回查 Product、Listing、正式 SupplierOffer 和采购链接 | 建立上架到货源的可审计 linkback |
| 竞争对手研究 | 竞品功能清单 | 能力对照只落到 KJDS 现有权威对象和证据链，并纳入策略版本、来源、时效、评测和回滚 | 从“复制功能”升级为原生能力与治理竞争 |
| 真实数据 | 先做完整界面再补数据 | 真实 RFQ、28 天候选数据、Ozon 回读和成本 Evidence 是当前 Gate；缺失显示 `awaiting_evidence/unknown` | 先保证现金利润真相，再扩大自动化 |

## 本次已落地的工程边界

1. `AutomatedCommerceLoop` 复用既有 AI Listing、Marketplace Catalog、Product、ListingDraft、
   SupplierOffer 和 ProfitScenario，只做编排与投影。
2. 新增的门店自动化字段进入既有 Store Profile；Profile 偏好不是 Grant，当前运行时不会
   获得外写权限。
3. Ozon 链接只接受已观察的 6–20 位 marketplace SKU；无目录回读时不使用 KJDS SKU 或
   SupplierOffer ID 猜造卖家身份。
4. 利润只在完整成本 Evidence 且 CM3>0 时标记 `recommended`；否则保持待补证或不推荐。
5. 外部发布、采购、付款仍必须经过原有 Approval/Permit/Executor/Readback/Kill Switch，
   不新增旁路。
6. 主线选择性集成按 BAS-219A/B 分期：A 只包含核心 Module、Store Profile 合同与 RFQ
   只读回链；隔离分支的 runtime/API/Web 仍未进入主线，等待 BAS-186 释放共享 seam 后再做
   独立 CAS、验收和回滚。
7. 需求追溯矩阵分别记录 `TRACE-005A=ADOPTED_ENGINEERING` 与
   `TRACE-005B=ISOLATED_IMPLEMENTED`，禁止用核心已接入掩盖前台/运行时仍未接入。

## 仍未完成、不能宣称完成的事项

- RU-001/RU-002 六家供应商的真实书面 RFQ 回复和独立接受；
- 当前 Ozon Listing 的精确目录回读与 Product 绑定；
- 十五项成本、汇率、物流、退货、平台费和有效 Evidence；
- 真实俄语审核、Approval/Permit/Executor/Readback；
- 监督批次/自治模式的独立 Eval、Grant、Kill Switch 和 Compensation 生产演练。

## 会话同步规则

本文件是后续 Codex/Claude 会话读取的决策锚点；会话间同步只同步上述产品边界、当前 Gate、
证据状态和工作分支，不同步凭证、私密启动包或未验证事实。实现任务继续遵循
`docs/project/19_AUTOMATED_COMMERCE_AND_RECURSIVE_STORE_MINING_PRD.md`、
`docs/project/20_LIVE_POLICY_TECHNOLOGY_RESPONSE_PLAN.md` 和 `MASTER_SPEC.md`。
