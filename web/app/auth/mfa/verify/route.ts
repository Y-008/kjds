import { mutationOriginIsAllowed } from "../../../../lib/identity-config";
import { createSupabaseServerClient } from "../../../../lib/supabase-server";
import { resolveWebIdentity, WebIdentityError } from "../../../../lib/web-identity";

export async function POST(request: Request) {
  if (!mutationOriginIsAllowed(request)) {
    return Response.json({ detail: "Cross-site or originless MFA verification is not allowed" }, { status: 403 });
  }
  try {
    const identity = await resolveWebIdentity({ enforceApproverMfa: false });
    if (!identity.roles.includes("approver")) {
      return Response.json({ detail: "MFA verification is reserved for approvers" }, { status: 403 });
    }

    const body = (await request.json()) as { factor_id?: unknown; code?: unknown };
    const factorId = typeof body.factor_id === "string" ? body.factor_id.trim() : "";
    const code = typeof body.code === "string" ? body.code.trim() : "";
    if (!factorId || !/^\d{6}$/.test(code)) {
      return Response.json({ detail: "A valid TOTP factor and six-digit code are required" }, { status: 400 });
    }

    const supabase = await createSupabaseServerClient();
    const { data: factors, error: factorsError } = await supabase.auth.mfa.listFactors();
    if (factorsError) throw factorsError;
    const factor = factors.all.find((item) => item.id === factorId && item.factor_type === "totp");
    if (!factor) {
      return Response.json({ detail: "TOTP factor does not belong to the current user" }, { status: 403 });
    }

    const { data: challenge, error: challengeError } = await supabase.auth.mfa.challenge({ factorId });
    if (challengeError) {
      return Response.json({ detail: "Unable to create MFA challenge" }, { status: 400 });
    }
    const { error: verifyError } = await supabase.auth.mfa.verify({
      factorId,
      challengeId: challenge.id,
      code,
    });
    if (verifyError) {
      return Response.json({ detail: "The MFA code is invalid or expired" }, { status: 400 });
    }
    return Response.json({ verified: true });
  } catch (error) {
    const status = error instanceof WebIdentityError ? error.status : 503;
    return Response.json(
      { detail: error instanceof Error ? error.message : "MFA verification is unavailable" },
      { status },
    );
  }
}
