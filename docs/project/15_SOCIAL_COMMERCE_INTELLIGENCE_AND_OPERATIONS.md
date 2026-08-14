# 社媒卖家情报与运营执行系统

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-OPS-SOCIAL-001 |
| owner | 经营负责人 |
| approver | 风险负责人 |
| status | Active Preparation |
| version | 1.0 |
| last_reviewed | 2026-08-03 |
| gate | G-1–G6 |

## 目标

围绕俄罗斯跨境电商与 KJDS 软件商业化，持续收集小红书、抖音及后续平台的卖家、创作者、内容、评论、商品、趋势和技术信息，形成“发现问题→验证需求→生成内容/产品实验→执行→回读→复盘→SkillCandidate”的闭环。

“全量”定义为：对已选定并可用的来源，读取其返回的全部页、字段和时间窗口，不再人为只抽 10 条或 30 条；同时输出覆盖率、缺失字段、失败页和断点，不能把抓取中断后的部分结果冒充全量。

## 三个并行分项

| 分项 | 责任 | 当前首任务 | 产出 |
|---|---|---|---|
| 共享情报底座 | 来源选择、采集、Evidence、断点、去重、分析与 campaign 执行 | BAS-178 | 统一数据合同、Adapter、问题解决 Loop、指标与回读 |
| 小红书运营 | 卖家问题、笔记结构、评论意图、话题、用户与内容实验 | OPS-XHS-001 | 全量研究语料、内容日历、互动计划、线索与产品假设 |
| 抖音运营 | 视频钩子、内容节奏、互动、创作者指标、直播/视频实验 | OPS-DY-001 | 视频脚本、内容矩阵、互动计划、授权账号复盘与漏斗 |

三个分项共享事实、Evidence 和实验合同，但不共享账号凭据、原始客户数据或平台写权限。小红书和抖音指标分别建基线，不直接横向比较绝对播放量。

俄罗斯市场需求与热点由独立的 `RussiaMarketIntelligenceWorkspace` 负责，和本系统共享采集/Evidence/Graph/问题解决 Loop，但不把俄罗斯消费者讨论、中国卖家内容互动和真实订单混成一个指标。俄罗斯雷达产生的卖家问题可进入小红书/抖音中文选题，内容产生的咨询再回商业漏斗验证。

## 数据采集矩阵

### 公开与授权数据

| 维度 | 主要字段 | 分析用途 |
|---|---|---|
| 卖家/创作者 | 账号 ID、名称、认证、简介、公开粉丝/获赞、内容数、店铺/商品关联 | 账号分层、内容定位、卖家类型、合作候选 |
| 内容 | 标题、正文/文案、标签、话题、发布时间、类型、时长、封面/媒体引用、转写/OCR | 选题、钩子、结构、表达、节奏和素材模式 |
| 互动 | 播放/阅读、赞、藏、评、转、回复、完播/观看时长（授权可得时） | 内容质量、传播、意图和复盘 |
| 评论会话 | 评论、回复、时间、点赞、问题、反对、痛点、需求、行动意图 | 用户需求树、FAQ、回复草稿、线索资格 |
| 商品与商业 | 商品/店铺引用、价格观察、CTA、优惠、合作方式、内容商品关系 | 选品信号、卖点、内容商品匹配、竞品打法 |
| 时间序列 | 每次快照、增量、变化速度、发布频率、季节与活动窗口 | 趋势、生命周期、异常与策略变化 |
| 技术与规则 | 官方公告、OpenAPI、GitHub Release/Issue、适配器失败 | 连接器更新、运营规则和 SkillCandidate |

原始层保留源记录和哈希；规范层统一平台字段；分析层可以反复重算。用户分析聚焦公开/授权行为与表达，不凭空推断敏感身份或把单条互动永久贴标签。

### 全量采集流程

```text
目标/关键词/账号/话题种子
  -> 中俄英关键词扩展与相近问题
  -> 搜索/热点/账号/内容/评论/子评论/自有后台多入口
  -> 全游标分页 + checkpoint
  -> 原始 Evidence + source ID + observed_at + hash
  -> 平台 ID/URL/内容 hash 去重但不丢历史快照
  -> 转写/OCR/结构化
  -> 用户意图、痛点、内容模式、卖家策略与趋势分析
  -> 人工/Agent 复核后的实验和 campaign
```

