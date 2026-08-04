import "./styles.css";

import { renderAppShell, renderFatalShell } from "./app-shell.ts";
import {
  APP_SHELL_READY_LABEL,
  registerAndVerifyOfflineShell,
} from "./offline-cache.ts";
import { workspaceFromHash } from "./workspace-catalog.ts";

const rootElement = document.querySelector<HTMLDivElement>("#app");
if (!rootElement) {
  throw new Error("demo_shell_root_missing");
}
const root: HTMLDivElement = rootElement;

let serviceWorkerState = "离线壳准备中";

function render(): void {
  try {
    const workspace = workspaceFromHash(window.location.hash);
    const expectedHash = `#/${workspace.route}`;
    if (window.location.hash !== expectedHash) {
      window.history.replaceState(null, "", expectedHash);
    }
    root.innerHTML = renderAppShell(workspace, serviceWorkerState);
    document.title = `${workspace.shortTitle} · KJDS Local Demo`;
  } catch (error) {
    const message = error instanceof Error ? error.message : "demo_shell_unknown_error";
    root.innerHTML = renderFatalShell(message);
  }
}

function setServiceWorkerState(state: string): void {
  serviceWorkerState = state;
  const element = document.querySelector<HTMLElement>("[data-sw-state]");
  if (element) {
    element.textContent = state;
  }
}

window.addEventListener("hashchange", () => {
  render();
  document.querySelector<HTMLElement>("#main-content")?.focus({ preventScroll: true });
});

render();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void registerAndVerifyOfflineShell()
      .then(() => setServiceWorkerState(APP_SHELL_READY_LABEL))
      .catch(() => setServiceWorkerState("离线壳缓存待重试"));
  });
} else {
  setServiceWorkerState("当前浏览器不支持离线缓存");
}
