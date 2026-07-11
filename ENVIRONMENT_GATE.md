# Hermes Environment Gate

复核日期：2026-07-11

| 闸门 | 状态 | 证据 |
|---|---|---|
| Git 仓库初始化 | PASS | `main` 分支，基线提交 `83346aa` |
| Git 工作区干净 | PASS | 基线提交后无未提交文件 |
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
| 干净容器重建 | PASS | Python 3.12-slim 从锁文件构建，迁移和 `/health` 通过 |

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

**Environment Gate：PASS。**

工程基线已经建立，可以进入下一阶段；领域持久化仍需从内存 Repository 迁移到 PostgreSQL，这是业务实现增量，不再是环境阻塞项。
