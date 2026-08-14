# Ultimate Start Gate RA 独立需求架构评审

| 项目 | 结果 |
|---|---|
| 评审类型 | Ultimate Start Gate / Requirements Architect 独立评审 |
| 结论 | **APPROVED** |
| 结论边界 | 仅表示需求架构无未关闭 P0 歧义、可以按依赖波次开工 |
| 不代表 | 0.59 Release、功能完成、真实 Pilot、Ozon 发布、订单、结算、商业化或盈利完成 |
| 评审分支 | `feature/batch-opportunity-mining-059` |
| 基线分支 | `main` / `origin/main` |
| 基线 commit | `b34a3a711f6e5f8dff4e2a7bde876a2a3df8a00f` |
| 基线说明 | `Release 0.58.0 marketplace observation and portfolio Pilot (#46)` |
| 基线提交时间 | `2026-07-27T06:54:13+08:00` |
| 最终取证时间 | `2026-07-27T09:24:14+08:00` |
| 勘误复审结论 | **APPROVED（维持）**；0053/0054 迁移责任修正后无新增 Start-P0 |
| 规范基线 | `ULTIMATE_PRODUCT_BLUEPRINT.md`、`ULTIMATE_REQUIREMENTS_ARCHITECTURE.md`、ADR-0032、`MASTER_SPEC.md` 8.5 |
| Release Gate | `20260727_GATE_RA_059.md` 继续保持 **REJECTED** |
| 修改范围 | 本评审只新增本文；未修改代码、测试、迁移、其他文档、Git、数据库、浏览器或店铺 |

## 1. 决定

**APPROVED**

最终版 Blueprint、Requirements Architecture 与 ADR-0032 已把开工所需的权威、
边界、失败语义、依赖顺序和验收面冻结到无 P0 歧义的程度。实现团队可以从 M0
Truth/Governance 开始，并按 `M0 → M1 → M2 → M3 → M4` 推进。

本批准严格限定为 Start Gate：

- 不撤销或覆盖现有 0.59 Release Gate 的 **REJECTED**；
- 不把当前未提交工作树视为可发布候选；
- 不要求用真实订单或真实结算证明“允许开工”，但 Final Release 仍必须取得这些证据；
- 不创建 Ultimate 开工 Evidence；
- 不授予 Ozon、供应商、采购、付款、广告、媒体或其他外部写权限；
- 不把公开页观察、测试、静态页面或模型建议称为真实利润或真实经营结果。

## 2. 评审方法与 Gate 分离

本评审使用深模块框架检查 Module、Interface、Implementation、Seam、Adapter、
Depth 与 Locality：

- Start Gate 判断规范是否为调用方提供唯一的权威 Interface、稳定不变量、错误语义、
  依赖方向和可测试 Seam；
- 当前 Implementation 仅作为“合同能否落地”和“还缺什么”的佐证；
- 实现不完整、真实数据未到、容器未验证等进入 P1/P2 Release backlog，不在规范已经
  唯一时反向制造 Start-P0；
- 现有 Release RA 仍负责判断 0.59 是否可提交、发布或进入真实经营。

评审中曾发现一个账本术语冲突：Settlement 被定义为应计、结算、到账三本账，但旧文本
又用 Scenario、accrual、cash 称“三本利润账”。规范 Owner 在最终取证前已统一为：

```text
Scenario CM3（估算）
+ Actual accrual（实际应计账）
+ Settled contribution（实际结算账）
+ Actual Cash CM3（实际到账账）
```

即“四种贡献视图 = 一个情景估算 + 三本实际账”。最终版两份真源已经一致，故该
Start-P0 在本次决定前关闭。

## 3. Git、代码与验证证据

### 3.1 Git 基线

只读命令：

```text
git status --short --branch
git rev-parse HEAD
git rev-parse main
git rev-parse origin/main
git show -s --format=fuller HEAD
```

结果：

- 当前分支为 `feature/batch-opportunity-mining-059`；
- `HEAD`、`main`、`origin/main` 均为
  `b34a3a711f6e5f8dff4e2a7bde876a2a3df8a00f`；
- 0.59 仍是大量未提交 tracked/untracked 工作树修改；
- 受保护的 `STRATEGY_AND_ARCHITECTURE_2026.md`、P0 verification 文档、`wuliu/`
  与 PDF 未被本评审触碰。

### 3.2 聚焦后端/API

执行：

```text
uv run pytest -q -p no:cacheprovider
  --basetemp=<系统 TEMP 下的独立随机目录>
  tests/test_batch_opportunity.py
  tests/test_ozon_global_rules.py
  tests/test_seller_operating_system.py
  tests/test_api_contract.py
```

