# KJDS 团队总控塔与老板运行手册

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-OPS-018 |
| owner | 人类 Business Owner（待实名绑定） |
| operator | Global Chief Commerce Officer / Chief of Staff |
| status | Engineering ready; human and business gates pending |
| version | 1.4 |
| reviewed_at | 2026-08-08 |

## 1. 已经搭好的系统

当前工程已经冻结 18 个核心岗位合同、十二个有界 AI 专家席位、20–40 人专家池容量目标、
五个独立控制角色和俄罗斯战区 Cell，并把用户指定的四条主线接入同一团队总控塔：项目总控与商业化、SKU 闭环、
双轮商业化、LG-001 Exact-scope。老板读取一张 `brief`，系统只给一个可推进动作；未 kickoff
时第一动作是打开 90 天战役首阶段，团队通过 `advance` 写回既有 OperatingTask/Event，不另建
Campaign 或任务账。

这证明“组织合同、调度逻辑、权限边界和界面”已具备，不证明真人已经聘任、俄罗斯真实
业务闭环或付费客户已经完成。系统里的 AI 角色在真人绑定前保持 proposal/shadow。

BAS-215B 进一步把 14 个全域 AI ERP 领域角色、8 个 Squad 和六项 EAERP WBS 的静态合同
接入同一张 `brief`。它只增加六个只读老板投影，不创建第二任务账或 ERP 执行权威；真人、
运行容量、任务进展和发布排期仍由各自权威决定，因此当前全部保持 `UNKNOWN/NOT_STARTED`。

## 2. 企业组织与拍板结构

| 层级 | 唯一责任 | 有权决定 | 无权绕过 |
|---|---|---|---|
| Owner/董事会 | 生存边界与资本纪律 | 使命、最大损失、13 周现金边界、任免总负责人、停止公司级赌注 | 法律、财税、付款与职责分离 |
| 全球经营总负责人 | 唯一经营 P&L 与组合取舍 | 不超过三项周结果、资源优先级、内部 WIP、继续/暂停/退出 | 自审自批、失败 Gate、Permit、平台凭据 |
| Chief of Staff/总控 PMO | 让决定进入同一任务和证据链 | 会议节奏、Owner/SLA、依赖、升级、复盘 | 经营拍板和专业签字 |
| 12 专家席位 | 各自领域产出 | 研究、方案、执行草案、Evidence handoff | 跨域最终批准 |
| 5 独立控制角色 | 反证与硬 Gate | 验证、风险否决、批准、执行和回读 | 替作者补造证据或强制 Go |
| 俄罗斯 Cell | Ozon 首战区交付 | 本地市场、平台、合规、物流、财务、内容和增长执行 | 继承其他国家或平台权限 |

18、12、20–40 和 5 都是机器合同数量，不是到岗人数。每个真人岗位必须登记主责、不同替补、
30/60/90 天结果、工具/数据白名单、SLA、预算状态、最大损失、独立 Reviewer、利益冲突、
任命/资质 Evidence 和交接条件，否则工作台保持 `UNKNOWN`。

## 3. 老板每天只看五件事

1. 哪个 SKU/客户的 Actual Cash CM3 已由订单、平台结算和银行到账对平；没有原始
   Evidence 就显示 UNKNOWN，不看 GMV 幻觉。
2. 13 周现金、已承诺现金和本轮最大损失是多少；任何实验先写停止条件再花钱。
3. 当前四条主线唯一下一动作是什么，谁负责，何时到期，为什么它比其他动作更重要。
4. 哪个硬 Gate、Evidence 时效、WIP 或共享写域正在阻断，谁拥有解除权。
5. 俄罗斯真实经营轮和客户商业化轮各自带来了什么可回读结果，是否值得继续、缩小、转向
   或停止。

## 4. 产品与商业化建设建议

KJDS 的切入口应是“利润真相 + 受控执行工作台”，不是一开始做通用跨境 ERP。最先售卖
的不是软件席位，而是可核验的俄罗斯/Ozon 利润诊断与经营闭环交付：把商品、报价、物流、
平台费用、结算、银行到账和 Actual Cash CM3 放到同一 Evidence 链，再把高频流程沉淀为
产品。

商业化按三层推进：

