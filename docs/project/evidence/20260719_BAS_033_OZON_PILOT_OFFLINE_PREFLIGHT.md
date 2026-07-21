# BAS-033 Ozon Pilot 离线预检验证

| 字段 | 值 |
|---|---|
| 状态 | DONE_ENGINEERING |
| 日期 | 2026-07-19 |
| Gate | G0 前置工程门，不构成 G0 放行 |
| 事实晋升 | false |
| requires_review | true |
| 真实 Ozon 调用 | 未执行 |
| 平台写操作 | 未执行 |

## 目标

将首个 Ozon 单 SKU 只读 Pilot 的默认入口改为离线、失败关闭的预检。操作员不显式传入 `-Execute` 时，系统只校验配置合同，不启动控制平面依赖、不构造 HTTP 客户端，也不访问 Ozon。

## 已冻结合同

- 首次 Pilot 只允许一个 `offer_id`，禁止批次、游标和自定义分页。
- Ozon 只允许 `https://api-seller.ozon.ru` 与固定 `/v4/product/info/attributes` 端点。
- 控制平面仅允许 HTTPS；本机、loopback 和 Compose `api` 服务名可使用 HTTP。
- 必须存在 Pilot Reader、Ozon Client ID 和 Ozon API Key；Pilot Reader Key、Ozon API Key、通用 API Key 与执行 Worker Key 不得复用。
- 预检输出只包含合同版本、布尔值、计数和 SHA-256，不输出密钥、原始 Pilot/offer/幂等键或 URL 查询。
- PowerShell 入口先以 `--no-deps --preflight` 运行；仅预检通过且操作员显式传入 `-Execute` 才进入现有隔离 Worker。

## 验证结果

- Ruff：PASS。
- 离线预检定向测试：22 passed。
- 全量 Python：182 passed（另有 1 条既有 Starlette/httpx 弃用警告）；Web 身份安全：6 passed。
- 完整 G-1：PASS，`ozon_pilot_preflight=true`，PostgreSQL 迁移/回滚、生产容器、API→Web 健康链、隔离备份恢复与清理均通过。
- 密钥扫描：275 个非忽略工作区文件通过；预检容器输出未包含合成 Key、Client ID 或原始 offer。
- 隔离恢复 SHA-256：`0f1eda0f9339f85d49c4a7dfb483e2d187b39daebcf8e4da17aceecf8462e829`。
- 机器报告：`.runtime/G1_VERIFICATION.json`。

## 未证明事项

- 未证明 Ozon 真实身份属于专用最小权限角色，也未读取、创建、轮换或撤销任何 Key。
- 未证明真实单 SKU API 响应符合 `ozon-product-read-v1`；仍由 `OZN-003` 和账户负责人批准阻塞。
- 未证明商品可售、供货可得、合规成立或 CM3 为正；本增量不创建 Listing、不生成图片、不发布商品。
- 离线预检使用当前部署镜像；部署或代码变化后必须重新构建镜像并重跑 G-1。

## 结论

工程入口已从“运行命令即可能联网”收紧为“默认只离线预检、显式执行才联网”。这降低误用和密钥混用风险，但不替代真实账号治理、业务证据和独立人工审批。
