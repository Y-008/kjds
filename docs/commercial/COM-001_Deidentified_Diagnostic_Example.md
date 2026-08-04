# COM-001 脱敏利润真相诊断样例

| 字段 | 样例值 |
|---|---|
| document_state | `synthetic_example_only` |
| customer_ref | `CUSTOMER-SYN-001` |
| tenant/entity/store | `TENANT-SYN-001 / ENTITY-SYN-001 / STORE-SYN-001` |
| data_window | `SYNTHETIC_WINDOW_START / SYNTHETIC_WINDOW_END` |
| active_sku_scope | `50–500；本页仅展示 3 个合成 SKU 的结构` |
| amount_policy | 仅使用 `SYNTHETIC_AMOUNT_SLOT`；不展示客户金额或利润 |
| external_write_count | `0` |

本页演示
[五工作日利润真相诊断 SOW](templates/COM-001_5_Day_Diagnostic_SOW.md)
的交付结构。所有 customer/store/SKU/Evidence 引用均为合成值；所有金额与利润均使用类型
槽或 `UNKNOWN/no_data`。本页不引用真实客户、联系人、店铺凭据、银行信息、交易正文、
实际金额或实际利润。

## 1. 作用域与数据地图

| 数据域 | 合成来源引用 | 期间 | 作用域 | 完整度状态 | 结论边界 |
|---|---|---|---|---|---|
| 商品目录 | `SRC-SYN-CATALOG-001` | `SYNTHETIC_WINDOW` | `STORE-SYN-001` | `provided_synthetic` | 仅建立 SKU 身份 |
| 订单 | `SRC-SYN-ORDER-001` | `SYNTHETIC_WINDOW` | `STORE-SYN-001` | `partial_synthetic` | 缺取消/退货映射 |
| 平台费用 | `SRC-SYN-FINANCE-001` | `SYNTHETIC_WINDOW` | `STORE-SYN-001` | `partial_synthetic` | 存在未分配费用 |
| 结算 | `SRC-SYN-SETTLEMENT-001` | `SYNTHETIC_WINDOW` | `STORE-SYN-001` | `provided_synthetic` | 尚缺银行回读 |
| 银行到账 | `SRC-SYN-BANK-UNKNOWN` | `UNKNOWN` | `ENTITY-SYN-001` | `no_data` | Actual Cash Profit 保持 `no_data` |
| FX | `SRC-SYN-FX-UNKNOWN` | `UNKNOWN` | `ENTITY-SYN-001` | `no_data` | 跨币种结果保持阻断 |
| SKU 成本 | `SRC-SYN-COST-001` | `SYNTHETIC_AS_OF` | `SKU-SYN-A/B/C` | `partial_synthetic` | B/C 缺正式成本 Evidence |

## 2. 币种完整度

| 检查 | 合成结果 | 状态 | Owner | 下一 Evidence 动作 |
|---|---|---|---|---|
| 平台金额币种 | 合成费用行标记 `RUB` | `complete_synthetic` | 财务角色 | 复验来源列与期间 |
| SKU 成本币种 | A 标记 `CNY`；B/C 为 `UNKNOWN` | `partial` | 运营角色 | 补充 B/C 成本原件 |
| 银行到账币种 | `no_data` | `blocked` | 财务角色 | 提交脱敏银行到账引用 |
| FX 币对/日期/来源 | `UNKNOWN` | `blocked` | 财务角色 | 提交有效 FX Evidence |

币种完整度样例结论：只对已明确币种的合成字段展示币种；任何 `UNKNOWN` 不按零处理，
不进行跨币种合计，也不输出实际现金利润。

## 3. SKU 成本与利润完整度

| SKU | 商品身份 | 成本 Evidence | 15 项成本覆盖 | scenario/downside | settlement | actual cash | 状态 |
|---|---|---|---|---|---|---|---|
| `SKU-SYN-A` | `ready_synthetic` | `EVD-SYN-COST-A` | `partial` | `no_data` | `no_data` | `no_data` | `fix` |
| `SKU-SYN-B` | `ready_synthetic` | `UNKNOWN` | `no_data` | `no_data` | `no_data` | `no_data` | `stop` |
| `SKU-SYN-C` | `ready_synthetic` | `EVD-SYN-COST-C-PENDING` | `review_pending` | `no_data` | `no_data` | `no_data` | `continue` |

完整度结论：本合成样例没有可发布利润值。`SKU-SYN-A` 仅证明存在成本引用，不证明 15 项
成本、结算或到账齐全；B/C 继续保持 `UNKNOWN/no_data`。

