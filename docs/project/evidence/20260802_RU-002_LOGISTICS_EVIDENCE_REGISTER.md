# RU-002 真实物流成本 Evidence Register

## 约束

- 只记录 `wuliu/` 下已提供原件的只读抽取结果。
- 原件文件不入 Git；本 register 只保存相对路径、SHA-256、页/表/单元格定位与可验证摘录。
- 任何未在原件里明确给出的 `税口径 / 含税 / 不含税 / 生效截止 / 结算主体` 一律记为 `UNKNOWN`。
- 所有金额均为来源原文，未做币种换算。

## 原件清单

| 相对路径 | SHA-256 | 备注 |
|---|---:|---|
| `wuliu/【2025.11.26】Yandex产品测费表(1).xlsx` | `b80d229e3c1e5426dae9d23adae773ad422bf3d3612df6ef92d91c500871723f` | Yandex 早期测费表，含 FBP / rFBS 费腿 |
| `wuliu/130 CEL深圳机场中心仓价格测算表(V7.24).xlsx` | `97056b3f8bd5eade9e7245a2f50299cef989ecac27163f6fbb4dfdacfd5d9941` | CEL / WB / Yandex / CIS 一体表 |
| `wuliu/CEL产品资费表 V7.24.xlsx` | `f7636864650c0dffab2cf398cb172324b6c7041b0591eab123ef14ca3583e010` | CEL rFBS / FBP / CIS / WB / Yandex |
| `wuliu/CEL最新资费试算表V7.24.xlsx` | `4141e05916d3ad7b72c003767f9b2efa39dabae498a0456d7dbd2fd37ddbe89f` | CEL 最新试算表，含退货/销毁提示 |
| `wuliu/GUOO产品资费测算表【2026.7.20更新】.xlsx` | `5b53889f49de6fd99df4a53b5e0ba02a03412e61c0972afc3f70c1eae4e0b86c` | GUOO / 头程 / 仓储 / 报关 / 增值服务 |
| `wuliu/Ural国际物流报价单20260721.xlsx` | `3d2a1f976460d758ef716df2688da0810eb311dcb6dc0605b00fa2fcb324c231` | Ural Ozon / Yandex / 退货 / 理赔 |
| `wuliu/兴远rFBS全渠道计算器2026-07-17.xlsx` | `2fbcfc9c924987ca94e51633d89a4770cf2704fbd894aef8e9506930266b6331` | 兴远 Ozon / Yandex / 存储 / 销毁 / 回退 |
| `wuliu/欧亚兴rFBS全渠道计算器2026-07-17.xlsx` | `871e92352b9e3a21b0a1b5646c05dae24a4e6299ac3a10ae4eafa7e26b17ff3b` | 欧亚兴 Ozon / Yandex / 存储 / 回退 |
| `wuliu/阿尔巴特rFBS全渠道计算器2026-07-17.xlsx` | `dd0d2f318d66150c2df768cfe297f10777a4b699771ed6871ed7e61755d418b0` | 阿尔巴特 Ozon / Yandex / 存储 / 回退 |
| `wuliu/130CEL深圳机场中心仓代贴单系统操作流程（V03.24）(16).pdf` | `2f05aa48e8c9bb4a04092e5bd06792b239e82f906cd36dc35ce81f66305bfa47` | 代贴单 / 增值服务 / 销毁流程 |
| `wuliu/130WB大粤深圳机场中心仓代贴单系统操作流程（V01.13）(2).pdf` | `902c9de543e7fc06859d2369091b9d7543f55499db1b1be218c538f7a4c67f5e` | WB 代贴单 / 增值服务 / 运费 |
| `wuliu/130yandex大粤深圳机场中心仓代贴单系统操作流.pdf` | `92e357e6338678b0f30b249fcee84dbbe7ed9983638563b28721dde407157994` | Yandex 代贴单 / 增值服务 |
| `wuliu/OZON-CEL仓库绑定及运输方式操作流程（V02.20）.pdf` | `1566ee3cc4a14e62eb13a26b37ae0fb8c88e477543a85f8183d4460bf6847f42` | 仓库绑定 / 配送方式 / 退货地址 |
| `wuliu/WB326005建仓流程.pdf` | `a3535c15dedb8aabea9c43e0030b0e7fe96e1e25c41841c618f6f99c01bbad42` | WB 仓库代码 / 物流限制 / 退货服务 |
| `wuliu/Yandex Market 仓库设置方法(东莞）(1).pdf` | `cdd5b8eb2bf8c17c05125d2106ab94c2ceeb73c7b0ad195f7ff4a6a59664d584` | 仓库设置流程 |
| `wuliu/1600858dfc1b43297c8c1fb7526b4a28.jpg` | `237203821b8ab3901d5a49847f28099e5ef407749f4af9758e795014807c8269` | 代贴单 / 拆单 / 合单 / 贴标 / 包材 |
| `wuliu/ca43db8d4405eca995547a4fc20404d0.jpg` | `fc040342662c557931e4e17864fade4bbdf5dc247d7acfb972e4194d427363d1` | 另一张服务费 OCR 图 |

