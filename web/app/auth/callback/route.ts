import { NextResponse } from "next/server";

import { webAuthMode } from "../../../lib/identity-config";
import { createSupabaseServerClient } from "../../../lib/supabase-server";

export async function GET(request: Request) {
  try {
    if (webAuthMode() !== "supabase") {
      return Response.json({ detail: "Interactive login is not enabled" }, { status: 409 });
    }
    const url = new URL(request.url);
    const code = url.searchParams.get("code");
    if (!code) return Response.json({ detail: "Authentication code is required" }, { status: 400 });
    const supabase = await createSupabaseServerClient();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (error) return NextResponse.redirect(new URL("/login?error=callback", request.url), 303);
    return NextResponse.redirect(new URL("/", request.url), 303);
  } catch {
    return Response.json({ detail: "Web authentication is not configured" }, { status: 503 });
  }
}
