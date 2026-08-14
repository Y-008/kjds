# BAS-207 自动经营、利润证据与货源回链工程证据

## 2026-08-10 BAS-219A 主线选择性集成

隔离分支 `feat/automated-commerce-linkback-20260808` 在复核 HEAD
`5078b9fdaf781863f6f0700bd90abb3bdfad24c2` 保持 clean；本次没有 merge/rebase 整条分支，
而是在主线控制提交 `701f7666b610dd92a49efcc82046856eb1f056c3` 所登记的 exact write
set 内选择性接入：

- `AutomatedCommerceLoop` 深模块及其 exact-scope、目录、分页、计数、snapshot 和只读控制验证；
- 现有 Store Profile 中默认关闭的总开关、playbook 开关、请求模式、额度与有效期合同；
- 既有 Scoped Sourcing Intelligence 的 RFQ package/dispatch/quote readiness 只读回链；
- 需求追溯矩阵拆分为 `TRACE-005A=ADOPTED_ENGINEERING`（主线核心）与
  `TRACE-005B=ISOLATED_IMPLEMENTED`（隔离 runtime/API/Web）。

BAS-219A 明确不修改 `runtime.py`、Router、API/OpenAPI、Web、数据库、迁移或 G-1，也不
创建外部联系、正式报价、采购、付款、Approval 或 Permit。隔离 runtime/API/Web 只有在
BAS-186 释放共享 seam 后，才能由 BAS-219B 独立 CAS 和回滚。现有
`SupplierQuoteAuthorityService` / `SourcingIntakeService` 继续作为报价原件、RFQ package、
dispatch lineage 与非上传者复核的唯一权威；acknowledgement、clarification、alternative、
platform notice、`latest_reply_unknown` 以及无法无损表达的多阶梯报价不会被截取或晋升为
supplier-confirmed quote、SupplierOffer 或利润事实。

### BAS-219A 失败关闭增量

- exact scope 失败时，目录、RFQ 和 AI Listing 零读取/零写入；
- Catalog 与 Sourcing projection 的 contract、scope、as-of、snapshot、分页、计数守恒、
  reason code 和只读控制信封任一漂移时返回通用 blocked，不回显上游 canary；
- 非有限 Decimal、成本 Evidence 缺失或 malformed ProfitScenario 均保持
  `awaiting_evidence`，金额隐藏且推荐计数为 0；
- `partial/no_data/blocked` 不会把三家已接受报价或外部联系伪装成 ready；RFQ 草稿可以在
  partial 状态下如实显示，但不等于已发送、已回复或正式报价；
- `start()` 仅允许 `manual_each_action` 的既有内部 dry-run，监督批次和自治请求在写入前拒绝。

### 前沿技术 freshness

`frontier_review=checked_no_change`，检查日 `2026-08-10`，适用范围为自动化策略评估与耐久
编排。OPA 官方仍提供 bundle discovery/signing/persistence 与 decision log，但它只适合作为
隔离 shadow/policy evaluator；decision log 输入需屏蔽敏感字段，OPA 不签发 KJDS Permit，
本切片不安装依赖。Temporal 官方项目仍持续发布，适合后续长周期 RFQ/结算/退款观察窗
Pilot，但不能替代 OperatingTask/Event、Outbox 或业务事实权威；BAS-219A 不接 runtime，
因此保持 `pilot_later`。注册表采用决定无变化，本次不虚假刷新 `reviewed_on`，也无需新增 ADR。
官方来源：

- https://www.openpolicyagent.org/docs/management-bundles
- https://www.openpolicyagent.org/docs/management-decision-logs
- https://github.com/open-policy-agent/opa/releases
- https://github.com/temporalio/temporal/releases

### 真实经营状态