## 核心运费腿

### 1) Yandex 产品测费表

| 原件 | 定位 | 抽取结果 | 口径 |
|---|---|---|---|
| `wuliu/【2025.11.26】Yandex产品测费表(1).xlsx` | `Sheet1!B3:H10` | `Fbp-Express 703卢布/kg + 158卢布/票`；`Fbp-Express Extra Small 538卢布/kg + 76卢布/票`；`Fbp-Economy 457卢布/kg + 158卢布/票`；`Fbp-Economy Extra Small 280卢布/kg + 76卢布/票`；`rFBS-Express 703卢布/kg + 158卢布/票`；`rFBS-Express Extra Small 538卢布/kg + 76卢布/票`；`rFBS-Economy 457卢布/kg + 158卢布/票`；`rFBS-Economy Extra Small 280卢布/kg + 76卢布/票` | 币种 `RUB`；`计费单位=kg + 票`；`tax=UNKNOWN`；`有效期=2025-11-26（文件名）/结束 UNKNOWN` |

### 2) 130 CEL 深圳机场中心仓价格测算表

| 原件 | 定位 | 抽取结果 | 口径 |
|---|---|---|---|
| `wuliu/130 CEL深圳机场中心仓价格测算表(V7.24).xlsx` | `报价主页!D3`, `报价主页!D5`, `报价主页!D7` | 页面明确写了三条线的生效日期：`CEL 2026-07-24`、`WB(CEL陆运) 2025-11-17`、`Yandex 2026-01-09` | 这是显式版本/日期，不是推断 |
| `wuliu/130 CEL深圳机场中心仓价格测算表(V7.24).xlsx` | `CEL运费价格测算表!A4:K20` | `CEL Express Extra Small 50.5元/kg + 3.37元/票`；`CEL Standard Extra Small 39.3元/kg + 3.37元/票`；`CEL Economy Extra Small 28.1元/kg + 3.37元/票`；`CEL Express Budget 37.1元/kg + 25.83元/票`；`CEL Standard Budget 28.1元/kg + 25.83元/票`；`CEL Economy Budget 19.1元/kg + 25.83元/票`；`CEL Express Small 50.5元/kg + 17.97元/票`；`CEL Standard Small 39.3元/kg + 17.97元/票`；`CEL Economy Small 28.1元/kg + 17.97元/票`；`CEL Express Premium Small 50.5元/kg + 24.71元/票`；`CEL Standard Premium Small 39.3元/kg + 24.71元/票`；`CEL Economy Premium Small 28.1元/kg + 24.71元/票`；`CEL Standard Big 28.1元/kg + 40.44元/票`；`CEL Economy Big 19.1元/kg + 40.44元/票`；`CEL Express HK 9.6元/100g + 19元/票` | 币种 `CNY`；模式 `到取货点`；`计费逻辑` 以实重/体积重为主；`tax=UNKNOWN` |
| `wuliu/130 CEL深圳机场中心仓价格测算表(V7.24).xlsx` | `CEL运费价格测算表!K4:K10`, `K13`, `K16` | `退货服务=免费销毁 / 无改派 / 无退回`；部分档位支持改派/退回，且按 `正向运价 x1.5倍` 收费 | 这是明确的退货/销毁规则，非猜测 |
| `wuliu/130 CEL深圳机场中心仓价格测算表(V7.24).xlsx` | `WB 运费价格测算表!B4:F5`, `A10` | `WB 326005`；`58元/kg + 2元/票`；`43元/kg + 8元/票`；`退货服务：派送失败退回WB官方仓我司不承运不收费；清关失败退货42元/票` | 币种 `CNY`；仓库代码显式为 `326005` |
| `wuliu/130 CEL深圳机场中心仓价格测算表(V7.24).xlsx` | `yandex 运费价格测算表!A4:F7` | `Yandex Express 550 RUB/kg + 78 RUB/票`；`Yandex Express 715 RUB/kg + 161 RUB/票`；`Yandex Economy 287 RUB/kg + 78 RUB/票`；`Yandex Economy 465 RUB/kg + 161 RUB/票` | 币种 `RUB`；模式 `到取货点` |
| `wuliu/130 CEL深圳机场中心仓价格测算表(V7.24).xlsx` | `CEL白俄罗斯和哈萨克斯坦运费价格测算表!A4:K22` | 白俄罗斯/哈萨克斯坦线路给出 `36.4/26/17.68/23.92/29.12 元/kg` 与 `3.12/16.64/23.92/37.44/64.48 元/票` 的组合；退货服务栏出现 `销毁`、`退回销毁` | 这是 CIS 线路，不直接等于 RU，但可作为跨境对比 |