结果：

```text
72 passed, 1 warning in 2.53s
```

唯一 warning 是 FastAPI TestClient 的 Starlette/httpx2 deprecation，不是本 Gate
的行为失败。旧 Release RA 中的 `50 passed, 2 failed` 是当时取证事实；当前聚焦合同
已经收敛到 72/72，但这不自动关闭 Release Gate。

定向 Ruff：

```text
uv run ruff check --no-cache
  apps/control_plane/batch_opportunity.py
  apps/control_plane/ozon_global_rules.py
  apps/control_plane/seller_operating_system.py
  apps/control_plane/marketplace_observation.py
  apps/control_plane/security.py
  apps/control_plane/api_contracts.py
  apps/control_plane/routers/marketplace_observation.py
  migrations/versions/20260727_0053_batch_opportunity.py
  migrations/versions/20260727_0054_observation_unit_price.py
  tests/test_batch_opportunity.py
  tests/test_ozon_global_rules.py
  tests/test_seller_operating_system.py
  tests/test_api_contract.py
```

结果：`All checks passed!`

### 3.3 Web

执行：

```text
cd web
npm test
```

结果：

```text
49 passed, 0 failed
```

这只证明当前 Web 组合合同；没有执行 `npm ci`、`npm run build`、容器或 Playwright，
因此不作为 Release 通过证据。

### 3.4 运行时 OpenAPI 与匿名访问

从 `app.openapi()` 只读检查到版本 `0.59.0`，路径与方法包括：

```text
POST /v1/batch-market-scans
GET  /v1/batch-opportunities/latest
GET  /v1/ozon-global-rules
POST /v1/ozon-global-rules/evaluate
POST /v1/ozon-global-rules/impact
GET  /v1/seller-os/strategy-packs
POST /v1/seller-os/evaluate
```

对以上七个入口分别执行匿名请求，全部返回 `401`。这证明最小认证边界存在，不证明
tenant/entity/store 全链、角色分离、数据库 RLS 或外部执行已完成。

### 3.5 当前实现与迁移只读检查

已检查：

- `BatchOpportunityWorkspace` 的分页/分片、exact cohort、供应全集、统一 1–3 件数量、
  landed Pareto、pilot allocation、请求 fingerprint 和只读 authority；
- `OzonGlobalRuleRegistry` 的 `as_of`、effective set、规则 hash、scheduled change、
  domain-bound impact、action-scoped readiness 和 fail-closed；
- `SellerOperatingSystem` 的四轴、版本化 Strategy Pack、策略/包络/Portfolio 与
  `commercial_entitlement_created=false`；
- `MarketplaceObservationWorkspace` 的 `price_scope`、unit price、exact identity、
  store filter、Evidence 和事实隔离；
- 已冻结的 0053 migration 只负责批量机会表及 Observation 的 candidate identity、
  checkout、税费/运费、置信度和信号扩展，不再改写其已执行历史；
- forward-only 0054 migration 才负责新增 `price_scope/unit_price`：在同一个
  PostgreSQL DDL 事务中精确临时停用 Observation item 不可变 trigger，执行
  legacy `displayed_price → unit_price` 回填，立即恢复 trigger，随后移除
  `price_scope` server default 并增加正数、scope 和数量守恒 CHECK；
- API schema/router/runtime/security 与四组聚焦测试。

迁移现场记录复核：

- 真实 PostgreSQL 已成功执行 `0053 → 0054`；
- `uv run python -m alembic heads` 只读复验为单一 head
  `20260727_0054 (head)`；
- 升级前后的 3 条 Observation 的 ID、content hash 与 Evidence hash 保持不变；
- 先前一次失败 downgrade 在 PostgreSQL 事务 DDL 下完整回滚，没有留下半迁移 schema；
- 空库 `base → 0054` 与完整 `0054 → 0053 → 0054` 回放仍是 Release 待验，不在本次
  Start Gate 中冒充已完成。

当前 Ozon Global CN registry 有 13 条规则，13 条均缺完整
`source_evidence_id + source_content_sha256 + source_observed_at` 绑定。当前 evaluator
因此保持约束/阻断，是正确的 Release 前 fail-closed 行为，不是 Start 架构歧义。

`git diff --check` 返回 0；只出现现有工作树 LF 将来可能转 CRLF 的 warning，没有
whitespace error。

## 4. Start-P0 逐项结论

