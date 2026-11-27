import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { isConfigured, SUPABASE_ANON_KEY, SUPABASE_URL } from "./lib/env";

// Oturum çerezini yeniler; oturum yoksa korumalı sayfalardan /login'e yönlendirir.
export async function proxy(req: NextRequest) {
  let res = NextResponse.next({ request: req });
  if (!isConfigured()) return res;
  const sb = createServerClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    cookies: {
      getAll: () => req.cookies.getAll(),
      setAll: (list) => {
        list.forEach(({ name, value }) => req.cookies.set(name, value));
        res = NextResponse.next({ request: req });
        list.forEach(({ name, value, options }) => res.cookies.set(name, value, options));
      },
    },
  });
  const { data: { user } } = await sb.auth.getUser();
  if (!user && !req.nextUrl.pathname.startsWith("/login")) {
    return NextResponse.redirect(new URL("/login", req.url));
  }
  return res;
}

export const config = { matcher: ["/((?!_next/|favicon.ico).*)"] };
