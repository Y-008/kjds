# 真实 SKU 采集运行手册

## 目标与边界

本手册把 1688 商品、供应商公开信息、素材和站内信回复作为 Research Inbox 证据接入 KJDS。采集任务可以读取并在本地固化证据，但不能发送询价、修改购物车、创建订单、提交结算或支付。

正式报价仍必须通过三家同口径报价入口建立 `SupplierOffer`；第三方页面字段、商品声明和站内信快照不会自动晋升为商品事实。Ozon 继续使用官方 Seller API、既有只读 Worker 或受控导出，不用网页采集替代官方合同。

## 首次配置

1. 为 KJDS 建立独立的 1688 浏览器 Profile。不要复用含个人浏览、支付或其他业务账户数据的 Profile。
2. 在有人值守的窗口中完成首次登录、短信、MFA 或验证码。KJDS 不保存或复制 Cookie、登录数据库和 MFA 材料。
3. 配置本地 CLI 入口和目标清单：

```dotenv
KJDS_OPENCLI_ENTRYPOINT=C:\path\to\opencli\dist\src\main.js
KJDS_1688_CLI_ENTRYPOINT=C:\path\to\1688-cli\dist\cli.js
KJDS_1688_PROFILE=kjds
KJDS_1688_SEARCHES_JSON=[{"candidate_ref":"candidate://compression-main","keyword":"真空压缩收纳袋","max_results":5,"sort":"relevance"},{"candidate_ref":"candidate://ordinary-control","keyword":"普通收纳袋","max_results":5,"sort":"price-asc"}]
KJDS_1688_TARGETS_JSON=[{"candidate_ref":"candidate://compression-main","offer_id":"900000000001","seller_id":"public-member-id"}]
KJDS_1688_ASSET_DOWNLOAD_ROOT=.runtime/source-assets
```

关键词清单最多包含 20 个受控搜索，每次最多返回 5 条且默认排除广告。首个 SKU 使用
`compression-main` 压缩款主线与 `ordinary-control` 普通低价对照；先搜索，再人工选择 Offer ID。
目标清单最多包含 20 个活跃候选，每个候选最多 5 个 Offer。`offer_id` 只接受数字。素材保存在
Git 忽略的 `.runtime/` 下；每个素材版本使用来源清单哈希分目录，同一版本只下载一次。每个文件
记录 SHA-256、大小和 `rights_status=requires_review`，下载不等于取得使用权。

## 健康检查

使用只读端点检查真实状态：

```http
GET /v1/sourcing/connectors
```

重点字段：

- `tool_installed`：本地入口是否存在。
- `browser_bridge_connected`：OpenCLI Browser Bridge 是否响应。
- `logged_in`：专用 Profile 是否已登录。
- `target_count`：当前受控目标数。
- `last_success_at`：最近一次成功读取时间。
- `schema_version`：KJDS 适配合同版本。
- `error_code` 与 `human_action_required`：稳定停机原因和是否需要人工接管。

`NOT_LOGGED_IN`、`CAPTCHA_REQUIRED`、`BROWSER_BRIDGE_DISCONNECTED`、`BROWSER_BRIDGE_UNRESPONSIVE` 或账户歧义出现时，任务立即停止。人工处理完成后重新运行健康检查；不要循环挑战、绕过验证或从其他 Profile 复制会话文件。

2026-07-25 的本机只读实测结果为：OpenCLI 工具已安装但 Browser Bridge 无响应；1688 CLI
Catalog 与 Message Adapter 已安装但现有 Profile 未登录。三项并行健康探测 5.02 秒返回。
因此真实采集尚未 ready，正式报价仍为 0。

## 受控采集

连接器健康后，先运行受控关键词发现与已批准 Offer 详情读取：

```http
POST /v1/sourcing/acquisitions/pull
Content-Type: application/json

{"connector_name":"1688-cli-catalog","cursor":null}
```

搜索结果只形成研究快照。人工选择最多 5 个目标 Offer 并写入 `KJDS_1688_TARGETS_JSON` 后，再运行
`1688-cli-catalog` 取得 SKU 组合、页面库存、价格阶梯和包装记录，并运行 `opencli-1688`
取得公开属性、店铺和素材：

```http
POST /v1/sourcing/acquisitions/pull
Content-Type: application/json

{"connector_name":"opencli-1688","cursor":null}
```

站内信只读增量检查：

```http
POST /v1/sourcing/acquisitions/pull
Content-Type: application/json

{"connector_name":"1688-cli-messages","cursor":"2026-07-25T00:00:00+00:00"}
```

采集入口先执行 L0 `source_discover` 授权，再校验批量上限与快照合同。相同 `provider + provider_record_id + content_hash` 复用已有 Evidence；字段变化追加新版本。消息优先使用服务端 `messageId` 去重。

读取结果：

```http
GET /v1/sourcing/discoveries?candidate_ref=candidate%3A%2F%2Fcompression-main
GET /v1/workbench/skus/candidate%3A%2F%2Fcompression-main
```

SKU 工作台把研究快照、正式报价、全成本场景、审批和样品单投影在一起。缺失字段显示为未知；该接口不重算利润、不发询价、不采购、不支付、不上架。

## 调度策略

调度器只负责按已批准目标触发采集，不拥有目标、证据、报价、审批或订单：

- 活跃候选商品：每 12 小时运行 `1688-cli-catalog` 与 `opencli-1688`。
- 活跃询价会话：每 2 小时运行 `1688-cli-messages`，保存返回游标。
- Ozon 市场和账户数据：每天通过官方 API Worker 或受控导出更新。
- 每轮仍受 20 个候选、每候选 5 家供应商和 500 条快照上限约束。

只有健康状态为 `ready` 才调度采集。出现登录、验证码、桥接或 Schema 错误后暂停对应连接器并通知人工。适配器连续三轮修复仍无法通过固定样本和代表性真实只读页面时，才评估小型私有 OpenCLI Adapter；不同时引入第二套采集框架。

## 询价与样品门槛

当前 Adapter 不包含消息发送命令。要进入真实询价，先在 SKU 工作台核对候选、Offer、供应商主体、待确认字段和统一询价文案，再由用户对明确的供应商与完整文案逐项批准。发送后的原始书面回复才可进入正式报价流程。

样品单必须继续满足三份同口径书面报价、包装尺寸/毛重/MOQ/样品价/国内运费/交期确认、Ozon 28 天验证、15 项全成本无未知、正 CM3 与安全边际、合规和授权结论、不可变审批快照及职责分离。系统不自动支付；首单只允许样品或最小可验证批量。

## 故障与证据处理

- 原始 HTML、截图、Trace、下载素材和命令日志不得提交 Git。
- 供应商回复中的电话、邮箱、微信号和链接在进入 Evidence 前自动替换；会话引用只保留
  SHA-256。发现其他个人信息或会话数据时先停止并人工脱敏，不把原值写入 Research Inbox。
- Schema 漂移先保留脱敏固定样本，更新 Parser 与合同测试，再恢复真实读取。
- 重复运行必须不产生重复 Evidence、重复询价或任何外部写操作。
- 需要回滚 Adapter 时只移除运行时配置与代码；历史 Evidence 保留，不覆盖或删除。
