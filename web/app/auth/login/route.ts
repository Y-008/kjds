import { NextResponse } from "next/server";

import { mutationOriginIsAllowed, webAuthMode } from "../../../lib/identity-config";
import { createSupabaseServerClient } from "../../../lib/supabase-server";
import { resolveWebIdentity, WebIdentityError } from "../../../lib/web-identity";

export async function POST(request: Request) {
  if (!mutationOriginIsAllowed(request)) {
    return Response.json({ detail: "Cross-site or originless login is not allowed" }, { status: 403 });
  }
  try {
    if (webAuthMode() !== "supabase") {
      return Response.json({ detail: "Interactive login is not enabled" }, { status: 409 });
    }
    const form = await request.formData();
    const email = String(form.get("email") ?? "").trim();
    const password = String(form.get("password") ?? "");
    if (!email || !password) {
      return Response.json({ detail: "Email and password are required" }, { status: 400 });
    }
    const supabase = await createSupabaseServerClient();
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      return NextResponse.redirect(new URL("/login?error=invalid", request.url), 303);
    }
    try {
      await resolveWebIdentity();
    } catch (identityError) {
      if (identityError instanceof WebIdentityError && identityError.status === 428) {
        return NextResponse.redirect(new URL("/mfa", request.url), 303);
      }
      return NextResponse.redirect(new URL("/login?error=binding", request.url), 303);
    }
    return NextResponse.redirect(new URL("/", request.url), 303);
  } catch {
    return Response.json({ detail: "Web authentication is not configured" }, { status: 503 });
  }
}
