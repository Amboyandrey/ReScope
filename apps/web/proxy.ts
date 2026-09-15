import { NextResponse, type NextRequest } from "next/server";
import { ROOT_DOMAIN } from "@/lib/config";
import { tenantSlugFromHost } from "@/lib/tenant";

/** Header the proxy sets so server components can read which tenant a request belongs to. */
export const TENANT_HEADER = "x-tenant-slug";

/**
 * Route by hostname. A tenant subdomain (`acme.rescope.app/companies`) is rewritten to the
 * internal `/t/acme/companies` tree; the root domain serves everything else. The `/t/` tree is
 * never reachable by typing it into the root domain's URL bar — the tenant always comes from the
 * Host header, so a path can't claim a tenant the browser isn't actually on.
 */
export function proxy(request: NextRequest) {
  const slug = tenantSlugFromHost(request.headers.get("host"), ROOT_DOMAIN);
  const { pathname } = request.nextUrl;

  if (pathname === "/t" || pathname.startsWith("/t/")) {
    return new NextResponse(null, { status: 404 });
  }

  if (!slug) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = `/t/${slug}${pathname === "/" ? "" : pathname}`;
  const headers = new Headers(request.headers);
  headers.set(TENANT_HEADER, slug);
  return NextResponse.rewrite(url, { request: { headers } });
}

export const config = {
  // Everything except Next's own assets and static files in /public.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
