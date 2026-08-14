import {
  credentialsByActor,
  parseWebActorBindings,
} from "../../../lib/identity-config";
import {
  verifyAuthorityWorkflowTopology,
} from "../../../lib/authority-workflow-topology";
import {
  resolveWebIdentity,
  WebIdentityError,
} from "../../../lib/web-identity";

export async function GET() {
  try {
    const configurationBlockers: string[] = [];
    let credentials = new Map();
    let bindings = new Map();
    try {
      credentials = credentialsByActor(process.env.KJDS_API_KEYS_JSON);
    } catch (error) {
      configurationBlockers.push(
        error instanceof Error
          && error.message.includes("more than one API credential")
          ? "ambiguous_actor_profile"
          : "identity_configuration_invalid",
      );
    }
    try {
      bindings = parseWebActorBindings(process.env.KJDS_WEB_USER_ACTORS_JSON);
    } catch {
      configurationBlockers.push("web_binding_configuration_invalid");
    }
    const identity = configurationBlockers.length
      ? {
          authMode:
            process.env.KJDS_WEB_AUTH_MODE?.trim().toLowerCase() === "supabase"
              ? "supabase" as const
              : "legacy" as const,
          actorId: process.env.KJDS_API_ACTOR?.trim() || "unresolved",
          roles: (process.env.KJDS_API_ROLES ?? "")
            .split(",")
            .map((role) => role.trim())
            .filter(Boolean),
        }
      : await resolveWebIdentity({ enforceApproverMfa: false });
    const currentCredential = credentials.get(identity.actorId);
    const tenantRef =
      currentCredential?.tenantRef
      ?? process.env.KJDS_API_TENANT?.trim()
      ?? "default";
    const storeRef =
      currentCredential?.storeRefs[0]
      ?? process.env.KJDS_API_STORES?.split(",")[0]?.trim()
      ?? "ozon-primary";
    return Response.json(
      verifyAuthorityWorkflowTopology({
        authMode: identity.authMode,
        credentials,
        bindings,
        currentActorId: identity.actorId,
        currentRoles: identity.roles,
        tenantRef,
        storeRef,
        environment: process.env.KJDS_ENVIRONMENT?.trim() || "development",
        observedAt: new Date(),
        externalWriteAllowed: false,
        configurationBlockers,
      }),
      {
        headers: {
          "Cache-Control": "no-store",
        },
      },
    );
  } catch (error) {
    const status = error instanceof WebIdentityError ? error.status : 503;
    return Response.json(
      {
        authenticated: false,
        detail:
          error instanceof Error
            ? error.message
            : "Authority workflow topology is unavailable",
      },
      { status },
    );
  }
}
