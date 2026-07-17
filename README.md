# KJDS — AI 跨境电商控制平面

这是面向俄罗斯市场的 AI 跨境电商经营系统。生产数据平台采用 Supabase PostgreSQL，本机 PostgreSQL 保留作开发和离线备用。系统当前覆盖：

- 市场原始观察、来源证据和可复算机会评分；
- Product / Compliance / Quality Passport；
- 图片、视频、文案 Brief，生成资产和五项 QA；
- 带预算封顶与止损线的增长实验；
- 订单费用账本和订单级 CM1 / CM2 / CM3；
- 高风险动作双人审批；
- 受模式和幂等约束的 Agent 任务；
- 稳定的领域事件与外部连接器协议。
- 1688、淘宝、天猫、京东、拼多多、Alibaba、AliExpress、Amazon、Temu、Shopify 和 WooCommerce 的统一供货连接器目录；
- 采购价、国内运费、国际物流、包装、关税、尾程、平台费、广告与退货准备金的单品 CM3 和保本价；
- 通过产品护照、正 CM3 和双人审批门禁生成 Ozon 上架草稿。

整体边界见 [架构说明](docs/architecture.md)，经营执行见 [90 天执行总纲](Ozon_90天执行总纲.md)。

## 当前目录

```text
apps/control_plane/
  api.py              HTTP API
  domain.py           稳定领域实体和状态
  repository.py       测试/开发存储适配器
  services.py         商品、订单、利润、审批、Agent
  intelligence.py     市场数据和机会评分
  content_growth.py   图片/视频/文案与增长实验
  connectors.py       Ozon/广告/物流/结算连接器协议
  ozon_contracts.py   Ozon 订单/费用/退货/结算版本化数据合同
  facts.py            暂存行到不可变正式事实的晋升与血缘
  finance.py          费用字典、FX、三方对账和 13 周现金流
  sourcing.py         全球供货商品、物流利润和上架草稿规则
  source_connectors.py 平台能力目录
  sourcing_store.py   Supabase/PostgreSQL 持久化适配器
  procurement.py      样品采购状态机、供应商实绩与备用方案
  decision_contracts.py 版本化交互模式与不可变决策合同
  decision_lifecycle.py 分权分析、独立复核、正式决定、结果与校准
  causal_experiments.py 因果实验预注册、稳定分流、结果账与 SRM 门禁
  causal_knowledge.py 实验独立复核、适用边界、复现关系与因果知识账
  causal_policies.py 有效知识到条件策略、影子阶段和逐级放量合同
  policy_shadow.py 不可变策略评估、零暴露影子批次与独立审批交接
  execution_plans.py 目标绑定、前置快照、回滚合同、执行审批与零写入预演
  limited_executor.py 默认关闭的命令队列、领取租约、平台回执与补偿回滚状态机
  ozon_worker.py 隔离 Seller API 凭证、读取真实状态、异步导入确认与回执上报
  post_execution.py 执行后观察合同、不可变指标、护栏冻结与补偿触发
  capability_economics.py 能力增量、避免损失、运行成本、事故损失与治理建议
  incident_recovery.py 生产事故、人工接管、恢复清单、独立复核与演练账
  operations_queue.py 事故、执行命令与观察窗口的 SLA 队列和升级账
  pilot_readiness.py Ozon 只读试点边界、控制证明、独立复核与准入门禁
migrations/
  001_initial.sql     持久化模型与事务事件表
tests/
  test_core.py        核心业务约束测试
```

## Supabase 配置

1. 在 Supabase 新建项目，进入 **Connect**，复制 Session pooler 连接串（端口 5432）。
2. 复制 `.env.example` 为 `.env`。
3. 将连接串协议从 `postgres://` 改为 `postgresql+psycopg://`，并保留 `sslmode=require`。
4. 运行 `uv run python -m alembic upgrade head`。

不要把 `.env`、数据库密码、Ozon API Key 或 service role key 发给 AI，也不要提交到 Git。

## API 身份与紧急停止

- 未配置 `KJDS_API_KEY` 时，所有 `/v1` 请求以失败关闭方式拒绝。
- 前端由 Next.js 服务端代理注入密钥，浏览器不保存 API 密钥。
- 正式双人审批可用 `KJDS_API_KEYS_JSON` 为不同密钥配置独立 actor 和 role；申请人无法批准自己的高风险动作。
- 紧急情况可调用 `/v1/system/kill-switch/engage`；开启后所有普通写操作返回 `423`，只有 `admin` 可解除。

