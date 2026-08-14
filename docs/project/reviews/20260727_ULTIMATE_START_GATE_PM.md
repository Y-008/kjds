# KJDS Ultimate Start Gate PM 评审

## 1. 评审元数据

| 字段 | 值 |
|---|---|
| 评审类型 | Ultimate Start Gate / 产品经理独立评审 |
| 评审结论 | **APPROVED** |
| 评审时间 | 2026-07-27 09:09–09:23（Asia/Shanghai） |
| 工作分支 | `feature/batch-opportunity-mining-059` |
| 基线分支 | `main` / `origin/main` |
| 基线提交 | `b34a3a711f6e5f8dff4e2a7bde876a2a3df8a00f` |
| 工作树 | 基线之上存在未提交的 0.59/Ultimate 方案、后端、迁移、合同、Web 与测试变更 |
| 评审真源 | `ULTIMATE_PRODUCT_BLUEPRINT.md`、`ULTIMATE_REQUIREMENTS_ARCHITECTURE.md`、ADR-0032、`MASTER_SPEC.md`、`AGENTS.md` |
| 对照评审 | `20260727_GATE_PM_059.md`，其 Release Gate 结论继续为 **REJECTED** |
| 写入约束 | 除本 Start Gate PM 文件外未修改代码、测试、其他文档、数据库、Git 或店铺 |

本评审只回答：

> Ultimate 产品方案、产品合同和实施依赖是否已经没有 P0 歧义，足以开始分阶段实施？

它不回答当前功能是否完成，不要求真实订单、Pilot 或结算结果，也不改变 0.59 Release
Gate、Pilot Gate、Final Release Gate 或 Ozon 写权限。

## 2. 最终决定

**APPROVED — 允许按 M0 → M4 依赖顺序开始实施。**

批准理由：

- 产品承诺、平台/商业/执行三个独立 Gate 和不可交易边界清楚。
- 七类客户的 JTBD、默认/升级计划假设和四轴诊断已经分开，诊断不再创建 entitlement。
- 六种经营模式有进入、退出、升级和回落条件。
- canonical journey 已区分观察、预算 allocation、独立批准、Permit、发布回读、订单、
  结算和 scale/stop。
- 22 个信息架构域有统一页面合同，不把条件分支壳当完成。
- 定价已明确为 `pricing_hypothesis/internal_preview/not_for_sale`。
- North Star、guardrails、漏斗 cohort 和实际利润语义已经冻结。
- `no_data/blocked/error/forbidden/stale`、动作级 readiness、桌面/390 和禁止演示数据已
  成为验收合同。
- M0–M4 的依赖波次和各自 Release 条件足够指导拆分实施。
- Rule Compiler、exact identity、tenant/store、四种贡献视图（Scenario CM3 估算 +
  Actual accrual、Settled contribution、Actual Cash CM3 三本实际账）、Agent authority、事件和
  失败恢复的实现接缝明确。

**APPROVED 只表示可开工，不表示功能完成、真实经营闭环完成、套餐可售、Ozon 已发布、
获得真实利润或 Release Gate 通过。**

## 3. Gate 分离

| Gate | 本次结论 | 含义 |
|---|---|---|
| Ultimate Start Gate PM | **APPROVED** | 产品方案和合同无 P0 歧义，可以实施 |
| `GATE_PM_059` Release Gate | **REJECTED，保持不变** | 当前页面、运行数据、端到端任务和商业实现仍未达到交付标准 |
| Pilot Gate | 未评审/未通过 | 仍需真实规格、完整 downside、Passport、权利/QA、独立批准、Permit、Readback、止损 |
| Final Release Gate | 未评审/未通过 | 仍需真实订单、退货、结算、到账和 Actual Cash CM3 |

当前运行容器六个 Seller OS 路由仍为 404、最近 batch 仍为全零 `no_data`，这些是
Release Gate 实现缺口，不是 Start Gate 产品合同歧义。不得用本次 APPROVED 覆盖或
降级 `20260727_GATE_PM_059.md` 中的任何 Release finding。

## 4. 证据与复验结果

### 4.1 文档阅读

已完整阅读：

- `AGENTS.md`
- `docs/project/MASTER_SPEC.md` 8.5
- `docs/project/ULTIMATE_PRODUCT_BLUEPRINT.md` 最新版
- `docs/project/ULTIMATE_REQUIREMENTS_ARCHITECTURE.md` 最新版
- `docs/adr/ADR-0032-ultimate-start-gates-and-rule-compiler.md`
- `docs/project/reviews/20260727_GATE_PM_059.md`
- 当前 Git 状态、diff、相关 Seller OS/Batch 页面、registry 和测试合同