私密启动包没有复制或提交。2026-08-10 合规清单只形成条件性法规 Observation：精确
TN VED、OKPD2、许可文件和 Честный ЗНАК 结论仍 `unknown`；不得写成“无需”。启动包仍仅
`structurally_valid`，只有 g0 可人工复核，其余 7 区段 `awaiting_inputs`，
`automatic_import=false`、`formal_fact_promoted=false`。本切片不修改 supplier-quotes、
candidate-research、SKU Passport，也不生成报价、28 天数据、利润、合规或可售结论。

### BAS-219A 工程验证

在主线 `feature/batch-opportunity-mining-059`、控制基线
`701f7666b610dd92a49efcc82046856eb1f056c3` 上执行：

```text
pytest: 129 passed
Ruff: All checks passed
registry JSON: requirements traceability + store strategy parse passed
secret scan: 1456 non-ignored worktree files + 1464 historical paths passed
document links: 7 changed entry/decision/evidence documents, missing=0
git diff --check: passed
```

该 129 项覆盖 Automated Commerce、Store Strategy、Requirements Traceability、active assignment、
Scoped Sourcing Intelligence、Supplier RFQ/dispatch、Sourcing 与 frontier registry。没有运行 DB、
迁移或 G-1，也没有借用 BAS-186 的 runtime/0098/Alembic 租约。测试产生的忽略目录
`.runtime/bas219a-*` 和本机 `__pycache__` 是可再生产物，不属于 exact write set；本记录不声称
已清理它们。工程测试通过不改变本文件记录的真实经营 `BLOCKED_EVIDENCE`。

## 结论

本切片在既有 KJDS 真源与治理链上增加了一个只做编排和投影的
`AutomatedCommerceLoop`，并把渐进式自动化偏好收口到现有 exact-scope Store Profile。
没有新增 ERP、事实账、任务账、授权账、状态机、数据库表或迁移。

工程状态为 `DONE_ENGINEERING_PENDING_INDEPENDENT_REVIEW`。它不证明真实 RFQ 已回复、正式
报价已取得、首个 SKU 已盈利、真实 Ozon Listing 已发布、供应商已下单或平台写权限已放行。

## 实现范围

1. `POST /v1/automated-commerce/runs` 从现有 Browser Capture submission 的精确变体启动
   既有 `AiListingPipeline`，固定 `internal_dry_run`，并在既有证据/审核/批准门暂停。
2. `GET /v1/automated-commerce/workspace` 按 exact tenant/entity/store/as-of 组合现有
   Marketplace Catalog、Product、ListingDraft、SupplierOffer、ProfitScenario 与 AI Listing
   run；支持 Ozon 商品 URL、数字 marketplace SKU 和 seller offer ID 精确反查。
3. Ozon 平台链接只由已观察的 6–20 位数字 marketplace SKU 生成；没有目录回读时 seller
   offer ID 与 Listing URL 均保持空，不使用 KJDS SKU 或 SupplierOffer ID 猜造平台身份。
4. 货源购买链接只来自正式 SupplierOffer 的 source URL；供应商店铺链接只来自已保存的明确
   `supplier_store_url/store_url/shop_url` 字段。卖家可自行打开，不自动联系、采购或付款。
5. 利润 verdict 只解释既有 Decimal ProfitScenario：全成本证据完整且 CM3>0 才
   `recommended`，完整且 CM3<=0 为 `not_recommended`，其余为 `awaiting_evidence`；AI 不得
   覆盖该结论。
6. Store Profile 增加默认关闭的门店总开关、默认关闭的单打法开关、逐动作请求模式、每日
   动作数/预算/单价/调价幅度/数量/最大损失/有效期上限。总开关不隐式开启全部打法。
7. 投影并列返回 `requested_mode`、`effective_mode`、`grant_ready`、
   `runtime_execution_enabled`。当前监督批次和 policy-bound 自治运行时仍为 `planned`；偏好
   和额度不是 Grant，所有有效模式保持 `manual_each_action`，外写保持 false。
