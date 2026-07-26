# BAS-102 点线面真实业务工作区穿透交付证据

## 结论

KJDS `0.56.0` 已完成 BR-077/BAS-102 工程闭环。143 个原子点、14 条端到端
价值流和 8 个经营控制面均解析到独立认证深链；服务端
`OperatingWorkspaceService` 只读组合版本化能力图谱与真实经营分析快照，前端不
重算阶段关系、运行状态、Evidence 或 Gate。

本证据对应分支 `feature/operating-workspaces-056`，验收日期为 `2026-07-26`。
发布截图保留在 ignored `output/playwright/release-0.56.0/`；Git 只提交代码、合同、
测试、ADR 和项目文档。

## 需求与安全边界

- Requirement: BR-077
- Baseline: BAS-102
- ADR: [ADR-0028](../../adr/ADR-0028-operating-workspace-drillthrough.md)
- API: authenticated read-only
  `GET /v1/operating-workspaces/{kind}/{item_id}?store_ref=...`
- Web:
  `/operations/points/{id}`、`/operations/lines/{id}`、
  `/operations/surfaces/{id}`
- `kind`、未知 ID 和不安全 ID 均失败关闭。
- `implemented/ready/gated/research_only` 是能力合同状态；
  `verified/blocked/no_data/contract_only/in_progress` 是运行事实状态，两者从未互相
  晋升。
- 缺少真实订单、结算、供应商、CM3、媒体权利或平台权限时，事实、Evidence 缺口和
  服务端下一动作保持可见。
- 工作区只导航到已有领域工作区；不新增数据库或事实源，不授予 Ozon、供应商、采购、
  广告、付款或媒体执行写权限。
- `read_only=true`、`external_write_allowed=false`、
  `client_can_recalculate_runtime_status=false`、
  `contract_status_is_runtime_fact=false`。
- 后续任何 Ozon 写入仍须独立 Evidence、Approval、一次性 Permit、Readback、
  Kill Switch 和 Compensation；本发布没有绕过路径。

## 实现与合同

- `CrossBorderCapabilityAtlas` 返回服务端验证的 143/14/8 图谱和规范哈希。
- `OperatingWorkspaceService.snapshot(kind, item_id, store_ref)` 在一个深模块内完成
  节点解析、点/线/面关系、阶段顺序、真实经营信号、事实、Evidence、缺口、下一动作、
  Owner、异常、回读和已有工作区导航的组合。
- 每个点可回到所属线和关联面；每条线保留完整有序阶段；每个面下钻到关联线和核心点。
- OpenAPI、FastAPI 路由、TypeScript 合同和 Next.js 动态路由使用同一字段边界。
- capability atlas 首页版本由服务端 `release_version` 和 `registry_version` 驱动，
  不再硬编码 KJDS 0.55.0。
- Operating Workspace 顶栏也读取同一服务端 `release_version` 和
  `registry_version`，不保留客户端发布版本常量。
- 版本源、能力图谱、`/health/ready`、OpenAPI、Python 包和 Web 包统一为
  `0.56.0`。

最新镜像上的认证运行快照：

| 工作区 | 阶段 | 运行状态分布 | `workspace_sha256` |
|---|---:|---|---|
| `points/trend_event_calendar` | 1 | `contract_only=1` | `58bd30de21d4bedad3856ef2d69e5b824210823445f2d5c1df36cf57aee62d9b` |
| `lines/trend_to_opportunity` | 6 | `blocked=2, contract_only=4` | `8adfc65a78cc9f27e41bd49cc98d3a2b0e15b8908afc0047cfa51dd9ff872b7f` |
| `surfaces/agent_skill_surface` | 30 | `blocked=4, contract_only=25, no_data=1` | `90c4e5f02189ae8659fa5dbb3028128ca1ed21b405da8ea4cd9d73cd09358c31` |

## 自动化质量门

