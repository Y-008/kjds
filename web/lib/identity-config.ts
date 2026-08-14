export type WebAuthMode = "legacy" | "supabase";

export type WebActorBinding = { actorId: string };
export type ApiCredential = {
  actorId: string;
  roles: string[];
  apiKey: string;
  tenantRef: string;
  storeRefs: string[];
  scopeExplicit: boolean;
};

export function webAuthMode(environment: NodeJS.ProcessEnv = process.env): WebAuthMode {
  const configured = (environment.KJDS_WEB_AUTH_MODE ?? "legacy").trim().toLowerCase();
  if (configured !== "legacy" && configured !== "supabase") {
    throw new Error("KJDS_WEB_AUTH_MODE must be legacy or supabase");
  }
  if (configured === "legacy" && environment.KJDS_ENVIRONMENT === "production") {
    throw new Error("Production Web requires KJDS_WEB_AUTH_MODE=supabase");
  }
  return configured;
}

export function parseWebActorBindings(raw: string | undefined): Map<string, WebActorBinding> {
  if (!raw?.trim()) return new Map();

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("KJDS_WEB_USER_ACTORS_JSON is not valid JSON");
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("KJDS_WEB_USER_ACTORS_JSON must be an object keyed by Supabase user ID");
  }

  const bindings = new Map<string, WebActorBinding>();
  for (const [userId, value] of Object.entries(parsed)) {
    if (!userId.trim()) throw new Error("Web identity user ID cannot be empty");
    const actorId =
      typeof value === "string"
        ? value.trim()
        : value && typeof value === "object" && "actor" in value && typeof value.actor === "string"
          ? value.actor.trim()
          : "";
    if (!actorId) {
      throw new Error(`Web identity ${userId} must map to a non-empty actor`);
    }
    bindings.set(userId, { actorId });
  }
  return bindings;
}

export function credentialsByActor(raw: string | undefined): Map<string, ApiCredential> {
  if (!raw?.trim()) throw new Error("KJDS_API_KEYS_JSON is required for Web server identity resolution");
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error("KJDS_API_KEYS_JSON is not valid JSON");
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("KJDS_API_KEYS_JSON must be an object keyed by API key");
  }

  const credentials = new Map<string, ApiCredential>();
  for (const [apiKey, profile] of Object.entries(parsed)) {
    if (!apiKey.trim() || !profile || typeof profile !== "object") {
      throw new Error("Every API credential requires a key and profile");
    }
    const actorId = "actor" in profile && typeof profile.actor === "string" ? profile.actor.trim() : "";
    const roles: unknown[] = "roles" in profile && Array.isArray(profile.roles) ? profile.roles : [];
    if (!actorId || !roles.length || !roles.every((role) => typeof role === "string" && role.trim())) {
      throw new Error("Every API credential requires an actor and string role list");
    }
    const tenantRef =
      "tenant" in profile && typeof profile.tenant === "string"
        ? profile.tenant.trim()
        : "default";
    const storeRefs: unknown[] =
      "stores" in profile && Array.isArray(profile.stores)
        ? profile.stores
        : ["ozon-primary"];
    if (
      !tenantRef
      || !storeRefs.length
      || !storeRefs.every((store) => typeof store === "string" && store.trim())
    ) {
      throw new Error("Every API credential requires a valid tenant and store scope");
    }
    if (credentials.has(actorId)) throw new Error(`KJDS actor ${actorId} has more than one API credential`);
    credentials.set(actorId, {
      actorId,
      roles: roles.map((role) => (role as string).trim()),
      apiKey,
      tenantRef,
      storeRefs: storeRefs.map((store) => (store as string).trim()),
      scopeExplicit: "tenant" in profile && "stores" in profile,
    });
  }
  return credentials;
}

export function resolveLegacyApiCredential(
  environment: NodeJS.ProcessEnv = process.env,
): ApiCredential {
  const configuredActorId = environment.KJDS_API_ACTOR?.trim();
  const directApiKey = environment.KJDS_API_KEY?.trim();
  if (directApiKey) {
    return {
      actorId: configuredActorId || "local-operator",
      apiKey: directApiKey,
      roles: (environment.KJDS_API_ROLES ?? "operator")
        .split(",")
        .map((role) => role.trim())
        .filter(Boolean),
      tenantRef: environment.KJDS_API_TENANT?.trim() || "default",
      storeRefs: (environment.KJDS_API_STORES ?? "ozon-primary")
        .split(",")
        .map((store) => store.trim())
        .filter(Boolean),
      scopeExplicit: Boolean(
        environment.KJDS_API_TENANT?.trim()
        && environment.KJDS_API_STORES?.trim(),
      ),
    };
  }
  const credentials = credentialsByActor(environment.KJDS_API_KEYS_JSON);
  if (configuredActorId) {
    const credential = credentials.get(configuredActorId);
    if (!credential) {
      throw new Error(`KJDS server identity actor ${configuredActorId} has no API credential`);
    }
    return credential;
  }
  const operatorCredentials = [...credentials.values()].filter((credential) =>
    credential.roles.includes("operator"),
  );
  if (operatorCredentials.length !== 1) {
    throw new Error(
      "Legacy Web requires KJDS_API_ACTOR when the credential map does not contain exactly one operator",
    );
  }
  return operatorCredentials[0];
}

