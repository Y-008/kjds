# SKU-001 公开候选预筛

## 边界

- 观察时间：`2026-07-22T01:54:58+08:00`
- 用途：只决定哪些商品值得继续取得正式 28 天需求原件、三家报价、样品和合规结论。
- 证据等级：公开搜索结果和供应商展示页均为发现信号，统一标记 `requires_review=true`、`decision_scope=research`、`fact_status=simulation`、`cost_status=estimate`。
- 本页不是 `candidate-research.csv`，不填写五指标数值，不创建 Product，不形成 `candidate_basis`，不放行付款、采购、发布、广告、补货或 `actual`。

## 淘汰的简单同质商品

| 商品形态 | 公开信号 | 裁决 |
|---|---|---|
| 单个理线夹、毛毡脚垫 | Ozon 公开结果主要落在约百卢布价格带，评论量大、同款密集 | 淘汰；低客单不足以承受跨境履约、广告、退款和审核成本 |
| 单个宠物除毛滚筒 | [Ozon 类目](https://www.ozon.ru/category/samoochischayuschiysya-rolik-ot-shersti-zhivotnyh/)展示约 `249–297 RUB`、`4,792–9,738` 条评价的成熟同质商品 | 淘汰单品；即使可采购，也没有证据证明风险调整后 CM3 足够 |
| 自粘式单个拖把夹 | [Ozon 评价样本](https://www.ozon.ru/product/derzhatel-dlya-shvabry-samokleyashchiysya-nastennyy-4sht-3339863024/reviews/)出现承重脱落、粘贴不牢和数量不符反馈 | 淘汰低价粘胶款；后续只研究带机械固定方案的铝合金墙架 |

## 进入正式取证的三个假设

### RU-HYP-001：6–7 件旅行箱收纳袋套装

- Ozon 公开类目页：[旅行收纳袋套装](https://www.ozon.ru/category/dorozhnye-organayzery-nabor-veshchey/)。公开搜索索引摘要显示约 `323–835 RUB` 的套装和多款千级评价商品，只能说明值得继续核验，不能推出 28 天销量或供需缺口。
- Alibaba 发现页：[6 件旅行收纳袋](https://www.alibaba.com/showroom/6-piece-packing-cubes-sets-travel.html)。展示页存在约 `$1.49–3.50/套`、MOQ `2–100` 的多种条目；这只是询价线索，不是可入账报价。
- 值得继续：非电、非液体、易演示、可通过面料、拉链、压缩结构和套装配置形成差异。
- 主要风险：拉链/缝线失效、尺寸误导、面料气味、颜色偏差、季节性；需实测净重、折叠体积和装箱体积。

### RU-HYP-002：8–12 件手动泵真空收纳袋套装

- Ozon 公开类目页：[真空收纳袋](https://www.ozon.ru/category/pakety-dlya-vakuumirovaniya-veshchey/)。公开搜索索引摘要显示约 `542–1,727 RUB`，部分商品有 `1,444–27,713` 条评价；这只能形成需求和竞争发现信号。
- Ozon 评价页：[真空袋评价样本](https://www.ozon.ru/category/vakuumnye-pakety-14760/review/)。公开评价同时出现持续密封的正面反馈，以及薄膜、破损、尺寸搭配和漏气风险。
- Alibaba 发现页：[手动泵真空袋](https://www.alibaba.com/showroom/vacuum-bag-with-hand-suction-pump.html)。展示页存在多种低 MOQ 条目和约 `$7.50–7.70`、MOQ `20` 的 11 件套；必须向供应商核实实际套装、泵型、厚度和报价。
- 值得继续：客单价和视频演示能力优于简单收纳件；限定手动泵版本，避免第一轮引入电器合规和电池风险。
- 主要风险：阀门和封边漏气、薄膜厚度虚标、破损、尺寸理解偏差、体积重和高退货；样品需做 72 小时保压、跌落、重复开合和不同尺寸装载测试。

### RU-HYP-003：铝合金 5 位 6 钩拖把/扫帚墙架

- Ozon 公开类目页：[5 位 6 钩墙架](https://www.ozon.ru/category/nastennyy-organayzer-derzhatel-na-5-shvabr-6-kryuchkov/)。公开搜索索引摘要显示约 `423–927 RUB`，评价样本从 `2` 到 `209` 不等；可能存在较高客单和较浅竞争，但不足以证明供需缺口。
- Alibaba 发现页：[铝合金 5 位 6 钩墙架](https://www.alibaba.com/product-introduction/Wall-Mounted-Aluminum-Hook-Tool-Organizer_1600821610928.html)。展示价约 `$1.30–3.70/套`、MOQ `1`；页面说明由第三方生成，所有材质、承重和安装声明都必须由供应商原件和样品重验。
- 值得继续：比单个粘胶夹客单更高，可通过铝材、机械固定、承重和完整配件做真实差异化。
- 主要风险：约 50–61 cm 长件带来的体积重、弯折和包装成本；安装孔位、螺丝配件、夹持直径和承重声明不实会造成退货。

## 官方边界

[Ozon 跨境物流标准条款](https://docs.ozon.ru/legal/en/partners/logistics/contract/)要求在适用时提供符合性证书或声明，并对包装、标签、重量和尺寸设有限制。因此三类假设的 `compliance_redline` 均保持“未知”，不能凭普通家居用品外观写成 `0`。

当前法规适用性、逐候选缺口和 A 级取证路径见[三候选合规预审](20260722_SKU_001_COMPLIANCE_PRESCREEN.md)。该预审不构成具体商品合规结论。

## 下一步与退出条件

私密 `candidate-research.csv` 可按指标逐项记录已取得的 `research_signal`，但只有下列资料全部齐全并通过服务端预检后，才允许形成正式候选、发起三报价交接或创建 Product：

1. 至少 28 天、30 个样本的需求、竞争和退货原件；
2. 至少两个独立来源族，且达到现有 A/B 证据等级要求；
3. 当前官方类目和质量文件要求，合规红线由 A 级证据确认；
4. 三家供应商的同口径书面报价、MOQ、贸易条款、交期、材料、净重和包装尺寸；
5. 样品实测和风险调整后 15 项成本/CM3。

若任一候选不能取得 28 天原件、三报价或可接受的样品结果，直接淘汰，不为它增加专用代码或降低 Gate。

截至 `2026-07-22`，RU-HYP-001 与 RU-HYP-002 已各找到 3 条跨 Alibaba、Made-in-China 的公开供应商联系线索；RU-HYP-003 仅确认 1 家主体明确、结构精确且铝材明确的供应商，另有 1 条精确商品页缺真实公司主体、1 家独立公司未确认铝材。它们只写入私密准备包的 `supplier_available` 研究项，公开展示价未进入 `supplier-quotes.csv`，需求、竞争、合规和退货指标仍为空，正式候选与真实询价继续失败关闭。
