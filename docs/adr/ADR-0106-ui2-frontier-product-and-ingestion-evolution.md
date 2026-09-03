# ADR-0106：KJDS UI 2.0 向经营决策与证据采集平台演进

- 状态：Proposed
- 日期：2026-08-20
- 范围：UI 2.1 BI / Wallboard / Briefing、数据搜索与抓取、AI 辅助分析
- 关联：`ADR-0105-ui2-operating-visualization-layer.md`、`docs/project/evidence/20260820_UI2_BI_SCOPE_VERIFICATION.md`

## 决策摘要

KJDS 不再把目标定义为“做一个更漂亮的 Dashboard”，而定义为：在同一作用域与同一数据时点下，把 **发现信号 → 证据采集 → 事实晋级 → 指标解释 → 决策动作 → 结果复核** 做成可追溯的经营系统。

本 ADR 只批准产品/架构边界与渐进式 UI 路线，不批准新建第二套事实库、不批准前端计算权威利润、不批准未审查的自动写入或批量抓取。

## 当前已落地的最小切片

- `/bi/overview`、`/bi/wallboard`、`/bi/briefing` 共用 `useBiProjection` 的 session-first、同 `store_ref/as_of` 作用域。
- 共享 UI2 层表达 `freshness`、`data_as_of`、`no_data`、`partial`、`blocked`、`forbidden`、`conflicted`、Evidence 入口和数据表回退。
- Overview 具备“结论 → 证据边界 → 下一动作 → 责任与复核”的决策脊柱；覆盖率图只显示已通过 truth-admission 的真实指标。
- 失败刷新不会保留旧快照冒充当前 READY；Evidence 只从 scoped 投影返回的 ID 按需读取 metadata / verify / lineage，原始内容需要显式下载。

## 一、产品全景：八个维度再补两层

原有八维（用户、决策、数据、交互、风险、节奏、终端、治理）继续保留，并增加两层：

### 9. 证据生命周期

`discovered → fetched → normalized → validated → promoted → consumed → superseded/revoked`。

每个状态要有进入条件、责任人、可见 UI、回滚动作。抓到网页不等于事实成立；抽取出的字段必须携带来源、时点、hash、解析器版本与置信度。

### 10. 组织与责任生命周期

每个指标异常必须能落到“谁确认、谁处理、谁复核、何时过期”。AI 建议与真实动作分离，动作需角色权限、幂等键、审批、回执、撤销/补偿和 kill switch。

## 二、搜索/抓取的正确架构

前端只消费投影，不直接抓网页，也不在浏览器里拼利润。采集层建议按以下边界拆分：

```text
Source Registry
  → Acquisition Adapters (API / JSON-LD / HTML / Headless)
  → Raw Evidence (immutable bytes + metadata + content hash)
  → Normalizer (schema/versioned parser)
  → Canonical Facts (server-owned, scoped)
  → Semantic Metric Layer (definition + formula + allowed dimensions)
  → Read Projections (overview / domain / wallboard / briefing)
  → Recommendation / Approval / Receipt
```

### 抓取前必须存在的 Source Registry

每个来源至少登记：`source_ref`、拥有者、授权方式、允许的采集模式、robots/服务条款约束、更新频率、时区、预期字段、敏感字段、保留期限、失败联系人、parser 版本和下线日期。

### 采集任务必须可重放、可停止

- URL canonicalization、分页游标、去重键、`idempotency_key`、超时、限速、退避、熔断、最大深度和最大成本。
- 每次采集记录 `run_id`、`requested_at`、`fetched_at`、HTTP 状态、响应头摘要、内容 hash、解析器版本、代理/会话类别和失败原因；不记录或展示秘密令牌。
- 抓取失败、被封、验证码、登录过期、结构漂移、空响应分别建模，不能都折叠成“无数据”。
- 增量与回填分开；回填必须指定 cutoff 和影响范围，不能默默覆盖最新投影。
- 任意外部来源的事实晋级需要可审计的 promotion decision；LLM 只能提出候选字段与引用，不能直接提升权威级别。

### 结构漂移与质量闸门