## 不可变证据账本

`/v1/evidence` 接收原始文件并计算 SHA-256，同时记录来源、证据等级、业务生效时间、系统记录时间和创建人。证据可链接到商品、订单、结算或其他证据；PostgreSQL 触发器禁止修改和删除账本行。默认单文件上限为 10 MB，可通过 `KJDS_EVIDENCE_MAX_BYTES` 调整。

已审核的 Product / Compliance / Quality Passport 只能引用账本中存在且哈希复验通过的证据，重复引用会被拒绝。商品放行时系统会重新复验证据，Passport 版本在 PostgreSQL 中只可追加、不可修改或删除。

供应商报价同样必须绑定候选商品、稳定供应商标识并引用哈希复验通过的原始证据；利润场景除报价证据外还必须提供价格、汇率、物流、费率等假设的证据。报价和利润场景在 PostgreSQL 中只可追加；同一平台外部报价编号若提交不同内容会返回冲突，不会覆盖历史。证据血缘会分别连接到 `supplier_offer` 与 `profit_scenario`。

## G0–G1 经营准入状态

`GET /v1/operations/readiness` 按真实数据库事实计算当前阶段门，不接受人工填写“已完成”：三个候选 SKU、三类 Passport、每 SKU 三个不同供应商、正 CM3 场景、Ozon 四类正式事实、费用映射、RUB/CNY 汇率及未知费用都会独立显示。经营负责人和 Ozon 账户证据可以从经营看板直接上传；`POST /v1/operations/gate-evidence` 会自动哈希固化并链接到 `gate_requirement/GOV-001` 或 `gate_requirement/OZN-001`，只有哈希复验通过的证据才计入。前端直接显示每项缺口和下一步，不会把工程骨架冒充为业务放行。

`POST /v1/intake/sku-episodes` 与经营看板的“候选 SKU 一站式录入”会同时建立商品身份、Product / Compliance / Quality Passport 草稿、三份不可变原始证据及血缘。重复提交相同 SKU 与文件会恢复既有对象，不增加虚假版本；同一 SKU 更换商品身份会被拒绝。录入结果始终是待人工审核草稿，不会自动批准合规、采购或上架。

`GET /v1/passport-reviews` 返回当前待审核队列；`POST /v1/products/{product_id}/passports/{kind}/review` 只允许审核角色提交批准、拒绝或阻断结论。审核会创建不可变新版本，使用预期版本防止覆盖并发修改，阻断或拒绝必须填写原因，重复提交同一结论可安全恢复原结果。

`POST /v1/sourcing/comparison-intake` 一次接收同一 SKU 的三家独立供应商报价、三份原始报价文件和一份共同利润假设证据，并为每家生成可比 CM3。`GET /v1/sourcing/comparisons/{product_id}` 返回排序后的报价比较；只有三家证据化供应商、完整利润场景、正 CM3 和三本已批准 Passport 同时满足时，`POST /v1/sourcing/procurement-candidates` 才能建立采购审批。采购申请仍须由不同身份通过双人控制，不会直接下单。

双人批准后的候选可通过 `POST /v1/procurement/sample-orders` 建立受控样品单；确认、发货、签收、验货、黄金样批准/淘汰均通过只可追加的证据事件推进。`GET /v1/procurement/suppliers/performance` 只用实际样品事件计算质量、交付完整度和准时率；备用供应商接口只返回正 CM3 建议，任何切换都会重新创建采购审批，系统不自动付款或替换供应商。

## 交互模式与决策合同

`GET /v1/interaction-profiles` 返回五个固定版本的协作流程：快速解释、苏格拉底澄清、证据研究、决策评审和概率预测；`/eli10`、`/socrates`、`/truth`、`/x10think`、`/oda`、`/product` 只是这些流程的别名，不是绕过经营控制的魔法口令。

`POST /v1/decision-contracts` 会把问题、风险、期限、最大损失、备选方案、假设、未知项和不可变证据编译成只可追加的合同。缺少关键输入时状态为 `clarification_required`，缺少证据时为 `evidence_pending`；高风险合同强制标记人工审批，重大风险保持纯建议。所有合同的 `execution_eligible` 固定为 `false`，模型分析结果必须经过独立的决策、审批与执行链才可能影响真实经营。

