# 开源 ERP 与电商内核最佳方案

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-ARCH-OSS-ERP-001 |
| status | Conditional decision; no production install |
| version | 1.1 |
| captured_at | 2026-07-20 |
| next_review | ERP 隔离 PoC 或自有商城立项时 |

## 结论先行

ERP 是标准经营底座，不是“大卖护城河”。KJDS 不应继续自研完整采购、库存、供应商、应收应付和总账，也不应现在把整套系统迁入某个 ERP。

当前最佳结构是：

1. KJDS 继续拥有商品全球身份、Evidence、来源血缘、真实 CM3、决策、实验、审批、审计和受控执行；
2. Ozon 官方 API/导出经版本化适配器进入 KJDS，浏览器操作只作缺少 API 时的受控兜底；
3. ERPNext 作为确定性交易内核的首选隔离 PoC，候选职责只包括采购单、收货、库存、供应商、应收应付和会计凭证；
4. 同一业务对象只能有一个可写 Owner。若 ERPNext 晋升，KJDS 保存其只读 Canonical 投影、原始引用和对账结果，不再维护第二份可写库存/会计事实；
5. Medusa、Saleor、Vendure只在自有独立站、DTC、B2B 或 Agent Commerce 成为真实渠道时重新评估。

## 为什么不是“安装一个 ERP 就完成全链路”

所有候选都缺少已经核验的 Ozon 中国卖家原生闭环，也不会自动解决 Ozon 费用分类、俄罗斯/中国税务口径、官方结算、银行到账、头程凭证、商品合规、因果增量和 Agent 权限。全链路仍需要 KJDS 的平台适配、证据、对账和决策层。

真正的差异化来自：

- 一份能追到订单、包裹、结算、银行、税单和汇率原件的利润事实；
- 针对国家、平台、类目、库存和竞争状态学习“何时采取什么策略”的因果知识；
- 把评论、退货、客服和内容实验转成产品改良与独家供应链；
- 所有 Agent 都在预算、权限、审批、回滚和责任账内运行；
- 每次成功和失败都形成可迁移的商业基因，而不是只生成一份报告。

## 候选比较

| 候选 | 最适合解决 | 当前判断 | 淘汰/暂缓原因 |
|---|---|---|---|
| ERPNext | 采购、库存、供应商、销售、会计、多币种 | 首选隔离 PoC | 仍需独立 Frappe/MariaDB 运维、Ozon 适配和中俄会计本地化核验 |
| Odoo Community | 更广的企业模块生态 | 第二候选 | 社区/企业功能边界、定制和升级成本更重，当前没有胜过 ERPNext 的实证 |
| Dolibarr | 较简单的中小企业 ERP | 备用 | PHP 技术栈与现有 Python/PostgreSQL 控制面适配较弱 |
| Medusa | 自有 DTC/B2B 商城 | 延期 | 是 Commerce Framework，不是会计 ERP；当前会重复尚未需要的商城能力 |
| Saleor | 多渠道 Headless Commerce | 延期 | GraphQL/API-first 很强，但不是采购会计内核，当前架构与运维税过高 |
| Vendure | 插件式 TypeScript Commerce | 延期 | 同样偏商城交易，不解决 Ozon 结算与会计真相 |
| 继续全部自研 | 完全控制 | 淘汰 | 重造库存、采购和会计会消耗核心资源，并增加正确性与审计风险 |

## 官方与原始来源

- [ERPNext GitHub](https://github.com/frappe/erpnext)：GPL-3.0；项目声明覆盖 Accounting、Order Management、Inventory、Supplier、Manufacturing 等能力。
- [Frappe REST API](https://docs.frappe.io/framework/user/en/api/rest)：DocType 自动提供 REST CRUD，并按专用用户角色校验权限。
- [Frappe Webhooks](https://docs.frappe.io/framework/v14/user/en/guides/integration/webhooks)：支持事件回调与 HMAC-SHA256 签名。
- [ERPNext Multi Currency](https://docs.frappe.io/erpnext/multi-currency-accounting) 与 [库存会计](https://docs.frappe.io/erpnext/accounting-of-inventory-stock)：提供多币种和库存总账基础，但本地税务仍须专家复核。
- [Odoo GitHub](https://github.com/odoo/odoo)、[Medusa GitHub](https://github.com/medusajs/medusa)、[Saleor GitHub](https://github.com/saleor/saleor)、[Vendure GitHub](https://github.com/vendurehq/vendure)、[Dolibarr GitHub](https://github.com/Dolibarr/dolibarr)。

以上只证明公开能力和许可证快照，不证明已适配本项目；注册表保持 `requires_review: true`。

## ERPNext 隔离 PoC 的硬门

PoC 不连接真实卖家写权限，不导入客户隐私，不自动生成会计凭证。只使用一组脱敏或测试样本验证：

1. KJDS Product/SKU ↔ ERPNext Item 的稳定外部 ID；
2. Supplier Quote → Purchase Order → Purchase Receipt → Landed Cost 的单据链；
3. Ozon Order/Return/Settlement → Sales/Journal/Payment 候选映射；
4. RUB/CNY 交易币种、记账币种、成交/结算/回款汇率的分离；
5. 每条同步的幂等键、原始 Evidence ID、版本、失败重放和反向对账；
6. 备份恢复、升级、API 限权、Webhook 验签和完整卸载；
7. 同一笔样本在 KJDS 贡献利润与 ERP 会计结果的差异可解释。

只有七项全部通过，且人工操作量或会计正确性确实改善，才允许 ADR 将部分确定性单据 Owner 迁给 ERPNext。失败则完全删除 PoC，不影响 KJDS 主链。

合同级第一步已经完成，见 [ADR-0013](../adr/ADR-0013-erpnext-sidecar-poc-contract.md) 与机器注册表 [`erpnext_poc_contract.json`](registries/erpnext_poc_contract.json)。当前只生成 `poc_dry_run` 草稿 envelope，覆盖 Item、Purchase Order 和 Journal Entry 候选，以及 HMAC-SHA256 验签和只读差异对账；没有远程客户端、生产凭证或自动提交能力。其余单据等真实脱敏样本出现后逐项补齐，不凭空猜测字段。

## 形成“大卖”的产品路线

阶段一不是“上线更多模块”，而是用一个真实 SKU 完成：需求原件 → 三家真实报价 → 到岸成本 → 合规证据 → 商品素材 → Ozon 草稿 → 订单 → 退货 → 结算 → 银行/税务/汇率 → CM3。

阶段二用同一事实链做选品、价格、广告、内容、库存和产品改良实验。阶段三再把验证过的策略作为条件化 Skill，有限自动执行。阶段四才复制到第二平台和自有渠道。

先进感的验收不是功能数量，而是：比竞品更早发现真实利润变化、更快完成低成本实验、更低错误率地执行，并把跨平台结果沉淀为下一次可复用的经营规律。
