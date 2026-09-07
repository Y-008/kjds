"use client";

import { ChevronDown, ChevronRight, ClipboardList, ExternalLink, Filter, Layers3, Search, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { moduleDomains, type ModuleDomain, type ModuleLeaf, type ModuleOperation, type ModuleWorkspace } from "./module-catalog";
import styles from "./module-catalog.module.css";

type Selection = { domain: ModuleDomain; workspace: ModuleWorkspace; module: ModuleLeaf; operation: ModuleOperation } | null;

const statusLabels = { available: "目录已登记", partial: "待补齐实现", gated: "需要运行门禁" } as const;
const workspaceRoutes: Record<string, string> = {
  "operating-command": "/",
  "market-intelligence": "/capture-inbox",
  "product-factory": "/pim",
  "content-studio": "/media-factory",
  "supply-pricing": "/sourcing-intelligence",
  "inventory-control": "/inventory",
  "order-fulfillment": "/oms",
  "returns-recovery": "/returns",
  "profit-finance": "/profit-command",
  "commercial-operations": "/commerce-os",
  "growth-command": "/growth-command",
  "evidence-control": "/evidenceops",
  "system-control": "/channel-accounts",
  "agent-project": "/project-graph",
  "platform-operations": "/team-control",
};

export function ModuleCatalogConsole() {
  const [query, setQuery] = useState("");
  const [openDomains, setOpenDomains] = useState<string[]>([moduleDomains[0].id]);
  const [openWorkspaces, setOpenWorkspaces] = useState<string[]>([moduleDomains[0].workspaces[0].id]);
  const [selected, setSelected] = useState<Selection>(null);

  const normalizedQuery = query.trim().toLowerCase();
  const filteredDomains = useMemo(() => moduleDomains.map((domain) => ({
    ...domain,
    workspaces: domain.workspaces.map((workspace) => ({
      ...workspace,
      modules: workspace.modules.map((module) => ({
        ...module,
        operations: module.operations.filter((operation) => !normalizedQuery
          || `${domain.title} ${workspace.title} ${module.title} ${operation.title} ${operation.action}`.toLowerCase().includes(normalizedQuery)),
      })).filter((module) => module.operations.length > 0),
    })).filter((workspace) => workspace.modules.length > 0),
  })).filter((domain) => domain.workspaces.length > 0), [normalizedQuery]);

  function toggle(id: string, setter: (value: (current: string[]) => string[]) => void) {
    setter((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function select(domain: ModuleDomain, workspace: ModuleWorkspace, module: ModuleLeaf, operation: ModuleOperation) {
    setSelected({ domain, workspace, module, operation });
  }

  return (
    <main className={styles.page}>
      <a className={styles.skipLink} href="#module-content">跳转到模块内容</a>
      <header className={styles.header}>
        <div className={styles.brand}><span><Layers3 size={19} /></span><div><strong>KJDS 功能模块中心</strong><small>L1 · L2 · L3 · L4 OPERATING MAP</small></div></div>
        <Link href="/commerce-os" className={styles.backLink}>返回 Commerce OS</Link>
      </header>

      <section className={styles.hero}>
        <div>
          <p className={styles.eyebrow}>NAVIGATION · HOW TO OPERATE</p>
          <h1>每个页面都有位置，<em>每个动作都有前置条件</em></h1>
          <p>一级是经营域，二级是工作台，三级是业务模块，四级是具体操作。这里解释“去哪里、怎么做、输入什么、产出什么”；运行状态和完成度仍以作用域服务端投影为准。</p>
        </div>
        <aside><ShieldCheck size={20} /><strong>导航元数据 · 运行状态分离</strong><span>不会用客户端目录推断业务完成度；当前 L4 只提供说明，不直接执行动作。</span></aside>
      </section>

      <section className={styles.toolbar} aria-label="模块筛选">
        <label><Search size={16} /><span className={styles.srOnly}>搜索模块</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索经营域、工作台、模块或操作" /></label>
        <span><Filter size={15} /> {filteredDomains.reduce((count, domain) => count + domain.workspaces.reduce((workspaceCount, workspace) => workspaceCount + workspace.modules.reduce((moduleCount, module) => moduleCount + module.operations.length, 0), 0), 0)} 个操作</span>
      </section>

      <div id="module-content" className={styles.layout}>
        <nav className={styles.tree} aria-label="四级功能模块树">
          <div className={styles.treeTitle}><strong>功能树</strong><small>点击 L4 查看操作说明</small></div>
          {filteredDomains.map((domain) => {
            const domainOpen = normalizedQuery.length > 0 || openDomains.includes(domain.id);
            return <section key={domain.id} className={styles.domain}>
              <button type="button" className={styles.domainButton} aria-expanded={domainOpen} onClick={() => toggle(domain.id, setOpenDomains)}>{domainOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}<span><strong>L1 · {domain.title}</strong><small>{domain.summary}</small></span></button>
              {domainOpen ? <div className={styles.workspaceList}>{domain.workspaces.map((workspace) => {
                const workspaceOpen = normalizedQuery.length > 0 || openWorkspaces.includes(workspace.id);
                return <div key={workspace.id} className={styles.workspace}>
                  <button type="button" className={styles.workspaceButton} aria-level={2} aria-expanded={workspaceOpen} onClick={() => toggle(workspace.id, setOpenWorkspaces)}>{workspaceOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}<span><strong>L2 · {workspace.title}</strong><small>{workspace.summary}</small></span></button>
                  {workspaceRoutes[workspace.id] ? <Link className={styles.workspaceRoute} href={workspaceRoutes[workspace.id]}>打开工作台</Link> : null}
                  {workspaceOpen ? <div className={styles.moduleList}>{workspace.modules.map((module) => <div key={module.id} className={styles.moduleGroup}>
                    <div className={styles.moduleLabel}><span>L3 · {module.title}</span><small>{module.summary}</small></div>
                    {module.operations.map((operation) => <button type="button" key={operation.id} className={`${styles.operationButton} ${selected?.operation.id === operation.id ? styles.operationSelected : ""}`} onClick={() => select(domain, workspace, module, operation)}><span>L4 · {operation.title}</span><small>{operation.action}</small></button>)}
                  </div>)}</div> : null}
                </div>;
              })}</div> : null}
            </section>;
          })}
          {!filteredDomains.length ? <p className={styles.empty}>没有匹配的模块或操作。</p> : null}
        </nav>

        <section className={styles.detail} aria-live="polite">
          {selected ? <>
            <div className={styles.breadcrumb}><span>{selected.domain.title}</span><b>›</b><span>{selected.workspace.title}</span><b>›</b><span>{selected.module.title}</span><b>›</b><strong>{selected.operation.title}</strong></div>
            <div className={styles.detailHeader}><div><p className={styles.eyebrow}>L4 OPERATION · NAVIGATION METADATA</p><h2>{selected.operation.title}</h2><p>{selected.operation.action}</p></div><span className={styles.status} data-status={selected.operation.availability}>{statusLabels[selected.operation.availability]}</span></div>
            <div className={styles.detailGrid}>
              <InfoBlock title="如何操作" icon={<ClipboardList size={16} />}><ol>{selected.operation.steps.map((step) => <li key={step}>{step}</li>)}</ol></InfoBlock>
              <InfoBlock title="输入" icon={<Layers3 size={16} />}><ul>{selected.operation.inputs.map((item) => <li key={item}>{item}</li>)}</ul></InfoBlock>
              <InfoBlock title="输出" icon={<ExternalLink size={16} />}><p>{selected.operation.output}</p></InfoBlock>
              <InfoBlock title="前置条件" icon={<ShieldCheck size={16} />}><ul>{selected.operation.preconditions.map((item) => <li key={item}>{item}</li>)}</ul></InfoBlock>
              <InfoBlock title="责任、失败与回读" icon={<ShieldCheck size={16} />}><ul><li>Owner / Reviewer：由服务端任务合同和 SoD 角色指定。</li><li>失败路径：进入 blocked、error 或 unknown_outcome，不自动冒充成功。</li><li>验收：Evidence、Lineage、外部回读和回滚引用由真实工作区提供。</li></ul></InfoBlock>
            </div>
            <div className={styles.nextStep}><strong>下一步</strong><span>进入对应业务工作区后，服务端会重新校验 tenant、entity、store、Evidence freshness 和 Permit；目录本身不会执行外部动作。</span><span>当前目录只提供操作说明；可执行入口必须绑定真实业务路由、action registry、readback 和 rollback 合同。</span></div>
          </> : <div className={styles.placeholder}><Layers3 size={34} /><h2>选择一个四级操作</h2><p>从左侧按 L1 → L2 → L3 → L4 展开，右侧查看操作步骤、输入、输出和前置条件。</p></div>}
        </section>
      </div>
    </main>
  );
}

function InfoBlock({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return <article className={styles.infoBlock}><h3>{icon}{title}</h3>{children}</article>;
}