分析就绪后，`POST /v1/decision-contracts/{id}/analyses` 要求结论、置信度、注册方案、预测指标、点预测、上下界、到期日和证据；分析提交者不能复核自己的产物。`POST /v1/decision-analyses/{id}/reviews` 记录不可变独立复核，重大风险需要两名接受结论的复核者，且最终决策人必须与分析者、复核者分离。正式决定仍固定为无执行权，真实执行必须另走既有审批链。

采纳或受控实验的决定到期后，`POST /v1/decision-resolutions/{id}/outcome` 才允许用证据回填真实值，不能提前填报或覆盖历史。`GET /v1/decision-calibration` 按指标与单位返回平均绝对误差、平均绝对百分比误差和预测区间命中率，使系统用实际成败校准，而不是按文本流畅度评价 Agent。

## 因果实验门禁

只有正式决定为 `experiment` 的决议才能调用 `POST /v1/decision-resolutions/{id}/experiment`。协议会一次性锁定可证伪假设、唯一主指标、随机化单位、干扰集群、两组分配比例、目标样本、最小有意义效果、预算、止损线、时间窗口、结果观察期、护栏和证据；同一决议不能事后更换协议。

实验启动、暂停、恢复、停止和完成均通过 `/v1/causal-experiments/{id}/events` 追加证据事件。分流使用服务端私密种子与 HMAC：相同业务单位稳定进入同一组，数据库只保存不可逆哈希，不保存原始用户、订单或会话标识。主指标结果同样只能追加一次，不能覆盖。

预算支出、累计损失和预注册护栏通过 `/v1/causal-experiments/{id}/safety-checks` 形成不可变安全读数。任何一次读数越线都会锁存为安全事故：系统阻止新增分流，结果状态变为 `safety_breach`，后续较低读数不能自动清除事故或恢复实验。

`GET /v1/causal-experiments/{id}/evaluation` 会先检查安全门和样本比例异常（SRM），再计算两组摘要、绝对/相对处理效应和 95% 区间。安全越线和 SRM 异常都会阻断解释；样本充分且质量门通过也只返回 `ready_for_independent_review`。接口固定输出 `decision_eligible=false` 和 `automatic_rollout=false`，因此实验报告不能绕过独立复核与后续正式决策。

协议还可预注册最多三个分层字段，以及内部蚕食、长期成本、长期价值等效果指标。分层值在首次分流时固化，不能事后改组；系统只计算预注册分层，避免实验结束后切割大量人群寻找偶然赢家。所有标记为必需的价值指标都达到样本要求后，才计算：

```text
每单位真实增量价值 =
主指标处理效应
+ 长期价值处理效应
- 内部蚕食处理效应
- 长期成本处理效应
```

缺少任何必需的蚕食或长期结果时，评估状态为 `incomplete_value_model`，不能进入独立复核。这样一个实验 SKU 的增长不能掩盖同店商品损失、退款或后续价值下降。

## 因果知识账与复现门禁

达到 `ready_for_independent_review` 不是“结论成立”。另一身份必须通过 `POST /v1/causal-experiments/{id}/reviews` 固化方法审查、数据质量审查、替代解释、证据与 `accepted / needs_replication / rejected` 结论；实验负责人不能复核自己的实验，同一复核人也不能覆盖已提交的审查。

只有当前仍通过安全门和质量门、且独立复核为 `accepted` 的实验，才能通过 `POST /v1/causal-experiments/{id}/knowledge` 登记知识。登记时必须明确因果主张、作用机制、平台/国家/品类/人群边界、反证条件、生效时间和最晚复验时间。知识发布者必须与实验负责人、复核人分离，条目不可修改；需要调整时必须用新的实验、复核和条目留下完整历史。

`GET /v1/causal-knowledge` 会动态核验来源实验。后续新增样本改变评估、出现 SRM、安全护栏越线或超过复验期限时，原知识分别变为 `source_evaluation_changed`、`source_experiment_invalidated` 或 `expired`，仍保留审计记录但不再可用。独立实验可显式登记复现关系：相同边界的有效复现把根知识从 `provisional` 升级为 `replicated`；不同边界只标记为 `portable_candidate`，永不宣称“普遍有效”。所有知识固定 `execution_eligible=false`、`automatic_rollout=false`，只能成为后续条件策略的证据输入。

