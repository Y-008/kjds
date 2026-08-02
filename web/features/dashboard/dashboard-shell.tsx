import {
  Activity,
  BrainCircuit,
  Boxes,
  ChevronRight,
  CircleDollarSign,
  Database,
  LayoutDashboard,
  LockKeyhole,
  LogOut,
  Network,
  PackageSearch,
  PanelsTopLeft,
  Radar,
  RefreshCw,
  ScanSearch,
  ShieldCheck,
  Store,
  TrendingUp,
  Waypoints,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import type { WebSession } from "./contracts";
import {
  workspaceDefinition,
  workspaceDefinitions,
  type WorkspaceId,
} from "./dashboard-workspaces";

const workspaceIcons: Record<WorkspaceId, LucideIcon> = {
  overview: LayoutDashboard,
  data: Database,
  research: ScanSearch,
  products: PackageSearch,
  batch: ScanSearch,
  pilot: Radar,
  sourcing: Waypoints,
  growth: TrendingUp,
  finance: CircleDollarSign,
  science: BrainCircuit,
  governance: ShieldCheck,
  system: Activity,
};

const workspaceGroups = ["经营", "业务", "控制"] as const;

type Props = {
  session: WebSession | null;
  activeWorkspace: WorkspaceId;
  ozonConnection: { label: string; ready: boolean };
  onNavigate: (workspace: WorkspaceId) => void;
  onRefresh: () => void;
  children: ReactNode;
};

export function DashboardShell({
  session,
  activeWorkspace,
  ozonConnection,
  onNavigate,
  onRefresh,
  children,
}: Props) {
  const current = workspaceDefinition(activeWorkspace);
  const displayName = session?.email ?? (session?.auth_mode === "legacy" ? "本地运营身份" : "身份校验中");

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">K</div>
          <div>
            <strong>KJDS</strong>
            <span>跨境经营控制平台</span>
          </div>
        </div>

        <div className="store-switcher" aria-label="当前经营主体">
          <Store size={16} />
          <div>
            <span>当前店铺</span>
            <strong>Ozon RU · 当前作用域</strong>
          </div>
          <ChevronRight size={15} />
        </div>

        <nav aria-label="经营工作区">
          {workspaceGroups.map((group) => (
            <div className="nav-group" key={group}>
              <span className="nav-group-label">{group}</span>
              {workspaceDefinitions.filter((item) => item.group === group).map((item) => {
                const Icon = workspaceIcons[item.id];
                const selected = activeWorkspace === item.id;
                return (
                  <button
                    type="button"
                    className={selected ? "nav-item active" : "nav-item"}
                    aria-current={selected ? "page" : undefined}
                    onClick={() => onNavigate(item.id)}
                    key={item.id}
                  >
                    <Icon size={18} />
                    <span>{item.label}</span>
                    {selected ? <span className="nav-active-dot" /> : null}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-status">
          <span className="pulse" />
          <div>
            <strong>真实写入通道受控</strong>
            <span>每次外部动作都需要证据、审批、单次许可和回读</span>
          </div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div className="page-heading">
            <p className="eyebrow">{current.eyebrow}</p>
            <h1>{current.title}</h1>
            <p>{current.description}</p>
          </div>
          <div className="topbar-actions">
            <Link className="evidenceops-launch atlas-launch" href="/profit-command">
              <CircleDollarSign size={16} />
              利润指挥
            </Link>
            <Link className="evidenceops-launch atlas-launch" href="/commerce-os">
              <Boxes size={16} />
              智能 ERP
            </Link>
            <Link className="evidenceops-launch atlas-launch" href="/capability-atlas">
              <Network size={16} />
              AI 能力树
            </Link>
            <Link className="evidenceops-launch atlas-launch" href="/frontend-toolkit">
              <PanelsTopLeft size={16} />
              卖家成交页
            </Link>
            <Link className="evidenceops-launch" href="/evidenceops">
              <BrainCircuit size={16} />
              EvidenceOps
            </Link>
            <div className={ozonConnection.ready ? "live-store-chip" : "live-store-chip pending"}>
              <span className="live-dot" />
              <span>{ozonConnection.label}</span>
            </div>
            <button className="icon-action" type="button" onClick={onRefresh} aria-label="刷新全部状态">
              <RefreshCw size={17} />
            </button>
            <div className="session-chip" title={session ? `${session.actor_id} · ${session.roles.join("/")}` : ""}>
              <span className="session-avatar">{displayName.slice(0, 1).toUpperCase()}</span>
              <div>
                <strong>{displayName}</strong>
                <span>{session?.roles.join(" / ") || "正在验证权限"}</span>
              </div>
            </div>
            {session?.auth_mode === "supabase" ? (
              <form action="/auth/logout" method="post">
                <button className="icon-action" type="submit" aria-label="退出登录">
                  <LogOut size={17} />
                </button>
              </form>
            ) : null}
          </div>
        </header>

        <div className="control-boundary">
          <LockKeyhole size={16} />
          <span>当前页面不会保存平台密钥；推荐、审批与真实执行是三个独立阶段。</span>
          <button type="button" onClick={() => onNavigate("governance")}>查看执行边界</button>
        </div>

        {children}
      </section>
    </main>
  );
}
