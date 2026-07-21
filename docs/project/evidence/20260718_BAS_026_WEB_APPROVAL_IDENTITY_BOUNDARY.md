# BAS-026 Web 独立审批身份边界

## 结论

状态：`PARTIAL_BLOCKED`

- 工程实现和本地验证已完成；真实 Supabase 项目、两个真实用户和经营负责人验收尚未完成。
- Web 生产身份复用 Supabase Auth 与 `@supabase/ssr`，没有自研密码、Token 刷新或第二套用户数据库。
- `KJDS_WEB_USER_ACTORS_JSON` 只保存 Supabase user ID 到 KJDS actor ID 的非密钥映射；API key 仍只存放在既有 `KJDS_API_KEYS_JSON`。
- BFF 每次敏感请求都在服务端调用 `auth.getUser()`，再按 actor 取唯一 credential；API key 不进入浏览器。
- 写请求必须携带完全同源的 `Origin`；无 Origin 或跨源写请求在 BFF 处失败关闭。
- 非管理员身份同时拥有 `operator` 与 `approver` 会在控制面启动时被拒绝。
- Supabase Web 配置缺少独立 operator user 或 approver user，或同一 user 兼任两者时，全部会话失败关闭。
- 会话接口只返回 KJDS actor 与角色，不向浏览器返回 Supabase user ID 或 API key。
- approver 会话必须达到 Supabase AAL2；未完成 MFA 时返回 428 并进入专用验证页，operator 不受此路径影响。
- TOTP 注册、challenge 和 verify 由服务端执行，且复验 approver 角色、因素归属、六位码格式和同源请求。
- `legacy` 只保留给本地运营开发，生产环境配置为 legacy 会失败关闭。

## 已冻结的正式实现合同

1. 生产环境使用 Supabase Cookie 会话；登录、PKCE 回调、会话查询和全局登出均由服务端 Route Handler 处理。
2. 运营人与审批人必须使用不同 Supabase user、不同 KJDS actor、不同 credential 和独立审计身份。
3. 浏览器不得提交 actor、角色或 API key；身份映射和 credential 解析只在服务端完成。
4. BFF 同源校验负责 CSRF 边界；Approval 单次状态转换负责不可重放；全局登出与逐请求 `getUser()` 负责撤销后的失败关闭。
5. API 继续校验申请人/批准人分离、Approval 状态、资源归属与 Listing SHA-256，前端显示与隐藏不能代替授权。
6. approver 必须在当前服务端会话达到 AAL2；MFA 注册、状态和验证接口不能绕过用户—actor 绑定。
7. 真实双账号验收完成前，Web 不开放 Listing 批准按钮；Ozon 写执行仍未放行。

## 已验证

- Web 身份配置、双身份拓扑、approver AAL2 与同源写保护：6 个 Node 测试通过。
- Next.js 生产构建通过，包含 `/login`、`/mfa`、`/auth/login`、`/auth/callback`、`/auth/logout`、`/auth/session`、三个 MFA Route Handler 和 `/backend/[...path]`。
- Python 定向验证：35 个测试通过，覆盖角色冲突、自提自批和重复决定失败。
- 本地运行冒烟：登录页 200；legacy 会话仅返回本地运营身份；无 Origin 写请求返回 403。
- Ruff 与 `git diff --check` 通过。
- 完整 `./scripts/verify-g1.ps1`：PASS；152 个 Python 测试、6 个 Web 身份安全测试、265 个非忽略文件密钥扫描、Next.js 生产构建、API/Web/PostgreSQL、迁移回放与隔离恢复均通过。
- 隔离恢复 SHA-256：`5b35ec4300806d885df36d67f1303c61132269f24295a13ee9358cd0e2141cdd`。

## 尚未完成

- 连接真实 Supabase 项目，创建并绑定独立 operator 与 approver 用户。
- 用真实 TOTP 设备验收 AAL2、管理员撤销、邮件恢复、因素丢失恢复和两个浏览器会话的分离效果。
- 由真实经营负责人使用独立账号完成一次 Listing 决定演练。
- 真实 Ozon 发布仍未放行。

真实执行必须遵循 [Supabase 双账号审批验收手册](../09_SUPABASE_DUAL_CONTROL_ACCEPTANCE.md)，并将结果作为独立 Evidence Package 留存；不能用截图数量或本地构建通过代替业务验收。

## 依据

- [ADR-0012：Web 认证与独立审批身份](../../adr/ADR-0012-web-authentication-and-independent-approval.md)
- [Supabase：Choosing a server package](https://supabase.com/docs/guides/auth/choosing-a-server-package)
- [Supabase：Creating a client for SSR](https://supabase.com/docs/guides/auth/server-side/creating-a-client?framework=nextjs)
- [Supabase：Multi-Factor Authentication](https://supabase.com/docs/guides/auth/auth-mfa)
- [Supabase：TOTP MFA](https://supabase.com/docs/guides/auth/auth-mfa/totp)
- [Next.js：Authentication](https://nextjs.org/docs/app/guides/authentication)
