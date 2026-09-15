import { apiFetch, AuthError } from "./auth-client";

export type TenantSummary = {
  id: string;
  slug: string;
  name: string;
  plan_id: string;
  plan_name: string;
  status: string;
  member_count: number;
  spend_this_month_usd: number;
  created_at: string;
};

export type Plan = {
  id: string;
  name: string;
  profiles_per_month: number;
  deep_runs_per_month: number;
  max_companies: number;
  max_members: number;
};

export type PlatformSettings = { scraping_paused: boolean; updated_at: string };

async function throwIfNotOk(res: Response): Promise<void> {
  if (res.ok) return;
  const body = (await res.json().catch(() => null)) as { detail?: string } | null;
  throw new AuthError(body?.detail ?? "Something went wrong.");
}

export async function listAllTenants(): Promise<TenantSummary[]> {
  const res = await apiFetch("/api/v1/admin/tenants");
  await throwIfNotOk(res);
  return (await res.json()) as TenantSummary[];
}

export async function listPlans(): Promise<Plan[]> {
  const res = await apiFetch("/api/v1/admin/plans");
  await throwIfNotOk(res);
  return (await res.json()) as Plan[];
}

export async function changeTenantPlan(tenantId: string, planId: string): Promise<TenantSummary> {
  const res = await apiFetch(`/api/v1/admin/tenants/${tenantId}/plan`, {
    method: "PATCH",
    body: JSON.stringify({ plan_id: planId }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as TenantSummary;
}

export async function getPlatformSettings(): Promise<PlatformSettings> {
  const res = await apiFetch("/api/v1/admin/settings");
  await throwIfNotOk(res);
  return (await res.json()) as PlatformSettings;
}

export async function setScrapingPaused(paused: boolean): Promise<PlatformSettings> {
  const res = await apiFetch("/api/v1/admin/settings", {
    method: "PATCH",
    body: JSON.stringify({ scraping_paused: paused }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as PlatformSettings;
}
