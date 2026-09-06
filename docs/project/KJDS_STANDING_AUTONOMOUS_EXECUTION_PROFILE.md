# Standing Autonomous Execution Profile

`StandingAutonomousExecutionProfile` 是一次性启用的治理配置，用于在无人值守场景下为**单个精确命令**生成短期、不可复用的 `ExternalWritePermit`。它不保存或读取平台凭证，也不直接调用 Ozon、广告或社媒 API；实际执行仍由既有 adapter 完成，并由 adapter 校验命令哈希、有效期和单次消费。

## Admission gates

每次请求都必须同时满足：

1. profile 已启用，且处于 activation/expiry 窗口；
2. tenant、entity、store、channel、operation 与 profile 完全匹配；
3. `proof_ready`、`evidence_fresh`、`data_quality_valid`、`external_readback_passed`、`rollback_available` 均为真；
4. `EconomicGuardResult.status=allowed`，且命令金额不超过 profile 限额；
5. 请求包含非空幂等键。

任一条件缺失都会返回 `blocked` 和稳定原因，不生成 Permit。成功结果包含 `profile_sha256`、`command_sha256`、`decision_sha256` 和一次性 Permit，便于审计、重放和回滚关联。

## Scope and governance

profile 的创建、启用、暂停、过期和版本变更应作为治理事件保存，并由独立 owner/reviewer/compliance 身份复核。Agent 不能修改 profile、预算、租约、Kill Switch 或自身权限。profile 的 `enabled=true` 只表达已完成治理授权，不能绕过现有 Approval、Permit、Readback、Rollback 和 Kill Switch 约束。

实现：`apps/control_plane/autonomous_execution_profile.py`；纯合同测试：`tests/test_autonomous_execution_profile.py`。
