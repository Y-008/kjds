import { NextResponse } from "next/server";

import { mutationOriginIsAllowed, webAuthMode } from "../../../lib/identity-config";
import { createSupabaseServerClient } from "../../../lib/supabase-server";

export async function POST(request: Request) {
  if (!mutationOriginIsAllowed(request)) {
    return Response.json({ detail: "Cross-site or originless logout is not allowed" }, { status: 403 });
  }
  try {
    if (webAuthMode() === "supabase") {
      const supabase = await createSupabaseServerClient();
      await supabase.auth.signOut({ scope: "global" });
    }
    return NextResponse.redirect(new URL("/login", request.url), 303);
  } catch {
    return Response.json({ detail: "Web authentication is unavailable" }, { status: 503 });
  }
}
