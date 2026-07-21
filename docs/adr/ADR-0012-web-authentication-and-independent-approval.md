# ADR-0012：Web 认证与独立审批身份

| 元数据 | 值 |
|---|---|
| status | Accepted |
| date | 2026-07-18 |
| owner | 工程负责人 |
| approver | 经营负责人（真实账号验收待完成） |
| affects | G2 / BAS-026 / SEC-001 / Listing 审批 |

## 背景

原 Web Backend-for-Frontend 只持有一个 `KJDS_API_KEY`。它适合本地运营界面，但无法证明运营人与审批人是两个独立主体；在同一会话中增加角色切换或批准按钮只会制造“看起来双人、实际单人”的控制幻觉。

项目已采用 Supabase PostgreSQL，Next.js 使用 App Router。官方当前建议 Cookie 会话的 Next.js 应用使用 `@supabase/ssr`，并明确要求 Route Handler 自己验证身份与权限：

- [Supabase：Choosing a server package](https://supabase.com/docs/guides/auth/choosing-a-server-package)
- [Supabase：Creating a client for SSR](https://supabase.com/docs/guides/auth/server-side/creating-a-client?framework=nextjs)
- [Supabase：Multi-Factor Authentication](https://supabase.com/docs/guides/auth/auth-mfa)
- [Supabase：TOTP MFA](https://supabase.com/docs/guides/auth/auth-mfa/totp)
- [Next.js：Authentication](https://nextjs.org/docs/app/guides/authentication)

## 决策

1. 复用 Supabase Auth 与 `@supabase/ssr`，不自研密码、Token 刷新或第二套用户数据库。
2. `KJDS_WEB_AUTH_MODE=supabase` 时，登录态只通过服务端 Cookie 会话进入 Web；敏感 BFF 请求每次调用 `auth.getUser()` 获取最新用户记录，不信任浏览器提交的角色或 `getSession()` 中未复验的用户对象。
3. `KJDS_WEB_USER_ACTORS_JSON` 只保存“Supabase user ID → KJDS actor ID”的非密钥映射；真实 API 密钥只在既有 `KJDS_API_KEYS_JSON` 出现一次，由服务端按 actor 反查。
4. 一个 KJDS actor 只能有一个 API credential；非管理员身份不得同时拥有 `operator` 与 `approver`。
   Supabase 模式还必须同时存在不同的 operator user 和 approver user，否则所有 Web 会话失败关闭。
5. 浏览器不接触 API key。BFF 只在服务端给控制面添加 `X-KJDS-API-Key`。
6. 所有非安全方法必须携带与请求 URL 完全同源的 `Origin`；跨站或无 Origin 写请求在 BFF 处返回 403。
7. 审批重放继续由 Approval 状态机失败关闭；Listing 批准还要复验资源、申请人/批准人分离与 SHA-256。
8. 登出使用 Supabase 全局 sign-out；后续请求再次 `getUser()`，不能仅凭旧 Cookie 继续授权。
9. `legacy` 只用于非生产本地运营开发；`KJDS_ENVIRONMENT=production` 时配置为 legacy 必须失败关闭。
10. `approver` 会话必须达到 Supabase AAL2。未达到时返回 428 并进入专用 MFA 页面；operator 会话不因此获得或被要求审批能力。
11. TOTP 注册、因素枚举、challenge 和 verify 只通过服务端 Route Handler 执行。验证前必须复验当前用户的 approver 绑定、因素归属、六位码格式和同源写请求；浏览器不能自行声明 AAL、actor 或角色。

## 验收

- Web 单元测试覆盖非法模式、生产 legacy、用户—actor 映射、actor 凭证唯一性、approver AAL2 要求和同源写保护。
- Web 单元测试还必须证明缺少任一身份或同一用户兼任 operator/approver 时失败关闭。
- Python 安全测试拒绝非管理员 `operator+approver` 组合。
- 自提自批与重复决定均失败。
- 登录、回调、会话、全局登出、MFA 状态/注册/验证和 BFF 动态路由通过 Next.js 生产构建。
- 没有 Supabase 配置、无登录会话、无 actor 绑定或无 actor credential 时分别以 503/401/403 失败关闭。

## 当前未证明

- 尚未连接真实 Supabase Auth 项目和两个真实用户。
- 尚未完成真实登录、TOTP 设备绑定、管理员撤销、邮件恢复、因素丢失恢复和真实审批人操作演练。
- 本 ADR 不授予 Ozon 发布权限。
