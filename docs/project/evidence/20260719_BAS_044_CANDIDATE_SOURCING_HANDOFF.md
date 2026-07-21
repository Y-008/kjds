# BAS-044 候选到三报价人工交接验收

| 项目 | 结果 |
|---|---|
| 日期 | 2026-07-19 |
| Gate | G0 工程准备；G0 业务尚未放行 |
| 状态 | DONE_ENGINEERING |
| API | `POST /v1/market/candidates/sourcing-handoff` |
| 数据迁移 | 无；复用 Product、Evidence lineage 与 Repository event |
| 新依赖 | 无 |

## 1. 问题与边界

BAS-043 能把候选研究结论推进到 `request_three_quotes`，但既有三报价入口必须接收 `product_id`，两者之间原来只能人工绕过候选门直接创建 Product。BAS-044 把这个断点收敛成唯一的受控交接。

只有同时满足下列条件才建立报价工作区：

- 操作者明确确认本次交接；
- 候选五类 Evidence 在交接时再次通过完整性、来源与时效复验；
- 当前结论仍为 `request_three_quotes`；
- 市场为当前 Ozon RU 垂直切片；
- SKU 未被其他商品占用。

成功后只创建 `candidate` 状态的 Product，并将候选原件以 `candidate_basis` 链接到该 Product。下一门是既有 `sourcing_comparison_intake`。不创建供应商报价、Passport、采购申请、Listing 或平台写入，也不代表候选已批准售卖。

## 2. 幂等与失败关闭

Product ID 由候选引用、市场、类目和 SKU 的规范摘要确定。相同交接重复执行时复用原工作区，不重复创建 Product 或审计事件；同一 SKU 已指向不同商品、名称或渠道时拒绝覆盖。Evidence 血缘链接本身幂等，若连接步骤中断，可由同一请求安全补齐。

## 3. 实现证据

- `apps/control_plane/intelligence.py`：交接前重新预检、RU/OZON 限界、稳定 Product ID、SKU 冲突拒绝和最小审计事件。
- `apps/control_plane/api.py`：显式 `confirmed=true` 输入合同、operator/admin 角色门、全部候选 Evidence 到 Product 的血缘链接。
- `web/app/page.tsx`：预检通过后才出现内部 SKU、人工确认和“建立报价工作区”操作；完成后导航至三报价入口。
- `web/app/globals.css`：紧凑的非技术确认区与下一步提示。
- `docs/project/contracts/openapi-v1.json`：已重新导出 API 契约快照。
- `tests/test_core.py`：未确认拒绝、候选 Product 状态、确定性重试和单一事件。
- `tests/test_security.py`：新写端点最低角色合同。
- `web/lib/candidate-research-contract.test.ts`：交接接口、确认文案和非自动批准边界。

## 4. 验证结果

| 检查 | 结果 |
|---|---|
| Python 全量测试 | 215 passed；1 条既有 Starlette/httpx 弃用警告 |
| Web 合同测试 | 7 passed |
| Ruff | PASS |
| Next.js production build | PASS |
| OpenAPI 快照 | PASS |
| Alembic PostgreSQL head | `20260718_0036` |
| Compose 配置 | PASS |
| Secret scan | 291 个非忽略工作区文件，PASS |
| G-1 | PASS；迁移回放、备份恢复、生产容器、API/Web 健康与代理鉴权均通过 |
| 视觉检查 | PASS；`output/playwright/bas044-candidate-handoff.png` |

第一次 G-1 调用误用 Windows PowerShell 5，在任何业务检查前被脚本的 PowerShell 7 前置条件拒绝；随后使用 `pwsh` 原样执行并得到 PASS。该失败不涉及代码或数据迁移。

## 5. 仍需真实业务输入

工程交接已打通，但真实上新仍保持阻塞：尚未录入三个真实候选、候选原件、每个候选三家可核验报价、包装与物流实测、合规批准和真实 CM3。任何采购、上架和 Ozon 写入继续冻结。
