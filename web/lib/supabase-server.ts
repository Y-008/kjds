import "server-only";

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for Supabase Web authentication`);
  return value;
}

export async function createSupabaseServerClient() {
  const cookieStore = await cookies();
  return createServerClient(required("NEXT_PUBLIC_SUPABASE_URL"), required("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"), {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value, options }) => cookieStore.set(name, value, options));
      },
    },
  });
}
