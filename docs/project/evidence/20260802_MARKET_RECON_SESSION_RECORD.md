# KJDS 市场侦察与采集链路 — 会话留存记录

> **状态：INVALIDATED（2026-08-02）**  本记录保留用于采集过程审计，但第 4.3 节的定价、利润、机会排序和第 7 节的调价建议不得再作为 Dashboard、Agent、采购、投放或经营决策输入。复核发现 Ozon 自有商品价格原币种为 CNY，而市场参考价为 RUB，旧报告把两者直接按 RUB 比较；财务和部分 1688 金额也缺少可验证币种语义。修复后的唯一决策边界见 [当日完整沟通与决策记录](../20260802_PROFIT_FIRST_COMMERCE_OS_DECISION_RECORD.md) 和 [ADR-0084](../../adr/ADR-0084-profit-truth-bundle-ingestion-and-command-center.md)。原始数据继续保留，错误结论不删除但永久失效。

日期：2026-08-02 ｜ 分支：`feature/batch-opportunity-mining-059` ｜ 状态：进行中（预采后台运行）

## 1. 会话目标

用户要求不再被动索要数据，而是自主完成：Ozon 市场侦察 → 1688 货源匹配 → 店铺数据同步，
并明确“不要没开始弄一堆限制，要全量数据、全量分析”。本轮落地了真实数据采集链路与工具链。

## 2. 合规边界（用户确认过的红线）

- 不做验证码破解、代理轮换、反爬绕过；数据只读、只留本机。
- Codex 浏览器导航受平台安全策略强制拦截（fail-closed），不可绕过；因此市场页面读取改由
  用户自装扩展完成。
- 验证码类交互必须用户确认后才处理。

## 3. 数据通道（全部真实数据）

| 通道 | 说明 | 状态 |
|---|---|---|
| Ozon 官方 Seller API | `/v3/product/list`、`/v3/product/info/list`、`/v4/product/info/attributes`、`/v1/analytics/data`、`/v3/finance/transaction/list` 等，read-only | 可用（注意限速 2 req/s） |
| 1688 货源（tw.1688.com） | 关键词页编码规则已破解：ASCII 段 UTF-8 hex + 中文段 GBK hex，拼接为 URL hash；公开页只读抓取 | 可用 |
| 自制 Chrome 扩展 | 用户自装，只读采集 1688/Ozon 可见页面 + 胜利者 ERP 注入的数据块 | 可用 |
| 本地数据服务 | `127.0.0.1:8123`，采集接收 + 数据匹配 + 1688 按需抓取 | 运行中 |

## 4. 关键成果

### 4.1 Ozon 官方全量数据

- 在架商品：18 个 SKU（含 7 个“三合一折叠床”变体）。
- 每个 SKU：售价/划线价/最低价、市场比价指数（`price_indexes`）、重量、库存、佣金、图片、属性。
- 12 个月销售分析（`/v1/analytics/data`）+ 2025-08 起逐月财务流水（`/v3/finance/transaction/list`）。

### 4.2 1688 货源数据库（持续增长）

- 每品类记录：供应商总数、TOP120 价格中位/区间、主要产地、成交王（店铺+成交件数+价格）。
- 已覆盖 64+ 品类（截至本记录）；后台预采 ~150 常见品类进行中，中断可续跑。
- 覆盖示例：电动葫芦（1,240 家）、车载吸尘器（37,488 家，TOP120 成交 105 万台）、
  鼻毛修剪器（12,516 家，14 万件）、折叠躺椅床（16,097 家）、沙滩罩衫（80,181 家）、
  洗发水（按需抓取 3.6s，621,808 家）等。

### 4.3 市场侦察核心结论

1. **店铺已停售 9 个月**：18 单 / 50,777₽ 全部发生在 2025-08~10，此后零流水；
   财务净额 +38,601₽，其中 2025-10 单月 -9,943₽。
2. **定价体系是坏的**：唇膏 13.6₽、手机支架 15.2₽、电锯 320₽ 等低于 1688 采购价+物流，
   每单必亏；多个 SKU 相对 Ozon 同类无价格优势（比价指数多在黄/红区间）。
3. **机会排序**（1688 成交信号 + 重量/物流约束）：
   车载吸尘器 > 鼻毛修剪器 > 手机吸盘支架 > 折叠床（物流重，仅适合海/铁）> 电动葫芦（需 EAC）。
