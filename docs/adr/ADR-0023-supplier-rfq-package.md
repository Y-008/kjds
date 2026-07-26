# ADR-0023：已有 Listing 的供应商 RFQ 冻结包

- 状态：Accepted
- 日期：2026-07-26
- 决策 Owner：供应链负责人、商品负责人、合规复核人
- 影响范围：已有 Ozon 商品、1688 询价、供应商报价、CM3

## 背景

真实 Ozon Listing 已能绑定 Canonical Product，供应商报价也已有“原件—独立复核—三报价最终化”
权威门，但两者之间没有可执行的询价规格。操作者只能在 1688 临时组织文字，容易让三家供应商收到
不同规格，也无法证明某份回复对应哪个冻结请求。

当前商品 `2105343364UB` 的目录同时存在可核验观察和不可靠内容：重量/尺寸来自 Seller 原始响应，
但标题和详情含明显机器翻译污染；详情还列出多个载重档位。因此不能把页面描述自动当成已确认的
采购规格。

## 决策

新增 `SupplierRfqWorkspace` 深模块，其小接口隐藏目录复验、身份解析、规格规范化、正文生成、
幂等、Evidence 固化和血缘：

1. 只接受已经绑定 Product 的最新 Ozon Catalog 条目；请求必须带当前 `item_hash` 和
   `confirmed=true`，旧页面不能静默生成 RFQ。
2. RFQ 严格区分：
   - `catalog_observation`：目录名称、包装重量/尺寸、Marketplace SKU、观察时间与源 Evidence；
   - `buyer_requirement`：操作者要求供应商逐项确认的规格，不自动晋升为 Product Fact。
3. 数量阶梯必须去重升序；逐项规格、包装要求、所需文件、目的地和回复期限均经服务端限长、
   去空和确定性排序。
4. 模块生成固定中文正文、供应商必须回复的商业/规格/物流/文件清单，以及仍未被供应商确认的
   问题。正文明确“询价不代表下单或付款”。
5. 完整包以 C 级 `supplier_rfq_package` Evidence 保存；`product + idempotency_key` 对应一个
   不可变来源引用。相同键内容变化必须冲突，PostgreSQL 唯一索引处理并发重放。
6. RFQ 只提供显示与复制，不自动打开 1688、发送消息、联系供应商、下单、付款或创建
   `SupplierOffer`。
7. 上传供应商回复时可选引用 RFQ Evidence；服务端复验 RFQ 属于同一 Product，并建立
   `supplier_response_context_for` 血缘。该引用不证明规格匹配，仍须 BR-070 独立复核。

## 数据与接口

RFQ 不新增第二套可变业务表，而复用不可变 Evidence Ledger：

- source：`supplier_rfq_package`
- grade：`C`
- content：`supplier-rfq-package-v1` Canonical JSON
- source_ref：`supplier-rfq://{product_id}/{idempotency_key}`
- 关系：Catalog Evidence → RFQ Evidence；RFQ Evidence → Product；RFQ Evidence → 报价原件

HTTP 接口：

- `POST /v1/sourcing/rfq-packages`
- `GET /v1/sourcing/rfq-packages`
- `GET /v1/sourcing/rfq-packages/{evidence_id}`
- 既有 `POST /v1/sourcing/quote-evidence` 增加可选 `rfq_package_evidence_id`

## 被否决方案

- 直接用 Ozon 标题/详情生成采购规格：机器翻译、多个档位和未核验宣传会被误当事实。
- 新建可变 RFQ/报价工作流表：会与 Evidence、报价原件和 lineage 形成第二事实源。
- 每个供应商自由编辑一份 RFQ：三报价将失去同规格可比性。
- AI 或浏览器自动发送 RFQ：没有逐供应商授权、平台条款、回读和消息撤回/异常处理。
- 把 RFQ 当作报价：RFQ 是买方请求，不能证明供应商价格、MOQ、交付或认证。

## 复核

当 1688/Alibaba 官方供应商消息接口具备可验证身份、条款许可、单次审批、幂等发送、服务端消息
ID 回读和撤销/异常合同后，再评估受控发送连接器。最迟于 2026-10-26 复核本 ADR。
