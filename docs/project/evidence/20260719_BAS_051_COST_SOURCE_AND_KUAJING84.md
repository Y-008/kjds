# BAS-051 成本来源与跨境巴士只读适配验证

| 项目 | 结果 |
|---|---|
| requirement | BR-038 |
| scope | 只读适配器、成本来源边界、CM2 科目完整性 |
| external write | 无 |
| credential used | 无 |
| business acceptance | 待真实企业授权、样本和财务复核 |

## 公开合同证据

- 跨境巴士正式地址：`https://api.service.kuajing84.com`；Apifox 接口说明仅用于适配器字段研究，不是最终费用权威。
- 订单列表：`/erpapi/orderlist/search`，公开响应包含六个原始费用字段。
- 出库信息：`/erpapi/order/get_order_out_info`，公开响应包含计费重量字段。
- 仓库服务：`/erpapi/storehouse/searchStorehouseSection`，公开响应包含服务名称和原始价格。
- 跨境巴士仓库帮助：`https://www.kuajing84.com/index/index/help_details/help_id/MDAwMDAwMDAwMH7QtWE.html`；当前公开内容包含部分仓库赔付按国内采购成本、单包裹/运单最高 100 元且打包费不退的边界，只能形成风险规则，实际赔付与费用仍需订单和账单。
- 逐项官网登记：`docs/project/registries/cost_authority_sources.json`，区分规则/报价与最终凭证。
- 海关：欧亚经济联盟统一税则、海关估价规则和海关法典官网已登记；最终值仍需报关单与缴款凭证。
- 税务：俄罗斯联邦税务局的跨境电商 VAT 指引与外国主体 VAT 办公室已登记；具体适用仍需主体和交易复核。
- 汇率：俄罗斯央行官方汇率页已登记为测算参考；实际利润仍需 booked FX 与手续费。
- Ozon 官方跨境物流合同：`https://docs.ozon.ru/legal/en/partners/logistics/contract/?__rr=1`；2026-05-06 版本明确费用按 Commercial Terms 与附件 5 确定、月度报告在个人账户提供。公开的 0.1% 与 150% 示例只属于该合同对应范围，不得外推为店铺统一费率。
- Ozon 广告帮助：`https://docs.ozon.ru/global/promotion/product-promotions/pay-per-click/edit-and-pause/`；页面说明预算、出价和历史操作，实际广告成本仍以账户报表为准。

## Authority Radar 运行证据

- 新增三个官方规则来源后，run `111` 真实访问得到 Ozon 两项 HTTP 307 循环与跨境巴士 HTTP 403；结果为 `success_with_errors`，没有把访问失败写成“无变化”。
- 因当前运行环境无法稳定直接抓取，三个来源改为既有 `manual + requires_review`，不引入浏览器爬虫或绕过站点保护。
- 清除三项来源的临时失败状态后执行 run `112`：`status=success`、`sources_checked=3`、`errors=[]`；全注册表 `configured=27`、`checked=27`、`healthy=27`、`failing=0`、`manual=8`。
- 运行原件：`.runtime/authority-radar/authority_radar.sqlite` 与 `.runtime/authority-radar/authority-radar-health.json`。运行时文件不提交 Git；本文件只记录非敏感结果。

## 工程验证边界

- Spec Review：逐项来源，不把第三方平台包装成全部费用权威。
- Correctness Review：适配器只开放三个读取方法；无订单创建、更新、废弃或关联入口。
- Architecture Review：复用现有 Provider、Evidence、FinanceEntry、FeeMapping 和 FxRate，不建立第二套财务账。
- Evidence Review：当前只证明公开接口合同与离线测试；未证明用户账户权限、真实字段语义或实际对账成功。

## 阻塞

`FIN-001` 仍需企业 API 授权引用、真实脱敏样本、Ozon 结算、银行到账和财务负责人批准。公开示例不得直接晋升正式利润事实。
