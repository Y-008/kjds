# BAS-038 Evidence 持续完整性巡检与事件升级

## 结论

控制平面现在能够主动、分批检查 Evidence 记录与底层 Blob 的一致性，而不再只在业务消费证据时发现损坏。巡检使用左连接读取快照，因此能够识别“Evidence 记录仍存在、Blob 已丢失”的故障，并同时复算实际 SHA-256 与实际字节数。

每个异常先生成一份不含原始正文的 Grade B 安全报告，再以异常内容的稳定指纹幂等创建 `medium` 运维事件。重复巡检不会重复建事件；巡检不会修复、删除或覆盖原 Evidence，也不会自动释放 Kill Switch。

本轮全部使用合成数据、SQLite 故障注入和隔离 PostgreSQL G-1；未读取真实 Ozon 凭证，未连接 Ozon，未执行平台操作。

## 规格与实现

- 主规格：`BR-026`。
- 有界分页：`limit=1..1000`、非负 `offset`，结果返回 `next_offset`。
- 故障码：`EVIDENCE_BLOB_MISSING`、`EVIDENCE_HASH_MISMATCH`、`EVIDENCE_SIZE_MISMATCH`。
- 受权入口：`POST /v1/evidence/integrity-scan`，仅 `monitor`、`risk` 或 `admin`。
- Kill Switch 已开启时，该端点仍作为安全控制可运行。
- 单项报告只包含 Evidence ID、声明/实际摘要、大小、机器码与首次发现时间，不包含原文件正文。
- 聚合扫描结果本身也固化为 Evidence，保留扫描范围、计数和异常 ID/码。
- 运维事件复用既有 `IncidentRecoveryService`，未新增表、队列或调度基础设施。

## 故障注入与行为

- 同时改变 Blob 内容和已声明大小：一次扫描同时返回哈希与大小不匹配。
- 删除 Blob、保留 Evidence 记录：左连接扫描返回缺失码并创建事件。
- 健康记录与异常记录分批扫描：分页计数及 `next_offset` 正确。
- 不同 monitor 身份重复扫描相同损坏：复用同一 finding Evidence 和同一 Incident。
- 同一异常事件关闭后再次出现：创建下一代 Incident；不会把仍在发生的损坏错误绑定到已关闭事件。
- 原损坏 Blob 保持不变；新生成的 finding/scan Evidence 均可通过独立哈希校验。
- 中等级事件不自动触发全局 Kill Switch；相关业务消费门仍各自失败关闭。
- `medium/low live` 事件可在不启用全局 Kill Switch 的前提下完成独立恢复审核；`high/critical live` 仍要求熔断保持到独立审核完成。

## 验证结果

- 定向 Evidence、Incident、API 合同回归：14 passed。
- 全量 Python：197 passed；另有 1 条既有 Starlette/httpx 弃用警告。
- Web 身份安全：6 passed。
- 密钥扫描：282 个非忽略文件通过。
- Ruff：通过。
- OpenAPI 快照：已刷新且合同测试通过。
- G-1：PASS；`evidence_integrity_monitor=true`、`ozon_response_integrity=true`。
- 隔离恢复 SHA-256：`d2b0b8626d49132e51699d082aac0354c18001ccea631a4515300e8eefd00fbf`。
- 恢复计数：`products=4`、`orders=0`、`evidence_records=20`、`read_only_pilot_runs=1`。
- 进程、数据库和临时文件清理均为 true。

## Review 结论

- Spec Review：实现与 BR-026 对齐，没有扩大为自动修复、证据删除或平台操作。
- Correctness Review：缺 Blob、哈希、大小、分页和重复扫描均有故障注入。
- Architecture Review：完整性算法由 Evidence Service 负责；Monitor 只负责固证与事件编排；Incident 继续拥有恢复责任链。
- Security Review：端点受角色控制且在 Kill Switch 下可用；异常输出无原始正文、凭证或数据库异常栈。
- Evidence Review：定向测试、全量回归、OpenAPI、完整 G-1 与隔离恢复共同支撑交付。

## 未完成边界

- 后续 `BAS-039` 已将该入口接入既有本机健康循环；外部通知渠道与机器离线时的托管运行仍未证明。
- 分页使用 offset；单次扫描期间是数据库快照，但跨页期间新增 Evidence 可能使运维方需要从 offset 0 重新执行完整轮次。
- 事件为 `medium`，不自动全局熔断；高危分级仍需结合证据类型、业务依赖图和责任人策略。
- 修复必须通过备份恢复、人工责任确认和独立复核完成。
