# BAS-092 店铺事实快照与多模式全店增长闭环证据

- 日期：2026-07-25
- 分支：`feat/ozon-growth-fact-loop`
- 需求：BR-068 / BAS-092
- ADR：ADR-0018
- API 版本：0.50.0 / schema v1

## 交付

1. `MarketplaceGrowthWorkspace` 以小接口封装快照采集、最新观测和全店计划；生产使用 PostgreSQL 适配器，模块测试使用内存适配器。
2. 新增不可变 `marketplace_growth_snapshots` 与 `marketplace_growth_observations`，使用来源 + 幂等键唯一约束、载荷 SHA-256、观测版本和结构约束。
3. `MarketplaceGrowthPlanner.normalize_observation()` 成为采集与规划共享的规范化入口，避免存储和计算出现两套校验。
4. 新增：
   - `POST /v1/marketplace-growth/snapshots`
   - `GET /v1/marketplace-growth/observations/latest`
   - `POST /v1/marketplace-growth/portfolio-plan/latest`
5. Web 增长工作区支持保存当前 SKU 事实、查看每个 SKU 最新事实和生成全店计划；加载为工作区懒加载，不加入驾驶舱初始 31 请求。
6. Web 旧模式可从共享凭证映射安全解析唯一 Operator；容器健康检查改为 `/auth/session`，不再由静态首页制造假健康。
7. 任务导航使用 `pushState` 并监听 `hashchange`/`popstate`，浏览器返回可恢复前一个工作区。
8. 套餐与运营模式见 `docs/product/KJDS_SAAS_PACKAGING_AND_PRICING_2026.md`。店群、铺货、精品/精细化、品牌和小白工作区共用一套事实与治理内核。

## 验证

- `uv run alembic upgrade head`：升级到 `20260725_0042`。
- PostgreSQL：`marketplace_growth_snapshots`、`marketplace_growth_observations` 两张表存在。
- PostgreSQL 适配器实测：首次写入、相同载荷重放、最新观测查询通过；相同幂等键不同哈希被拒绝；测试快照按精确 ID 清理。
- `uv run ruff check .`：通过。
- `uv run pytest -q --basetemp=.pytest-tmp-kjds-growth-release`：429 passed，1 个既有 Starlette/httpx 弃用警告。
- `npm test`：27 passed。
- `npm run build`：Next.js 生产构建通过。
- `git diff --check`：通过；仅 Windows 工作树 LF→CRLF 提示。
- Docker Compose：PostgreSQL、API、Web 均为 healthy。
- `GET http://127.0.0.1:3000/auth/session`：200。
- `GET http://127.0.0.1:3000/backend/v1/integrations/health`：200。
- `GET /backend/v1/marketplace-growth/observations/latest?limit=10`：200，当前返回 0 条；本地数据库没有 Product 或利润场景，未用假商品冒充真实店铺事实。
- Playwright CLI：
  - 进入 `#growth` 可见最新店铺事实、全店方案按钮、真实空状态和建议边界。
  - `#growth`→`#finance`→浏览器返回，URL 与内容恢复到 `#growth`。
  - 新浏览器会话控制台 0 error / 0 warning。
  - 桌面和 390×844 移动端全页视觉检查通过。

## 安全边界

- 计划继续固定 `execution_mode=recommendation_only`。
- `automatic_marketplace_write=false`。
- `automatic_ad_spend=false`。
- 保存事实不创建 Listing、采购、广告或价格写入。
- 真实平台动作仍需既有 Approval、一次性许可、回读、止损和补偿链。
- 当前没有可用的 Figma 连接文件/节点，未声称写入 Figma。

## 回滚

停用三个新 API 后，原手工组合规划接口仍可使用。Alembic 降级只删除本次新增快照表，不改写 Product、Evidence、成本场景或执行历史。
