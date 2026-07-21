# ADR-0009：最小端到端关联链

- 状态：Accepted
- 日期：2026-07-17
- Gate：G-1

## 背景

API 已有 `X-Request-ID`，试运行已有 `run_id`，有限执行已有 `command_id`，但这些标识无法跨 worker 的多次 HTTP 调用和证据记录稳定关联。当前只有一个控制平面和两个 Ozon worker，不需要先建设完整分布式追踪平台。

## 决策

1. API 接受符合安全格式且不超过 128 字符的 `X-Request-ID`、`X-Trace-ID`；非法或缺失值使用标准库生成。
2. `request_id` 表示一次 HTTP 请求；`trace_id` 表示一次 worker 操作。worker 同一操作共享 trace，每次 HTTP 调用生成独立 request。
3. 只读试运行在启动时保存 `request_id/trace_id`，并随 `run_id` 写入脱敏结果证据。
4. 有限执行回执保存 `request_id/trace_id`，并与 `command_id`、既有证据链接一起返回。
5. PostgreSQL 为两类记录的 `trace_id` 建索引；迁移 0035 为历史记录生成可识别的 legacy 关联值。
6. 不引入 OpenTelemetry、日志采集器、追踪数据库或新依赖。

## 结果与边界

G-1 已用一个 trace 串联试运行和有限执行，验证 `request_id + trace_id + run_id + command_id + evidence_id` 可追溯。当前实现不提供分布式 span、采样、服务拓扑或集中告警；当独立服务增多、排障跨进程或 SLO 明确需要时，再以现有关联头为兼容入口升级。

验证证据：`docs/project/evidence/2026-07-17-end-to-end-correlation-verification.md`。
