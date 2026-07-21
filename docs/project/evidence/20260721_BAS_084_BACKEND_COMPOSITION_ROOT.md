# BAS-084 后端组合根收敛证据

## 结论

后端组合根已从单文件领域实现收敛为单一运行时对象和八个领域 Router，公共 HTTP 合同、数据库模型和运行依赖均未改变。

## 变更边界

- `apps/control_plane/api.py` 从 4,178 行缩减为 208 行，只保留应用创建、中间件、异常边界、Router 注册和兼容入口。
- 新增简单的 `RuntimeServices` 与 `build_runtime()`；每个 Repository、Service 和 Provider 只构造一次，不引入 DI 框架。
- 路由按系统、证据治理、决策科学、执行运营、商品内容、采购供应、财务导入和 Ozon 平台八个稳定领域拆分。
- 请求模型与运行时依赖移出组合根；没有新增数据库迁移、第三方依赖或公共 API。
- 测试通过替换 `app.state.runtime` 中的服务注入替身，不再修改组合根模块全局变量。

## 已验证

- 密钥与禁止文件扫描：398 个非忽略文件通过。
- 写路径注册表和外部调用边界：通过。
- Ruff：通过。
- Python：341 项通过；包含 OpenAPI 精确快照。
- Web：19 项通过，生产构建成功。
- `git diff --check`：通过。

## 待远程验证

本机 Docker Desktop 守护进程未运行，因此没有把本地 PostgreSQL smoke 记为通过。PR 必须由 GitHub Actions 的 `postgres-smoke` 完成 PostgreSQL 17、唯一 Alembic head、API 启动和 `/health/ready` 验证；检查未通过不得合并。

## 失效与回退

- 任一公共路径、响应、operation ID 或 OpenAPI 快照变化，本交付失效。
- 任一领域服务在应用创建期间被重复构造，本交付失效。
- 可直接回退本 PR；没有数据迁移或外部事实需要补偿。
