# ADR-0024：RFQ 人工发送证明与独立核验

- 状态：Accepted
- 日期：2026-07-26
- 决策 Owner：供应链负责人、合规复核人、平台运营负责人
- 影响范围：1688/Alibaba 询价、供应商回复、三家报价、Evidence Ledger

## 背景

`SupplierRfqWorkspace` 已能为真实 Ozon Listing 冻结可比询价正文，但“复制到剪贴板”不能证明消息
已经发送，也不能证明发给了哪个独立供应商。若直接让操作者勾选“已发送”，三家供应商、发送时间、
会话上下文和实际消息内容都不可复验，后续回复也可能错误归因。

系统当前没有经过条款与身份治理的 1688 消息写入适配器。因此本阶段不自动发送，而为人工发送建立
可验证交接：原始平台证明进入 Evidence，另一身份复核，供应商回复再引用该证明。

## 决策

新增 `SupplierRfqDispatchWorkspace` 深模块。其接口隐藏 RFQ 复验、供应商身份规范化、发送时间
约束、原文比对、证明摘要、幂等、独立复核、状态计算和回复归因：

1. 只接受完整有效的 `supplier_rfq_package`；发送正文必须与冻结 `message_text` 逐字一致。
2. 每份证明必须包含供应商稳定标识、平台、供应商/店铺 URL、会话或消息编号、带时区发送时间、
   幂等键和非空原始截图/导出。
3. 发送时间不得早于 RFQ 创建时间，不得在服务器当前时间之后，也不得晚于 RFQ 回复截止时间。
4. 原件以 B 级 `supplier_rfq_dispatch` 保存，冻结 RFQ Evidence/hash、消息 SHA-256、供应商身份
   哈希、证明 SHA-256 和 `dispatch_hash`。同一 source ref 只允许相同事实与相同原件。
5. 上传者不能自审。接受必须由另一身份同时确认：平台原件真实、供应商身份匹配、RFQ 全文匹配、
   发送时间与会话匹配；结论以 A 级 `supplier_rfq_dispatch_review` Evidence 保存。
6. 接受的发送证明只表示“存在已复核的发送记录”；`delivery_confirmed`、`supplier_replied`、
   `counts_as_supplier_quote` 和所有自动外部动作仍为 false。
7. 报价原件可引用 dispatch Evidence。服务端必须复验 Product、RFQ 和 supplier ref 一致，并建立
   dispatch Evidence → quote Evidence 的 `supplier_response_to_dispatch` 血缘；该血缘不替代
   BR-070 报价独立复核。

## 数据与接口

复用不可变 Evidence Ledger，不新增可变发送状态表：

- 发送原件 source：`supplier_rfq_dispatch`，Grade B
- 复核 source：`supplier_rfq_dispatch_review`，Grade A
- source ref：
  `supplier-rfq-dispatch://{rfq_evidence_id}/{supplier_identity_hash}/{idempotency_key}`
- lineage：
  - RFQ Evidence → dispatch Evidence：`rfq_dispatch_context_for`
  - dispatch Evidence → Product：`supplier_outreach_for`
  - review Evidence → dispatch Evidence：`supplier_rfq_dispatch_review`
  - dispatch Evidence → quote Evidence：`supplier_response_to_dispatch`

HTTP 接口：

- `POST /v1/sourcing/rfq-dispatches`
- `GET /v1/sourcing/rfq-dispatches`
- `GET /v1/sourcing/rfq-dispatches/{evidence_id}`
- `POST /v1/sourcing/rfq-dispatches/{evidence_id}/authority-review`
- 既有报价上传增加可选 `rfq_dispatch_evidence_id`

## 被否决方案

- 用 checkbox 记录“已发送”：没有原件、消息定位或全文证明。
- 把复制时间当发送时间：剪贴板不是外部平台回执。
- 只保存供应商 URL：无法证明会话、消息内容和发送时间。
- 发送证明自动成为报价：外联不证明供应商回复或任何商业条款。
- 当前直接自动化 1688 消息：尚无官方身份、条款许可、单次审批、幂等发送和平台消息 ID 回读。

## 复核

当受支持供应商平台具备合法消息写入适配器、专用凭证、单次批准、服务端 message ID、送达状态和
失败/不确定回读合同后，可新增自动发送 adapter；它仍必须生成相同 dispatch Evidence，不得绕过
本模块。最迟于 2026-10-26 复核本 ADR。