| 审查面 | 最终架构合同 | 结论 |
|---|---|---|
| 六层语义 | Observation → Fact → Inference → Decision → Execution → Settlement；低层不能被模型或 UI 越级 | 无 P0 歧义 |
| 利润账 | Scenario estimate 与 accrual / settled / cash 三本实际账四视图分离，Evidence 不完整不得显示实际利润 | 无 P0 歧义 |
| Bounded contexts | Identity、Market、Supply、Profit、Passport、Content、Rules、Seller OS、Operations、Execution、Settlement、Evidence 分属权威 Module，并列明“不负责” | 无 P0 歧义 |
| Deep seams | 调用方消费小 Interface；规则、身份、利润、执行和证据各有独立权威，Adapter 不拥有事实或批准 | 无 P0 歧义 |
| Rule Compiler | effective Registry 是唯一规则真源；Evaluator 只做通用编译/解释；缺域、重叠、失效或来源绑定缺失 fail-closed | 无 P0 歧义 |
| `as_of` 与 impact | current/previous 用同一 `as_of` 编译；未来规则只 scheduled；只影响绑定域 SKU；旧 run 固化 hash | 无 P0 歧义 |
| Exact identity | cohort key 为 canonical product identity + exact variant；错误变体永不聚合 | 无 P0 歧义 |
| Own/external | own listing 收入观察与 external competitor cohort 永不混合；新 SKU 只产生 proposed price scenario | 无 P0 歧义 |
| 供应价格 | checkout observation、RFQ、Supplier Offer、actual cost 四种 authority 分离；比较用冻结 1–3 件数量 | 无 P0 歧义 |
| 税费与运费 | MOQ、精确数量、税费、国内运费完整才进入 landed Pareto；未知不得按 0 | 无 P0 歧义 |
| Profit kernel | tenant/entity/store/product/SKU/order/date/currency/FX date；自然键归集，未知进 unallocated，侵蚀守恒且不重计 | 无 P0 歧义 |
| Tenant/entity/store | Principal 服务端映射 tenant/store；URL/body 不能扩权；own/decision/execution/order/settlement 隔离 | 无 P0 歧义 |
| RBAC / SoD | proposer、approver、executor、finance reviewer 分离；approver 不持执行密钥；executor 只消费 frozen command + Permit | 无 P0 歧义 |
| Evidence/audit | Evidence、Lineage、Audit 不可变；override 有 actor/reason；坏 Evidence fail-closed | 无 P0 歧义 |
| 幂等/outbox | 写 API 使用 key + request fingerprint；同 key 异 payload conflict；事务 outbox；consumer/event/version 幂等 | 无 P0 歧义 |
| API/events/recovery | keyset cursor、page/shard、保守 prescore、append-only 关键事件、lease 回收、compensation state 已定义 | 无 P0 歧义 |
| AI authority | Agent port 必须定义输入、输出、自动动作、人审、eval、失败；proposer 无 Approval/Permit tool；Execution 只消费已签发 Permit | 无 P0 歧义 |
| no_data/failure | workspace 有 ready/partial/no_data/blocked/error/forbidden/stale；动作级 readiness 不被顶层状态吞掉 | 无 P0 歧义 |
| 迁移/回滚 | 冻结旧 0053、用 forward-only 0054 完成 Observation 1.1 事务回填/default/CHECK；candidate key 兼容、deprecated alias、downgrade→upgrade 与失败停止策略已冻结 | 无 P0 歧义 |
| Archetype/plan | 七类 archetype 有默认/升级 plan 假设；四轴与 archetype 只形成 plan recommendation，不创建 entitlement | 无 P0 歧义 |
| 依赖波次 | M0→M1→M2→M3→M4；后波不得复制前波 authority；每波 Release 条件明确 | 无 P0 歧义 |
| 查询/仪表盘 | read model 最小 scope/time/currency/FX/source/freshness 合同与八个核心页面 KPI/drilldown 已冻结 | 无 P0 歧义 |
| Source Adapter | Seller API、official export、authorized connector、allowed public observation 分级；声明 ToS/rate/region/privacy/revocation；不可访问=no_data | 无 P0 歧义 |

**开放 Start-P0：0。**

## 5. P1 Implementation / Release backlog

以下均重要，但规范已经给出唯一实现方向，因此不阻止开工。

### P1-START-01：先完成 M0 的实际 tenant/entity/store 数据边界

当前 Principal 增加了 tenant/store scope，部分 Router 会返回 403；但 0053 的 Batch
表仍只有 `store_ref`，只执行 `ENABLE ROW LEVEL SECURITY`，未见 tenant/entity 键和
实际 RLS policy。必须在 M1/Release 前：

