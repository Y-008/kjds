# BAS-099 经营流转分析快照与可视化驾驶舱交付证据

## 结论

KJDS `0.53.0` 已完成 BAS-099 工程闭环：服务端提供经身份认证的只读经营分析快照，Web 使用同一合同展示真实 Ozon 商品驾驶舱、10 步经营流、对象管线、证据覆盖率、数据缺口、执行边界和下一步导航。交付不新建第二经营真源，不改变 Gate，不授予 Ozon、供应商、采购、广告或付款写权限。

本证据对应分支 `feature/operating-analytics-053`，验收日期为 `2026-07-26`。发布产物保留在 ignored `output/release-0.53.0/`；Git 仅提交代码、合同、测试、ADR 和项目文档。

## 真实运行快照

对 healthy Docker API 的认证请求 `GET /v1/operating-analytics/snapshot` 返回：

| 字段 | 实测值 |
|---|---:|
| `contract_id` | `kjds-operating-flow-analytics-v1` |
| `snapshot_sha256` | `253084bb43af604e20b722e17859db064a872504b1fcd5b6d440786fc6e5bf74` |
| `status` | `needs_input` |
| `stages` | 10 |
| `pipeline` | 8 |
| `coverage` | 8 |
| `data_gaps` | 8 |
| 焦点 Ozon `offer_id` | `2105343364UB` |
| 可售库存 | 9 |

快照明确区分 `verified`、`blocked` 与 `no_data`。没有真实历史序列、需求报告、独立三候选、正 CM3、订单或结算时，服务端和前端均保持缺口状态，不生成演示 GMV、销量、转化或利润曲线。

## 实现与合同

- `OperatingAnalyticsService` 只读组合 readiness、目录、现有 Listing 绑定、RFQ、发送证明、样品、受控执行和正式财务对象。
- `/v1/operating-analytics/snapshot` 通过既有身份层读取；匿名请求实测返回 `401 AUTHENTICATION_REQUIRED`。
- OpenAPI v1、Web TypeScript 合同、Dashboard controller 和 HTML 组件使用同一字段边界。
- Web 展示 10 步流转、真实商品引用、价格/库存/媒体事实、对象管线、证据覆盖和数据缺口；所有下钻回到已有工作区。
- [ADR-0025](../../adr/ADR-0025-operating-flow-analytics-projection.md) 记录只读投影、稳定哈希、无第二真源和失败关闭边界。

## 可视化与企业交付物

### 前端截图

- `output/release-0.53.0/operating-command-center-desktop.png`
- `output/release-0.53.0/operating-command-center-desktop-viewport.png`
- `output/release-0.53.0/operating-command-center-mobile.png`
- `output/release-0.53.0/operating-flow-analytics-desktop.png`
- `output/release-0.53.0/operating-analytics-charts-desktop.png`
- `output/release-0.53.0/KJDS-0.53.0-operating-analytics-dashboard.png`

### 文档、演示与工作簿

- `KJDS-0.53.0-system-design.docx` 与对应 PDF：7 页，架构图、合同、幂等、安全、可运维性和决策。
- `KJDS-0.53.0-design-report.docx` 与对应 PDF：6 页，封面、自动目录、执行摘要、发现、建议和来源。
- `KJDS-0.53.0-project-kickoff.pptx`：7 页。
- `KJDS-0.53.0-team-alignment.pptx`：7 页。
- `KJDS-0.53.0-operating-analytics.xlsx`：Dashboard、Data & Targets、`_Chart Helpers`。
- `KJDS-0.53.0-project-tracker.xlsx`：项目计划、状态与 Gantt。

两份 DOCX 均从已审计模板生成，模板哈希保持不变；结构检查确认 section geometry、styles、numbering、关系和媒体部件完整。最终 PDF 已逐页渲染验收。两份 PPTX 的模板保真检查均为 `0 issue`，14 张最终幻灯片均已渲染检查。两份 XLSX 的所有工作表均已渲染检查，公式错误扫描匹配 `0` 条。

## 自动化质量门禁

| 门禁 | 结果 |
|---|---|
| `uv run python scripts/verify_secrets.py` | PASS；514 个非忽略工作区文件、512 个历史路径 |
| `uv run ruff check .` | PASS |
| `uv run python -m pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local` | PASS；486 tests |
| `npm ci` | PASS；0 vulnerabilities |
| `npm test` | PASS；36/36 |
| `npm run build` | PASS；Next.js 生产构建与 13 个路由生成 |
| Alembic heads/current | PASS；唯一且当前为 `20260726_0050 (head)` |
| `alembic upgrade head` | PASS |
| PostgreSQL `pg_isready` | PASS；accepting connections |
| `GET /health/ready` | PASS；HTTP 200，version `0.53.0`，database `ok` |
| Web `/auth/session` | PASS；HTTP 200 |
| `git diff --check` | PASS |

主机最初由 Windows 应用控制策略拦截项目受管 CPython 的 `_ctypes` DLL。随后使用允许执行的系统 CPython `3.12.10` 作为项目 `uv` 解释器、同步锁定的 `dev` 依赖后，全量 486 个测试通过；这不是跳过测试。唯一测试警告为 Starlette 对当前 `httpx` TestClient 适配的弃用提示，不影响本次行为验收。

## 工具与产物 QA

- curated skill 清单通过 `skill-installer` 官方脚本取得；未为本次任务安装无直接用途的 skill。
- OpenCLI 以 `npx @jackwener/opencli` `1.8.6` 执行 `list -f json` 和 `doctor -v`：daemon `OK`，Chrome Browser Bridge 扩展未连接，因此 browser connectivity 为 `FAIL`。本次真实业务事实不依赖 OpenCLI browser bridge，此结果保留为环境信息。
- Project Kickoff 的通用 `slides_test.py` 在第 3、6 页对继承标题占位符产生假阳性；最终 layout JSON 对两页分别检查 9/13 个 slide elements，越界数均为 0，模板保真为 0 issue，实际渲染无裁切。Team Alignment 的同一溢出测试直接通过。

## 边界与未宣称事项

- Ozon 仅使用已存在、逐字节复验的只读商品证据；`Ozon write = OFF`。
- LinkFox 只作为 C-tier 公开营销能力参考，不声明已验证 Ozon 集成、API、数据许可或效果。
- `C:\Users\Lunar\Desktop\1` 仅只读审阅，没有修改，也不作为经营真源。
- 外部商品图片和视频仍为未核权引用；本发布不取得媒体权利。
- Figma 未连接，本发布不声称已写入 Figma。
- 正式需求、供应商三报价、样品、Passport、媒体权利、CM3、平台授权、双人审批、执行回读和财务对账仍按 10 步流转补证，不能由当前快照自动晋升。

## Review findings

| 等级 | 发现 | 处理 |
|---|---|---|
| P0 | 无 | no-op |
| P1 | 无 | no-op |
| P2 | 无 | no-op |
| Info | Starlette/httpx 弃用警告 | defer；依赖升级时复核 |
| Info | OpenCLI Browser Bridge 扩展未连接 | defer；仅在 COOKIE/INTERCEPT/UI/browser 工作需要时连接 |
| Info | Kickoff 第 3/6 页模板占位符触发溢出脚本假阳性 | no-op；layout 与实际逐页渲染均证明画布内 |

## 验收

BAS-099 的代码、合同、前后端、真实运行数据、自动化测试、数据库迁移、HTML 仪表盘、截图和企业级交付物均已闭环，状态更新为 `DONE`。后续平台写入仍需独立业务授权与 Gate 验收，不属于本次只读发布。
