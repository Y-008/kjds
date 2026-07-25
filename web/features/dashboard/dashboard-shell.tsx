import {
  Boxes,
  BrainCircuit,
  CircleDollarSign,
  FileUp,
  FlaskConical,
  Image as ImageIcon,
  LayoutDashboard,
  RefreshCw,
  ShieldCheck,
  Waypoints,
} from "lucide-react";
import type { ReactNode } from "react";
import type { IdentityStatus, WebSession } from "./contracts";

const nav = [
  [LayoutDashboard, "经营总览", "#dashboard-top"],
  [FileUp, "数据中心", "#ozon-import"],
  [Waypoints, "全球货源", "#sourcing-intake"],
  [Boxes, "商品中心", "#sku-intake"],
  [BrainCircuit, "AI 工作台", "#decision-workbench"],
  [ImageIcon, "内容工厂", "#product-media-intake"],
  [FlaskConical, "增长实验", "#causal-experiments"],
  [CircleDollarSign, "利润中心", "#actual-cost-review"],
  [ShieldCheck, "审批中心", "#listing-approval"],
] as const;

type Props = {
  session: WebSession | null;
  identityStatus: IdentityStatus;
  onRefresh: () => void;
  children: ReactNode;
};

export function DashboardShell({ session, identityStatus, onRefresh, children }: Props) {
  return <main className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">K</div><div><strong>KJDS</strong><span>俄罗斯经营系统</span></div></div>
      <nav aria-label="经营工作区">{nav.map(([Icon, label, href]) => (
        <a aria-label={label} href={href} key={label} title={label}><Icon size={19} /><span>{label}</span></a>
      ))}</nav>
      <div className="sidebar-status"><span className="pulse" /><div><strong>{identityStatus === "ready" ? "受控经营模式" : "身份状态未知"}</strong><span>只建议，不执行高风险动作</span></div></div>
    </aside>

    <section className="workspace">
      <header className="topbar" id="dashboard-top">
        <div><p className="eyebrow">OZON · RUSSIA</p><h1>经营指挥中心</h1></div>
        <div className="topbar-actions">
          <div className="session-chip"><ShieldCheck size={16} /><span>{identityStatus === "unavailable" ? "身份状态未知" : session?.email ?? (session?.auth_mode === "legacy" ? "本地运营身份" : "身份校验中")}{session && identityStatus === "ready" ? ` · ${session.actor_id} · ${session.roles.join("/")}` : ""}</span></div>
          {session?.auth_mode === "supabase" ? <form action="/auth/logout" method="post"><button className="refresh" type="submit">退出</button></form> : null}
          <button className="refresh" disabled={identityStatus === "checking"} onClick={onRefresh} type="button"><RefreshCw size={17} />刷新状态</button>
        </div>
      </header>
      {children}
    </section>
  </main>;
}
