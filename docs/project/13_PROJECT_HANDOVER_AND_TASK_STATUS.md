# KJDS 项目交接与任务状态总览

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-HANDOVER-001 |
| status | Active |
| snapshot_at | 2026-07-20（Ozon Data / Seller 只读复验后） |
| repository | `D:\KJDS\kjds` |
| branch / HEAD | `main` / `1f1d1e6ca75445756570ab14385a5a9a8da8ca14` |
| canonical_task_source | [03_REMAINING_WORK_AND_PARALLEL_PLAN.md](03_REMAINING_WORK_AND_PARALLEL_PLAN.md) v7.9 |
| master_spec | [MASTER_SPEC.md](MASTER_SPEC.md) v7.4 |
| last_verified_gate | G-1 `PASS` |

> 本文件是交接快照，不是第二份任务真源。任务状态、验收和依赖以后只修改 `03_REMAINING_WORK_AND_PARALLEL_PLAN.md`，再同步刷新本文件。任务工作簿仍有 108 项候选库存；其中 88 项已进入当前执行账，未进入当前 P0 的 20 项不得绕过优先级直接开工。

## 一、当前结论

KJDS 已形成可运行、可审计、可恢复的 AI 原生跨境经营控制面，但还不是已经打通真实经营闭环的“大卖 ERP”。系统工程门禁已通过；真实经营仍被 Ozon 类目需求原件、最小权限身份、三个候选 SKU、三报价/样品、Passport、真实成本账单、结算—银行—FX 证据和独立人工复核阻断。

开源 ERP 的当前最佳方案不是替换 KJDS，而是让 ERPNext 作为隔离侧车 PoC：KJDS 继续拥有商品决策、Evidence、利润、Gate、审批和因果实验真相；ERP 只接收经批准的 Item、采购和财务草稿投影，禁止双写。

## 二、验证基线

| 项目 | 结果 |
|---|---|
| Alembic | `20260720_0038` |
| Python | 317/317 通过；1 条第三方 Starlette 弃用警告 |
| Web | 19/19 通过 |
| Next.js build | 通过 |
| Ruff | 通过 |
| G-1 | `PASS`，`2026-07-20T06:35:03.0648792Z`–`2026-07-20T06:37:00.9618381Z` |
| BAS-076 | `actual_cost_authority_gate=true` |
| BAS-077 | `actual_cost_authority_catalog=true`；非技术复核工作台可用 |
| PostgreSQL 隔离恢复 | 通过，SHA-256 `b45228f5486b489c5dd7e7a79b7f488010b3b896fdfae919bf2afd99918e8fb1` |
| 清理 | processes/database/files 全部完成 |

第一次直接运行全量 pytest 时，Windows 系统临时目录 `pytest-of-Lunar` 拒绝访问；改用仓库 `.runtime` 隔离临时目录后 317 项全部通过。该问题属于机器环境权限，不是代码测试失败。

## 三、任务统计

| 状态 | 数量 | 交接含义 |
|---|---:|---|
| `DONE` | 34 | 已完成并通过当前验收 |
| `DONE_ENGINEERING` | 38 | 工程实现完成；仍不得冒充真实经营输入已完成 |
| `DONE_FIRST_BATCH` | 1 | 当前范围首批完成，后续按触发条件扩展 |
| `DONE_RESEARCH` | 1 | 研究结论完成，实施受独立 PoC 门约束 |
| `DONE_PENDING_REVIEW` | 1 | 已存证，等待另一真实身份复核 |
| `PARTIAL_BLOCKED` | 6 | 部分完成，缺真实账户/文件/人员/业务数据 |
| `BLOCKED_CONFIG` | 1 | 工程合同完成，缺部署配置和连续运行验收 |
| `BLOCKED` | 5 | 前置真实输入未满足，不能继续放行 |
| `NEEDS_REVIEW` | 1 | 已形成候选清单，等待责任人批准 |
| **合计** | **88** | 当前执行账全部任务 |

## 四、下一位执行者先做什么

1. 不再新增 ERP、Agent、模型或工作流模块；优先解除 `SKU-000` 与 `OZN-003`。
2. 由账户主体按 [SKU-000 / OZN-003 账户负责人决策包](evidence/20260720_SKU_000_OZN_003_OWNER_DECISION_PACKET.md) 亲自决定 Ozon Data 要约与个人信息条件；取得类目级至少 28 天真实需求报告原件，固化哈希，再由不同身份接受。Seller 销售漏斗、已有 SKU 的 `product-queries` 和第三方工具不得替代。
3. 建立 Ozon 专用最小权限只读身份，完成调用方盘点、Owner、撤销路径和独立复核；不得在仓库、日志或交接文档放密钥。
4. 在需求报告放行后确认三个真实候选，逐 SKU 完成五指标证据、三家报价、重量尺寸/包装实测、三类 Passport 和样品生命周期。
5. 对首个真实 SKU 逐项上传供应商、物流、Ozon、税关、FX 实际原件；由非上传者按 BAS-076 接受，才能显示 `actual`。
6. 由另一财务身份复核 BAS-068 的 Ozon 计提原件，再补结算、银行到账和 FX 三腿；未匹配前不得宣称真实利润或自动入账。
7. 用两个真实 Supabase 用户、真实 MFA 设备完成 BAS-026；用真实运行配置完成 BAS-040 至少三次连续调度结果 0。

