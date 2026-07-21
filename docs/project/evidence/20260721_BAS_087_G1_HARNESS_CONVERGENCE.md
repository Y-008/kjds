# BAS-087 G1 Harness 收敛证据

日期：2026-07-21
分支：`refactor/g1-harness`

## 冻结的场景边界

G1 PowerShell 继续负责且必须真实跨进程验证：

- PostgreSQL 启动或复用、临时数据库创建、迁移降级与重新升级；
- Transactional Outbox 与五组 PostgreSQL 数值完整性脚本；
- 密钥扫描、身份配置、Ruff、完整 Pytest、Web 测试和隔离生产构建；
- API、Web 和 Ozon Worker 容器构建与启动；
- Ozon Worker 离线预检、显式执行意图与执行时复验；
- 真实 HTTP 身份校验、Kill Switch、数据库写入、事件、Evidence、Lineage 与完整性扫描；
- 24x7 健康环、备份与隔离恢复、Web 到 API 的服务端代理；
- 端口、进程、临时文件和临时数据库清理。

以下领域场景不再在 PowerShell 中重复编排，而由已有 Pytest 合同承担：

| 场景组 | 主要测试真源 |
|---|---|
| 候选、需求报告、研究信号 | `test_candidate_evidence_review.py`、`test_demand_report_gate.py`、`test_research_inbox.py` |
| DecisionPacket、校准与生命周期 | `test_decision_contracts.py`、`test_decision_lifecycle.py` |
| 因果实验、策略、影子账与发布 | `test_causal_experiments.py`、`test_pilot_runs.py` |
| 有限执行、Readback、重试与恢复 | `test_ozon_worker.py`、`test_incident_recovery.py`、`test_operations_governance.py` |
| Passport、三报价、样品与采购 | `test_intake.py`、`test_sourcing.py`、`test_procurement.py`、`test_reserved_evidence_workflows.py` |
| 成本权威、财务导入、对账与现金预测 | `test_cost_authority_registry.py`、`test_finance.py`、`test_ozon_finance_review.py` |
| Evidence 健康与完整性 | `test_evidence_integrity.py`、`test_evidence_health_task.py`、`test_health_loop.py` |

## 收敛结果

- `verify-g1.ps1` 从 2,395 行收敛到 697 行；领域 HTTP 请求和重复断言不再与测试代码双重维护。
- G1 报告不再列出没有在 Harness 内独立执行的几十个布尔字段；完整 Pytest 统一汇总为 `domain_contracts`。
- 迁移验证从易漂移的固定版本号改为读取并验证唯一 Alembic head；当前迁移仍会写入报告并用于恢复验收。
- 仍保留一个真实 API 最小闭环：身份、Loop Registry、Kill Switch、PostgreSQL 写入、事件、Evidence、Lineage 和完整性监控。
- 新增机器合同，阻止已迁移领域路由重新回流 PowerShell，并强制保留基础设施关键接缝。
- 隔离 Web 构建显式复制 `app`、`features` 与 `lib`，覆盖组合根拆分后的真实生产依赖。
- 生产镜像统一打包机器可读注册表目录，避免策略、写路径与 Loop Registry 因 Docker 白名单漂移而缺失。
- PostgreSQL 数值约束脚本各自建立并清理最小夹具，不再依赖旧领域 API 的执行顺序，也不向备份留下孤儿引用。
- 没有新增测试框架、运行依赖、数据库对象或第二套编排器。

## 验收方法

- PowerShell 语法解析；
- G1 Harness 合同测试；
- 完整本地 G1（包含 PostgreSQL、容器、API、Worker、Web、备份恢复与清理）；
- 密钥扫描、写路径合同、Ruff、全部 Python 测试、Web 测试、生产构建与远程 CI。

## 本地实证

2026-07-21 完整执行 `scripts/verify-g1.ps1`，结果为 `PASS`：

- 唯一 Alembic Head：`20260721_0040`；迁移降级与重新升级通过；
- Transactional Outbox、五组 PostgreSQL 数值完整性与全部领域合同通过；
- 345 项 Python 测试、21 项 Web 测试和隔离生产构建通过；
- API、Web、Ozon Worker 生产镜像及执行意图隔离通过；
- 身份、Kill Switch、Evidence、Lineage、完整性健康环与 Web 代理通过；
- PostgreSQL 备份、隔离恢复、计数核对及最终资源清理通过。

运行报告位于忽略目录 `.runtime/G1_VERIFICATION.json`，不作为静态状态真源提交。