## 4. `unallocated` 与到账缺口

### 4.1 未分配费用

| 合成费用行 | amount | currency | 自然键/人工绑定 | 状态 | 下一动作 |
|---|---|---|---|---|---|
| `FEE-SYN-001` | `SYNTHETIC_AMOUNT_SLOT` | `RUB` | `UNKNOWN` | `unallocated` | 查找官方订单/结算自然键 |
| `FEE-SYN-002` | `SYNTHETIC_AMOUNT_SLOT` | `RUB` | `BINDING-SYN-PENDING` | `review_pending` | 财务角色复核绑定 Evidence |

未分配费用不按销售额、件数或比例猜分摊。`FEE-SYN-001` 在获得正式自然键或客户财务角色
接受的人工绑定之前，持续保持 `unallocated`。

### 4.2 结算到账链

```text
SETTLEMENT-SYN-001
  -> bank_receipt: no_data
  -> bank_currency: UNKNOWN
  -> fx_source/date: UNKNOWN
  -> cash_reconciliation: blocked
  -> actual_cash_profit: no_data
```

到账缺口：缺银行到账引用、到账币种、实际 FX 日期/来源及结算到银行的匹配键。当前只可
报告缺口，不生成实际到账额、差额或实际现金利润。

## 5. `stop / fix / continue / no_data` 决策清单

| decision_id | 对象 | 决定 | 原因 | Owner | SLA | 下一动作 | 复核条件 |
|---|---|---|---|---|---|---|---|
| `DEC-SYN-001` | `SKU-SYN-B` | `stop` | 正式成本和利润 Evidence 为 `no_data` | 运营角色 | `[SLA_SLOT]` | 暂停利润主张 | 成本与费用原件通过复核 |
| `DEC-SYN-002` | `SKU-SYN-A` | `fix` | 15 项成本覆盖不完整 | 财务角色 | `[SLA_SLOT]` | 补成本组件及币种 | 完整度与守恒复验通过 |
| `DEC-SYN-003` | `SKU-SYN-C` | `continue` | 仅继续只读补证，不形成业务写 | 运营角色 | `[SLA_SLOT]` | 收集正式成本 Evidence | 独立 Reviewer 接受来源 |
| `DEC-SYN-004` | `SETTLEMENT-SYN-001` | `no_data` | 银行到账与 FX 缺失 | 财务角色 | `[SLA_SLOT]` | 提交到账/FX 引用 | cash reconciliation 可复算 |

所有决定均为诊断工作流内部状态；发布、改价、采购、付款、广告、消息和 Ozon 买家订单
退款等第三方业务写保持关闭。

## 6. Evidence 索引

| evidence_id | 合成来源类型 | scope_ref | content_sha256 | 等级/状态 | 支持的结论 |
|---|---|---|---|---|---|
| `EVD-SYN-CATALOG-001` | `synthetic_catalog_export` | `STORE-SYN-001` | `[SHA256_SLOT]` | `synthetic_only` | SKU 身份结构 |
| `EVD-SYN-FINANCE-001` | `synthetic_finance_export` | `STORE-SYN-001` | `[SHA256_SLOT]` | `synthetic_only` | 费用与币种结构 |
| `EVD-SYN-COST-A` | `synthetic_cost_reference` | `SKU-SYN-A` | `[SHA256_SLOT]` | `partial_synthetic` | 存在成本引用 |
| `EVD-SYN-COST-C-PENDING` | `synthetic_cost_reference` | `SKU-SYN-C` | `[SHA256_SLOT]` | `review_pending` | 不支持正式成本 |
| `EVD-SYN-BANK-UNKNOWN` | `bank_receipt` | `ENTITY-SYN-001` | `UNKNOWN` | `no_data` | 不支持实际到账 |
| `EVD-SYN-FX-UNKNOWN` | `fx_source` | `ENTITY-SYN-001` | `UNKNOWN` | `no_data` | 不支持跨币种利润 |

## 7. 样例验收结论

- 结构交付：`accepted_synthetic_example`。
- 首次可信价值：`blocked/no_data`；样例未形成至少 1 个带完整 Evidence 的利润投影。
- 金额币种：部分合成字段明确，缺失项保持 `UNKNOWN`。
- `unallocated`：存在，未猜分摊。
- 实际到账与实际现金利润：`no_data`。
- 外部写：`0`。
- 下一安全动作：使用
  [客户资格与输入模板](templates/COM-001_Customer_Qualification_Input.md)
  收集脱敏引用，再由运营、财务和 Independent Verifier 复核。