### 3) CEL 产品资费表 / 最新试算表

| 原件 | 定位 | 抽取结果 | 口径 |
|---|---|---|---|
| `wuliu/CEL产品资费表 V7.24.xlsx` | `OZON-rFBS!A3:O16`、`OZON-FBP!A3:O16` | 与上表一致的 Ozon 费腿：`3.37 + 0.0505/0.0393/0.0281 元/克`，`25.83 + 0.0371/0.0281/0.0191 元/克`，`17.97 + 0.0505/0.0393/0.0281 元/克`，`24.71 + 0.0505/0.0393/0.0281 元/克`，`40.44 + 0.0371/0.0281/0.0191 元/克` | 这是费率口径更细的版本 |
| `wuliu/CEL产品资费表 V7.24.xlsx` | `OZON-rFBS!G3`, `G9`, `G19` | `免费销毁 / 无改派 / 无退回`；`支持改派 / 支持退回 / 收取正向运价x1.5倍` | 退货/销毁规则显式存在 |
| `wuliu/CEL产品资费表 V7.24.xlsx` | `WB!A3:H5`, `Yandex!A3:F7` | `WB-Express 48元/kg+9元/票`；`WB-Economy 58元/kg+2元/票`；`WB-Economy 43元/kg+8元/票`；`Yandex 715/161`, `550/78`, `465/161`, `287/78` | 与 130 workbook 相互印证，但版本不同，需按来源日期选用 |
| `wuliu/CEL产品资费表 V7.24.xlsx` | `OZON CIS 独联体国家!A3:J15` | 白俄罗斯/哈萨克斯坦独联体线路再次给出 `36.4/26/17.68/23.92/29.12 元/kg` 与对应票费，并把退货写为 `销毁` 或 `退回销毁` | 适用于 CIS，不直接外推俄罗斯本土 |
| `wuliu/CEL最新资费试算表V7.24.xlsx` | `OZON-rFBS!M5`, `M11`, `M21` | 细化写明 `免费销毁 / 无改派 / 无退回`，以及 `支持改派 / 支持退回 / 收取正向运费×1.5倍` | 与前表一致，作为复核来源 |

### 4) GUOO 资费与增值服务

| 原件 | 定位 | 抽取结果 | 口径 |
|---|---|---|---|
| `wuliu/GUOO产品资费测算表【2026.7.20更新】.xlsx` | `GUOO realFBS资费试算表!C10:L24`, `GUOO FBP资费试算表!C10:M24` | Ozon 费腿覆盖 `28.1/39.3/50.55/19.1/25.8/31.4 元/kg` 与 `3.37/17.97/24.71/40.44/69.64 元/票` 的多档组合；同时给出 `PUDO` / `Courier` / `空运` / `陆空联运` / `陆运` 模式 | 币种 `CNY`；`tax=UNKNOWN` |
| `wuliu/GUOO产品资费测算表【2026.7.20更新】.xlsx` | `GUOO 增值服务!B8:K24` | `保税仓备货出口报关服务 500元/单`；`代贴条码/标签 1元/件`；`贴标签+气泡袋入库 2元/件`；`贴标签+气泡膜入库 2元/件`；`贴标签+快递袋入库 2元/件`；`贴标签+珍珠棉入库 2元/件`；`贴标签+气泡柱入库 3元/件`；`缠绕膜二次包装 3元/件` | 这是报关 / 贴标 / 包材 / 二次包装的直接原件 |
| `wuliu/GUOO产品资费测算表【2026.7.20更新】.xlsx` | `备货一件代发报价!B5:B15` | `0-90天/91-120天/121-150天/151-180天` 存储费均显示为免费，`>180天` 为 `4元`；库内操作与代发服务列为零或待定 | 这张表把仓储窗口写得很明确 |

