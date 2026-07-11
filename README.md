# KJDS — AI 跨境电商控制平面

这是整体架构的第一版可运行骨架。工程基线固定为 Python 3.12、uv、PostgreSQL 17、Alembic 和 Ruff，覆盖：

- 市场原始观察、来源证据和可复算机会评分；
- Product / Compliance / Quality Passport；
- 图片、视频、文案 Brief，生成资产和五项 QA；
- 带预算封顶与止损线的增长实验；
- 订单费用账本和订单级 CM1 / CM2 / CM3；
- 高风险动作双人审批；
- 受模式和幂等约束的 Agent 任务；
- 稳定的领域事件与外部连接器协议。

整体边界见 [架构说明](docs/architecture.md)，经营执行见 [90 天执行总纲](Ozon_90天执行总纲.md)。

## 当前目录

```text
apps/control_plane/
  api.py              HTTP API
  domain.py           稳定领域实体和状态
  repository.py       测试/开发存储适配器
  services.py         商品、订单、利润、审批、Agent
  intelligence.py     市场数据和机会评分
  content_growth.py   图片/视频/文案与增长实验
  connectors.py       Ozon/广告/物流/结算连接器协议
migrations/
  001_initial.sql     持久化模型与事务事件表
tests/
  test_core.py        核心业务约束测试
```

## 本地运行

```powershell
.\scripts\bootstrap.ps1
.\scripts\dev.ps1
```

打开 `http://127.0.0.1:8000/docs` 查看并调用接口。

也可以使用 Docker：

```powershell
docker compose up --build
```

## 测试

通过项目锁定环境执行：

```powershell
uv run ruff check .
uv run pytest
```

## 当前成熟度

这是架构底座和首条业务纵切，不是生产系统。PostgreSQL、Alembic 和健康检查已经接通，但领域读写当前仍使用内存仓储，重启后业务数据会清空；下一增量是实现 SQLAlchemy Repository 与事务 Outbox，不改变现有领域服务和 API。生产前还必须加入身份认证、密钥托管、备份恢复、真实平台连接器和监控告警。

环境规范见 [TOOLCHAIN.md](TOOLCHAIN.md)，环境决策见 [ADR-0001](docs/adr/ADR-0001-development-environment.md)。
