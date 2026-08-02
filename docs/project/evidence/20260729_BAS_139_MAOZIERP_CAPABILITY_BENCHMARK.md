# BAS-139 Maozi ERP 飞书能力基准完整映射 Evidence

## 1. 结论

用户提供的公开飞书文档
`https://mcn5ze6lo0iz.feishu.cn/wiki/Zd2xwn5m4ijIaQkiDc7c34qgnye`
已经按页面可见目录和正文建立 28/28 项能力映射，未映射数为 0。

本结论现为 `IN_PROGRESS`：28 项研究映射和首个可见运行投影已完成，但不是
28 项实现完成。每一项仍须按 M0→M4 分别取得代码、迁移、API、Web、真实运行
和业务 Evidence 才能升级状态。

## 2. 机器真源

- Registry：
  `docs/project/registries/maozierp_feishu_capability_benchmark.json`
- contract：`kjds-competitive-capability-benchmark-v1`
- benchmark：`maozierp-feishu-ozon-20260729`
- 来源等级：C
- 权威：`workflow_and_capability_observation_only`
- canonical capability snapshot SHA-256：
  `763f8496bceaecdd6355135a2c31290018dfca716d863e1ae5dcad49b43aa86e`
- Registry 文件 SHA-256：
  `8c228bb8aa858342d06f2f55a976d6858bc3e1feda310ffb28af7b6f5f640a6e`

## 3. 覆盖

- 观察能力：28
- 已映射：28
- 未映射：0
- `adapt`：18
- `deepen`：7
- `replace`：2
- `reject`：1
- external write allowed：false
- `implementation_is_not_claimed_by_mapping`：true

覆盖域包括：插件/授权/同步、多店 Listing、AI 文案/翻译/图片、1688/淘宝/
拼多多采集、库存、促销、利润计算、店铺分析、多店管理、Listing 状态与修复、
水印、规则选品、批量候选、自动促销退出、Passport/取件/评价提醒、经营看板、
多设备、订单、反查话题标签、错误处理和工具目录。

## 4. KJDS AI ERP 落点

所有安全能力均映射到 KJDS 原生经营内核：

- PIM：Canonical Product、Exact Variant、Passport、ListingPlan。
- OMS：订单、退货、取消、客服时间线和出单触发采购审查。
- 供应/采购：Browser Capture Inbox、来源适配器、正式报价和 landed cost。
- 库存/履约：库存账、多仓、FBP/realFBS、补货和物流。
- 财务：15 项 Decimal CM3、应计/结算/到账三本账和对账。
- 内容媒体：俄语内容草稿、图片/视频任务、权利/QA/Manifest。
- BI：Market Radar、Opportunity、异常任务、组合和结算后学习。
- Agent Team：只生成内部 artifact、建议、差异和任务；状态由真实 Harness
  Observation 回写 Graph，Agent 不得自证。

套餐和成熟度只改变配额、协作、SLA、连接器频率和可申请执行包络，不能改变
事实真实性、利润口径、Evidence 或外部写治理。

## 5. 明确拒绝的旧路线

- Cookie/localStorage/session 绑定与跨店复用。
- `<all_urls>`、宽域 host、全页自动注入、webRequest/CSP 移除。
- 未核权复制供应商或同行图片。
- 把公开展示价升级为 Supplier Offer/actual cost。
- 无完整 downside CM3、Passport、媒体权利/QA、独立 Approval 和一次性
  Permit 的一键铺货。
- 绕过验证码、限流、平台条款、知识产权或内部 API。

## 6. 验证

- `CommerceOperatingSystem._maozierp_workflow_registry`
  - 从版本化 Registry 动态读取 28 项，不在 API 或前台复制第二份常量；
  - 返回源哈希、28/28/0、采用与实现状态汇总、逐项原生目标/波次/边界；
  - count、ID、adoption 或 external-write 边界漂移时失败关闭。
- `/v1/commerce-os/workspace` 的 `benchmark_coverage[maozierp].workflow_mapping`
  暴露同一服务端投影；`/commerce-os` 可展开逐项查看，并明确显示
  “映射 ≠ 实现 · 外部写关闭”。
- 同一 Registry 文件 SHA-256 进入 12 个责任 Agent 的
  `input_snapshot_hashes.competitive_benchmarks`；基准资料变化会改变 Agent
  输入快照，不能沿用旧结论。
- `tests/test_maozierp_capability_benchmark.py`
  - 28 个 ID 唯一；
  - count/adoption summary 与实际载荷一致；
  - canonical hash 可重算；
  - 高风险路径 fail-closed；
  - mapping 不等于 implementation。
- `tests/test_competitive_capability_patterns.py`
  - Maozi 来源 URL、benchmark registry 和拒绝项已进入统一竞争能力注册表。
- 聚焦服务端：`13 passed`（Commerce OS + benchmark registry）。
- Web 合同：`66 passed`，包含逐项工作流映射可见性和外部写边界。
- 全量后端：`807 passed`，9 warnings（仅已知依赖弃用警告）。

## 7. 运行回执

- 镜像明确执行 `COPY docs/project/registries ./docs/project/registries`。
- 四容器：PostgreSQL/API/Web/media-worker 均 `healthy`。
- API `/health/ready`：HTTP 200，version `0.59.0`，database `ok`。
- Alembic current/head：`20260729_0071`，单一 head；本切片未新增或重跑迁移。
- 认证 `/v1/commerce-os/workspace?store_ref=ozon-primary`：HTTP 200；
  Maozi `28 observed / 28 mapped / 0 unmapped / 28 rows`；
  `mapping_status=mapped_not_implemented`；
  `implementation_is_not_claimed=true`；
  `external_write_allowed=false`。
- 运行镜像 Registry SHA-256：
  `8c228bb8aa858342d06f2f55a976d6858bc3e1feda310ffb28af7b6f5f640a6e`。
- 12/12 责任 Agent 的 `competitive_benchmarks` 输入哈希均与该运行镜像
  Registry SHA-256 一致。
- 同 endpoint 匿名访问：HTTP 401；`/commerce-os`：HTTP 200。

## 8. 后续实施顺序

- M0：统一 tenant/entity/store、Evidence、规则、RBAC/SoD、Graph/Harness。
- M1：市场/供应情报、精确 cohort、机会评分、Browser Capture Inbox。
- M2：PIM/Passport、内容媒体、Listing approval allocation、受控 Pilot。
- M3：OMS、库存、履约、售后、结算/到账 CM3、组合学习。
- M4：多店/多主体/企业 RBAC、用量/商业化、SSO/SLA/灾备。

0.59 PM/RA Release Gates 继续 `REJECTED`；这份基准不改变 Pilot、Final Gate
或任何 Ozon/供应商/采购/付款/广告外部写状态。
