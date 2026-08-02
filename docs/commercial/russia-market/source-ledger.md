# Source Ledger

**截点**: 2026-08-02  
**规则**: 只收一手来源，优先 Ozon 官方、俄罗斯政府/海关/税务/认证官方、以及中国海关/商务官方。  
**可信等级**:

- `A` = 发行机构官方当前页面，且直接说明本任务所需规则
- `B` = 发行机构官方页面，但属于索引页、标签页、翻译页、或结论需要再拆一层才能落地
- `C` = 发行机构官方页面，但证据只覆盖边界、历史或间接事实

| ID | URL | 机构 | 发布日 | 访问日 | 适用范围 | 可信等级 | 备注 |
|---|---|---|---|---|---|---|---|
| SL-01 | https://seller.ozon.ru/en/ | Ozon | live / unstated | 2026-08-02 | Ozon 卖家注册入口、整体 onboarding | A | 说明可注册、上传商品并开始销售 |
| SL-02 | https://docs.ozon.ru/global/en/accounting/receiving-payments/settlements/?country=TR | Ozon | live / unstated | 2026-08-02 | 结算、打款、币种、销售报表、费用口径 | A | 直接给出 bank transfer、seller country 和结算报表口径 |
| SL-03 | https://docs.ozon.ru/global/en/tags/mandatory-%D1%81haracteristics/ | Ozon | live / unstated | 2026-08-02 | 必备资料索引：Documents for Selling、Brand Certificates、Product Quality Certificates、Safety Data Sheet | B | 是索引页，但能直接指向必须准备的证据类型 |
| SL-04 | https://docs.ozon.ru/global/en/products/requirements/product-info/product-description/ | Ozon | live / unstated | 2026-08-02 | 商品页内容、年龄限制、外国代理声明、证书/文档引用 | A | 直接影响 listing 合规和展示文案 |
| SL-05 | https://docs.ozon.ru/global/en/brand-account/ | Ozon | live / unstated | 2026-08-02 | 品牌代表、品牌销售与评论跟踪、受限销售商品索引 | B | 适合核实品牌/授权路径 |
| SL-06 | https://docs.ozon.ru/global/en/tags/video/ | Ozon | live / unstated | 2026-08-02 | 内容与视频规则索引、费率/配送/退货/合同相关索引 | B | 用于核实内容政策和费用/履约文档入口 |
| SL-07 | https://docs.ozon.ru/global/en/products/requirements/media/video-requirements/?country=CN | Ozon | live / unstated | 2026-08-02 | 视频内容禁限项 | A | 明确列出禁止展示的内容类型 |
| SL-08 | https://docs.ozon.ru/global/en/tags/brand-certificates/ | Ozon | live / unstated | 2026-08-02 | 品牌证书、产品质量证明、SDS、内容政策与客户沟通规则 | B | 证书类资料索引 |
| SL-09 | https://xn--80ajghhoc2aj1c8b.xn--p1ai/ | CRPT / Честный ЗНАК | live / unstated | 2026-08-02 | 国家商品数字标识系统总入口 | A | 识别适用类目与系统入口 |
| SL-10 | https://xn--80ajghhoc2aj1c8b.xn--p1ai/about-marking/ | CRPT / Честный ЗНАК | live / unstated | 2026-08-02 | 标识系统工作原理、可追溯性、参与者责任 | A | 说明每件商品都要可追踪 |
| SL-11 | https://eec.eaeunion.org/en/news/eaes-rasshiryaet-perechen-tovarov-legkoy-promyshlennosti-podlezhashchikh-markirovke-sredstvami-ident/ | EEC | 2024 / live page | 2026-08-02 | EAEU 轻工商品强制标识扩展 | A | 可直接用来判断服装等品类的标识风险 |
| SL-12 | https://eec.eaeunion.org/en/news/do-1-sentyabrya-2023-goda-uproshcheny-pravila-markirovki-tovarov-znakom-eas-/ | EEC | 2023 / live page | 2026-08-02 | EAC 标志和消费者信息标识原则 | B | 过渡性新闻，但对“销售前需标识”有帮助 |
| SL-13 | https://eec.eaeunion.org/en/news/utverzhdeny-obshchie-podkhody-k-zashchite-prav-potrebiteley-v-elektronnoy-torgovle-eaes/ | EEC | live / unstated | 2026-08-02 | 电子商务消费者权益的共同做法 | A | 退货、退款、争议处理时限的跨境参照 |
| SL-14 | https://cgon.rospotrebnadzor.ru/naseleniyu/gramotnyy-potrebitel/distancionnaya-torgovlya-v-voprosax-i-otvetax/ | Rospotrebnadzor | live / unstated | 2026-08-02 | 远程销售定义、消费者端权利与义务 | A | 适合解释俄罗斯远程销售/网购规则 |
| SL-15 | https://cgon.rospotrebnadzor.ru/naseleniyu/gramotnyy-potrebitel/pamyatka-dlya-potrebiteley-pri-pokupke-v-internet-magazine/ | Rospotrebnadzor | live / unstated | 2026-08-02 | 网购退货/拒收消费者指引 | A | 支持 7 日退货等消费者保护边界 |
| SL-16 | https://pd.rkn.gov.ru/docs/242-FZ_11.docx | Roskomnadzor | 242-FZ / official text | 2026-08-02 | 个人数据本地存储要求 | A | 明确在线收集个人数据时需使用位于俄罗斯境内的数据库 |
| SL-17 | https://www.nalog.gov.ru/eng/inn/ | FTS of Russia | live / unstated | 2026-08-02 | 税务登记号 INN 规则 | A | 对税务身份、开户注册和后续申报很关键 |
| SL-18 | https://www.nalog.gov.ru/html/sites/www.eng.nalog.ru/Tax%20Code%20Part%20Two.pdf | FTS of Russia | codified law / PDF | 2026-08-02 | 《俄罗斯税法典》第二部分，含进口货物税务处理 | A | 用于进口 VAT、税务边界和后续律师核验 |
| SL-19 | https://eng.customs.gov.ru/folder/87002 | Federal Customs Service of Russia | live / unstated | 2026-08-02 | 海关收入与税费管理职责 | B | 证明海关对税费征收/管理有官方职权 |
| SL-20 | https://eng.customs.gov.ru/folder/86997 | Federal Customs Service of Russia | live / unstated | 2026-08-02 | 货物通关规则索引 | B | 用作海关规则总入口 |
| SL-21 | https://eng.customs.gov.ru/activities/individuals/movement/rules-for-moving-goods/uniform-rates-of-customs-duties%2C-taxes%2C-and-also-categories-of-goods-for-personal-use-concerning-which-customs-duties%2C-the-taxes-levied-in-the-form-of-aggregate-customs-payment-are-subject-to-payment | Federal Customs Service of Russia | live / unstated | 2026-08-02 | 关税、税费、类别和个人自用边界 | B | 主要用于确认进口税费框架 |
| SL-22 | https://english.customs.gov.cn/topic/customs16/service2/info196479.htm | China Customs | live / unstated | 2026-08-02 | 中俄海关合作概述 | B | 只做跨境合规与通关协作背景，不做结论依据 |
| SL-23 | https://english.mofcom.gov.cn/News/PressConference/art/2024/art_7e1282d1fc37494aaa51bc84bb9b8014.html | MOFCOM | 2024-01-18 | 2026-08-02 | 中俄跨境电商和经贸合作背景 | B | 说明中俄跨境电商在商务口径下是被持续关注的业务形态 |
| SL-24 | https://english.mofcom.gov.cn/News/PressConference/art/2021/art_d0c2dfa010b54c3b83e59d483d9b05a8.html | MOFCOM | 2021-12-16 | 2026-08-02 | 中国对俄跨境电商与海外仓合作背景 | C | 旧一些，但能证明对俄跨境电商合作长期存在 |

## 读法

- 如果来源是 `A`，可以直接进入门槛判断。
- 如果来源是 `B`，只能当作支持证据，不能单独作为最终结论。
- 如果来源是 `C`，只用于背景和趋势，不用于硬性放行。
