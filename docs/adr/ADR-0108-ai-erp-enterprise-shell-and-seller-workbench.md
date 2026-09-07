# ADR-0108：AI+ERP EnterpriseShell 与 Seller Workbench

状态：Proposed
日期：2026-09-07
范围：KJDS Web UI，首期覆盖 `/seller-os` 与可复用 AI+ERP 组件合同
## 决策摘要

KJDS 采用“ERP 工作台为骨架、AI 决策层为侧栏、Evidence/Action Contract 为控制层”的渐进式 UI 架构。
首期不重写业务 API、不引入新的前端框架、不启用 Ozon 外部写入；以现有 UI2 tokens、Radix primitives 和 Next/React 基线建立深模块 `EnterpriseShell` 与 `AI ERP UI Kit`，再用 adapter 迁移旧页面。

目标界面必须让用户在同一视线内看到：

```text
当前作用域 → 事实状态 → AI 判断 → 证据 → 风险 → 下一动作 → 回读/回滚
```

## 备选方案

### A：UI2 增量迁移（选定）

- 复用现有 UI2 tokens、`AppShell`、`StatusBadge`、`DataTable` 和 `EvidenceDrawer`。
- 新增统一 EnterpriseShell 与 AI ERP 组件合同。
- 旧页面通过 adapter 迁移，保留 alias 和回滚路径。
- 不改变业务权威、权限和外部写入边界。

优点是变更可分片验证、可回滚、与当前 UI2 证据和无障碍基础兼容；缺点是迁移期间会暂时保留少量 legacy 样式。

### B：全站一次性重写

拒绝。它会同时改变导航、数据请求、权限、状态语义和视觉层，无法区分 UI 缺陷与业务回归，也会放大当前共享 WIP 的冲突面。

### C：引入全量第三方企业组件库

拒绝。当前已有 Radix + UI2 + TanStack Table 基线；并行引入 Ant/Arco/Semi 会重复 Modal、Table、Form、token 和无障碍语义，增加迁移成本和视觉分裂。

## 设计合同

### EnterpriseShell

```text
NavigationRail
→ ContextBar
→ Breadcrumb/PageHeader
→ MainWorkbench
→ AI/Evidence Inspector
→ Activity/Audit Dock
```

Shell 只负责布局、导航、上下文和状态边界，不计算利润、Gate、权限或业务排序。

### ScopeContext

```ts
type ScopeContext = {
  tenant: string
  entity: string
  store?: string
  warehouse?: string
  sku?: string
  currency: string
  timezone: string
  asOf?: string
  snapshotHash?: string
  permissionScope?: string
}
```

### DataState

```ts
type DataState<T> = {
  value?: T
  status: "loading" | "ready" | "no_data" | "partial" | "stale" |
    "blocked" | "forbidden" | "conflicted" | "unknown_outcome" | "error"
  quality?: string
  freshness?: string
  asOf?: string
  snapshotHash?: string
  sourceRefs?: string[]
}
```

`NO_DATA` 不能显示为 0，`UNKNOWN_OUTCOME` 不能被渲染为成功或失败。

### ActionContract

```text
recommended
→ preflight
→ permit_ready
→ executing
→ readback_pending
→ verified | unknown_outcome
→ rollback | recovery
```

UI 只呈现服务端动作状态和原因；任何写入仍由既有 API、Permit、租约、审计、读回和回滚门禁决定。

## Seller Workbench 首期布局

`/seller-os` 从营销式 Hero 改为经营工作台：

1. 上方显示主体、授权店铺、数据时点、快照、只读/写边界和 freshness。
2. 左侧显示 Seller OS 二级工作台：诊断、策略、规则、组合、店群、增长。
3. 主区显示“今日经营判断”：规模、证据覆盖、主要阻断、下一动作和风险预算。
4. 中段显示 AI 诊断表单与服务端结果，结果和自报输入严格分离。
5. 下段显示动作就绪度、策略包、候选和跨层级策略矩阵。
6. 右侧 Inspector 显示来源、证据、规则版本、模型建议、成本和动作合同。

首期页面不展示伪造趋势、虚构商品、自动上架数量或未经证据支持的收益。

## 视觉和响应式合同

- 浅色运营主题使用 UI2 semantic tokens；深色只作为显式 monitor variant。
- 8px spacing、12/14/16/20/28/40 字级、44px 交互目标。
- 1440px：240px 导航 + 56px ContextBar + 12 栏工作区 + 360px Inspector。
- 1280px：Inspector 抽屉化，顶部低频动作收进更多菜单。
- 768px：导航和 Inspector 使用 Sheet。
- 390px：垂直工作区、底部导航和固定动作栏，`scrollWidth <= clientWidth`。
- `prefers-reduced-motion`、键盘焦点、`aria-live`、表格 caption/headers 和图表数据表替代必须保留。

## 性能和边界

当前首页存在多 endpoint fan-out；首期新模块采用服务端投影接口和按 scope/snapshot 的查询键，目标是首屏聚合读请求不超过 8 个、N+1 为 0、旧响应不能覆盖新作用域。

不在本 ADR 中引入新数据库、Redis、Kafka、向量库、模型运行时或 Ozon 写权限。React/Next 继续使用当前仓库版本；根据 `react_19_2_next_16_delivery_patterns` 的 registry 记录，本次仅采用已验证的现有能力，`frontier_review=checked_no_change`。

## 验收

- `/seller-os` 在 390、768、1280、1440px 无横向溢出。
- 首屏能同时读到 scope、数据状态、阻断、下一动作和外部写边界。
- 所有数字经过 `DataState` 渲染，缺失值不会变成 0。
- 只读页面不产生 Ozon 写请求。
- AI 建议有来源、快照、版本、置信度、成本和风险。
- ActionContract 的状态和按钮由服务端投影决定。
- Axe serious/critical 为零，键盘操作和焦点恢复通过。
- 旧 Seller OS 路由仍可访问，且可回退到旧组件。
- 变更拥有 exact HEAD、测试回执、截图回执和 rollback_ref。
