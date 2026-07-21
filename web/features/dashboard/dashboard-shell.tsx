import {
  Boxes,
  BrainCircuit,
  ChevronRight,
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
import type { WebSession } from "./contracts";

const nav = [
  [LayoutDashboard, "经营总览", true],
  [FileUp, "数据中心", false],
  [Waypoints, "全球货源", false],
  [Boxes, "商品中心", false],
  [BrainCircuit, "AI 工作台", false],
  [ImageIcon, "内容工厂", false],
  [FlaskConical, "增长实验", false],
  [CircleDollarSign, "利润中心", false],
  [ShieldCheck, "审批中心", false],
] as const;

type Props = {
  session: WebSession | null;
  onRefresh: () => void;
  children: ReactNode;
};

export function DashboardShell({ session, onRefresh, children }: Props) {
  return <main className="shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">K</div><div><strong>KJDS</strong><span>俄罗斯经营系统</span></div></div>
      <nav>{nav.map(([Icon, label, active]) => (
        <button className={active ? "active" : ""} key={label}><Icon size={19} /><span>{label}</span>{active && <ChevronRight size={16} />}</button>
      ))}</nav>
      <div className="sidebar-status"><span className="pulse" /><div><strong>14天影子运行</strong><span>只建议，不执行高风险动作</span></div></div>
    </aside>

    <section className="workspace">
      <header className="topbar">
        <div><p className="eyebrow">OZON · RUSSIA</p><h1>经营指挥中心</h1></div>
        <div className="topbar-actions">
          <div className="session-chip"><ShieldCheck size={16} /><span>{session?.email ?? (session?.auth_mode === "legacy" ? "本地运营身份" : "身份校验中")}{session ? ` · ${session.actor_id} · ${session.roles.join("/")}` : ""}</span></div>
          {session?.auth_mode === "supabase" ? <form action="/auth/logout" method="post"><button className="refresh" type="submit">退出</button></form> : null}
          <button className="refresh" onClick={onRefresh}><RefreshCw size={17} />刷新状态</button>
        </div>
      </header>
      {children}
    </section>
  </main>;
}
