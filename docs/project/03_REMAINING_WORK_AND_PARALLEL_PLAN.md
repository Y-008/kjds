# 剩余任务与并行调度

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-PLAN-001 |
| owner | 项目负责人（待确认） |
| approver | 经营负责人 |
| status | Active |
| version | 8.4 |
| last_reviewed | 2026-07-25 |
| next_review | 2026-07-27 |
| gate | G-1–G1 |

任务工作簿中 108 项任务、58 项 P0 继续作为候选库存；当前执行 P0 收敛为下表。没有进入本表的任务不得占用当前开发窗口。

## 当前 P0

| ID | Gate | 任务 | Owner | 验收 | 依赖 | 状态 |
|---|---|---|---|---|---|---|
| BAS-001 | G-1 | 审阅并分层冻结当前工作区 | 工程负责人 | 可回滚提交；无不明来源改动 | 无 | DONE |
| BAS-002 | G-1 | PostgreSQL 迁移与回滚验证 | 工程负责人 | 当时迁移到 Alembic head（0038）；保留迁移回放与历史 upgrade/downgrade 证据 | BAS-001 | DONE |
| BAS-005 | G-1 | 事务 Outbox 第一批 | 工程负责人 | 业务/事件原子提交；并发独占；租约恢复；失败重试；稳定 event ID | BAS-002 | DONE_FIRST_BATCH |
| BAS-006 | G-1 | 供应商时间/金额语义第一批 | 工程负责人 | UTC/Decimal/有限值；领域与数据库双重拒绝非法输入 | BAS-002 | DONE |
| BAS-007 | G-1 | Ozon/财务金额语义第二批 | 工程负责人 | 非有限导入/FX/账本/容差/概率被领域与数据库拒绝 | BAS-006 | DONE |
| BAS-008 | G-1 | 决策/实验风险数字第三批 | 工程负责人 | 最大损失、置信度、预测区间、预算、止损、观测与阈值双层约束 | BAS-007 | DONE |
| BAS-009 | G-1 | 策略/能力经济数字第四批 | 工程负责人 | 阶段结果有限、成本非负、净价值守恒、币种 ASCII；领域与 DB 双层约束 | BAS-008 | DONE |
| BAS-010 | G-1 | 旧核心 NUMERIC 第五批 | 工程负责人 | 订单/费用/观测/机会/旧实验/建议/样品采购双层数值约束 | BAS-009 | DONE |
| BAS-011 | G-1 | 端到端关联基线 | 工程负责人 | request/trace/run/command/evidence 可从一次受控链互相追溯 | BAS-003 | DONE |
| BAS-012 | G-1 | Ozon 连接器安全闭环 | 工程负责人 | 有界重试、熔断、schema 漂移拒绝、成功响应先存原件再完成 run | BAS-011 | DONE |
| BAS-013 | G-1 | 运行身份与密钥扫描 | 工程负责人 | 启动配置失败关闭；生产禁止共享密钥；工作区高置信 secret scan | SEC-001 | DONE |
| BAS-014 | G-1 | head 隔离恢复演练 | 工程负责人 | 当时的备份哈希、0038 恢复、四张关键表计数一致、资源清理 | BAS-002 | DONE |
| BAS-015 | G0 | 启动资料包结构合同 | 工程负责人 | 八份 CSV 的文件名、列、关键行、三候选×五指标、三 SKU×三供应商覆盖和敏感字段名拒绝可重复校验；不晋升证据 | BAS-004 | DONE |
| BAS-016 | G-1 | Gate Review 事务 Outbox | 工程负责人 | 创建/提交/决定各产生一个最小脱敏事件；事件失败时业务状态回滚；不新增消息基础设施 | BAS-005 | DONE |
| BAS-017 | G-1 | Outbox 覆盖清单与防漂移 | 工程负责人 | 所有直接 Session 事务模块逐项分类并说明升级触发条件；代码集合与清单精确一致；不增加运行基础设施 | BAS-016 | DONE |
| BAS-018 | G0 | 私密启动资料工作区 | 工程负责人 | 复制公开模板到 Git 忽略目录；重复准备只补缺失模板且拒绝覆盖已有资料；输出非敏感位置与边界；可用现有校验器验证 | BAS-015 | DONE |
| BAS-019 | G1 | 图片素材采集合同 | 工程负责人 | 每 SKU 七类基础素材；已核验行必须含来源、授权、带时区时间、SHA-256 和负责人；不读取图片、不晋升证据 | BAS-018 | DONE |
| BAS-020 | G1 | 真实图片/权利证据入口 | 工程负责人 | 原图与独立权利文件成对上传；签名、哈希、SKU/变体/角色血缘可复验；追加 Quality Passport 草稿；七角色均获批准后才进入完整生产；上传不触发生成 | BAS-019 | DONE |
| BAS-021 | G2 | 图片 Brief 前置闸门与官方 ComfyUI 健康 | 工程负责人 | Content Service 强制复验 7/7 readiness 和原图—权利精确配对；官方本地 ComfyUI 版本/GPU 可观测；Web 只能建立 Brief，不自动生成 | BAS-020 | DONE |
| BAS-022 | G2 | 受控 ComfyUI 执行与 Evidence 回收 | 工程负责人 | 仅 `retouch` 可进入固定核心节点模板；队列幂等、状态可同步、失败关闭；输出哈希固化为 Evidence；Web 不提供任意 workflow；生成后仍须 8 项 QA 与人工批准 | BAS-021 | DONE |
| BAS-023 | G2 | 图片 QA 审计与 Listing 草稿交接 | 工程负责人 | 八项检查完整且无未知项；每项有结论/说明，服务端记录审核人/时间；任一失败退回；草稿图片只能引用同 SKU 已批准 ContentAsset Evidence；只建立发布审批，不执行发布 | BAS-022 | DONE |
| BAS-024 | G2 | Listing 审批不可变快照 | 工程负责人 | 规范 JSON 摘要稳定且内容变化必变；审批展示草稿、商品、报价、CM3、完整文案、属性、图片资产与产物证据；申请/批准身份分离；不执行 Ozon 写入 | BAS-023 | DONE |
| BAS-025 | G2 | Listing 批准时快照复验 | 工程负责人 | 批准前从存储重读草稿并以常量时间复核摘要；资源、审批或摘要不一致失败关闭；拒绝仍可记录；Approval 为决定状态唯一事实源；不执行 Ozon 写入 | BAS-024 | DONE |
| BAS-026 | G2 | Web 独立审批会话 | 工程+经营 | Supabase SSR、用户—actor 映射、服务端 credential、同源写保护、角色冲突、approver AAL2/TOTP 和重放门禁均已实现并进入 G-1；真实验收按 `09_SUPABASE_DUAL_CONTROL_ACCEPTANCE.md` 执行，仍需两个真实用户、真实设备绑定、撤销/恢复和经营负责人演练 | BAS-025、真实 Supabase 用户 | PARTIAL_BLOCKED |
| BAS-027 | G0 | 启动资料内容严格预检 | 工程负责人 | 结构合法与可交人工证据录入分开报告；逐行列出缺值/证据/Owner/素材角色；严格模式缺输入返回 3；不读引用、不写库、不晋升事实 | BAS-018、BAS-019 | DONE |
| BAS-028 | G0 | 启动资料双层状态边界 | 工程负责人 | 现有经营看板明确区分本地资料完整度预检与系统 Evidence/Passport/事实账 readiness；API 不读取或暴露私有 CSV；两层状态均不触发自动上架 | BAS-027 | DONE |
| BAS-029 | G-1 | API 镜像运行时资源一致性 | 工程负责人 | 生产镜像显式包含 Loop Engineering registry；`.dockerignore` 只开放该机器真源；镜像内 API 导入与真实容器 health 通过；G-1 持久检查 `container_import=true` | BAS-003 | DONE |
| BAS-030 | G-1 | Web 交付镜像与 Compose 健康链 | 工程负责人 | standalone 非 root 镜像；API healthy→Web healthy；真实首页/代理 200；G-1 `web_container_health=true`；SLA 验证时钟不随固定日期失效 | BAS-029 | DONE |
| BAS-031 | G0 | Ozon API 身份盘点合同 | 工程负责人 | 逐身份记录脱敏引用、调用系统、Owner、角色数、最后使用时间、处置与独立复核；空引用和重复引用失败关闭；禁止保存密钥值；不自动创建/轮换/撤销身份 | OZN-003 | DONE_ENGINEERING |
| BAS-032 | G0 | Ozon 单 SKU 只读目标绑定 | 工程负责人 | 产品信息与属性响应均恰好命中请求 offer；空、多条、缺字段、错目标失败关闭；控制面二次复验合同版本、1+1 计数和状态哈希；旧合同不得进入 Claim；不调用写端点 | BAS-012、OZN-003 | DONE_ENGINEERING |
| BAS-033 | G0 | Ozon Pilot 执行前离线预检 | 工程负责人 | 默认入口不联网且不启动依赖；单目标、官方端点、独立凭证与安全输出失败关闭；只有显式 `Execute` 才继续 | BAS-032、OZN-003 | DONE_ENGINEERING |
| BAS-034 | G0 | Ozon Worker 显式执行意图与执行时复验 | 工程负责人 | Worker 必须且只能选择 preflight/execute；执行进程在建客户端前复验当前环境；Compose 不保留隐式联网默认值 | BAS-033、OZN-003 | DONE_ENGINEERING |
| BAS-035 | G0 | Ozon run 一次性执行授权与幂等重放闸门 | 工程负责人 | 只有新 run 获得一次执行权；在途/完成/过期重放均返回历史结果且 Worker 不访问 Ozon、不重复存证或完成 | BAS-034、OZN-003 | DONE_ENGINEERING |
| BAS-036 | G0 | Ozon 成功响应检查点与恢复闭环 | 工程负责人 | 成功响应先固化 Evidence 再完成；控制面重试不重复调用 Ozon；`response_captured` 租约由证据恢复；摘要变化失败关闭 | BAS-035、OZN-003 | DONE_ENGINEERING |
| BAS-037 | G0 | Ozon 响应 Evidence 完整性恢复门 | 工程负责人 | 完成/恢复前重算 Blob 哈希并复验唯一血缘与元数据；缺失或损坏保持待恢复并返回安全阻塞码；坏 run 不阻塞同批健康 run | BAS-036、OZN-003 | DONE_ENGINEERING |
| BAS-038 | G0 | Evidence 持续完整性巡检与事件升级 | 工程负责人 | 有界扫描覆盖缺 Blob、哈希和大小不符；异常生成可验证报告并以稳定指纹幂等开事件；重复扫描不重复建事件；不自动修复或删除 | BAS-037 | DONE_ENGINEERING |
| BAS-039 | G0 | 24×7 Evidence 巡检接入 | 工程负责人 | 独立 monitor 身份分页扫描；必需模式下缺身份、调用失败、异常或分页未完成均非零；输出脱敏；G-1 从真实 API 调用健康脚本 | BAS-038 | DONE_ENGINEERING |
| BAS-040 | G0 | Evidence 健康循环调度部署验收 | 工程+运维 | 默认 Plan 不改系统；Install 只从任务可见 `.env` 预检成功后注册固定无密钥 Action；Audit 复验定义、最近结果和原生完成历史；至少三次连续结果 0 | BAS-039、运行配置 | BLOCKED_CONFIG |
| BAS-041 | G0 | 新上新候选研究预检 | 工程+商品 | 商品级证据不串组；五类指标、双来源、时效、供货与合规红线失败关闭；只允许淘汰、补证或进入三报价 | UNK-001 | DONE_ENGINEERING |
| BAS-042 | G0 | 候选观测绑定不可变 Evidence | 工程+商品 | 五类观测均引用哈希复验通过的原件；来源和时效匹配；结果分别返回观测与原件 ID | BAS-041 | DONE_ENGINEERING |
| BAS-043 | G0 | 候选研究原件录入与原子预检 | 工程+商品 | Web 可固化原件并提交五类固定指标；来源由原件派生；全验后原子写入；确定性重试不重复；只进入淘汰、补证或三报价 | BAS-042 | DONE_ENGINEERING |
| BAS-044 | G0 | 候选到三报价人工交接 | 工程+商品 | 重新复验证据；仅 RU/OZON；显式确认后建立幂等 candidate Product；候选原件血缘完整；SKU 冲突失败关闭；不自动采购、上架或平台写入 | BAS-043 | DONE_ENGINEERING |
| BAS-045 | G0 | 三报价前置门不可绕过 | 工程+商品 | 三报价写入前必须同时存在内部候选交接事件与有效 `candidate_basis` 血缘；缺任一项不写报价或假设 Evidence；G-1 从候选原件到三报价走真实 API 链 | BAS-044 | DONE_ENGINEERING |
| BAS-046 | G0 | 候选测量合同与报价筛选策略 | 工程+商品 | 五类指标有服务端固定方法/单位/窗口/样本合同；需求、竞争缺口、退货风险按可信度加权并实际参与 50/50/30 询价筛选；响应暴露策略与阈值失败；不批准采购或上架 | BAS-045 | DONE_ENGINEERING |
| BAS-047 | G0 | 三候选离线证据包 | 工程+商品 | 恰好三候选×五指标；RU/OZON、窗口、样本、值域、可信度、带时区时间和双来源失败关闭；合同与运行时策略防漂移；只做本地收集预检，不读原件、不自动导入或晋升事实 | BAS-046 | DONE_ENGINEERING |
| BAS-048 | G0 | 作用域化需求原件门与候选 readiness 防串组 | 工程+商品 | 保留一个 `SKU-000`；不少于 28 天的合格原件可按来源资质满足 `research`，Ozon Data 或两个独立 Ozon 官方分析入口才可满足 `real_execution`；`SKU-001/002/003` 只统计同时具备候选交接事件与有效 `candidate_basis` 血缘的 Product；历史目录不计 | BAS-047、SKU-000 | DONE_ENGINEERING |
| BAS-049 | G0 | 需求原件双人不可变复核 | 工程+账户 | 所有来源上传均仅待复核；不同身份接受且无拒绝后，按来源资质分别计算研究与真实执行 readiness；自审、改写复核与通用 Evidence/Lineage 伪造失败关闭 | BAS-048 | DONE_ENGINEERING |
| BAS-050 | G0 | 候选研究绑定已接受需求报告 | 工程+商品 | 录入、复评和三报价交接显式绑定同一份当前已接受报告；五类观测不串报告；报告缺失、损坏、待复核或拒绝均失败关闭 | BAS-049 | DONE_ENGINEERING |
| BAS-051 | G1 | 逐项成本权威来源与跨境巴士只读适配 | 工程+财务 | 费用来源矩阵冻结；只读适配器可读取订单原始费用、出库计费重量和仓库服务价；原始字段不被猜测映射；仓储和税费进入 CM2；真实凭证与财务映射仍独立验收 | FIN-001、跨境巴士企业授权 | DONE_ENGINEERING |
| BAS-058 | G4 | Ozon 原始财务文件只读预检 | 工程+财务 | 正式存证前无状态识别类型/行数/字段映射/缺列；失败不写库且不要求改原件；正式导入独立复验 | BAS-057、UNK-006 | DONE_ENGINEERING |
| BAS-059 | G0 | 候选证据权威等级门 | 工程+商品 | C/D 级第三方工具资料保留但不计入合格指标或来源族；需求/竞争/供货/退货至少 A/B，合规红线必须 A；独立返回低权威阻塞 | BAS-046、外部来源登记 | DONE_ENGINEERING |
| BAS-060 | G0 | 候选证据独立权威复核 | 工程+商品+合规 | 上传自报等级不直接生效；另一 Reviewer/Compliance/Admin 按指标核对三项权威条件并固化不可变接受/拒绝；任何拒绝、坏原件或证明失配失败关闭；通用接口不可伪造 | BAS-059、BAS-026 | DONE_ENGINEERING |
| BAS-061 | G0 | 跨境 SaaS 竞品能力模式注册 | 产品+工程 | 萌啦、Seerfar、妙手、51Selling 的当前公开能力、可借鉴模式、禁止复制边界、验证状态和下一合同机器可读；外部营销声明不晋升经营事实 | BAS-059 | DONE_ENGINEERING |
| BAS-062 | G0 | 第三方研究信号收件箱 | 工程+商品 | 手工导出以专用 API 固化提供方、稳定 ID/URL、原始字段、双时间、许可和候选关联；精确重试去重、变化追加；通用 Evidence/Lineage 不可伪造；只作辅助资料且不自动建商品、采购或 Listing | BAS-061、BAS-060 | DONE_ENGINEERING |
| BAS-063 | G0 | 版本化全成本场景模板 | 工程+财务+商品 | 15 项命名成本逐项保存 estimate/actual/unknown 与 Evidence；未知、缺证据和未分类成本失败关闭；返回公式版本、来源解释、保本价、安全边际和 ±10% 售价敏感性；旧 JSONB 场景兼容；不自动定价 | BAS-039、BAS-061 | DONE_ENGINEERING |
| BAS-064 | G0–G1 | 三候选组合决策视图 | 工程+商品+供应链 | 只聚合通过候选交接、原件复验和已接受需求报告门的 Product；每家供应商只使用当前报价及其当前利润场景；展示 Passport、三报价、完整正 CM3、最佳场景和阻断原因；排序只作人工决策辅助，不自动选品、采购、定价或上架 | BAS-050、BAS-063 | DONE_ENGINEERING |
| BAS-065 | G0–G4 | 证据支撑的经营异常工作台 | 工程+经营 | 服务端 readiness 把未满足 Gate 形成稳定 requirement 阻断投影，包含 Gate、来源、当前/目标、责任角色和下一动作；Web 与现有事故/命令/观察 SLA 队列同屏但不混淆时间语义；不自动补证、消除阻断、关闭事故或写平台 | BAS-064、BAS-038 | DONE_ENGINEERING |
| BAS-066 | G4 | Ozon 官方计提原件适配 | 工程+财务 | 真实 2025-10 原件无状态识别、15/15 行解析、精确控制总额与独立来源复核边界；不得误作纯费用表 | BAS-058 | DONE_ENGINEERING |
| BAS-067 | G4 | Ozon 计提分类与防重复确认 | 工程+财务 | 只对已接受原件真实出现组合做版本化分类；未全覆盖不晋升，不生成分录、不替代订单收入 | BAS-066 | DONE_ENGINEERING |
| BAS-068 | G4 | Ozon 计提原件正式待复核存证 | 工程+财务 | 原件哈希、Blob、Evidence/import 血缘和期间一致；15/15 行；复核数 0；正式事实与财务分录均为 0 | BAS-066、BAS-067 | DONE_PENDING_REVIEW |
| BAS-069 | G-1 | 最佳方案选择合同 | 工程负责人 | `/best` 先检查硬约束与比较维度；无证据不下结论；保存淘汰理由、失效条件和审批要求；页面可建立合同；全量回归通过 | BAS-008 | DONE_ENGINEERING |
| BAS-070 | G-1 | 最佳方案结构化结果与反方复核门 | 工程负责人 | 每个方案×硬约束完整落库；每方案六项经营评估；非选方案有淘汰原因；选择项全过硬约束；接受复核至少一条反方解释；0038 可升降；Web/API/OpenAPI/回归通过 | BAS-069 | DONE_ENGINEERING |
| BAS-071 | G-1 | 开源 ERP / Commerce 内核最佳方案研究 | 架构+工程 | ERPNext/Odoo/Dolibarr/Medusa/Saleor/Vendure 的官方仓库、许可证、职责、缺口、晋升门和退出条件机器可读；首选只进入隔离 PoC，不自动安装或改变事实 Owner | BAS-069 | DONE_RESEARCH |
| BAS-072 | G-1 | ERPNext 隔离侧车防双写合同 | 架构+工程 | 离线 Item/采购/财务草稿投影具备稳定 ID、版本、幂等键和 Evidence；Decimal/FX/Owner/Webhook/对账失败关闭；无远程写、自动提交、依赖或迁移 | BAS-071 | DONE_ENGINEERING |
| BAS-073 | G4 | Ozon 财务独立复核只读交接包 | 工程+财务 | 待复核状态展示原件哈希/大小/上传者、解析覆盖、逐币种精确合计、日期范围和实际计提组合；只聚合，不暴露原始业务行，不自动决策、分类或入账 | BAS-068 | DONE_ENGINEERING |
| BAS-074 | G4 | Ozon 计提分类币种与符号不变量 | 工程+财务 | 组合金额逐币种汇总；实际正/负/零可见；预期符号在批准与状态解析时逐行复验；失配批准不满足 ready；不新增规则引擎或自动分类 | BAS-067、BAS-073 | DONE_ENGINEERING |
| BAS-075 | G4 | 财务三方对账双人控制与原件独立性 | 工程+财务 | 对账人不得上传原件、创建分录、批准已采用费用映射或创建已采用 FX；银行与平台侧原件按 Blob SHA-256 独立，即使重复存证也不可冒充；阻断快照可审计；不新增表、依赖或银行解析器 | FIN-001、BAS-074 | DONE_ENGINEERING |
| BAS-076 | G0–G2 | 实际成本权威证明与执行前复验 | 工程+财务+供应链 | `actual` 必须由非上传者按精确成本项核对原件、计费主体及金额—币种—期间，并使用允许的权威类型固化不可变证明；任一拒绝优先阻断；利润创建、readiness、采购评审、样品下单和 Listing 草稿均重新复验；不新增表、依赖或成本总账 | BAS-063、BAS-075 | DONE_ENGINEERING |
| BAS-077 | G0–G2 | 实际成本权威复核工作台 | 工程+财务+供应链 | 服务端只读下发 15 项成本及允许权威类型；Reviewer/Compliance/Admin 可在 Web 选择 Evidence、查询状态并提交四项检查与不可变结论；Operator 只读；不复制规则、不自动改场景、入账、采购、定价或上架；不新增表、依赖或前端框架 | BAS-076、BAS-055 | DONE_ENGINEERING |
| BAS-078 | G0–G4 | 唯一运行时动作授权与 readiness 绑定 | 工程+控制面 | 计划创建/读取、许可排队及 Worker claim 均调用同一 phase-aware `authorize_action()`；L1–L4 动作政策与写路径注册表精确对应，CI 验证入口、正式写点、执行复验、幂等、回读、补偿及外部 HTTP 模块边界；候选晋升复用独立 Approval，Listing 草稿与 ComfyUI 在实际执行前复验；未接入许可和回读的真实动作保持 `policy_only` | BR-037、BR-060、BAS-077 | DONE_ENGINEERING |
| BAS-079 | G0 | SKU-000 单任务双作用域操作界面 | 工程+商品 | 现有 G0–G1 页面同时展示研究闭环与真实经营状态；上传时选择官方/历史/固定测试来源并保存来源定位；测试数据只能放行研究，不能放行任何真实副作用；不新增后台或 Gate | BAS-048、BAS-078 | DONE_ENGINEERING |
| BAS-080 | G0–G4 | Readiness 依据冻结进 DecisionPacket | 工程+控制面 | 执行计划申请时把精确需求原件与独立接受证明自动并入计划 Evidence/Lineage，并把每项 readiness 的状态、证据 ID、阻塞码和快照哈希冻结进现有 Approval payload 与 DecisionPacket；读取时另算当前状态但不改写历史依据；任一冻结证据损坏均阻断旧计划 | BR-061、BAS-078 | DONE_ENGINEERING |
| BAS-081 | G0–G4 | 受限执行组合风险预留与快照 | 工程+控制面 | 复用 Action Policy 与 Limited Executor；同动作同 UTC 日排队在 PostgreSQL 事务中串行预留每日次数，固化同动作/同币种累计风险、派生上限、覆盖边界和快照哈希，授权摘要绑定快照，Worker claim 前重新复验；不新增风险注册表、不虚构店铺/法人/现金阈值；[工程证据](evidence/20260721_LIMITED_EXECUTION_AGGREGATE_RISK_RESERVATION.md) | BR-062、BAS-080 | DONE_ENGINEERING |
| BAS-082 | G-1–G4 | 外部合同固定样本回放门 | 工程+集成 | 复用现有 Ozon 客户端、ComfyUI 结果解析、财务导入预检和测试运行器；版本化脱敏样本声明合同、预期与 SHA-256；自动测试回放成功/漂移并失败关闭；现有限流、超时、写入不确定、幂等与回读专项测试保持通过；GitHub 公开仓库、真实 PR、`backend-quality`、`web-quality`、`postgres-smoke` 与 `main` 分支保护已运行成功；[工程证据](evidence/20260721_BAS_082_EXTERNAL_CONTRACT_REPLAY.md)、[CI](https://github.com/Y-008/kjds/actions/runs/29807719392) | BR-063、BAS-081 | DONE_ENGINEERING |
| BAS-083 | G5 | Champion/Challenger 独立影子对照账 | 工程+能力治理 | 复用既有 Policy Evaluation `result_json` 和 Evidence/Lineage，冻结不同身份产生的 champion/人工基线、双方哈希、精确差异路径及一致性；缺基线或基线证据失效时禁止记录影子阶段结果和申请激活；不新增表、服务或依赖；真实收益与跨 SKU 复现仍在 G5/G7 验收 | BR-061、BR-064、BAS-082 | DONE_ENGINEERING |
| BAS-084 | G-1 | 后端组合根收敛 | 工程负责人 | 新增单一 `RuntimeServices`；`api.py` 只保留应用创建、中间件、异常边界和领域 Router 注册；公共路径、响应、operation ID 与 OpenAPI 精确不变；不新增依赖或迁移；[工程证据](evidence/20260721_BAS_084_BACKEND_COMPOSITION_ROOT.md) | BAS-083 | DONE_ENGINEERING |
| BAS-085 | G-1 | Web 组合根收敛 | 工程负责人 | `page.tsx` 只保留 Dashboard 组合入口；统一原生 `fetchJson` 与实际使用的合同类型；按财务、运营、决策科学、研究门禁、商品内容和采购拆分领域面板；请求失败按领域隔离；页面不重算 Gate、利润、权限或 Evidence；[工程证据](evidence/20260721_BAS_085_WEB_COMPOSITION_ROOT.md) | BAS-084 | DONE_ENGINEERING |
| BAS-086 | G-1 | 可选 Provider 运行边界 | 工程负责人 | n8n、Firecrawl、Ollama 仅在显式配置后构造、展示和检查；核心 readiness 不依赖可选 Provider；ComfyUI 继续受控且不得直传平台；删除无调用方配置；[工程证据](evidence/20260721_BAS_086_OPTIONAL_PROVIDER_BOUNDARIES.md) | BAS-085 | DONE_ENGINEERING |
| BAS-087 | G-1 | G1 Harness 收敛 | 工程负责人 | 已冻结场景与覆盖映射；PowerShell 只保留基础设施生命周期、迁移、恢复、Worker、跨进程最小烟测与清理；领域场景由分组 Pytest 合同覆盖；[工程证据](evidence/20260721_BAS_087_G1_HARNESS_CONVERGENCE.md) | BAS-086 | DONE_ENGINEERING |
| BAS-088 | G0–G4 | 唯一经营工作台 Agent 简报 | 工程+经营 | 单一只读快照聚合 Gate 阻断、运行异常、已有建议与候选组合；动态展示责任 Agent 和当前焦点；Gate 阻断不伪造 SLA；固定禁止自动执行、平台写入和第三方事实晋升；第三方未授权代码不进入仓库；[工程证据](evidence/20260725_BAS_088_UNIFIED_OPERATING_WORKBENCH_AGENT_BRIEFING.md) | BR-065、BAS-065、BAS-086 | DONE_ENGINEERING |
| BAS-003 | G-1 | API、DB、Web 真实 smoke | 工程负责人 | 冷启动可复现；健康检查通过 | BAS-002 | DONE |
| BAS-004 | G-1 | 环境状态自动生成 | 工程负责人 | 不再依赖过时静态 PASS 文档 | BAS-003 | DONE |
| SEC-001 | G-1 | API 身份认证 | 工程负责人 | `KJDS_API_KEY` 或正式身份层生效；未授权为 401/403 | BAS-003 | DONE |
| SEC-002 | G0 | 审批身份、Kill Switch 与审计 | 工程+经营 | 申请/批准不可伪造；紧急停止可验证 | SEC-001 | DONE |
| SKU-000 | G0 | Ozon 新品需求数据访问与原始报告 | 账户+商品 | 唯一任务内分别验收 `research` 与 `real_execution`：研究需至少 28 天、来源定位、SHA-256 和独立复核；真实执行另需 Ozon Data，或至少两个独立 Ozon 官方分析入口。公开示例、测试和第三方信号不得放行真实动作 | UNK-015 | PARTIAL_BLOCKED |
| SKU-001 | G0 | 确认三个真实候选 SKU | 商品负责人 | 每个 SKU 完成五指标预检、人工报价交接、稳定 ID、有效 `candidate_basis` 与红线结论；历史 Product 不计 | SKU-000、Owner/RACI | BLOCKED |
| SKU-002 | G1 | 三类 Passport 与证据包 | 商品/合规 | 3×3 Passport 完整且人工批准 | SKU-001 | BLOCKED |
| SKU-003 | G1 | 报价、样品、包装和物流实测 | 商品/供应链 | 每 SKU 三报价；重量尺寸与包装有实测 | SKU-001 | PARTIAL_BLOCKED |
| OZN-001 | G0 | Ozon 账户、权限和收款路径核验 | 经营负责人 | 官方后台/合同/权限证据；已只读确认登录态、有效合同和 Seller API，仍需脱敏原件入账及专用最小权限身份 | 人工批准/原始导出 | PARTIAL_BLOCKED |
| OZN-002 | G1 | Ozon 数据合同与只读接入矩阵 | 工程+经营 | 订单/费用/退货/结算字段与来源明确 | OZN-001 | PARTIAL_BLOCKED |
| OZN-003 | G0 | Ozon API 身份最小权限治理 | 账户+工程 | 盘点现有调用方；专用只读 Key 只授予所需角色；闲置宽权限 Key 经批准撤销；不在仓库、日志或对话暴露密钥 | OZN-001、账户负责人批准 | BLOCKED |
| FIN-001 | G1 | 费用字典、FX 与 CM3 口径 | 财务负责人 | 金额/币种/日期/证据齐全；未知费用隔离 | OZN-002 | PARTIAL_BLOCKED |
| EVD-001 | G1 | 不可变证据对象与双时间设计 | 工程负责人 | 哈希、原件、血缘、等级、effective/recorded 时间可验证 | BAS-002 | DONE |

`BLOCKED` 项不是工程问题：需要账号所有者、真实商品/供应商、样品或一手业务文件。增加开发窗口不能消除这些阻塞。

2026-07-19 已核验 Ozon 官方 `data.ozon.ru`：公开页中的商品、销量、搜索量和类目增长均明确标注为报告示例；真实分析入口要求账户主体先接受 Ozon 要约和个人信息处理条件。本次没有替账户主体接受条款。`SKU-000` 因此保持 `PARTIAL_BLOCKED`，公开示例不得写入三个候选；账户负责人完成条款决定并导出真实 28 天原始报告后，才开始候选淘汰、供货核验和三报价。证据见 `docs/project/evidence/20260719_SKU_000_OZON_DEMAND_DATA_ACCESS_GATE.md`。

2026-07-20 已从 Ozon 官方文章定位并实测 Seller“我商品的搜索查询”入口。当前账号可读默认七天的两个历史商品，但跨月 28 天范围未被接受；点击“下载报告”后出现 Premium/Premium Lite 订阅门，本地没有生成原始文件。该结果证明登录态和可见页面，不满足 `SKU-000` 的原件、28 天窗口、哈希和独立复核要求。下一步由经营负责人决定 Ozon Data 条款、Premium 支出，或批准专用只读 Seller API 身份验证等强官方原始响应；不得抓包绕过或用第三方数据替代。证据见 `docs/project/evidence/20260720_SKU_000_OZON_SELLER_ANALYTICS_EXPORT_GATE.md`。

同日进一步核验 Ozon Developer 与 Seller API 契约：`/v1/analytics/product-queries` 和 `/details` 只分析我方已有 SKU 的搜索查询，不能提供尚未上架候选的全市场/类目需求。它们可在未来用于现有 Listing 诊断，但不解除 `SKU-000`；因此本批不新增错误用途的第三个 Ozon Worker，也不扩大 API Key 权限面。`SKU-000` 下一输入仍是 Ozon Data 或其他官方类目级 28 天原件。

2026-07-20 再次只读核验 Ozon Data 与 Seller：Ozon Data 仍要求账户主体接受要约、个人信息处理条件并确认已满 18 岁；Seller“销售漏斗”可切换 28 天并做类目/竞争对手对比，但仍是“我的商店”经营分析，不能替代新候选的全市场原件。默认解阻路径收敛为 Ozon Data；Premium 和 `product-queries` 不为 `SKU-000` 扩权或采购。账户负责人的两项最小决定、失败关闭条件和 OZN-003 身份收敛步骤见 `docs/project/evidence/20260720_SKU_000_OZN_003_OWNER_DECISION_PACKET.md`。

2026-07-22 使用现有登录态再次只读复验：免费 Seller Analytics 的 28 天销售漏斗可用，但当前店铺订购金额和订购数量为零；竞争对手销售、类目数据、热门商品、搜索查询、Ozon 尚无商品及售罄需求等能力仍位于 Premium 订阅区。页面存在免费试用和多档付费方案，本次未点击、未订阅、未付款。由于用户已明确不升级付费，`SKU-000 research` 改走“免费 Ozon 官方信号 + 公共市场证据 + 第三方辅助信号 + 供应商实价”的研究路径，结果始终标记 `research_signal/estimate/simulation`；`real_execution` 继续失败关闭。证据见 `docs/project/evidence/20260722_SKU_000_FREE_ANALYTICS_PREMIUM_GATE.md`。

同日修正 KJDS 来源合同：新增 `ozon_seller_analytics` 作为店铺级、仅研究来源，并允许固化页面截图或导出文件；它经独立复核后只能解除 `research` 阻塞，不属于可组合的 `real_execution` 官方类目来源。界面和测试明确这一边界，避免把当前后台页面误称为全市场需求报告。

同日完成第一轮公开候选预筛：低客单的单个理线夹、毛毡脚垫、宠物除毛滚筒和自粘拖把夹直接淘汰；旅行箱收纳袋套装、手动泵真空收纳袋套装、机械固定铝合金拖把/扫帚墙架进入正式取证队列。公开 Ozon 页面和 Alibaba 展示价只证明“值得继续核验”，不提供 28 天指标、不构成真实报价，也不解除 `SKU-000/001`。三类假设只有补齐 28 天原件、A/B 证据等级、官方合规结论、三家同口径报价和样品实测后，才允许完成候选包并申请人工交接。证据见 `docs/project/evidence/20260722_SKU_001_PUBLIC_CANDIDATE_PRESCREEN.md`。

同日继续完成私密候选包的供应端准备：RU-001、RU-002、RU-003 均已有 3 条可联系供应商发现线索。RU-003 只有 Jiaxing All-Link 的公开页精确匹配 5 位 6 钩；CLEANIC 与 Fuzhou Eastsound 仍须按同一冻结规格书面确认 `60 cm / 5 位 / 6 钩 / 机械固定`，因此不视为三家精确规格供应商或三份报价。公开页面只填入 `supplier_available` 的 `research_signal`，未写入正式报价；启动包 v4 结构校验通过，但 15 行候选指标仍有 15 个阻塞项，需求、竞争、合规、退货、两来源族及全部真实经营 Gate 继续失败关闭。

同日完成三候选官方合规框架预审：当前 EEC 的 ТР ТС 017/2011（含 2025 年修订）、ТР ТС 005/2011（含 2024 年修订）和第 299 号决定只证明存在按材料、用途、TN VED 和类目判断的义务，不能直接证明任一具体候选合规或豁免。RU-001～003 的 `compliance_redline` 因此继续为 `UNKNOWN`，私密包不填数值；每个候选须取得供应商材料/用途声明、独立 TN VED 书面判断、当前符合性路径、Ozon 类目要求原件及非上传者复核。证据见 `docs/project/evidence/20260722_SKU_001_COMPLIANCE_PRESCREEN.md`。

`2026-07-22T12:33:34+08:00` 再次逐条复验官方来源：EEC 页面可直接证明 ТР ТС 017/2011、ТР ТС 005/2011 的现行修订入口，并明确 TN VED 归类依赖材料、结构、用途及充分商品描述；俄罗斯第 2425 号决议只提供强制认证/声明清单入口。Ozon 条款页本次无法被独立抓取器稳定读取，因此旧记录中的具体修订日期和“3 个工作日”降级为 `requires_review`，不参与 A 级合规放行。三候选状态与阻塞不变，没有填入猜测 TN VED、豁免或认证结论。

为减少外部资料准备摩擦，Web 首屏已增加按 readiness 实时驱动的七步启动路径：治理、Ozon 权限、真实需求报告、候选研究、Passport/素材、三报价和财务。`web/public/startup/` 提供治理、Ozon 权限、Ozon API 身份盘点、三候选五指标、三 SKU、图片素材、三报价、财务对账八份 CSV 模板；真实需求报告没有伪模板，只链接 Ozon Data 正式入口。该增量只改善收集与导航，不把模板、公开示例、引用或 `verified` 文本当作原始证据，也不改变上述 `BLOCKED/PARTIAL_BLOCKED` 状态。

`OZN-002` 的工程侧已完成 `ozon-v1` 订单、费用、计提、退货、结算五类版本化合同、CSV/XLSX 暂存校验、原文件证据绑定、不可变事实晋升和真实 PostgreSQL smoke。2026-07-20 首份真实官方计提 XLSX 已通过专用合同预检与隔离复算，但尚未正式存证、独立复核或完成会计分类；订单、结算、退货和银行/FX 原件仍缺，因此保持阻塞，不能用猜测补齐。

2026-07-18 的 Ozon Seller 只读观察已把 `OZN-001` 从完全未知推进为部分阻塞：店铺可登录，合同与 Seller API 可用，商品区有 18 个商品（15 在售、3 待售、0 错误）。同时发现 7 个已激活 API Key 均为 35 角色宽权限、后台只有一个员工主体；未读取、复制、生成或吊销任何密钥。最近 7–14 天经营窗口为 0 订单，最近一周仅 33 次展示、1 次商品卡访问、0 加购，价格指数 100% 不利，14 个可评估 SKU 中 8 个未认购/不可售。因此不能把“账户可访问”包装成“可自动上新”：先完成 `OZN-003`、获取长期商品/订单/费用原始导出并补真实成本；现有 18 个商品只作为历史目录和经营基线，新的三个上新候选另行走需求、货源、报价、合规和 CM3 门禁。浏览器观察只记为 `requires_review`，不晋升正式事实；见 `evidence/2026-07-18-ozon-seller-read-only-observation.md`。

2026-07-19 再次只读复验确认商品计数未变，财务、分析、Seller API 与 API 通知入口仍可访问；没有查看或操作已有密钥，也没有下载报表。由于用户已明确要求后续做新上新，`SKU-001/UNK-001` 的口径随之收紧：现有 18 个商品只作为历史目录与竞品对照，不直接选为三个新候选；新候选必须先完成需求证据、可采购性、三报价、合规红线与风险调整后 CM3，再由经营负责人确认。此次复验不解除 `OZN-003/UNK-012/UNK-013`。

`OZN-003` 的最小执行顺序已冻结为“调用方盘点 → 账户负责人批准 → 专用产品只读身份 → 单 SKU Pilot → 原始响应复验 → 独立 Claim Review → 最多 3 SKU 扩量”。订单、库存和财务读取权限必须分别随已批准 Pilot 增加，不允许为了省事直接复制现有 35 角色身份。该流程复用现有只读 Worker、Evidence、Claim 与 Gate Review，不新增第二套连接器。

`BAS-031` 将上述调用方盘点变成启动资料包 v3 的第七份机器可校验清单。模板预置七个非敏感身份别名，要求补调用系统、Owner、角色数、最后使用时间、处置决定、证据和独立复核；校验器拒绝空引用与重复引用。它不读取 Key、不创建或撤销身份，也不替代账户负责人批准，因此 `OZN-003` 仍为业务阻塞。

`BAS-032` 复用现有 Worker/Pilot/Evidence/Claim 链，将 `ozon.product.read` 固定为 `ozon-product-read-v1`：产品信息和属性端点必须各返回且只返回一个与请求 offer 一致的对象；空结果、多结果、缺失 `offer_id` 或串到其他商品均失败关闭。控制面还会复验合同版本、1+1 记录数和状态 SHA-256，旧版或不完整 run 不能提 Candidate Claim。该工程门不证明真实 Ozon 响应已经符合合同，仍需 `OZN-003` 专用只读身份完成单 SKU 影子 Pilot。

`BAS-033` 将首次 Pilot 的操作入口收紧为离线预检：默认只在隔离容器内检查单目标、幂等键、官方 HTTPS Ozon origin、固定属性路径、控制面传输和专用凭证隔离，不启动 API 依赖或构造 HTTP 客户端；输出只保留哈希、计数和布尔结果。只有预检通过且操作员显式传入 `-Execute` 才运行现有只读 Worker。该门不会读取真实密钥值、不会证明最小权限或真实响应，也不解除 `OZN-003`。

`BAS-034` 把执行意图从 PowerShell 包装层下沉到 Worker：CLI 缺失模式或同时指定 `--preflight/--execute` 都在参数解析期拒绝；Compose 运行命令显式携带 `--execute`。真正执行前会在同一进程、同一环境中再次校验连接与凭证，首次单 SKU 还会完整重跑离线预检，从而关闭直接模块调用绕过和两容器之间的配置变化窗口。显式执行仍不等于经营批准，真实调用继续由 Pilot Review、Kill Switch 与 `OZN-003` 阻塞。

`BAS-035` 将 run 的记录幂等升级为执行权幂等：控制面只有在新建 run 时授予一次执行权；命中既有在途、完成或过期 run 时只返回历史状态。Worker 未取得明确执行权就不会调用 Ozon、采集第二份响应或重复完成。该门选择 at-most-once 安全语义，首次授权响应丢失时不会自动重授，必须待租约回收后使用新的可追踪幂等键人工重试。

`BAS-036` 关闭平台成功后、控制面完成前的结果丢失窗口：Worker 先把原始成功响应提交为不可变 Evidence 并进入 `response_captured`，再从持久化结果完成 run。相同检查点和完成请求可幂等复放，内容变化失败关闭；控制面超时/5xx 只重试控制面提交，绝不再次调用 Ozon。租约回收器会完成已有响应的 run，而不是把它误判为 `RUN_LEASE_EXPIRED`。该门仍未运行真实 Ozon Pilot，也不解除 `OZN-003`。

`BAS-037` 针对 Evidence 记录正确但底层 Blob 已损坏或丢失的故障：完成与回收必须重新读取内容并计算实际 SHA-256，同时复验唯一 raw-response 血缘、来源、run 引用、类型、等级、元数据和字节数。异常 run 保持 `response_captured` 等待人工恢复，不生成成功摘要；回收器用非敏感错误码报告并继续处理同批健康 run。该工程门不替代备份恢复、运维告警或真实 Ozon Pilot。

`BAS-038` 将消费时门禁扩展为主动巡检：扫描快照必须包含没有 Blob 的 Evidence 记录；每个异常先生成不含原始正文的监测报告，再复用现有 Operational Incident 与恢复审批链。初始实现只提供受权触发的有界扫描，不引入新调度器；后续由既有自动化入口定时调用。

`BAS-039` 把上述入口接入现有 `run-24x7-health.ps1`，不新增调度器。健康循环使用专用 monitor key 完成分页扫描，只输出脱敏摘要，并以现有非零退出交给 Windows Task/OpenClaw 外层处理。该工程交付不证明机器离线时仍运行，也不证明 Slack/邮件/短信等外部通知已经送达。

`BAS-040` 已补齐默认安全的 Windows Task 管理合同：`manage-evidence-health-task.ps1` 默认只输出 Plan；显式 Install 仍必须从调度任务可见的项目 `.env` 重跑 `ControlPlaneOnly`，不会把当前终端临时变量当成部署配置；注册后的 Action、工作目录、重复间隔、执行上限与重叠策略必须立即复验。Audit 使用原生 Task Scheduler 完成事件和最近结果，少于三次连续成功、历史不可用或定义漂移都返回非零。当前只读审计仍确认没有目标任务和 `.env`，因此本批次完成的是工程防误装合同，不是运行部署，状态继续为 `BLOCKED_CONFIG`。见 `docs/project/evidence/20260719_BAS_040_HEALTH_SCHEDULER_AUDIT.md`。

`BAS-041` 复用现有 `MarketObservation` 与市场情报服务，不增加表、迁移或第二套选品评分器。候选预检按稳定 `candidate_ref` 精确隔离五类观测，拒绝未来/过期、越界和证据单一化；当前合规红线优先返回 `reject`，其余缺口返回 `collect_evidence`，全部满足也只返回 `request_three_quotes`。它不会创建 Product、采购、Passport 或 Listing，也不把公开页面估算晋升为三家真实报价，因此 `SKU-001/UNK-001/005` 仍未解除。证据见 `docs/project/evidence/20260719_BAS_041_NEW_LISTING_CANDIDATE_PREFLIGHT.md`。

`BAS-047` 为 `SKU-001` 增加私密离线准备合同：公开 `candidate-research.csv` 只给出三个候选×五指标的空结构，实际资料应复制到 Git 忽略目录填写。校验器拒绝候选/指标缺失或重复、非 RU/OZON、窗口样本与运行时测量策略漂移、非有限/越界值、无时区时间和少于两个来源族；但它不读取 `evidence_reference`、不调用候选 API、不创建 Product，也不改变 `SKU-001/UNK-001/014` 的业务阻塞。证据见 `docs/project/evidence/20260719_BAS_047_CANDIDATE_PORTFOLIO_PACKAGE.md`。

`BAS-042` 不增加市场表或另一套 Evidence 系统，而是在 BAS-041 评估边界复用现有 EvidenceService。候选观测必须用 `dimensions.evidence_id` 绑定存在且哈希复验通过的原件；原件来源必须与观测来源完全一致，观测时间、原件生效时间和可选失效时间同时受 `as_of` 约束。结果分别返回 observation 与 Evidence ID。缺原件、损坏、过期或来源不匹配均补证而非进入报价。证据见 `docs/project/evidence/20260719_BAS_042_CANDIDATE_EVIDENCE_BINDING.md`。

`FIN-001` 的工程侧已完成版本化费用映射、指定来源/日期 FX、不可变财务分录、未知费用隔离、订单—平台—银行对账快照和 13 周现金流骨架。Ozon 映射只能从已接受的真实费用导入中逐个批准，不能再走通用接口旁路；真实费用字典、银行格式、FX 会计口径与 CM3 实际验收仍依赖 `UNK-005/006/007` 的一手文件和财务负责人批准。

`SKU-002` 的工程准入门已完成：已审核 Passport 只能引用哈希复验通过的不可变证据，版本只可追加，商品放行时再次复验并记录证据—Passport 血缘。三 SKU 的真实事实、合规结论和人工批准仍由 `SKU-001/002` 业务阻塞决定。

`SKU-003` 的工程准入门已完成：供应商报价必须引用不可变原始证据，利润场景必须附带假设证据；报价与利润场景只可追加，同一外部报价编号的变化不会覆盖历史。三 SKU、每 SKU 三家真实报价、样品实测、包装测试与物流凭证仍依赖商品/供应链负责人提供的一手资料。

本轮工程增量已完成两项支撑：G0 Gate Review 已从单一 GOV-001 文件升级为 owner/独立 approver/风险预算/最大损失/回滚/证据/决定的结构化合同；Ozon 只读 worker 已支持有界批次、确定性游标、目标哈希脱敏和逐 run 幂等证据登记。两者都不能替代 OZN-001 的真实账户权限或 OZN-002 的一手报表样本。

同时完成 API 最小权限收敛：商品、市场、内容、实验、订单、推荐和模型发现等业务写入口均要求 endpoint 级角色；全局写 middleware 不再被视为充分授权。专用 worker 身份仍只能访问其明确的控制面接口。

`BAS-005` 第一批已将 Repository 驱动的业务服务和自动化推荐纳入同事务 Outbox，并在真实 PostgreSQL 验证 `SKIP LOCKED` 独占领取、租约恢复和至少一次发布；外部 sink 必须按 `event_id` 去重。仍直接管理 SQLAlchemy Session 且尚未声明 Outbox 事件的领域，需要在产生跨边界副作用时逐项迁移；因此状态不是“全系统完成”。

`BAS-006` 已冻结供应商报价与利润场景的第一批时间/金额语义：外部时间必须带时区并转 UTC，金额/汇率/度量只接受有限 Decimal，负成本与非法费率由领域和 PostgreSQL 0030 双重拒绝。G-1 已验证 11 条数据库约束和三类绕过服务层的非法写入；其他金额表与真实财务舍入口径仍需在一手数据进入前逐项审计。

`BAS-007` 已把相同语义扩展到 Ozon 导入、FX、正式财务分录、对账容差、现金计划和期初余额；PostgreSQL 0031 的 5 条约束及四类非法直写均通过 G-1。真实费用字典、银行格式、FX 会计口径和其他金额领域仍需一手数据与负责人批准。

`BAS-008` 已扩展到决策合同、分析置信度、预测区间、结果账和因果实验的 MDE/预算/止损/观测/安全阈值；PostgreSQL 0032 的 7 条约束及七类非法直写均通过 G-1。

`BAS-009` 已覆盖因果策略阶段结果与能力经济账；PostgreSQL 0033 的 5 条约束拒绝非有限值、负成本、净值不守恒和非 ASCII 币种，五类绕过服务层的非法写入均通过 G-1 拒绝验证。执行计划本身没有 NUMERIC 列；执行后观测以字符串保存但入口已强制有限 Decimal。未来新金额/度量字段仍须按 ADR-0008 审计，不能把本批解释为全系统会计口径完成。

`BAS-010` 已完成当前 ORM 剩余显式 NUMERIC 列审计：PostgreSQL 0034 为七张旧核心表增加 7 条约束，七类非法直写全部被拒绝，完整 G-1 为 127 passed。当前结构层缺口已收口；下一步应转向字符串型数值字段的数据合同、真实 Ozon/银行/税务口径和恢复复演，而不是继续机械增加 CHECK。

`BAS-011` 用 PostgreSQL 0035 收口最小关联链：API 安全复用或生成 request/trace 头，worker 每次操作保持一个 trace、每次 HTTP 请求使用独立 request；只读 run 证据与有限执行 receipt 持久化关联 ID。G-1 用同一 trace 关联 run、command 和 evidence，128 项测试通过。当前没有引入 OpenTelemetry 或集中日志平台；待出现多个独立服务、跨进程排障或 SLO 告警需求时再升级。

`BAS-012` 按 ADR-0010 收口 Ozon 连接器最小安全链：读请求仅对传输错误、429/5xx 最多尝试三次，连续故障开启进程内熔断；写请求不盲目重试；端点关键结构漂移以稳定错误码失败关闭。成功只读 run 必须先通过专用 `pilot_reader` 路由保存无请求凭证的原始响应包，控制面复验 SHA-256 和大小后才允许生成脱敏摘要证据。最新 G-1 的 `connector_safety=true`、136 项测试通过；真实 Ozon 账户响应回放仍依赖 OZN-001/OZN-002。

`BAS-013` 按 ADR-0011 收口运行身份和仓库密钥的最小门禁：空身份映射安全回退开发密钥；未知角色、占位密钥、生产共享密钥和未登记 Web 代理密钥启动失败关闭；G-1 只输出非敏感身份摘要，并用标准库扫描当前 277 个已跟踪或未忽略的新文件。最新 G-1 的 `runtime_identity_config=true`、`secret_scan=true`，不提前引入 Vault/KMS；首次托管生产部署再评审轮换与撤销。

`BAS-014` 将 head 恢复演练纳入默认 G-1：该次业务 smoke 后用官方 `pg_dump/pg_restore` 生成带 SHA-256 清单的临时备份，恢复到隔离库，校验当时的 `20260720_0038` 并比较商品、订单、证据和只读运行四张关键表的精确行数。该次 G-1 的 `backup_restore=true`，源库、恢复库和备份目录均清理；当前结果必须以 `.runtime/G1_VERIFICATION.json` 为准，自动计划、异地副本和生产 RPO/RTO 仍不在本地基线内。

`BAS-015` 只冻结外部资料进入正式证据链之前的结构合同：标准库校验器不写数据库、不读取凭证、不把 CSV 当作原件或正式事实；领域值、证据哈希和人工批准仍由现有后端入口负责。供应商模板已补齐 3 SKU×3 家占位行，负向回归会拒绝报价覆盖缺口和敏感字段名；最新 G-1 的 `startup_package_contract=true`、138 项测试通过，文档同步后的当前密钥扫描覆盖 231 个文件。

`BAS-016` 将最先影响放行结论的直接 Session 领域纳入第二批 Outbox：Gate Review 创建、提交和决定分别与最小脱敏事件原子提交，事件故障时决定回滚到 `submitted`。复用现有 PostgreSQL Outbox，不新增 migration、消息队列或外部 sink；其他直接 Session 领域仍按是否存在真实跨边界消费者逐项评估。

`BAS-017` 已冻结真实覆盖边界：25 个直接管理 SQLAlchemy 事务的控制面模块全部进入机器可读清单，分为 2 个已覆盖、2 个轮询合同、4 个 Gate 前延期、15 个仅内部状态和 2 个基础设施模块。标准库回归测试要求源码发现集合与清单精确一致；清单只描述现状，不授予外部副作用权限，也不把轮询或内部状态包装成 Outbox。完整 G-1 为 139 passed、234 文件密钥扫描并通过真实 PostgreSQL/API/Web/恢复验证。

`BAS-030` 使用 Next.js 原生 standalone 输出和现有 Compose 收口 Web 交付，没有新增运行框架或依赖。多阶段镜像以非 root `node` 用户运行；API 和 Web 都有原生健康检查，Web 与 Ozon worker 只在 API healthy 后启动。真实 Compose 联调已验证 Web 首页和服务端 `/backend` 代理返回 200，完整 G-1 的 `web_container_health=true`。首次完整回归还暴露了 operations queue 使用固定 `as_of` 日期的时间炸弹，现改为相对当前 UTC 的未来观察点并复跑通过。该闭环不代表生产 Supabase 双用户验收、G0、镜像仓库发布、云部署或 Ozon 写权限已经完成。

`BAS-018` 已补齐私密资料准备路径：公开 CSV 继续作为可下载空模板，本地填写副本默认放入已被 Git 忽略的 `.runtime/startup-intake`。准备入口不读取或输出已有内容；首次创建全部模板，重复执行只补充新版本中缺失的模板，任何已有文件均原样保留。默认副本通过现有结构合同，且结构校验不等于证据、正式事实或 Gate 放行。

`BAS-019` 将真实图片生成前置条件加入启动资料包 v2：每个 SKU 的 base variant 必须覆盖主图、背面、侧面、细节、配件、包装和比例参照；只有真实样品拍摄或供应商明确授权的素材，且来源引用、授权引用、带时区拍摄时间、文件 SHA-256 与负责人齐全时，清单行才允许标记 `verified`。校验器不读取或上传图片，也不把清单晋升为证据；真实原图、授权文件和人工审核仍由 `SKU-001/002` 阶段门控制。

`BAS-020` 把上述清单合同接入正式证据链：Web 与 API 成对接收真实原图和独立权利文件，拒绝扩展名与文件签名不符的伪文件，分别固化 SHA-256、来源、SKU、变体、素材角色和授权关系，并将证据追加到最新 Quality Passport 草稿。readiness 明确区分缺失、已捕获待审批和已批准；只有七角色全部进入已批准 Quality Passport 才允许完整图片生产。该入口不调用 ComfyUI、模型或外部生成服务；当前仍缺三个真实 SKU、原件和权利文件，因此不改变 `SKU-001/002` 的阻塞状态。

`BAS-022` 只开放 `ozon-retouch-v1`：已批准真实原图经官方 `LoadImage → ImageScaleToTotalPixels → SaveImage` 核心节点做 4MP 等比保真处理，任务状态、模板、Prompt、请求人和时间写入 ContentAsset，完成结果以不可变 Evidence 回收。真实本机队列/历史/下载烟测成功，但输入是技术测试截图，不是商品原图；`composite`、`infographic`、生成模型、自定义节点、自动 QA 和自动上架仍保持关闭。

`BAS-023` 收紧现有 JSON 合同而未新增表或迁移：图片审核必须一次恰好提交八项检查，每项含结论与人工依据，服务端补写可信审核身份和 UTC 时间；缺项、重复、未知检查与无依据结论均失败关闭。已批准图片可在 Web 中与正 CM3 场景一起建立 Ozon Listing 草稿，草稿的图片必须精确匹配同 SKU ContentAsset 的不可变产物 Evidence，并保存资产 ID 血缘；系统只创建 `listing.publish` 待审批对象，没有平台发布执行器。证据见 `docs/project/evidence/20260718_BAS_023_IMAGE_QA_LISTING_HANDOFF.md`。

`BAS-054` 已关闭 Ozon 财务暂存到正式事实之间的来源复核缺口：费用、退货和结算导出必须由非上传者确认真实账户、期间、非公开样例和导出完整性，复核以不可变 Evidence 和双血缘保存；缺少接受、任一拒绝、原件损坏或血缘歧义均阻断事实晋升。未新增表、迁移或依赖，普通订单导入不受影响。真实报表、会计字段映射和三方对账仍依赖 UNK-006，不得将本能力表述为已取得店铺财务数据。证据见 `docs/project/evidence/20260719_BAS_054_OZON_FINANCE_REPORT_REVIEW.md`。

`BAS-055` 已把上述复核门交付到非技术 Web：财务文件上传后明确显示交接编号、导入类型、暂存行数、复核状态和“未入账”；Reviewer/Compliance/Admin 身份可读取状态并逐项确认四个来源条件，普通 operator 只看到交接说明。页面没有自动晋升、会计映射或对账按钮。真实双身份业务演练和首份 Ozon 财务样本仍属于 UNK-006。证据见 `docs/project/evidence/20260719_BAS_055_OZON_FINANCE_REVIEW_WEB.md`。

`BAS-056` 已关闭“来源复核通过后可用任意证据登记 Ozon 费用码”的旁路：实际费用码只从已接受的 Ozon 费用导入中出现，由非上传者逐码选择会计类型、符号规则和有效期，批准记录与原始报表、导入任务和映射三向绑定；任一 Evidence 损坏、复核失效或血缘缺失都会使映射失效并阻断事实晋升。通用费用映射 API 明确拒绝 `provider=ozon`。该门不自动入账、不猜测费用语义，也不替代真实财务负责人批准。证据见 `docs/project/evidence/20260719_BAS_056_OZON_FEE_MAPPING_APPROVAL.md`。

`BAS-057` 已补齐财务报告下载与独立复核之间的期间交接合同：所有带时间窗口的 Ozon 导入在 API 边界必须提交查询起止日期，服务端校验 `YYYY-MM-DD`、顺序和最长 31 天，并把标准化期间写入原件 Evidence；复核状态和不可变复核 Evidence 均回显该期间。同一文件哈希只可在原 Evidence 存在且期间完全一致时复用，旧 Evidence 无期间、血缘缺失、改报其他期间、非法期间或复核期间血缘不一致均失败关闭。订单保留期间上下文但不进入财务复核；没有新增表、服务或依赖，也没有改变财务事实仍需独立晋升的边界。全量 `264 passed` 且 G-1 `PASS`。首份真实文件仍须按 `2025-10-01` 至 `2025-10-31` 下载、上传并由另一身份复核，故 `OZN-002/UNK-006` 状态不变。证据见 `docs/project/evidence/20260719_BAS_057_OZON_FINANCE_REPORT_PERIOD_HANDOFF.md`。

`BAS-051` 的官网来源已于 2026-07-19 复核并同步到机器注册表：Ozon 跨境物流合同、广告帮助和跨境巴士仓库帮助均登记为规则/风险来源，不能替代账户账单。真实 Authority Radar run `111` 记录两项 307 与一项 403；三个入口因此按现有 `manual + requires_review` 管理，不新增绕过站点保护的采集器。配置调整后的 run `112` 为 27/27 来源有状态、0 failing。该维护不解除真实采购、物流、Ozon 结算与银行原件阻塞；证据见 `docs/project/evidence/20260719_BAS_051_COST_SOURCE_AND_KUAJING84.md`。

`BAS-059` 关闭了第三方选品/ERP/计算器被手工标级后直接推动询价的缺口：服务端在哈希、时效、测量合同和需求报告绑定复验之后，再按指标检查 Evidence 等级。C/D 级资料仍写入观测账供探索和交叉验证，但不进入聚合值、来源族或三报价放行；需求、竞争、供货和退货至少要求 A/B，合规红线要求 A。Web 默认把新研究原件按 C 级收集、显示每份原件等级和低权威阻塞，不允许第三方资料替代真实 Ozon 报告、供应商原件或官方规则。该能力不解除 `SKU-000/001`、真实报价和经营阈值复核阻塞；证据见 `docs/project/evidence/20260720_BAS_059_CANDIDATE_EVIDENCE_AUTHORITY_GATE.md`。

`BAS-060` 进一步取消了对上传人自报等级的信任：生产候选评估只读取指标级独立权威复核证明。Reviewer/Compliance/Admin 必须与上传者分离，核对真实完整原件、适用范围和 A/B 权威依据；接受时三项全部为真，拒绝结论优先并永久阻塞该原件—指标组合。服务在候选录入、复评和三报价交接时重新验证证明与原件哈希、身份、指标和血缘；Web 提供非技术复核入口但不自动采购或上架。真实双用户演练仍随 `BAS-026` 执行；工程证据见 `docs/project/evidence/20260720_BAS_060_CANDIDATE_EVIDENCE_AUTHORITY_REVIEW.md`。

`BAS-061` 将萌啦、Seerfar、妙手 ERP 和 51Selling 从零散链接收敛成产品模式注册表：借鉴低门槛成本模板、30–90 天趋势与竞品监控、采集箱、批量编辑、订单/库存/物流异常工作台；拒绝照搬未知公式、一键搬运即刊登、自动跟价或把第三方 SaaS 变成事实唯一真源。Seerfar Open API 当前只确认官网入口，文档抓取超时，保持 `requires_review`；正式适配必须先完成数据血缘、协议、权限、速率和真实样本对账。产品与工程映射见 `docs/project/11_COMPETITOR_CAPABILITY_BENCHMARK.md`。

`BAS-062` 复用现有不可变 Evidence、Blob、Lineage 和指标级权威复核，不增加表、迁移、插件或第三方运行依赖。候选工作台现可把 Seerfar、萌啦、妙手、51Selling 或其他来源的手工导出作为研究信号固化，并保留提供方原始字段与候选关联；专用服务拒绝敏感字段、凭证 URL、非法许可状态和无界关联。输出固定标记为辅助资料，通用 Evidence/Lineage 入口不能伪造研究角色，且不存在自动 Product、采购或 Listing 路径。Open API 仍保持延期，直到正式准入合同和真实样本对账完成。证据见 `docs/project/evidence/20260720_BAS_062_RESEARCH_SIGNAL_INBOX.md`。

`BAS-063` 没有复制萌啦计算器或增加第二套利润引擎，而是在现有 `ProfitScenario`/Evidence/CM3 上固化 `ozon-ru-full-cost-v1`。场景 JSONB 以向后兼容包装保存公式模板和逐项状态，不增加表或迁移；Web 补齐仓储、税费、汇兑、资金占用、售后和损耗输入，并要求 15 项分别声明预估、实际或未知。`unknown`、缺证据和非零未分类成本阻断采购评审与 Listing；只读解释接口返回逐项来源、保本价、安全边际及售价 ±10% 敏感性，且明确 `automatic_pricing=false`。验证为 284 项 Python、12 项 Web、Next 生产构建和 PostgreSQL/容器/备份恢复 G-1 PASS；证据见 `docs/project/evidence/20260720_BAS_063_VERSIONED_FULL_COST_TEMPLATE.md`。

`BAS-064` 复用现有 `GateReadinessService`，没有新增表、接口或依赖。`/v1/operations/readiness` 现在附带只读 `candidate_portfolio`：历史目录和未通过候选资格门的 Product 不进入组合；当前每家供应商只保留最新报价，并只读取该报价的最新利润场景，旧报价上的历史正利润不能继续满足 readiness。服务端按“可进入人工选择优先、CM3 其次、SKU 稳定排序”返回 Passport、供应商数、完整正 CM3、最佳供应商及阻断原因；Web 使用同一合格候选集合加载 Passport、素材和三报价，不再取任意前三个 Product。所有自动选品、采购、定价和 Listing 标志固定为 `false`。证据见 `docs/project/evidence/20260720_BAS_064_THREE_CANDIDATE_PORTFOLIO.md`。

`BAS-065` 继续复用同一个 readiness 和现有 `operations-control/queue`：未满足 requirement 由后端投影为稳定 `gate_requirement:*` 阻断，保留 Gate、来源对象、当前/目标、责任角色、下一动作和原始 details；没有发生时间的资料缺口不伪造 SLA。Web 异常中心把这些经营阻断与已有事故、受限命令和观察窗口并列，后者仍按真实截止时间和升级等级处理。该增量未新增表、迁移、队列、接口或依赖，也不授予自动修复或平台写权限。证据见 `docs/project/evidence/20260720_BAS_065_EVIDENCE_BACKED_EXCEPTION_WORKSPACE.md`。

`OZN-002/UNK-006` 于 2026-07-19 完成已登录只读追溯：默认七月以及五月、六月整月应计明细均为空；余额页选择 `2026-01-01` 至 `2026-07-19` 后，销售、退货和 Ozon 代理佣金均为 `0 ₽`。同时当前余额与七月月初余额均为 `8,568 ₽`，所以只能把后续搜索范围收敛到 2025 年或更早，不能据此猜测余额组成或费用码。没有下载空报告、读取密钥或执行账户写操作；真实费用字段、代码和结算周期仍未获得，阻塞不变。证据见 `docs/project/evidence/20260719_OZN_002_ACCRUAL_READONLY_CHECK.md`。

同日继续使用 Ozon Seller 原生期间筛选后，真实样本已收敛到 `2025-10-01` 至 `2025-10-31`：销售 `15,658 ₽`、期间净应计 `−9,943 ₽`、代理佣金 `−2,975 ₽`、配送 `−313 ₽`、合作伙伴服务 `−7,753 ₽`、赔偿净额 `139 ₽`、其他应计 `−14,699 ₽`；2025 年 11 月与 12 月销售、退货和代理佣金均为零。2026-07-20 已下载该月官方计提 XLSX：4,459 字节，15 行，SHA-256 `489d4518e8e8c1f00c135cd1380ed636ff5e3ee1768182a9146b3cc4b1dcae68`；15/15 行已正式存入本机 PostgreSQL，Evidence `evd_902fe12a454e4703b88b6ad7314ed652` 通过 Blob 完整性复验，并以 `source_for` 血缘绑定 import `imp_76eab9701e954896a6f67ccdbb845cb6`。当前来源复核仍为 pending（0 次复核），`ozon_accrual` 正式事实和财务分录均为 0，分类入口按合同返回阻塞。尚无独立 Reviewer、月度代理/服务文件、结算、银行或 FX 对账，因此 `FIN-001/OZN-002/UNK-006` 继续阻塞。证据见 `docs/project/evidence/20260720_BAS_066_OZON_OFFICIAL_ACCRUAL_EXPORT.md` 与 `docs/project/evidence/20260720_BAS_068_OZON_ACCRUAL_FORMAL_PENDING_REVIEW.md`。

## 第一批四窗口：只冻结合同与模板

| 窗口 | 文件所有权 | 输入 | 输出 | 验收 | 禁止事项 |
|---|---|---|---|---|---|
| A 治理 | `docs/project/00–04` | 方案母稿、Backlog、负责人决定 | 章程、Gate、RACI、未知项 | 所有当前任务有 Gate/Owner/验收 | 不改业务代码/迁移 |
| B SKU 准入 | `docs/project/templates/T03*` + SKU 资料区 | 三个真实 SKU、报价、样品、合规资料 | 三 Passport 和 Episode 包 | 3/3 字段完整，缺失项明确 UNKNOWN | 不猜硬事实 |
| C 财务 | `docs/project/templates/T04*` + 财务资料区 | Ozon 费用、结算、银行、FX | 费用字典、三方对账、现金模板 | 数字可复算、差异可隔离 | 不用浮点/“其他”吞差异 |
| D 工程合同 | ADR、数据合同、连接器矩阵 | 当前代码、官方 API/报表 | 证据层/Ozon/安全实现合同 | 能直接生成测试与迁移验收 | 不同时修改 `api.py` 和共享迁移 |

并行原则：每个窗口拥有独立文件区；`api.py`、共享领域对象和 Alembic 迁移由单一集成人合并。多个窗口不得同时修改同一文档或 Schema。

## 支撑性 AI 运行项

以下能力支持项目，但不能替代三个真实 SKU、Ozon 权限和经营证据：

| ID | 任务 | 验收 | 状态 |
|---|---|---|---|
| INT-001 | 30 分钟权威来源采集与去重 | Windows Task 结果 0；单源失败隔离 | DONE |
| INT-002 | 确定性晨报与本机健康检查 | 三条 OpenClaw command job 连续错误归零 | DONE |
| INT-003 | 本地候选分析 Evidence Gate | 证据外年份/版本、无 event_id 自动拒绝 | DONE |
| INT-004 | 智谱并行 Auditor | 20 条金标集和评分器已完成；本地基线 19/20（95.0%）、90% 不退化门已启用；GLM-5.2 独立候选仍需有效额度 | BLOCKED |
| INT-005 | SEC/企业 IR 资本 watchlist | 候选清单已完成；待批准 CIK/证券代码和合规 UA | NEEDS_REVIEW |
| INT-006 | 国内平台只读连接器 | 六平台合同已完成；商家账户、应用审核、最小权限 Token 仍缺失 | BLOCKED |

## 第二批代码开发（模板冻结后）

1. 不可变证据对象、血缘和双时间。
2. Ozon 暂存行到正式订单/费用/退货/结算事实的转换。（工程骨架 DONE；一手样本映射 BLOCKED）
3. 财务账本、三方对账、差异队列和 13 周现金流。（工程骨架 DONE；真实口径验收 BLOCKED）
4. API 身份、可信审批、原子 outbox、Command/Result/Readback/Kill Switch。
5. 里程碑、准入和异常经营看板。

## 每日调度规则

- 每个窗口每天最多一个 `IN_PROGRESS` 主任务。
- 开始前填写任务合同；结束时给出证据、状态和下一个阻塞。
- 发现跨窗口 Schema 变更时暂停实现，先提交 ADR/数据合同。
- 每日整合只做交叉引用、冲突消解和验收检查，不追加新愿景。
- 每周从 P0 删除不再提高当前 Gate 通过率的任务。
