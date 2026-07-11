# Hermes Environment Gate

复核日期：2026-07-11

| 闸门 | 状态 | 证据 |
|---|---|---|
| Git 仓库初始化 | 待最终提交 | 已准备忽略规则和基线文件 |
| Git 工作区干净 | 待最终提交 | 完成基线提交后复核 |
| 项目 Python 隔离 | PASS | `.venv` 使用 Python 3.12.10 |
| 依赖锁存在 | PASS | `uv.lock` 已生成 |
| Docker 可用 | PASS | Docker Server 与 Compose 正常 |
| PostgreSQL 健康 | PASS | PostgreSQL 17 容器 healthy |
| 迁移可执行 | PASS | Alembic `20260711_0001 (head)` |
| API 健康检查 | PASS | `/health` 返回 API 与 database 状态 ok |
| 测试通过 | PASS | pytest 5/5 |
| Lint 通过 | PASS | Ruff 无错误 |
| 未提交真实密钥 | PASS | 仅保留 `.env.example` 和开发占位值 |
| Bootstrap 已文档化 | PASS | Windows/Bash bootstrap 与 dev 脚本齐备 |
| Compose 配置 | PASS | API + PostgreSQL 配置可解析 |

当前已验证命令：

```text
uv sync --extra dev
docker compose up -d postgres
uv run alembic upgrade head
uv run ruff check .
uv run pytest
uv run uvicorn apps.control_plane.api:app
GET /health
```

剩余 Gate 动作仅为 Git 基线提交与提交后干净状态复核。
