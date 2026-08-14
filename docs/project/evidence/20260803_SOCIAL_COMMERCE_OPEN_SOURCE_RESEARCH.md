# 社媒运营与开源采集技术研究 Evidence

| 元数据 | 值 |
|---|---|
| evidence_id | KJDS-EV-SOCIAL-20260803 |
| status | Reviewed research; runtime installation separately verified |
| observed_at | 2026-08-03 |
| owner | Market Intelligence |
| authority | GitHub repository metadata/source and official platform documentation |

## 结论

最佳方案不是复制一个万能爬虫，而是把成熟项目的成功模式组合到 KJDS 深模块：官方接口和导出优先，用户指定的 `xiaohongshu-cli` 作为首个隔离运行时，OpenCLI 提供 Adapter/typed failure/site memory，`last30days` 和 `xhs-research` 提供多轮检索、扩词、去重和评分，KJDS 提供 Evidence、作用域、全量守恒、campaign、回读、Graph 和 Skill 晋级。

经营负责人要求降低不必要限制：已接入来源默认全分页、全字段、全时间窗口采集；分析默认覆盖卖家、用户、内容、评论、商品、时间和技术；发布、互动、私信、下载与账号操作保留为 campaign 能力。仍保留账号密钥不泄露、验证码不绕过、客户数据不混用和评论不冒充销量四个硬约束。

## 官方平台事实

抖音官方 OpenAPI 提供授权、个人资料、关系、内容、搜索和数据能力；用户数据能力覆盖授权账号主页、近 30 天视频及评论等数据。平台能力申请规范要求说明授权用途、保护账号/用户数据并隔离服务客户。小红书开放平台当前公开文档明确覆盖商品、订单、库存等商家接口和沙箱/正式环境。

- https://developer.open-douyin.com/docs/resource/zh-CN/dop/develop/openapi/list
- https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/open-capacity/basic-capacities/douyin/
- https://developer.open-douyin.com/docs/resource/zh-CN/dop/operation-standard/platform-capabilities/usage-spec
- https://school.xiaohongshu.com/en/open/index.html
- https://school.xiaohongshu.com/en/open/product/summary.html
- https://school.xiaohongshu.com/en/open/inventory/retrieve.html

官方商业接口不能覆盖全部公开内容研究，因此保留 CLI/浏览器/公开页/人工 Evidence 的降级路线；降级不提升 Evidence 等级，也不猜缺失字段。

## GitHub 候选核验

### 采用方法

`last30days-skill` 最新核验 Release 为 v3.18.4，MIT；可借鉴 query expansion、多源并行、去重、热度/时效评分与引用式总结，不把其第三方运行时直接变成 KJDS 真源。

- https://github.com/mvanhorn/last30days-skill/releases/tag/v3.18.4

`xhs-research` 为 MIT，组合多轮小红书检索和评分报告；采用方法，不允许其 Skill 隐式安装依赖或把报告直接晋升事实。

- https://github.com/kunhai1994/xhs-research

### 隔离运行候选

OpenCLI v1.8.6 为 Apache-2.0，支持小红书与抖音确定性命令、结构化输出、站点记忆和 typed failures；同一工具也有写命令，因此 KJDS 用 campaign capability manifest 管理，而不是依赖 Prompt 自律。

- https://github.com/jackwener/OpenCLI/releases/tag/v1.8.6
- https://github.com/jackwener/OpenCLI/blob/v1.8.6/docs/adapters/browser/xiaohongshu.md
- https://github.com/jackwener/OpenCLI/blob/v1.8.6/docs/adapters/browser/douyin.md

`xiaohongshu-mcp` v2.4.3 为 Apache-2.0，支持搜索、详情、评论和互动/发布等 MCP 能力；作为与已选 CLI 的隔离对照候选。

- https://github.com/xpzouying/xiaohongshu-mcp/releases/tag/v2.4.3

`Kuhakucai/douyin-mcp` 为 AGPL-3.0，最值得借鉴专用浏览器档案、创作者增量同步、覆盖/新鲜度、按需转写和凭据不返回 Agent；其平台风险和网络部署许可仍须单独核对。

- https://github.com/Kuhakucai/douyin-mcp

### 用户指定安装

`jackwener/xiaohongshu-cli` 当前项目版本为 0.6.4，核验提交为 `4d63f3c0c85ccd9054fa8e96d7f761aaf2507449`。它支持 search/read/comments --all/sub-comments/user/user-posts/feed/hot/topics/search-user/my-notes/notifications/unread，以及 like/favorite/comment/reply/follow/post/delete。上游说明不支持私信和媒体下载，因此这两项必须由其他 Adapter 补齐。

- https://github.com/jackwener/xiaohongshu-cli
- https://github.com/jackwener/xiaohongshu-cli/blob/4d63f3c0c85ccd9054fa8e96d7f761aaf2507449/pyproject.toml

`pyproject.toml` 声明 Apache-2.0，但核验提交根目录没有独立 LICENSE 文件。当前允许本机隔离使用和评测；把代码打包进商业产品前需上游补充 LICENSE 或提供书面澄清。

### 本机安装与问题解决记录