1. **自营验证**：先跑通一个真实 SKU 的现金闭环，证明系统对自己的经营有效；
2. **产品化服务**：选择 1–3 个设计伙伴，按诊断包/托管交付收费，记录交付毛利、用时、
   复用率和客户回读；
3. **软件化**：只有同一问题被多次付费、输入输出稳定、人工步骤可标准化后，才转订阅或
   使用量计费。

现阶段资本分配建议按决策包而不是绝对金额控制：约 70% 投向俄罗斯 SKU 利润与现金真相，
20% 投向首个 C0 设计伙伴交付底座，10% 保留给来源研究和高杠杆自动化。该比例只是组合
护栏，不构成预算批准；每笔仍需 Owner、最大损失、停止条件和现有财务 Gate。

## 5. 运行节奏与拍板规则

| 节奏 | 必须输出 | 拍板人 |
|---|---|---|
| 每日 15 分钟 | 唯一下一动作、Owner、SLA、blocker、今日最大损失 | 总负责人 |
| 每周一 45 分钟 | 最多三项周结果、明确不做事项、资源和停止条件 | Owner + 总负责人 |
| 每周三 Gate Clinic | 合规、财务、Evidence、架构与客户交付的反方审查 | 独立控制角色 |
| 每周五 60 分钟 | 结果回读、现金、失败、UNKNOWN、继续/缩小/停止 | Owner |
| 每月组合会 | 国家/平台/SKU/客户投入产出与关键任免 | Owner/董事会 |

没有 Evidence 的讨论只能形成假设；没有唯一 Owner 的事项不得进入进行中；同一专家默认
只有一个 active task；跨泳道共享写域必须先由总负责人裁决。法务、财务、认证、安全与
发布 Gate 只有阻止权，没有替经营者制造成功的权力；总负责人拥有业务取舍权，但没有
强制失败 Gate 放行权。

## 6. 分阶段建设与验收

| 阶段 | 验收结果 | 当前状态 |
|---|---|---|
| S0 控制塔工程 | 四条主线、exact scope、唯一动作、幂等、角色、Evidence、Kill Switch | DONE_ENGINEERING |
| S1 真人组织绑定 | 五个最小责任节点实名、替补、SLA、专业资质和冲突声明 | PENDING_HUMAN |
| S2 俄罗斯经营真相 | 1 个 SKU 订单→结算→银行→Actual Cash CM3 对平 | BLOCKED_EVIDENCE |
| S3 首个商业 C0 | 设计伙伴、SOW/DPA/SLA、交付单位经济和客户回读 | PREP_ONLY |
| S4 可复制产品 | 至少三次付费复用、稳定输入输出、人工成本下降、续费信号 | NOT_STARTED |
| S5 第二战区 | 独立规则包、身份、财税物流、Native Caps 和退出 Gate | RESEARCH_ONLY |

企业家现在最重要的三个动作是：实名任命 Business Owner 与 Russia/Ozon Owner；给一个
SKU 和一个设计伙伴分别设定最大损失与停止条件；要求所有周会只围绕 `brief` 的唯一动作
和 Evidence 回读。完成这三项，系统才从“工程团队已搭好”进入“经营组织真正运行”。

## 7. 工程与权威边界

`GET /v1/team-control/brief` 可由有权查看的角色读取；
`POST /v1/team-control/advance` 只允许 operator/admin。推进接口不是 Kill Switch 安全白名单，
紧急停止时必须关闭。continuation 绑定注册表、当前泳道、exact scope、动作、预期状态和
五类经营交付投影、六类全域 AI ERP 投影共同形成的 `decision_basis_sha256`；
完成和停止必须有当前 exact-scope Evidence；战役首阶段从 `acknowledged` 进入 `in_progress`
也必须绑定 Evidence，该 `start` Event 才是 kickoff 真源。

本切片没有数据库迁移，避免与当前迁移租约冲突；写入沿用 OperatingTask/Event。未来只有在
多进程并发量要求出现时，才在同一权威账增加数据库唯一幂等约束和事务 Outbox，不得新增
旁路 `team_tasks`、决定账或 Agent 自主外写。

## 8. 18 人核心 RACI 与替补合同