8. 工作台按 canonical Product 复用现有 `ScopedSourcingIntelligenceWorkspace`，并列投影
   RFQ package、dispatch proof、quote/accepted supplier readiness、下一补证动作和上游
   Evidence authority。查询沿游标读取全部页后再映射；重复 work item、游标循环、无效结构
   或跨页 contract/scope/as-of/upstream authority 漂移均失败关闭。该投影始终只读，
   `external_contact_allowed=false`。
9. 现有 `/commerce-os` 页面新增只读自动经营面板，不新建前端状态机或 ERP 页面：可按 Ozon
   URL、Marketplace SKU 或 seller offer ID 查询，并在同一作用域展示 RFQ/dispatch/报价就绪度、
   确定性利润 verdict、Ozon→SupplierOffer 回链、下一人工动作和所有执行锁。缺字段显示
   `unknown`，不把空数组或未读到的聊天当作“无回复”。RFQ 下一动作由后端投影返回
   `next_workspace=/#sourcing`，前端回到既有 `SupplierQuoteWorkspace`，因此冻结询价包、
   发送证明、独立复核和报价证据仍在同一真源工作区完成。

## 复用的权威与边界

- 商品、报价、利润、Listing 与目录继续由现有 Product、SupplierOffer、ProfitScenario、
  ListingDraft、Scoped Marketplace Catalog 持有。
- 自动化真正放行继续由现有 Causal Policy、Independent Approval、ExecutionPlan、一次性
  Permit、Transactional Outbox、Authoritative Readback、Kill Switch 与 Compensation 持有。
- 经营待办继续进入现有 OperatingTask/OperationsQueue；本切片没有创建第二任务队列。
- `.runtime/real-sku-startup` 私密启动包未加入 Git，也未晋升任何正式事实。

## 验证

在 `D:\KJDS\kjds-auto-commerce`、分支
`feat/automated-commerce-linkback-20260808` 运行：

```text
uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local \
  tests/test_store_category_strategy.py tests/test_automated_commerce.py
18 passed

uv run ruff check apps/control_plane/automated_commerce.py \
  apps/control_plane/routers/automated_commerce.py \
  apps/control_plane/api_contracts.py apps/control_plane/store_category_strategy.py \
  tests/test_automated_commerce.py tests/test_store_category_strategy.py
All checks passed

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-openapi \
  tests/test_api_contract.py::test_openapi_v1_snapshot_matches_runtime_contract
1 passed

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-rfq-slice \
  tests/test_automated_commerce.py tests/test_store_category_strategy.py \
  tests/test_supplier_rfq.py tests/test_supplier_rfq_dispatch.py \
  tests/test_sourcing.py tests/test_scoped_sourcing_intelligence.py
54 passed

uv run ruff check apps/control_plane/automated_commerce.py \
  apps/control_plane/runtime.py tests/test_automated_commerce.py
All checks passed

cd web
npm test
150 passed

npm run build
Next.js production build passed; /commerce-os is present

npm audit --omit=dev --json
0 vulnerabilities (nanoid transitive dependency updated 3.3.16 → 3.3.18)

Browser UX smoke (local-only fixture, never committed)
- exact lookup `2216781923` displayed `marketplace_sku`, Catalog hit 1, RFQ `partial`,
  three accepted quotes `0`, next action preserved, Ozon/1688 links visible;
- 390×844 viewport: automated panel and search visible, three link actions visible,
  `document.documentElement.scrollWidth=375 < innerWidth=390` (no horizontal overflow);
- local mock and fixture `.env.local` removed after verification.
```

OpenAPI snapshot 的上述结果是在导出脚本使用一次性假数据库/密钥占位环境、且保留本分支
原有策略包字节的验证结果。随后直接重跑时，仓库基线的 Windows 文本换行使既有
`seller_strategy_packs` 原始 SHA256 检查先于收集阶段失败；该漂移未由本切片修改，不能把它
改写成自动化切片通过全量 API 门禁。

