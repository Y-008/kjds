"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import {
  Activity,
  Bot,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  FileCheck2,
  LayoutDashboard,
  Menu,
  PanelRightClose,
  ShieldCheck,
  X,
} from "lucide-react";
import styles from "./enterprise-shell.module.css";

export type EnterpriseNavItem = { label: string; href?: string; icon?: ReactNode; badge?: string };
export type EnterpriseContext = {
  tenant: string;
  entity: string;
  store: string;
  warehouse: string;
  asOf: string;
  snapshot: string;
  permission: string;
};
export type EnterpriseBreadcrumb = { label: string; href?: string };
export type EnterpriseActivity = { label: string; detail: string; time: string; tone?: "info" | "success" | "warning" };

const defaultNav: EnterpriseNavItem[] = [
  { label: "总览", href: "/commerce-os", icon: <LayoutDashboard size={17} /> },
  { label: "经营工作台", href: "/module-catalog", icon: <Activity size={17} />, badge: "12" },
  { label: "证据与治理", href: "/evidenceops", icon: <FileCheck2 size={17} /> },
  { label: "权限与策略", href: "/capability-atlas", icon: <ShieldCheck size={17} /> },
];

export function EnterpriseShell({
  children,
  nav = defaultNav,
  context,
  breadcrumbs = [],
  title,
  description,
  eyebrow = "Enterprise control plane",
  actions,
  inspector,
  activity = [],
  activeHref,
}: {
  children: ReactNode;
  nav?: EnterpriseNavItem[];
  context: EnterpriseContext;
  breadcrumbs?: EnterpriseBreadcrumb[];
  title: string;
  description?: string;
  eyebrow?: string;
  actions?: ReactNode;
  inspector?: ReactNode;
  activity?: EnterpriseActivity[];
  activeHref?: string;
}) {
  const [navOpen, setNavOpen] = useState(true);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);

  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#enterprise-main">跳转到主内容</a>
      <header className={styles.topbar}>
        <button className={styles.mobileMenu} type="button" aria-label="打开导航" aria-expanded={mobileNavOpen} onClick={() => setMobileNavOpen(true)}><Menu size={19} /></button>
        <div className={styles.brand}><span className={styles.brandMark}>K</span><span><strong>KJDS Enterprise</strong><small>AI + ERP operating system</small></span></div>
        <div className={styles.topbarMeta}><span className={styles.readOnly}>只读模式</span><span className={styles.status}><i /> Snapshot bound</span></div>
      </header>

      <div className={styles.layout}>
        <NavigationRail items={nav} collapsed={!navOpen} mobileOpen={mobileNavOpen} activeHref={activeHref} onClose={() => setMobileNavOpen(false)} onToggle={() => setNavOpen((open) => !open)} />
        {mobileNavOpen ? <button className={styles.mobileScrim} type="button" aria-label="关闭导航" onClick={() => setMobileNavOpen(false)} /> : null}

        <main id="enterprise-main" className={styles.main} tabIndex={-1}>
          <ContextBar context={context} />
          <div className={styles.contentHeader}>
            <Breadcrumbs items={breadcrumbs} />
            <PageHeader eyebrow={eyebrow} title={title} description={description} actions={actions} />
          </div>
          <div className={styles.content}>{children}</div>
        </main>

        <InspectorPanel open={inspectorOpen} onClose={() => setInspectorOpen(false)}>{inspector}</InspectorPanel>
        <div className={styles.utilityDock}>
          <button className={styles.dockButton} type="button" aria-pressed={inspectorOpen} onClick={() => setInspectorOpen((open) => !open)}><FileCheck2 size={17} /><span>Evidence / AI</span></button>
          <button className={styles.dockButton} type="button" aria-pressed={activityOpen} onClick={() => setActivityOpen((open) => !open)}><Activity size={17} /><span>Activity</span></button>
        </div>
        <ActivityDock open={activityOpen} activity={activity} onClose={() => setActivityOpen(false)} />
      </div>
    </div>
  );
}

