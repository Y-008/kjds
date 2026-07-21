export type WebAuthMode = "legacy" | "supabase";

export type WebActorBinding = { actorId: string };
export type ApiCredential = { actorId: string; roles: string[]; apiKey: string };

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
  if (!raw?.trim()) throw new Error("KJDS_API_KEYS_JSON is required for Supabase Web authentication");
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
    if (credentials.has(actorId)) throw new Error(`KJDS actor ${actorId} has more than one API credential`);
    credentials.set(actorId, { actorId, roles: roles.map((role) => (role as string).trim()), apiKey });
  }
  return credentials;
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

export function mutationOriginIsAllowed(request: Request): boolean {
  const method = request.method.toUpperCase();
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return true;
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    return new URL(origin).origin === new URL(request.url).origin;
  } catch {
    return false;
  }
}
