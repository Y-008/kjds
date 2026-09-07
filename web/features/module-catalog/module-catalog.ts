/**
 * Navigation-only metadata. Runtime readiness, counts and evidence status must
 * come from scoped server projections; these labels explain where and how to
 * work, they are not a second business authority.
 */
export type ModuleOperation = {
  id: string;
  title: string;
  action: string;
  inputs: string[];
  steps: string[];
  output: string;
  preconditions: string[];
  availability: "available" | "partial" | "gated";
};

export type ModuleLeaf = {
  id: string;
  title: string;
  summary: string;
  operations: ModuleOperation[];
};

export type ModuleWorkspace = {
  id: string;
  title: string;
  summary: string;
  route?: string;
  modules: ModuleLeaf[];
};

export type ModuleDomain = {
  id: string;
  title: string;
  summary: string;
  workspaces: ModuleWorkspace[];
};

export const moduleDomains: ModuleDomain[] = [
  {
    id: "operating-overview",
    title: "经营总览与情报",
    summary: "从市场观察到经营优先级，统一查看证据、任务和风险。",
    workspaces: [
      {
        id: "operating-command",
        title: "经营指挥台",
        summary: "查看今天要处理的阻断、机会、预算和现金。",
        modules: [
          {
            id: "daily-briefing",
            title: "今日经营简报",
            summary: "把店铺、SKU、任务、证据和经济状态压缩成行动队列。",
            operations: [
              { id: "briefing-review", title: "查看今日待办", action: "按优先级打开阻断和到期任务", inputs: ["tenant/store 作用域", "当前快照"], steps: ["读取服务端简报", "按风险、SLA、现金影响排序", "进入对应工作台处理"], output: "带 Owner、SLA 和下一步的任务队列", preconditions: ["身份已认证", "快照可用"], availability: "available" },
              { id: "briefing-replay", title: "回放一条决策", action: "从任务追溯到证据、规则、Agent 和回读", inputs: ["task_id 或 decision_id"], steps: ["锁定快照哈希", "展开输入证据和规则版本", "查看执行与外部回读"], output: "可复现的决策时间线", preconditions: ["Evidence 尚未过期或已有历史版本"], availability: "available" },
            ],
          },
          {
            id: "portfolio-cockpit",
            title: "组合与现金驾驶舱",
            summary: "按店铺、类目、SKU 和经营模式看资金占用与扩量风险。",
            operations: [
              { id: "portfolio-segment", title: "筛选经营组合", action: "按经营模式、利润状态、库存和证据等级筛选", inputs: ["时间范围", "店铺/仓库", "组合状态"], steps: ["选择作用域", "读取风险调整利润", "下钻到 SKU 实际现金记录"], output: "可扩量、观察、停止和 no_data 四类组合", preconditions: ["真实结算数据足够"], availability: "partial" },
              { id: "portfolio-stop", title: "生成停止建议", action: "识别亏损、缺货、退货或证据失效的 SKU", inputs: ["CM3", "库存", "退货", "Evidence freshness"], steps: ["运行经济护栏", "生成反例和停止原因", "创建受控任务"], output: "停止/降级建议，不直接写平台", preconditions: ["利润和库存口径已对齐"], availability: "gated" },
            ],
          },
        ],
      },
      {
        id: "market-intelligence",
        title: "市场与同行情报",
        summary: "管理 Ozon、抖音和公开页面形成的外部观察证据。",
        modules: [
          {
            id: "source-inbox",
            title: "来源采集箱",
            summary: "导入链接、官方导出和授权连接器结果，保留来源边界。",
            operations: [
              { id: "source-import", title: "导入外部链接", action: "粘贴链接并生成待复核观察卡片", inputs: ["source_url", "来源类型"], steps: ["记录来源和抓取时间", "计算内容哈希", "标记 source_grade 和 requires_review"], output: "Observation + Evidence 元数据", preconditions: ["来源允许访问", "没有绕过验证码或权限"], availability: "available" },
              { id: "source-review", title: "复核来源可信度", action: "查看来源、时间、权限和数据缺口", inputs: ["Observation ID", "Evidence ID"], steps: ["查看元数据", "检查新鲜度和完整性", "决定可用于观察、候选或阻断"], output: "来源等级和可用范围", preconditions: ["Evidence 元数据可读"], availability: "available" },
            ],
          },
          {
            id: "competitor-monitor",
            title: "同行店铺监控",
            summary: "观察店铺上新、价格、类目覆盖和持续经营质量。",
            operations: [
              { id: "competitor-add", title: "加入监控店铺", action: "保存公开店铺标识并设置观察频率", inputs: ["店铺链接或卖家标识", "类目范围", "频率"], steps: ["校验来源权限", "建立 CompetitorStore", "安排只读采集任务"], output: "可追踪的同行时间序列", preconditions: ["公开页或授权连接器可用"], availability: "available" },
              { id: "competitor-compare", title: "比较同行变化", action: "查看新品、价格带、销量代理指标和异常", inputs: ["店铺集合", "观察窗口"], steps: ["对齐 exact identity", "排除自有店铺", "生成变化和置信度"], output: "同行观察报告，不等于平台销量事实", preconditions: ["数据源没有跨店污染"], availability: "partial" },
            ],
          },
        ],
      },
    ],
  },
  {
    id: "product-content",
    title: "商品与内容",
    summary: "从候选商品、精确身份到俄语内容和媒体资产。",
    workspaces: [
      {
        id: "product-factory",
        title: "商品工厂",
        summary: "统一处理候选、变体、属性、合规和商品 Passport。",
        modules: [
          {
            id: "candidate-funnel",
            title: "候选漏斗",
            summary: "把观察商品转成可核价、可测款或阻断的候选。",
            operations: [
              { id: "candidate-score", title: "运行候选评分", action: "按需求、竞争、库存、成本和风险排序", inputs: ["Observation", "供应报价", "物流场景", "规则版本"], steps: ["去重 exact identity", "补齐成本和库存字段", "计算风险调整分数"], output: "候选排序和缺口说明", preconditions: ["不能把 NO_DATA 当成 0"], availability: "partial" },
              { id: "candidate-block", title: "阻断不合格候选", action: "冻结侵权、缺证据或经济不成立的候选", inputs: ["Passport", "利润底线", "权利证据"], steps: ["运行合规规则", "生成阻断原因", "保留修复任务"], output: "COMPLIANCE_BLOCKED 或 ECONOMIC_BLOCKED", preconditions: ["规则 Registry 可用"], availability: "available" },
            ],
          },
          {
            id: "product-passport",
            title: "商品 Passport",
            summary: "维护商品、变体、供应、权利、属性和媒体的冻结版本。",
            operations: [
              { id: "passport-create", title: "创建商品身份", action: "建立 Product/Variant 的精确身份和版本", inputs: ["外部标识", "属性 schema", "变体证据"], steps: ["生成自然键", "检查重复和错 variant", "冻结 Passport 版本"], output: "可引用的 Product Passport", preconditions: ["类目和属性 schema 已确定"], availability: "available" },
              { id: "passport-diff", title: "查看商品差异", action: "比较供应商、草稿和平台读回版本", inputs: ["两个 Passport 版本"], steps: ["生成字段差异", "标记影响利润和发布的字段", "创建修复任务"], output: "可审计的 Listing Diff", preconditions: ["两个版本均有 Evidence"], availability: "available" },
            ],
          },
        ],
      },
      {
        id: "content-studio",
        title: "内容与媒体工厂",
        summary: "生成俄语文案、生图、视频和发布素材，但不复制无权素材。",
        modules: [
          {
            id: "text-studio",
            title: "俄语内容工作台",
            summary: "基于事实 Passport 和术语表生成可复核草稿。",
            operations: [
              { id: "text-draft", title: "生成俄语草稿", action: "按类目模板生成标题、属性和描述草稿", inputs: ["Passport", "术语表", "禁词表"], steps: ["冻结事实", "生成候选文本", "运行事实和语言 QA"], output: "versioned draft，不是已发布内容", preconditions: ["事实字段完整", "权利状态可用"], availability: "available" },
              { id: "text-qa", title: "执行内容质检", action: "检查事实、俄语、禁词、夸张词和相似度", inputs: ["Draft", "QA 规则", "来源证据"], steps: ["执行确定性检查", "记录模型评测", "输出修复项"], output: "QA pass、partial 或 blocked", preconditions: ["规则版本固定"], availability: "available" },
            ],
          },
          {
            id: "media-studio",
            title: "图片与视频工作台",
            summary: "管理生图、生视频、版权、成本和媒体清单。",
            operations: [
              { id: "media-generate", title: "生成媒体资产", action: "按任务选择模型并记录 Token/媒体成本", inputs: ["媒体 Brief", "模型策略", "预算"], steps: ["路由模型", "生成候选资产", "写入成本和 lineage"], output: "带权利和成本元数据的媒体版本", preconditions: ["预算足够", "素材权利明确"], availability: "partial" },
              { id: "media-qa", title: "媒体发布检查", action: "检查画幅、清晰度、品牌、相似度和权利", inputs: ["媒体资产", "Passport", "权利 Evidence"], steps: ["执行媒体 QA", "标记失败原因", "进入审批或返工"], output: "媒体 Manifest 和发布资格", preconditions: ["原始输入可追溯"], availability: "gated" },
            ],
          },
        ],
      },
    ],
  },
  {
    id: "supply-inventory",
    title: "供应链与库存",
    summary: "把供应、物流、库存承诺和补货决策统一到经济模型。",
    workspaces: [
      {
        id: "supply-pricing",
        title: "供应商与物流",
        summary: "比较采购、规格、物流、税费和到岸成本。",
        modules: [
          {
            id: "supplier-quotes",
            title: "供应商报价",
            summary: "管理供应商规格、MOQ、报价和询价回执。",
            operations: [
              { id: "quote-compare", title: "比较供应报价", action: "按冻结数量和完整费用比较方案", inputs: ["供应报价", "MOQ", "数量", "费用证据"], steps: ["统一币种", "补齐缺失费用", "计算 Pareto 方案"], output: "risk-adjusted supplier options", preconditions: ["数量和价格范围明确"], availability: "available" },
              { id: "quote-rfq", title: "生成询价草稿", action: "生成供应商询价包但不自动发送", inputs: ["商品规格", "数量", "交期"], steps: ["冻结 RFQ", "绑定供应商", "等待独立发送授权"], output: "可审阅 RFQ package", preconditions: ["不含秘密或付款指令"], availability: "gated" },
            ],
          },
          {
            id: "logistics-lab",
            title: "物流核价",
            summary: "计算体积重、线路、时效、税费和不确定区间。",
            operations: [
              { id: "logistics-calc", title: "计算到岸成本", action: "按线路和规格计算保守物流区间", inputs: ["长宽高", "毛重", "路线", "币种"], steps: ["计算计费重", "匹配费率证据", "输出上下界"], output: "landed-cost scenario", preconditions: ["费率和单位可验证"], availability: "available" },
              { id: "logistics-compare", title: "比较履约方案", action: "比较 FBP、realFBS、仓储和补货路径", inputs: ["库存位置", "时效目标", "订单预测"], steps: ["模拟路径", "计算现金占用", "标记认证和税务影响"], output: "route recommendation", preconditions: ["不能把估算当到账事实"], availability: "partial" },
            ],
          },
        ],
      },
      {
        id: "inventory-control",
        title: "库存与补货",
        summary: "观察可售、在途、缺货、库龄和补货承诺。",
        modules: [
          {
            id: "stock-health",
            title: "库存健康",
            summary: "区分真实低需求、缺货截断和库存不可售。",
            operations: [
              { id: "stockout-analysis", title: "分析缺货截断", action: "估算 observed demand 与 lost sales", inputs: ["库存快照", "销量", "缺货区间"], steps: ["识别 stockout interval", "计算可售率", "输出需求上下界"], output: "需求修正和爆款置信度", preconditions: ["库存时间序列连续"], availability: "partial" },
              { id: "stock-alert", title: "生成库存告警", action: "按安全库存、现金和时效生成任务", inputs: ["库存", "预测", "现金预算", "物流时效"], steps: ["运行补货规则", "检查经济护栏", "创建建议任务"], output: "补货、降速或停止建议", preconditions: ["没有跨店库存污染"], availability: "available" },
            ],
          },
          {
            id: "replenishment",
            title: "补货与库存承诺",
            summary: "把采购、在途和 FBA 承诺绑定到现金和风险。",
            operations: [
              { id: "replenishment-plan", title: "生成补货计划", action: "生成数量、时点和资金占用计划", inputs: ["需求区间", "供应商", "仓库", "现金"], steps: ["模拟周转", "计算最坏情景", "输出冻结计划"], output: "Inventory Commitment Plan", preconditions: ["供应和物流证据完整"], availability: "gated" },
              { id: "replenishment-review", title: "审阅库存承诺", action: "查看计划对利润、现金和退货的影响", inputs: ["Plan", "风险调整 CM3", "退货准备金"], steps: ["比较方案", "审阅反例", "决定执行或回退"], output: "可批准或拒绝的库存决策包", preconditions: ["独立审阅身份可用"], availability: "gated" },
            ],
          },
        ],
      },
    ],
  },
  {
    id: "orders-after-sales",
    title: "订单履约与售后",
    summary: "从订单读回到发货、退货、客服、争议和赔付。",
    workspaces: [
      {
        id: "order-fulfillment",
        title: "订单与履约",
        summary: "查看订单状态、物流、取消和履约 SLA。",
        modules: [
          {
            id: "order-timeline",
            title: "订单时间线",
            summary: "按事件重建订单从创建到结算的完整过程。",
            operations: [
              { id: "order-reconcile", title: "对账订单状态", action: "比较平台回读、仓库和物流事件", inputs: ["订单事件", "物流事件", "外部回读"], steps: ["按事件时间排序", "检测缺失和乱序", "生成异常"], output: "Immutable Order Timeline", preconditions: ["事件作用域一致"], availability: "available" },
              { id: "fulfillment-alert", title: "处理履约异常", action: "识别延迟、取消、丢件和无法发货", inputs: ["SLA", "物流", "库存", "订单"], steps: ["计算 SLA", "分配 Owner", "执行模板化补救"], output: "履约异常任务", preconditions: ["消息模板和权限已配置"], availability: "partial" },
            ],
          },
          {
            id: "customer-service",
            title: "客服与平台争议",
            summary: "用事实证据生成客服处理和争议资料。",
            operations: [
              { id: "service-triage", title: "客服分流", action: "按订单、问题类型和 SLA 分配任务", inputs: ["客户消息", "订单事实", "语言模板"], steps: ["识别意图", "绑定订单", "生成可审阅回复"], output: "Customer Service Task", preconditions: ["订单事实已验证"], availability: "partial" },
              { id: "dispute-pack", title: "生成争议包", action: "汇总订单、物流、退款和沟通证据", inputs: ["订单", "物流", "退款", "沟通 Evidence"], steps: ["锁定截止时间", "检查证据完整性", "生成争议包"], output: "可提交的争议证据包", preconditions: ["不能编造或补写事实"], availability: "gated" },
            ],
          },
        ],
      },
      {
        id: "returns-recovery",
        title: "退货与赔付",
        summary: "处理批准、回仓、退款、拒付和结算后重开。",
        modules: [
          {
            id: "return-lifecycle",
            title: "退货生命周期",
            summary: "区分已批准、运输中、已回仓和已结算的退货事实。",
            operations: [
              { id: "return-track", title: "跟踪退货状态", action: "重建退货和退款事件链", inputs: ["平台退款", "仓库回仓", "物流事件"], steps: ["合并事件", "识别迟到和重开", "更新准备金"], output: "Return Timeline 和状态", preconditions: ["事件有来源和时间"], availability: "available" },
              { id: "return-reserve", title: "更新售后准备金", action: "把退货、拒付和赔付纳入风险利润", inputs: ["退货率", "索赔", "历史结算"], steps: ["计算 expected return cost", "更新 chargeback reserve", "重算风险调整 CM3"], output: "可回放的售后经济结果", preconditions: ["利润账本可用"], availability: "available" },
            ],
          },
          {
            id: "recovery-claims",
            title: "赔付与追回",
            summary: "跟踪平台赔付、供应商责任和可追回金额。",
            operations: [
              { id: "claim-open", title: "创建索赔任务", action: "根据证据缺口创建赔付或追回任务", inputs: ["损失事件", "责任方", "截止日期"], steps: ["校验责任证据", "生成索赔包", "分配 Owner"], output: "Claim Record", preconditions: ["损失金额已对账"], availability: "partial" },
              { id: "claim-settle", title: "确认追回结果", action: "把最终追回额写入结算链路", inputs: ["平台回执", "银行到账", "索赔 Evidence"], steps: ["验证回执", "确认到账", "更新现金账"], output: "Settled recovery amount", preconditions: ["银行或平台结算证据存在"], availability: "gated" },
            ],
          },
        ],
      },
    ],
  },
  {
    id: "profit-commercial",
    title: "利润、财务与商业化",
    summary: "把估算利润、结算现金、模型成本和客户账单分开核算。",
    workspaces: [
      {
        id: "profit-finance",
        title: "利润与财务控制",
        summary: "查看十五项成本、三本实际账、汇率和资金周期。",
        modules: [
          {
            id: "profit-lab",
            title: "利润实验室",
            summary: "比较价格、广告、物流和退货情景，不冒充实际利润。",
            operations: [
              { id: "profit-scenario", title: "测算利润情景", action: "计算 Scenario CM3 和 downside 区间", inputs: ["价格", "采购", "物流", "平台费", "广告"], steps: ["读取服务端成本", "应用 FX 和规则版本", "生成上下界"], output: "Scenario CM3", preconditions: ["缺失项必须显式显示"], availability: "available" },
              { id: "profit-reconcile", title: "核对实际利润", action: "对齐应计、结算和到账三本账", inputs: ["订单", "费用", "结算单", "银行"], steps: ["匹配自然键", "识别未分摊", "输出差异任务"], output: "Actual accrual / Settled / Cash CM3", preconditions: ["禁止客户端重算"], availability: "partial" },
            ],
          },
          {
            id: "budget-guard",
            title: "预算与经济护栏",
            summary: "限制广告、模型、媒体、库存和外部动作成本。",
            operations: [
              { id: "budget-allocate", title: "分配预算", action: "按店铺、SKU、实验和 Agent 分配预算", inputs: ["现金", "利润底线", "风险预算"], steps: ["冻结预算", "保留预占", "设置 overrun 行为"], output: "Budget Snapshot", preconditions: ["预算 Owner 独立"], availability: "available" },
              { id: "budget-stop", title: "触发经济止损", action: "预算、现金或利润越线时暂停相关动作", inputs: ["预算消耗", "CM3", "库存风险"], steps: ["检测阈值", "暂停实验或降并发", "创建恢复任务"], output: "经济护栏事件", preconditions: ["成本事件及时入账"], availability: "available" },
            ],
          },
        ],
      },
      {
        id: "commercial-operations",
        title: "商业订阅与用量",
        summary: "把 Skill、模型、媒体和 SaaS 客户用量转成可结算账本。",
        modules: [
          {
            id: "entitlement-console",
            title: "套餐与权限包络",
            summary: "管理配额、连接器频率、模型额度和执行包络。",
            operations: [
              { id: "entitlement-check", title: "检查客户 entitlement", action: "判断当前功能、额度和执行资格", inputs: ["Customer", "Contract", "Subscription"], steps: ["读取有效版本", "检查 grace/read_only", "返回允许范围"], output: "Entitlement Decision", preconditions: ["商业账本未冲突"], availability: "available" },
              { id: "entitlement-expire", title: "处理到期降级", action: "到期后保留导出审计并停止新增高风险动作", inputs: ["合同日期", "未完成任务", "Permit"], steps: ["进入 grace", "停止新写入", "保留在途回读和导出"], output: "可审计的降级事件", preconditions: ["账单状态可信"], availability: "available" },
            ],
          },
          {
            id: "usage-billing",
            title: "用量与账单",
            summary: "统计 Token、图片、视频、存储、API 和服务用量。",
            operations: [
              { id: "usage-record", title: "记录模型与媒体用量", action: "将每次调用绑定到客户、任务、SKU 和成本中心", inputs: ["Agent Run", "Provider Receipt", "资产"], steps: ["校验用量回执", "写入成本账", "处理重复事件"], output: "Usage Event", preconditions: ["Provider 回执可验证"], availability: "available" },
              { id: "invoice-preview", title: "生成账单预览", action: "按合同、套餐、用量和退款生成账单草稿", inputs: ["Usage Ledger", "Contract", "Refund"], steps: ["锁定结算窗口", "计算应收和成本", "输出可审阅账单"], output: "Invoice Draft", preconditions: ["商业账本已对账"], availability: "partial" },
            ],
          },
        ],
      },
    ],
  },
  {
    id: "ai-governance",
    title: "AI 项目治理与系统运维",
    summary: "管理 Agent、证明图、数据质量、自治配置、运行和灾备。",
    workspaces: [
      {
        id: "agent-project",
        title: "Agent 项目控制塔",
        summary: "按依赖图管理任务、证明、证据、测试和阻塞。",
        modules: [
          {
            id: "project-graph",
            title: "项目图与证明债务",
            summary: "查看已证明、过期、阻断和可并行的节点。",
            operations: [
              { id: "frontier-plan", title: "计算下一波任务", action: "按关键路径和最小阻塞集派发任务", inputs: ["HEAD", "图快照", "节点状态", "租约"], steps: ["读取依赖", "标记失效传播", "生成并行任务波"], output: "可执行任务波和 next_dependencies", preconditions: ["图快照绑定当前版本"], availability: "available" },
              { id: "proof-debt", title: "查看证明债务", action: "定位缺证明、缺证据、缺测试和缺回读的节点", inputs: ["ProofState", "EvidenceState", "OperationalState", "EconomicState"], steps: ["按状态聚合", "识别最小阻塞集", "创建修复任务"], output: "Proof Debt Report", preconditions: ["四状态不能互相冒充"], availability: "available" },
            ],
          },
          {
            id: "agent-runtime",
            title: "Agent 运行与恢复",
            summary: "监控心跳、租约、进度、预算和未知结果。",
            operations: [
              { id: "stuck-detect", title: "发现卡死任务", action: "识别无心跳、无消费者、无进展和重复执行", inputs: ["Heartbeat", "Progress Cursor", "Lease", "Queue"], steps: ["检测 deadline", "隔离任务", "执行 compensation"], output: "Stuck Task Incident", preconditions: ["任务有预期下一事件"], availability: "available" },
              { id: "agent-replay", title: "重放 Agent 运行", action: "用固定模型、Prompt、工具和输入快照复现结果", inputs: ["Agent Run", "Input Snapshot", "Model Version"], steps: ["恢复依赖", "执行只读重放", "比较输出和成本"], output: "Replay Diff", preconditions: ["输入和版本仍可取得"], availability: "available" },
            ],
          },
        ],
      },
      {
        id: "platform-operations",
        title: "平台运行与灾备",
        summary: "管理数据质量、SLO、备份、恢复和生产发布。",
        modules: [
          {
            id: "data-quality",
            title: "数据质量中心",
            summary: "查看 freshness、完整性、冲突、延迟和跨模块守恒。",
            operations: [
              { id: "quality-check", title: "执行质量检查", action: "检查字段、时间、作用域、哈希和金额守恒", inputs: ["Data Product", "Quality Rules", "Lineage"], steps: ["运行规则", "标记状态", "阻止不合格数据进入决策"], output: "Data Quality Report", preconditions: ["规则版本固定"], availability: "available" },
              { id: "quality-repair", title: "修复数据缺口", action: "生成重新采集、重放、人工复核或隔离任务", inputs: ["质量失败", "来源", "Owner"], steps: ["分类原因", "选择恢复路径", "跟踪直到验证"], output: "可验证修复记录", preconditions: ["不覆盖旧事实"], availability: "available" },
            ],
          },
          {
            id: "backup-recovery",
            title: "备份与恢复",
            summary: "验证数据库、对象存储、账本和运行快照能否恢复。",
            operations: [
              { id: "restore-test", title: "执行恢复演练", action: "在隔离环境恢复并校验事实、账本和 Evidence", inputs: ["Backup", "Restore Point", "RPO/RTO"], steps: ["恢复快照", "运行一致性检查", "记录差异"], output: "Restore Receipt", preconditions: ["不得触碰生产外部写入"], availability: "partial" },
              { id: "release-rollback", title: "回滚生产版本", action: "回到上一证明快照并隔离新任务", inputs: ["Release Snapshot", "Proof Snapshot", "Health Signals"], steps: ["停止新写", "恢复上一版本", "重建读模型和回读任务"], output: "Rollback Receipt", preconditions: ["有已验证回滚快照"], availability: "gated" },
            ],
          },
        ],
      },
    ],
  },
  {
    id: "growth-market",
    title: "增长与市场",
    summary: "管理广告、促销、实验、自然流量和市场增长任务。",
    workspaces: [{
      id: "growth-command",
      title: "增长工作台",
      summary: "用实验和边际利润决定继续、调整或停止。",
      modules: [{
        id: "growth-experiments",
        title: "增长实验",
        summary: "管理价格、广告、主图、标题和库存实验。",
        operations: [
          { id: "growth-start", title: "创建增长实验", action: "冻结控制组、处理组、预算和停止规则", inputs: ["实验假设", "人群", "预算", "暴露窗口"], steps: ["检查污染", "冻结实验协议", "生成实验任务"], output: "Experiment Protocol", preconditions: ["实验范围和停止规则明确"], availability: "gated" },
          { id: "growth-review", title: "复盘实验结果", action: "按因果证据、边际利润和风险决定下一步", inputs: ["实验事件", "订单", "退货", "利润"], steps: ["检查完成度", "排除污染", "生成扩量或停止建议"], output: "Learning Report", preconditions: ["实验未混入长期趋势"], availability: "partial" },
        ],
      }],
    }],
  },
  {
    id: "evidence-governance",
    title: "证据与治理",
    summary: "管理来源、事实、证据血缘、权限、回放和外部验收。",
    workspaces: [{
      id: "evidence-control",
      title: "Evidence 与权限工作台",
      summary: "把原始证据推进到可验证事实和受控决策。",
      modules: [{
        id: "evidence-lifecycle",
        title: "证据生命周期",
        summary: "登记、验证、晋级、失效和回放证据。",
        operations: [
          { id: "evidence-promote", title: "复核证据晋级", action: "检查来源、哈希、作用域和有效期", inputs: ["原始文件/响应", "source grade", "scope"], steps: ["验证完整性", "绑定 lineage", "生成事实候选"], output: "Evidence review result", preconditions: ["来源允许且哈希一致"], availability: "available" },
          { id: "evidence-replay", title: "回放事实链", action: "从指标回到原始证据、规则和 Agent 决策", inputs: ["metric 或 decision", "as_of"], steps: ["锁定历史前沿", "读取版本链", "比较重算结果"], output: "可复现的历史快照", preconditions: ["版本和时间字段完整"], availability: "available" },
        ],
      }],
    }],
  },
  {
    id: "system-commercial",
    title: "系统与商业化",
    summary: "管理店铺账户、团队、Agent、部署、套餐和用量。",
    workspaces: [{
      id: "system-control",
      title: "系统控制台",
      summary: "查看运行身份、租约、Agent、商业资格和部署健康。",
      modules: [{
        id: "store-and-team",
        title: "店铺与团队治理",
        summary: "配置作用域、角色、SoD、租约和运行身份。",
        operations: [
          { id: "scope-review", title: "审阅店铺作用域", action: "查看 tenant/entity/store 和当前授权边界", inputs: ["Principal", "Scope Grant", "Runtime Identity"], steps: ["读取服务端投影", "检查撤销和有效期", "确认可用动作"], output: "Exact Scope Review", preconditions: ["治理身份和 Evidence 可用"], availability: "available" },
          { id: "runtime-health", title: "检查运行身份", action: "查看 Adapter、租约、能力和回读新鲜度", inputs: ["Channel Account", "Lease", "Capabilities"], steps: ["读取运行投影", "检查 capability match", "阻断不新鲜身份"], output: "Runtime Identity Status", preconditions: ["不返回凭据值"], availability: "available" },
        ],
      }],
    }],
  },
];

export const allModuleOperations = moduleDomains.flatMap((domain) => domain.workspaces.flatMap((workspace) => workspace.modules.flatMap((module) => module.operations)));

