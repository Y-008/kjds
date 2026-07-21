# BAS-064 三候选组合决策视图实施证据

| 字段 | 值 |
|---|---|
| task | BAS-064 |
| requirement | BR-050 |
| gate | G0–G1 |
| status | DONE_ENGINEERING |
| reviewed_at | 2026-07-20 |

## 结果

KJDS 现有 `/v1/operations/readiness` 增加只读 `candidate_portfolio`。组合只包含同时具备候选交接事件、有效 `candidate_basis` 和一份当前已接受需求报告的 Product；普通历史目录和残缺候选不会进入。

每个组合行只读取每家供应商当前报价及该报价的当前利润场景，显示 Passport、供应商数、完整正 CM3 场景数、最佳供应商、CM3、保本价、Evidence 数和阻断原因。排序固定为可进入人工选择优先、CM3 其次、SKU 稳定排序。结果明确返回：

- `advisory_only=true`
- `automatic_product_selection=false`
- `automatic_procurement=false`
- `automatic_pricing=false`
- `automatic_listing=false`

## Ponytail 取舍

- 复用 `GateReadinessService`、现有 Product、报价、利润场景和 Web 工作台。
- 没有新增数据库表、迁移、队列、接口或依赖。
- 没有提前实现尚无真实使用瓶颈的批量改价/刊登执行系统。
- 修复同一根因：旧供应商报价上的历史正利润不得继续满足当前比较或 readiness。

## 变更位置

- `apps/control_plane/readiness.py`：合格候选组合、当前快照投影、稳定排序和自动化禁令。
- `apps/control_plane/sourcing.py`：供应商报价及利润场景按时间选择当前版本。
- `web/app/page.tsx`：三候选组合决策台，并只为合格候选加载 Passport、素材与三报价。
- `tests/test_readiness.py`：合格范围、排序、负 CM3 阻断与自动化禁令。
- `tests/test_sourcing.py`：新报价不得继承被替代报价的利润场景。
- `scripts/verify-g1.ps1`：真实 API/PostgreSQL 组合投影断言。

## 验收

| 检查 | 结果 |
|---|---|
| 定向 Python | 25 passed |
| 全量 Python | 286 passed；1 条既有 Starlette/httpx 弃用警告 |
| Ruff | PASS |
| Web 契约测试 | 12 passed |
| Next.js 生产构建与 TypeScript | PASS |
| OpenAPI v1 快照 | 已刷新，定向合同测试通过 |
| JSON 解析 / `git diff --check` | PASS；仅有既有 LF→CRLF 提示 |
| G-1 | PASS；`three_candidate_portfolio=true`，报告 `.runtime/G1_VERIFICATION.json` |

## 未完成的业务事实

工程组合目前不代表有三个真实可售商品。仍缺账户主体导出的真实 Ozon 需求报告、三项真实候选原件、每候选三家可核验报价、样品与包装/物流实测、官方合规结论和逐项真实成本账单。上述输入满足前，G0、采购、Listing 与平台写入继续冻结。