评审过程中 Ultimate 真源新增四项合同；本结论基于 2026-07-27 09:13:44 保存的最新
Blueprint/Requirements，而不是此前快照。

### 4.2 聚焦后端/API 复验

执行：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
uv run pytest -q -p no:cacheprovider `
  --basetemp=.runtime/pytest-ultimate-start-pm `
  tests/test_batch_opportunity.py `
  tests/test_ozon_global_rules.py `
  tests/test_seller_operating_system.py `
  tests/test_api_contract.py
```

结果：

```text
72 passed, 1 warning in 2.63s
```

唯一 warning 为 Starlette TestClient/httpx 的弃用提示，不改变 Start Gate 合同判断。
这 72 项已覆盖 exact variant/store、checkout price scope、未知运费、own/competitor
隔离、cohort 去重、风险调整供应 Pareto、3 件 Pilot 不使用 100 件阶梯价、allocation
selected/waitlist、费用宽区间、幂等冲突、规则 effective/scheduled impact、四轴诊断、
Portfolio unclassified、动作级 research/draft 和 OpenAPI/匿名鉴权。

### 4.3 Web 合同复验

执行：

```powershell
cd web
npm test
```

结果：

```text
49 passed, 0 failed
```

该结果证明当前源码合同测试通过，不证明页面已构建进运行镜像、390px 视觉完成或真实
用户任务完成；这些仍属于 Release Gate。

### 4.4 只读运行检查

| 检查 | 结果 | Start Gate 解释 |
|---|---|---|
| `/health/ready` | 200，API `0.59.0`，database `ok` | 说明当前服务可读，不是 Ultimate Release 证明 |
| 六个 Seller OS 路由 | 全部 404 | Release 缺口，保持原 PM REJECTED |
| batch latest | 200；五项计数全 0，`state=no_data` | 真实无数据，未造演示事实 |

### 4.5 Git 基线

`main`、`origin/main`、当前 HEAD 均为
`b34a3a711f6e5f8dff4e2a7bde876a2a3df8a00f`。Tracked diff 为 25 个文件、
约 2759 additions / 36 deletions，另有 Ultimate 文档、registry、模块、迁移、测试与
页面等未跟踪工作树文件。本评审不把未提交状态解释为交付完成。

## 5. 产品方案审查

### 5.1 产品承诺和不可交易边界

结论：**无 P0 歧义。**

KJDS 被定义为 Ozon Global 中国卖家的 Seller Operating System，价值是把市场观察、
精确身份、供应、十五项 CM3、内容、批准、执行、订单与结算变成可回放经营闭环。
“规则优势”明确是更早发现、模拟和采取更严格的内部控制，不是绕过条款、验证码、限流、
风控、IP 或访问控制。

Ozon 授权、KJDS 商业订阅、单次外部动作 Approval + Permit 是三个独立 Gate，任何一个
不能替代另一个。该边界足以约束产品、销售、Agent 和实现。

### 5.2 七类客户与 JTBD

结论：**无 P0 歧义。**

Blueprint 已定义七类渐进体验：

1. 新手
2. 个人
3. 小微
4. 中小企业
5. 中型企业
6. 大卖
7. 集团

每类均有首要 JTBD、默认计划假设和可升级计划假设。七类 archetype 映射到有限商业
计划，不要求“一个客群一个套餐”。共享 JTBD 已收敛为：

```text
发现需求 → 精确匹配 → downside CM3 → 有权利内容 → 独立批准
→ 受控发布 → Readback → 订单/退货 → 结算/到账 → scale/stop
```

四个诊断轴分别是规模、运营成熟度、品牌阶段和风险姿态；各轴输出 provenance、
observed_at、input completeness、Evidence coverage 和 classification confidence。
用户自报只产生 plan fit/recommendation，不创建 entitlement。

### 5.3 六种经营模式

结论：**无 P0 歧义。**

`controlled_distribution`、`refined_operation`、`hero_sku`、
`brand_building`、`store_cluster`、`hybrid` 六模式均有可实施的进入、退出和升级条件。
模式建立在同一事实/利润/治理内核上，不按套餐降低真实性；真实父体、24h/72h/7d 和
结算条件阻止虚假变体扩张。

### 5.4 IA 与端到端任务流

结论：**无 P0 歧义。**

Blueprint 的 22 个 IA 域覆盖登录/授权、诊断、总览、市场、机会、Passport、供应、
利润、内容、发布、广告、库存、订单、结算、Portfolio、店群、规则、任务、Evidence、
连接器、RBAC 和 Usage/Billing。

