# BAS-107 · Commerce OS / Agent Team 首个可验收切片

| 项 | 结果 |
|---|---|
| 日期 | 2026-07-28（Asia/Shanghai） |
| 分支 | `feature/batch-opportunity-mining-059` |
| 基线 HEAD | `b34a3a7`（当前集成工作树尚未提交） |
| 版本 | API/Web `0.59.0` |
| 合同 | `commerce-operating-system/1.0.0` / `kjds-commerce-mcp/1.0.0` |
| 范围 | BR-085 / ADR-0035 / ADR-0036 |
| 外部写 | 全部关闭 |

## 结论

KJDS 已交付首个原生 Commerce OS 投影，不再把无忧易售、妙手、芒果店长、
Maozi、荔枝和 LinkFox 当运行依赖或“已接入”目标。认证服务端从既有
Truth/Governance、Batch Opportunity、Profit ERP Sync、Operating Analytics/
Workbench 与 Media Workbench 动态组合：

- 13 段真实经营状态机；
- 10 个 KJDS 原生 ERP/经营模块；
- 6 个仅比较用的能力基准；
- 12 个受治理的责任 Agent；
- AI 图片/视频内容工厂状态与 Manifest/QA 边界；
- 当前 outcome、source gaps、Owner、SLA、下一工作区和稳定快照哈希。

客户端不重算 readiness。全局媒体 Manifest、通用执行计划或观察窗口不能冒充某个
候选已完成内容、独立审批或履约。

## 真实运行快照

认证 `GET /v1/commerce-os/workspace?store_ref=ozon-primary` 返回：

| 指标 | 实际值 |
|---|---:|
| observed listings | 43 |
| unique exact identities | 3 |
| fully costed candidates | 0 |
| downside positive | 0 |
| ERP Item readback succeeded | 0 |
| published | 0 |
| ordered | 0 |
| settled/proven | 0 |
| benchmark rows | 6 |
| Agent rows | 12 |

状态为 `operating_with_constraints`，当前控制点为“十五项利润资格”。
`external_writes=false`，因此不能把此切片表述为完整 ERP 经营闭环、真实盈利、
已上架或已接单。

## 开源复用

`best_solution/2026-07-28` 已冻结在 ADR-0036：

- ERPNext v16 作为隔离 ERP 单据侧车，不取得 KJDS 商品/利润/Evidence/审批真相；
- ComfyUI 与 FFmpeg 作为固定版本媒体 Worker；
- OpenTelemetry 采用稳定 trace/metrics 信号，logs 不作为当前硬依赖；
- MCP Python SDK 实际锁定 `mcp==1.28.1`，依赖约束 `<2`；
- Medusa/Saleor 当前不进入经营内核，避免第二套商品、库存、价格和订单真相；
- AutoGen 已进入 maintenance mode，不作为新实现基础。

实际 `kjds-commerce-mcp` 只注册 `get_commerce_os_workspace` 和对应只读 Resource。
工具从现有 API 多身份映射绑定 Principal，跨店失败；没有 publish、purchase、
payment、approval 或 Permit Tool。

## 本地竞品样本边界

`D:\KJDS\ozon` 仅做只读代码级研究。样本是已打包 Electron/.NET 应用、插件和
安装包，没有发现可覆盖整个业务源码的明确许可证；浏览器插件还包含 `cookies`、
宽域 host、全页面 content script 和静态凭证形态。因此只吸收业务步骤、字段、异常
分支和交互模式，不复制私有打包代码、凭证、内部接口、宽域权限或静态费用真源。

## 自动化验证

```text
uv run python scripts/verify_secrets.py
Secret scan passed: 635 non-ignored worktree files and 581 historical paths checked

uv run ruff check .
All checks passed

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local
619 passed, 1 warning

cd web && npm ci
added 38 packages; 0 vulnerabilities

cd web && npm test
50 passed

cd web && npm run build
Next.js production build passed; /commerce-os generated

uv run alembic heads
20260727_0056 (head)

git diff --check
passed
```

聚焦 API/OpenAPI 回归为 `34 passed`；Commerce OS/MCP 聚焦回归为 `10 passed`。
运行容器 `postgres/api/web/media-worker` 全部 healthy，`/health/ready` 返回
`version=0.59.0`，数据库为单一 head `0056`。匿名 Commerce OS 请求为 401，
认证 operator 请求为 200，OpenAPI 路由声明 `KjdsApiKey`。

## 浏览器证据

- `output/playwright/release-0.59.0/commerce-os-desktop.png`
- `output/playwright/release-0.59.0/commerce-os-mobile-390.png`

桌面为 1440px；移动端实测：

```text
innerWidth=390
documentElement.scrollWidth=390
body.scrollWidth=390
errorAlerts=0
console errors=0
```

两端均显示授权 `ozon-primary`、43→3→0 漏斗、当前利润资格阻断、外部写关闭、
6 个 comparison-only 基准和 12 个 Agent handoff。

## 评审发现

| 级别 | 发现 | 处理 |
|---|---|---|
| P0 | 本切片未发现 | no-op |
| P1 | 完整成本、downside CM3、内容权利/QA、独立审批、订单和结算均为 0/no_data；完整业务覆盖尚未证明 | 继续 M1–M3，并保持 Release Gate REJECTED |
| P1 | entity authority 仍为 `no_data` | 继续 M0 scoped Evidence/grant 绑定，不以 tenant 代替 entity |
| P2 | MCP 当前只开放本地 stdio 读取，没有远程 OAuth/HTTP transport | 真实远程 Agent JTBD 出现后再做身份、会话和撤销评审 |
| P2 | OpenTelemetry、ERPNext、ComfyUI 的完整运行可观测/连接验收尚未进入本切片 | 按 ADR-0036 分别做最小 Adapter 切片 |

## Gate 边界

- Ultimate Start PM/RA 结论保持 APPROVED，仅表示允许 M0→M4 实施。
- 0.59 PM/RA Release Gates 仍为 REJECTED。
- Pilot/Final Gates 未通过。
- Ozon、供应商消息、采购、付款、库存、价格和广告写入仍关闭。
- pricing 继续是 `not_for_sale`。
- 成功指标仍是结算后 cash CM3、受控学习和可逆执行，不是自动上品数量。
