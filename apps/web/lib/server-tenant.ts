import "server-only";
import { cookies } from "next/headers";
import { API_INTERNAL_URL } from "./config";

/**
 * Resolve a tenant on the server, forwarding the incoming request's own cookies to the API.
 *
 * This runs inside the Next.js server handling `acme.rescope.app/...` directly — it's not a
 * cross-origin browser fetch, so there's no CORS/`credentials` concept here; the session cookie
 * just has to be copied onto the outgoing request by hand, which `fetch` never does on its own.
 */
export async function resolveTenant(slug: string): Promise<{ id: string; name: string } | null> {
  const cookieHeader = (await cookies()).toString();
  const res = await fetch(`${API_INTERNAL_URL}/api/v1/tenants/current`, {
    headers: { Cookie: cookieHeader, "X-Tenant-Slug": slug },
    cache: "no-store",
  });
  if (!res.ok) return null;
  return (await res.json()) as { id: string; name: string };
}
