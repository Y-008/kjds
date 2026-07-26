# ADR-0028：点线面到真实业务工作区的全链路穿透

- 状态：Accepted
- 日期：2026-07-26
- 决策 Owner：产品负责人、经营负责人、工程负责人
- 影响范围：能力图谱、经营分析、控制平面 API、Next.js Web
- 决策合同：`best_solution/1.0.0`
- 首发版本：`0.56.0`
- 需求：BR-077 / BAS-102

## 背景

0.55.0 已把 LinkFox 公开功能参考和 KJDS 经营内核组织成 143 个原子点、14 条价值流和
8 个经营控制面，但“进入真实工作区”仍是浅接口：136 个点只跳转到根页面锚点，7 个点
跳回图谱自身，线和面没有工作区合同。用户可以阅读节点，却无法携带节点、阶段、对象、
Evidence 和下一动作上下文继续工作。

## `best_solution` 评估

| 方案 | 硬约束 | 长期价值 | TCO / 风险 | 结论 |
|---|---|---|---|---|
| A. 为 165 个节点分别手写页面 | 可实现，但重复状态和 Gate | 页面数量多，语义易漂移 | 维护和测试成本最高 | 淘汰 |
| B. 前端从图谱拼装工作区 | 违反客户端不得重算路径/状态 | 初始快，形成第二状态真源 | 事实与权限误导风险高 | 淘汰 |
| C. 只把链接改到根页面锚点 | 不满足上下文穿透 | 无新增能力 | 继续出现“进去没有内容” | 淘汰 |
| D. 一个服务端只读深模块 + 一个参数化 Web 工作区 | 通过全部边界 | 一个接口覆盖 143/14/8，复用真实经营投影 | 无迁移、无新依赖、可回滚 | 选择 |
| E. 引入图数据库/工作流引擎 | 缺少规模和长事务证据 | 远期可能有用 | 当前增加部署和权限面 | 延期 |

## 决策

新增 `OperatingWorkspace.snapshot(kind, item_id, store_ref)`，作为调用方与测试共同使用的
唯一外部 interface。实现内部组合两个现有只读模块：

1. `CrossBorderCapabilityAtlas.snapshot()` 提供点、线、面的版本化结构、控制合同与来源边界。
2. `OperatingAnalyticsService.snapshot(store_ref)` 提供当前店铺的真实阶段、事实、
   Evidence 引用、数据缺口、焦点 Listing、优先事项和下一动作。

模块隐藏节点查找、点线面展开、阶段排序、领域工作区映射、真实状态匹配、缺数据降级、
相关节点导航和规范哈希。返回合同固定区分：

- `contract_status`：图谱中的 `implemented/ready/gated/research_only`；
- `runtime_status`：经营投影中的 `verified/in_progress/blocked/no_data/contract_only`；
- `workspace_href`：当前点/线/面的独立工作区；
- `domain_href`：既有真实领域工作区锚点；
- `facts/evidence_ids/data_gaps/next_action`：只来自服务端投影。

## 路由与接口

- Point：`/operations/points/{point_id}`
- Line：`/operations/lines/{stream_id}`
- Surface：`/operations/surfaces/{surface_id}`
- API：`GET /v1/operating-workspaces/{kind}/{item_id}?store_ref=ozon-primary`

Next.js 16 动态段在服务端页面中异步解析 `params`，交互和无缓存认证请求集中在一个
Client Component。图谱继续使用 `<Link>`，不拼接不可信 URL。

## 固定边界

- 工作区只读，不创建新经营事实，不保存页面状态，不新增数据库。
- `implemented` 只证明仓库合同存在，不证明当前店铺已完成该阶段。
- `ready` 只证明产品合同可实施，不证明 Provider、平台或模型已接入。
- LinkFox 仍是 C 级公开工作流参考。
- 所有外部写动作继续经过 Evidence、独立批准、一次性 Permit、平台回读、Kill Switch
  和补偿；本模块只导航，不获得写权限。
- 缺少真实数据必须显示 `no_data`、`blocked` 或 `contract_only`。

## 验收

- 确定性注册表检查证明 143/143 点、14/14 线、8/8 面都有独立工作区路由。
- 模块 interface 测试覆盖三种 kind、全部 14 条线、未知 ID、稳定哈希、真实/合同状态分离。
- 认证 API 只有 GET；匿名请求失败关闭；OpenAPI 固化。
- Web 从图谱点、线、面均可进入工作区，工作区可回图谱并导航既有领域模块。
- 至少逐条验证 14 条线均有阶段、事实/缺口、下一动作和异常/接管信息。
- 桌面与移动端无横向溢出；loading/error/unknown/empty/success 状态可见。
- Python、Web、PostgreSQL、OpenAPI、secrets 和 Git 门禁通过。

## 复审触发

- 需要在工作区直接执行外部写动作；
- 第二个真实平台或店铺进入运行；
- 需要保存跨会话任务状态；
- 节点超过 500 或出现真实多跳图查询压力；
- 真实业务证明需要工作流引擎或图数据库。
