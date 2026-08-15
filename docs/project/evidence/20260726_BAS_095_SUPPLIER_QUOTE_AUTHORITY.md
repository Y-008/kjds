# BAS-095 供应商报价独立权威门验收

- 日期：2026-07-26
- Requirement：BR-070、SKU-003
- ADR：`docs/adr/ADR-0021-supplier-quote-authority.md`
- 实现分支：`feat/supplier-quote-authority`

## 真实只读研究输入

当前 Ozon 目录商品：

- Offer ID：`2105343364UB`
- Marketplace SKU：`2216781923`
- 商品：便携式电动提升机，500 kg，7.6 m，三种控制方式
- 目录重量/尺寸：11.999 kg，37.9 × 31.9 × 24.9 cm
- Ozon 公开页面当前显示：13,607 RUB，当前访问地区不可配送
- 标题含明显机器翻译污染：`случайные волосы BA`

登录态 Ozon 搜索 `электрическая лебедка 500 кг` 的只读观察：

- 同款跨境重复商品显示约 41,422–41,603 RUB，多数无评价且交付较晚；
- 接近规格的 500 kg / 8 m / 3 合 1 商品显示 10,173 RUB，5.0 分、1 条评价；
- 300 kg / 12 m / 3 合 1 商品显示 12,395 RUB，4.9 分、137 条评价；
- 固定式 500/250 kg 商品显示 7,013 RUB，4.9 分、2665 条评价。

登录态 1688 搜索 `便携式电动葫芦 500kg 7.6米 三控 220v` 的只读观察：

- 河北悍象起重机械有限公司：公开展示价 409 CNY；
- 徐州赵氏起重机械有限公司：公开展示价 465 CNY；
- 河北神冠机电科技有限公司：公开展示价 410 CNY；
- 河北工之助起重机械制造有限公司：公开展示价 420 CNY；
- 河北孟工起重机械制造有限公司：公开展示价 425 CNY；
- 保定冀恒起重机械制造有限公司：公开展示价 672 CNY；
- 河北永图起重机械制造有限公司：公开展示价 800 CNY；
- 河北亿康起重机械制造有限公司：公开展示价 856 CNY；
- 另有 100 CNY 页面项，明显需要核对 SKU 档位和引流价。

这些数据只证明存在潜在供应商和市场价格带，不证明精确规格、包装、交付、MOQ、税费、国内运费或
报价有效期。因此本次没有创建正式 `SupplierOffer`、采购、消息、订单、改价、广告或 Ozon 写入。

## 工程控制

1. `public_display_price` 固定为 `research_only`，不能接受为正式报价。
2. `supplier_confirmed_quote` 与 `proforma_invoice` 必须带失效时间。
3. 原件以 B 级 `supplier_quote_source` 捕获，条款冻结在 Evidence metadata。
4. 上传者自审被拒绝；接受必须通过五项检查并生成 A 级不可变复核凭证。
5. `SourcingService.capture_offer` 在运行时复验接受状态和冻结条款完全一致。
6. 三报价最终化要求三份不同 Evidence、不同供应商、同一候选 Product、当前有效且已接受。
7. 报价采购价与国内物流只能为 `estimate`；`actual` 继续要求发票/付款或最终账单权威复核。
8. 旧 `/v1/sourcing/comparison-intake` 返回 409，禁止上传即建正式报价。
9. Web 提供“原件录入—独立复核—三报价最终化”三阶段工作台。

## 数据库决策

未新增表或 Alembic 迁移。该流程复用现有不可变 `evidence_records`、`evidence_blobs` 和
`lineage_edges`；正式报价继续复用 `source_offers`。这是 ADR-0021 的有意设计，避免可变工作流表与
Evidence Ledger 形成第二事实源。

## 验收命令

