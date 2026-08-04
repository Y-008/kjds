import type { JsonValue, ScenarioHeroFlow } from "../domain/contracts.ts";
import { WORKSPACES, type WorkspaceShellDefinition } from "./workspace-catalog.ts";

const DEMO_MARKERS = ["LOCAL DEMO", "合成数据", "不计费"] as const;

export interface AppRuntimeView {
  readonly scenarioVersion: string;
  readonly scenarioSha256: string;
  readonly sequence: number;
  readonly stateSha256: string;
  readonly readModelSha256: string;
  readonly items: readonly JsonValue[];
  readonly summary: JsonValue;
  readonly operation: string;
  readonly errorCode: string | null;
  readonly heroFlows: readonly ScenarioHeroFlow[];
  readonly resetRestored: boolean;
}

const EMPTY_RUNTIME: AppRuntimeView = {
  scenarioVersion: "v2",
  scenarioSha256: "pending",
  sequence: 0,
  stateSha256: "pending",
  readModelSha256: "pending",
  items: [],
  summary: {},
  operation: "固定场景正在打开",
  errorCode: null,
  heroFlows: [],
  resetRestored: false,
};

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortHash(value: string): string {
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

function markerRail(): string {
  return `
    <div class="demo-rail" role="status" aria-label="本地演示声明">
      <span class="rail-beacon" aria-hidden="true"></span>
      ${DEMO_MARKERS.map((marker) => `<strong>${marker}</strong>`).join('<span aria-hidden="true">/</span>')}
      <span class="rail-note">固定合成场景 · 全程零外写</span>
    </div>`;
}

function navigation(active: WorkspaceShellDefinition): string {
  return WORKSPACES.map(
    (workspace, index) => `
      <a class="workspace-link${workspace.id === active.id ? " is-active" : ""}"
        href="#/${workspace.route}" ${workspace.id === active.id ? 'aria-current="page"' : ""}>
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
        <span class="matrix-state"><i aria-hidden="true"></i> 可查询 · 可推进</span>
      </a>`,
  ).join("");
}

function valueText(value: JsonValue): string {
  if (value === null) return "null";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function readModelItems(items: readonly JsonValue[]): string {
  if (items.length === 0) return '<p class="empty-state">当前工作区为 no_data。</p>';
  return items.slice(0, 6).map((item, index) => {
    const record = typeof item === "object" && item !== null && !Array.isArray(item)
      ? item
      : { value: item };
    const entries = Object.entries(record);
    const priority = entries.filter(([key]) =>
      /(?:state|decision|profit|fee|stock)/u.test(key),
    );
    const fields = [...priority, ...entries.filter((entry) => !priority.includes(entry))].slice(0, 6);
    return `<article class="query-item" data-query-item>
      <span class="query-index">${String(index + 1).padStart(2, "0")}</span>
      <div>${fields.map(([key, value]) => `<p><small>${escapeHtml(key)}</small><strong>${escapeHtml(valueText(value))}</strong></p>`).join("")}</div>
    </article>`;
  }).join("");
}

function heroFlowCards(flows: readonly ScenarioHeroFlow[]): string {
  return flows.map((flow, index) => `
    <article class="journey-card">
      <span>HERO ${String(index + 1).padStart(2, "0")}</span>
      <h3>${escapeHtml(flow.title)}</h3>
      <p>${escapeHtml(flow.outcome)}</p>
      <ol>${flow.steps.map((step) => `<li>${escapeHtml(step.label)}</li>`).join("")}</ol>
      <button type="button" data-hero-flow="${escapeHtml(flow.flow_id)}">运行确定性旅程</button>
    </article>`,
  ).join("");
}

export function renderAppShell(
  active: WorkspaceShellDefinition,
  swState: string,
  runtime: AppRuntimeView = EMPTY_RUNTIME,
): string {
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
        <div class="scope-card"><span>企业演示包 · DEMO</span><strong>九域经营工作台</strong><small>ScenarioPack v2 · 本地内存</small></div>
        <nav class="workspace-nav">${navigation(active)}</nav>
        <div class="offline-card"><span class="status-light" aria-hidden="true"></span><span><strong>LOCAL FIRST</strong><small data-sw-state>${escapeHtml(swState)}</small></span></div>
      </aside>

      <main id="main-content" class="main-content" tabindex="-1">
        <header class="topbar">
          <div><span class="topbar-kicker">SYNTHETIC OPERATING VIEW</span><strong>场景版本 ${escapeHtml(runtime.scenarioVersion)}</strong></div>
          <div class="topbar-meta"><span><i aria-hidden="true"></i> 外部写关闭</span><span data-sequence>SEQ ${runtime.sequence}</span></div>
        </header>

        <section class="workspace-hero accent-${active.id}">
          <div class="hero-copy">
            <span class="eyebrow">${escapeHtml(active.eyebrow)} · ${escapeHtml(active.shortTitle)}</span>
            <h1>${escapeHtml(active.title)}</h1><p>${escapeHtml(active.summary)}</p>
            <div class="hero-actions">
              <button type="button" data-advance>模拟推进</button>
              <button type="button" data-error-replay>错误重放</button>
              <button type="button" data-reset>重置场景</button>
            </div>
            <p class="operation-state${runtime.errorCode ? " is-error" : ""}" data-operation>
              ${escapeHtml(runtime.errorCode ? `${runtime.errorCode} · ${runtime.operation}` : runtime.operation)}
            </p>
          </div>
          <div class="signal-orbit" aria-label="当前模块场景状态：可交互"><span class="orbit orbit-a" aria-hidden="true"></span><span class="orbit orbit-b" aria-hidden="true"></span><strong>${String(WORKSPACES.indexOf(active) + 1).padStart(2, "0")}</strong><small>SCENARIO<br />READY</small></div>
        </section>

        <section class="runtime-strip" aria-label="确定性状态">
          <div><span>SCENARIO SHA</span><strong>${escapeHtml(shortHash(runtime.scenarioSha256))}</strong></div>
          <div><span>STATE SHA</span><strong>${escapeHtml(shortHash(runtime.stateSha256))}</strong></div>
          <div><span>READ MODEL SHA</span><strong>${escapeHtml(shortHash(runtime.readModelSha256))}</strong></div>
          <div><span>RESET</span><strong>${runtime.resetRestored ? "HASH RESTORED" : "READY"}</strong></div>
        </section>

        <section class="content-grid" aria-label="工作区场景详情">
          <article class="capability-panel">
            <div class="section-heading"><div><span>LIVE READ MODEL</span><h2>${escapeHtml(active.shortTitle)} 查询结果</h2></div><span class="status-chip">${runtime.items.length} 条</span></div>
            <div class="query-list">${readModelItems(runtime.items)}</div>
          </article>
          <aside class="boundary-panel">
            <div class="section-heading"><div><span>LOCAL BOUNDARY</span><h2>隔离与状态</h2></div></div>
            <dl><div><dt>数据</dt><dd>仅合成</dd></div><div><dt>计费</dt><dd>关闭</dd></div><div><dt>外部写</dt><dd>关闭</dd></div><div><dt>场景接入</dt><dd class="ready">已就绪</dd></div></dl>
            <p>所有推进仅写本页内存 session；query 由 append-only transition 派生。</p>
          </aside>
        </section>

        <section class="journey-panel" aria-label="三条 Hero Flow">
          <div class="section-heading"><div><span>DETERMINISTIC HERO FLOWS</span><h2>三条端到端合成旅程</h2></div><small>每次运行先重置到同一场景哈希</small></div>
          <div class="journey-grid">${heroFlowCards(runtime.heroFlows)}</div>
        </section>

        <section class="matrix-panel" aria-label="九工作区矩阵"><div class="section-heading"><div><span>ERP WORKSPACE MAP</span><h2>九工作区矩阵</h2></div><small>均已接入 query / apply / replay / reset</small></div><div class="workspace-matrix">${workspaceMatrix(active)}</div></section>
        <footer><span>KJDS LOCAL DEMO · BAS-194</span><span>ScenarioPack v2 → DemoSession → LocalDemoGateway → transition-derived UI</span></footer>
      </main>
    </div>`;
}

export function renderFatalShell(message: string): string {
  return `${markerRail()}<main class="fatal-shell"><span>LOCAL SHELL ERROR</span><h1>本地演示加载失败</h1><p>${escapeHtml(message)}</p></main>`;
}