全量 `scripts/verify-g1.ps1` 已完成清理，但 generic pytest 报告为
`25 failed, 2637 passed, 1 skipped, 105 errors`。失败/错误集中在当前分支没有带入的私密
`output/browser_capture`、`wuliu` 输入、旧的 0096 closed-loop harness，以及既有 outbox/
策略包字节漂移；本切片聚焦测试、ruff、secret scan 和迁移/数值/启动包合同阶段已通过。
完整结果保存在忽略的 `.runtime/G1_VERIFICATION.json` 与 `.runtime/g1-rerun.log`，不作为
本切片的绿色全量证明。

## 集成状态

实现提交 `4dd22eb1dd9e9201b33d75dd5f97ad22da1efb23` 所在分支与当前主工作分支
`feature/batch-opportunity-mining-059` 只在 `3ba5f3a` 汇合；两侧仍各自有大量独有提交，主
工作树当前 HEAD 为 `5f7f071` 且有其他用户/并行任务的修改与未跟踪文件。当前不做盲目 rebase/merge，也不向旧 `origin/main`
开一个会带入大量无关历史的 PR；
由集成负责人基于汇合点选择性接入并重新跑适配后的 G-1。

在不写入主工作树的 `git apply --check --3way` 预检中，自动经营代码、运行时、API 合同、
策略注册表和测试文件可以直接应用；`03_REMAINING_WORK_AND_PARALLEL_PLAN.md` 与
`MASTER_SPEC.md` 的文档上下文存在冲突，需要集成负责人按主线最新内容手工合并。这次检查
没有改变主工作树或本分支状态。

## 2026-08-09 真实输入复验

在主工作区读取私密启动包（未复制到本分支、未改写 Git 文件）并运行：

```text
uv run python scripts/validate_startup_package.py .runtime/real-sku-startup --require-review-ready
contract=kjds-startup-package-v4
status=structurally_valid
exit=3 (awaiting real inputs)
ready_sections=g0-ozon-api-identities.csv
blocked_sections=7 other required sections
automatic_import=false
formal_fact_promoted=false
```

三候选仍只有 15 条模板指标，其中每个候选的 `demand_signal`、`competition_gap` 和
`return_risk` 没有可晋升值；当前 Ozon 观察是账户级 28 天零订单，不是候选类目需求。固定
六家供应商的 `message_sent=false`、`formal_quote_received=false`，`supplier-quotes.csv`
仍为草稿空报价。1688 已读到的服务器历史只含平台等待通知/自动消息，或被 CAPTCHA 阻断，
没有新的人工正式报价。因而本次没有写入 candidate-research、supplier-quotes、Passport、
ProfitScenario 或任何 external write。

目标测试覆盖：正/非正/缺证据利润、Ozon URL/数字 SKU/offer 精确反查、跨来源和未绑定失败
关闭、同 Product 多 Listing 不串线、无目录回读不猜 seller offer、RFQ 权威按 Product 精确
映射、跨页读取、投影失败关闭、权威哈希回传、供应商联系保持关闭、内部 dry-run 不产生采购
或付款、总开关关闭、动作开关关闭、运行时未开放、授权未就绪、额度规范化与非法额度拒绝；
RFQ projection 还断言下一工作区固定回到既有 `/#sourcing`，没有新增发送接口。

## 仍需真实输入

- RU-001/RU-002 固定六家供应商的真实书面 RFQ 回复及独立接受；
- 当前 Ozon Listing 的精确目录回读与 Product 绑定；
- 完整十五项成本、汇率、物流、退货、平台费用与有效 Evidence；
- 真实俄语审核、Approval/Permit/Executor/Readback 验收；
- 监督批次/自治模式的独立 Eval、Grant、Kill Switch 和 Compensation 生产演练。

在这些输入和 Gate 完成前，不得把本工程切片描述为“已经自动上架、自动采购、正式盈利或
全面自动驾驶”。
