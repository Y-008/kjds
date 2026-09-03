# D1 Ozon 会话恢复 Runbook（2026-08-15）

| 字段 | 值 |
|---|---|
| doc_id | KJDS-D1-SESSION-RECOVERY-20260815-001 |
| 状态 | READ_ONLY_RUNBOOK |
| 目标 | 恢复本地 CDP 9224 与已登录的 Ozon 卖家会话，随后继续 D1 剩余写操作 |

## 1. 当前阻塞

- `http://127.0.0.1:9224/json/version` 连接被拒绝。
- 两店解封工单已通过 SCRM 发出，但归档、改价、回复、RFQ、Premium、官促需要恢复已登录卖家页面。

## 2. 模式 A：真人自己浏览器操作

这是最稳妥的降级路径，无需复制会话。

1. 真人使用自己的 Chrome 打开并登录 `seller.ozon.ru`。
2. 确认页面不是 `seller.ozon.ru/app/registration/signin`，而是卖家后台仪表盘或商品页。
3. 逐项执行 D1 剩余步骤，按执行卡截图。
4. AI 只负责读回核对、记录工单号与证据哈希，不代点。

## 3. 模式 B：恢复 9224 调试窗口

1. 关闭真人自己的 Chrome，确保任务栏图标退出，等待约 10 秒。
2. 在 PowerShell 运行：

```powershell
D:\KJDS\.runtime\refresh-ozon-session.ps1
```

3. 再启动调试 Chrome：

```powershell
D:\KJDS\.runtime\launch-ozon-debug.ps1 -Port 9224
```

4. 若新窗口落在登录页，使用真人手机号 + SMS 登录；不要把验证码发给 AI。
5. 登录后确认当前页面 URL 是 `seller.ozon.ru`，不是 `signin`。
6. 完成后回复“已登录”或直接让我继续只读复核。

## 4. 验证命令

登录完成后，我会运行：

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:9224/json/version' -TimeoutSec 5
Invoke-RestMethod -Uri 'http://127.0.0.1:9224/json/list' -TimeoutSec 5
```

只有同时满足以下条件才继续：

- `json/version` 可达。
- 页面列表中存在 `seller.ozon.ru` 页面。
- 页面 URL 不包含 `/app/registration/signin`。

## 5. 恢复后的执行顺序

1. 运行 `scripts/run-w2-readonly-snapshot.ps1`。
2. 运行 `scripts/compare-w2-ozon-snapshot.ps1`。
3. 若快照仍显示 active FBS 0，继续：
   - 归档 15 项。
   - LINYAN 两笔改价与 Listing。
   - 消息/评价回复。
   - RFQ、Premium、官促。

## 6. 边界

- 不读取或输出短信验证码、密码、Cookies、`.env`、`Api-Key`、`Client-Id`、银行账号或 PII。
- 不复制含完整主档案的调试目录到仓库或外部位置。
- 会话恢复后仍先做只读快照，再执行授权范围内的写操作。