# ADR-0018：受控货源采集与统一研究快照

| 元数据 | 值 |
|---|---|
| status | Accepted |
| date | 2026-07-25 |
| owner | 工程负责人 / 商品负责人 |
| approver | 经营负责人 |
| affects | G0–G1 / BR-007 / BR-008 / BR-048 / BR-065 / BR-066 |

## 背景

KJDS 已有 `CommerceConnector.pull(cursor)`、Research Inbox、Evidence、候选研究、三报价和统一经营简报，但货源连接器目录仍把多个平台静态标记为 `firecrawl_browser / ready_for_credentials`，不能反映工具是否安装、浏览器桥接、登录状态、Schema 版本或最近失败。1688 CLI 与 OpenCLI 1688 Adapter 已隔离安装并完成能力核对，但尚未成为 KJDS 的统一运行时实现。

本次需要让只读商品、店铺、素材和站内信读取进入现有 Evidence 链，同时保持登录、CAPTCHA、消息发送、购物车、订单和支付在人工接管或独立审批之外不可执行。

## 决策

1. 复用 `CommerceConnector` 作为外部采集 seam；具体 Adapter 只返回 `ConnectorRecord`，不得直接写 Repository、正式报价或业务事实。
2. 新增一个深的 `SourceAcquisitionService`：统一执行 L0 `source_discover` 授权、每轮最多 20 个候选/每候选 5 家供应商的控制总数、快照合同校验、Research Inbox 捕获、内容哈希去重和只读投影。
3. 首批合同固定为：
   - `source-listing-snapshot-v1`
   - `market-signal-snapshot-v1`
   - `asset-manifest-v1`
   - `supplier-message-snapshot-v1`
4. 去重键为 `provider + provider_record_id + content_sha256`。相同内容再次观察复用已有 Evidence；内容变化追加新 Evidence，不覆盖历史。
5. OpenCLI 1688 Adapter 负责已配置 Offer 的商品、店铺与素材清单读取；1688 CLI Catalog
   Adapter 负责受控关键词搜索与已配置 Offer 的 SKU、包装和价格详情，Message Adapter 负责只读
   回复检查并优先使用服务端 `messageId`；回复中的电话、邮箱、微信号和链接在进入 Evidence
   前脱敏，会话引用只保留 SHA-256。三者都通过无 shell 的有界子进程调用，输出和错误不得
   包含 Cookie、Token、页面正文或原始会话。
6. `/v1/sourcing/connectors` 返回真实的配置、工具、桥接、登录、最近成功、合同版本和稳定错误码；未配置、未登录、CAPTCHA、桥接断开和 Schema 漂移不得显示为 ready。
7. `/v1/sourcing/discoveries` 与 `/v1/workbench/skus/{ref}` 只投影现有 Evidence、候选、报价、利润、审批和样品状态；页面不重算 Gate 或利润。
8. 调度器只调用受控采集入口：活跃商品默认 12 小时、活跃询价会话默认 2 小时。调度器不拥有目标清单、事实、审批或外部写权限；目标清单由 KJDS 配置并受 20×5 上限约束。
9. 登录、短信、MFA、CAPTCHA 和账户歧义返回 `human_action_required` 并停止。Adapter 不调用登录命令、不循环挑战、不导出浏览器 Profile，也不调用消息发送、购物车、结算确认、订单或支付命令。
10. 拼多多、闲鱼和其他公开来源保持 `research_only`；Ozon 继续使用官方 API/导出及既有 Worker，不通过网页采集替代官方合同。

## 未选择方案

- 不安装 Firecrawl 或第二个浏览器控制面；当前缺口是接线、合同和健康状态，不是通用爬虫缺失。
- 不把 CLI 输出直接写入 `SupplierOffer`；页面展示价、商品声明和消息都先是研究证据，正式报价仍走既有三报价入口。
- 不新增 Provider 专用表、任务数据库或 Schema Registry；首版复用 Evidence 元数据、Lineage 和固定回放样本。
- 不让健康检查自动修复登录或浏览器扩展；这些状态需要可见人工处理。

## 迁移与回滚

本批不新增数据库迁移。回滚代码和新增路由即可移除运行时采集；已捕获 Evidence 仍作为不可变研究历史保留。删除或停用 Adapter 配置不会删除 Evidence，也不会改变正式报价、利润、审批或订单。

## 验收

- 1688 商品、素材、消息的正常、未登录、CAPTCHA、桥接断开、Schema 漂移和重复消息固定样本可回放。
- 相同内容不同采集时间只产生一个 Evidence；字段变化产生新版本。
- 超过 20 个候选或单候选 5 家供应商失败关闭。
- 只读 Adapter 的命令白名单测试证明不能调用登录、发送、购物车、结算、订单或支付。
- 连接器端点不再把未配置能力表述为 ready。
- SKU 工作台返回研究信号、发现、正式报价、成本、审批和样品的现有状态，并固定禁止自动采购和平台写入。

## 复审触发条件

- 1688 Adapter 连续三轮修复仍不能通过代表性回放与真实只读 Pilot。
- 需要超过 20 个活跃候选、多个 Worker 或共享熔断状态。
- 出现平台官方企业 API、合法 Webhook 或可替代浏览器会话的稳定合同。
- 需要持久化调度租约、跨实例游标或高于 Evidence 窗口的查询性能。
