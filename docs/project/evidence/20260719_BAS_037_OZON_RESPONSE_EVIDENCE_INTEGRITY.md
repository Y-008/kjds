# BAS-037 Ozon 响应 Evidence 完整性恢复门

## 结论

`response_captured` run 在完成或租约恢复前，现在会重新读取原始 Evidence Blob 并逐字节计算 SHA-256，同时复验唯一血缘、来源、run 引用、内容类型、证据等级、元数据和字节数。系统不再仅信任 Evidence 记录中保存的声明哈希。

缺失、断链、内容损坏或合同不匹配的 run 保持 `response_captured`，不生成成功摘要；批量回收会报告非敏感机器码并继续处理同批健康 run。

本轮只使用合成响应、SQLite 故障注入和隔离 PostgreSQL G-1；未读取真实 Ozon 凭证，未连接 Ozon，未执行平台写操作。

## 需求与边界

- 主规格：`BR-025`。
- 适用入口：Worker 主动 `finalize`、租约回收器自动恢复、检查点幂等复放。
- 完整性复验：唯一 `raw_response` 血缘、Grade A、`application/json`、固定来源、`source_ref=run_id`、元数据响应哈希、实际 Blob SHA-256、实际与声明字节数。
- 异常状态：保持 `response_captured`，`evidence_id` 仍为空，不伪造 `failed` 或 `completed`。
- 可观测输出：`raw_response_verified`、`raw_response_integrity_code`、`recovery_blocked`、`recovery_blocked_run_ids` 和 `recovery_blockers`。
- 阻塞码不包含商品正文、原始 offer、凭证或数据库异常文本。

## 实现范围

- `apps/control_plane/evidence.py`
  - 增加单一数据库快照内的记录/Blob 读取和实际哈希复算。
  - 原有 `verify` 复用同一完整性检查入口。
- `apps/control_plane/pilot_runs.py`
  - 增加机器可读的响应证据完整性错误。
  - 完成前复验实际 Blob 与 Evidence 合同。
  - 序列化时公开安全的已验证状态，不因损坏抛出原始存储异常。
  - 回收器逐 run 隔离损坏，保持总批次上限并继续恢复健康 run。
- `scripts/verify-g1.ps1`
  - 增加 `ozon_response_integrity` 持久门。
  - 合成检查点和完成结果必须返回 `raw_response_verified=true` 且无完整性错误码。

## 故障注入

- 保持字节数不变但篡改 Blob 内容：拒绝完成，返回 `RAW_RESPONSE_EVIDENCE_HASH_MISMATCH`。
- 删除 Blob、保留 Evidence 记录与血缘：拒绝完成，返回 `RAW_RESPONSE_EVIDENCE_MISSING`。
- 删除 `raw_response` 血缘：拒绝完成，返回 `RAW_RESPONSE_LINEAGE_INVALID`。
- 同批包含一个损坏 run 和一个健康 run：损坏 run 保持待恢复，健康 run 正常完成；不产生批次级连锁失败。
- 异常 run 不产生第二份摘要 Evidence。

## 验证结果

- 定向完整性/API 回归：17 passed。
- 全量 Python：193 passed，另有 1 条既有 Starlette/httpx 弃用警告。
- Ruff：`uv run ruff check .` 通过。
- Web 身份安全：6 passed。
- G-1：PASS；`ozon_response_integrity=true`、`ozon_response_recovery=true`、`ozon_run_replay_guard=true`。
- 隔离恢复 SHA-256：`34ce5d7356a39f54b6e756df33a9784754f6fbbd5d392a4af1ac6859642e4fcd`。
- 恢复计数：`products=4`、`orders=0`、`evidence_records=19`、`read_only_pilot_runs=1`。
- 进程、数据库和临时文件清理均为 true。

## Review 结论

- Spec Review：实现范围与 BR-025 一致，没有扩展到真实平台调用或自动修复损坏证据。
- Correctness Review：缺失、篡改、断链和混合批次均有故障注入；错误保持失败关闭。
- Architecture Review：完整性判断留在 Evidence/Pilot application service，Worker 和 API 不复制业务规则；未增加基础设施或迁移。
- Security/Privacy Review：对外只暴露固定错误码和内部 run ID，不回显 Blob、offer、密钥或异常栈。
- Evidence Review：定向测试、全量回归、完整 G-1、隔离恢复和清理结果足以支持工程交付。

## 未完成边界

- 不自动修复、覆盖或删除损坏 Evidence；恢复仍需备份、运维诊断和人工责任确认。
- 尚未建立持续 Evidence 巡检与告警；当前门保证消费时失败关闭。
- `OZN-003` 专用最小权限只读身份和账户负责人批准仍未完成。
- 未运行真实单 SKU Ozon Pilot，G0 仍未放行。
