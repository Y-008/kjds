# Ozon 连接器可靠性验证记录

| 元数据 | 值 |
|---|---|
| date | 2026-07-17 |
| requirement | BR-003 / BR-008 / BAS-012 |
| decision | ADR-0010 |
| status | PASS（工程闭环）；真实 Ozon 账户回放 BLOCKED |
| migration | 无新增迁移；复用 Evidence Ledger 与 Lineage Edge |

## 验证范围

- 读请求只对传输错误、HTTP 429 和 5xx 做最多三次有界尝试。
- 连续可重试故障开启进程内熔断，冷却后半开探测，成功后关闭。
- 写请求网络异常不自动重试，返回稳定 `OZON_WRITE_UNCERTAIN`。
- 非 JSON、顶层结构错误和端点关键字段缺失以稳定 schema drift 错误失败关闭。
- 成功只读 run 在完成前必须上传原始响应包；缺失原件、哈希或字节数不一致均拒绝完成。
- 原始响应包只包含响应路径、状态、允许的响应头和原始 body，不包含请求头、Client ID、API Key 或 Token。
- 脱敏完成摘要保存原始证据 ID，并通过 `raw_response` lineage 可追溯。

## 执行结果

```text
ruff: PASS
pytest: 130 passed
Alembic head: 20260717_0035
G-1: PASS
G-1 connector_safety: true
G-1 end_to_end_trace: true
Web production build: PASS
cleanup_processes/database/files: true
```

专项测试覆盖正确原件上传、无原件拒绝、哈希不一致拒绝、worker 脱敏摘要、批量结果、关联头传播、schema 漂移和 5xx 熔断恢复。完整 G-1 在一次性 PostgreSQL 中创建只读 run，先上传响应包，再以相同 SHA-256/字节数完成 run，并确认返回的原始证据 ID 与 run 一致。

运行报告保存在 `.runtime/G1_VERIFICATION.json`；该文件是本机运行产物，不替代本验证记录和不可变业务证据账。

## 已知边界

- 熔断状态仅存在于单个 Worker 进程；多实例共享熔断尚无真实需求。
- 本轮使用合成响应包验证控制链，未宣称真实 Ozon 字段映射或账户权限已经验证。
- 原件仍受当前 Evidence 上传大小上限约束；超过上限或需要对象存储时必须重新评审。
- 真实 429、5xx、字段漂移和业务响应回放需要 OZN-001/OZN-002 的最小权限账户与一手样本。
