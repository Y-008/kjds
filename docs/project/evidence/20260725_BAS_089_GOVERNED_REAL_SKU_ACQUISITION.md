# BAS-089：受控真实 SKU 采集与只读工作台

## 结论

KJDS 已复用现有 `CommerceConnector.pull(cursor)`、`healthcheck()`、Research Inbox 和 Ozon
官方只读链路，新增 1688 CLI/OpenCLI 受控采集适配层与只读 SKU 聚合工作台。工程能力已完成；
真实业务 M0 的页面核验已启动。ChatGPT Chrome Browser Bridge 可读取已登录的 1688 页面；
OpenCLI 自有桥接探测与 1688 CLI 专用 Profile 仍未就绪，活动目标列表仍为空。

本交付没有安装新插件，也没有发送询价、修改购物车、创建订单、支付、刊登或把第三方采集结果
自动晋升为正式商品事实。

## 实现范围

- 新增 `source-listing-snapshot-v1`、`market-signal-snapshot-v1`、
  `asset-manifest-v1`、`supplier-message-snapshot-v1` 四类合同。
- 以 `provider + provider_record_id + content_hash` 去重；内容变化追加版本，不覆盖历史证据。
- OpenCLI 只读采集商品、店铺、图片和视频；1688 CLI 只读执行关键词发现、Offer/SKU/包装详情
  和供应商消息检查。
- 每轮最多 20 个候选、每候选最多 5 家供应商；图片/视频按商品版本只下载一次。
- 登录失效、验证码、浏览器桥接异常、Schema 漂移和网络失败均失败关闭并要求人工接管。
- 新增真实连接器健康、发现列表、受控拉取和 SKU 工作台 API；OpenAPI 快照已更新。
- 身份不可用时 Web 显示“未知”并隐藏写操作区；Agent 状态来自真实工作台，不再硬编码。
- 修复移动端导航可访问性和无数据时的大面积空白。
- Ozon 继续使用既有官方 API/受控导出，不新增第二套凭据或网页爬取路径。

## 外部副作用边界

采集适配器的命令白名单不包含登录、发送消息、购物车、结算、下单或支付命令。所有采集证据
固定为 research-only；询价发送、样品采购、支付和刊登仍须各自的独立授权与审批。

原始 HTML、截图、日志、Cookie、浏览器登录数据库和 MFA 数据不进入 Git。资产清单只保留必要
来源 URL、内容哈希、下载状态和授权状态；下载不代表获得使用权。
供应商回复中的电话、邮箱、微信号和链接在进入 Evidence 前自动脱敏，会话引用只保存哈希。

## 真实工具探测

2026-07-25 使用已安装工具执行只读健康检查：

| 连接器 | 工具 | 状态 | 错误码 | 活动目标 |
|---|---|---|---|---:|
| `opencli-1688` | 已安装 | 需要人工接管 | `OPENCLI_BRIDGE_UNRESPONSIVE` | 0 |
| `1688-cli-catalog` | 已安装 | 需要人工接管 | `NOT_LOGGED_IN` | 0 |
| `1688-cli-messages` | 已安装 | 需要人工接管 | `NOT_LOGGED_IN` | 0 |

三项并行探测合计 5.02 秒，在 Web 15 秒读取预算内返回。这里的 OpenCLI Bridge 状态不代表
ChatGPT Chrome Browser Bridge 状态；后者已通过现有 1688 标签页发现和只读 DOM 读取验证。
书面报价和订单仍为 0；系统没有用样例或推测值冒充真实报价或订单。

## Verification

```text
uv run pytest -q --basetemp .runtime/pytest-real-sku-full-final
  PASS：373 passed（1 个上游 Starlette/httpx 弃用警告）

npm test
  PASS：25 passed

npm run build
  PASS：Next.js 生产构建与 TypeScript

uv run python scripts/verify_secrets.py
  PASS：448 个非忽略工作树文件、434 个历史路径

uv run python scripts/validate_write_paths.py
  PASS

uv run ruff check .
  PASS

uv run alembic heads
  PASS：20260721_0040（单 head）

pwsh -NoProfile -ExecutionPolicy Bypass -File scripts/verify-g1.ps1
  PASS：迁移降级/升级重放、PostgreSQL 数值约束、事务 Outbox、备份/隔离恢复、
        API/Web 认证、生产容器、Ozon 离线和明确执行意图门禁、清理

git diff --check
  PASS
```

G-1 报告位于本地忽略目录 `.runtime/G1_VERIFICATION.json`；状态为 `PASS`，
`cleanup_processes=true`、`cleanup_database=true`、`cleanup_files=true`。

## 未解除的业务阻塞

开始 5 个候选 SKU 灰度前，仍需人工完成以下动作：

1. 连接 Browser Bridge，并用独立 `kjds` 浏览器配置完成 1688 首次登录、短信或验证码。
2. 复核压缩款主线与普通低价对照关键词；运行只读搜索后选择首批真实 Offer ID。灰度最多
   5 个候选、每候选最多 5 家供应商。
3. 只读采集完成后审核字段冲突和未知值，再单独批准统一口径询价文本及发送对象。

在完成上述动作前，SKU-000/001/003 的真实商品、三家书面报价、Ozon 28 天验证、15 项全成本、
CM3、合规结论和样品审批门槛继续失败关闭。
