# KJDS Compose 迁移边界合同

## 目的

Compose 运行时把数据库 schema 的所有权限制在一次性的 `migrate` 服务中。
`api`、Web 和 Worker 只使用已迁移数据库上的专用运行主体。API 重启、滚动更新
或 Worker 重启都不会隐式执行 Alembic DDL。

## 身份与变量

| 变量 | 允许的服务 | 语义 |
|---|---|---|
| `KJDS_DATABASE_URL` | `migrate` | 迁移管理员/owner DSN，仅用于 `alembic upgrade head` |
| `KJDS_RUNTIME_DATABASE_URL` | `api`、需要数据库的 Worker | 非 owner、非 superuser 的运行主体 DSN |
| `KJDS_MIGRATION_HEAD` | 构建标签和 `migrate` | 期望的代码迁移 head；不能替代数据库版本检查 |

两个 DSN 都必须由部署配置明确提供；Compose 不用默认值合成密码、主机或运行
主体。`KJDS_RUNTIME_DATABASE_URL` 必须指向与迁移数据库相同的端点，但登录主体
必须不同。运行主体的创建、授权和密码轮换属于数据库管理员/部署系统职责，不能
由 API 启动时临时创建。

`migrate` 镜像启动时拒绝同时收到 `KJDS_RUNTIME_DATABASE_URL`；API 服务的环境
映射不包含 `KJDS_DATABASE_URL`。因此即使服务定义被复制或重启，也不会把运行
凭据误用作 DDL 凭据。

## 启动顺序

```text
postgres healthy
        ↓
migrate (one-shot, exit 0)
        ↓
api healthy
        ↓
web / media-worker / read-only workers
```

`api.depends_on.migrate.condition=service_completed_successfully` 是启动门。迁移
失败时 API 不会启动；迁移成功后可安全重启 API，而不会再次执行迁移。迁移版本
由镜像中随发布物携带的 `migrations/` 和 `KJDS_MIGRATION_HEAD` 标签共同核对，
`/health/ready` 仍会复验运行数据库的实际 head 和必需表。

## 运维命令

第一次部署或发布新 schema 时：

```powershell
# 先用部署系统注入两个已 provision 的 DSN，再仅渲染配置检查边界
docker compose --env-file .env -f compose.yaml config

# 常规启动；migrate 成功后 API 才会被 Compose 拉起
docker compose --env-file .env -f compose.yaml up --build
```

只重跑迁移服务时使用一次性命令，并在同一发布快照下执行：

```powershell
docker compose --env-file .env -f compose.yaml run --rm migrate
```

不要把 `KJDS_DATABASE_URL` 放入 API、Web、Worker 的环境或 secret；不要通过 API
启动钩子、健康检查或应用代码执行 `alembic upgrade`。生产部署应使用文件/秘密
管理器注入 DSN，并保留迁移服务的退出码、镜像摘要、迁移 head 和回滚证据。

## 证明范围

`tests/test_compose_migration_boundary.py` 检查 Dockerfile stage、服务环境隔离、
成功依赖条件和不启动容器的 `docker compose config` 渲染。该合同证明的是启动
边界，不证明数据库已在当前机器实际迁移、运行主体已 provision、生产高可用或
外部平台读回；这些仍需 PostgreSQL、发布和 G-1 证据。
