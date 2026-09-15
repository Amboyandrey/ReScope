import { apiFetch, AuthError } from "./auth-client";
import type { Role } from "./types";

export type Tenant = {
  id: string;
  slug: string;
  name: string;
  plan_id: string;
  created_at: string;
};

export type MyTenant = Tenant & { role: Role };

/** Every request to a tenant-scoped route needs this header — the API resolves it against the
 * caller's own membership; a slug for a tenant the caller doesn't belong to 404s. */
function tenantHeaders(slug: string): Record<string, string> {
  return { "X-Tenant-Slug": slug };
}

/** Create a tenant and become its owner. `slug` is derived from `name` when omitted. */
export async function createTenant(name: string, slug?: string): Promise<Tenant> {
  const res = await apiFetch("/api/v1/tenants", { method: "POST", body: JSON.stringify({ name, slug }) });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new AuthError(body?.detail ?? "Could not create the workspace.");
  }
  return (await res.json()) as Tenant;
}

/** List every tenant the signed-in user belongs to. */
export async function listMyTenants(): Promise<MyTenant[]> {
  const res = await apiFetch("/api/v1/tenants");
  if (!res.ok) return [];
  return (await res.json()) as MyTenant[];
}

/** Resolve the tenant named by `slug`, or null if the caller isn't a member (or it doesn't exist). */
export async function getCurrentTenant(slug: string): Promise<Tenant | null> {
  const res = await apiFetch("/api/v1/tenants/current", { headers: tenantHeaders(slug) });
  if (res.status === 404) return null;
  if (!res.ok) return null;
  return (await res.json()) as Tenant;
}
