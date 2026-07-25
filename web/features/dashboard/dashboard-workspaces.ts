export type WorkspaceId =
  | "overview"
  | "data"
  | "research"
  | "products"
  | "sourcing"
  | "growth"
  | "finance"
  | "science"
  | "governance"
  | "system";

export type WorkspaceDefinition = {
  id: WorkspaceId;
  label: string;
  eyebrow: string;
  title: string;
  description: string;
  group: "经营" | "业务" | "控制";
};

export const workspaceDefinitions: WorkspaceDefinition[] = [
  {
    id: "overview",
    label: "经营总览",
    eyebrow: "TODAY · OZON RU",
    title: "今天该做什么，一屏看清",
    description: "聚合真实阻断、机会、责任人和下一动作；所有计数来自控制平面。",
    group: "经营",
  },
  {
    id: "growth",
    label: "Ozon 增长",
    eyebrow: "PRICE · CONTENT · ADS",
    title: "现有商品增长工作台",
    description: "用全成本、同行价格、评价、内容和转化证据生成可解释增长方案。",
    group: "经营",
  },
  {
    id: "finance",
    label: "利润与结算",
    eyebrow: "CM3 · SETTLEMENT",
    title: "利润、费用与权威成本",
    description: "复核实际成本、费用映射和结算依据，不把估算利润冒充真实到账。",
    group: "经营",
  },
  {
    id: "data",
    label: "数据与证据",
    eyebrow: "EVIDENCE · IMPORTS",
    title: "Ozon 原件与 Evidence 中心",
    description: "预检并固化原始报表，查看导入交接与独立复核状态。",
    group: "业务",
  },
  {
    id: "research",
    label: "选品研究",
    eyebrow: "DEMAND · CANDIDATES",
    title: "需求证据与候选研究",
    description: "从真实 Ozon 需求依据完成三候选、五指标和三报价交接。",
    group: "业务",
  },
  {
    id: "products",
    label: "商品与内容",
    eyebrow: "SKU · MEDIA · LISTING",
    title: "商品 Passport 与内容工厂",
    description: "管理 SKU、七类原图、权利证明、图片 QA、俄语 Listing 和发布审批。",
    group: "业务",
  },
  {
    id: "sourcing",
    label: "1688 与供应链",
    eyebrow: "SUPPLIER · LANDED COST",
    title: "供应商、报价与样品",
    description: "录入三家真实报价、十五项成本、样品进度和备用供应商。",
    group: "业务",
  },
  {
    id: "science",
    label: "AI 决策与实验",
    eyebrow: "DECISION · EXPERIMENT",
    title: "可审计 AI 决策与增长实验",
    description: "把经营问题编译成决策合同，运行因果实验、策略影子与结果复盘。",
    group: "控制",
  },
  {
    id: "governance",
    label: "审批与执行",
    eyebrow: "APPROVAL · EXECUTION",
    title: "双人审批与受控执行",
    description: "查看审批、执行计划、一次性命令、回读、回滚和观察窗口。",
    group: "控制",
  },
  {
    id: "system",
    label: "系统运行",
    eyebrow: "READINESS · INCIDENTS",
    title: "真实业务启动与运行中心",
    description: "查看 Gate、异常队列、事故、只读试点和系统连接健康。",
    group: "控制",
  },
];

export function workspaceDefinition(id: WorkspaceId): WorkspaceDefinition {
  return workspaceDefinitions.find((item) => item.id === id) ?? workspaceDefinitions[0];
}