每页共同合同为：

- 明确 JTBD 和 canonical object；
- 只消费服务端状态；
- 主要动作与 drilldown；
- loading/empty/error/forbidden/stale；
- 桌面和 390px 验收。

canonical journey 已把 `approval_allocation_selected/waitlist` 与真正
Approval、Permit、Pilot 分开。每个动作必须展示 status、why、missing Evidence、
Owner、SLA 和下一工作区；缺结算只锁 actual/proven/scale，不阻止合法 observe 或
content draft。

### 5.5 Pricing hypothesis 与不可交易边界

结论：**无 P0 歧义。**

所有 ¥299/999/3999、¥120,000/年、¥250,000/年价格明确为
`pricing_hypothesis/internal_preview/not_for_sale`。未完成 Billing、Usage Ledger、
Entitlement、退款/发票、AI/媒体单位经济和 SLA 验收前不得售卖。

套餐只改变配额、协作、SLA、连接器频率和可申请的 scale 包络；不能改变首批 1–3 件
Pilot 上限，也不能降低 Evidence、利润、SoD、Permit、Readback、Kill Switch 和
Compensation。

### 5.6 North Star 与 guardrails

结论：**无 P0 歧义，存在 P1 指标细化工作。**

North Star 已锁定为：在证据完整和治理通过的 SKU 中，按时完成结算并保持正
Actual Cash CM3 的数量、金额与现金周期。它没有把自动上品数、观察价差或场景 CM3
冒充成功。

Guardrails 覆盖 downside、unallocated、Evidence 新鲜度、Pilot 单量、控制链完整率、
退货/取消/履约、广告边际利润、库存现金、内容/IP、规则响应，以及重复商品、跨店污染、
越权和外部副作用为零。

### 5.7 failure / no_data / 桌面与 390

结论：**无 P0 歧义。**

每个 workspace 必须返回
`loading/ready/partial/no_data/blocked/error/forbidden/stale`，全局状态不能吞掉动作级
readiness；失败提供 Owner、SLA、missing Evidence、retry 和下一 workspace；离线不得
使用演示数据。

390px 合同明确为 `scrollWidth === innerWidth`，且 OpenAPI、匿名 401、越权 403、
migration、容器、全质量门均列为 Release NFR。

### 5.8 阶段和 Release 条件

结论：**无 P0 歧义。**

| 波次 | 产品范围 | Release 条件 |
|---|---|---|
| M0 Truth/Governance | Identity、Evidence、tenant/store、Rule Compiler、四种贡献视图、Approval/Permit/Readback | 迁移、API、权限、三本实际账守恒、匿名/越权测试 |
| M1 Intelligence/Candidate | 市场/竞品 cohort、供应 Pareto、十五项 downside、漏斗、候选详情 | 真实 Observation 回放；listing 不冒充 SKU |
| M2 Content/Approval/Pilot | Passport、俄语/媒体、allocation、frozen plan、小流量 Pilot | 权利/QA、1–3 件、SoD、Permit/readback 沙箱 |
| M3 Order/Settlement/Portfolio | 订单、退货、应计、结算、到账、Portfolio | 四种贡献视图分离且三本实际账守恒、期限、unclassified/no_data、真实回放 |
| M4 Enterprise/Commercial | 多主体、SSO、连接器、SLA、Usage/Billing/Entitlement | 隔离、灾备、用量、毛利、生命周期、退款/发票沙箱 |

后波不能复制或绕过前波 authority。真实写仍需 Pilot Gate；商业交易必须等 M4 Release。

## 6. 四项补充 Start-P0 的独立判定

### START-P0-A：七类 archetype → plan，且 axis ≠ entitlement

**已消除歧义。**

七类客户均有默认/升级计划假设；四轴只做诊断与 plan fit。Billing/Entitlement 是独立
authority，用户自报、成熟度或推荐不能自动授予套餐、配额或外部执行权。

### START-P0-B：M0–M4 依赖波次和 Release 条件

**已消除歧义。**

Blueprint 和 Requirements 同时固定 M0→M4 顺序、每波能力、Release 条件及“后波不得
复制前波 authority”。团队可以据此拆 Epic、迁移和验收，不需要在实现中重新发明顺序。

### START-P0-C：AI Agent 输入/输出/自动动作/人审/Eval

**已消除歧义。**

Research、Match、Economics、Content、Approval、Execution、Growth、Settlement 八类
Agent 场景均明确输入事实、输出 artifact、可自动动作、人审 Gate 和 Eval/失败语义。
Approval/Permit authority 不得成为 proposer 的工具；Execution Agent 只能消费精确绑定
frozen plan hash 的已签发一次性 Permit。

