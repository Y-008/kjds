# SKU-000 Ozon Seller 搜索分析导出门复验证据

| 字段 | 值 |
|---|---|
| 日期 | 2026-07-20 |
| Gate | G0 / `SKU-000` |
| 状态 | `PARTIAL_BLOCKED` |
| 来源 | 已登录 Ozon Seller 官方页面、Ozon 官方产品说明 |
| 证据等级 | B / `requires_review=true` |
| 平台写入 | 否 |

## 本次实际核验

- 从 Ozon 官方文章“Новая аналитика по запросам товаров”的“Попробовать инструмент”链接取得当前官方入口：`https://seller.ozon.ru/app/analytics-search/search-results/apz`，没有猜测内部路由。
- 当前 Seller 登录态可读取“我商品的搜索查询”，页面提供商品/SKU、类目、日期、平台和商品特征筛选，并显示“下载报告”。
- 默认可见窗口为 2026-07-11 至 2026-07-17；页面列出两个现有商品及其查询入口。现有目录只能作为基线，不能冒充三个新候选。
- 尝试把日期改为 2026-06-21 至 2026-07-18 时，页面未接受跨月 28 天范围；没有修改页面代码、伪造请求或绕过产品限制。
- 恢复默认筛选后实际点击“下载报告”，页面弹出 `PREMIUM` / `PREMIUM_LITE` 订阅选择和“开通 Premium”，本地下载目录没有产生报告文件。
- Ozon 官方说明同时注明部分搜索查询指标仅对 Premium / Premium Plus 开放。因此当前可读页面不等于已取得可逐字节复验的原始报告。
- Ozon Developer 官方说明确认存在 `POST /v1/analytics/product-queries` 与 `POST /v1/analytics/product-queries/details`。前者给出我方商品查询的汇总分析，后者给出具体查询明细；它们对应 Seller“商品在搜索中 → 我商品的查询”，不是全市场或类目机会报告。
- 官方契约页确认汇总方法以 `Client-Id` / `Api-Key` 调用，请求包含 `date_from`、`date_to`、`page`、`page_size`、`skus`、`sort_by` 和 `sort_dir`；`skus` 与 `page_size` 上限均为 1000。最近一个月可选非当日区间，计算需 1–2 天；更早数据需 Premium 系列订阅且按周查询。

## 结论

1. `SKU-000` 继续阻塞：没有原始报告文件、导出任务标识、筛选快照和 SHA-256，页面读数或截图不能满足 `BR-035/036`。
2. 不能把萌啦、Seerfar、妙手或 51Selling 的数据替换成 Ozon 官方报告；它们只能进入 C/D 级辅助研究信号并交叉检查。
3. 不通过前端篡改、未公开接口或抓包绕过 Premium；是否购买订阅属于经营负责人支出决定。
4. Seller API 方法已核验为“我方现有商品查询分析”，可用于现有 Listing 的搜索词诊断和账户内页面/导出交叉验证，但不能发现尚未上架的全市场候选，因此不能作为 `SKU-000` 类目需求报告的等强替代。当前不为错误场景新增 Worker。
5. 旧的 `data.ozon.ru/app` 路径仍需账户主体自行决定是否接受要约和个人信息条款。Seller 搜索分析已登录可读并不代替该法律决定。

## 仍需人工决定

- 方案 A：经营负责人决定是否开通可导出报告的 Ozon Premium，并导出最近 28 天原件。
- 方案 B：账户负责人通过 Ozon Data 或其他 Ozon 官方类目级报告取得新候选所需的全市场需求原件。若未来要诊断现有 Listing，再单独批准专用只读 Seller API 身份接入上述查询分析端点；不得使用现有宽权限 Key 直接试跑，也不得把该响应冒充类目需求。
- 任一方案取得原件后，仍须由不同复核人确认账户来源、窗口、非公开示例属性和文件哈希，才能解除 `SKU-000`。

## 官方来源

- Ozon 官方“Новая аналитика по запросам товаров”：<https://seller.ozon.ru/media/news/novaya-analitika-po-zaprosam-tovarov/>
- Ozon Seller 官方搜索分析入口：<https://seller.ozon.ru/app/analytics-search/search-results/apz>
- Ozon Developer 关于搜索查询分析 API：<https://dev.ozon.ru/news/512-Novye-metody-dlia-raboty-s-analitikoi-po-zaprosam-tovarov-v-Seller-API/?__rr=1>
