# Supabase 双账号审批验收手册

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-RUNBOOK-009 |
| owner | 工程负责人 |
| approver | 经营负责人 |
| status | Ready for external execution |
| gate | G2 / BAS-026 |
| last_reviewed | 2026-07-18 |

## 目的与边界

本手册只验收 Web 登录主体、KJDS actor、审批角色和 MFA 是否真正分离。它不证明商品、利润、合规或 Ozon 发布已经获批，也不授权任何平台写操作。

只有全部步骤通过并保存证据后，`BAS-026` 才能由 `PARTIAL_BLOCKED` 转为 `DONE`。任一失败均保持 Web Listing 批准按钮隐藏、Ozon 写执行禁用。

## 前置条件

1. 使用真实 Supabase 项目，不使用本地 `legacy` 模式。
2. 由账号所有者创建两个不同用户：
   - operator：只绑定 KJDS operator actor；
   - approver：只绑定 KJDS approver actor。
3. 两个 actor 使用不同 API credential；密钥只进入运行环境，不写入仓库、截图或证据正文。
4. 配置 `KJDS_WEB_AUTH_MODE=supabase`、Supabase URL/publishable key、用户—actor 映射和既有 credential map。
5. 准备两个独立浏览器配置文件或两台设备，避免 Cookie 混用。
6. 准备一个尚未决定的测试 Approval。其资源必须是测试 Listing 草稿，Ozon 执行器保持禁用。

## 验收矩阵

| # | 操作 | 预期 | 必留证据 |
|---|---|---|---|
| 1 | operator 登录 | 进入控制台；`/auth/session` 只返回 operator actor/role，不含 user ID 或 API key | 脱敏响应、UTC 时间、浏览器配置标识 |
| 2 | operator 直接调用批准接口 | 服务端返回 403；不得因前端参数、Cookie 或 MFA 改变角色 | 状态码、request ID、审计事件 |
| 3 | approver 首次登录 | 密码正确后转到 `/mfa`，未达到 AAL2 时不能进入控制台 | 428/重定向证据、UTC 时间 |
| 4 | approver 绑定 TOTP | 只能注册当前用户因素；扫描二维码后六位码验证成功 | 因素 ID 的末六位、AAL2 状态；不得保存 QR/密钥种子 |
| 5 | approver 再查会话 | `/auth/session` 返回独立 approver actor/role，不含 operator 身份或密钥 | 脱敏响应、UTC 时间 |
| 6 | approver 决定测试 Approval | 服务端重新读取 Listing、复算摘要并记录独立批准人；仍不调用 Ozon | approval ID、草稿摘要、request ID、审计事件 |
| 7 | 重放同一决定 | 返回冲突或失败；不得产生第二次状态转换或平台写入 | 状态码、事件计数 |
| 8 | operator 自提自批 | 即使使用同一浏览器重新登录，也必须因 actor 相同或角色不足失败 | 状态码、审计 actor |
| 9 | 管理员全局撤销 approver 会话 | 旧会话后续请求失败，不能只靠旧 Cookie 继续操作 | 撤销时间、下一请求状态码 |
| 10 | 密码恢复 | 只恢复同一个 Supabase user；KJDS actor/角色不得被客户端改变 | 恢复事件、恢复后 session |
| 11 | TOTP 设备丢失 | 由管理员按正式流程撤销旧因素并重新绑定；旧因素不能继续验证 | 管理员 actor、撤销/重绑时间、因素末六位 |
| 12 | 登出 | 全局 sign-out 后敏感请求返回 401 | 登出时间、下一请求状态码 |

## 失败关闭判定

出现以下任一情况立即停止验收并保持 `PARTIAL_BLOCKED`：

- 同一 Supabase user 同时映射 operator 与 approver；
- 浏览器可提交或读取 API key、actor 或角色并影响授权；
- approver 在 AAL1 状态进入控制台或执行决定；
- operator 能调用批准接口；
- 因素 ID 不属于当前用户仍可 challenge/verify；
- Approval 可以重复决定、自提自批或绕过 Listing 摘要复验；
- 会话撤销后旧 Cookie 仍能执行敏感请求；
- 任一步触发 Ozon 写入。

## 证据包

验收结束后建立一份 Evidence Package，至少包含：

- Supabase 项目标识的脱敏值和执行环境；
- 两个 user ID 的不可逆摘要、对应 KJDS actor 和角色；
- 每步 UTC 时间、HTTP 状态、request/trace ID；
- Approval ID、Listing 草稿 ID、决定前后状态和摘要；
- 撤销、恢复、TOTP 因素重绑的管理员审计记录；
- 无 Ozon 写入的回读证据；
- 经营负责人结论：`approve`、`conditional` 或 `reject`。

禁止保存密码、TOTP QR/seed、完整 API key、访问 Token、恢复链接或完整身份文件。

## 放行后的下一步

验收通过只允许进入下一项工程变更：在 Web 中加入受限的 Listing 决定界面，并继续复用后端角色、状态机和摘要复验。该界面仍须单独经过 Spec、Correctness、Architecture 和 Evidence Review；真实 Ozon 发布由后续 Gate 决定。
