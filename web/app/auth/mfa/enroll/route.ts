import { mutationOriginIsAllowed } from "../../../../lib/identity-config";
import { createSupabaseServerClient } from "../../../../lib/supabase-server";
import { resolveWebIdentity, WebIdentityError } from "../../../../lib/web-identity";

export async function POST(request: Request) {
  if (!mutationOriginIsAllowed(request)) {
    return Response.json({ detail: "Cross-site or originless MFA enrollment is not allowed" }, { status: 403 });
  }
  try {
    const identity = await resolveWebIdentity({ enforceApproverMfa: false });
    if (!identity.roles.includes("approver")) {
      return Response.json({ detail: "MFA enrollment is reserved for approvers" }, { status: 403 });
    }

    const supabase = await createSupabaseServerClient();
    const { data: factors, error: factorsError } = await supabase.auth.mfa.listFactors();
    if (factorsError) throw factorsError;
    if (factors.totp.length) {
      return Response.json({ detail: "A verified TOTP factor already exists" }, { status: 409 });
    }

    for (const factor of factors.all.filter(
      (item) => item.factor_type === "totp" && item.status !== "verified",
    )) {
      const { error } = await supabase.auth.mfa.unenroll({ factorId: factor.id });
      if (error) throw error;
    }

    const { data, error } = await supabase.auth.mfa.enroll({ factorType: "totp" });
    if (error) throw error;
    return Response.json({ factor_id: data.id, qr_code: data.totp.qr_code });
  } catch (error) {
    const status = error instanceof WebIdentityError ? error.status : 503;
    return Response.json(
      { detail: error instanceof Error ? error.message : "MFA enrollment is unavailable" },
      { status },
    );
  }
}