- 为 business object、幂等唯一键、Evidence 和事件补 tenant/entity/store 作用域；
- 建立 Principal-to-scope grant 与 PostgreSQL policy；
- 验证匿名 401、同租户越店 403、跨租户 403、external observation 的受控共享；
- 证明导出、游标、idempotency、task、cache/read model 不跨 scope。

### P1-START-02：Rule Compiler 从“版本化注册表 + 专用代码”收敛为通用解释器

当前 registry 已有版本、hash、effective 与 impact，但 evaluator 仍按固定 rule ID
调用专用 Python 方法。M0 必须按 ADR-0032 收敛为“registry 唯一规则真源”，删除
阈值/有效日双写；13 条当前规则必须逐条绑定真实官方 Evidence，缺绑定继续阻止
Pilot Approval/publish。

### P1-START-03：实现四种贡献视图和三本实际账，而不是只改名称

当前实现主要提供 scenario、actual accrual、reconciled cash，尚未形成独立
`Settled contribution` 账和完整订单/结算/银行自然键。M0/M3 必须补：

- 四个不可互换的 DTO/read model；
- order/return/accrual/statement/bank/FX Evidence 与冲销；
- unallocated、跨币种阻断、重复导入和 component conservation；
- settlement 已对账但银行未到账的独立状态与金额。

### P1-START-04：事务原子性、Outbox 与并发幂等

当前 Batch `prepare()` 在 run 事务之外创建 Evidence/OperatingTask，随后插入唯一 run，
并在提交后再建 lineage；并发或中间故障仍可能产生孤儿 Evidence/task/link。必须把
request fingerprint、run、Evidence link、task projection 和 Outbox 放进可证明的原子
边界，或采用有补偿且可巡检的 staged protocol。

### P1-START-05：角色责任与 Agent Port 落地

当前 `POST /v1/batch-market-scans` 仍允许 reviewer 创建研究产物。应按职责收紧为
operator 发起、reviewer/compliance 独立复核，或明确第二复核人约束。八类 Agent Port
必须分别实现输入 fact type、输出 schema、允许动作、人审 Gate、eval dataset/metric
和失败状态；Approval/Permit 权威不得注册为 proposer 工具。

### P1-START-06：Archetype、四轴、plan recommendation 与 entitlement 真正解耦

当前 Seller OS 已返回 `commercial_entitlement_created=false`，但实现仍主要由
`scale_segment` 直接选择 Strategy Pack，尚未实现七类 archetype→plan recommendation
与独立 Billing/Entitlement。M4 前必须建立稳定 plan ID、plan-fit artifact、独立
entitlement ledger 和取消/grace/read-only 语义；任何套餐不得改变事实、利润或安全门。

### P1-START-07：最小 read model、Source Adapter 与 UI 合同落地

当前 API 尚未在所有查询统一要求 tenant/entity/store、time range/timezone、
display currency、FX policy/date、source grade 和 freshness；八个核心仪表盘也未全部
按此 DTO 交付。必须建立服务端 read model 和 adapter port，Web 只展示服务端结果，
不得计算 CM3/cohort/readiness 或用随机数据补空。

### P1-START-08：迁移、真实 PostgreSQL 和全交付门

已冻结的 0053 不承担 unit-price 转换，forward-only 0054 才是该转换的唯一迁移
Implementation。真实库 `0053→0054`、单一 head 0054、3 条 Observation
ID/content/Evidence hash 保持及失败 downgrade 事务回滚已验证。Release 前仍必须完成：

- 空库 `base→0054`；
- 完整 `0054→0053→0054` downgrade/upgrade 回放并再次验证数据哈希、trigger 与 CHECK；
- 0054 并发约束、不可变 trigger、RLS/tenant policy 与故障注入；
- secret scan、全量 Ruff/pytest、OpenAPI snapshot、`npm ci/test/build`、容器
  PostgreSQL/API/Web/worker 健康、浏览器桌面/390px、性能/恢复和 `git diff --check`。

## 6. P2 backlog

### P2-START-09：内部 Locality 与可替换 Adapter

`BatchOpportunityWorkspace` 当前约 2738 行，`OzonGlobalRuleRegistry` 约 1302 行，
外部 Interface 较小但 scanner/query/scoring/policy/content/persistence 的变化仍集中
在大型 Implementation。不要为形式拆文件；当出现第二个真实 source adapter、第二个
规则域实现或删除测试无法隔离复杂度时，再把 Observation Query、Rule Compiler、
Profit Kernel、Source Adapter 和 persistence 明确成可替换 seam。

### P2-START-10：M4 企业与商业能力延后实现

