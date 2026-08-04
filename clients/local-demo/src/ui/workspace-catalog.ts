export const WORKSPACE_IDS = [
  "dashboard",
  "sourcing",
  "pim",
  "listings",
  "oms",
  "fulfillment",
  "customer_service",
  "growth",
  "profit",
] as const;

export type WorkspaceId = (typeof WORKSPACE_IDS)[number];

export interface WorkspaceShellDefinition {
  readonly id: WorkspaceId;
  readonly route: string;
  readonly eyebrow: string;
  readonly title: string;
  readonly shortTitle: string;
  readonly summary: string;
  readonly shellState: "shell_ready";
  readonly scenarioState: "ready";
  readonly capabilities: readonly [string, string, string];
}

export const WORKSPACES: readonly WorkspaceShellDefinition[] = Object.freeze([
  {
    id: "dashboard",
    route: "dashboard",
    eyebrow: "CONTROL TOWER",
    title: "经营驾驶舱",
    shortTitle: "驾驶舱",
    summary: "在一个本地视图中组织店铺、商品、订单与利润工作区。",
    shellState: "shell_ready",
    scenarioState: "ready",
    capabilities: ["经营总览", "异常聚合", "工作区下钻"],
  },
  {
    id: "sourcing",
    route: "sourcing",
    eyebrow: "OPPORTUNITY",
    title: "选品机会台",
    shortTitle: "选品",
    summary: "查询合成机会并确定性推进至商品建档。",
    shellState: "shell_ready",
    scenarioState: "ready",
    capabilities: ["机会发现", "候选对比", "建档交接"],
  },
  {
    id: "pim",
    route: "pim",
    eyebrow: "PRODUCT CORE",
    title: "PIM 商品中枢",
    shortTitle: "PIM",
    summary: "展示合成商品身份、内容完整度与本地预览准备度。",
    shellState: "shell_ready",
    scenarioState: "ready",
    capabilities: ["商品身份", "内容资产", "就绪检查"],
  },
  {
    id: "listings",
    route: "listings",
    eyebrow: "LISTING STUDIO",
    title: "刊登预览台",
    shortTitle: "刊登",
    summary: "由合成商品状态生成本地 Listing 预览，不执行平台发布。",
    shellState: "shell_ready",
    scenarioState: "ready",
    capabilities: ["字段差异", "俄语预览", "本地模拟"],
  },
  {
    id: "oms",
    route: "oms",
    eyebrow: "ORDER FLOW",
    title: "OMS 订单工作台",
    shortTitle: "OMS",
    summary: "组织合成订单时间线、状态推进和异常演示入口。",
    shellState: "shell_ready",
    scenarioState: "ready",
    capabilities: ["订单时间线", "状态筛选", "异常回放"],
  },
  {
    id: "fulfillment",
    route: "fulfillment",
    eyebrow: "FULFILLMENT",
    title: "库存与履约",
    shortTitle: "履约",
    summary: "展示合成库存覆盖、履约推进与退货异常位置。",
    shellState: "shell_ready",
    scenarioState: "ready",
    capabilities: ["库存覆盖", "履约进度", "退货异常"],
  },
  {
    id: "customer_service",
    route: "customer-service",
    eyebrow: "SERVICE DESK",
    title: "客户服务台",
    shortTitle: "客服",
    summary: "为合成售后事件保留回复草稿与处理轨迹入口。",
    shellState: "shell_ready",
    scenarioState: "ready",
    capabilities: ["工单视图", "回复草稿", "处理轨迹"],
  },
  {
    id: "growth",
    route: "growth",
    eyebrow: "GROWTH LAB",
    title: "增长实验室",
    shortTitle: "增长",
    summary: "以合成场景展示活动假设、预算边界和结果占位。",
    shellState: "shell_ready",
    scenarioState: "ready",
    capabilities: ["活动假设", "预算边界", "结果占位"],
  },
  {
    id: "profit",
    route: "profit",
    eyebrow: "PROFIT TRUTH",
    title: "合成利润场景",
    shortTitle: "利润",
    summary: "组织结算、费用、到账与决策状态的演示入口。",
    shellState: "shell_ready",
    scenarioState: "ready",
    capabilities: ["结算结构", "费用归集", "决策状态"],
  },
]);

const BY_ROUTE = new Map(WORKSPACES.map((workspace) => [workspace.route, workspace]));
const DEFAULT_WORKSPACE = WORKSPACES[0] as WorkspaceShellDefinition;

export function workspaceFromHash(hash: string): WorkspaceShellDefinition {
  const route = hash.replace(/^#\/?/, "").split(/[?&]/, 1)[0]?.trim();
  return (route ? BY_ROUTE.get(route) : undefined) ?? DEFAULT_WORKSPACE;
}