## 条件策略与逐级放量合同

`POST /v1/causal-policies` 只能引用当前 `usable=true` 的因果知识，策略的平台、国家、品类和人群必须与知识边界完全一致。策略使用结构化条件（`eq / neq / gt / gte / lt / lte / in / not_in`），不接受可执行代码；动作和退回动作只能使用 `recommend_*` 类型，并强制登记护栏和至少两个严格递增的阶段。第一阶段必须是暴露比例为零的 `shadow`，避免从单次实验直接跳到真实全量。

策略提出者不能自审；接受复核后，另一名审批者才能调用 `/v1/causal-policies/{id}/releases` 批准当前阶段。阶段不得跳过，后续阶段必须等上一阶段的不可变结果达到最小观察数、最小增量价值且未越过护栏。即使全部条件满足，系统也只形成受控阶段合同：`execution_eligible=false`、`automatic_execution=false`、`automatic_promotion=false`。真实执行仍需未来单独的执行适配器、预算审批和平台权限门禁。

策略会持续反查来源知识。一旦任一知识失效，策略立即变为 `source_knowledge_invalidated`；上下文评估返回退回动作而非候选动作。这样企业学习可以进入条件化策略，但错误或过期知识不会继续静默驱动经营。

## 策略评估账、影子运行与审批交接

`POST /v1/causal-policy-releases/{id}/evaluations` 把每一次条件判断连同策略快照、去敏后的结构化上下文、结果、证据和观察时间写入不可变事件账。同一发布阶段和幂等键不能改写历史；上下文禁止客户、邮箱、电话、地址、令牌和密钥等敏感字段，单条限制为 100 个字段和 64 KiB。

零暴露阶段通过 `/v1/causal-policy-releases/{id}/shadow-batches` 批量回放真实经营上下文。批次只记录“命中候选建议”或“退回不行动”，固定 `zero_exposure=true`、`execution_eligible=false`。影子阶段结果的观察数必须与不可变评估账完全一致并达到预注册门槛，不能靠手工填写观察数跳过影子运行。

进入非零暴露阶段后，`/v1/causal-policy-releases/{id}/activation-handoff` 只会生成高风险审批事项。请求者不能自批；审批通过也只返回 `activation_eligible=true`，始终保持 `execution_eligible=false` 和 `automatic_execution=false`。任何来源知识失效或策略快照变化都会让既有交接动态变为不可激活，后续执行适配器必须再次核验该状态。

## 可逆执行计划与零写入预演

阶段激活审批与具体平台操作是两项不同授权。只有仍然有效且已经独立批准的阶段交接，才能调用 `/v1/causal-policy-activation-handoffs/{id}/execution-plans`。计划必须选择能力白名单中的适配器，绑定具体目标、当前平台状态 SHA-256、拟修改字段、完整回滚字段和证据；计划本身不可修改，同一幂等键不能偷换内容。

当前首个适配器 `ozon.listing.draft.v1` 仅接受 Listing 草稿的标题、描述、属性和图片字段，并固定 `live_execution_supported=false`。建立计划会产生第二个高风险审批事项 `platform_execution.execute_plan`，申请人不能批准自己的具体执行计划。

`POST /v1/governed-execution-plans/{id}/dry-run` 会再次核对阶段交接仍有效、当前状态与前置快照一致、回滚合同存在且网页实时写入仍被禁用。预演凭证不可覆盖，并明确返回 `platform_write_performed=false`。只有预演通过、具体执行审批通过且来源知识仍有效时，计划才会显示 `ready_for_executor=true`；计划对象依旧固定 `execution_eligible=false`，真实动作只能通过下述受限命令队列完成，不能绕过队列直接调用平台。

## 受限执行命令、回执与补偿状态机

受限执行由独立全局开关 `KJDS_LIMITED_EXECUTION_ENABLED` 控制，默认 `false`。开启后，计划仍需在入队时重新通过来源知识、阶段交接、零写入预演、具体执行审批和全局熔断检查。`POST /v1/governed-execution-plans/{id}/commands` 只生成不可变命令信封，不由网页进程直接调用平台；同一计划只有一个执行命令，并使用确定性幂等令牌。