## 五、待完成与阻塞任务明细

| ID | Gate | 状态 | Owner | 还缺什么 | 下一动作 |
|---|---|---|---|---|---|
| BAS-026 | G2 | PARTIAL_BLOCKED | 工程+经营 | 两个真实用户、MFA 设备、撤销/恢复和经营演练 | 按 `09_SUPABASE_DUAL_CONTROL_ACCEPTANCE.md` 实机验收 |
| BAS-040 | G0 | BLOCKED_CONFIG | 工程+运维 | 任务可见 `.env`、计划任务定义和三次连续成功历史 | 先 `Plan`，经批准后 `Install`，最后 `Audit` |
| BAS-068 | G4 | DONE_PENDING_REVIEW | 工程+财务 | 不同身份对真实 Ozon 计提原件接受/拒绝 | 使用财务只读交接包复核，不直接入账 |
| SKU-000 | G0 | PARTIAL_BLOCKED | 账户+商品 | Ozon 类目级 28 天真实需求报告原件；Ozon Data 条款尚未由本人决定 | 按 Owner Decision Packet 决定条款、导出、哈希、上传和独立复核 |
| SKU-001 | G0 | BLOCKED | 商品负责人 | 三个真实候选及五指标证据 | 只能在 SKU-000 放行后确认 |
| SKU-002 | G1 | BLOCKED | 商品/合规 | 每 SKU 商品/合规/质量 Passport | 基于真实候选和原件逐项审核 |
| SKU-003 | G1 | PARTIAL_BLOCKED | 商品/供应链 | 每 SKU 三报价、样品、重量尺寸、包装、物流实测 | 完成三报价→样品订单→检验→金样 |
| OZN-001 | G0 | PARTIAL_BLOCKED | 经营负责人 | 脱敏账户、合同、权限与收款路径证据 | 只读核验后存证并指定 Owner |
| OZN-002 | G1 | PARTIAL_BLOCKED | 工程+经营 | 订单/费用/退货/结算真实字段与样本 | 逐类型建立官方原件→导入→复核合同 |
| OZN-003 | G0 | BLOCKED | 账户+工程 | 现有 7 个宽权限 Key 调用方未知；专用最小权限 API 身份与撤销策略缺失 | 按 Owner Decision Packet 盘点调用方，再批准专用只读身份和独立复核 |
| FIN-001 | G1 | PARTIAL_BLOCKED | 财务负责人 | 真实费用映射、RUB/CNY FX、结算和银行到账 | 未知费用隔离，完成三腿独立对账 |
| INT-004 | 持续情报 | BLOCKED | 情报/模型 Owner | GLM-5.2 独立候选缺有效额度 | 额度可用后只跑隔离候选，不降低 19/20 本地基线 |
| INT-005 | 持续情报 | NEEDS_REVIEW | 经营+合规 | SEC/企业 IR 的 CIK/证券代码和合规 User-Agent 未批准 | 责任人批准 watchlist 后再启用只读采集 |
| INT-006 | 持续情报 | BLOCKED | 账户+工程 | 六平台商家账户、应用审核和最小权限 Token 缺失 | 按平台逐一完成官方应用与只读权限，不共享 Token |

## 六、全部已完成任务

### DONE（34）

- BAS-001：审阅并分层冻结当前工作区
- BAS-002：PostgreSQL 迁移与回滚验证
- BAS-003：API、DB、Web 真实 smoke
- BAS-004：环境状态自动生成
- BAS-006：供应商时间/金额语义第一批
- BAS-007：Ozon/财务金额语义第二批
- BAS-008：决策/实验风险数字第三批
- BAS-009：策略/能力经济数字第四批
- BAS-010：旧核心 NUMERIC 第五批
- BAS-011：端到端关联基线
- BAS-012：Ozon 连接器安全闭环
- BAS-013：运行身份与密钥扫描
- BAS-014：当前 head 隔离恢复
- BAS-015：启动资料包结构合同
- BAS-016：Gate Review 事务 Outbox
- BAS-017：Outbox 覆盖清单与防漂移
- BAS-018：私密启动资料工作区
- BAS-019：图片素材采集合同
- BAS-020：真实图片/权利证据入口
- BAS-021：图片 Brief 前置闸门与官方 ComfyUI 健康
- BAS-022：受控 ComfyUI 执行与 Evidence 回收
- BAS-023：图片 QA 审计与 Listing 草稿交接
- BAS-024：Listing 审批不可变快照
- BAS-025：Listing 批准时快照复验
- BAS-027：启动资料内容严格预检
- BAS-028：启动资料双层状态边界
- BAS-029：API 镜像运行时资源一致性
- BAS-030：Web 交付镜像与 Compose 健康链
- SEC-001：API 身份认证
- SEC-002：审批身份、Kill Switch 与审计
- EVD-001：不可变证据对象与双时间设计
- INT-001：30 分钟权威来源采集与去重
- INT-002：确定性晨报与本机健康检查
- INT-003：本地候选分析 Evidence Gate

