# TRUTH-SKU-001 证据清单与四席责任签署页

| 字段 | 值 |
|---|---|
| doc_id | KJDS-TRUTH-SKU-001-MANIFEST |
| 生效日 | 2026-08-14 |
| 状态 | AWAITING_SIGNATURE（空白签署页，不包含任何经营秘密） |
| 经营负责人 | 待签署（`primary_human_ref=UNKNOWN`） |
| 独立复核人 | 待签署（`primary_human_ref=UNKNOWN`） |
| 安全边界 | 本清单只登记不透明 `evidence_ref`、SHA-256、Owner、独立复核和状态；密码/Token/API Key/完整银行资料/客户与供应商 PII/原始经营数据一律不进 Git，原件只进私密 Evidence 工作区 |

## 0. 唯一下一动作

**今天由经营负责人签署 `TRUTH-SKU-001`，并按下表第 2 节 6 项交真实原件给对应 Owner。**
未完成前：暂停第二 SKU、新 Dashboard 与社媒自动化。新 Agent 平台**可以引入**（2026-08-15 修订）。其他 SKU 保持 `STANDBY/UNKNOWN`。

## 1. Truth SKU 唯一身份（待签署，缺一即 `BLOCKED_EVIDENCE`）

| 项 | 值 | 状态 |
|---|---|---|
| Truth SKU 名称 | `UNKNOWN` | BLOCKED_EVIDENCE |
| Product 稳定标识 | `UNKNOWN` | BLOCKED_EVIDENCE |
| SKU 稳定标识 | `UNKNOWN` | BLOCKED_EVIDENCE |
| Ozon offer 映射 | `UNKNOWN` | BLOCKED_EVIDENCE |
| 名称 / 材质 / 用途 / 产地 | `UNKNOWN` | BLOCKED_EVIDENCE |
| 实测重量 / 长宽高 | `UNKNOWN` | BLOCKED_EVIDENCE |

已知事实（来自 `seller_identity_registry.json`，非本次签署）：
- 自家主店 `BEIJIXINGYOUXUAN`，Ozon ID `176797869`，client_id `2735620`，store_ref `ozon-primary`。
- `catalog.read` 与 `finance.read` 已官方回读验证；`order.read` / 结算 / 银行到账仍为缺口。
- 历史订单存在（2025/7/20、7/28、8/2、8/24 等，见历史对账 Runbook），可用于首条历史现金闭环。

## 2. 六项真实证据（与八资料区对应，全部 `UNKNOWN` 起始）

| # | Owner（待署名） | 交付物 | 落地资料区 | 状态 |
|---|---|---|---|---|
| 1 | 商品负责人 | 稳定 Product/SKU/Ozon offer、名称、材质、用途、产地、实测重量尺寸 | SKU Passport | UNKNOWN |
| 2 | 供应链负责人 | 同一 SKU 三家真实报价原件：报价 ID、MOQ、单价/币种、交期、重量尺寸、国内物流、有效期 | 供应商报价 | UNKNOWN |
| 3 | 合规负责人 | HS、EAEU/EAC、Честный ЗНАК、俄文标签、知识产权、运输限制及对应原件 | SKU Passport + 候选研究 | UNKNOWN |
| 4 | 账户负责人 | 只读 Ozon 身份、调用系统、Owner、角色数、权限类别、最后使用时间、处置决定、独立复核人 | Ozon 访问 + Ozon API 身份 | UNKNOWN |
| 5 | 财务负责人 | 一条订单应收—解释费用—预计结算—平台结算—银行到账记录，含 FX、未知费用、原件引用 | 财务对账 | UNKNOWN |
| 6 | 独立复核人 | 确认提案人与复核人分离；只接受原始文件、时间、SHA-256、明确 Owner | G0 治理 | UNKNOWN |

对账键（固定口径，FIN-001）：`order_id → posting_number → settlement 记录 → 银行流水备注`；任一层断链即 `UNMATCHED`，禁止估算补齐。

## 3. 八资料区缺口表（Owner / 截止 / 失败路径，待分配）

| 资料区 | Owner（待署名） | 截止 | 失败路径（未完成时的动作） | 状态 |
|---|---|---|---|---|
| G0 治理 | 经营负责人 | 待定 | 不进入资金放行；停在资料补齐 | UNKNOWN |
| Ozon 访问 | 账户负责人 | 待定 | 冻结真实读；不扩权 | UNKNOWN |
| Ozon API 身份 | 账户负责人 | 待定 | 只留脱敏盘点，禁止录入密钥 | UNKNOWN |
| SKU Passport | 商品 + 合规 | 待定 | 停止上架，不生成 Listing | UNKNOWN |
| 供应商报价 | 供应链负责人 | 待定 | 不下采购、不付样品款 | UNKNOWN |
| SKU 媒体 | 商品负责人 | 待定 | 不进入内容生成 | UNKNOWN |
| 候选研究 | 商品 + 合规 | 待定 | 不把候选线索冒充真实经营证据 | UNKNOWN |
| 财务对账 | 财务负责人 | 待定 | `reconciliation unmatched != 0` 时不晋升 `CASH_VERIFIED` | UNKNOWN |

## 4. 四席责任与 SoD（待签署）

| 席位 | 承载责任 | 真人署名 | 状态 |
|---|---|---|---|
| 经营席 | 企业责任、商品、类目、商业拍板 | UNKNOWN | AWAITING |
| 运营席 | 供应商、质量、物流、关务、Ozon 运营 | UNKNOWN | AWAITING |
| 财务席 | 成本、结算、银行、Actual Cash CM3 | UNKNOWN | AWAITING |
| 独立控制席 | 验证、批准、风险与冲突审查 | UNKNOWN | AWAITING |

不可兼任（六条 SoD，违反即 `BLOCKED`）：
产物编写人≠独立验证人；财务制单人≠付款批准人；外部动作批准人≠执行人；Migration 作者≠最终发布批准人；Agent/Skill Owner≠晋级批准人；监管研究人≠正式法律结论签署人。

**最大损失与阶段预算（待签署，系统不得补数）**

| 项 | 值 | 状态 |
|---|---|---|
| 单次最大损失（悲观 CM3） | UNKNOWN | AWAITING |
| 阶段预算金额 | UNKNOWN | AWAITING |
| 预算有效期 | UNKNOWN | AWAITING |
| 停止线（触发即停） | UNKNOWN | AWAITING |

## 5. 证据交付路径

原件只进本地私密工作区（Git 忽略），记录：导出时间、SHA-256、来源页面、Owner、独立复核人。
本清单在 Git 中只登记 `evidence_ref` + SHA-256 + Owner + 复核 + 状态，不登记原件正文。

## 6. Day 0–3 验收 Gate

> 一个 SKU、一个责任组、一套 manifest、一个下一动作。未满足则保持 `BLOCKED_EVIDENCE`。

当前状态：四要素全部未闭合，`BLOCKED_EVIDENCE` 持续成立，直到经营负责人签署并交齐六项。
