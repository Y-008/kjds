# KJDS — AI 跨境电商控制平面

KJDS 是面向跨境电商经营的模块化单体控制面。它统一管理商品、证据、成本与利润、审批、动作授权和外部执行回读；首个业务纵切面是 Ozon 俄罗斯市场。

系统坚持以下边界：

- PostgreSQL 保存经营事实，Transactional Outbox 交付跨边界事件；
- 所有真实副作用经过唯一动作授权、单次许可、执行时复验和 Readback；
- `research`、`forecast`、`commitment` 与 `actual` 不得互相冒充；
- ComfyUI 只执行受控媒体工作流，生成结果必须回到 KJDS 的 Evidence、Lineage、QA 和审批链；
- n8n 只承担外围定时、通知和受控 API 触发，不拥有业务状态；
- 当前不建设第二后台、第二审批系统、微服务、Kafka、Temporal 或 Kubernetes。

## 唯一真源

| 内容 | 文档 |
|---|---|
| 老板、团队与 Coding Agent 统一入口 | [项目.md](项目.md) |
| 稳定需求、业务不变量和架构约束 | [MASTER_SPEC.md](docs/project/MASTER_SPEC.md) |
| 当前任务、状态、依赖、Owner 和下一动作 | [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](docs/project/03_REMAINING_WORK_AND_PARALLEL_PLAN.md) |
| 稳定系统边界 | [architecture.md](docs/architecture.md) |
| Gate 定义与放行标准 | [02_ROADMAP_AND_GATES.md](docs/project/02_ROADMAP_AND_GATES.md) |
| 架构决策 | [ADR](docs/adr/) |
| 对应版本的验收证据 | [evidence](docs/project/evidence/) |
| 文档总导航 | [项目文档入口](docs/project/README.md) |

README 不维护迁移号、测试数量或任务完成度。实时本地验证结果由 `.runtime/G1_VERIFICATION.json` 生成且不提交。

## 本地启动

复制 `.env.example` 为 `.env`，按注释填写开发配置。不要提交或发送 `.env`、数据库密码、Ozon 凭证、Supabase service role key、银行资料或客户数据。

```powershell
.\scripts\bootstrap.ps1
.\scripts\dev.ps1
```

API 文档：`http://127.0.0.1:8000/docs`

也可以使用 Docker：

```powershell
docker compose up --build
```

生产型数据库迁移使用项目锁定环境：

```powershell
uv run python -m alembic upgrade head
```

## 质量门

日常快速门禁：

```powershell
.\scripts\verify-fast.ps1
```

清理或降本审计：

```powershell
.\scripts\audit-cleanup.ps1 -IncludeCommands
```

基础检查（快速门禁会执行其中核心步骤）：

```powershell
uv run python scripts/verify_secrets.py
uv run ruff check .
uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local
git diff --check
```

Web 变更另运行：

```powershell
Set-Location web
npm ci
npm test
npm run build
```

数据库、API、Worker、迁移或运行边界变更还必须运行完整 G-1：

```powershell
.\scripts\verify-g1.ps1
```

远程交付固定经过真实 Pull Request，并等待 `backend-quality`、`web-quality`、`postgres-smoke` 三项检查通过。公开仓库 `Y-008/kjds` 已对 `main` 启用 GitHub 分支保护，禁止强推和删除，并要求解决 Review 会话。

## 真实资料准备

公开空模板位于 `web/public/startup/`。真实资料只放入 Git 忽略的本地工作区：

```powershell
.\scripts\prepare-startup-package.ps1
uv run python scripts/validate_startup_package.py .runtime/startup-intake
uv run python scripts/validate_startup_package.py .runtime/startup-intake --require-review-ready
```

模板校验不读取原件、不写数据库、不晋升事实，也不会放行采购、发布、广告、补货或财务入账。真实动作仍需 Evidence、Passport、成本/利润快照、独立复核和服务端授权。

## 代码入口

```text
apps/control_plane/   后端模块化单体与外部适配器
web/                  非技术经营控制台
migrations/           数据库迁移
tests/                单元、合同与集成测试
scripts/              本地运行、验证与恢复工具
docs/                 架构、项目规格、ADR 与证据
```

公共 HTTP 合同以应用生成的 OpenAPI 和 [固定快照](docs/project/contracts/openapi-v1.json) 为准。新增能力必须先找到对应需求、动作策略、写路径、验收证据和回滚方式。