| 核心角色 | Accountable 结果 | 独立 Reviewer | 主要协作 |
|---|---|---|---|
| GCEO | 唯一组合 P&L、周目标、继续/转向/停止 | Business Owner | Program Director、Finance |
| Program Director / Chief of Staff | WBS、关键路径、RAID、决定落地 | GCEO | Delivery PMO、各泳道 Owner |
| Delivery PMO Lead | 版本、里程碑、验收、客户交付 Evidence | GCEO | Product、QA/Release |
| Russia/Ozon GM | 首战区经营结果 | GCEO | Ozon、市场、物流、财务 |
| Product Lead | JTBD、范围、路线图、用户验收 | GCEO | UX、工程、客户成功 |
| Chief Architect | 目标架构、ADR、权威边界、恢复与技术债 | Risk Authority | 后端、SRE、QA |
| Market/Category Lead | 类目、SKU 组合与预检 | Product Lead | 市场雷达、采购、财务 |
| Ozon Operations Lead | 平台规则、Listing 与运营输入 | Russia GM | 内容、广告、物流 |
| Sourcing/Quality Lead | 三报价、样品、工厂、包装、质检 | Product Lead | 类目、物流、认证 |
| Logistics/Customs Lead | 头程、关务、仓配、退货和全成本 | Russia GM | 关务专家、财务 |
| Finance Controller | 三账、Actual Cash CM3、13 周现金 | Risk Authority | GM、物流、Owner |
| Growth/Sales/CS Lead | 设计伙伴、C0、单位经济和价值回读 | Product Lead | PMO、法务、财务 |
| Backend Domain Engineer | 领域权威与不变量 | Chief Architect | 数据、QA |
| Backend Integration Engineer | 平台 Adapter、幂等与回读 | Chief Architect | SRE、平台运营 |
| Frontend/UX Engineer | 老板工作台、采用与无障碍 | Product Lead | QA、客户成功 |
| Data/AI/Evidence Engineer | 数据血缘、Benchmark selector、Agent Eval | Chief Architect | Finance、Verifier |
| DevSecOps/SRE Engineer | 身份、部署、观测、备份恢复与安全 | Risk Authority | Architect、QA |
| QA/Release Lead | 独立验收、发布/回滚 Evidence | Delivery PMO | 全工程、Verifier |

每行只能有一个主责；替补必须是不同真人且在交接条件内才可接管。Reviewer 不得等于当前
工作执行者。真人 Business Owner、Verifier、Approver、Risk Authority 和 Executor 是五个
独立控制身份，不因出现在协作链就合并职责。

## 9. 专家池调用规则

专家池容量目标为 20–40 人，按九类能力签约：俄罗斯法务、税务、EAEU/EAC 认证、关务物流、
采购工厂质检、俄语内容与客服、Ozon 类目广告、安全/架构/发布审计、未来 Country Lead。
调用时必须形成一个 OperatingTask，包含 exact scope、唯一 Owner、输入 Evidence、交付物、
Reviewer、验收、预算、最大损失、停止条件、SLA 和回读。专业意见只有在执业/资质作用域、
有效期和利益冲突 Evidence 当前时才可进入 Gate；专家名录或 AI 输出不能替代专业签字。

默认不把专家池全部转为全职固定成本。需求反复出现、SLA 持续不可满足、知识需要沉淀或
外包总成本高于内部团队时，由 Owner 依据 13 周现金和 `best_solution` 再决定 build/buy/
partner/defer/no_action。

## 10. 90 天战役与会议节奏

计划基线为 2026-08-07，目标结束日为 2026-11-04；无 kickoff Evidence 时实际战役日为
`UNKNOWN`。

| 阶段 | 结果门 | 固定会议 |
|---|---|---|
| Day 1–7 组织冻结 | 主责/替补、一个目标 SKU/候补、设计伙伴、WBS/RAID、现金底线与停止条件 | 每日总控；周一三结果；周三 Gate Clinic |
| Day 8–30 真实输入 | 三 SKU 预检、三报价、Passport、合规物流成本、Ozon/银行只读权威、竞品队列 | 每周经营真相审查；周五 Evidence 回读 |
| Day 31–60 Alpha/现金闭环 | 商品→银行链、Actual Cash CM3、生产身份/恢复/安全/回滚、诊断交付包 | 每周独立失败审查；每次发布前 Gate |
| Day 61–90 商业/Top1 审计 | 1–3 个设计伙伴、至少一个受控交付、单位经济、十二维独立审计、Owner 拍板 | 客户验收会；最终继续/缩小/转向/停止会 |

