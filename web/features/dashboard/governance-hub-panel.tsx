import {
  ArrowUpRight,
  CheckCircle2,
  Clock3,
  FileLock2,
  KeyRound,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import type { DashboardModel } from "./use-dashboard-controller";
import type { WorkspaceId } from "./dashboard-workspaces";

type Props = {
  model: DashboardModel;
  onNavigate: (workspace: WorkspaceId) => void;
};

function destinationFor(action: string): WorkspaceId {
  if (action.includes("listing") || action.includes("image") || action.includes("passport")) return "products";
  if (action.includes("procurement") || action.includes("sample")) return "sourcing";
  if (action.includes("finance") || action.includes("cost") || action.includes("fee")) return "finance";
  if (action.includes("policy") || action.includes("experiment") || action.includes("decision")) return "science";
  return "system";
}

export function GovernanceHubPanel({ model, onNavigate }: Props) {
  const pending = model.approvals.filter((item) => item.status === "pending");
  const approved = model.approvals.filter((item) => item.status === "approved");
  const readyPlans = model.governedExecutionPlans.filter((item) => item.ready_for_executor);
  const activeCommands = model.limitedExecutionCommands.filter((item) => !["succeeded", "failed", "expired", "precondition_failed"].includes(item.status));
  const uncertainCommands = model.limitedExecutionCommands.filter((item) => item.status === "uncertain");
  const openIncidents = model.operationalIncidents.filter((item) => item.status !== "closed");

  return (
    <div className="workspace-page governance-page">
      <section className="governance-hero">
        <div>
          <span><FileLock2 size={15} /> SEPARATION OF DUTIES</span>
          <h2>提出、批准、执行、回读，四个阶段互不冒充。</h2>
          <p>运营人员可以准备草稿和申请；审批人必须使用独立登录会话。执行 Worker 只能消费已批准的单次命令，不能自行选择商品、预算或目标。</p>
        </div>
        <div className="governance-chain">
          {[
            ["01", "提案", "operator"],
            ["02", "独立批准", "approver · AAL2"],
            ["03", "单次执行", "executor"],
            ["04", "回读观察", "monitor"],
          ].map(([step, title, role]) => (
            <div key={step}><span>{step}</span><strong>{title}</strong><small>{role}</small></div>
          ))}
        </div>
      </section>

      <section className="governance-kpis">
        <article><Clock3 size={19} /><div><span>待独立审批</span><strong>{pending.length}</strong></div></article>
        <article><CheckCircle2 size={19} /><div><span>已批准记录</span><strong>{approved.length}</strong></div></article>
        <article><KeyRound size={19} /><div><span>执行就绪计划</span><strong>{readyPlans.length}</strong></div></article>
        <article className={uncertainCommands.length ? "danger" : ""}><ShieldAlert size={19} /><div><span>不确定命令</span><strong>{uncertainCommands.length}</strong></div></article>
      </section>

      <section className="governance-grid">
        <article className="governance-panel">
          <div className="section-heading"><div><span>APPROVAL QUEUE</span><h3>待处理审批</h3></div><span className="status-pill">{pending.length} 项</span></div>
          <div className="approval-queue">
            {pending.length ? pending.slice(0, 12).map((item) => (
              <button type="button" onClick={() => onNavigate(destinationFor(item.action))} key={item.id}>
                <span className="approval-icon"><ShieldCheck size={17} /></span>
                <div><span>{item.action}</span><strong>{item.resource_id}</strong><p>申请人 {item.requested_by} · 必须由另一身份决定</p></div>
                <ArrowUpRight size={16} />
              </button>
            )) : <div className="overview-empty"><CheckCircle2 size={25} /><strong>没有待处理审批</strong><p>新的采购、Listing、策略或执行申请会出现在这里。</p></div>}
          </div>
        </article>

        <article className="governance-panel">
          <div className="section-heading"><div><span>EXECUTION STATUS</span><h3>受控执行状态</h3></div><span className="status-pill">{activeCommands.length} 运行中</span></div>
          <div className="execution-lifecycle">
            <div><span>计划总数</span><strong>{model.governedExecutionPlans.length}</strong><p>冻结来源快照、证据和回滚补丁</p></div>
            <div><span>命令总数</span><strong>{model.limitedExecutionCommands.length}</strong><p>每个命令只有一次写入机会</p></div>
            <div><span>观察窗口</span><strong>{model.executionObservationWindows.length}</strong><p>记录主指标、护栏和止损</p></div>
            <div><span>开放事故</span><strong>{openIncidents.length}</strong><p>异常会阻断继续执行</p></div>
          </div>
          <button className="governance-link" type="button" onClick={() => onNavigate("science")}>打开执行计划与观察窗口 <ArrowUpRight size={16} /></button>
          <button className="governance-link secondary" type="button" onClick={() => onNavigate("system")}>打开异常与事故中心 <ArrowUpRight size={16} /></button>
        </article>
      </section>

      <section className="execution-guardrails">
        <div><ShieldCheck size={20} /><strong>正常链路</strong><p>证据 → 草稿 → 独立审批 → 执行计划 → 单次命令 → 平台回读 → 观察窗口</p></div>
        <div><RotateCcw size={20} /><strong>补偿链路</strong><p>失败或结果不确定时冻结后续动作，进入事故、回读和补偿命令。</p></div>
        <div><KeyRound size={20} /><strong>身份链路</strong><p>浏览器不接触 Ozon API key；approver 不能在同一会话切换角色。</p></div>
      </section>
    </div>
  );
}
