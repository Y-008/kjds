# ADR-0030：Marketplace Observation 与组合 Pilot 深模块

- 状态：Accepted
- 日期：2026-07-26
- 需求：BR-081 / BAS-103
- Owner：经营负责人、供应链负责人、工程负责人
- Approver：经营负责人
- 复审触发：首个真实 Pilot 完成结算；新增第二平台；外部页面合同或许可变化

## 背景

KJDS 已有 Ozon 官方目录、Canonical Product、Supplier Offer、十五项 CM3、
Listing、OperatingTask、Approval 和受控执行链，但缺少把 Ozon/1688 页面与卖家工具
观察转成可批量去重、保留来源且不污染正式事实的读模型。`D:\KJDS\ozon` 中的毛子
ERP、浏览器插件和荔枝助手证明了价格、销量、变体、类目和供应线索具有经营价值；同时
其 Cookie/localStorage 读取、移除 CSP、宽域权限、内部 Seller 端点和静态费用表不能
成为 KJDS 的身份、费率或执行真源。

当前真实经营起点是一个已绑定 Ozon Listing 和三个 1688 供应候选。目标不是把页面
展示价包装成 Supplier Offer，而是用它快速筛选、明确规格差距、生成询价与小批 Pilot
准备，再由既有报价、利润、内容、审批和执行模块继续闭环。

## best_solution 选择

### 硬约束

- 不复制或持久化浏览器 Cookie、localStorage、验证码、API 密钥或会话。
- 不移除 CSP，不建立任意 URL 代理，不调用未经准入的 Ozon 内部写端点。
- 原始观察先形成不可变 Evidence，并保留 URL、来源、观察时间、操作者和 SHA-256。
- `public_display_price`、新人价、区间最低价和工具估价永远不是正式报价或实际成本。
- 只使用 Decimal、显式币种、时间和价格语义；客户端不重算排序或利润口径。
- 不复制 Product、Supplier Offer、Profit、OperatingTask、Approval 或 Execution 真源。
- 所有平台写入仍消费既有冻结计划、批准、一次性 Permit、Readback 和止损合同。

### 方案

1. **直接移植现有 ERP/插件。** 淘汰。权限面、身份处理、内部端点、静态费率和许可
   不满足硬约束，且会产生第二控制面。
2. **只写入 Research Signal Inbox。** 可行但未选。能保存线索，却丢失变体自然键、
   价格语义、规格差距、批量去重和 Pilot 排序，调用方仍需重复拼装。
3. **新增证据化 `MarketplaceObservationWorkspace`，并由
   `PortfolioPilotWorkspace.prepare()` 组合既有真源。** 选定。外部 Interface 小，
   页面/工具/固定测试样本都通过 Adapter 进入同一规范合同；默认路径深且可替换。
4. **延期。** 淘汰。会继续让真实页面线索停留在浏览器和对话中，无法形成经营任务，
   也无法验证用户要求的批量利润筛选。

选定方案在证据完整、最小权限和可逆性上满足硬约束；相对方案 2 增加一张快照表和一张
明细表，但换来稳定自然键、幂等、来源等级、规格差距和组合级排序，长期风险调整价值更高。

## 决策

### MarketplaceObservationWorkspace

这是一个深 Module。外部 Interface 只有：

```text
capture(request, actor_id) -> ObservationSnapshot
latest(filters) -> list[ObservationItem]
```

`capture` 把调用方提交的原始观察 JSON 本身保存为 C 级 Evidence，规范化来源、页面、
主体、商品、变体、币种、展示价语义、MOQ、规格和目标绑定，计算稳定 item fingerprint
与 snapshot SHA-256，并以 `source + idempotency_key` 失败关闭不同载荷重放。所有结果
固定 `formal_fact_promoted=false`、`supplier_offer_created=false`、
`actual_cost_created=false` 和 `external_write_allowed=false`。

生产 Adapter 首批为人工确认的浏览器观察与卖家工具导出；测试 Adapter 使用固定脱敏
快照。Ozon 官方自身商品继续读取 `MarketplaceCatalogWorkspace`，不重复复制到观察表。

### PortfolioPilotWorkspace

这是调用方默认使用的深 Module。外部 Interface 只有：

```text
prepare(store_ref, product_id, target_specification, policy_id, limits, actor_id)
  -> PortfolioPilotView
```

Implementation 在同一 Seam 后组合：

- 当前 Ozon Catalog 与 Product binding；
- Marketplace Observation 最新候选；
- 服务器版本化保守筛选政策；
- 已有 Supplier Offer / Profit Scenario / Listing readiness；
- Existing OperatingTask / OperationsQueue。

输出区分：

- `observed_spread`：售价减展示价，只是研究价差；
- `screening_contribution`：使用版本化估算政策的悲观/基准筛选值；
- `scenario_cm3`：既有十五项场景 CM3；
- `actual_profit`：只来自 BR-078 的完整实际利润账。

缺少平台费、物流、退货、税费、FX、权利或规格时，不得产生 `pilot_ready=true`。
排序固定为规格匹配度、悲观筛选贡献、来源质量、Evidence 覆盖、风险和 fingerprint，
客户端不得重排为经营结论。阻断使用稳定 fingerprint 写入既有 OperatingTask 与不可变
事件，不建立第二队列。

## Dependency 与 Adapter

- Ozon/1688/卖家工具：true external，使用只读 Adapter 和固定快照 Mock。
- KJDS Catalog、Sourcing、Profit、Task、Execution：remote-owned/in-process，直接复用
  既有 Interface，不复制表。
- PostgreSQL/Evidence Blob：local-substitutable，生产使用 SQL/Blob Adapter，测试使用
  内存 Adapter。
- 保守筛选：in-process，金额与守恒通过 Module Interface 测试。

## 失败模式

- Evidence 无效、URL 非 HTTP(S)、观察时间无时区、未知来源/价格语义、金额非正、
  币种无效、重复自然键或幂等键漂移：拒绝捕获。
- 目标 Product/Listing 不存在或绑定不一致：拒绝准备。
- 规格缺失或不一致：候选保持 `partial/blocked`，不能自动补写。
- 所有外部页面故障、登录、验证码或联系人未加载：创建/更新内部阻断任务，不绕过。
- 页面展示价变化：形成新快照；历史不覆盖。

## 迁移、回滚与验收

- 新增独立 observation snapshot/item 表；回滚只删除新表和路由，不改变既有正式事实。
- 固定样本覆盖精确匹配、规格差距、展示价语义、幂等、坏 Evidence、跨币种和排序。
- API 匿名访问为 401；OpenAPI 显示捕获、读取和 Pilot prepare 合同。
- Web 只显示服务端状态、价差、规格差距、阻断和下一动作。
- 用当前 Ozon Listing 与河北九鸣、隆祥、东奥三个候选形成版本化经营 Evidence。
- 全量后端、Web、迁移、容器健康与桌面/390px 浏览器回归通过。

复审时若页面来源条款不允许保存必要字段、Seller 工具无法合法导出、或误报成本导致
Pilot 最大损失超过批准预算，立即冻结对应 Adapter；正式报价、实际成本和执行合同不受
回滚影响。