A、B、C、D、E、I、L、M 是主战泳道；F–H 只保持准备态。每周公司级结果不超过三项，
同一专家默认一个 active task，共享写域只有一个集成人。日历到期、泳道完成或任务关闭都
不能替代正式 Gate PASS。

## 11. 老板 `brief` v1.4

第一屏只显示组织合同/绑定、13 周现金、实际战役日、最大已验证 Top1 差距和五个 Gate；
第二屏是唯一下一动作；第三屏是四阶段关键路径；第四屏是十二维评分卡；第五屏是组织缺口、
专家池和四条现有业务主线。所有值来自服务端，Web 不计算排名、利润、Gate 或战役完成度。

统一状态为 `VERIFIED/PARTIAL/BLOCKED/STALE/CONFLICTED/UNKNOWN`。Top1 只能显示既有
StrategicBenchmark 在同一 metric/cohort/market/window 的 leader refs；至少五个合格 peer
且 KJDS current observation 已在 leader refs 中才显示 `METRIC_LEADER`。无数据、过期、
重复最新组和 authority drift 必须显式显示，所有输出固定 `global_top1_claim=false`。

现金缺期初余额、CashPlan、批准 FX、签署现金底线或最大损失时不调用预测。组织、关键路径、
Top1、现金和 Gate 的投影哈希共同进入 continuation；网络失败重试复用同一幂等键，成功或
continuation 变化后才换键。

全域 AI ERP 增量提供六个服务端字段：

| 字段 | 当前能证明 | 当前不能证明 |
|---|---|---|
| `squad_readiness` | 8 个 Squad 的 Owner/Reviewer、能力和首验合同完整 | 真人到岗、资质和可用工时 |
| `role_conflicts` | 6 条职责分离规则完整 | 当前身份没有冲突 |
| `parallel_execution` | `1 总控 + 最多 3 专业 Agent/Writer` 等上限 | 当前占用量或仍有空闲容量 |
| `integration_queue` | EAERP-01..06 的 DAG、Squad 和泳道亲和 | OperatingTask 已启动或完成 |
| `capacity_risk` | 容量红线和 Stop 合同 | 当前容量足够或风险已解除 |
| `next_release_train` | 每周两次集成列车政策 | 下一班日期、候选已准入或 Gate PASS |

六字段总体必须保持 `UNKNOWN`，只有嵌套 `program_contract.static_contract_integrity` 可以显示
`VERIFIED`。scope-invalid 时不读取 Program；Program 缺失显示 UNKNOWN，合同/来源/snapshot/
动态真相或权限边界漂移则失败关闭。Tower 固定 BAS-215A 已复核的 registry、source-bundle
和 compiled snapshot；只重算自报哈希但未更新受信合同的投影仍被拒绝。正式合同升级后的
Program 快照变化使旧 continuation 失效，单纯 `as_of`
变化不失效。前端仍不得计算或补造这六类状态。

HTTP 200 使用完整严格响应模型，保存的 OpenAPI 以具名 `$ref` 固定六字段为 required 并拒绝
额外顶层键。scope-invalid 或 Program 未连接时允许每个字段缩减为带 reason code 的最小
`UNKNOWN`，但不得省略字段。老板页逐一展示六个投影及 Program snapshot；页面只格式化
服务端顺序与值，不计算角色冲突、执行波次、可用容量、发布候选、Gate 或排期。键盘焦点、
状态播报、语义 disclosure 和 390px 无横向溢出属于发布验收。

对外 `projection_sha256` 保留完整 `as_of`，用于证明每次读取的快照；推进用的
`decision_basis_sha256` 则剔除纯观测时间和原始快照时间噪声，保留组织绑定、任务/Event、
现金闭环状态、Benchmark leader refs、Gate readiness 和权威语义哈希。连续刷新不会令当前
动作无故过期；任一业务权威变化仍会使旧 continuation 失效。

