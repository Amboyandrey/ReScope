import { AuthError, readCsrfCookie } from "./auth-client";
import { API_URL, ROOT_DOMAIN } from "./config";
import { tenantSlugFromHost } from "./tenant";

export type Provider = "anthropic" | "browser_use";

export type Credential = {
  id: string;
  provider: Provider;
  last4: string;
  validated_at: string;
  created_at: string;
};

/** The current tenant's slug — same rule every tenant-scoped client module in this app follows. */
function currentTenantSlug(): string {
  const slug = tenantSlugFromHost(window.location.host, ROOT_DOMAIN);
  if (!slug) throw new AuthError("Not viewing a workspace.");
  return slug;
}

async function tenantFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const csrf = readCsrfCookie();
  return fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      "X-Tenant-Slug": currentTenantSlug(),
      ...init.headers,
    },
  });
}

async function throwIfNotOk(res: Response): Promise<void> {
  if (res.ok) return;
  const body = (await res.json().catch(() => null)) as { detail?: string } | null;
  throw new AuthError(body?.detail ?? "Something went wrong.");
}

export async function listCredentials(): Promise<Credential[]> {
  const res = await tenantFetch("/api/v1/tenants/current/credentials");
  await throwIfNotOk(res);
  return (await res.json()) as Credential[];
}

export async function setCredential(provider: Provider, apiKey: string): Promise<Credential> {
  const res = await tenantFetch("/api/v1/tenants/current/credentials", {
    method: "PUT",
    body: JSON.stringify({ provider, api_key: apiKey }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as Credential;
}

export async function deleteCredential(provider: Provider): Promise<void> {
  const res = await tenantFetch(`/api/v1/tenants/current/credentials/${provider}`, { method: "DELETE" });
  await throwIfNotOk(res);
}
