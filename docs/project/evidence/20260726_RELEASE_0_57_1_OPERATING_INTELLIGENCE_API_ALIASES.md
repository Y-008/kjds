# KJDS 0.57.1 Operating Intelligence API 别名补丁证据

- 日期：2026-07-26
- 分支：`fix/operating-intelligence-contract-0571`
- 需求：BR-079
- ADR：`docs/adr/ADR-0029-operating-intelligence-profit-task-media.md`
- 结论：修复 0.57 计划名称与运行态 OpenAPI 的显式合同偏差，不改变指标、异常扫描、
  任务、数据库或外部写入语义。

## 合同变更

- 新增认证规范入口：
  - `GET /v1/operating-intelligence/metrics`
  - `POST /v1/operating-intelligence/anomaly-scans`
- 保留向后兼容入口：
  - `GET /v1/metrics`
  - `POST /v1/anomaly-scans`
- 规范入口与兼容入口由同一 FastAPI endpoint 提供，复用同一个
  `OperatingIntelligenceService`，不复制指标、扫描或权限逻辑。
- Web 读取指标和触发只读扫描时使用规范入口；所有结果仍由服务端生成，客户端不重算。
- 两个规范入口均要求 `X-KJDS-API-Key`；匿名访问返回 401。
- 异常扫描继续只创建内部任务，`automatic_business_action=false`、
  `external_write_allowed=false`，不获得 Ozon、供应商、广告、采购、付款或媒体写权限。

## 验收证据

### 合同与认证

- OpenAPI `info.version=0.57.1`，规范路径与兼容路径同时存在，均声明
  `KjdsApiKey`。
- 路由回归测试证明两组路径指向同一个 Python endpoint。
- 运行态规范/兼容 metrics 返回相同
  `snapshot_sha256=ab7fda01bde4241a22fc72ba07f620e6103bd219fa221d02056dd5f6d0a00433`。
- 以下四项匿名直连均返回 401：
  - `GET /v1/operating-intelligence/metrics`
  - `POST /v1/operating-intelligence/anomaly-scans`
  - `GET /v1/metrics`
  - `POST /v1/anomaly-scans`
- 认证规范扫描返回八项指标、
  `automatic_business_action=false`、`external_write_allowed=false`，
  快照哈希为
  `19b093c52ed7a64c5f2e47c7ff4265dcc0ab074f52ed55db04a6c88542d487c7`；
  当前无经营样本，因此创建任务数为 0，没有伪造异常。

### 自动化门禁

- Secrets：PASS；572 个非忽略工作区文件、573 个历史路径。
- Write-path registry：PASS。
- Ruff：PASS。
- Pytest：527 passed；仅保留既有 Starlette TestClient 上游弃用警告。
- 规范/兼容路由、OpenAPI、Atlas、Workspace 定向测试：38 passed。
- Web：`npm ci` 0 vulnerabilities；46 tests passed；Webpack 生产构建通过。
- 图谱生成器 `--check`：current。
- `git diff --check`：PASS。
- Alembic：单一 `20260726_0051 (head)`；本补丁无 schema 变化。

### 运行态与前端

- PostgreSQL、API、Web、media-worker 四容器均为 `healthy`。
- `/health/ready` 返回 `status=ok`、`version=0.57.1`、
  `database.status=ok`。
- media-worker 内固定 FFmpeg `7.1` 可用。
- 认证 Web 代理从规范 metrics 入口读取成功，并从规范 anomaly scan 入口完成一次
  只读扫描；页面无客户端阈值或扫描逻辑。
- `/operating-intelligence` 生产页面返回 200。本补丁未修改 CSS/布局，0.57 已冻结的
  1440px 与 390px 截图继续适用；Web 回归仍验证 390px 显式边界和无演示数据。

### 发布审计

- 独立 PR、三项必需 CI、评论检查、squash merge 与本地 `main` 同步结果在发布时追加。
