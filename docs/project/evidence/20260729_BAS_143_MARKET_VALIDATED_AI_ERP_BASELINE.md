# BAS-143 市场验证 Must-have AI ERP 基线 Evidence

## 1. 结论

毛子、荔枝、芒果店长、店小秘、妙手、无忧易售、Seerfar 与 LinkFox 已从
“参考灵感”升级为 KJDS `must_have_native_parity` 基线。安全能力不允许遗漏；
不安全实现必须有完成同一 JTBD 的安全替代。第三方仍不是 KJDS 事实源或运行依赖。

本项状态为 `IN_PROGRESS`：合同、运行投影、Web 和 Agent 责任矩阵已经完成，
但八类产品的全部能力尚未逐项取得真实经营验收。当前页面显示 0 个
`native_verified` 是诚实的 Release 事实，不代表代码模块为 0，也不能被隐藏。

## 2. 机器合同与来源

- Registry：`docs/project/registries/competitive_capability_patterns.json`
  version 2.1。
- 必选提供方：Seerfar、无忧易售、妙手、芒果店长、店小秘、Maozi、荔枝、
  LinkFox。
- Maozi 公开飞书 28/28 工作流继续由独立 Registry 映射。
- 店小秘依据官网与帮助中心的刊登、订单、客服、采购、库存、仓储、PDA、物流、
  数据财务与 Ozon 入口。
- Seerfar 依据官方功能页与用户提供菜单截图的选品、关键词、竞品/店铺监控、
  评论、产品卡、调价、促销与广告工作流。
- `D:\KJDS\ozon\荔枝OZON助手` 只读样本继续为 C 级实现观察；静态
  `fee.txt/category.txt`、Cookie、宽域插件和未核权图片不能成为权威。

## 3. AI 化不是聊天框

Ultimate Product Blueprint 已冻结 12 个责任 Agent：经营总控、市场雷达、商品
身份、供应链、利润定价、商品库、内容媒体、Listing、订单履约、库存物流、
风险合规、实验学习。每个 Agent 都有：

- scoped 输入事实；
- 版本化 output artifact；
- 独立 verifier；
- Owner/SLA/next；
- 明确禁止动作。

Harness 读取测试、数据库、API、页面、队列、Readback 和结算等外部观测后才
更新 Graph。模型自述完成不改变状态，Agent 不得自批、自发 Permit 或执行外部写。

## 4. 运行投影

认证 `/v1/commerce-os/workspace?store_ref=ozon-primary`：

- benchmark providers：8；
- baseline requirement：`must_have_native_parity`；
- safe capability omission allowed：false；
- mapping is implementation：false；
- provider runtime dependency：false；
- external write：false。

Commerce OS 对每家返回 required capability、native verified 和 gap IDs。
Maozi 同时显示 28/28 mapped，并明确“映射 ≠ 实现”。

## 5. 测试与浏览器

- 基线/Commerce OS 与 BAS-142 聚焦集合：92 passed。
- 全量后端：836 passed。
- Web：70 passed，39 路由生产构建通过。
- 运行容器：四项 healthy。

浏览器 section screenshot：

- `output/playwright/release-0.59.0/native-must-have-baseline-desktop.png`
- SHA-256：
  `06079d9c46446be7703e836c959ebb810f6d5fe85ee6e596a2bf24e068935a05`
- 八类名称全部可见；
- Must-have 与 external write closed 可见；
- 0 新 console error、0 failed response。

## 6. 后续完成条件

Graph 中 `task-bas143-market-baseline` 已由 registry+API+browser verifier
标记 `passed/fresh`；这只证明基线合同与投影可用。BAS-143 计划状态仍为
`IN_PROGRESS`，八类产品的逐项 native parity 未完成。

每个 gap 继续进入 M0→M4，只有 code、migration、API、Web、permission、
runtime replay、Evidence 全齐才升级 `verified_native`。AI 额外评价采用 verifier
正确率、处理时延、失败恢复、结算后 Actual Cash CM3 和现金周期，不使用生成量、
上品量或模型自评分。

0.59 Release Gates、Pilot/Final Gates 继续未通过；本基线不开放任何 Ozon、
供应商、采购、付款、库存、广告或促销写入。