export function validateWebApprovalTopology(
  bindings: Map<string, WebActorBinding>,
  credentials: Map<string, ApiCredential>,
): void {
  const operatorUsers = new Set<string>();
  const approverUsers = new Set<string>();
  for (const [userId, binding] of bindings) {
    const roles = credentials.get(binding.actorId)?.roles ?? [];
    if (roles.includes("operator")) operatorUsers.add(userId);
    if (roles.includes("approver")) approverUsers.add(userId);
  }
  if (!operatorUsers.size || !approverUsers.size) {
    throw new Error("Supabase Web requires independently bound operator and approver users");
  }
  for (const userId of operatorUsers) {
    if (approverUsers.has(userId)) {
      throw new Error("The same Supabase user cannot be both Web operator and approver");
    }
  }
}

export function approverMfaRequired(roles: string[], currentLevel: string | null): boolean {
  return roles.includes("approver") && currentLevel !== "aal2";
}

function mutationRequestOrigins(request: Request): Set<string> {
  const requestUrl = new URL(request.url);
  const origins = new Set<string>([requestUrl.origin]);
  const host = request.headers.get("host")?.trim();
  if (host) {
    origins.add(new URL(`${requestUrl.protocol}//${host}`).origin);
  }
  const configuredPublicOrigin = process.env.KJDS_WEB_PUBLIC_ORIGIN?.trim();
  if (configuredPublicOrigin) {
    origins.add(new URL(configuredPublicOrigin).origin);
  }
  return origins;
}

export function webRequestUrl(request: Request, path: string): URL {
  const configuredPublicOrigin = process.env.KJDS_WEB_PUBLIC_ORIGIN?.trim();
  if (configuredPublicOrigin) {
    return new URL(path, new URL(configuredPublicOrigin).origin);
  }
  const requestUrl = new URL(request.url);
  const host = request.headers.get("host")?.trim();
  if (host) {
    return new URL(path, `${requestUrl.protocol}//${host}`);
  }
  return new URL(path, requestUrl);
}

export function webRedirect(request: Request, path: string): Response {
  return Response.redirect(webRequestUrl(request, path), 303);
}

export function rejectedLoginResponse(request: Request): Response {
  const loginUrl = webRequestUrl(request, "/login").href
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
  return new Response(
    `<!doctype html><html lang="zh-CN"><meta charset="utf-8">`
    + `<meta name="viewport" content="width=device-width,initial-scale=1">`
    + `<title>KJDS 登录请求已拒绝</title>`
    + `<main style="max-width:42rem;margin:12vh auto;padding:2rem;font:16px/1.7 system-ui">`
    + `<h1>登录请求已被安全门拒绝</h1>`
    + `<p>该请求不是从可信的 KJDS 登录页发起，没有提交任何登录凭据。</p>`
    + `<p><a href="${loginUrl}">返回 KJDS 登录页</a></p></main></html>`,
    {
      status: 403,
      headers: {
        "cache-control": "no-store",
        "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'",
        "content-type": "text/html; charset=utf-8",
        "x-content-type-options": "nosniff",
      },
    },
  );
}

export function mutationOriginIsAllowed(request: Request): boolean {
  const method = request.method.toUpperCase();
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return true;
  const origin = request.headers.get("origin");
  try {
    const requestOrigins = mutationRequestOrigins(request);
    if (origin && origin !== "null") return requestOrigins.has(new URL(origin).origin);
    if (request.headers.get("x-kjds-csrf") === "same-origin-fetch") return true;
    const fetchSite = request.headers.get("sec-fetch-site");
    const referer = request.headers.get("referer");
    return (
      Boolean(referer)
      && requestOrigins.has(new URL(referer as string).origin)
      && fetchSite !== "cross-site"
    );
  } catch {
    return false;
  }
}
