# ADR-0004：API v1 合同与兼容策略

- 状态：Accepted
- 日期：2026-07-17
- Owner：工程负责人
- Approver：经营负责人（Gate Review 时确认）

## 背景

控制台、worker 和运维脚本已经共同使用 `/v1` API，但成功响应未声明合同版本，普通业务错误与认证错误的结构也不一致。直接给所有成功响应增加外壳会破坏现有客户端。

## 决定

1. `/v1` 继续保持现有成功响应体，所有响应增加 `X-KJDS-Schema-Version: v1` 和 `X-Request-ID`。
2. `/version` 显式返回 `schema_version`，启动脚本按服务身份与 schema 版本识别进程，不绑定应用补丁版本。
3. 错误响应保留旧客户端使用的 `detail`，并增加 `error.code`、`error.message`、`request_id` 和 `schema_version`。
4. `docs/project/contracts/openapi-v1.json` 是 v1 快照；接口变更必须显式重新生成并通过快照测试。
5. v1 只允许增加可选字段和新端点。删除字段、改变类型/枚举语义或改变既有状态码必须新建 `/v2` ADR 与迁移窗口。

## 取舍

该方案没有引入 API Gateway、代码生成器或新的 Schema Registry。它不能自动证明业务语义兼容，但能以最小成本阻断无意的 OpenAPI 漂移，并保持现有 Web 和 worker 可用。

## 验收与回滚

- 合同测试验证成功响应头、向后兼容的错误体和 OpenAPI 快照。
- G-1 必须继续通过 Web 代理身份、API auth 和真实数据库 smoke。
- 若客户端不接受新增响应头或错误字段，可回滚中间件扩展；旧 `detail` 和成功体始终保持不变。
