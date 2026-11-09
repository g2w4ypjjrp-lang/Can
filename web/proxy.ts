import { NextResponse, type NextRequest } from "next/server";

import { runtimeConfig } from "@/lib/config";
import { buildCsp, newNonce, originOf } from "@/lib/csp";

// Her sayfa isteğinde yeni nonce'lu CSP. Next.js nonce'u istek başlığındaki CSP'den okuyup
// kendi betiklerine ekler (sayfalar bu yüzden dinamik oluşturulur: app/layout.tsx).
/** Yönetim paneli ayrı alan adında: orada yalnızca /yonetim, herkese açık sitede /yonetim yok. */
export function adminRouting(request: NextRequest, adminHost: string | null): NextResponse | null {
  if (!adminHost) return null;
  const host = (request.headers.get("host") ?? "").split(":")[0]?.toLowerCase();
  const path = request.nextUrl.pathname;
  const isAdminPath = path === "/yonetim" || path.startsWith("/yonetim/");
  if (host === adminHost && !isAdminPath) {
    return NextResponse.redirect(new URL("/yonetim", request.url));
  }
  if (host !== adminHost && isAdminPath) {
    return NextResponse.rewrite(new URL("/__yok", request.url), { status: 404 });
  }
  return null;
}

export function proxy(request: NextRequest) {
  const cfg = runtimeConfig();
  const routed = adminRouting(request, cfg.adminHost);
  if (routed) return routed;
  const nonce = newNonce();
  const csp = buildCsp({
    nonce,
    apiOrigin: originOf(cfg.publicApiUrl),
    dev: process.env.NODE_ENV === "development",
    https: cfg.siteUrl.startsWith("https://"),
  });
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);
  if (request.nextUrl.pathname.startsWith("/yonetim")) {
    response.headers.set("X-Robots-Tag", "noindex, nofollow");
    response.headers.set("Cache-Control", "no-store");
  }
  if (cfg.production) {
    response.headers.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload");
  }
  return response;
}

export const config = {
  matcher: [
    {
      source: "/((?!_next/static|_next/image|favicon.ico|icon.svg|robots.txt|sitemap.xml).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
