# 2026-08-15 W2 只读验证门

| 字段 | 值 |
|---|---|
| doc_id | KJDS-W2-READONLY-GATE-20260815-001 |
| 状态 | READ_ONLY_VERIFICATION_GATE |
| 生成时间 | 2026-08-15T13:50:00+08:00 |
| 当前 HEAD | c744c7943e09b4890d07b0efc0ec1a031b408ba7 |
| CDP 状态 | 9224 已恢复，但 Ozon 为 signin 登录页 |
| 快照比对 | LINYAN `to_supply` 6→7 CHANGED；其余关键指标无变化 |

## 机器检查结果

| 检查项 | 结果 |
|---|---|
| `node --check capture_w2_ozon_cdp_snapshot.mjs` | PASS |
| PowerShell 解析 `run-w2-readonly-snapshot.ps1` | PASS |
| PowerShell 解析 compare-w2-ozon-snapshot.ps1 | PASS |
| 运行 scripts/verify-w2-readonly-audit.ps1 | PASS |
| BASELINE JSON 解析 | PASS |
| LATEST JSON 解析 | PASS |
| W2 清单哈希复核 | PASS，`MANIFEST_CHECKED=30`，`MANIFEST_MISMATCHES=0` |
| staged | 0 |
| index.lock | false |
| W2 交付物 | 27 个，全部 untracked |

## 当前事实摘要

| 店 | 余额 | active FBS | 封锁仓 | Premium grace | in_sale | to_supply |
|---|---:|---:|---:|---:|---:|---:|
| BEIJIXINGYOUXUAN | 8,568.15 ₽ | 0 | 2 | 可用 | 14 | 5 |
| LINYAN888 | 8,375.94 ₽ | 0 | 20 | 已过期 | 27 | 7 |
| Treasures of the road | 12,621.01 ₽ | 0 | 8 | 可用 | 64 | 1 |

## Go/No-Go

| 项 | 状态 |
|---|---|
| 真人签字 | 未签，NO-GO |
| Ozon 登录态 | signin，NO-GO |
| active FBS | 0，GO |
| 余额/应计/已付 | 当前稳定，GO |
| AI 执行店铺写操作 | 禁止 |

## 边界

- 本门只证明本地 W2 交付物可解析、脚本语法有效、清单哈希闭合和当前工作树未 stage。
- 本门不构成 Ozon 登录授权、店铺写授权、`CASH_VERIFIED` 或生产发布授权。
- Ozon 登录和所有店铺写操作必须由真人完成。