# Hermes Phase 0 环境审计报告

审计日期：2026-07-11
项目目录：`D:\KJDS\kjds`
审计方式：只读系统检查、现有测试执行、Docker Compose 配置校验、敏感信息文件名扫描

## 结论

当前电脑足以承担 Hermes 第一阶段开发，推荐采用 **WSL 2 + Docker Desktop + 项目独立 Python 3.12/uv 环境**。现有业务骨架可以保留，但 Environment Gate **未通过**，目前不应继续扩展 Ozon、市场数据、图片、视频、广告或 Agent 功能。

主要阻塞项是：项目尚未初始化 Git、没有 `.python-version` 和 `uv.lock`、没有项目 `.venv`、Compose 中没有 PostgreSQL、没有 Alembic、没有工程启动脚本，也尚未完成干净环境重建验证。

## 1. 当前环境事实

### 操作系统与终端

| 项目 | 检测结果 |
|---|---|
| Windows 产品标签 | Windows 10 Home China（注册表标签） |
| DisplayVersion | 25H2 |
| Build | 26200.8655 |
| 架构 | 64 位 |
| PowerShell | 7.6.0 Core |
| 当前代码页 | UTF-8，65001 |
| 系统区域 | en-US |
| 时区 | UTC+08:00 |
| 当前进程管理员权限 | 否 |

备注：Windows 注册表产品名称仍显示 Windows 10，但 Build 26200 / 25H2 与该标签存在不一致。工程决策应以 Build、WSL 和 Docker 实际能力为准，不依赖产品名称字符串。

### 硬件

| 项目 | 检测结果 |
|---|---|
| CPU | AMD Ryzen AI 9 HX 370 |
| 核心/线程 | 12 核 / 24 线程 |
| 内存 | 31.07 GB |
| 虚拟化 | 固件虚拟化已启用，Hypervisor 已存在 |
| 集成显卡 | AMD Radeon 890M |
| 独立显卡 | NVIDIA GeForce RTX 4060 Laptop GPU |
| C 盘剩余 | 56.58 GB |
| D 盘剩余 | 174.23 GB |

硬件足以运行 Codex、API、PostgreSQL、少量 Worker 和前端。Docker Desktop 当前限制约 8 GB 内存，适合第一阶段。现阶段不建议下载本地大型图片/视频模型；独显显存值由 Windows WMI 报告为 4 GB，正式决定本地生成方案前应再用 NVIDIA 工具核实。

### WSL 与 Docker

| 项目 | 检测结果 |
|---|---|
| WSL 发行版 | Ubuntu 24.04 |
| WSL 版本 | 2 |
| Ubuntu 当前状态 | Stopped |
| Docker Desktop WSL 发行版 | Running，WSL 2 |
| Docker Engine | 29.6.1 |
| Docker Compose | v5.2.0 |
| Docker Server | 正常运行 |
| Docker 分配 CPU | 8 |
| Docker 分配内存 | 约 8 GB |
| 当前 Compose 配置语法 | 通过 |

当前只有一个与本项目无关的 Docker 容器运行在端口 9999。5432、6379、8000、3000 和 9090 当前均未监听，没有发现第一阶段常用端口冲突。

### 开发工具

| 工具 | 状态 | 版本/位置摘要 |
|---|---|---|
| Git | 已安装 | 2.55.0.windows.1，当前项目尚未初始化仓库 |
| uv | 已安装 | 0.11.26 |
| Docker | 已安装且运行 | 29.6.1 |
| Node.js | 已安装 | 24.18.0 |
| npm | 已安装 | 11.16.0 |
| psql | 未安装到主机 PATH | 可选择只在容器内使用 |
| Alembic | 未安装到主机 PATH | 项目依赖尚未建立 |
| Ruff | 未安装到主机 PATH | 项目依赖尚未建立 |

### Python 环境

检测到多个 Python：

| 版本 | 路径/用途 |
|---|---|
| 3.15 alpha | Windows `py` 当前默认，不适合生产项目 |
| 3.14 | `D:\IT\python.exe`，当前 `python` 命令 |
| 3.14 free-threaded | `D:\IT\python3.14t.exe` |
| 3.12 | 用户本地正式安装，可作为项目基线 |
| 3.11 | `D:\AI\Apps\Python311\python.exe` |
| Codex bundled Python | 仅用于 Codex 文档/工具运行，不应成为项目解释器 |

当前 `D:\IT\python.exe` 已经可以导入 FastAPI、Pydantic 和 Uvicorn，且 5 项核心领域测试全部通过。但这是共享主机环境，不是可复现的项目环境；默认 Python 3.14 和 `py` 默认 Python 3.15 alpha 也会增加误用风险。

建议正式固定 Python 3.12，并由 uv 创建项目 `.venv`。不要把 Codex 缓存运行时写入任何项目脚本、配置或文档。

## 2. 当前项目状态

已有：

- `pyproject.toml`
- `compose.yaml`
- `Dockerfile`
- `.env.example`
- `.gitignore`
- FastAPI API 与领域代码
- 初始 SQL 迁移文件
- 5 项核心领域测试
- 架构与执行文档

缺少：

- Git 仓库与首个基线提交
- `.python-version`
- `uv.lock`
- 项目 `.venv`
- `AGENTS.md`
- `TOOLCHAIN.md`
- PostgreSQL 服务
- SQLAlchemy 持久化适配器
- Alembic 迁移环境
- Ruff 配置与检查
- `scripts/bootstrap.ps1` / `bootstrap.sh`
- `scripts/dev.ps1` / `dev.sh`
- 开发环境 ADR
- 干净环境重建测试

