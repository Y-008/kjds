# ADR-0063：市场验证 Must-have 原生覆盖与 ERP Agent 化

Status: Accepted<br>
Date: 2026-07-29<br>
Scope: M0–M4 / KJDS AI ERP

## Context

毛子 ERP、荔枝 Ozon 助手、芒果店长、店小秘、妙手、无忧易售、Seerfar
和 LinkFox 的公开资料、用户提供截图及 `D:\KJDS\ozon` 只读样本，证明卖家工具
已经形成采集、商品、刊登、订单、采购、仓储、物流、客服、财务、广告、促销、
分析与媒体等成熟工作流。KJDS 不能用少量 AI 页面替代这些基础能力。

同时，样本中存在 Cookie/session 复用、宽域扩展、静态费用表、无权利图片复制
和无治理批量写等不可接受实现。复制二进制或旧技术路线也会建立第二套事实权威。

## Decision

1. `competitive_capability_patterns.json` 是市场基线 Registry，八类产品均为
   `must_have_native_parity`；安全能力不得遗漏。
2. 不安全实现标为 `prohibited_with_safe_replacement`，但同一卖家 JTBD 必须由
   KJDS 官方 API/授权导出/最小权限助手和受控执行完成。
3. 每项覆盖必须分别取得 code、migration、API、Web、permission、runtime replay
   和 Evidence；映射、菜单和模型自述不算实现。
4. 第三方只提供 C/D 级能力观察，不是 KJDS runtime dependency、Fact authority、
   credential source、fee source 或 media-rights source。
5. 基础覆盖率与 AI operating advantage 分开验收。只有前者完整，后者才可用于
   “超越”评价。
6. AI 化采用 12 个责任 Agent；每个 Agent 只输出版本化内部 artifact，随后由
   deterministic/schema/rule/Evidence/Harness verifier 观察真实状态并写回 Graph。
7. 所有 Agent 共用一个 scoped PIM/OMS/Inventory/Finance/Evidence/Rule 内核；
   不能自批、签发 Permit、修改平台/库存/价格、下采购单或付款。

## Consequences

- Commerce OS 会如实显示每家 `verified/required` 和原生缺口；当前 0 不会被隐藏。
- 基础能力量大，但通过一个经营内核和深模块 seam 实现，不为每家 ERP 复制一套。
- Maozi/Lizhi 的 Cookie、`<all_urls>`、内部接口和静态文件继续只作 rejected
  alternative；许可/安全审查通过的开源组件可以在 Adapter 内复用。
- 0.59 PM/RA Release Gates、Pilot Gate 与 Final Gate 不因本 ADR 自动通过。
