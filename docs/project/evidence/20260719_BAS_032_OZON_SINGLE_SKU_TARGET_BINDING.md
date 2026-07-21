# BAS-032 Ozon 单 SKU 只读目标绑定验证

| 元数据 | 值 |
|---|---|
| 日期 | 2026-07-19 |
| Gate | G0 / OZN-003 |
| 状态 | DONE_ENGINEERING |
| 事实晋升 | false |
| requires_review | true |

## 目的

防止单 SKU 影子 Pilot 请求一个 Ozon `offer_id`，却把空响应、批量串组、缺失目标字段或其他商品响应记录成该 SKU 的成功事实。

## 合同

- 只读合同版本固定为 `ozon-product-read-v1`。
- 只允许产品信息 `/v3/product/info/list` 与版本化商品属性只读端点参与该合同。
- 两个响应都必须恰好包含一个对象，且对象 `offer_id` 与请求目标一致。
- 空结果返回 `OZON_TARGET_NOT_FOUND`，多结果返回 `OZON_TARGET_AMBIGUOUS`，错目标返回 `OZON_TARGET_MISMATCH`，缺字段按 `OZON_SCHEMA_DRIFT` 失败关闭。
- 原始响应进入与 run 绑定的不可变 Evidence；控制面摘要只保留合同版本、两个计数、状态 SHA-256、错误码和熔断状态。
- 控制面再次要求合同版本为当前版本、信息与属性计数均为 1、总记录数为 2、状态哈希合法；旧版或不完整成功 run 不能提 Candidate Claim。

## 实现边界

- 复用现有 `OzonSellerClient`、`OzonReadOnlyWorker`、`PilotRunService`、`EvidenceService` 和 `ReadOnlyClaimService`。
- 未新增数据库表、迁移、消息系统、第二连接器或平台写能力。
- 错误与控制面摘要不包含请求 offer、意外 offer、商品正文、Client ID 或 API Key。
- 目标不匹配属于请求/数据绑定失败，不触发盲目重试；传输、限流、5xx 与 schema 漂移继续沿用既有有界重试和熔断策略。

## 验证

- 相关 Ruff：PASS。
- Ozon Worker、Pilot Run、Read-only Claim 回归：22 passed。
- 覆盖空响应、多响应、错误 offer、属性串组、缺失 offer 字段、摘要脱敏、原始响应 Evidence、旧合同 Claim 拒绝、幂等、租约和独立复核入口。
- 完整 G-1：PASS；160 项 Python 测试、6 项 Web 身份安全测试和 273 个非忽略文件密钥扫描通过。
- 当前迁移 head：`20260718_0036`；隔离备份恢复 SHA-256：`e6088e3a217dc00603d06771e739c5b29253798e47abac5ae450b21b4345b816`。
- G-1 证据报告：`.runtime/G1_VERIFICATION.json`。
- 因果实验分层价值模型测试改为使用现有的确定性平衡分配键，连续 3 次定向回归均为 `12 passed`，消除随机 SRM 假红；生产随机化与 SRM 规则未修改。

## Review Findings

| 严重度 | Finding | 处理 |
|---|---|---|
| P0 | 未发现 | no-op |
| P1 | 尚无经专用最小权限身份取得的真实 Ozon 单 SKU 响应，不能证明线上 payload 已满足 v1 合同 | defer：保留 `UNK-013`，由 OZN-003 后的单 SKU 影子 Pilot 取证 |
| P2 | 属性端点版本可能继续变化 | no-op：保留显式端点版本、404 兼容回退和 schema drift 失败关闭，不预建通用适配框架 |

## 放行边界

本增量只证明工程合同和失败关闭行为。它不创建、读取、轮换或撤销 Ozon Key，不证明真实商品事实，不批准 G0，也不允许上架、改价、库存、订单或财务写入。
