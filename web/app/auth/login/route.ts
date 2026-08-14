import { NextResponse } from "next/server";

import {
  mutationOriginIsAllowed,
  rejectedLoginResponse,
  webAuthMode,
  webRedirect,
  webRequestUrl,
} from "../../../lib/identity-config";
import { createSupabaseServerClient } from "../../../lib/supabase-server";
import { resolveWebIdentity, WebIdentityError } from "../../../lib/web-identity";

export async function GET(request: Request) {
  return webRedirect(request, "/login");
}

export async function POST(request: Request) {
  if (!mutationOriginIsAllowed(request)) {
    return rejectedLoginResponse(request);
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
      return NextResponse.redirect(webRequestUrl(request, "/login?error=invalid"), 303);
    }
    try {
      await resolveWebIdentity();
    } catch (identityError) {
      if (identityError instanceof WebIdentityError && identityError.status === 428) {
        return NextResponse.redirect(webRequestUrl(request, "/mfa"), 303);
      }
      return NextResponse.redirect(webRequestUrl(request, "/login?error=binding"), 303);
    }
    return NextResponse.redirect(webRequestUrl(request, "/"), 303);
  } catch {
    return Response.json({ detail: "Web authentication is not configured" }, { status: 503 });
  }
}
