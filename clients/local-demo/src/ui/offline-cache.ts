export const APP_SHELL_PATHS = Object.freeze([
  "",
  "index.html",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "assets/app.css",
  "assets/app.js",
] as const);

export const APP_SHELL_READY_LABEL = `离线壳已缓存（${APP_SHELL_PATHS.length}/${APP_SHELL_PATHS.length}）`;

type CacheStatusReply = {
  type: "CACHE_STATUS";
  expected_count: number;
  cached_count: number;
  all_cached: boolean;
};

function waitForController(): Promise<ServiceWorker> {
  const current = navigator.serviceWorker.controller;
  if (current) return Promise.resolve(current);

  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      navigator.serviceWorker.removeEventListener("controllerchange", onChange);
      reject(new Error("demo_service_worker_controller_timeout"));
    }, 10_000);
    const onChange = () => {
      const controller = navigator.serviceWorker.controller;
      if (!controller) return;
      window.clearTimeout(timeout);
      navigator.serviceWorker.removeEventListener("controllerchange", onChange);
      resolve(controller);
    };
    navigator.serviceWorker.addEventListener("controllerchange", onChange);
  });
}

function queryCacheStatus(controller: ServiceWorker): Promise<CacheStatusReply> {
  return new Promise((resolve, reject) => {
    const channel = new MessageChannel();
    const timeout = window.setTimeout(() => {
      channel.port1.close();
      reject(new Error("demo_service_worker_cache_status_timeout"));
    }, 5_000);
    channel.port1.onmessage = (event: MessageEvent<CacheStatusReply>) => {
      window.clearTimeout(timeout);
      channel.port1.close();
      resolve(event.data);
    };
    controller.postMessage({ type: "CACHE_STATUS" }, [channel.port2]);
  });
}

export async function registerAndVerifyOfflineShell(): Promise<void> {
  await navigator.serviceWorker.register("./sw.js", { scope: "./" });
  await navigator.serviceWorker.ready;
  const status = await queryCacheStatus(await waitForController());
  if (
    status.type !== "CACHE_STATUS" ||
    !status.all_cached ||
    status.expected_count !== APP_SHELL_PATHS.length ||
    status.cached_count !== APP_SHELL_PATHS.length
  ) {
    throw new Error(
      `demo_app_shell_cache_readback_failed:${status.cached_count}/${status.expected_count}`,
    );
  }
}
