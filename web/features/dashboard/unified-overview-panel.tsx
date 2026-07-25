import {
  ArrowUpRight,
  Bot,
  CheckCircle2,
  CircleDollarSign,
  Database,
  FileCheck2,
  PackageSearch,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Store,
  TrendingUp,
  Waypoints,
} from "lucide-react";
import type { DashboardModel } from "./use-dashboard-controller";
import type { WorkspaceId } from "./dashboard-workspaces";

type Props = {
  model: DashboardModel;
  onNavigate: (workspace: WorkspaceId) => void;
};

const capabilityCards: Array<{
  id: WorkspaceId;
  step: string;
  title: string;
  description: string;
  icon: typeof Store;
}> = [
  { id: "data", step: "01", title: "连接真实数据", description: "Ozon 原件、API 只读回读与 Evidence", icon: Database },
  { id: "research", step: "02", title: "验证需求与候选", description: "三候选、五指标、双来源与合规门", icon: PackageSearch },
  { id: "sourcing", step: "03", title: "核算真实落地成本", description: "1688、三报价、十五项成本与样品", icon: Waypoints },
  { id: "growth", step: "04", title: "优化现有商品", description: "价格带、内容、评价、转化与广告上限", icon: TrendingUp },
  { id: "products", step: "05", title: "生产商品内容", description: "七类图片、权利文件、俄语 Listing 与 QA", icon: Sparkles },
  { id: "finance", step: "06", title: "验证利润与到账", description: "CM3、费用、结算、银行和 FX 对账", icon: CircleDollarSign },
  { id: "science", step: "07", title: "运行增长实验", description: "决策合同、因果实验、影子策略与止损", icon: Bot },
  { id: "governance", step: "08", title: "审批后受控执行", description: "双人审批、一次许可、回读与回滚", icon: ShieldCheck },
];