采集器遇到错误时必须分类为：认证失效、验证码、限流、页面漂移、字段漂移、空结果、部分批次、内容删除或网络故障。先从断点重试，再查上游源码/Issue/Release/Fork，再切官方导出、OpenCLI、CLI/MCP、可见浏览器或人工 Evidence。禁止只写“受限，无法完成”而不寻找替代路径。

## 用户与卖家分析

### 用户需求模型

- `problem`: 选品、物流、汇率、利润、平台规则、内容、投放、库存、售后或软件效率问题；
- `intent`: 学习、比较、求方案、求工具、求服务、准备购买、售后或反对；
- `stage`: unaware/problem-aware/solution-aware/tool-aware/pilot-ready；
- `evidence`: 原评论/内容位置、时间、平台、内容 hash；
- `confidence`: 模型置信度与人工复核状态分开；
- `next_action`: 内容回答、公开回复、私信草稿、诊断邀请、产品需求或忽略。

### 卖家/创作者模型

- 经营市场、平台、品类、内容支柱、账号规模、发布频率、主要格式；
- 标题/首屏钩子、叙事结构、证据表达、CTA、评论响应与商品植入；
- 内容的中位数表现、爆款偏离、趋势速度、主题衰减与复用周期；
- 可验证的商品、店铺、服务或软件需求，不根据热度猜实际销量和利润；
- 与 KJDS 诊断、内容、软件 Pilot 和俄罗斯/Ozon 服务的匹配程度。

### 图谱关系

```text
Actor -> publishes -> Content -> mentions -> Topic/Product
Content -> receives -> Engagement/Comment -> expresses -> PainPoint/Intent
Seller -> operates -> Store/Category -> uses -> Workflow/Tool
Campaign -> produced -> Content/Interaction -> influenced -> Lead/Pilot
Insight -> supported_by -> Evidence -> captured_by -> AdapterVersion
```

图用于找共同问题、内容空白和可复用打法；模型生成的边先是 Observation，真实成交和利润仍由 KJDS 经营真源确认。

## 运营写能力

发布、更新、删除、评论、回复、点赞、收藏、关注、私信、下载和账号操作不做全局关闭。每个 campaign 一次性确认以下内容：

- 使用哪个账号、服务哪个经营主体；
- 目标人群、主题、内容和互动规则；
- 允许的动作集合、总量/频率/预算、开始/结束时间；
- 事实来源、禁用表述、品牌和知识产权边界；
- 失败、投诉、风控、负反馈和转化下限的停止条件；
- 执行后要回读的发布状态、互动、线索和业务结果。

同一 campaign 范围内不逐条重复审批。目标、账号、动作类型、预算或内容版本漂移时重新确认。验证码交给经营者完成，密钥不进入 Agent；这是保护账号和回读可信度的最低控制。

## 30 天闭环

### 第 1 周：全量基线

- 完成专用账号/浏览器、关键词、卖家、话题、品类和竞品种子表；
- 运行所有可用页和字段的全量采集，建立覆盖率、断点和失败清单；
- 对评论做问题、意图、反对和购买阶段聚类；
- 形成俄罗斯经营、利润真相、软件提效三类内容支柱及首批 campaign 草案。

### 第 2 周：结构实验

- 每个平台按内容支柱形成标题、首屏、结构、CTA 和互动策略矩阵；
- 由经营者批准 campaign 后发布和互动；
- 统一回读 1h/24h/72h/7d 指标，使用同窗口分母；
- 每次只解释实际改变的变量，不把相关性写成因果。

### 第 3 周：需求与线索

- 全量增量同步评论、回复、用户公开内容和自有后台指标；
- 对高意图问题生成公开回复、私信或诊断邀请，按 campaign 执行；
- 将需求聚类映射到软件功能、运营服务、内容选题和俄罗斯/Ozon 经营问题；
- 记录从内容到咨询、诊断、Pilot 的真实漏斗。

