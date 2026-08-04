const CACHE_PREFIX = "kjds-local-demo-shell";
const CACHE_VERSION = "bas-193a-v2";
const CACHE_NAME = `${CACHE_PREFIX}-${CACHE_VERSION}`;
const APP_SHELL_PATHS = [
  "",
  "index.html",
  "manifest.webmanifest",
  "icons/icon-192.png",
  "icons/icon-512.png",
  "assets/app.css",
  "assets/app.js",
];
const FORBIDDEN_LOCAL_SEGMENT = ["back", "end"].join("");

self.appShellUrls = () =>
  APP_SHELL_PATHS.map((path) => new URL(path, self.registration.scope).href);

self.assertAppShellCached = async (cache) => {
  const reads = await Promise.all(
    self.appShellUrls().map((url) => cache.match(url, { ignoreSearch: true })),
  );
  if (reads.some((response) => !response?.ok)) {
    throw new Error("demo_app_shell_cache_incomplete");
  }
};

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then(async (cache) => {
        for (const url of self.appShellUrls()) {
          const request = new Request(url, {
            cache: "reload",
            credentials: "same-origin",
          });
          const response = await fetch(request);
          if (!response.ok) {
            throw new Error(`demo_app_shell_fetch_failed:${response.status}`);
          }
          await cache.put(url, response);
        }
        await self.assertAppShellCached(cache);
      })
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type !== "CACHE_STATUS") {
    return;
  }
  const replyPort = event.ports?.[0];
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then(async (cache) => {
        const urls = self.appShellUrls();
        const reads = await Promise.all(
          urls.map((url) => cache.match(url, { ignoreSearch: true })),
        );
        const cachedCount = reads.filter((response) => response?.ok).length;
        replyPort?.postMessage({
          type: "CACHE_STATUS",
          cache_name: CACHE_NAME,
          expected_count: urls.length,
          cached_count: cachedCount,
          all_cached: cachedCount === urls.length,
        });
      })
      .catch(() => {
        replyPort?.postMessage({
          type: "CACHE_STATUS",
          cache_name: CACHE_NAME,
          expected_count: APP_SHELL_PATHS.length,
          cached_count: 0,
          all_cached: false,
        });
      }),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
            .map((name) => caches.delete(name)),
        ),
      )
      .then(async () => {
        const cache = await caches.open(CACHE_NAME);
        await self.assertAppShellCached(cache);
        await self.clients.claim();
      }),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    event.respondWith(new Response("Local demo is read-only.", { status: 405 }));
    return;
  }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.pathname.includes(`/${FORBIDDEN_LOCAL_SEGMENT}`)) {
    event.respondWith(new Response("Local demo network boundary.", { status: 403 }));
    return;
  }
  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(url.href, { ignoreSearch: true });
      if (cached) {
        return cached;
      }
      if (request.mode === "navigate") {
        const indexUrl = new URL("index.html", self.registration.scope).href;
        const index = await cache.match(indexUrl, { ignoreSearch: true });
        if (index) {
          return index;
        }
      }
      return fetch(request).catch(
        () => new Response("Local demo asset unavailable.", { status: 503 }),
      );
    }),
  );
});
