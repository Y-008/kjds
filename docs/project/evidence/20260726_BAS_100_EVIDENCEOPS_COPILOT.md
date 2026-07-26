# BAS-100 EvidenceOps Copilot 独立产品入口交付证据

## 结论

KJDS `0.54.0` 已完成 BAS-100 工程闭环：新增独立认证产品入口
`/evidenceops`，把一个经营目标通过服务端深模块编译成带哈希的证据任务合同。合同明确
区分用户意图、已验证事实、unknown、任务、责任 Agent、验证条件和控制边界；前端不重算
任务优先级、不生成演示经营数据，也不取得 Ozon、供应商、采购、改价、Listing、广告或付款
写权限。

本证据对应分支 `feature/evidenceops-copilot-054`，验收日期为 `2026-07-26`。截图保留在
ignored `output/release-0.54.0/`；Git 仅提交代码、合同、测试、ADR 和项目文档。

## 产品与模块决策

`EvidenceOpsCopilot.plan(objective, store_ref)` 是本次唯一新增业务接口。模块内部只组合：

- `OperatingAnalyticsService.snapshot(store_ref)`：阶段、覆盖、真实商品、正式财务和执行对象；
- `OperatingWorkbenchService.snapshot(limit=100)`：当前工作项、责任 Agent 和下一动作。

模块不直接读取 Repository，不复制 Gate，不保存聊天或计划，不调用外部模型，不新建第二
事实库或第二权限面。相同来源快照与目标产生稳定 `plan_sha256`；未来模型只能作为模块内部
可替换的挑战者，不能改变合同、事实成熟度或执行权限。

详细接口与 `best_solution` 选择见
[`ADR-0026`](../../adr/ADR-0026-evidenceops-copilot-product-seam.md)。

## 合同真实性边界

| 对象 | 合同语义 | 不允许的晋升 |
|---|---|---|
| `objective` | `user_intent`，仅影响任务排序 | 经营事实、审批、执行许可 |
| `verified_facts` | 来自当前服务端经营快照 | 客户端或目标文本补数 |
| `unknowns` | 缺口与补证动作，`synthetic_fill_allowed=false` | 演示数、插值、模型猜测 |
| `missions` | 来源、当前/目标、Agent、验证条件和工作区 | 客户端自行改变 Gate |
| `control_envelope` | `plan_only=true`、`external_write_allowed=false` | 自动采购、改价、发布、投放或平台写入 |

## 真实认证运行证据

在健康的 Docker Postgres/API/Web 上，以现有 operator 身份调用
`POST /v1/evidenceops/plan`，目标为“提升当前 Ozon 商品利润，先找出最关键的证据缺口和
下一步”，结果如下：

| 字段 | 实际值 |
|---|---|
| HTTP | `200` |
| contract | `kjds-evidenceops-copilot-plan-v1` |
| product version | `0.54.0` |
| inferred intent | `profit_cash` |
| verified facts | `5` |
| explicit unknowns | `12` |
| ordered missions | `6` |
| plan SHA-256 | `a64c0cabddbecbf503755de532ca65d6a7dfd5edc1c00981c922032f7242e92f` |
| external write | `false` |

匿名调用同一接口返回 `401`。`/health/ready` 返回 `200`、版本 `0.54.0`、数据库
`status=ok`；`/evidenceops` 与 `/auth/session` 均返回 `200`。

## 前端与视觉证据

Playwright 在真实 Web/API 容器上完成页面加载、目标示例切换和全页截图。切换到俄语
Listing/素材目标后，服务端意图、任务顺序和计划哈希发生变化，事实账本保持来源驱动。

| 产物 | 尺寸 | 视觉复验 |
|---|---:|---|
| `output/release-0.54.0/evidenceops-copilot-desktop.png` | 1440×2972 | PASS；完整目标、事实、unknown、任务、Agent 与控制包 |
| `output/release-0.54.0/evidenceops-copilot-mobile.png` | 390×4882 | PASS；无横向溢出，标题不拆字，任务与控制边界完整 |

## LinkFox 与竞品边界

LinkFox 继续按 C 级公开营销参考管理。KJDS 借鉴其“目标到工具计划”的低门槛入口，但已实现
更严格的 `evidenceops_objective_to_evidence_plan_v1`：目标先回到真实经营快照，再生成
explicit unknown、可复验任务、责任 Agent、控制包和稳定哈希。公开资料不证明 LinkFox 已
接入 Ozon；本次也未接入其 API、模型、素材库或账号。

## 质量门禁

| 门禁 | 结果 |
|---|---|
| `scripts/verify_secrets.py` | PASS；522 个非忽略工作区文件、516 个历史路径 |
| `ruff check .` | PASS |
| 全量 Pytest | PASS；496 tests，1 个既有 Starlette/httpx 弃用警告 |
| `npm ci` | PASS；0 vulnerabilities |
| `npm test` | PASS；38/38 |
| `npm run build` | PASS；Next.js 生产构建与 14 个路由生成 |
| Docker Web webpack build | PASS |
| Alembic heads/current/upgrade | PASS；唯一且当前为 `20260726_0050 (head)` |
| Postgres | PASS；healthy、accepting connections |
| API/Web | PASS；两个服务均 healthy |
| `git diff --check` | PASS |

## 审查结论

- 目标变化只改变推断意图、任务相关性和排序，不改变已验证事实。
- 所有任务都要求人工参与，且 `automatic_execution=false`、
  `platform_write_allowed=false`。
- 未引入外部 LLM、聊天持久化、第二数据库、第二权限面或 Agent 市场。
- 桌面与移动端均使用真实容器快照；没有模拟 GMV、利润或经营趋势。
- 受保护的用户文件、`wuliu/`、PDF、`Desktop\1` 和 Figma 均未修改或纳入提交。

## 验收

BAS-100 的产品决策、深模块、API、独立 Web 入口、真实运行、前后端测试、数据库兼容、
视觉截图、竞品边界和项目治理均已闭环，状态更新为 `DONE`。后续任何内容生成或平台副作用
仍需独立提供方准入、业务授权和既有 Gate 验收。
