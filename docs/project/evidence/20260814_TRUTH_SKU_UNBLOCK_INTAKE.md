# Truth SKU 原件解除阻塞工作单（预填版，待真人终签）

| 字段 | 值 |
|---|---|
| 类型 | 解除阻塞工作单（`INTAKE_WORKSHEET`，草稿，非正式事实） |
| 目标 | 把“真人原件”从 8 区全空压缩到“只剩外部不可替代事实”，其余由已核验证据预填 |
| 默认 Truth SKU | `激光水平仪(红光束) 1958938002`（LINYAN，佣金 12%，历史净额 +19,435.13 ₽，328 单） |
| 备选（利润天花板） | `折叠式旅游床 2021923794`（BEIJI，佣金 19%，历史净额 +92,117.22 ₽，176 单） |
| 铁律 | 预填只引用已核验证据 + SHA；外部事实（银行到账、三家报价、EAC 证书、实测重量尺寸、法定主体名）仍必须真人提供，系统不补数 |

## 1. 已可由已核验证据预填（真人只需确认）

### 1.1 Ozon 访问（g0-ozon-access）

| 字段 | 预填值 | 来源 |
|---|---|---|
| account_alias | `BEIJIXINGYOUXUAN` | seller_identity_registry.json |
| seller_or_client_id | Ozon ID `176797869` / client_id `2735620` | 同上 |
| allowed_read_operations | `product; inventory; orders; analytics; finance`（其中 `catalog.read`/`finance.read` 已官方回读验证） | 同上 |
| forbidden_write_operations | `product; price; inventory; ads; finance`（`external_write_allowed=false`） | 同上 |
| legal_entity | **真人填**（BEIJI/LINYAN/TREAS 三公司对应法定主体，需你确认） | 待签 |

### 1.2 Ozon API 身份盘点（g0-ozon-api-identities）

| identity_ref | purpose | 预填 | 状态 |
|---|---|---|---|
| IDENTITY-01 | read-only | `KJDS-RO-read-only`，created 2026-07-24 / expires 2027-01-30 | 待复核 |
| IDENTITY-02 | listing_execution | `KJDS-L3-listing-executor`，created 2026-07-25 / expires 2027-01-31 | 待复核 |

> 只登记名称与用途，**绝不粘贴 key 值**；`role_count/scope_class/last_used/disposition` 由账户负责人核。

### 1.3 SKU Passport（sku-passports，对应默认 Truth SKU）

| 字段 | 预填值 | 来源 |
|---|---|---|
| sku | `1958938002` | 修正账 CSV |
| product_name | `激光水平仪 红 光束` | 修正账 CSV |
| country_of_origin | `CN`（待真人确认） | 候选清单默认 |
| 历史净额 | `+19,435.13 ₽`（应计口径） | 修正账 CSV 独立复算 |
| 实际佣金率 | `12%`（众数） | 修正账 CSV `Вознаграждение Ozon, %` 列 |
| hs_code / eaeu_rules / eac_requirement / chestny_znak / russian_labeling / ip_status / transport | **真人 + 供应商/报关行原件** | 不可推断 |

### 1.4 候选研究（candidate-research，默认 SKU 五指标）

| metric | 预填 | 来源 |
|---|---|---|
| demand_signal | 328 单 / 6 个月，历史净额 +19,435.13 ₽ | 修正账 CSV |
| supplier_available | **真人提供三家报价后置 1** | 待补 |
| compliance_redline | `UNKNOWN`（测量仪器类，需 TN VED/EAC 归类） | 合规预审口径 |
| return_risk | **真人核退货率后填** | 待补 |
| competition_gap | **真人核对手价后填** | 待补 |

## 2. 真人必须提供的外部事实（不可由系统生成，共 5 项）

1. **银行/收款方到账流水**：任一条历史订单的到账金额、日期、币种、流水备注（含结算批次 reconciliation key）。→ 填入 `finance-reconciliation.csv` 的 `bank_receipt + evidence_reference`。
2. **三家供应商真实报价**：同 SKU（激光水平仪）三家 1688/供应商报价原件，含报价 ID、MOQ、单价、交期、重量尺寸、国内物流、有效期。→ 填 `supplier-quotes.csv`。
3. **合规原件**：该 SKU 的 TN VED 归类、EAC/Declaration 证书或“无需认证”书面判断、俄文标签、Честный ЗНАК 是否适用、IP 风险。→ 填 `sku-passports.csv` 合规列。
4. **实测重量/长宽高**：商品 + 包装的实测参数。→ 填 `sku-passports.csv`。
5. **法定主体名 + 四席签字 + 预算/最大损失/停止线**：经营/运营/财务/独立控制四席实名。→ 填 `g0-governance.csv`。

## 3. 解除阻塞后的状态判定

- 交齐 §2 第 1 项（银行流水）后，`finance-reconciliation` 区可进入 `review_ready`；五段对账 `unmatched=0` 且独立复核通过 → `CASH_VERIFIED`。
- 交齐 §2 第 2/3/4 项后，`supplier-quotes`、`sku-passports` 可进入 `review_ready`，允许进入三报价与真实经营门禁。
- §2 第 5 项是资金放行的前置，未签前不采购、不付款、不上架、不广告。

## 4. 边界

- 本工作单是“真人填写的脚手架”，不是正式事实；正式登记仍走 `startup-intake` 8 个 CSV + `originals/` + SHA-256 + Owner + 独立复核。
- 历史净额/佣金率为“平台应计口径”，不得在拿到银行流水前升级为 Cash 事实。
