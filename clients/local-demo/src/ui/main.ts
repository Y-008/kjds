import "./styles.css";

import { LocalDemoGateway, type DemoEnvelope } from "../application/local-demo-gateway.ts";
import type {
  DemoSessionSnapshot,
  DemoWorkspace,
  ScenarioHeroStep,
} from "../domain/contracts.ts";
import { loadScenarioPack } from "../domain/scenario-pack.ts";
import scenarioV2 from "../scenarios/enterprise-overview.zh-CN.v2.json" with { type: "json" };
import { renderAppShell, renderFatalShell, type AppRuntimeView } from "./app-shell.ts";
import { APP_SHELL_READY_LABEL, registerAndVerifyOfflineShell } from "./offline-cache.ts";
import { workspaceFromHash } from "./workspace-catalog.ts";

const SESSION_ID = "demo-session-browser-v2";
const pack = loadScenarioPack(scenarioV2);
const gateway = new LocalDemoGateway(pack, {
  gateway_scope_token: "demo-browser-scope-v2",
  session_id_factory: () => SESSION_ID,
});

const rootElement = document.querySelector<HTMLDivElement>("#app");
if (!rootElement) throw new Error("demo_shell_root_missing");
const root: HTMLDivElement = rootElement;

let serviceWorkerState = "离线壳准备中";
let stateSha256 = "";
let sequence = 0;
let initialStateSha256 = "";
let operation = "固定 ScenarioPack v2 已打开";
let errorCode: string | null = null;
let resetRestored = false;
const initialReadModelHashes = new Map<DemoWorkspace, string>();

function absorbEnvelope(envelope: DemoEnvelope<unknown>): void {
  stateSha256 = envelope.state_sha256;
  sequence = envelope.sequence;
  errorCode = envelope.error?.code ?? null;
}

function openScenario(): DemoEnvelope<DemoSessionSnapshot> {
  const response = gateway.open_session({
    scenario_ref: pack.scenario_ref,
    locale: pack.locale,
  });
  absorbEnvelope(response);
  if (response.error || !response.data) {
    throw new Error(response.error?.code ?? "demo_open_failed");
  }
  if (initialStateSha256.length === 0) initialStateSha256 = response.state_sha256;
  return response;
}

openScenario();
for (const workspace of [
  "dashboard", "sourcing", "pim", "listings", "oms", "fulfillment",
  "customer_service", "growth", "profit",
] as const) {
  const baseline = gateway.query({ session_id: SESSION_ID, workspace });
  if (baseline.data) initialReadModelHashes.set(workspace, baseline.data.read_model_sha256);
}

function currentRuntime(workspace: DemoWorkspace): AppRuntimeView {
  const query = gateway.query({ session_id: SESSION_ID, workspace });
  stateSha256 = query.state_sha256;
  sequence = query.sequence;
  return {
    scenarioVersion: pack.scenario_version,
    scenarioSha256: pack.scenario_sha256,
    sequence,
    stateSha256,
    readModelSha256: query.data?.read_model_sha256 ?? "query-error",
    items: query.data?.items ?? [],
    summary: query.data?.summary ?? {},
    operation,
    errorCode: errorCode ?? query.error?.code ?? null,
    heroFlows: pack.hero_flows ?? [],
    resetRestored,
  };
}

function render(): void {
  try {
    const workspace = workspaceFromHash(window.location.hash);
    const expectedHash = `#/${workspace.route}`;
    if (window.location.hash !== expectedHash) window.history.replaceState(null, "", expectedHash);
    root.innerHTML = renderAppShell(workspace, serviceWorkerState, currentRuntime(workspace.id));
    document.title = `${workspace.shortTitle} · KJDS Local Demo`;
  } catch (error) {
    root.innerHTML = renderFatalShell(error instanceof Error ? error.message : "demo_unknown_error");
  }
}

function setServiceWorkerState(state: string): void {
  serviceWorkerState = state;
  const element = document.querySelector<HTMLElement>("[data-sw-state]");
  if (element) element.textContent = state;
}

function resetAndReopen(announce: boolean): void {
  const reset = gateway.reset({ session_id: SESSION_ID });
  if (reset.error) throw new Error(reset.error.code);
  openScenario();
  const workspace = workspaceFromHash(window.location.hash).id;
  const baseline = gateway.query({ session_id: SESSION_ID, workspace });
  resetRestored =
    baseline.scenario_sha256 === pack.scenario_sha256 &&
    baseline.state_sha256 === initialStateSha256 &&
    baseline.data?.read_model_sha256 === initialReadModelHashes.get(workspace);
  errorCode = null;
  if (announce) operation = resetRestored ? "场景 / 状态 / Read Model 哈希已恢复" : "重置校验失败";
}

