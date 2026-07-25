# BAS-089 批准 Listing 到 Ozon 受控执行闭环证据

- 日期：2026-07-25
- 状态：`DONE_ENGINEERING`
- Gate：G2–G6
- 依赖：BAS-078、BAS-080、BAS-082、OZN-003
- 迁移：`20260724_0041`

## 交付

批准的 Ozon `ListingDraft` 现在可以作为 `approved_listing_draft` 不可变来源建立受控执行计划。服务端重读 Listing Approval 和当前草稿，复算摘要，从已接受的写前只读 Claim 取得真实 offer 状态，并派生 Ozon import item、目标 SKU、前置哈希和回滚 item；Web 不提交 adapter、target、intended patch 或 rollback patch。

执行计划冻结 Listing Approval、草稿摘要、Evidence、source-aware readiness 与风险上下文，并申请独立 Execution Approval。`20260724_0041` 为历史因果策略计划回填来源字段，同时允许批准 Listing 来源，并对来源组合、审批外键和 Ozon 执行证据幂等键增加数据库约束。

批准 Listing 的执行 readiness 固定覆盖：

- `demand.real_execution`；
- `listing.snapshot_unchanged`；
- `product.passports`；
- `listing.russian_native_review`；
- `listing.image_qa`；
- `finance.cost_complete`；
- `finance.cm3_positive`；
- `finance.actual_cost_authority`；
- `listing.product_source_binding`；
- `ozon.before_state_claim`；
- `ozon.execution_identity`；
- `kill_switch.released`。

俄语母语复核与 Ozon 专用执行身份复核都固化为不可变 Grade A Evidence，要求提交人与复核人分离，接受结论必须逐项通过；拒绝、过期、损坏、血缘缺失或 Listing 内容变化均失败关闭。Web 只向 Reviewer、Compliance 或 Admin 展示这两个复核入口，身份盘点只显示脱敏引用、文件名和哈希，不读取或保存凭证。

`OzonExecutionWorker` 在 claim 和写入尝试前重跑同一授权、readiness、Kill Switch 与 Evidence 完整性检查。一次性 permit 只允许一个写入尝试；完整 Ozon 响应先进入不可变 Evidence，再解析远端 task ID、轮询 import 状态并做写后商品回读。租约过期或结果不确定统一记录为 `uncertain` 并进入事故/恢复边界。补偿使用独立 rollback 命令和新的授权，不改写原执行历史。

写路径注册表同时冻结请求入口、正式写表、服务入口、唯一 Worker、Ozon 端点所有权、执行时复验、单次 permit、回读和补偿合同。`availability=enabled` 只表示工程能力存在。

## 验证结果

- Listing authority、readiness、计划、Worker、API 与安全专项：`96 passed`。
- 全量 Python：`415 passed, 1 warning`。
- Ruff：`All checks passed`。
- Web：`24 passed`。
- Next.js 生产构建：通过，13 个路由生成完成。
- Alembic：单一 head 为 `20260724_0041`。
- PostgreSQL 独立临时库：空库升级到 0041、降级到 0040、再次升级到 0041 全部通过；临时库已删除。
- 当前 Compose API：使用本工作区镜像重建，`/health/ready` 返回 `status=ok`、`database.status=ok`。
- Secret scan：461 个未忽略工作树文件与 458 个历史路径通过。
- `git diff --check`：通过，仅输出既有 Windows 行尾转换提示。
- npm 生产依赖审计：0 vulnerabilities。既有 PostCSS override 从 8.5.10 升至 8.5.23，修复 `<=8.5.17` 的任意文件读取/路径穿越公告；Web 测试与生产构建在升级后重新通过。

唯一警告来自现有 Starlette TestClient 对 `httpx` 的弃用提示，不影响本次合同结论。

## 安全与运行边界

- 没有连接真实 Ozon 账户，没有读取、创建、轮换或暴露 API Key。
- 没有接受外部条款、付款、采购、发布 Listing、广告或财务入账。
- Web 的复核和计划入口不排队命令、不 claim、不消费一次性写许可。
- `KJDS_LIMITED_EXECUTION_ENABLED` 和真实 Worker 执行仍默认关闭。
- OZN-003、真实专用最小权限身份、真实商品、真实需求原件和经营批准未完成，因此状态只能是工程完成，不是 G6 运行放行。

## 下一步

由账户负责人在仓库外完成 OZN-003：建立专用最小权限执行身份、固化不含凭证值的 Grade A 盘点并由另一身份复核。随后在经营负责人批准且 Kill Switch 可演练的隔离账户中，以单 SKU、单次、数量 1 和显式最大损失执行真实影子验收；在此之前不得开启运行开关。