### 5) Ural 资费、退货与保险

| 原件 | 定位 | 抽取结果 | 口径 |
|---|---|---|---|
| `wuliu/Ural国际物流报价单20260721.xlsx` | `Ozon官方伙伴Ural线上物流!A3:H24` | Ozon 线路给出 `100g` 计费单位，`Ural Express HK 18 RMB/票 + 10.5 RMB/100g`；`Ural Standard HK 18 + 5.5/100g`；大陆/OZON 新渠道给出 `3.37 + 50.5/39.3/28.1`、`25.83 + 37.1/28.1/19.1`、`17.97 + 50.5/39.3/28.1`、`40.44 + 37.1/28.1`、`24.71 + 50.5/39.3/28.1`、`69.64 + 31.4/25.8` | 币种混合 `RMB` / `CNY`；渠道模式 `PUDO` / `Courier` / `空运` / `陆运` |
| `wuliu/Ural国际物流报价单20260721.xlsx` | `ozon官方伙伴Ural增值服务!A3:H24` | `FBP入库操作费 1元/PC`；`30天内仓储免费`；`30-60天 2元/PC/月`；`60-90天 3元/PC/月`；`90-120天 4元/PC/月`；`120天以上 强制退仓/销毁`；`FBP出库操作费 6元/PC`；`退仓费 6元/PC`；`贴标/换标 1元/sku`；`拍视频 3元/sku`；`核重 1元/sku`；`检验费 5元/sku`；`拆分/合并 1元/sku`；`拆包拍照 3元/sku` | 仓储 / 包装 / 贴标 / 复核 / 退仓全都有 |
| `wuliu/Ural国际物流报价单20260721.xlsx` | `退回内地快递报价表!A3:F6` | `退运服务费`：`0-3kg 18`；`3kg-60kg 7`；`60kg-100kg 4`，备注中有 `计泡/6000`、`首重/续重` 说明 | 这是回程/退运价目 |
| `wuliu/Ural国际物流报价单20260721.xlsx` | `OZON退件业务报价单!A3:G24` | `仓储 store up 15-60天 2元/件/天；60天以上 4元/件/天`；`出库 operation fee 6.5元/订单`；`出库拦截（二次上架）2元/件`；`打托/打板 80元/托`；`盘点 2元/件`；`换包装 5元/件`；`拍视频 10元/件`；`换标 2元/件`；`贴标 2元/件`；`拍照 5元/件`；`称重 5元/件`；包材 `2/25/70` 元/件；俄境内派送普货 `25元/100g` 起，部分段 `50元/5kg` 起 | 这是退件 / 仓储 / 贴标 / 包材 / 派送的关键原件 |
| `wuliu/Ural国际物流报价单20260721.xlsx` | `Ural理赔ozon!A3:H13` | `OZON直发运输险`：申报金额 `1600元内 0.5%`，`1600-10000元 1%`，保险金额上限 `10000元`；丢件赔付上限与无保险上限分列 | 这是明确的保险费率，不是推断 |

### 6) 兴远 / 欧亚兴 / 阿尔巴特

