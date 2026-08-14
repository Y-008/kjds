# OPS-DY-001 抖音全量研究与运营分项 Evidence

## 1. 结论

OPS-DY-001 在 BAS-178 社媒情报工作台与分析契约之上，新增了平台专属、只读、prep-only
的抖音运营深模块 `GovernedDouyinOperations`，冻结官方 OAuth/创作者中心优先、专用浏览器
降级的源绑定，七维研究基线，输出分类法（复用 BAS-178），以及明确 synthetic 的研究问题、
内容假设、campaign 草案模板、运营 runbook 与来源中断 Adapter 解决 Loop。真实账号绑定、
平台写与任何外部写均未接入；真实执行须先账号绑定与 grant，真实写后必须读回。

- 唯一外部模块接口：`apps/control_plane/douyin_operations.py`。
- 输出类型：`SourceBinding`、`ResearchPlan`、`ContentHypothesesSet`、
  `CampaignDraftTemplatesSet`、`OperatorRunbook`、`AdapterLoop`。
- 无迁移、无公共 API、无 OpenAPI 变化、无 runtime 聚合、无新依赖、无 outbox。
- 真源复用：BAS-178 `social_analysis.py`/`social_commerce.py` 分析输出。

本结果只证明契约与 fixture 确定性，不声称任何真实抖音账号、采集或内容执行。

## 2. 冻结契约

| 字段 | 冻结值 |
|---|---|
| 模块 | `GovernedDouyinOperations` |
| 运营契约 | `kjds-douyin-operations-v1` |
| 研究计划契约 | `kjds-douyin-research-plan-v1` |
| runbook 契约 | `kjds-douyin-operator-runbook-v1` |
| Adapter Loop 契约 | `kjds-douyin-adapter-resolution-loop-v1` |
| 平台 | `douyin` |
| 首选 source rank | `official_oauth_or_creator_center` |
| 降级 source rank | `dedicated_browser` |
| 真实账号 admitted | `false` |

## 3. 研究基线、输出分类与 fixture

- 七维研究基线：`video_hooks` / `pacing` / `comment_intent` / `creator_product_match` /
  `live_short_video_funnel` / `authorized_account_metrics` / `content_campaign_baseline`。
- 输出分类（复用 BAS-178，不重复实现）：`seller_segmentation` / `comment_intent` /
  `content_structure` / `product_demand` / `calendar` / `campaign_drafts`。
- 7 条研究问题、3 条内容假设、3 个 campaign 草案模板全部标记 `FIXTURE`，`synthetic_fixture=True`。

## 4. 运营 runbook 与 Adapter 解决 Loop

- 6 步 runbook 绑定 `SetupOAuth → SetupBrowser → Baseline → Research → Campaign → Readback`；
  其中 `Readback` 冻结"写前读回、无 grant 不真实执行"。
- 5 阶段 Adapter 解决 Loop：`detect → quarantine → diagnose → retry_or_fallback → readback`，
  来源中断/漂移时隔离受影响记录、有界重试或降级专用浏览器，恢复后写前读回。

## 5. 控制边界

`zero_authority()` 全部 `false`：常规十项 + `platform_write`。`external_write_allowed`
恒 `false`；`ACCOUNT_BINDING_REQUIRED=True`、`REAL_WRITE_REQUIRES_READBACK=True`、
`REAL_ACCOUNT_ADMITTED=False`。

## 6. UNKNOWN / 外部阻断

- 官方 OAuth/创作者中心授权身份、专用浏览器账号与授权账号指标基线尚未建立。
- 真实视频钩子、节奏、评论意图、创作者/商品匹配、直播/短视频漏斗与内容 campaign 基线
  尚未由真实数据产出。

## 7. 验证

- `tests/test_douyin_operations.py` 13 passed。
- Ruff check（E/F/I/UP/B/SIM，忽略 E501）PASS。
- Secret scan PASS（1518 非忽略工作树文件、1658 历史路径）。
- 社媒 lane 聚焦回归 87 passed（active_workstream + social_commerce + social_analysis +
  xiaohongshu_operations + douyin_operations）。