### 第 4 周：复盘与晋级

- 比较主题、格式、账号、发布时间、互动策略的中位数与分布；
- 保留胜出模式，停止无效或账号风险上升的打法；
- 将有效打法形成带 Evidence 的 SkillCandidate，走 Eval/Shadow/Review；
- 形成下一周期内容矩阵、产品需求、销售脚本和软件演示计划。

## 指标

| 层 | 指标 |
|---|---|
| 覆盖 | 页/记录守恒、字段覆盖、checkpoint 完整、去重率、失败页、数据新鲜度 |
| 内容 | 阅读/播放、完播、赞藏评转率、主页访问、关注、主题与格式中位数 |
| 用户 | 问题覆盖、意图分布、高意图率、重复痛点、有效回复、负反馈 |
| 卖家 | 内容频率、商品/服务关联、策略变化、工具/流程痛点、合作适配 |
| 漏斗 | 内容→评论/私信→合格咨询→诊断→Pilot→付费→现金 CM3 |
| 效率 | 单篇制作时间、单次采集/分析成本、自动化节省时长、失败恢复时间 |
| 账号 | 验证码/限流/警告、失败动作、重复动作、投诉和 kill-switch 次数 |

热度、评论和收藏是内容与需求信号，不等于销量；真实营收、现金、成本和利润继续来自订单、结算、银行与财务 Evidence。

## 商业化

1. 卖家运营诊断：交付来源覆盖、需求地图、内容/竞品模式、机会与 30 天实验。
2. 运营 Copilot：持续采集、草稿、campaign 执行、互动与复盘。
3. 授权多账号 SaaS：客户数据隔离、来源与动作审计、内容资产、线索和真实业务归因。
4. 俄罗斯跨境增长包：把国内平台验证出的痛点、内容结构和获客线索连接到 Ozon 经营诊断与软件 Pilot。

卖的是持续解决问题与提效增长能力，不是无法说明授权和来源的原始数据包。

## 运行入口

- 安装/修复：`.\scripts\manage-xiaohongshu-cli.ps1 -Mode Setup`
- 自检：`.\scripts\manage-xiaohongshu-cli.ps1 -Mode Doctor`
- 默认二维码登录：`.\scripts\manage-xiaohongshu-cli.ps1 -Mode LoginQr`
- 经营者显式选择浏览器：`.\scripts\manage-xiaohongshu-cli.ps1 -Mode LoginBrowser -CookieSource chrome`
- 运行任意读写命令：`.\scripts\manage-xiaohongshu-cli.ps1 -Mode Run -CliArgs @("search", "俄罗斯 Ozon", "--json")`
- 上游测试：`.\scripts\manage-xiaohongshu-cli.ps1 -Mode Test`

管理脚本固定 0.6.4 提交和上游锁文件，把源码、虚拟环境、浏览器和会话全部放在 Git 忽略的项目运行目录。Windows 应用控制阻止上游生成的 `xhs.exe` 时，脚本直接调用同一个 `python -m xhs_cli` 入口。二维码是默认路径；明确指定浏览器时才导入对应来源，不做隐式全浏览器扫描。搜索、全量评论/子评论、用户、热点、话题、通知、发布、删除、点赞、收藏、评论、回复和关注命令均通过 `Run` 暴露。

- 开源采用注册表：[social_commerce_source_adoption.json](registries/social_commerce_source_adoption.json)
- 平台连接器注册表：[china_platform_connectors.json](registries/china_platform_connectors.json)
- 活跃分项：[active_workstream_assignments.json](registries/active_workstream_assignments.json)
- 来源适配器：[intelligence_source_adapters.json](registries/intelligence_source_adapters.json)
- TeamAgent Loop：[loop_engineering_registry.json](registries/loop_engineering_registry.json)
- 研究证据：[20260803_SOCIAL_COMMERCE_OPEN_SOURCE_RESEARCH.md](evidence/20260803_SOCIAL_COMMERCE_OPEN_SOURCE_RESEARCH.md)
