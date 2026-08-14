# OPS-XHS-001 小红书全量研究与运营分项 Evidence

## 1. 结论

OPS-XHS-001 在 BAS-178 社媒情报工作台与分析契约之上，新增了平台专属、只读、prep-only
的小红书运营深模块 `GovernedXiaohongshuOperations`，冻结 `xiaohongshu-cli` 0.6.4 固定
checkout 源绑定、七维研究基线、输出分类法（复用 BAS-178 分析输出）与明确 synthetic 的
研究问题、内容假设、campaign 草案模板和运营 runbook。真实账号绑定、平台写与任何外部写
均未接入；真实执行须先账号绑定与 grant，真实写后必须读回。

- 唯一外部模块接口：`apps/control_plane/xiaohongshu_operations.py`。
- 输出类型：`SourceBinding`、`ResearchPlan`、`ContentHypothesesSet`、
  `CampaignDraftTemplatesSet`、`OperatorRunbook`。
- 无迁移、无公共 API、无 OpenAPI 变化、无 runtime 聚合、无新依赖、无 outbox。
- 真源复用：BAS-178 `social_analysis.py`/`social_commerce.py` 分析输出、
  `scripts/manage-xiaohongshu-cli.ps1` 固定 checkout 与 Camoufox 运行时。

本结果只证明契约与 fixture 确定性，不声称任何真实小红书账号、采集或内容执行。

## 2. 冻结契约

| 字段 | 冻结值 |
|---|---|
| 模块 | `GovernedXiaohongshuOperations` |
| 运营契约 | `kjds-xiaohongshu-operations-v1` |
| 研究计划契约 | `kjds-xiaohongshu-research-plan-v1` |
| runbook 契约 | `kjds-xiaohongshu-operator-runbook-v1` |
| 平台 | `xiaohongshu` |
| CLI 版本 | `0.6.4` |
| CLI pinned commit | `4d63f3c0c85ccd9054fa8e96d7f761aaf2507449` |
| source rank | `operator_cli_or_browser` |
| 真实账号 admitted | `false` |

## 3. 研究基线、输出分类与 fixture

- 七维研究基线：`search` / `notes` / `comments_and_sub_comments` / `users` / `topics` /
  `notifications` / `owned_content`。
- 输出分类（复用 BAS-178，不重复实现）：`seller_segmentation` / `comment_intent` /
  `content_structure` / `product_demand` / `calendar` / `campaign_drafts`。
- 7 条研究问题、3 条内容假设、3 个 campaign 草案模板全部标记 `FIXTURE`，`synthetic_fixture=True`，
  不冒充真实平台数据。

## 4. 运营 runbook（6 步，绑定 6 种 CLI 模式）

`Setup → Doctor → LoginQr → LoginBrowser → Run → Test`，每步含动作与读回条件；其中
`Test` 冻结"写前必须读回、无 grant 不真实执行"。

## 5. 控制边界

`zero_authority()` 全部 `false`：常规十项 + `platform_write`。`external_write_allowed`
恒 `false`；`ACCOUNT_BINDING_REQUIRED=True`、`REAL_WRITE_REQUIRES_READBACK=True`、
`REAL_ACCOUNT_ADMITTED=False`。

## 6. UNKNOWN / 外部阻断

- 专用二维码账号、搜索/笔记/评论/用户/话题/通知/自有内容基线尚未建立（需真实账号绑定与 grant）。
- 真实卖家分群、评论意图、内容结构、产品需求、日历与 campaign 草案尚未由真实数据产出。

## 7. 验证

- `tests/test_xiaohongshu_operations.py` 11 passed。
- Ruff check（E/F/I/UP/B/SIM，忽略 E501）PASS。
- Secret scan PASS（1515 非忽略工作树文件、1655 历史路径）。
- 社媒 lane 聚焦回归 78 passed（active_workstream + social_commerce + social_analysis +
  xiaohongshu_cli_harness_contract + xiaohongshu_operations）。