专用执行器使用 `executor` 身份调用 `/v1/limited-execution-commands/{id}/claim`。领取前必须提交刚读取的当前平台状态 SHA-256，任何漂移都会把命令锁定为 `precondition_failed`；领取采用 30–600 秒租约，只有持有租约的执行器才能提交平台回执。成功回执必须包含远端操作号、变更后状态指纹及 `mutation_applied=true`，失败回执必须保留错误码。回执不可覆盖，网络超时或租约过期进入 `uncertain`，禁止盲目重试造成重复写入。

如果失败或不确定回执确认平台已经发生部分变更，系统会使用预批准的回滚内容自动生成独立 `rollback` 命令，并把变更后状态指纹作为回滚前置条件。风险负责人也能对已成功命令主动请求回滚。回滚同样需要领取、状态核验、幂等令牌和不可变回执；全局熔断开启时，新的执行与回滚领取都会失败关闭。

## 执行后观察、护栏冻结与补偿触发

只有已确认成功且确实产生平台变更的执行命令，才能通过 `/v1/limited-execution-commands/{id}/observation-window` 固化一次不可变观察合同。合同会在看见结果前锁定主要经营指标、各护栏指标的基线、最少观察数、开始与结束时间以及证据；缺少任一策略护栏的基线就不能开始。结果只能由合同内指标在预注册时间窗中追加，不能覆盖历史，也不会自动晋级策略。

当新结果越过 `max` 或 `min` 护栏时，系统先根据原执行回执中的变更后状态指纹生成补偿命令，再将观察窗口标记为 `guardrail_breached` 并开启全局熔断。此时平台写操作和补偿命令领取都失败关闭；风险负责人必须检查证据并由管理员明确解除熔断，专用执行器随后才能按状态指纹领取已排队的回滚。这样自动化只负责及时止损和准备可审计补偿，不会在异常状态下自行连续写平台。

观察结束或护栏越界后，独立复核者可通过 `/v1/execution-observation-windows/{id}/capability-economics` 固化一次能力损益：实际增量价值与避免损失，减去模型计算、人工审核、事故和维护成本。每个观察窗口只能有一份不可变核算并必须引用证据；按执行适配器和币种汇总后，系统只给出“继续观察、限制复核或考虑淘汰”的治理建议，固定 `automatic_authority_change=false`，不会因为一次盈利或亏损自动扩权、停权或改写知识。

## 生产事故接管与恢复演练

执行后护栏越界会自动创建 `operational_incident`，把异常指标、观察窗口、执行命令和执行计划绑定到同一事故影响范围。高危或严重的真实事故会保持全局熔断；事故接口是冻结期内唯一仍可写的安全控制面之一，但每个动作仍经过角色检查。负责人必须逐项提交远端状态核对、回滚确认、数据对账、凭证处置和监控恢复证据，不能一次点击把清单全部标记完成。

恢复负责人不能复核自己的处理，事故发起人也不能担任独立复核者。复核接受后状态仅变为 `ready_for_release`，固定 `automatic_release=false`；管理员必须另行调用熔断解除，再以新证据关闭事故。`mode=drill` 使用完全相同的接管、检查、复核和关闭事件账，但不会触碰生产熔断或平台写入，可用于季度恢复演练并证明备用流程实际可执行，而不只是留在文档中。

## 持续运营队列与 SLA 升级

`GET /v1/operations-control/queue` 把未关闭事故、待领取或状态不确定的执行命令、仍在观察或样本不足的执行后窗口统一排序。严重事故采用 15 分钟 SLA，执行结果不确定采用 5 分钟 SLA；队列明确负责人、截止时间、逾期分钟数、升级等级和下一动作。`POST /v1/operations-control/escalation-scan` 可在全局冻结期间继续运行，将 L1–L3 逾期升级固化为不可变记录，但固定 `automatic_business_action=false`，不会因为逾期自动回滚、解冻、改价或调用平台。

## Ozon 只读试点准入

只读试点只能选择商品、库存、订单、分析和财务读取白名单，最长 14 天，并锁定每日请求数、目标数、非敏感账户别名和证据。系统不接受写操作，不保存 Client Secret、API Key 或 Token，所有试点对象固定 `platform_write_allowed=false`、`execution_eligible=false`、`credential_material_stored=false`。