| 门禁 | 实测结果 |
|---|---|
| `uv run python scripts/verify_secrets.py` | PASS；555 个非忽略工作区文件、548 个历史路径 |
| `uv run ruff check .` | PASS |
| `uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local` | PASS；511 passed |
| Operating Workspace/Atlas/API 定向测试 | PASS；37 passed |
| `uv run python scripts/build_cross_border_operating_graph.py --check` | PASS；注册表 current |
| `npm ci` | PASS；0 vulnerabilities |
| `npm test` | PASS；43 passed |
| `npm run build` / `npm run build -- --webpack` | PASS；Next.js 生产构建与动态点线面路由生成 |
| `git diff --check` | PASS |
| Alembic heads/current | PASS；唯一且当前为 `20260726_0050 (head)` |
| `uv run alembic upgrade head` | PASS |
| Docker PostgreSQL/API/Web | PASS；三者 healthy |
| `GET /health/ready` | PASS；HTTP 200、version `0.56.0`、database `ok` |
| 运行 OpenAPI | PASS；version `0.56.0` 且包含 Operating Workspace 路径 |
| 匿名 Operating Workspace 请求 | PASS；HTTP 401、`AUTHENTICATION_REQUIRED` |

Python 全量测试只有既有 Starlette/httpx 适配弃用警告；未跳过测试。

## Playwright 点→线→阶段→面验收

认证浏览器从 `/capability-atlas` 读取到服务端版本 `0.56.0`、注册表版本
`0.56.0` 和计数 `143/14/8/0`，随后完成：

1. 从 `trend_event_calendar` 点进入独立
   `/operations/points/trend_event_calendar`。
2. 点工作区显示 `contract_only`、无精确事实、Evidence 缺口和只读下一动作。
3. 进入 `/operations/lines/trend_to_opportunity`，在六阶段中选择
   `market_signal_inbox`；该阶段显示服务端 `blocked`，没有把能力
   `implemented` 冒充真实运行完成。
4. 继续进入 `/operations/surfaces/agent_skill_surface`；经营面展示 30 个阶段、
   4 条关联线、9 个真实域信号和 9 条现有领域工作区动作。
5. 390 px 移动端实测 `scrollWidth=390`、`innerWidth=390`，无横向溢出。
6. 最新 webpack standalone 页面实测 console 0 errors；保留 1 条 Next.js CSS preload
   未使用 warning，不影响合同、渲染或交互。

忽略目录中的正式截图均已逐张检查：

| 文件 | 尺寸 | SHA-256 |
|---|---:|---|
| `point-trend-event-desktop.png` | 1440×2078 | `DC2ACA99ED65765AE2E5982B37CE1AD3588D2775D74D0625907E82C6C3035435` |
| `line-trend-to-opportunity-stage-blocked-desktop.png` | 1440×2050 | `011CB9B42926052524CEFA62FE76B176D08B305209A7FAEEE7657F80DAA25E5C` |
| `surface-agent-skill-desktop.png` | 1440×2561 | `E77096481B8F5B95FD7C571001507990B48C7ACB734D395C1BF1CB07CF7E9185` |
| `surface-agent-skill-mobile.png` | 390×6391 | `50F532C632620331180652D42405D3C82B2550D12B723384E56AAD01AAACEAA8` |

## Review findings

| 等级 | 发现 | 处理 |
|---|---|---|
| P0 | 无 | no-op |
| P1 | 无 | no-op |
| P2 | 无 | no-op |
| Info | Starlette/httpx TestClient 弃用警告 | defer；依赖升级时复核 |
| Info | Next.js 页面出现 1 条 CSS preload 未使用 warning | defer；框架资源提示，不影响渲染、合同或交互 |
| Info | Playwright CLI headed 首次启动超时，随后无头认证会话成功完成回归 | no-op；不影响页面、截图或合同证据 |

## 未宣称事项

- 当前快照不证明真实订单、结算、银行到账、供应商报价、实际 CM3 或平台写权限已齐备。
- 外部商品图片和视频继续保持未核权引用；本发布不取得媒体权利。
- LinkFox 只作为 C 级公开产品工作流基线，不证明其 API、Ozon 接入、模型效果或许可。
- Figma 未连接，本发布不声称写入 Figma。
- 0.56.0 工作区是只读穿透层，不是第二工作流引擎、第二队列或平台自动执行入口。
