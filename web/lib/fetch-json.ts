export type JsonResponse<T = any> = {
  ok: boolean;
  status: number;
  json: () => Promise<T>;
};

const failureResponse = (error: unknown): JsonResponse => ({
  ok: false,
  status: 0,
  json: async () => ({ detail: error instanceof Error ? error.message : "网络请求失败" }),
});

export async function fetchJson<T = any>(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs = 15_000,
): Promise<JsonResponse<T>> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort("request timeout"), timeoutMs);
  const abort = () => controller.abort(init.signal?.reason);
  if (init.signal?.aborted) abort();
  else init.signal?.addEventListener("abort", abort, { once: true });

  try {
    const response = await fetch(input, { ...init, signal: controller.signal });
    const body = await response.json().catch(() => ({}));
    return { ok: response.ok, status: response.status, json: async () => body as T };
  } catch (error) {
    return failureResponse(error);
  } finally {
    globalThis.clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abort);
  }
}

export async function settleJsonRequests(
  requests: Array<Promise<JsonResponse>>,
): Promise<JsonResponse[]> {
  return (await Promise.allSettled(requests)).map((result) =>
    result.status === "fulfilled" ? result.value : failureResponse(result.reason),
  );
}
