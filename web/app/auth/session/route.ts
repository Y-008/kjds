import { resolveWebIdentity, WebIdentityError } from "../../../lib/web-identity";

export async function GET() {
  try {
    const identity = await resolveWebIdentity();
    return Response.json({
      authenticated: true,
      auth_mode: identity.authMode,
      email: identity.email,
      actor_id: identity.actorId,
      roles: identity.roles,
      tenant_ref: identity.tenantRef,
      store_refs: identity.storeRefs,
      default_store_ref: identity.storeRefs[0],
    });
  } catch (error) {
    const status = error instanceof WebIdentityError ? error.status : 503;
    return Response.json(
      {
        authenticated: false,
        detail: error instanceof Error ? error.message : "Web identity is unavailable",
      },
      { status },
    );
  }
}
