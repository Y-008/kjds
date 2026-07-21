import { createSupabaseServerClient } from "../../../../lib/supabase-server";
import { resolveWebIdentity, WebIdentityError } from "../../../../lib/web-identity";

export async function GET() {
  try {
    const identity = await resolveWebIdentity({ enforceApproverMfa: false });
    const supabase = await createSupabaseServerClient();
    const [{ data: assurance, error: assuranceError }, { data: factors, error: factorsError }] =
      await Promise.all([
        supabase.auth.mfa.getAuthenticatorAssuranceLevel(),
        supabase.auth.mfa.listFactors(),
      ]);
    if (assuranceError || factorsError) throw new Error("MFA state is unavailable");

    return Response.json({
      required: identity.roles.includes("approver"),
      verified: assurance.currentLevel === "aal2",
      enrolled: Boolean(factors.totp.length),
      factor_id: factors.totp[0]?.id ?? null,
    });
  } catch (error) {
    const status = error instanceof WebIdentityError ? error.status : 503;
    return Response.json(
      { detail: error instanceof Error ? error.message : "MFA is unavailable" },
      { status },
    );
  }
}
