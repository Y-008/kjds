import "server-only";

import {
  approverMfaRequired,
  credentialsByActor,
  parseWebActorBindings,
  resolveLegacyApiCredential,
  validateWebApprovalTopology,
  webAuthMode,
} from "./identity-config";
import { createSupabaseServerClient } from "./supabase-server";

export type ResolvedWebIdentity = {
  apiKey: string;
  authMode: "legacy" | "supabase";
  userId: string | null;
  email: string | null;
  actorId: string;
  roles: string[];
  tenantRef: string;
  storeRefs: string[];
};

export async function resolveWebIdentity(
  { enforceApproverMfa = true }: { enforceApproverMfa?: boolean } = {},
): Promise<ResolvedWebIdentity> {
  const mode = webAuthMode();
  if (mode === "legacy") {
    const credential = resolveLegacyApiCredential();
    return {
      apiKey: credential.apiKey,
      authMode: "legacy",
      userId: null,
      email: null,
      actorId: credential.actorId,
      roles: credential.roles,
      tenantRef: credential.tenantRef,
      storeRefs: credential.storeRefs,
    };
  }

  const bindings = parseWebActorBindings(process.env.KJDS_WEB_USER_ACTORS_JSON);
  const credentials = credentialsByActor(process.env.KJDS_API_KEYS_JSON);
  validateWebApprovalTopology(bindings, credentials);
  const supabase = await createSupabaseServerClient();
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) throw new WebIdentityError(401, "Authentication required");

  const binding = bindings.get(data.user.id);
  if (!binding) throw new WebIdentityError(403, "Authenticated user has no KJDS actor binding");
  const credential = credentials.get(binding.actorId);
  if (!credential) throw new WebIdentityError(403, "Bound KJDS actor has no API credential");
  if (enforceApproverMfa && credential.roles.includes("approver")) {
    const { data: assurance, error: assuranceError } =
      await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
    if (assuranceError) throw new WebIdentityError(503, "MFA assurance level is unavailable");
    if (approverMfaRequired(credential.roles, assurance.currentLevel)) {
      throw new WebIdentityError(428, "MFA verification required");
    }
  }
  return {
    apiKey: credential.apiKey,
    authMode: "supabase",
    userId: data.user.id,
    email: data.user.email ?? null,
    actorId: credential.actorId,
    roles: credential.roles,
    tenantRef: credential.tenantRef,
    storeRefs: credential.storeRefs,
  };
}

export class WebIdentityError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}
