import { AuthError, readCsrfCookie } from "./auth-client";
import { API_URL, ROOT_DOMAIN } from "./config";
import { tenantSlugFromHost } from "./tenant";
import type { ChatProvider, ScrapeProvider } from "./tenant-client";

export type Provider = "anthropic" | "browser_use" | "openai" | "gemini" | "nebius" | "custom";
export type { ChatProvider };

export type Credential = {
  id: string;
  provider: Provider;
  base_url: string | null;
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

export async function setCredential(
  provider: Provider,
  apiKey: string,
  baseUrl?: string,
): Promise<Credential> {
  const res = await tenantFetch("/api/v1/tenants/current/credentials", {
    method: "PUT",
    body: JSON.stringify({ provider, api_key: apiKey, base_url: baseUrl ?? null }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as Credential;
}

export async function deleteCredential(provider: Provider): Promise<void> {
  const res = await tenantFetch(`/api/v1/tenants/current/credentials/${provider}`, { method: "DELETE" });
  await throwIfNotOk(res);
}

export async function getCurrentTenantSettings(): Promise<{
  scrape_provider: ScrapeProvider;
  chat_provider: ChatProvider;
  chat_model: string;
}> {
  const res = await tenantFetch("/api/v1/tenants/current");
  await throwIfNotOk(res);
  return (await res.json()) as { scrape_provider: ScrapeProvider; chat_provider: ChatProvider; chat_model: string };
}

export async function setScrapeProvider(provider: ScrapeProvider): Promise<void> {
  const res = await tenantFetch("/api/v1/tenants/current/scrape-provider", {
    method: "PUT",
    body: JSON.stringify({ provider }),
  });
  await throwIfNotOk(res);
}

export async function setChatModel(provider: ChatProvider, model: string): Promise<void> {
  const res = await tenantFetch("/api/v1/tenants/current/chat-model", {
    method: "PUT",
    body: JSON.stringify({ provider, model }),
  });
  await throwIfNotOk(res);
}

/** The chat-capable model ids `provider` reports for the workspace's key — an affordance for a
 * dropdown, not a gate; throws (with the provider's own message) when the list can't be loaded,
 * which the caller treats as "fall back to typing a model id manually", never as a broken page. */
export async function getAvailableModels(provider: ChatProvider): Promise<string[]> {
  const res = await tenantFetch(
    `/api/v1/tenants/current/chat-model/available-models?provider=${provider}`,
  );
  await throwIfNotOk(res);
  return ((await res.json()) as { models: string[] }).models;
}
