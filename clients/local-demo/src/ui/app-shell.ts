import { WORKSPACES, type WorkspaceShellDefinition } from "./workspace-catalog.ts";

const DEMO_MARKERS = ["LOCAL DEMO", "合成数据", "不计费"] as const;

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function markerRail(): string {
  return `
    <div class="demo-rail" role="status" aria-label="本地演示声明">
      <span class="rail-beacon" aria-hidden="true"></span>
      ${DEMO_MARKERS.map((marker) => `<strong>${marker}</strong>`).join('<span aria-hidden="true">/</span>')}
      <span class="rail-note">所有界面仅为本地壳层</span>
    </div>`;
}

function navigation(active: WorkspaceShellDefinition): string {
  return WORKSPACES.map(
    (workspace, index) => `
      <a
        class="workspace-link${workspace.id === active.id ? " is-active" : ""}"
        href="#/${workspace.route}"
        ${workspace.id === active.id ? 'aria-current="page"' : ""}
      >
        <span class="workspace-index">${String(index + 1).padStart(2, "0")}</span>
        <span>${escapeHtml(workspace.shortTitle)}</span>
        <span class="workspace-dot accent-${workspace.id}" aria-hidden="true"></span>
      </a>`,
  ).join("");
}

function workspaceMatrix(active: WorkspaceShellDefinition): string {
  return WORKSPACES.map(
    (workspace) => `
      <a class="matrix-card${workspace.id === active.id ? " is-current" : ""}" href="#/${workspace.route}">
        <span class="matrix-number">${String(WORKSPACES.indexOf(workspace) + 1).padStart(2, "0")}</span>
        <strong>${escapeHtml(workspace.shortTitle)}</strong>
        <span class="matrix-state"><i aria-hidden="true"></i> 壳层就绪</span>
      </a>`,
  ).join("");
}

export function renderAppShell(active: WorkspaceShellDefinition, swState: string): string {
  return `
    ${markerRail()}
    <div class="ambient ambient-one" aria-hidden="true"></div>
    <div class="ambient ambient-two" aria-hidden="true"></div>
    <div class="app-frame">
      <aside class="sidebar" aria-label="演示工作区导航">
        <a class="brand" href="#/dashboard" aria-label="返回经营驾驶舱">
          <span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>
          <span><strong>KJDS</strong><small>ENTERPRISE DEMO</small></span>
        </a>
        <div class="scope-card">
          <span>企业演示包 · DEMO</span>
          <strong>九域经营工作台</strong>
          <small>固定合成场景 · 本地内存</small>
        </div>
        <nav class="workspace-nav">${navigation(active)}</nav>
        <div class="offline-card">
          <span class="status-light" aria-hidden="true"></span>
          <span><strong>LOCAL FIRST</strong><small data-sw-state>${escapeHtml(swState)}</small></span>
        </div>
      </aside>

      <main id="main-content" class="main-content" tabindex="-1">
        <header class="topbar">
          <div>
            <span class="topbar-kicker">SYNTHETIC OPERATING VIEW</span>
            <strong>场景版本 v1</strong>
          </div>
          <div class="topbar-meta">
            <span><i aria-hidden="true"></i> 外部写关闭</span>
            <span>演示容量 500</span>
          </div>
        </header>

        <section class="workspace-hero accent-${active.id}">
          <div class="hero-copy">
            <span class="eyebrow">${escapeHtml(active.eyebrow)} · ${escapeHtml(active.shortTitle)}</span>
            <h1>${escapeHtml(active.title)}</h1>
            <p>${escapeHtml(active.summary)}</p>
            <div class="hero-actions">
              <button type="button" disabled title="BAS-194 接入固定 ScenarioPack 后开放">场景接入待续</button>
              <span>Shell ready · Scenario queued</span>
            </div>
          </div>
          <div class="signal-orbit" aria-label="当前模块壳层状态：已就绪">
            <span class="orbit orbit-a" aria-hidden="true"></span>
            <span class="orbit orbit-b" aria-hidden="true"></span>
            <strong>${String(WORKSPACES.indexOf(active) + 1).padStart(2, "0")}</strong>
            <small>SHELL<br />READY</small>
          </div>
        </section>

        <section class="content-grid" aria-label="工作区壳层详情">
          <article class="capability-panel">
            <div class="section-heading">
              <div><span>CAPABILITY SURFACE</span><h2>模块能力面</h2></div>
              <span class="status-chip">界面已就绪</span>
            </div>
            <div class="capability-list">
              ${active.capabilities
                .map(
                  (capability, index) => `
                    <div class="capability-item">
                      <span>${String(index + 1).padStart(2, "0")}</span>
                      <strong>${escapeHtml(capability)}</strong>
                      <small>固定场景将在 BAS-194 接入</small>
                    </div>`,
                )
                .join("")}
            </div>
          </article>

          <aside class="boundary-panel">
            <div class="section-heading">
              <div><span>LOCAL BOUNDARY</span><h2>隔离边界</h2></div>
            </div>
            <dl>
              <div><dt>数据</dt><dd>仅合成</dd></div>
              <div><dt>计费</dt><dd>关闭</dd></div>
              <div><dt>外部写</dt><dd>关闭</dd></div>
              <div><dt>场景接入</dt><dd class="queued">待续</dd></div>
            </dl>
            <p>本切片只交付独立 PWA 壳，不创建真实经营对象。</p>
          </aside>
        </section>

        <section class="matrix-panel" aria-label="九工作区矩阵">
          <div class="section-heading">
            <div><span>ERP WORKSPACE MAP</span><h2>九工作区矩阵</h2></div>
            <small>选择任一工作区切换壳层</small>
          </div>
          <div class="workspace-matrix">${workspaceMatrix(active)}</div>
        </section>

        <footer>
          <span>KJDS LOCAL DEMO · BAS-193a</span>
          <span>ScenarioPack → DemoSession → LocalDemoGateway → local UI</span>
        </footer>
      </main>
    </div>`;
}

export function renderFatalShell(message: string): string {
  return `${markerRail()}<main class="fatal-shell"><span>LOCAL SHELL ERROR</span><h1>本地演示壳加载失败</h1><p>${escapeHtml(message)}</p></main>`;
}
