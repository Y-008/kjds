# 2026-08-15 W1 补证：337 评价全量 + 三店主体/收款通道（只读）

| 字段 | 值 |
|---|---|
| status | OBSERVED（只读采集，零写操作） |
| 采集时间 | 2026-08-15 |
| 来源 | Ozon Seller 后台（CDP 9224 副本 Chrome）+ 页面同源 API（/api/v4/review/list 新通路）+ 设置页 UI 实测 |
| 关联 | 24e 总签核包、24f 回复执行包、24g Listing 成品 |
| 原始数据 | D:\KJDS\.runtime\w1c-linyan-reviews-all.json、w1c-beiji-reviews-all.json、w1c-3stores-legal*.json、w1c-treas-*.json |

## 一、评价全量（NOT_VIEWED 口径，与 W1 快照 337 = 125+212 对齐）

| 店 | 总数 | 5★ | 4★ | 3★ | 2★ | 1★ | 有文字 | ≤3★ 有文字 |
|---|---|---|---|---|---|---|---|---|
| LINYAN (2706897) | 212 | 156 | 22 | 13 | 2 | 19 | 91 | 34 |
| BEIJI (2735620) | 125 | 101 | 13 | 2 | 2 | 7 | 50 | 11 |

## 二、差评聚类（驱动 24e 归档清单）

- LINYAN 花园秋千 2013451212：标题「качели」实发蚊帐/篷布，1★×6 聚簇 → 归档。
- LINYAN 急救箱 1991148962 1★×3、水龙头 1958225675 缺三通 1★×2 → 归档。
- BEIJI 建筑搅拌机 2208635505：中国插头 + 缺件 1★×2、无力 2★ → 暂停销售。
- BEIJI 折叠床 2021923794 图文不符 1★（4 图）→ 修 Listing。
- 折梯 2016928452 塑料台阶 2★、燃气灶 1959976490 破盒 2★ → 复投池禁入（钢/铝加强款 + 新包装才可重新评估）。

## 三、三店主体/收款通道（设置页 UI 实测）

| 店 | 卖家 ID | 法人名称 | 税号 | 激活合同 | 支付方式 | 备用账户 |
|---|---|---|---|---|---|---|
| BEIJIXINGYOUXUAN | 2735620 | Zhaodong City star cloud Hui Internet sales Co., LTD | 91231282MAE08E0C2C | 待复核 | LianLianPay CNY（同主体推断） | 待复核 |
| LINYAN888 | 2706897 | 同上 | 同上 | КОМИСС 39-81237/25 от 14.03.2025 | LianLianPay CNY | 未添加 |
| Treasures of the road | 2315091 | 同上 | 同上 | КОМИСС 39-301280/24 от 23.09.2024 | LianLianPay CNY | 结算账户 5181240920027820298（CNY） |

- TREAS：余额 12,621.01₽，8 月应计 0，当期应收 0，标准时间表激活 → 无可付金额，提现入口暂不显示属正常。
- 新支付方式可用：PingPong / Payful (GEP) / PandaPay（仅记录，不动）。

## 四、API 通路 v3 新增（复用清单）

- 评价列表：POST /api/v4/review/list，body {company_id, company_type:'seller', filter:{published_at:{}, interaction_status:['NOT_VIEWED'], awaiting_reply?:true, by_content_2:[], publish_info:[]}, sort:{sort_by:'PUBLISHED_AT', sort_direction:'DESC'}, last_review?:<上一页响应>}；每页 5 条，hasNext + last_review 游标翻页。
- 评价计数：POST /api/review/counter，body {company_id, company_type:'seller'}。
- 跨公司调用：/api/v4/review/list 信任 body 的 company_id（无需切换当前公司）。
- 公司切换 UI：右上角公司名 SPAN（n2d-l3）mouseMoved→click 打开菜单（行为不稳定，建议优先用 API 跨公司读取）。

## 五、红线声明

- 本报告全部只读，未回复、未改价、未归档、未提现。
- BEIJI 合同号与备用账户状态待下次 UI 复核，不影响收款通道同源结论。