### START-P0-D：核心仪表盘最小分析合同

**已消除歧义。**

Market Radar、Opportunity Funnel、Profit Lab、Content Studio、Growth Command、
Settlement、Portfolio、Rule Advantage 均明确最低 KPI/chart 和 drilldown。所有查询必须
显式 tenant/entity/store、时间范围/时区、显示币种、FX date、freshness 和 source grade。
禁止跨店混合、评论冒充销量、客户端 CM3、无来源趋势、绕过来源限制、复制竞品素材和
随机填空。

## 7. Findings

### P0

**无。**

最新 Blueprint、Requirements 与 ADR-0032 已为产品开工提供一致、可实现且失败关闭的
合同。现存代码/页面/运行缺陷仍保留为 0.59 Release findings，不构成 Start Gate
“方案不清楚”。

### P1

#### P1-START-PM-01：在首个 M0 PR 中把 Ultimate 真源回链到 Master Spec

`MASTER_SPEC.md` 仍是仓库总规格，Ultimate 文档通过 ADR-0032 成为 Start-Gate
normative sources，但 Master 尚未列出 ADR-0032、M0–M4 和 Ultimate 文档入口。

处理：`auto-fix`。首个 M0 规格 PR 更新 Master 元数据、Requirement/ADR 索引和真源优先
规则；不得把此文档同步工作误写为 M0 实现完成。

#### P1-START-PM-02：North Star 需要机器可执行指标字典

当前产品语义足以开工，但“按时”、统计窗口、SKU 去重、币种换算、金额聚合、现金周期
起止、迟到退货重述和 Owner 尚未形成版本化指标定义。

处理：`defer` 到 M3 前完成服务端指标注册、数据源、分子/分母、窗口、重述和护栏阈值。

#### P1-START-PM-03：七类客户和价格仍需真实 discovery

七类 JTBD 与 plan mapping 足以实施渐进体验，但没有客户访谈、激活率、愿付价格、支持
成本和流失数据。

处理：`defer` 到 M4 商业 Gate；页面在此之前必须持续显示
`internal_preview/not_for_sale`，不得接单或产生应收。

#### P1-START-PM-04：22 个 IA 域需形成按波次的 route/object/action map

IA 范围清晰，但实施需要为每页冻结 canonical object、角色、query/mutation、主要 CTA、
deep link、empty/error 和所属 M0–M4 波次，避免一次性建设 22 个空壳。

处理：`auto-fix`。M0 先交付授权/治理骨架；每一波只开放已满足 Release 条件的页面。

#### P1-START-PM-05：内部 tenant 维度与商业多租户解冻时间需显式区分

Requirements 要求 M0 即有 tenant/entity/store scope；Master 仍把多租户 SaaS 冻结到
G7。两者可以兼容：M0 的 tenant 是防跨店/未来迁移的内部作用域，不等于开放多租户
商业产品。

处理：`auto-fix`。在 M0 ADR/Spec 明确“内部单 tenant 强制 scope/RLS”和“M4/G7 后才
允许多客户商业暴露”，避免实现者提前建设 SaaS 控制面。

#### P1-START-PM-06：Agent Eval 需补 dataset、阈值、Owner 和成本预算

Agent 产品矩阵已明确应评什么，但尚未冻结样本集版本、precision/recall/事实一致性阈值、
人工修改率、最大模型成本和失效回退。

处理：`defer` 到对应 Agent 首次进入 M1/M2 Shadow 前；未通过 Eval 只能人工辅助。

#### P1-START-PM-07：仪表盘需补统计口径与大规模查询预算

p25/p50/p75、freshness、source grade 已定义方向，但还需各页最小样本、cohort 时效、
late-arriving data、分页/Top-K、P95 和最大扫描成本。

处理：`defer` 到对应 M1/M3 read model；浏览器不得为补口径而重算。

### P2

#### P2-START-PM-01：统一中英术语和用户文案

`controlled_distribution`、`refined_operation`、`approval allocation`、`actual accrual`
等术语需要稳定中文名、悬浮解释和角色化示例。

处理：`defer` 到每个波次的内容设计。

#### P2-START-PM-02：补可访问性与低认知负担验收

除 390px 外，还应定义键盘、焦点、色彩、表格朗读、错误摘要和高密度财务数据的无障碍
要求。

处理：`defer` 到 Web Release checklist。

#### P2-START-PM-03：为新手提供安全 sandbox 示例

Blueprint 允许 Starter sandbox，但未定义示例数据如何显著标识、如何与真实 tenant
隔离、如何一键清除。