## 12. Coding Agent 交付纪律

复杂任务遵循 `AGENTS.md` 的八步流程：项目认知、任务分级、文档先行、至少双设计比较、
增量实现、持续验证、独立审查、文档/代码共同演进。本轮实施顺序是注册表校验→后端五投影
→老板 Web→外部权威，且每片可独立测试/回滚。新增外部权限、真实付款、合同、平台写、
真人任命或重大范围变化才暂停请求决定；测试通过不得升级任何未到达的经营 Evidence。

## 13. Campaign 调度与 as-of SKU 现金归因

四阶段不是第二套 flow。每个阶段按需编译为 `team_control:campaign:*` OperatingTask；打开和
领取只表示责任接管，首阶段带 Evidence 的 `start` 才把 kickoff 从 `UNKNOWN` 变为
`VERIFIED` 并开始计算实际战役日。阶段 `resolve` 是 Evidence-backed handoff，仍保持
`formal_gate_pass=false`；没有同 scope canonical Gate PASS 时，系统不自动打开下一阶段，
而是把唯一动作交回现有 LG-001、SKU、项目总控或商业化 flow 去补齐缺口。

现金面只读现有 `ScopedSettlementCashWorkspace`。同一 cycle 必须同时满足订单 Fact、平台
结算、银行现金、三账 `reconciled`、Actual Cash CM3 available、Evidence 当前且 exact scope，
并由严格同 scope/current-authority 的 order-grain Profit 权威发行 `canonical_order_sku_receipt_v1`，
再由 runtime 从 canonical dependencies 独立构造的 server-owned
`ScopedProfitOrderSkuReceiptAuthority` 回读验证。该对象必须与可变 Profit adapter 不同，Settlement
不得从 adapter 动态取得 verifier，且回读 source snapshot 必须等于实际消费 Profit snapshot。
receipt 绑定唯一 Order Fact、canonical Product/SKU、稳定 Profit row
basis 与现金守恒，
才把独立字段 `single_sku_attribution_status` 显示为 `VERIFIED`。兼容老板页既有“真实 SKU
现金闭环”标签的外层 `actual_cash_truth.status` 必须保持 `PARTIAL`；老板页只显示状态、计数和
hashed lineage，不显示 Product、SKU、订单号、银行标识或金额。缺 SKU 归因的 reconciled cycle
同样为 `PARTIAL`；offer 映射和退货退款观察窗终结仍为 `BLOCKED_EVIDENCE`，因此不得称最终全
生命周期闭环。即便当前归因已验证，俄罗斯经营 readiness、13 周现金和正式 Gate 仍保持
`UNKNOWN/BLOCKED`，直至相应独立权威全部到达。

归因 verified count 还要求 source=`ready`、完整单页、excluded=0、无 gap/blocker，且
`order_count=identity_count=1`；partial/blocked/no_data 一律归零。完整审计 snapshot 保留观测
`as_of` 与顶层 Profit snapshot，语义 lineage 则排除这两类时间噪声，所以同一业务 T/T+5 不会
使 continuation 过期，而 Order/Product/SKU/row/current-authority 任一变化仍会使旧动作 stale。

## 14. 全域 AI ERP Squad 使用规则

14 个领域角色和 8 个 Squad 是可执行工作的组织合同，不是当前真人名册。每个 Squad 的
`first_acceptance_contract` 是未来验收条件，不是已发生结果；`integration_queue` 中的
`NOT_STARTED` 与依赖波次也不能从 Plan、日期或静态 registry 自动晋级。要开始 EAERP 工作，
仍须在现有泳道创建唯一 OperatingTask，绑定 Owner/替补、exact scope、输入 Evidence、写集
租约、Reviewer、预算/最大损失、Stop、回滚和交接条件。

运行容量只能由 active-work authority 读取后证明；当前 Program 不连接该权威，所以
`observed_active_writers`、专家 WIP、泳道 WIP 和周结果均为 `null`。发布列车同理：每周两次
只是节奏上限，候选、日期和 Gate 由现有 Release/QA 权威决定。任何 Squad 不得因静态合同
获得数据库、资金、平台写、Approval、Permit 或真人身份。
