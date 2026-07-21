# BAS-030 Web 交付镜像与 Compose 健康链验证

| 元数据 | 值 |
|---|---|
| 日期 | 2026-07-18 |
| Gate | G-1 |
| 结论 | PASS |
| 范围 | Web 生产镜像、Compose 健康依赖、G-1 运行时验证 |

## 问题

此前 Web 只通过本地 Next.js build 和 dev server 烟测。它能证明源码可构建，却不能证明实际交付镜像包含正确产物、以正确身份运行，或能在 Compose 中等待 API readiness 后完成服务端代理。

## 最小改动

- 使用 Next.js 原生 `output: "standalone"`，不引入新框架或运行依赖。
- 增加多阶段 `web/Dockerfile` 和最小 `.dockerignore`，运行阶段使用内置 `node` 非 root 用户。
- 为 API 和 Web 增加仅使用各自运行时标准能力的健康检查。
- Web 与 Ozon workers 依赖 API `service_healthy`，而不是容器“已启动”。
- G-1 构建并真实启动生产 Web 镜像，验证首页包含 KJDS 标识并记录 `web_container_health=true`。

## 可复验证据

- `docker compose build web`：PASS。
- 生产 Web 镜像启动：Next.js `16.2.10` 监听 `0.0.0.0:3000`，容器用户为 `node`。
- `docker compose config --quiet`：PASS。
- 真实 Compose API + Web 联调：
  - API health：`healthy`
  - Web health：`healthy`
  - Web 首页：HTTP 200，包含 KJDS 标识
  - Web 服务端代理 `/backend/v1/products`：HTTP 200
- 完整 `scripts/verify-g1.ps1`：
  - Alembic head：`20260718_0036`
  - Python：152 passed
  - Web：6 passed
  - `container_import=true`
  - `web_container_health=true`
  - 隔离恢复 SHA-256：`149703c36f4a52a730ffd66144ac4eea5344b68867c0aa6399b690decc440d7f`
  - 恢复计数：products 4、orders 0、evidence 19、pilot runs 1
  - 资源清理：进程、临时数据库、临时文件均为 true

首次完整 G-1 没有被包装成成功：新 Web 门通过，但 operations queue 的固定 `as_of=2026-07-18T12:00:00Z` 已早于执行时刻，导致 SLA 检查失败。根因修复为基于当前 UTC 的未来观察点，随后完整 G-1 复跑 PASS。这样验证不会在日期推进后自行失效。

## 边界

- 这是本地开发 Compose 与生产形态镜像验证，不是镜像仓库发布或云部署。
- 未完成生产 Supabase 双用户、真实设备 AAL2、撤销/恢复演练。
- 未改变 G0 状态，不启用 Ozon 写操作，也不替代真实 SKU、供应商、合规或财务证据。