| 原件 | 定位 | 抽取结果 | 口径 |
|---|---|---|---|
| `wuliu/兴远rFBS全渠道计算器2026-07-17.xlsx` | `兴远渠道计算!A3:E17`, `俄罗斯公式!A2:H8` | `XY Economy Extra Small 3.37 + 0.0281/克`；`XY Standard Extra Small 3.37 + 0.0393/克`；`XY Express Extra Small 3 + 0.045/克`；`XY Economy Budget 25.83 + 0.0191/1克`；`XY Standard Budget 25.83 + 0.0281/克`；`XY Express Budget 23元 + 0.033/1克`；`XY Economy Small 17.97 + 0.0281/克`；`XY Standard Small 17.97 + 0.0393/克`；`XY Express Small 16元 + 0.045/克`；`XY Economy Big 40.44 + 0.0191/1克`；`XY Standard Big 40.44 + 0.0281/克`；`XY Express Big 36元 + 0.033/1克`；`XY Premium Small 24.71 + 0.0281/克`；`XY Standard Premium Small 24.71 + 0.0393/克`；`XY Premium Big 69.64 + 0.0258/克`；`XY Standard Premium Big 69.64 + 0.0314/克` | 模式 `PUDO` / `Courier`；`计费单位` 以克 / 票为主 |
| `wuliu/兴远rFBS全渠道计算器2026-07-17.xlsx` | `兴远渠道计算!Q9:V10` | `免费存储14天，14天内未给处理方案则销毁`；`免费存储7天，8-14天存储费3元/件/天，第15天销毁`；`中国口岸/俄罗斯清关失败，监管仓退回支付1.5倍运费` | 这是退回 / 销毁 / 清关失败规则 |
| `wuliu/欧亚兴rFBS全渠道计算器2026-07-17.xlsx` | `欧亚兴合集!A3:E17`, `1111!A2:H24` | 与兴远同型费腿：`3.37/0.0281`、`25.83/0.0191`、`17.97/0.0281`、`40.44/0.0191`、`24.71/0.0281`、`69.64/0.0258`；另有 `7天 / 14天` 存储销毁与 `1.5倍` 回退说明 | 与兴远互相印证 |
| `wuliu/阿尔巴特rFBS全渠道计算器2026-07-17.xlsx` | `线上渠道合集!A3:E17`, `1111!A2:H29` | 同类费腿与模式，另有 `免费存储14天`、`8-14天存储费3元/件/天，第15天销毁`、`清关失败退回 1.5倍运费` | 与兴远/欧亚兴一致，作为交叉校验 |

## PDF / 图片原件中的运营与增值证据

### 代贴单、贴标、拆单、销毁

| 原件 | 定位 | 抽取结果 | 说明 |
|---|---|---|---|
| `wuliu/130CEL深圳机场中心仓代贴单系统操作流程（V03.24）(16).pdf` | `page 19` | `贴单 2元/单`；`拆单 3.5元/单`；`合包 5元/单`；`库存贴单 3.5元/单`；`入库 0元`；`临时查货拍照 3元/单`；`边境仓代贴 SKU 3元/单`；`配货出错最高赔偿 ≤100元（成本+运费）` | OCR / 页面文本一致 |
| `wuliu/130CEL深圳机场中心仓代贴单系统操作流程（V03.24）(16).pdf` | `page 21-22` | `退货申请` 与 `默认销毁` 的 OMS 流程说明 | 说明仓配与问题件处理方式 |
| `wuliu/130WB大粤深圳机场中心仓代贴单系统操作流程（V01.13）(2).pdf` | `page 9-10` | 同样的 `2 / 3.5 / 5 / 3.5 / 0 / 3 / 3 / ≤100` 费腿与 `WB` 退货规则 | 与 CEL manual 相互印证 |
| `wuliu/130yandex大粤深圳机场中心仓代贴单系统操作流.pdf` | `page 12` | 同样的 `2 / 3.5 / 5 / 3.5 / 0 / 3 / 3 / ≤100` 费腿 | 与 CEL / WB manual 相互印证 |
| `wuliu/1600858dfc1b43297c8c1fb7526b4a28.jpg` | `OCR line 1+` | `贴单（不拆包）0.5元`；`拆包贴单 2元`；`国内快递拒收/退回 0.1元`；`3个以上快递合单 3元`；`一拆多第二个国际面单 1元`；`1KG-3KG 仅贴单 1元`；`欧标插头 2元`；`称重 0.5元`；`大件耗材 1元`；`纸箱 2元`；`小件带电补差 1元`；`2kg-5kg 带电补差 1.5元`；`牛皮纸泡沫袋 0.5元` | 已做 OCR 脱敏，未保留手机号 |
| `wuliu/ca43db8d4405eca995547a4fc20404d0.jpg` | `OCR line 1+` | 另一张服务费图，包含 `贴单 / 拆包贴单 / 退回 / 合单 / 仅贴单 / 称重 / 纸箱 / 带电补差` 等同类费用项 | 作为第二份图片级交叉印证 |

### 仓库设置与模式证据

| 原件 | 定位 | 抽取结果 | 说明 |
|---|---|---|---|
| `wuliu/OZON-CEL仓库绑定及运输方式操作流程（V02.20）.pdf` | `page 1-17` | 仓库创建、备货时间、退货地址、配送方式、配送渠道添加流程 | 只提供仓配模式，不提供新的价格腿 |
| `wuliu/WB326005建仓流程.pdf` | `page 1`, `page 10` | `仓库编号 326005`；`58元/kg+2元/票` 与 `43元/kg+8元/票` 的 WB 费用；`退货失败免费`、`清关失败退货 42元/票` | 与 workbook 一致 |
| `wuliu/Yandex Market 仓库设置方法(东莞）(1).pdf` | `page 1-4` | 仓库设置流程，无新价格腿 | 只作模式证据 |

