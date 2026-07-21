# BAS-043 候选研究原件录入与原子预检验收

| 项目 | 结果 |
|---|---|
| 日期 | 2026-07-19 |
| Gate | G0 工程准备；G0 业务尚未放行 |
| 状态 | DONE_ENGINEERING |
| API | `POST /v1/market/candidates/intake` |
| 数据迁移 | 无；复用 Evidence、MarketObservation 与 Outbox |
| 新依赖 | 无 |

## 1. 交付边界

非技术用户先把市场、供应、合规等原件上传到既有 Evidence Ledger，再为一个候选填写五类固定观测：需求信号、竞争缺口、可采购性、合规红线和退货风险。服务端从 Evidence 派生来源、引用和观测时间，客户端不能自报这些事实。

系统先复验全部原件，再在一个 Repository 事务中写入观测和最小审计事件。任一指标缺失、重复、未知，或任一 Evidence 不存在、损坏、过期或与候选不匹配时，整个提交失败且不留下部分观测。观测 ID 由候选、市场、类目、指标、Evidence、值与可信度的规范摘要确定，重试同一提交不会重复建账。

预检结果只允许：

- `reject`：触发供货或合规红线；
- `collect_evidence`：证据覆盖、时效、来源族或可信度不足；
- `request_three_quotes`：仅允许进入三家真实报价收集。

本能力不会创建 Product、采购单、Passport、Listing，不会生成商品结论，也不会调用 Ozon 写接口。

## 2. 实现证据

- `apps/control_plane/intelligence.py`：固定指标集合、Evidence 全量前置复验、单事务写入、稳定观测 ID 与既有候选预检复用。
- `apps/control_plane/api.py`：版本化输入合同与候选研究录入端点，沿用角色校验。
- `web/app/page.tsx`：原件上传、候选基础信息、五项固定指标、Evidence 选择、可信度和下一动作展示。
- `web/app/globals.css`：非技术表单、结果卡与响应式布局。
- `docs/project/contracts/openapi-v1.json`：已重新导出机器可比 OpenAPI 快照。
- `tests/test_core.py`：成功、原子失败和幂等重试。
- `tests/test_security.py`：端点最低角色合同。
- `web/lib/candidate-research-contract.test.ts`：前端 Evidence-first、五指标与禁止自动创建/上架边界。

## 3. 验证结果

| 检查 | 结果 |
|---|---|
| Python 全量测试 | 214 passed；1 条既有 Starlette/httpx 弃用警告 |
| Web 合同测试 | 7 passed |
| Ruff | PASS |
| Next.js production build | PASS |
| OpenAPI 快照 | PASS |
| Alembic PostgreSQL head | `20260718_0036` |
| Compose 配置 | PASS |
| Secret scan | 294 个非忽略工作区文件，PASS |
| `git diff --check` | PASS；仅 Windows LF/CRLF 提示 |
| G-1 | PASS；迁移回放、备份恢复、容器、API、Web 健康与代理鉴权均通过 |
| 视觉检查 | PASS；`output/playwright/bas043-candidate-section.png` |

首次 G-1 运行因视觉验收遗留的同项目 Next.js 开发进程占用 `.next/dev` 锁而在 Web UI 等待阶段失败。确认日志后关闭该预览进程并原样复跑，最终 G-1 PASS；未为此修改业务实现。

## 4. 未完成与人工输入

以下仍是业务事实阻塞，不得因 BAS-043 完成而宣告上新可执行：

- 尚未确定 RU-001、RU-002、RU-003 三个真实候选及稳定商品身份；
- 尚未上传候选的一手市场、供应和合规原件；
- 尚未取得每个候选三家可核验供应商报价、样品、包装尺寸/重量和物流实测；
- 尚未完成 EAEU/EAC、标识、知识产权和运输限制的人工合规审批；
- 尚未形成订单—费用—结算—银行口径的真实 CM3；
- 尚未建立 Ozon 专用最小权限只读身份，任何平台写入仍冻结。

下一业务动作是用本入口录入真实候选研究证据；只有结果为 `request_three_quotes` 才进入三报价，不得跨 Gate 自动上架。