对字段缺失、类型变化、单位变化、币种/时区变化、重复率、日期断档、跨源不一致建立 contract test。质量失败时投影显示 `partial` / `stale` / `conflicted` 和可恢复动作，而不是用 0、空字符串或上一版值填充。

## 三、指标语义层：六张图必须共享一套口径

附件中提到的六类分析应进入语义层，而不是各页面各算一遍：

1. 流量转化漏斗：曝光 → 点击 → 访问 → 加购 → 支付；每步定义分母、去重键和时点。
2. 流量质量四象限：流量规模 × 支付转化率；低样本区标记 `low_confidence`。
3. 商品销售贡献：销售额、订单、毛利贡献和集中度；禁止只按销量排序。
4. 销售额 × 毛利率矩阵：核心利润、走量、潜力、低效四类，象限边界可配置且可追溯。
5. 投放花费 × 利润质量：ROAS 不是利润；明确归因窗口、费用分摊和退款/履约扣除。
6. 商品动作优先级：将洞察转为建议动作，带负责人、证据、预期收益、截止时间与复核指标。

每个 KPI 的最小合同：`metric_id`、显示名、定义、公式版本、单位、币种、时区、粒度、分母、数据时点、freshness SLA、对比基准、source refs、evidence refs、权限和状态。

## 四、UI 产品架构

### 三种模式，不混成一个页面

- **经营驾驶舱**：一句结论、6 个关键指标、1 个趋势、1 个根因、1 个动作；默认密度低、结论优先。
- **BI 分析台**：作用域、时间、维度、对比、钻取、表格、导出和证据；默认密度高、可复盘。
- **大屏/简报**：16:9、只读、异常置顶、轮播/手动翻页、固定时点和打印/投屏安全边界。

### 每个可视化模块的固定骨架

`结论标题 → 口径/时点/新鲜度 → 主视觉 → 数据表回退 → 异常解释 → Evidence/Lineage → 下一动作`。

图表越复杂，越要把“我为什么相信这个数字”放在同一视线内；没有历史序列就显示 `no_data`，不要绘制假趋势。

### 视觉方向

保留深色大屏和浅色 BI 两套主题，但共享语义色和 token：

- 中性灰：事实/未判断；蓝：导航/信息；绿：已验证/健康；黄：需复核；红：阻断/风险；紫：AI 建议但未授权。
- 用字体层级、留白、对齐和数据密度建立层次，不用发光、渐变和装饰地图掩盖口径缺失。
- 所有图表提供可读表格、键盘焦点、`aria-label`、`prefers-reduced-motion` 和 390px 降级布局。

## 五、AI 能做什么，不能做什么

### 可以做

- 从限定来源候选中规划抓取顺序、总结变化、生成假设、解释指标树、建议下一步。
- 对每条结论绑定引用片段、evidence_id、source_as_of、模型版本、prompt 版本和置信度。
- 生成查询草稿、字段映射、埋点草案和评审清单，由服务器合同和人工复核拦截。

### 不可以做

- 不能凭 LLM 输出创建权威事实、补齐缺失历史、把 `no_data` 变成 0、绕过租户/店铺权限或直接调用外部写接口。
- 不能把搜索摘要、相似商品、口头数字或单一网页信号直接晋级为财务/合规结论。
- 不能让推荐动作与真实动作共用同一个按钮或同一个权限。

建议采用“两阶段 AI”：第一阶段检索/抽取候选并输出引用，第二阶段由确定性 validator、交叉来源和人工角色确认后才进入语义层。

## 六、开源选型：采用、评估、暂不引入

### 现在采用

- 现有 Radix primitives + CSS Modules + UI2 tokens：保持可组合、可控和无障碍，不再引入第二套全量 Design System。
- 现有 TanStack Table：作为无头表格能力，逐步补排序、筛选、虚拟化和列状态；业务口径仍在服务器。
- 现有 Recharts：Overview 的轻量图表，使用 `accessibilityLayer` 和数据表回退。
- 已安装并使用 Anthropic `frontend-design` Skill（固定 commit）与 `SpaceZephyr/pm-skills` 的 PM 子技能；它们只影响设计/评审工作流，不进入业务运行时。

### 评估后再引入