多主体矩阵、SSO、私有连接器、SLA、Usage/Billing/Entitlement、退款/发票、灾备和
商业毛利必须等 M0–M3 权威链稳定后实施。此前所有价格继续保持
`hypothesis_internal_preview_not_for_sale`。

### P2-START-11：规模与可观测性

在真实样本进入后补 100/500/1000/1501+ 观察的 P95、SQL 数、内存、Evidence verify
次数、超时/取消/租约恢复，以及 worker/queue age、source freshness 和人工注意力预算。
未出现实证压力前不引入 Redis、Kafka、Temporal 或第二工作流引擎。

## 7. 必须成为实现验收的场景

1. **六层不可越级**：公开 Observation 和 AI 推断不能创建 Fact、Offer、Approval、
   Permit、actual 或平台副作用。
2. **四种贡献视图**：同一订单依次形成 Scenario、accrual、settled、cash；每次晋级
   创建新账与 Evidence，不原地改标，四种金额可不同且均守恒。
3. **Exact variant cohort**：同 identity 的正确变体 5 个 external listing、错误变体
   2 个、own listing 1 个；错变体排除，own 价格不进入 competitor median。
4. **供应数量与边界**：供应 tier 为 100/100/3，Pilot 数量为 3；不能使用百件价。
   税/国内运费未知的最低展示价不得进入 landed Pareto。
5. **Rule effective/impact**：当前阈值变更会改变 evaluator；未来规则只 scheduled，
   生效日才改变绑定域 SKU；旧 run 以 registry/compiled/input hash 重放不漂移。
6. **Source Evidence**：规则 URL 存在但 Evidence/hash/observed_at 缺失时 research 可
   partial，candidate 不精确排序，Pilot Approval 与 publish 必须 blocked。
7. **Tenant/store 隔离**：Store B 新数据不覆盖 Store A；跨 tenant/store 403，匿名
   401；external market observation 共享不带出 own/order/settlement。
8. **SoD**：proposer 不能批准自己；approver 不持 executor key；Execution Agent 只能
   消费已批准 frozen plan hash 对应的一次性 Permit；第二次消费失败。
9. **幂等/Outbox**：20 个并发同 key/同 payload 只有一个 run/Evidence/task/event；
   同 key/异 payload conflict；任一故障点重试无孤儿或双写。
10. **Agent authority**：Research/Match/Economics/Content/Approval/Execution/Growth/
    Settlement 八类 port 各自通过金标 eval；失败返回 no_data/blocked/stop，不能自授权。
11. **Plan 与 entitlement**：同 scale、不同 ops/brand/risk 只改变策略建议；archetype
    只改变 plan fit；无 Billing 决定时 entitlement 不变，套餐不能扩大 1–3 件安全门。
12. **Portfolio**：Actual Cash CM3、置信度、退货、履约或结算不完整的 SKU 只进入
    `unclassified/no_data`，不分配 proven/growth/experiment/exit 额度。
13. **Read model/UI**：八个核心页面显式 scope/timezone/currency/FX/source/freshness；
    empty/partial/blocked/stale/error/forbidden 不造演示事实，390px 无横向溢出。
14. **迁移恢复**：冻结 0053 后以 forward-only 0054 执行 unit-price 事务回填；
    已验证的真实库 `0053→0054` 和 hash 保持继续成立，Release 再完成空库
    `base→0054`、`0054→0053→0054`、旧 candidate alias、exact variant 重捕获、
    不可变 trigger、RLS 和中途失败停止。
15. **外部副作用**：所有扫描、规则评估、策略推荐、内容 draft 和异常任务保持内部；
    未通过独立 Pilot Gate 时 Ozon/供应商/采购/付款/广告写入数为 0。

## 8. 最终 Gate 声明

Ultimate Start Gate RA：**APPROVED**

理由：最终规范已经为语义、权威、深模块 seam、失败关闭、依赖波次、Agent Port、
查询/仪表盘、迁移和验收提供唯一且可实施的方向，开放 P0 为 0。

勘误复审结论：**APPROVED（维持）**。0053 冻结、0054 forward-only 的迁移责任已经
与最终文件及真实库取证一致；已完成与 Release 待验项已分开记录，没有新增 Start-P0，
也没有把部分迁移成功扩大解释为 Release 通过。

0.59 Release Gate：**仍为 REJECTED**。只有关闭现有 Release P0/P1、冻结候选 commit，
完成全门禁、真实 PostgreSQL/容器/浏览器回放及必需经营 Evidence 后，才能由独立
Release 复审改变该结论。

本批准不证明有真实订单、真实结算、真实 Actual Cash CM3、真实 Ozon 发布、商业套餐
可售或月收入目标可实现。
