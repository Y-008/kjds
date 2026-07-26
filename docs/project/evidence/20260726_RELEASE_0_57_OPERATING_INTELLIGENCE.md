# KJDS 0.57 Operating Intelligence 发布证据

- 日期：2026-07-26
- 分支：`feature/operating-intelligence-057`
- 需求：BR-078、BR-079、BR-080
- ADR：`docs/adr/ADR-0029-operating-intelligence-profit-task-media.md`
- 边界：本版本不授予 Ozon、供应商、广告、采购或付款写权限；Figma 未连接且未写入。

## 1. 服务端合同

### 实际利润账

- `GET /v1/profit-ledger`
- `GET /v1/profit-ledger/erosion`
- 唯一归集维度为 `store_ref + product/SKU + order + accounting_date + currency`。
- 只接受订单自然键、正式 FactRecord 或显式绑定；未知金额进入
  `unallocated/blocked`，`proportional_allocation_allowed=false`。
- 场景 CM3、应计贡献、结算贡献、到账贡献与 actual profit 分列；实际利润只有在所需
  Evidence 完整时出现。
- 侵蚀类别固定为采购、物流、仓储/库龄、佣金、广告、退货退款、折扣、税费、FX、
  损耗、未分摊；测试验证 `baseline - Σ erosion = result`。

### 数据异常与运营任务

- `GET /v1/metrics`
- `POST/GET /v1/anomaly-scans`
- `GET /v1/operating-tasks`
- `POST/GET /v1/operating-tasks/{task_id}/events`
- 指标注册表版本为 `operating-metrics/1.0.0`，首批八项指标均包含固定基线、最小
  样本、阈值、严重度、冷却期、Owner 和 Evidence 要求。
- 稳定指纹与冷却期阻止重复建任务；任务只投影进既有 `OperationsQueueService`。
- 状态机为 `open → acknowledged → in_progress → resolved|dismissed`；解决或驳回
  必须提供理由和有效 Evidence。
- 扫描返回 `automatic_business_action=false` 与
  `external_write_allowed=false`。

### 媒体工作台

- `GET /v1/media/workbench`
- `POST /v1/content/assets/{asset_id}/execution`
- `POST /v1/media/executions/batch`
- `POST /v1/content/assets/{asset_id}/execution/sync`
- `GET /v1/content/assets/{asset_id}/delivery-manifest`
- 图片只允许固定版本准入模板；批量执行逐项幂等并显式返回部分失败。
- 视频只接受同商品已批准图片、人工批准俄语脚本/字幕及有效音频权利 Evidence。
- 独立 `media-worker` 从 PostgreSQL 租约领取，使用固定 FFmpeg 链生成
  9:16、1:1、16:9 MP4、封面、字幕、关键帧与编码报告，不使用外部视频 Provider、
  Redis、Kafka 或 Temporal。
- 产物全部进入 Blob/Evidence，记录输入哈希、模板、编码器、耗时、成本和输出哈希；
  只有 QA 全过的资产可以生成 Listing 可用 Manifest。

## 2. 数据库证据

- Alembic 单一 head：`20260726_0051`
- PostgreSQL 已从 `20260726_0050` 升级到 `20260726_0051`
- 新表：
  - `operating_tasks`
  - `operating_task_events`
  - `anomaly_scan_runs`
  - `media_executions`
  - `media_execution_events`
  - `media_delivery_manifests`
- `operating_task_events`、`anomaly_scan_runs`、`media_execution_events` 存在数据库
  不可变触发器；迁移只新增表、索引与触发器，不改写既有业务事实。

## 3. 自动化验证

- `uv run python scripts/verify_secrets.py`：通过，检查 571 个非忽略工作区文件与
  557 个历史路径
- `uv run ruff check .`：通过
- `uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local`：
  526 项通过；仅有一项来自 Starlette TestClient 的上游弃用警告
- Web `npm test`：46 项通过
- Web `npm ci`：安装锁定依赖成功，0 vulnerabilities
- Web `npm run build`：通过，包含静态路由 `/operating-intelligence`
- `uv run python scripts/build_cross_border_operating_graph.py --check`：registry current
- `git diff --check`：通过
- OpenAPI 快照与服务端合同测试：通过；运行态 OpenAPI 为 `0.57.0`，共 219 条路径

## 4. 前端真实性边界

- `/operating-intelligence#profit`：真实 SKU/订单利润趋势、覆盖率、对账、侵蚀桥和
  Evidence；无完整证据显示“实际利润不可显示”。
- `/operating-intelligence#anomalies`：版本化指标、固定基线、最小样本、异常任务、
  Owner、冷却期和不可变处理记录。
- `/operating-intelligence#media`：模板目录、Brief/权利边界、批量/执行账、图片/视频
  状态、QA、成本、重试和 Manifest。
- 所有图表为服务端返回值派生的 HTML/SVG；源码没有 `Math.random` 或演示趋势。
- 能力工作区的 finance、products、data、overview 领域入口分别指向真实利润、媒体和
  异常工作区。

## 5. 运行态与权限证据

- Docker Compose 的 PostgreSQL、API、Web、media-worker 四项服务均为 `healthy`。
- Alembic `heads` 与 `current` 均为单一 `20260726_0051 (head)`。
- `GET /health/ready` 返回 `status=ok`、`version=0.57.0`、
  `database.status=ok`。
- 运行态 OpenAPI 包含利润账、侵蚀桥、指标、异常扫描、运营任务、任务事件、媒体
  工作台、批量执行、同步和 Manifest 合同。
- 匿名直连以下六个读取入口均返回 401：
  `/v1/profit-ledger`、`/v1/profit-ledger/erosion`、`/v1/metrics`、
  `/v1/anomaly-scans`、`/v1/operating-tasks`、`/v1/media/workbench`。
- 认证 Web 代理访问同一组数据成功；浏览器页面没有触发任何平台写入，页面持续显示
  `OZON WRITE DENIED`。

## 6. 浏览器验收证据

- 桌面：
  `output/playwright/release-0.57.0/operating-intelligence-desktop.png`
  - 视口 `1440px`，`documentElement.scrollWidth=1440`
  - SHA-256：
    `BEB9FE5A62E90F3EE1725577F2CE2C47E122DF83B16F00B7D06D429CDAC6F8E5`
- 移动端：
  `output/playwright/release-0.57.0/operating-intelligence-mobile.png`
  - 视口 `390px`，布局宽与 `scrollWidth` 均为 `375px`（15px 为浏览器滚动条），
    无水平溢出
  - SHA-256：
    `154088B699C8EF7E535053A06B7612ACE0A6CFAED707B1776515CC7F57415054`
- 两个视口控制台均为 0 error。
- 浏览器穿透 `/operations/points/media_delivery_manifest` 后，“进入领域工作区”和
  “进入图片与视频工作台”均真实链接到 `/operating-intelligence#media`；节点同时
  显示“能力已实现”与“无运行真源”，没有把合同存在冒充为已验证业务结果。

## 7. 发布闭环

- 0.57 通过独立分支 `feature/operating-intelligence-057` 发布。
- PR 必需检查、评论处置与 squash merge 结果由同一 PR 的 GitHub 审计轨迹冻结；
  合并后本地 `main` 必须 fast-forward 到该 squash 结果。