```text
uv run pytest -q tests/test_sourcing_intake.py -p no:cacheprovider --basetemp=.runtime/pytest-supplier-authority-3
9 passed

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-supplier-authority-full
449 passed, 1 failed（仅 OpenAPI 固定快照待更新）

uv run python scripts/export_openapi.py
uv run pytest -q tests/test_api_contract.py tests/test_sourcing_intake.py -p no:cacheprovider --basetemp=.runtime/pytest-supplier-contract
26 passed

cd web
npm test
33 passed

npm run build
Compiled successfully；TypeScript 与 13 个页面生成通过

uv run ruff check .
All checks passed

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-supplier-authority-final
451 passed
```

## 仍然阻塞的真实业务

- 尚未向三家供应商发送精确 RFQ，也未获得三份当前有效的确认报价或形式发票；
- 尚未确认 500 kg / 7.6 m / 三控 / 220V 的精确 SKU、包装、认证和交付条款；
- 当前商品在访问地区不可配送，必须先核验配送覆盖；
- Ozon 标题必须先由俄语母语/合规复核，广告投放仍受真实转化率、评价、内容和全成本门阻断。

## BAS-095A：正式报价数量阶梯无损补强（2026-08-10）

首个真实 SKU 的冻结 RFQ 要求样品、100、300、500 件报价。复核发现原有 Evidence 可以保存任意
`offer_data`，但正式 `SupplierOffer` 与 `supplier-quotes.csv` 只显式投影单个 `unit_price + MOQ`；
若直接截取其中一档，会丢失原始阶梯并可能把不同采购量当作可比成本。

本次继续复用 ADR-0021 的单一报价真源：

- 完整阶梯保存在同一不可变 `offer_data.attributes.price_tiers`，正式投影继续落入既有
  `source_offers.attributes_json`，没有新增报价表或迁移；
- 每档只允许 `minimum_quantity + unit_price`，数量唯一、规范化严格升序，数量和金额必须为正，
  金额使用有限 Decimal；
- 同一原件冻结 `selected_quantity`，`SupplierOffer.unit_price` 必须等于该数量适用的最高起订档，
  且所选数量不得低于报价 MOQ；
- 同组三报价只要任一份带阶梯，三份都必须声明同一 `selected_quantity`；检查发生在利润假设
  Evidence 与 SupplierOffer 创建之前，失败不留下部分正式对象；
- 完整阶梯和比较数量进入既有不可变复核 payload、Source Offer 幂等比较和三报价响应，公开价、
  上传者自审、采购、付款、平台写入与 `actual` 权限没有变化。

被否决方案包括：为每档复制一个 SupplierOffer（会把一家伪装为多份报价）、只留被选档（丢失
权威条款），以及新增报价行事实表（与当前 Evidence + immutable `source_offers` 形成第二真源）。
当签名供应商 API 或大量区间查询证明 JSONB 无法满足索引/审计 SLO 时，才按 ADR 失效条件重新评估
规范化子表。

`frontier_review=not_required`：本切片没有新增依赖、Provider、运行时、模型或外部接口，只加强既有
内部 Decimal/Evidence 合同。

### 2026-08-10 验收

```text
uv run pytest -q tests/test_sourcing_intake.py tests/test_sourcing.py tests/test_api_contract.py \
  -p no:cacheprovider --basetemp=D:\KJDS\.tmp\quote-tiers-contract
59 passed

uv run python scripts/verify_secrets.py
Secret scan passed: 555 non-ignored worktree files and 1465 historical paths checked

uv run ruff check .
All checks passed!

uv run alembic heads
20260726_0052 (head)

uv run pytest -q -p no:cacheprovider --basetemp=D:\KJDS\.tmp\quote-tiers-full
542 passed, 1 non-blocking upstream StarletteDeprecationWarning

git diff --check
passed
```

独立完成复核结论：没有发现 P0/P1/P2 未解决项。旧单价报价不含 `price_tiers` 时保持原行为；阶梯
输入的重复数量、零价、无适用档、缺比较数量、单价漂移和三家数量不一致均有确定性负向测试。
本工程验收不证明已收到任何真实供应商报价；真实报价数仍为 0。