export function NavigationRail({ items = defaultNav, collapsed = false, mobileOpen = false, activeHref, onClose, onToggle }: { items?: EnterpriseNavItem[]; collapsed?: boolean; mobileOpen?: boolean; activeHref?: string; onClose?: () => void; onToggle?: () => void }) {
  return <aside className={`${styles.navRail} ${collapsed ? styles.navRailCollapsed : ""} ${mobileOpen ? styles.navRailMobileOpen : ""}`} aria-label="一级导航"><div className={styles.navHead}><span className={styles.navTitle}>业务域</span><button className={styles.iconButton} type="button" aria-label="关闭导航" onClick={onClose}><X size={17} /></button><button className={styles.iconButton} type="button" aria-label={collapsed ? "展开导航" : "折叠导航"} onClick={onToggle}>{collapsed ? <ChevronRight size={17} /> : <ChevronLeft size={17} />}</button></div><nav className={styles.navItems}>{items.map((item) => <Link key={item.label} href={item.href ?? "#"} className={activeHref === item.href ? styles.navItemActive : styles.navItem} title={collapsed ? item.label : undefined} onClick={onClose}><span className={styles.navIcon}>{item.icon ?? <CircleHelp size={17} />}</span><span className={styles.navLabel}>{item.label}</span>{item.badge ? <span className={styles.navBadge}>{item.badge}</span> : null}</Link>)}</nav><div className={styles.navFoot}><span className={styles.navIcon}><ShieldCheck size={17} /></span><span className={styles.navLabel}>权限已校验</span></div></aside>;
}

export function Breadcrumbs({ items }: { items: EnterpriseBreadcrumb[] }) { return <nav className={styles.breadcrumbs} aria-label="面包屑">{items.map((crumb, index) => <span key={`${crumb.label}-${index}`}>{index > 0 ? <ChevronRight size={13} aria-hidden="true" /> : null}{crumb.href ? <Link href={crumb.href}>{crumb.label}</Link> : <strong>{crumb.label}</strong>}</span>)}</nav>; }

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: ReactNode }) { return <div className={styles.titleRow}><div><p className={styles.eyebrow}>{eyebrow}</p><h1>{title}</h1>{description ? <p className={styles.description}>{description}</p> : null}</div>{actions ? <div className={styles.actions}>{actions}</div> : null}</div>; }

export function InspectorPanel({ open, children, onClose }: { open: boolean; children?: ReactNode; onClose?: () => void }) { return <aside className={`${styles.inspector} ${open ? styles.inspectorOpen : ""}`} aria-label="Evidence 与 AI Inspector"><div className={styles.inspectorHead}><div><span className={styles.eyebrow}>Inspector</span><h2><Bot size={18} /> Evidence / AI</h2></div><button className={styles.iconButton} type="button" aria-label="关闭 Inspector" onClick={onClose}><PanelRightClose size={17} /></button></div>{children ?? <p className={styles.empty}>选择一条数据查看 Evidence、血缘与 AI 建议。</p>}</aside>; }

export function ContextBar({ context }: { context: EnterpriseContext }) {
  const items = [["Tenant", context.tenant], ["Entity", context.entity], ["Store", context.store], ["Warehouse", context.warehouse], ["As of", context.asOf], ["Snapshot", context.snapshot], ["Permission", context.permission]];
  return <section className={styles.contextBar} aria-label="当前作用域与快照"><div className={styles.contextLabel}>当前上下文</div>{items.map(([label, value]) => <div className={styles.contextItem} key={label}><span>{label}</span><strong>{value}</strong></div>)}</section>;
}

export function ActivityDock({ open, activity, onClose }: { open: boolean; activity: EnterpriseActivity[]; onClose: () => void }) {
  if (!open) return null;
  return <section className={styles.activityDock} aria-label="Activity 活动记录"><header><div><span className={styles.eyebrow}>Live readout</span><h2>Activity</h2></div><button className={styles.iconButton} type="button" aria-label="关闭 Activity" onClick={onClose}><X size={17} /></button></header>{activity.length ? <ol>{activity.map((entry, index) => <li key={`${entry.label}-${index}`}><span className={`${styles.activityDot} ${entry.tone ? styles[`tone${entry.tone}`] : ""}`} /><div><strong>{entry.label}</strong><p>{entry.detail}</p><time>{entry.time}</time></div></li>)}</ol> : <p className={styles.empty}>暂无新的活动记录。</p>}</section>;
}