处理：`defer` 到 M1 onboarding；示例不得进入正式漏斗、指标或 Evidence。

## 8. 开工验收场景

以下场景是设计/合同验收，不要求本次已实现：

1. **七类客户映射**：七类 archetype 均能返回 default/upgrade plan hypothesis；相同
   archetype 的不同四轴事实可产生不同建议，但不能创建 entitlement。
2. **四轴真实性**：input completeness、Evidence coverage、classification confidence
   分开；任意文本不能把 confidence 凑成 1.00。
3. **六模式晋级**：同规模、不同 ops/brand/risk 能改变模式；无结算不能进入 hero；
   权利失效立即冻结 brand。
4. **canonical action**：observe/content draft 可 allowed，publish/scale 因缺门
   blocked；每个动作返回 why/Evidence/Owner/SLA/next workspace。
5. **allocation 不越权**：`approval_allocation_selected` 只是预算槽位，不能创建
   Approval、Permit、命令或 Pilot。
6. **exact identity/cohort**：同 identity 错 variant 不聚合；own listing 不混 competitor；
   Store B 数据不覆盖 Store A。
7. **供应数量语义**：100/100/3 场景使用 3 件 Pilot 可购买价格，不使用 100 件阶梯价；
   未知运费/税费不按 0 排序。
8. **利润四种贡献视图**：Scenario CM3（估算）与 Actual accrual、Settled
   contribution、Actual Cash CM3 三本实际账严格分离；十五项与 unallocated 守恒；
   缺结算不得显示 settled contribution，缺到账不得显示 Actual Cash CM3。
9. **Rule Compiler**：当前规则变更只影响命中域 SKU；未来规则仅 scheduled，到期才改变
   readiness；Evidence 缺失阻断 Pilot Approval/publish。
10. **AI authority**：Agent 能生成 source-bound brief/draft/recommendation，不能自批、
    签发 Permit、绕验证码、晋升 actual 或在 readback 失败后扩量。
11. **最小仪表盘**：八个核心页均带 tenant/store/timezone/currency/FX/freshness/
    source grade；drilldown 回到原 Observation/Evidence/Fact/Event。
12. **Portfolio**：无完整 actual cash snapshot 时四桶保持 no_data/unclassified，
    不给资金 allocation。
13. **定价边界**：所有价格显示 hypothesis/internal preview/not for sale；无 Billing/
    Entitlement 不产生订阅、发票或生产额度。
14. **套餐生命周期**：M4 沙箱验证 active→grace→read_only，保留 export/audit，在途命令
    停止或完成 Readback/Compensation。
15. **失败态**：每个 workspace 覆盖 loading/partial/no_data/blocked/error/forbidden/
    stale/retry；离线不造演示事实。
16. **安全作用域**：匿名 401、越权 403；URL/body 不能扩大 tenant/store；operator 不能
    批准自己的外部写。
17. **390px**：核心旅程在 390px 满足 `scrollWidth === innerWidth`，长哈希、blocker、
    表格和错误态不造成页面级横向溢出。
18. **依赖波次**：M1 不绕过 M0 identity/rules；M2 不复制 Approval/Permit；M3 不用
    Scenario 冒充结算；M4 不降低全套餐安全不变量。

## 9. 开工条件与不授权事项

Start Gate APPROVED 后允许：

- 将 M0–M4 拆成版本化需求、ADR、迁移、后端 Interface、Web 任务和验收；
- 先实现 M0 的 Truth/Governance seam；
- 使用固定 Evidence-backed 样本和 sandbox 验证合同；
- 把本报告 P1/P2 纳入对应波次 backlog。

本批准不允许：

- 声称 0.59 Release 已通过；
- 把六个 404 页面、全零 run 或静态测试说成产品已完成；
- 出售任何 pricing hypothesis；
- 自动联系供应商、采购、付款、投放、发布或扩量；
- Agent 自批、自发 Permit 或绕过 Ozon 条款；
- 把 Observation/checkout/Scenario CM3 冒充 Offer、actual 或真实利润；
- 创建 Ultimate 开工 Evidence 冒充实施或经营结果。

## 10. 结论

**ULTIMATE START GATE PM：APPROVED**

最新产品与需求架构已达到“无 P0 产品歧义、可按依赖波次实施”的标准。四项补充
Start-P0 均已明确关闭；P1/P2 是实施期 backlog，不改变开工决定。

`20260727_GATE_PM_059.md` 的 **REJECTED** 继续有效，直至对应 Release findings、
真实数据回放、页面/API/迁移/浏览器验收和后续 Pilot/Final Gate 各自完成。