- 源码固定在 0.6.4 / `4d63f3c0c85ccd9054fa8e96d7f761aaf2507449`，位于 Git 忽略的 `.runtime/social-intelligence/tools`。
- 首次 `uv sync` 因 PyPI `pathspec` 下载超时；镜像重试后发现上游 editable build 漏声明 `editables`，管理脚本以固定 `hatchling==1.31.0`、`editables==0.6` 和 `pathspec==1.1.1` 提供构建 shim，不修改上游源码。
- 运行依赖随后严格按上游 `uv.lock` 重装，`xhshow` 从误取的 0.2.0 回到锁定的 0.1.9，`uv pip check` 通过。
- Windows 应用控制阻止生成的 `xhs.exe` shim，`python -m xhs_cli` 同入口可正常显示 0.6.4 版本和全部读写命令；KJDS 管理脚本已永久采用 module entrypoint。
- 上游非真实账号测试为 `112 passed, 27 skipped, 13 deselected`。其中 11 项由上游 `not smoke` 默认标记排除，2 项是 Windows ACL 不提供 Unix `0600` mode bits；签名、Cookie、解析、命令、分页与其他单元合同通过。
- Camoufox 492,370,020 字节 Release 资产首次下载中断；改为 `curl --continue-at -` 断点续传，并按 GitHub Release `sha256:386fc2f41139685f9a1a9cef0d024bc041d899c315ea538d561171b5b282e57d` 校验后安装。运行时版本为 `152.0.4-beta.28`，可执行路径已由 `camoufox.pkgman.launch_path()` 验证。
- 当前未执行账号登录或真实平台请求，`real_account_connection_status` 仍为 `no_data`；这不影响安装完成，但不能声称已抓到真实小红书数据。

`jackwener/xhs-cli` 作为 Apache-2.0 备选，只在已选 CLI 出现不可恢复缺口时比较，避免同时维护两个同类运行时。

- https://github.com/jackwener/xhs-cli

### 观察候选

RSSHub 适合 route/feed 增量模式，但 AGPL 和与现有 Authority Radar 重叠使其先观察：

- https://github.com/DIYgod/RSSHub

changedetection.io 0.55.8 为 Apache-2.0，适合官方页变更检测；先比较与现有 collector 的误报和运维成本：

- https://github.com/dgtlmoon/changedetection.io/releases/tag/0.55.8

browser-use 0.13.7 与 Stagehand server 3.7.4 都是 MIT，适合作为结构漂移恢复和 schema extraction 备选，不在当前确定性采集器有效时新增通用浏览器 Agent：

- https://github.com/browser-use/browser-use/releases/tag/0.13.7
- https://github.com/browserbase/stagehand/releases/tag/stagehand-server-v3/v3.7.4

Firecrawl v2.11.0 适合公开网页/PDF/结构化提取，AGPL 运行时与当前能力重叠，保持观察：

- https://github.com/firecrawl/firecrawl/releases/tag/v2.11.0

### 当前不进入商业运行

MediaCrawler 明确使用 NON-COMMERCIAL LEARNING LICENSE 1.1，并禁止未经同意的商业用途和大规模采集；KJDS 可研究 Adapter、断点和 Store 思路，但不能复制代码或把它部署为商业采集器。

- https://github.com/NanmiCoder/MediaCrawler
- https://github.com/NanmiCoder/MediaCrawler/blob/main/LICENSE

`yzfly/douyin-mcp-server` 已归档且重点为无水印下载/转写，只借鉴长媒体分片，不作为运行依赖：

- https://github.com/yzfly/douyin-mcp-server

Yht20927 的抖音/小红书 CLI 可借鉴草稿、失败记忆、成本与回复审核，但“行为模拟”和自动穿插点赞不作为 KJDS 真实运营策略；KJDS 可以做 campaign 互动，但不伪装随机真人行为。

- https://github.com/Yht20927/douyin-cli
- https://github.com/Yht20927/xiaohongshu-cli

## 超越开源项目的 KJDS 组合

1. 开源工具负责来源 Adapter，不拥有经营真相。
2. 所有页和字段有 `source_total = accepted + quarantined` 守恒与 checkpoint。
3. 原始、规范、分析、实验、动作和业务结果六层分离，可重算不可篡改。
4. 用户、内容、评论、卖家、商品、时间和技术事件进入同一时序 Graph。
5. 一次 campaign 授权覆盖重复动作，保留目标、预算、停止条件和回读，不做每条审批。
6. 失败后自动搜索官方文档、源码、Issue、Release、Fork 和替代 Adapter，形成 SkillCandidate，而不是直接结束任务。
7. 有效模式必须由真实曝光、互动、咨询、Pilot、付费和现金 CM3 逐层验证，热度不替代经营结果。

## UNKNOWN

- 小红书和抖音真实账号尚未在本切片登录，真实字段覆盖、历史深度和账号风控表现未知。
- `xiaohongshu-cli` 商业再分发的 LICENSE 文件缺口待澄清。
- 私信、媒体下载、直播和更深店铺数据需单独 Adapter；不能把 CLI 未实现写成已完成。
- 真实发布、互动、线索和转化基线需运营 campaign 运行后建立。
