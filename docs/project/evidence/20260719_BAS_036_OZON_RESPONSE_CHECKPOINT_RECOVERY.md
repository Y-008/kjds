# BAS-036 Ozon 成功响应检查点与恢复闭环

## 结论

Ozon 只读 Worker 的成功路径已从“平台返回后直接完成 run”收紧为两阶段控制面提交：先把原始成功响应固化为不可变 Evidence 并将 run 标记为 `response_captured`，再只依赖已落库数据完成 run。控制面超时或 5xx 只会有界重试检查点/完成请求，不会再次调用 Ozon。

本轮只使用合成响应和隔离 PostgreSQL 验证；未读取真实 Ozon 凭证，未连接 Ozon，也未执行任何平台写操作。

## 需求与状态机

- 主规格：`BR-024`。
- 成功状态机：`started → response_captured → completed`。
- `response-checkpoint` 对相同响应幂等返回同一 Evidence；同一 run 的哈希、字节数、记录数或摘要变化会失败关闭。
- `finalize` 只读取检查点中持久化的结果，不访问外部平台；重复完成返回既有结果且不重复存证。
- 租约到期时，`response_captured` run 由回收器从持久化响应恢复为 `completed`；只有仍停留在 `started` 的 run 才按 `RUN_LEASE_EXPIRED` 失败。
- Worker 未取得 BAS-035 的一次性执行授权时，仍不得调用 Ozon。

## 实现范围

- `apps/control_plane/pilot_runs.py`：成功响应检查点、完成恢复、幂等复放、不可变校验和回收器分流。
- `apps/control_plane/api.py`：新增响应检查点和完成端点。
- `apps/control_plane/ozon_read_worker.py`：平台请求成功后只提交检查点与完成；控制面传输错误/5xx 最多三次重试，4xx 不重试。
- `apps/control_plane/evidence.py`：并发唯一键冲突时读取并复用胜出 Evidence/血缘，避免把数据库竞争暴露为业务失败。
- `docs/project/contracts/openapi-v1.json`：从运行时 OpenAPI 重新生成。
- `scripts/verify-g1.ps1`：增加检查点/完成双重重放和 `ozon_response_recovery` 持久门禁。

## 失败场景验证

- 相同检查点重复提交返回同一 Evidence ID。
- 已捕获响应由租约回收器完成，不被误标为租约过期。
- 回收动作留下独立 reaper actor 证据。
- 响应摘要或完整性字段变化被拒绝。
- 完成请求重复提交不产生第二份 Evidence。
- 控制面连续 5xx 只重试控制面请求；测试桩确认 Ozon 读取仍只发生一次。

## 验证结果

- 定向测试：31 passed。
- 全量 Python：190 passed，另有 1 条既有 Starlette/httpx 弃用警告。
- Ruff：`uv run ruff check .` 通过。
- Web 身份安全：6 passed。
- PowerShell 语法检查通过。
- 密钥扫描：278 个非忽略工作区文件通过。
- G-1：PASS，`ozon_response_recovery=true`、`ozon_run_replay_guard=true`，进程、数据库与临时文件清理均为 true。
- 隔离备份恢复 SHA-256：`ef61fcd969a7bd27cc15c502bf911f0a96121583eee3a7b065e3b5158bd80060`；恢复后 `products=4`、`orders=0`、`evidence_records=19`、`read_only_pilot_runs=1`。

## 未完成边界

- `OZN-003` 的专用最小权限只读身份、真实凭证隔离和账户负责人批准仍未完成。
- 未运行真实单 SKU Ozon Pilot，无法声称真实响应已满足合同。
- G0 仍未放行；该工程门只降低平台成功后控制面中断导致重复读取或结果丢失的风险。
- 既有 Starlette/httpx 弃用警告需随依赖兼容升级单独处理，不影响本轮门禁结果。