4. **监管风险**：电动葫芦出口俄罗斯需 EAC（TR CU 010/2011）；Makita 属品牌商品，有商标风险；
   唇膏/化妆品类需化妆品合规。
5. 比价指数官方口径已核实：你的价<竞品时 指数=你的价÷竞品价；你的价>竞品时 指数=2−竞品价÷你的价；
   指数≤1 有竞争力，>1 价格偏高。`market_min_rub` 字段按“同类最低价参考”标注。

### 4.4 自制 Chrome 扩展：KJDS 跨境数据采集器

路径：`tools/browser_collector/`

- **采集**：1688 详情/店铺/货源列表、Ozon 搜索/商品页、胜利者 ERP 数据块（类目/SKU/月销/
  跟卖价等），只读，数据发本机。
- **页面增强**（KJDS 数据卡）：
  - Ozon 市场页（搜索/商品）：绿色卡 = 1688 同款采购价（¥/₽）+ 供应商数 + 产地 + 成交王 +
    参考毛利（页面价可读时）。
  - Ozon 卖家后台：黄色卡 = 官方月销/销额/市场最低/比价指数 + 1688 采购中位 + 参考毛利。
- **全品类策略**：中文类目直匹配（胜利者 ERP 的汉字类目）→ 已采数据秒出；未采品类**按需抓取**
  （首次约 3-4s 并缓存）；俄语标题字典兜底；后台批量预采加速。
- 本地服务 `tools/browser_collector/collector.py`：`/capture`、`/data/match`、`/data/supply`、
  `/data/catalog`、`/data/crawl`、`/health`，仅监听 127.0.0.1:8123。

## 5. 文件清单

| 路径 | 说明 |
|---|---|
| `output/market_recon/market_recon_report.md` | 市场侦察报告（逐 SKU 比价 + 毛利测算 + 供应侧信号） |
| `output/market_recon/per_sku_analysis.json` | 18 SKU 分析明细（含 landed cost） |
| `output/market_recon/full_catalog.json` | Ozon 全量目录 |
| `output/market_recon/full_product_info.json` | Ozon 商品详情（价格/指数/重量/库存） |
| `output/market_recon/finance_by_month.json` | 财务流水（按月） |
| `output/market_recon/analytics_by_window.json` | 销售分析（两窗口） |
| `output/market_recon/attributes_full.json` | 商品属性 |
| `output/market_recon/supply_1688/supply_crawl.json` | 1688 货源数据库（64+ 品类，持续增长） |
| `output/market_recon/supply_1688/cn_categories.json` | 全品类预采清单（~150 词） |
| `output/browser_capture/` | 扩展采集的页面数据 |
| `tools/browser_collector/` | 扩展（manifest/extract/inject/popup/background）+ 数据服务 |
| `scripts/probe_ozon_*.py`、`pull_ozon_*.py` | Ozon 官方 API 采集脚本（read-only） |
| `scripts/crawl_1688_supply.py` | 1688 货源批量采集（增量续跑） |
| `scripts/build_market_recon_report.py` | 报告生成 |
| `scripts/parse_browser_capture.py` | 扩展采集数据解析 |
| `.tmp/supply_crawl_bg.log` | 后台预采进度日志 |

## 6. 运行中状态

- 本地数据服务：`127.0.0.1:8123` 运行中（电脑重启后需重新拉起）。
- 1688 后台预采：进行中（每品类落盘，中断可续跑）。
- 扩展：已安装待重载（inject.js 已升级，需在 `chrome://extensions` 点重新加载并刷新 Ozon 页面）。

## 7. 下一步

1. 重载扩展、刷新 Ozon 页面，验证 KJDS 数据卡在各品类页面的显示与准确性。
2. 选定 3-5 个 SKU，用 1688 详情页核验真实采购价/起订量/包装重量，产出 landing cost 与发布门禁。
3. 修复定价：把低于成本的 SKU 提到市场区间（参考市场最低价与比价指数）。
4. 电动葫芦 EAC（TR CU 010/2011）核验；Makita 类品牌商品下架或替换。
5. 预采完成后把 1688 货源库接入平台目录（catalog_items 目前仅 1 条，与真实 18 SKU 严重不符，需导入）。

## 8. 复现命令

