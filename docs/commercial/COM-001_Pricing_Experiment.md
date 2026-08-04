# COM-001 定价与转化实验

| 字段 | 当前值 |
|---|---|
| status | `internal_review_only` |
| activation_gate | `C0 Commercial Pilot Gate = PASS` |
| cohort | 中国 Ozon 成长卖家；1–3 店、50–500 活跃 SKU、3–20 人团队 |
| diagnostic | `4,800 RMB / one store / five working days / prepay` |
| pilot | `19,800 RMB / same store / 90 calendar days` |
| credit | 诊断验收后 10 个自然日内转 Pilot，`4,800 RMB`全额抵扣 |

本实验验证真实付费意愿、交付成本和转化，不通过临时降价制造成交。C0 通过前只进行资格
访谈、意向记录和输入准备，不产生订单、收款或应收。

## 1. 固定报价合同

- 诊断：人民币 `4,800 元`，未税，启动前 100% 支付。
- Pilot：人民币 `19,800 元`，未税。
- 同一主体、同一店铺在诊断验收日起 10 个自然日内签署 Pilot，诊断费全额抵扣；开工
  前支付余额 `15,000 元`。
- 抵扣只使用一次，不兑换现金、不跨主体或店铺、不与其他优惠叠加。
- 价格、作用域和抵扣规则在首轮样本内保持一致；实验只比较客户问题、输入准备度、首次
  价值和转化，不按销售人员临时调整价格。

本实验的 T0 采用
[五工作日利润真相诊断 SOW](templates/COM-001_5_Day_Diagnostic_SOW.md)定义：C0 全部检查
为 `PASS`、客户级主协议/DPA/SOW/退出附表完成签署、诊断款到账并回读、精确作用域冻结
且输入准入通过后的首个工作日。验收与关闭采用
[验收、数据返还与退出模板](templates/COM-001_Acceptance_and_Exit.md)。

`docs/product/KJDS_SAAS_PACKAGING_AND_PRICING_2026.md` 的公开 SaaS 套餐与本次单客户
托管 Pilot 属于不同商业阶段。本实验采用 2026-08-02 商业 GTM 冻结的“未税、非公开”
口径，税率、开票项目和签约主体仍需财务/法务批准。

## 2. 实验假设

1. 合格成长卖家愿为五工作日、可审计、纯只读的利润真相诊断支付 `4,800 元`。
2. 诊断形成客户确认的问题和动作后，全额抵扣可把高意向客户转为 `19,800 元` Pilot。
3. 单店标准交付在不超过 12 人时实施投入下，可实现至少 50% Pilot 交付毛利。
4. 真实 Evidence、明确 `no_data` 和可执行下一动作比功能数量更能驱动转化。

## 3. 漏斗与事件

每个事件使用匿名稳定 `customer_ref`、时间、Owner、作用域哈希和 Evidence 引用；仓库中
不保存客户真名、联系方式、凭据、银行资料或销售聊天正文。

```text
qualified_interview
  -> data_willing
  -> conditional_loi
  -> c0_eligible
  -> diagnostic_ordered
  -> diagnostic_paid
  -> input_accepted
  -> diagnosis_delivered
  -> diagnosis_accepted
  -> first_credible_value
  -> pilot_ordered
  -> pilot_paid
  -> pilot_activated
  -> renewed_or_closed
```

必须记录的字段：

- `customer_ref / cohort_version / store_count / active_sku_band / team_size_band`
- `problem_category / current_process_hours / operations_owner_ready / finance_owner_ready`
- `readonly_data_willing / input_ready / rejection_reason`
- `offer_version / quoted_amount / currency / tax_basis / credit_deadline`
- `ordered_at / paid_at / t0 / delivered_at / accepted_at / first_credible_value_at`
- `delivery_hours / support_hours / infrastructure_cost / ai_cost / storage_cost`
- `pilot_decision / decision_reason / annualized_confirmed_value / evidence_refs`

## 4. 样本与决策门

| 门 | 最小样本 | 通过条件 | 未通过处理 |
|---|---:|---|---|
| 问题/数据意愿 | 20 次合格访谈 | 至少 8 家愿提供真实只读数据 | 修正 ICP、问题或输入要求 |
| 诊断付费 | 10 家获得同版正式报价 | 至少 5 家完成真实付款 | 复核价值主张、交付包和价格 |
| 首次价值 | 5 家付费诊断 | 至少 4 家在 T0 后 5 工作日内达到首次可信价值 | 缩小数据合同并修正实施流程 |
| Pilot 转化 | 5 家完成诊断 | 至少 2 家签署并支付 Pilot 或续约定金 | 复核抵扣窗口、价值证明和支持成本 |
| Pilot 经济 | 至少 3 家完成 30 天交付 | 交付毛利至少 50%，实施不超过 12 人时 | 保持托管、压缩范围或调整价格 |

若连续 10 个合格客户均没有真实付费意愿，触发商业方案复审；免费意向、演示账户、关联方
和未到账订单不计入付费样本。

## 5. 指标定义

- 诊断付费率：`diagnostic_paid / c0_eligible`。
- 诊断验收率：`diagnosis_accepted / diagnosis_delivered`。
- 首次可信价值率：`first_credible_value / diagnostic_paid`。
- Pilot 转化率：`pilot_paid / diagnosis_accepted`。
- 首次价值时间：`first_credible_value_at - T0`，客户输入暂停时长单独报告。
- 交付毛利：`(已确认收入 - 基础设施 - AI - 媒体 - 存储 - 实施工时成本 - 支持工时成本) / 已确认收入`。
- 确认价值：仅使用客户财务角色接受、绑定基线/窗口/公式/Evidence 的金额。

## 6. 价格治理

- 每个报价绑定 `offer_version`、审批角色、有效期和精确店铺作用域。
- 销售人员不通过口头承诺增加功能、店铺、用户、SLA 或外部写权限。
- 退款、抵扣、服务信用和关闭账必须进入追加式商业事件并幂等回读。
- 每完成 5 个付费诊断或每 30 天复核一次，以先到者为准；调整价格时发布新版本，不改写
  既有报价和事件。
- 未达到样本门时保留 `pricing_hypothesis`，不发布转化率、盈利率或市场领先声明。
