# BAS-045 三报价前置门完整性验收

| 项目 | 结果 |
|---|---|
| 日期 | 2026-07-19 |
| Gate | G0 工程准备；G0 业务尚未放行 |
| 状态 | DONE_ENGINEERING |
| 受控入口 | `POST /v1/sourcing/comparison-intake` |
| 数据迁移 | 无；复用 Repository event 与 Evidence lineage |
| 新依赖 | 无 |

## 1. 修复的问题

BAS-044 建立了候选研究到报价工作区的受控交接，但旧三报价入口仍可接收普通 Product ID。界面遵守流程并不能阻止 API 绕过，因此“唯一交接”此前尚未成为服务端事实。

BAS-045 要求三报价入口在读取和固化上传文件之前同时验证：

- Product 存在内部生成的 `product.candidate_sourcing_workspace_created` 事件；
- Product 至少存在一份 `candidate_basis` Evidence；
- 全部候选基础 Evidence 当前仍通过 Blob 哈希完整性复验。

缺事件、缺血缘、证据损坏或 Product 不存在均失败关闭，并且不留下利润假设、供应商报价或利润场景的部分写入。

## 2. 最小实现

- `apps/control_plane/sourcing_intake.py`：复用既有 Repository event 与 `EvidenceService.target_evidence_ids/require_valid`，无新表、无令牌、无依赖。
- `tests/test_sourcing_intake.py`：覆盖正常三报价、幂等重试、重复供应商拒绝及缺候选交接时零新增 Evidence/报价。
- `scripts/verify-g1.ps1`：先固化五份、至少两个来源族的候选原件，再通过候选原子预检和人工交接取得 Product，最后进入三报价。
- `docs/project/contracts/openapi-v1.json`：API 版本升级到 `0.33.0`；请求形状不变。

## 3. 验证结果

| 检查 | 结果 |
|---|---|
| Python 全量测试 | 216 passed；1 条既有 Starlette/httpx 弃用警告 |
| Web 合同测试 | 7 passed |
| Ruff | PASS |
| Next.js production build | PASS |
| OpenAPI 快照 | PASS |
| Alembic PostgreSQL head | `20260718_0036` |
| Compose 配置 | PASS |
| Secret scan | 293 个非忽略工作区文件，PASS |
| G-1 | PASS；真实候选原件→预检→交接→三报价链通过 |

## 4. 未解除的业务阻塞

该门只证明无法用普通 Product 绕过研究流程，不证明任何商品值得售卖。三个真实候选、每个候选的原始市场证据、三家可核验供应商报价、样品/包装/物流实测、合规批准和真实 CM3 仍缺失；采购、上架和 Ozon 写入继续冻结。