- [Apache ECharts](https://github.com/apache/echarts)：适合高密度大屏、dataZoom、brush、地图和复杂联动；等历史序列与语义合同成熟后，以独立 `ChartAdapter` 引入，避免页面直接依赖 ECharts option。
- [Storybook](https://github.com/storybookjs/storybook)：作为 UI2 组件契约、状态样例、视觉回归与 a11y story 的治理层；先覆盖 `MetricCard/ChartFrame/DataTable/EvidenceDrawer`。
- [Vega-Lite](https://github.com/vega/vega-lite)：适合将分析图形声明化、版本化和导出；先用于探索性分析，不替代业务投影。
- [React Aria](https://github.com/adobe/react-spectrum)：若 Radix 在复杂表格/组合框/拖拽场景出现缺口，再按组件边界引入，不与 Radix 全量并存。

### 暂不引入

- Ant Design、Arco、Semi 三者不同时引入；会造成 token、Modal、Table、Form 和交互语义重复。若未来需要全量企业组件，只能先做一次迁移评审并选一个。
- Perspective、AG Grid 等高性能网格等数据量和实时流真正达到阈值再评估，避免为演示数据引入重量级运行时。
- 任何会在运行时从可变 `main` 分支拉取规则的 UI skill 都不进入生产链路；技能必须固定提交、可审计、可回滚。

## 七、P0/P1/P2 路线

### P0：可信与可追责（上线前）

- 同一 `store_ref/as_of` 贯穿 session、analytics、briefing、wallboard；未授权请求为 0。
- 统一运行时合同，严格区分 `no_data`、`zero`、`partial`、`blocked`、`stale`、`conflicted`、`forbidden`。
- 抓取任务具备 source registry、幂等、重试/熔断、schema drift、证据 hash、审计和 kill switch。
- 每个 KPI 都能查看口径、时点、freshness、来源和证据；失败刷新不显示旧 READY。

### P1：分析效率（下一迭代）

- 指标目录、指标树、六张分析图的统一语义配置。
- Storybook 状态矩阵与视觉回归；TanStack Table 列配置/虚拟滚动；ECharts `ChartAdapter` 试点。
- 证据 lineage 图、异常假设、责任人/截止时间、导出和简报打印。
- 抓取可观测性：覆盖率、freshness lag、blocked rate、parser drift、cost/run、人工晋级率。

### P2：规模与智能（稳定后）

- Temporal 或等价 durable workflow 承载长任务、回填和人工等待；每一步可重放。
- dlt/Airbyte 只负责适配与搬运，不能替代 KJDS 的证据晋级和语义层。
- DuckDB/列式分析层用于离线探索；OpenTelemetry 贯通浏览器、API、抓取和投影的 trace/metric/log。
- AI 生成“变化解释 + 可验证假设 + 下一动作”，仍以引用、权限和人工确认作为上线门槛。

## 八、上线验收与失败回滚

### 验收

- 视觉：390/1280/1440/1920 无横向溢出；键盘、焦点恢复、skip link、reduced motion、axe 通过；图表全部有表格回退。
- 数据：同作用域同 cutoff；无历史不画趋势；每个 KPI 有口径/单位/时点/freshness/evidence；异常与筛选空结果分开。
- 采集：API/HTML/headless 失败可区分；重复运行不重复晋级；schema drift 不污染 canonical facts；回填有 cutoff；kill switch 生效。
- AI：所有结论可追溯到 evidence；模型/提示版本可审计；无权限绕过、无未授权写入、无 PII 泄露。

### 回滚

UI 回滚只删除 `/bi/*` 入口或关闭 feature flag；采集回滚停止对应 source adapter、保留 immutable raw evidence、冻结晋级，不删除历史事实。任何 schema/metric 版本回退必须保留旧版本并通过 projection version 切换，不做破坏性迁移。

## 结论

最值得继续投入的不是再加十种图，而是把 **来源可信度、作用域、时点、语义口径、证据穿透、责任动作、失败恢复** 变成 UI 和后端都遵守的同一套产品语言。这样大屏才是决策终端，BI 才是分析工具，AI 才是受控的加速器，而不是另一套会制造“看起来很专业”的数字系统。
