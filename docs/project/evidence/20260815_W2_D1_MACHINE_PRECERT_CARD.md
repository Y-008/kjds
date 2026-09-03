# 2026-08-15 W2 D1 真人签字前机器预检证据卡

| 字段 | 值 |
|---|---|
| doc_id | KJDS-W2-D1-MACHINE-PRECERT-20260815-001 |
| 状态 | READ_ONLY_MACHINE_PRECERT |
| 生成时间 | 2026-08-15T13:27:53.6961635+08:00 |
| 当前 HEAD | c744c7943e09b4890d07b0efc0ec1a031b408ba7 |
| 分支 | feat/ai-listing-first-real-sku |
| staged | 0 |
| index.lock | 0 |
| 快照比对 | CHANGED（LINYAN to_supply 6→7） |
| 依据 | 20260815_W2_AI_SNAPSHOT_BASELINE.json / 20260815_W2_AI_SNAPSHOT_LATEST.json / scripts/compare-w2-ozon-snapshot.ps1 |
| 复采时间 | 2026-08-15T05:34:06Z |
| 当前结论 | PARTIAL_DONE（两店解封工单已发送；其余 D1 写操作仍 HOLD，需执行前复采） |

## 机器预检结论

| 店 | 当前余额 | active FBS | 8 月应计 | 8 月已付 | 封锁仓 | Premium grace |
|---|---:|---:|---:|---:|---:|---:|
| BEIJIXINGYOUXUAN | 8,568.15 ₽ | 0 | 0 | 0 | 2 | 可用 |
| LINYAN888 | 8,375.94 ₽ | 0 | 0 | 0 | 20 | 已过期 |
| Treasures of the road | 12,621.01 ₽ | 0 | 0 | 0 | 8 | 可用 |

- 三店 active FBS 订单均为 0；历史 delivered/cancelled 仅作经营参考，不作为当前现金闭环证据。
- LINYAN `to_supply` 当前为 7，最新只读采样由 6 变为 7；仅商品状态变化，不自动进入归档名单。
- BASELINE 当前字节 11156，SHA-256 为 `9B1AEF4E5DCB62947C37B81B302EA92A8939B175A6F84CA0DB0A368CC28032B3`；LATEST 当前字节 11156，SHA-256 为 `DB4B2ECBB051770B627F18B6830B2FD9D04B5C2BEE0AD62D942845EC3C08404E`。
- `scripts/compare-w2-ozon-snapshot.ps1` 实测输出 `LINYAN888 to_supply 6→7 CHANGED`，其余余额/active FBS/仓库/Premium 均无变化。

## 签字前边界

| 项 | 当前状态 |
|---|---|
| 真人签字 W2 启动包 | 已签 |
| D1 店铺写操作 | 两店工单已发送；归档/改价/回复仍 NO-GO，待执行前复采 |
| AI 代发工单 / 改价 / 归档 / 回复 / 提现 | D1 剩余写操作已授权；提现仍禁止 |
| 新仓 / 配送方式 / 上新 realFBS 商品 | 禁止 |
| 付费 Premium / 评价工具 / 忠诚度 / 付费推广 | 禁止 |
| TREAS 操作 | 冻结，待 2026-08-29 付款日复采 |

## 真人执行前复采门

1. 刷新三店订单页，确认 active FBS 仍为 0。
2. 刷新财务页，确认三店余额、8 月应计、已付仍与本表一致。
3. 刷新仓库页，确认 BEIJI 2、LINYAN 20、TREAS 8 的封锁数未变。
4. 运行 `scripts/run-w2-readonly-snapshot.ps1`，再运行 `scripts/compare-w2-ozon-snapshot.ps1`，仅当结果为 `NO_CHANGE` 时维持本卡有效。
5. 任一指标漂移，立即停止 D1 写操作并转真人复核。

## 真人签字栏

| 字段 | 填写 |
|---|---|
| 签字人 | |
| 角色 | |
| 签字时间 | |
| 结论 | APPROVE / REJECT / HOLD |
| 复核说明 | |

- [ ] 我已阅读 `20260815_W2_D1_PRECHECK_GONOGO.md`，确认签字前不执行任何店铺写操作。
- [ ] 我已确认执行前会重新运行只读快照和差异比对，仅当结果为 `NO_CHANGE` 后继续。
- [ ] 我已确认 AI 不代发工单、不改价、不归档、不回复、不提现。

本卡只证明机器可读基线当前稳定，不替代真人签字，也不构成任何 Ozon 店铺写授权。