### DONE_ENGINEERING（38）

- BAS-031：Ozon API 身份盘点合同
- BAS-032：Ozon 单 SKU 只读目标绑定
- BAS-033：Ozon Pilot 执行前离线预检
- BAS-034：Ozon Worker 显式执行意图与执行时复验
- BAS-035：Ozon run 一次性执行授权与幂等重放闸门
- BAS-036：Ozon 成功响应检查点与恢复闭环
- BAS-037：Ozon 响应 Evidence 完整性恢复门
- BAS-038：Evidence 持续完整性巡检与事件升级
- BAS-039：24×7 Evidence 巡检接入
- BAS-041：新上新候选研究预检
- BAS-042：候选观测绑定不可变 Evidence
- BAS-043：候选研究原件录入与原子预检
- BAS-044：候选到三报价人工交接
- BAS-045：三报价前置门不可绕过
- BAS-046：候选测量合同与报价筛选策略
- BAS-047：三候选离线证据包
- BAS-048：真实需求报告门与候选 readiness 防串组
- BAS-049：真实需求报告双人不可变复核
- BAS-050：候选研究绑定已接受需求报告
- BAS-051：逐项成本权威来源与跨境巴士只读适配
- BAS-058：Ozon 原始财务文件只读预检
- BAS-059：候选证据权威等级门
- BAS-060：候选证据独立权威复核
- BAS-061：跨境 SaaS 竞品能力模式注册
- BAS-062：第三方研究信号收件箱
- BAS-063：版本化全成本场景模板
- BAS-064：三候选组合决策视图
- BAS-065：证据支撑的经营异常工作台
- BAS-066：Ozon 官方计提原件适配
- BAS-067：Ozon 计提分类与防重复确认
- BAS-069：最佳方案选择合同
- BAS-070：最佳方案结构化结果与反方复核门
- BAS-072：ERPNext 隔离侧车防双写合同
- BAS-073：Ozon 财务独立复核只读交接包
- BAS-074：Ozon 计提分类币种与符号不变量
- BAS-075：财务三方对账双人控制与原件独立性
- BAS-076：实际成本权威证明与执行前复验
- BAS-077：实际成本权威复核工作台

### 其它已交付范围（3）

- BAS-005：事务 Outbox 第一批（DONE_FIRST_BATCH）
- BAS-071：开源 ERP / Commerce 内核最佳方案研究（DONE_RESEARCH）
- BAS-068：Ozon 计提原件正式待复核存证（DONE_PENDING_REVIEW，工程完成但经营复核未完成）

## 七、BAS-076 / BAS-077 本轮交接

核心门禁是“`actual` 不能自报”。15 个成本项具有精确权威类型；复核证明绑定原件哈希、成本项、上传者、复核者和四项检查。任一拒绝优先阻断。利润创建、readiness、采购评审、样品下单和 Listing 草稿共用同一个 release-time 复验入口。BAS-077 进一步补齐非技术人工工作台：后端下发唯一规则目录，Operator 只读状态，Reviewer/Compliance/Admin 提交不可变结论；页面不自动改场景、入账、采购、定价或上架。

证据：[BAS-076](evidence/20260720_BAS_076_ACTUAL_COST_AUTHORITY_GATE.md)、[BAS-077](evidence/20260720_BAS_077_ACTUAL_COST_AUTHORITY_WORKBENCH.md)。

## 八、工作区交接警告

- 当前工作树不是干净提交：178 个变更路径，其中 70 个 modified、108 个 untracked；这些是连续实施形成的用户工作，不得 `reset --hard`、`checkout --` 或批量删除。
- 当前 HEAD 只用于定位基线，不代表上述全部工作已提交。
- `.runtime/G1_VERIFICATION.json` 是本机最新验收报告，不应当作长期文档真源或提交敏感运行数据。
- `.runtime/startup-intake` 是 Git 忽略的私密资料区；不得复制到 `web/public`、日志、对话或交接文档。
- 不要为了“先进感”安装更多 Agent/ERP/工作流；只有当前门禁无法解决且有真实复用量时才引入新组件。

## 九、恢复工作命令

```powershell
cd D:\KJDS\kjds
Get-Content AGENTS.md
Get-Content docs\project\MASTER_SPEC.md
Get-Content docs\project\03_REMAINING_WORK_AND_PARALLEL_PLAN.md
Get-Content docs\project\13_PROJECT_HANDOVER_AND_TASK_STATUS.md
git status --short
uv run pytest -q --basetemp=.runtime\pytest-handover
uv run ruff check apps\control_plane tests
pwsh -NoProfile -File .\scripts\verify-g1.ps1
```

如果只继续真实经营解阻，不要先跑写操作。先读取 readiness、异常工作台和启动资料严格预检；任何 Ozon 登录、验证码、付费授权、API 权限、付款或发布动作都由账户所有者显式批准。