提交独立复核前必须逐项证明凭证隔离、最小权限、监控和数据导出备份，同时动态确认没有未关闭生产事故、熔断已解除、90 天内完成过一次恢复演练、期限未过期且操作仍在只读白名单内。申请人不能自审；复核通过后管理员激活时再次计算全部条件。激活只代表这份只读合同获准，不会启动 Worker，也不会把任何真实 Ozon 凭证写进数据库或仓库。

## 隔离的 Ozon Seller API Worker

真实 Ozon 凭证只允许出现在独立 Worker 的 `OZON_CLIENT_ID` 和 `OZON_API_KEY` 环境变量中；控制平面、数据库、计划、命令、回执和 AI 上下文均不保存这两个值。Worker 使用单独的 `KJDS_EXECUTOR_API_KEY`，该身份在 `KJDS_API_KEYS_JSON` 中只能授予 `executor` 角色。

`ozon.product.import.v3` 是首个支持命令投递的真实适配器。执行计划必须提供完整的 Ozon `import item`，而不是只提供标题差异，因为 Ozon 商品更新接口要求传递商品完整信息。Worker 在领取命令前分别读取 `/v3/product/info/list` 和 `/v4/product/info/attributes`，生成确定性状态指纹；通过后只调用一次 `/v3/product/import`，再用 `/v1/product/import/info` 确认异步任务。读取遇到 429 或服务端错误会有限退避重试；写请求遇到网络中断绝不盲重试，而是上报 `uncertain`，防止重复提交。

本地启动前必须先保持 `KJDS_LIMITED_EXECUTION_ENABLED=false` 完成合同测试。准备真实试点时，为 API 注册独立 executor 密钥、上传本轮状态证据、设置 `KJDS_EXECUTION_EVIDENCE_ID`，最后显式运行 `docker compose --profile live-execution up ozon-worker`。没有真实 Ozon 凭证和人工批准时，Worker 不会启动。

## Ozon 数据合同与正式事实

- `GET /v1/contracts/ozon` 返回 `ozon-v1` 订单、费用、退货和结算合同。
- `POST /v1/imports/ozon` 先把原始 CSV/XLSX 固化为 A 级证据，再写入可诊断暂存区；重复文件按 SHA-256 幂等返回。
- `POST /v1/imports/{import_id}/promote` 重新校验合同并晋升为不可变正式事实。缺少源证据或整份被拒绝的导入失败关闭；未知 SKU 保留为 `requires_product_mapping`，不会被静默绑定。
- `GET /v1/facts` 与证据血缘接口可以追溯每条事实的原文件、导入行、记录时间和业务生效时间。

## 财务控制层

- 原始 Ozon 费用码默认进入未知费用队列；只有具备证据、审核人、生效区间和金额符号规则的版本化映射才参与对账。
- FX 按币种对、指定来源和业务日期选择，非本位币金额缺少匹配汇率时失败关闭。
- 财务事实保留原金额、币种、日期、源事实和证据；对账快照分开显示订单应收、已解释调整、平台结算、银行到账、未知费用和差异率。
- 13 周现金流把已承诺项目与概率加权情景分开，不把预测伪装成已经发生的现金事实。

## 本地运行

```powershell
.\scripts\bootstrap.ps1
.\scripts\dev.ps1
```

打开 `http://127.0.0.1:8000/docs` 查看并调用接口。

也可以使用 Docker：

```powershell
docker compose up --build
```

## 测试

通过项目锁定环境执行：

```powershell
uv run ruff check .
uv run python -m pytest
```

完整 G-1 验证（临时 PostgreSQL 迁移回放、API/DB/Web smoke、测试和构建）：

```powershell
.\scripts\verify-g1.ps1
```

实时结果保存在 `.runtime/G1_VERIFICATION.json`。

## 当前成熟度

数据库持久化、Ozon 原文件证据化导入、四类版本化数据合同、正式事实晋升、费用/FX 控制、三方对账、13 周现金流、工具健康检查、多供货平台标准化、物流利润核算和 Ozon 上架草稿已经接通。默认仍为14天影子模式，高风险写操作不会自动执行。真实平台采集需要对应账号/API权限；浏览器登录、验证码和付费授权必须由账号所有者完成。

环境规范见 [TOOLCHAIN.md](TOOLCHAIN.md)，环境决策见 [ADR-0001](docs/adr/ADR-0001-development-environment.md)。