当前 API 使用内存仓储；虽然已有 SQL 表设计，但应用重启后业务数据会清空。现有 Compose 只启动 API，并使用 SQLite 环境变量，没有 PostgreSQL 服务，因此尚未达到文档要求的正式数据基线。

## 3. 测试与安全检查

| 检查 | 结果 |
|---|---|
| `python -m unittest discover -s tests -v` | 5/5 通过 |
| Docker Compose 配置解析 | 通过 |
| FastAPI/Pydantic/Uvicorn 可由主机 Python 导入 | 通过，但环境未隔离 |
| Git 工作区检查 | 无法执行，尚未初始化 Git |
| PostgreSQL 健康检查 | 未通过，服务尚未配置 |
| Alembic 迁移 | 未通过，尚未配置 |
| API 健康检查 | 代码已定义，未在独立项目环境中启动验证 |
| Ruff | 未通过，尚未配置 |
| 敏感文件名 | 未发现真实 `.env`、secret 或 credential 文件 |
| 密钥模式扫描 | 仅命中 `.env.example` 和 Compose 的占位配置，未发现可确认的真实密钥 |

安全扫描只检查仓库文本文件中的常见模式，不等同于完整秘密扫描。Git 初始化后还应使用专门的提交前秘密检查，并确保 Word、日志、数据库转储和截图不会进入公开仓库。

## 4. Windows 原生与 WSL 2 路线

### Windows 原生

优点：现有路径无需迁移，当前工具已能运行测试。
缺点：存在多个 Python，Linux 生产环境差异更大；后续 PostgreSQL、Worker、文件权限和容器挂载更容易出现环境偏差。

### WSL 2

优点：Ubuntu 24.04 已安装，Docker Desktop 已使用 WSL 2；更接近未来 Linux 服务器；适合 PostgreSQL、后台 Worker 和容器工具链。
缺点：需要迁移或重新克隆源码，并统一 Windows/WSL 的 Git、换行符和凭证使用方式。

### 推荐

选择 WSL 2 作为正式开发运行环境，源码最终放在 Linux 文件系统，例如 `/home/lunar/projects/hermes`。当前 `D:\KJDS\kjds` 保留为现有工作副本，在 Git 基线和备份建立之前不要直接移动或删除。

如果暂时不迁移，也可以先在 Windows 原生完成基线，但必须固定 Python 3.12、uv 和项目 `.venv`，并且只运行 Docker 中的 PostgreSQL，避免 Windows、WSL 和 Docker 三套数据库并存。

## 5. 建议安装与修改计划（尚未执行）

以下动作需要用户确认后再执行：

1. 在当前目录初始化 Git，并建立基线提交。
2. 选择正式源码位置：继续 Windows，或在 WSL Linux 文件系统重新克隆。
3. 用 uv 固定 Python 3.12，生成 `.python-version`、`.venv` 和 `uv.lock`。
4. 在项目开发依赖中加入 SQLAlchemy、Alembic、pytest、Ruff 和类型检查器。
5. 将 Compose 改为 API + PostgreSQL；不安装主机 PostgreSQL。
6. 将初始 SQL 迁移转为 Alembic 版本迁移。
7. 增加 PostgreSQL Repository 和事务 Outbox。
8. 增加 PowerShell/Bash bootstrap 与 dev 脚本。
9. 创建 `AGENTS.md`、`TOOLCHAIN.md` 和开发环境 ADR。
10. 从空 `.venv` 和空数据库完成一次全量重建验证。

不建议现在安装 Kubernetes、Kafka、Temporal、Redis、Elasticsearch、Milvus、ComfyUI、本地视频模型或多 Agent 框架。

## 6. Environment Gate

| 闸门 | 状态 | 说明 |
|---|---|---|
| `git_repository_initialized` | FAIL | 项目没有 `.git` |
| `git_worktree_clean` | BLOCKED | 无 Git 仓库，无法判断 |
| `project_python_isolated` | FAIL | 没有项目 `.venv` |
| `dependency_lock_exists` | FAIL | 没有 `uv.lock` |
| `docker_available` | PASS | Docker Server 与 Compose 正常 |
| `postgres_healthy` | FAIL | Compose 未配置 PostgreSQL |
| `migrations_work` | PARTIAL | 初始 SQL 可解析，但没有 Alembic/真实数据库验证 |
| `api_healthcheck_passes` | PARTIAL | 路由存在，未在隔离环境启动验证 |
| `tests_pass` | PASS | 主机 Python 下 5/5 通过 |
| `lint_passes` | FAIL | Ruff 未配置 |
| `secrets_not_committed` | PARTIAL | 未发现真实密钥，但没有 Git 历史和正式秘密检查 |
| `bootstrap_documented` | FAIL | 缺少 bootstrap/dev 脚本和 TOOLCHAIN |
| `clean_rebuild_tested` | FAIL | 尚未执行 |

**Environment Gate：FAIL。**

## 7. 下一步建议

在不删除现有代码的前提下，执行“工程基线建设”增量：Git 基线、Python 3.12 + uv、PostgreSQL + Alembic、Ruff、启动脚本和干净重建验证。Gate 通过后，再继续领域拆分和真实 Ozon 连接。
