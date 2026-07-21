# 端到端关联链验证

- 日期：2026-07-17
- Gate：G-1
- 数据库：一次性 PostgreSQL `kjds_g1_smoke`
- Alembic head：`20260717_0035`
- 完整回归：128 passed
- G-1：PASS
- 报告：`.runtime/G1_VERIFICATION.json`

## 覆盖范围

- API 对 `X-Request-ID`、`X-Trace-ID` 做长度与字符边界校验，非法输入不会原样进入响应或持久层；
- Ozon 读 worker 与有限执行 worker 在一次操作内传播同一 trace，每次 HTTP 请求生成独立 request；
- `read_only_pilot_runs` 保存启动 request/trace，完成证据包含 request、trace、run；
- `limited_execution_receipts` 保存回执 request/trace，并与 command 和既有 evidence 链接；
- 两张表均建立 trace 索引，历史数据在迁移时获得 legacy 关联值。

## G-1 结果

- 0035 从空库升级、回退到 0024、再升级：PASS；
- Ruff：PASS；
- Pytest：128 passed；仅有既存 Starlette/httpx 弃用警告；
- Next.js production build：PASS；
- `end_to_end_trace=true`：同一 `trace-g1-controlled-loop` 串联试运行与有限执行，分别验证 request、run、command 和 evidence ID；
- API、治理、因果实验、执行/回滚、采购、财务、Web 代理：PASS；
- 进程、数据库、文件清理：PASS。

## 边界

本批提供可查询、可证据化的关联基线，不等同于完整 APM。未引入集中日志、分布式 span、采样、指标告警或第三方追踪平台；这些能力只在服务规模与 SLO 证明必要时增加。

0035 尚未取得新的备份恢复复演：当前环境缺少 `pg_dump`/`pg_restore` 且无 Docker 控制权限，恢复证据仍停留在 0029。
