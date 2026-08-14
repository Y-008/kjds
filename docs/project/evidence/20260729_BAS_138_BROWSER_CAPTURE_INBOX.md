# BAS-138 Browser Capture Inbox 工程与真实运行 Evidence

## 1. 结论

- 基线：`feature/batch-opportunity-mining-059`，应用版本 `0.59.0`。
- 工程切片：`BrowserCaptureInbox`、Alembic `0071`、认证 API/OpenAPI、
  `/capture-inbox`、Manifest V3 最小权限助手和真实 Chrome 1688→KJDS
  C 级 Evidence 回执已经实现并验证。
- 状态仍为 `IN_PROGRESS`：扩展包尚未由用户确认后加载到 Chrome，因此
  本证据只证明真实页面观察经手工受控 envelope 完成端到端落账，以及扩展
  源码/权限合同通过静态和单元测试；不声称扩展分发已验收。
- 外部写始终为 `false`。没有联系供应商、下单、付款、创建 Ozon Listing、
  发布、改价、加库存或投广告。

## 2. 真源和边界

- Requirement：[BR-112](../MASTER_SPEC.md)
- ADR：[ADR-0059](../../adr/ADR-0059-browser-capture-inbox.md)
- 浏览器助手：
  `extensions/kjds-browser-capture/`
- API：
  - `POST /v1/browser-capture-inbox/preflight`
  - `POST /v1/browser-capture-inbox/submissions`
  - `GET /v1/browser-capture-inbox/submissions`
- 浏览器助手权限仅为 `activeTab`、`scripting`、`storage`；没有
  `host_permissions`、`content_scripts`、cookies、localStorage、
  webRequest、`<all_urls>`、内部 API 或 CAPTCHA 绕过。
- 当前 Principal 没有 entity authority 时保留真实 tenant/store，
  返回 `entity_ref=null`、`quarantined` 和
  `entity_scope_authority_missing`，没有把 tenant 伪装为 entity。
- `public_display_price` 只保留公开页面价义，不能成为 Supplier Offer、
  actual cost 或完整 CM3。未选择精确变体时
  `variant_selection_unverified` 在独立 Evidence binding 后仍阻断晋级。

## 3. 数据库与迁移

- Alembic single head：`20260729_0071`。
- 独立临时 PostgreSQL 空库从 base 升级到 `0071` 成功。
- PostgreSQL 直接绕过服务层写入 `item_count=0` 被 CHECK 拒绝；测试事务
  回滚后表计数仍为 0。
- 真实库只执行 `0070→0071` 前向迁移。
- 迁移前后既有市场 Observation 均为 26 条，按
  `id|snapshot_sha256|evidence_id|blob_sha256` 排序后的聚合 SHA-256 均为
  `f93869c58f3eb49a4a04b47a009934c8770bfa2e7346f7efc6ea102e98bb90ce`。
- 新收件箱表初始为 0；真实验收后为 1。

## 4. 真实 Chrome 1688→KJDS 回执

只读取 1688 可见商品详情页：

- 来源：
  `https://detail.1688.com/offer/1045914391146.html`
- 商品：`1045914391146`
- 标题：
  `2026跨境新款手钩沙滩裙流苏手勾花亚马逊爆款镂空沙滩罩衫`
- 供应方显示：`汕头市涵艺服饰有限公司`
- 页面显示价：`42.00 CNY`，`public_display_price / unit_price`
- 页面显示 MOQ：2 件；库存：900 件；重量：150g；国内运费：6 CNY 起。
- 可见变体集合：白色、黑色、杏色、咖啡色、卡其色；均码。
- 没有在详情页完成精确变体选择，故保存为 `variant_key=unselected`，
  服务端明确保留 `variant_selection_unverified`。

不可变回执：

- submission：
  `bci_afb42807036a46519bb208939a117015`
- request SHA-256：
  `cfb21515770a9933e8f70fc4a458d94940c3acaf153fb2ed98428642a88fa71f`
- Evidence：
  `evd_6d5e9c531b884fb4ad4b4399c12689fb`
- Evidence SHA-256：
  `cfb21515770a9933e8f70fc4a458d94940c3acaf153fb2ed98428642a88fa71f`
- tenant/store：`default / ozon-primary`
- entity/status：`null / quarantined`
- Evidence integrity：`ready`
- promotion：`no_data`
- Supplier Offer、actual cost、Product、Listing、Approval、Permit、
  external write：全部 `false`。

这条记录是 AI ERP 的真实外部观察入口，不是利润款、可上架 SKU 或采购指令。

## 5. API、容器和浏览器

- `/health/ready`：HTTP 200，版本 `0.59.0`，DB `ok`。
- PostgreSQL/API/Web/media-worker：四容器 `healthy`。
- OpenAPI 同时包含 preflight 与 submissions 路由；匿名 GET 实测 401。
- 桌面 CSS viewport：
  `innerWidth=2048`、`clientWidth=scrollWidth=2028`。
- 移动端设备仿真：
  `innerWidth=clientWidth=scrollWidth=390`。
- 截图：
  - `output/playwright/release-0.59.0/browser-capture-inbox-desktop.png`
    SHA-256
    `a0968a0a265e2f4468542061f15b6a07d35da80ef2e2a0937ec45c0347e11c75`
  - `output/playwright/release-0.59.0/browser-capture-inbox-mobile-390.png`
    SHA-256
    `8aa880b14cab44f4522e770c93faaafd265948938817caf3ffbfd2bdd4cd0b80`

## 6. 验证命令与结果

- `uv run python scripts/verify_secrets.py`
  - 787 个非忽略工作树文件、581 个历史路径，passed。
- `uv run ruff check .`
  - passed。
- `uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-full-bas138-retry`
  - `806 passed`。
- `uv run pytest ... tests/test_api_contract.py`
  - `32 passed`。
- Web：
  - `npm ci`：0 vulnerabilities
  - `npm test`：`66 passed`
  - `npm run build -- --webpack`：36 routes，含 `/capture-inbox`
- `git diff --check`
  - passed；只有 Windows 行尾提示。
- `node --check`：
  `background.js`、`popup.js` 均 passed。

## 7. Review findings

- `P0 / auto-fix / closed`：原实现只把 item 级
  `variant_selection_unverified` 放在载荷中，独立 binding 后可能错误显示
  ready。现已进入 preflight/project blockers，`promotion_ready` 同时要求
  无语义 gaps，并增加回归测试。
- `P0 / auto-fix / closed`：新增直接 SQL 事务模块未登记 Outbox coverage，
  导致全量测试失败。现已登记为 `internal_only`，全量 806 通过。
- `P1 / defer-with-explicit-state / open`：Manifest V3 助手尚未经用户确认后
  加载到 Chrome。不得把源码存在写成分发/安装完成；BAS-138 保持
  `IN_PROGRESS`。
- `Info`：Maozi/荔枝参考插件的 Cookie、宽域权限和内部存储模式只作为拒绝
  方案，未复制到 KJDS。