export function UnifiedOverviewPanel({ model, onNavigate }: Props) {
  const pendingApprovals = model.approvals.filter((item) => item.status === "pending");
  const openIncidents = model.operationalIncidents.filter((item) => item.status !== "closed");
  const onlineTools = Object.values(model.health).filter((item) => item.status === "ok").length;
  const configuredTools = Object.keys(model.health).length;
  const workItems = model.operatingWorkbench?.work_items ?? [];
  const researchReady = model.researchReadiness?.ready ?? false;
  const executionReady = model.realExecutionReadiness?.ready ?? false;
  const candidateSummary = model.gateReadiness?.candidate_portfolio;

  return (
    <div className="workspace-page overview-page">
      <section className="overview-hero">
        <div>
          <span className="hero-kicker"><Store size={15} /> Ozon RU 统一经营平台</span>
          <h2>从“看到问题”到“验证结果”，<br />所有工作在一条受控链上完成。</h2>
          <p>系统把今天讨论的店铺连接、1688 比价、商品优化、图片内容、广告、订单利润和真实执行统一起来。首页只告诉你当前事实、最大阻断和下一步。</p>
          <div className="hero-actions">
            <button type="button" onClick={() => onNavigate("growth")}>开始现有商品诊断 <ArrowUpRight size={16} /></button>
            <button className="secondary" type="button" onClick={() => onNavigate("system")}>查看真实业务启动路径</button>
          </div>
        </div>
        <div className="scope-card">
          <div className="scope-card-head">
            <div>
              <span>当前经营作用域</span>
              <strong>{executionReady ? "真实执行条件可复核" : researchReady ? "研究可继续，实盘仍有门禁" : "先补齐真实需求证据"}</strong>
            </div>
            {executionReady ? <CheckCircle2 size={24} /> : <ShieldAlert size={24} />}
          </div>
          <div className="scope-row">
            <span>研究与分析</span>
            <b className={researchReady ? "ready" : "blocked"}>{researchReady ? "可继续" : "缺证据"}</b>
          </div>
          <div className="scope-row">
            <span>平台真实副作用</span>
            <b className={executionReady ? "ready" : "blocked"}>{executionReady ? "待单次审批" : "保持阻断"}</b>
          </div>
          <small>即使作用域满足，改价、发布和广告仍需独立审批与一次性许可。</small>
        </div>
      </section>

      <section className="overview-kpis" aria-label="经营关键状态">
        <article>
          <span className="kpi-icon green"><PackageSearch size={20} /></span>
          <div><small>合格候选</small><strong>{candidateSummary?.selection_ready_count ?? 0}<em> / {candidateSummary?.target_count ?? 3}</em></strong><p>通过需求、三报价与完整成本门</p></div>
        </article>
        <article>
          <span className="kpi-icon violet"><FileCheck2 size={20} /></span>
          <div><small>待审批</small><strong>{pendingApprovals.length}</strong><p>必须由独立身份完成决定</p></div>
        </article>
        <article>
          <span className="kpi-icon amber"><ShieldAlert size={20} /></span>
          <div><small>经营与运行阻断</small><strong>{(model.gateReadiness?.exception_workspace.blocked_count ?? 0) + model.operationsQueue.length}</strong><p>{openIncidents.length} 个未关闭事故</p></div>
        </article>
        <article>
          <span className="kpi-icon blue"><Database size={20} /></span>
          <div><small>证据与连接</small><strong>{model.evidenceRecords.length}<em> 条</em></strong><p>{onlineTools}/{configuredTools || 0} 个工具在线</p></div>
        </article>
      </section>

      <section className="overview-grid">
        <article className="overview-panel priority-panel">
          <div className="section-heading">
            <div><span>TODAY&apos;S PRIORITIES</span><h3>今天优先处理</h3></div>
            <button type="button" onClick={() => onNavigate("system")}>全部任务</button>
          </div>
          <div className="priority-list">
            {workItems.length ? workItems.slice(0, 6).map((item, index) => (
              <button
                type="button"
                className="priority-item"
                onClick={() => onNavigate(item.item_type === "gate_blocker" ? "research" : item.item_type === "runtime_operation" ? "system" : "growth")}
                key={item.id}
              >
                <span className="priority-number">{String(index + 1).padStart(2, "0")}</span>
                <div>
                  <span>{item.agent_name} · {item.risk}</span>
                  <strong>{item.title}</strong>
                  <p>{item.next_action}</p>
                </div>
                <ArrowUpRight size={17} />
              </button>
            )) : (
              <div className="overview-empty">
                <ShieldCheck size={25} />
                <strong>暂时没有可验证的经营任务</strong>
                <p>导入真实数据后，经营简报会按证据和风险生成下一动作。</p>
              </div>
            )}
          </div>
        </article>

        <article className="overview-panel agent-briefing">
          <div className="section-heading">
            <div><span>AI OPERATING TEAM</span><h3>Agent 当前焦点</h3></div>
            <span className="status-pill">影子建议</span>
          </div>
          <div className="agent-briefing-list">
            {model.operatingWorkbench?.agents.map((agent) => (
              <div key={agent.agent_id}>
                <span className="agent-monogram">{agent.name.slice(0, 1)}</span>
                <div><strong>{agent.name}</strong><p>{agent.current_focus}</p></div>
                <b>{agent.work_item_count}</b>
              </div>
            )) ?? <div className="overview-empty"><Bot size={24} /><strong>简报尚未加载</strong></div>}
          </div>
          <div className="agent-boundary">
            <ShieldCheck size={16} />
            <span>Agent 只能解释、排序和提出建议，不能自己选择商品或写入平台。</span>
          </div>
        </article>
      </section>

      <section className="capability-map">
        <div className="section-heading">
          <div><span>ONE OPERATING LOOP</span><h3>八步经营闭环</h3><p>每一步都能回到证据、责任人和下一道门。</p></div>
        </div>
        <div className="capability-grid">
          {capabilityCards.map((item) => {
            const Icon = item.icon;
            return (
              <button type="button" onClick={() => onNavigate(item.id)} key={item.id}>
                <span className="capability-step">{item.step}</span>
                <span className="capability-icon"><Icon size={20} /></span>
                <strong>{item.title}</strong>
                <p>{item.description}</p>
                <ArrowUpRight size={16} />
              </button>
            );
          })}
        </div>
      </section>
    </div>
  );
}