function applyStep(step: ScenarioHeroStep, keyPrefix: string): boolean {
  const response = gateway.apply({
    session_id: SESSION_ID,
    action: step.action,
    subject_ref: step.subject_ref,
    payload: step.payload,
    idempotency_key: `${keyPrefix}-${step.step_id}-${sequence + 1}`,
    expected_state_sha256: stateSha256,
  });
  absorbEnvelope(response);
  if (response.error) {
    operation = `${step.label} 未推进`;
    return false;
  }
  operation = `${step.label} · transition ${response.data?.transition.sequence ?? sequence}`;
  return true;
}

function runSteps(steps: readonly ScenarioHeroStep[], keyPrefix: string): void {
  for (const step of steps) {
    if (!applyStep(step, keyPrefix)) return;
  }
  errorCode = null;
}

function customStep(workspace: "dashboard" | "customer_service" | "growth"): ScenarioHeroStep {
  if (workspace === "dashboard") return {
    step_id: "demo-step-dashboard-refresh",
    label: "刷新合成经营信号",
    workspace,
    action: "refresh_dashboard",
    subject_ref: "demo-store-001",
    payload: { target: "refreshed" },
  };
  if (workspace === "customer_service") return {
    step_id: "demo-step-service-draft",
    label: "生成合成回复草稿",
    workspace,
    action: "draft_customer_reply",
    subject_ref: "demo-order-001",
    payload: { target: "drafted" },
  };
  return {
    step_id: "demo-step-growth-simulate",
    label: "模拟增长活动",
    workspace,
    action: "simulate_campaign",
    subject_ref: "demo-store-001",
    payload: { target: "positive_signal" },
  };
}

function stepsForWorkspace(workspace: DemoWorkspace): readonly ScenarioHeroStep[] {
  const flows = pack.hero_flows ?? [];
  const opportunity = flows[0]?.steps ?? [];
  const order = flows[1]?.steps ?? [];
  const profit = flows[2]?.steps ?? [];
  if (workspace === "dashboard" || workspace === "customer_service" || workspace === "growth") {
    return [customStep(workspace)];
  }
  if (workspace === "sourcing") return opportunity.slice(0, 1);
  if (workspace === "pim") return opportunity.slice(0, 2);
  if (workspace === "listings") return opportunity;
  if (workspace === "oms") return order.slice(0, 1);
  if (workspace === "fulfillment") return order;
  return profit;
}

function runWorkspaceAdvance(): void {
  const workspace = workspaceFromHash(window.location.hash).id;
  resetAndReopen(false);
  runSteps(stepsForWorkspace(workspace), `demo-ui-${workspace}`);
  operation = errorCode ? operation : `${workspace} 模拟推进完成 · SEQ ${sequence}`;
  render();
}

function runHeroFlow(flowId: string): void {
  const flow = pack.hero_flows?.find((candidate) => candidate.flow_id === flowId);
  if (!flow) throw new Error("demo_hero_flow_not_found");
  resetAndReopen(false);
  runSteps(flow.steps, flow.flow_id);
  operation = errorCode ? operation : `${flow.title} · 确定性旅程完成`;
  render();
}

function replayExpectedStateError(): void {
  const workspace = workspaceFromHash(window.location.hash).id;
  const step = stepsForWorkspace(workspace).at(-1);
  if (!step) throw new Error("demo_replay_step_missing");
  const request = {
    session_id: SESSION_ID,
    action: step.action,
    subject_ref: step.subject_ref,
    payload: step.payload,
    idempotency_key: `demo-error-${workspace}-${sequence}`,
    expected_state_sha256: "0".repeat(64),
  };
  const first = gateway.apply(request);
  const replay = gateway.apply(request);
  absorbEnvelope(replay);
  const deterministic = JSON.stringify(first) === JSON.stringify(replay);
  operation = deterministic ? "expected-state 错误已确定性重放，状态未推进" : "错误重放漂移";
  render();
}

root.addEventListener("click", (event) => {
  const button = (event.target as Element).closest<HTMLButtonElement>("button");
  if (!button) return;
  if (button.matches("[data-advance]")) runWorkspaceAdvance();
  else if (button.matches("[data-error-replay]")) replayExpectedStateError();
  else if (button.matches("[data-reset]")) {
    resetAndReopen(true);
    render();
  } else if (button.dataset.heroFlow) runHeroFlow(button.dataset.heroFlow);
});

window.addEventListener("hashchange", () => {
  errorCode = null;
  operation = "工作区 Read Model 已查询";
  render();
  document.querySelector<HTMLElement>("#main-content")?.focus({ preventScroll: true });
});

render();
if ("serviceWorker" in navigator) {
  const startOfflineShell = () => {
    void registerAndVerifyOfflineShell()
      .then(() => setServiceWorkerState(APP_SHELL_READY_LABEL))
      .catch(() => setServiceWorkerState("离线壳缓存待重试"));
  };
  startOfflineShell();
} else {
  setServiceWorkerState("当前浏览器不支持离线缓存");
}
