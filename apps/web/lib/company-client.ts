import { apiFetch, AuthError } from "./auth-client";
import { ROOT_DOMAIN } from "./config";
import { tenantSlugFromHost } from "./tenant";

export type Company = {
  id: string;
  domain: string;
  name: string;
  website_url: string;
  industry: string | null;
  hq_country: string | null;
  hq_city: string | null;
  employee_range: string | null;
  founded_year: number | null;
  socials: Record<string, string>;
  logo_url: string | null;
  overview: string | null;
  profile_status: "pending" | "scraping" | "done" | "failed";
  last_profiled_at: string | null;
  created_at: string;
};

export type Evidence = { url: string; quote: string };

export type Offering = {
  id: string;
  kind: "product" | "service";
  name: string;
  description: string | null;
  category: string | null;
  url: string | null;
  evidence: Evidence[];
};

export type Competency = {
  id: string;
  kind: "capability" | "technology" | "certification" | "industry_served" | "partnership";
  name: string;
  description: string | null;
  evidence: Evidence[];
};

export type CompanyDetail = Company & { offerings: Offering[]; competencies: Competency[] };

export type ScrapeJob = {
  id: string;
  mode: "fast" | "deep";
  status: "queued" | "running" | "done" | "failed";
  tier_reached: number;
  pages_fetched: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  error: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
};

/** The current tenant's slug, read from wherever the browser actually is. Every call below needs
 * it as the `X-Tenant-Slug` header the API resolves membership from. */
function currentTenantSlug(): string {
  const slug = tenantSlugFromHost(window.location.host, ROOT_DOMAIN);
  if (!slug) throw new AuthError("Not viewing a workspace.");
  return slug;
}

async function tenantFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return apiFetch(path, { ...init, headers: { "X-Tenant-Slug": currentTenantSlug(), ...init.headers } });
}

async function throwIfNotOk(res: Response): Promise<void> {
  if (res.ok) return;
  const body = (await res.json().catch(() => null)) as { detail?: string } | null;
  throw new AuthError(body?.detail ?? "Something went wrong.");
}

export async function listCompanies(): Promise<Company[]> {
  const res = await tenantFetch("/api/v1/tenants/current/companies");
  await throwIfNotOk(res);
  return (await res.json()) as Company[];
}

export async function createCompany(domain: string): Promise<Company> {
  const res = await tenantFetch("/api/v1/tenants/current/companies", {
    method: "POST",
    body: JSON.stringify({ domain }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as Company;
}

export async function getCompany(companyId: string): Promise<CompanyDetail> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}`);
  await throwIfNotOk(res);
  return (await res.json()) as CompanyDetail;
}

export async function deleteCompany(companyId: string): Promise<void> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}`, { method: "DELETE" });
  await throwIfNotOk(res);
}

export async function listScrapeJobs(companyId: string): Promise<ScrapeJob[]> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/scrape-jobs`);
  await throwIfNotOk(res);
  return (await res.json()) as ScrapeJob[];
}

export type SearchHit = {
  company: Company;
  source_kind: string;
  content: string;
  distance: number;
};

export type SimilarCompany = { company: Company; distance: number };

export async function searchCompanies(query: string): Promise<SearchHit[]> {
  const res = await tenantFetch(`/api/v1/tenants/current/search?${new URLSearchParams({ q: query })}`);
  await throwIfNotOk(res);
  return (await res.json()) as SearchHit[];
}

export async function getSimilarCompanies(companyId: string): Promise<SimilarCompany[]> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/similar`);
  await throwIfNotOk(res);
  return (await res.json()) as SimilarCompany[];
}
