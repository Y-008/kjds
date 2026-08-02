# ADR-0036：开源复用、Agent 工具与反重复造轮子

| 元数据 | 值 |
|---|---|
| status | Accepted for incremental implementation |
| reviewed_at | 2026-07-28 |
| affects | BR-055 / BR-075 / BR-078–BR-085 |
| decision owner | Commerce OS |
| implementation owner | Platform / Media / Agent Operations |

## 决策目标

KJDS 要在经营覆盖、事实质量、自动化深度、执行可靠性和结算后收益五个维度超过
无忧易售、妙手、芒果店长、Maozi、荔枝和 LinkFox 等能力基准。超越不等于把多个
开源系统堆在一起，也不等于复制未授权竞品代码；每个引入项必须减少自研面积，同时
不能产生第二套商品、订单、利润、Evidence、审批或执行真相。

本 ADR 冻结 `best_solution/2026-07-28` 选型基线。版本升级必须重新检查许可证、
迁移、维护状态、安全公告、资源成本和回滚。

## 选择

| 能力 | 候选与证据 | 决策 | KJDS 边界 |
|---|---|---|---|
| ERP 文档与标准后台 | [ERPNext](https://github.com/frappe/erpnext) `v16.22.0`，GPL-3.0，覆盖会计、采购、库存等标准 ERP 能力 | **采用隔离侧车** | KJDS 保留 Product Identity、Passport、Evidence、Profit、Approval 与执行权威；ERPNext 只接收幂等草稿/单据并回读。锁定版本，升级前回放 API 合同。 |
| Headless commerce | [Medusa](https://github.com/medusajs/medusa) `v2.15.3`，MIT；[Saleor](https://github.com/saleor/saleor) `3.23.7`，BSD-3-Clause | **当前不作为经营内核** | 两者适合自营站/渠道 storefront，但现在引入会形成第二套商品、价格、库存和订单真相。未来只有出现自营站 JTBD 时才作为外部 Channel Adapter 重新评审。 |
| 图片工作流 | [ComfyUI](https://github.com/Comfy-Org/ComfyUI) `v0.24.0`，GPL-3.0 | **采用隔离媒体 Worker** | 仅执行准入的固定版本 workflow；模型、节点、权利、输入哈希、成本、时延、输出和 QA 进入 Evidence/Lineage。KJDS 不复制第三方模型权重。 |
| 视频与编码 | [FFmpeg](https://github.com/FFmpeg/FFmpeg)，默认主体 LGPL-2.1+，可选组件可能切换为 GPL | **采用可复验固定编码链** | 冻结构建清单与 encoder/version；默认不启用会改变许可义务的可选组件。生成 MP4、封面、字幕、关键帧、编码报告和 Manifest。 |
| Agent 标准工具面 | [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) `v1.28.1`，MIT；官方说明 v1 为当前稳定线 | **采用稳定 v1，只读优先，约束 `<2`** | 第一批只暴露认证、作用域受限的 Commerce OS 读取工具。MCP Tool 不等于业务权威，不得自批、签发 Permit 或直接调用外部写。v2 只有完成迁移与安全评审后采用。 |
| 多 Agent 编排 | KJDS 现有状态机；[Microsoft AutoGen](https://github.com/microsoft/autogen) 已处于 maintenance mode，官方建议新项目使用继任框架 | **先用 KJDS 确定性状态机；不采用 AutoGen** | Agent 框架只能替换推理/编排实现，不能拥有业务状态。Microsoft Agent Framework、LangGraph、CrewAI 等须通过回放 eval、暂停恢复、幂等、租户隔离和许可评审后才可作为内部 Adapter。 |
| 可观测性 | [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python) `1.42.1`，Apache-2.0；trace/metrics 稳定，logs 尚未稳定 | **采用 API/SDK 的稳定信号** | 先接 API、HTTP、Worker、outbox 与 Agent artifact trace；日志仍沿用当前稳定管线，不把开发状态的 OTel logs 当硬依赖。 |

## 本地竞品样本结论

`D:\KJDS\ozon` 继续只读。2026-07-28 代码级盘点发现：

- 样本主要是已打包 Electron/.NET 应用、浏览器插件和安装包，不是带明确业务源码
  许可证的开源仓库；
- 插件存在 `cookies`、`<all_urls>`/宽域 host、全页面 content script 等权限；
- 本地配置包含静态凭证形态和静态费用/类目快照。

因此可以复用的是业务步骤、字段、异常分支和交互模式；不得迁入私有打包代码、密钥、
Cookie/localStorage、内部接口、宽域权限、静态费用真源或未经授权的媒体。若权利人
后续提供明确源码许可证和 provenance，再按组件逐项评审，不做整包导入。

## Agent/MCP 硬约束

1. 每个 Agent 输入必须是带 `tenant/entity/store/as_of/hash` 的服务端事实快照。
2. 输出必须是版本化 artifact、Evidence、diff、内部任务或建议；模型文本不是业务事实。
3. MCP Resource 用于只读上下文，Tool 也必须调用既有深模块接口，不直接读写内部表。
4. 所有外部写继续需要独立 Approval、一次性 Permit、Readback、Kill Switch 和
   Compensation；Agent 不得自批或签发 Permit。
5. 工具调用记录 actor、scope、输入/输出 hash、版本、耗时、成本和失败语义；无真源
   返回 `no_data/blocked`，不以模型补齐。

首个实现为本地 stdio `kjds-commerce-mcp`：只注册
`get_commerce_os_workspace` 和对应只读 Resource，复用现有 API 身份映射与
`CommerceOperatingSystem` 接口；未注册任何 publish/purchase/payment/permit/
approval Tool。

## 为什么不是“全部拿来”

- 同时引入 ERPNext、Medusa 和 Saleor会复制商品、库存、价格与订单真相，增加对账
  和迁移成本，不能增加经营优势。
- 通用 Agent 框架不能替代 Ozon 规则、CM3、Evidence、审批和结算语义；先让 KJDS
  深模块成为稳定 Tool，再评估框架，能保持可替换性。
- 开源许可证是可用边界，不是安全、质量或业务适配证明；所有侧车都要最小权限、
  固定版本、健康检查、回放、回读和卸载路径。

## 验收与回滚

- 每个采用组件必须有 SBOM/版本/许可证记录、容器健康、合同测试、失败注入和数据
  导出/卸载路径。
- 侧车故障不得破坏 KJDS 权威事实；转为 `blocked/no_data` 并创建内部任务。
- MCP 或 Agent runtime 可关闭而不影响人工完成经营闭环。
- 升级前以冻结事实快照和 golden fixtures 回放；不通过则回滚镜像/依赖版本，数据库
  迁移只允许可验证的 forward repair。
