# BAS-035 Ozon 只读运行一次性执行授权

| 字段 | 值 |
|---|---|
| 状态 | DONE_ENGINEERING |
| 日期 | 2026-07-19 |
| Gate | G0 前置工程门，不构成 G0 放行 |
| 事实晋升 | false |
| requires_review | true |
| 真实 Ozon 调用 | 未执行 |
| 平台写操作 | 未执行 |

## 问题

只读 run 原本以幂等键保证记录唯一，但命中既有 run 时仍返回普通历史记录。Worker 无法区分“本次新获执行权”和“只是读取历史结果”，因此相同幂等键可能再次调用 Ozon、重复保存响应或重复完成 run。

## 已实现合同

- 控制面只有在事务内新建 run 时返回 `execution_granted=true` 与 `idempotency_replay=false`。
- 同一幂等键命中任何既有在途、已完成或已过期 run 时，返回同一历史 run，并明确 `execution_granted=false`、`idempotency_replay=true`。
- Worker 在首次 Ozon 请求之前检查一次性执行权；字段缺失、值为 false 或历史重放时直接返回控制面结果，不访问平台、不采集第二份原始响应、不重复完成。
- 采用安全优先的 at-most-once 语义：若控制面首次授权响应在网络中丢失，不自动重新授予执行权；等待旧租约回收后，操作员以新的可追踪幂等键发起人工受控重试。
- 不新增数据库、队列、分布式锁或第三方依赖；现有唯一约束与租约继续负责 run 记录和中断回收。

## 验证结果

- 定向 Pilot/Worker/预检回归：45 passed；Ruff PASS。
- 全量 Python：187 passed（另有 1 条既有 Starlette/httpx 弃用警告）；Web 身份安全：6 passed。
- 完整 G-1：PASS，真实 API 烟测先创建并完成一个合成 run，再用相同幂等键重放；返回同一 run、`status=completed`、`execution_granted=false`、`idempotency_replay=true`。
- G-1 机器结果：`ozon_run_replay_guard=true`、`ozon_pilot_preflight=true`、`ozon_worker_execution_intent=true`。
- 密钥扫描：277 个非忽略工作区文件通过。
- 隔离恢复 SHA-256：`d6376b149bb864b27c030d99d0bcc13f89ef3060024fedb4e26f58f86c5d2ede`；数据库、进程与临时文件均完成清理。
- 机器报告：`.runtime/G1_VERIFICATION.json`。

## 边界与失败处理

- 本增量保证“相同逻辑 run 不会由 Worker 自动执行第二次”，不保证上游网络恰好一次；Ozon 请求发出但响应丢失时仍需人工核对外部状态。
- 只有新 run 才会重新评估当前 Pilot、独立 Review、时间窗口、Kill Switch、目标与日预算；历史重放没有执行权，因此无需也不得访问平台。
- 没有真实 Ozon 权限、最小权限证明和一手商品输入，`OZN-003` 与 G0 仍未解除；本次未读取真实 Key、未访问 Ozon、未生成 Candidate Claim 或 Formal Fact。
