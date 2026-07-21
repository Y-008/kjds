# Readiness 证据冻结与 DecisionPacket 证据（2026-07-21）

## 结论

受控执行计划现在能够证明“当时为什么被认为可执行”，而不只记录一个布尔 Gate。实现复用现有执行计划 `evidence_json`、Approval payload、Evidence/Lineage 和 `DecisionPacket` 投影，没有新增数据表、迁移、服务或依赖。

这项工程不放行任何真实经营动作；外部执行仍由动作政策、独立审批、短期单次许可、执行时复验、全局开关和实际账户条件共同控制。

## 已实现合同

1. Readiness provider 可为每个 requirement 返回 `ready`、精确 `evidence_ids` 和稳定 `blocking_reasons`；旧布尔 provider 继续兼容。
2. 每项 requirement 在申请时被规范化并计算独立 SHA-256 `snapshot_hash`。
3. Readiness Evidence 自动并入执行计划的 Evidence 清单和 Lineage；需求门同时携带原始报告与独立接受证明，而不只携带报告 ID。
4. 规范化 Readiness 快照进入执行计划请求摘要和现有 Approval payload，随后由现有 `DecisionPacket` 确定性投影；不允许以后用新证据改写当时依据。
5. 读取计划时单独计算 `current_readiness_snapshot`。当前状态用于重新授权，冻结快照用于解释历史决定，二者不混淆。
6. 计划全部 Evidence 或冻结 Readiness Evidence 发生缺失、Blob 损坏或哈希失配时，分别返回 `PLAN_EVIDENCE_INVALID` 和 `READINESS_EVIDENCE_INVALID`，并把 `ready_for_executor` 置为 false。

## 验证证据

| 检查 | 结果 |
|---|---|
| Python 静态检查 | `uv run ruff check .` 通过 |
| 因果策略—执行—回读—回滚闭环 | 12 passed |
| 动作注册表、API、需求门、Worker、readiness 相关增量回归 | 61 passed；1 条第三方 Starlette/httpx 弃用警告 |
| Python 全量回归 | 329 passed；1 条第三方 Starlette/httpx 弃用警告 |
| Web 合同与生产构建 | 19 passed；Next.js production build 通过 |
| OpenAPI v1 快照 | 已由运行时契约重新导出 |
| 差异空白检查 | `git diff --check` 通过；仅既有 LF/CRLF 提示 |
| 冻结依据自动血缘 | 执行计划 Evidence 同时包含业务证据与 readiness 证据 |
| 独立接受证明 | Ozon 需求门的 readiness `evidence_ids` 同时包含报告和 accepted review attestation |
| 防历史改写 | DecisionPacket 读取 Approval payload 中的冻结快照，当前 readiness 另字段返回 |
| 证据损坏 | 篡改冻结 readiness Blob 后，旧计划失败关闭并返回两个稳定阻断码 |

真实 PostgreSQL 迁移与健康检查仍受本机 Docker daemon 不可用阻塞；本项没有 Schema 变化，但不能把 SQLite/单元测试当作生产数据库证据。

## 下一顺序

1. 把单动作限额提升为最小组合风险预留：先覆盖 SKU、店铺、日采购/广告总额和 13 周现金底线，不建设资本优化器。
2. 让组合额度在申请和 Worker 执行时使用同一快照/预留语义，并用幂等命令防重复占用。
3. 建立 Ozon、ComfyUI 与财务导入的脱敏 fixture 回放，覆盖超时、限流、漂移、重复结果和 readback 不一致。
4. 用先锋 SKU 的研究闭环和第二、第三 SKU 复现数据，开始真正衡量人工修改率、总运行成本和增量利润。
