# BAS-093 证据优先商业数据中枢工程证据

- 日期：2026-07-26
- 需求：BR-069 / BAS-093
- ADR：ADR-0019
- 版本：Control Plane `0.51.0`

## 已实现

1. 新增 `MarketplaceCatalogWorkspace` 深模块，接口仅包含导入已复验 Evidence 和读取指定店铺最新目录。
2. `PilotRunService.verified_product_response_bundle()` 在交出正文前复验成功 run、唯一 raw-response 血缘、来源、等级、内容类型、声明/实际 SHA-256 和字节数。
3. 固定解析 `ozon-response-bundle-v2 / ozon-product-read-v1`，逐个复验两个内嵌响应的 Base64、SHA-256、HTTP 状态、路径集合、单一目标和 offer 一致性。
4. PostgreSQL 迁移 `20260726_0043` 保存不可变目录快照与规范化商品条目，店铺范围和幂等键冲突失败关闭。
5. 同步字段覆盖 offer/SKU、名称、价格、库存、状态、尺寸重量、属性、图片、视频和文档引用。外部媒体固定标记为 `unverified_external_reference`。
6. 统一经营前台的“现有商品增长工作台”可选择 A 级 Seller 原始响应、导入快照并查看目录；原始正文不在页面展示。
7. 1688/采购报价继续使用 `SourcingService`，竞品与行业动态继续进入 Research Signal Inbox，物流与利润继续使用逐项成本权威和 15 项全成本模板；没有建立重复事实源。
8. 浏览器 JSON 写请求增加 `x-kjds-csrf: same-origin-fetch` 标记；代理仍优先精确校验 `Origin`，仅在浏览器未发送 Origin 时接受自定义头/同源 Referer。跨站普通表单不能设置该头，跨站脚本需要 CORS 预检，现有代理不开放 CORS。

## 真实回放

- 输入：既有 A 级 Ozon Seller 原始响应 Evidence（ID 已在 Evidence Ledger）。
- 结果：快照 `mcs_2b9eae9e7ebb49b08fe7421fc63d7cb1`，1 个真实目录条目。
- 媒体投影：15 个图片引用、2 个视频引用。
- 数据库事务曾因官方库存对象形态与固定样本不同而被约束拒绝并完整回滚；解析器补充兼容后再次成功，证明约束和失败关闭实际生效。
- 自动创建 Product：否。
- 自动采购、改价、上架、广告或其他 Ozon 写入：否。

## 验证

- `uv run python scripts/verify_secrets.py`：通过。
- `uv run ruff check .`：通过。
- `uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-commerce-hub`：436 passed。
- `npm test`：29 passed。
- `npm run build`：通过。
- `uv run alembic heads/current`：单一 `20260726_0043 (head)`。
- Compose：PostgreSQL、API、Web 健康；API `/health/ready` 返回 `0.51.0` 和数据库正常。
- Playwright：生产 Web 登录态下进入 `#growth`，可见真实目录条目、价格/库存、15 个图片引用、2 个视频引用及“未核权外部引用”；通过前台重放相同幂等导入成功，控制台 0 error / 0 warning；全页截图位于 Git 忽略的 `output/playwright/commerce-data-hub.png`。

## 明确未完成

- 没有在缺少正式开放合同、凭证和用途条款时声称已打通 1688 API；当前使用既有导入/受控浏览器/人工核验适配边界。
- 没有把第三方竞品或行业文章自动晋升为经营事实。
- SaaS 对外售卖前仍需 tenant/store 强隔离、连接凭证托管与轮换、来源条款登记、删除/导出和用量计费。

## 审查结论

- P0：无。
- P1（已处理）：生产浏览器的同源 JSON POST 未携带可选 Origin，最初被 CSRF 门拒绝；增加自定义同源请求标记和单元测试后，前台幂等导入成功，跨站 Origin 仍优先失败关闭。
- P2（已处理）：固定样本与真实 Ozon 库存形态不同；数据库约束触发事务回滚，解析器补充对象/数组双形态并增加回归测试。
- Info：真实目录现为 1 个条目，Canonical Product 仍为 0，符合“不自动创建商品”的需求边界。