## 映射到 15-cost

| 15-cost leg | 当前结论 | 证据来源 |
|---|---|---|
| `product_cost` | `UNKNOWN` | 本批未审采购发票 |
| `domestic_logistics` | `PARTIAL` | `退回内地快递报价表`, `OZON退件业务报价单`, `Ural退运服务费` |
| `international_logistics` | `SUPPORTED` | `Yandex / CEL / WB / Ural / GUOO / 兴远 / 欧亚兴 / 阿尔巴特` 费腿表 |
| `packaging` | `SUPPORTED` | `Ural增值服务`, `GUOO增值服务`, 图片 OCR 服务费 |
| `warehousing` | `SUPPORTED` | `Ural/GUOO/兴远/欧亚兴/阿尔巴特` 仓储条款 |
| `customs` | `PARTIAL` | `GUOO保税仓备货出口报关 500元/单`；进口税费仍 `UNKNOWN` |
| `tax` | `UNKNOWN` | 未见税单 / 税务确认 |
| `last_mile` | `PARTIAL` | `WB / Yandex / Ural` 的到取货点 / 到门价格腿 |
| `platform_fee` | `UNKNOWN` | 未审平台结算原件 |
| `advertising` | `UNKNOWN` | 未审广告报表 |
| `return` | `SUPPORTED` | `CEL/WB/Ural/兴远/欧亚兴/阿尔巴特` 的退货、回退、销毁、拦截费 |
| `fx` | `UNKNOWN` | 未审换汇单 / 费率确认 |
| `capital_cost` | `UNKNOWN` | 未审资金占用政策 |
| `aftersales` | `SUPPORTED` | `Ural理赔ozon`、退件/换包装/拍视频/称重等 |
| `loss` | `SUPPORTED` | `销毁 / 强制退仓 / 赔付上限 / 100元上限 / 1.5倍运费` |

## 映射到 `unit-economics-inputs.md`

| 变量 | 当前建议值 | 状态 | 证据 |
|---|---|---|---|
| `main_leg_freight_cny_per_shipment` | `UNKNOWN` 直到按 SKU 选择渠道 | `partial` | 所有主运费表 |
| `units_per_shipment` | `UNKNOWN` | `unknown` | 需要 SKU / 装箱合同 |
| `cargo_insurance_cny_per_shipment` | `Ural 0.5% / 1%` 仅作候选 | `partial` | `Ural理赔ozon` |
| `storage_fee_per_sku_day` | `UNKNOWN`，但仓储窗口和价格已记录 | `partial` | `Ural/GUOO/兴远/欧亚兴/阿尔巴特` |
| `return_handling_fee_per_return` | `UNKNOWN`，但退货 / 销毁 / 拦截费已记录 | `partial` | `CEL/WB/Ural/兴远/欧亚兴/阿尔巴特` |
| `labeling_cost_per_sku` | `1-3元/件` 仅为候选区间 | `partial` | `Ural增值服务`, `GUOO增值服务`, 图片 OCR |
| `packaging_cost_per_unit` | `0.5-70元/件` 仅为候选区间 | `partial` | `Ural增值服务`, 图片 OCR |
| `brokerage_fee_per_shipment` | `500元/单` 仅对 GUOO 保税备货出口报关可见 | `partial` | `GUOO增值服务` |
| `clearance_fee_per_shipment` | `UNKNOWN` | `unknown` | 未见进口清关账单 |
| `customs_duty_rate` | `UNKNOWN` | `unknown` | 未见报关单与税单 |
| `import_vat_rate` | `UNKNOWN` | `unknown` | 未见税务意见 |
| `recoverable_import_vat_rate` | `UNKNOWN` | `unknown` | 未见税务意见 |
| `fx_rate_rub_cny` | `UNKNOWN` | `unknown` | 未见银行成交汇率单 |
| `bank_transfer_fee_rate` | `UNKNOWN` | `unknown` | 未见银行 / 支付机构报价 |

## 缺口

- `OZON` 平台结算、广告、退货退款报表未在本批提供。
- 税单、海关缴款、银行成交汇率未在本批提供。
- 每个 SKU 的装箱数量 `units_per_shipment` 仍未给出。
- 以上任何缺口都必须保留 `UNKNOWN`，不能用渠道报价猜成本结论。