```bash
uv run python scripts/pull_ozon_full_store.py              # Ozon 全量
uv run python scripts/pull_ozon_finance_analytics_attrs.py # 财务/分析/属性
uv run python scripts/crawl_1688_supply.py                 # 1688 预采（增量）
uv run python scripts/build_market_recon_report.py         # 报告
uv run python scripts/parse_browser_capture.py             # 解析扩展采集
uv run python tools/browser_collector/collector.py 8123    # 本地数据服务
```

## 9. 风险与注意

- Ozon API 限速 2 req/s；1688 抓取保持礼貌频率（约 1-1.5s/请求间隔），避免触发风控。
- 价格指数中 `minimal_price` 字段的精确口径与指数公式不完全一致，报告已按“参考字段”标注。
- 扩展只读、不发外网；本地服务仅监听 127.0.0.1。

## 10. 2026-08-02 利润增长 OS 并行开发续记

- 用户要求把数据大屏、全维利润、不同段位卖家运营、店铺属性/官方类目路由、VK、
  Telegram 和 Agent 判断合并交付，并明确要求 ZiAgent 多线程同步开发。
- 四个 ZiAgent 分别交付利润数据修复、证据化店铺画像、增长渠道端口和受治理 Agent
  Runtime，主线程完成 Runtime/API/Profit Command Web 组合与端到端验收。
- 新增利润修复页，可从 374 条全量源记录下钻到错误码、Evidence 要求、SKU、责任人、
  期限和预计解锁影响；数据质量不足不删除，只限制高风险使用。
- 店铺画像首轮只使用 18 个真实 Product Info 派生的 36 条 listing/category 观察；订单、
  流量、利润和精确变体证据缺口如实保留，不自动创建或发布店铺画像。
- VK/Telegram 统一以 `incremental_cash_cm3` 为目标，保留完整归因、奖励确认、退款和
  反作弊规则；当前只交付受治理端口和能力声明，不宣称生产账号已接通。
- Agent Runtime 已具备能力/准确率/延迟/成本/利润价值路由、预算、回退、脱敏和追踪；
  未配置模型时返回 `no_data`，且永远不能晋升事实、自批、签发 Permit 或直接写平台。
- 运行态发现同店铺 Scope Grant 轮换会让历史 Bundle 被普通身份拒绝，现已改为“当前
  授权负责访问、历史授权负责数据血缘”，不放宽租户/主体/店铺隔离。
- 详细决定与证据见 `ADR-0086` 和 `BAS-163-166` 交付证据。

## 11. 2026-08-02 利润真相 Gate 续记

- 本记录 4.3 中“定价体系是坏的”“每单必亏”以及基于该结果的机会排序，曾把 CNY
  商品价格与 RUB 市场价格直接比较，现正式标记为 `invalidated`。这些结论不得进入
  Dashboard、Agent、调价、采购、广告或上架决策；原始文件继续保留作为错误复盘证据。
- 新增 exact-scope FX Evidence intake；完整记录必须包含方向、Decimal 汇率、有效/失效
  时间、来源、权威、用途、Evidence、内容哈希和幂等键。历史 2 条 unscoped FX 仅作
  blocked candidate，`decision_eligible=false`。
- 新增变体身份、Ozon finance allocation、十五项成本 Evidence 与利润真相 readiness
  四条只读深模块。实时投影保留 374/374 源记录、18 SKU、99 个身份来源和 114 个财务
  operation；93 个身份来源 accepted、6 个 unresolved、21 个 exact group。
- 当前完整 scoped FX=0、正式 Fact=0、scoped FinanceEntry=0、决策快照=0；360 个成本/
  数量/FX/账本补证请求等待处理。scenario/accrual/settlement/cash 全部为 `no_data`。
- Ozon 商品与财务真实只读已通过；真实订单、平台结算、银行到账与任何 provider 外写
  尚未通过。`channel-accounts workspace=ready` 不能解释为整体经营闭环 ready。
- downside CM3、退款率、CAC/ACOS、履约时效和现金占用阈值全部保持 `UNKNOWN`，等待
  经营与财务负责人以 Evidence 签署口径、作用域和有效期；Agent 不得猜数。
- 利润真相页已在桌面和 390px 验收，可显示全量链路、FX Gate、身份守恒、finance
  quarantine、四账分离、阻断责任人与补证队列；现金利润仍诚实显示 `no_data`。
- 详细决定与证据见 `ADR-0087` 和 `BAS-167-170` 交付证据。
