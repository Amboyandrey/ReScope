import { AuthError } from "./auth-client";
import type { CompanyDetail, CompanyType } from "./company-client";
import { API_URL, ROOT_DOMAIN } from "./config";
import { tenantSlugFromHost } from "./tenant";

export type CompetencyKind = "capability" | "technology" | "certification" | "industry_served" | "partnership";

export type FacetValue = { value: string; count: number };
export type CompanyTypeFacetValue = { value: CompanyType; count: number };
export type CompetencyKindFacetValue = { value: CompetencyKind; count: number };
export type TagFacetValue = { id: string; name: string; color: string; count: number };

export type CatalogueFacets = {
  countries: FacetValue[];
  company_types: CompanyTypeFacetValue[];
  industries: FacetValue[];
  competency_kinds: CompetencyKindFacetValue[];
  tags: TagFacetValue[];
};

export type CatalogueFilters = {
  country?: string;
  company_type?: CompanyType;
  industry?: string;
  competency_kind?: CompetencyKind;
  tag?: string;
  q?: string;
};

/** The current tenant's slug — same rule every tenant-scoped client module in this app follows. */
function currentTenantSlug(): string {
  const slug = tenantSlugFromHost(window.location.host, ROOT_DOMAIN);
  if (!slug) throw new AuthError("Not viewing a workspace.");
  return slug;
}

async function tenantFetch(path: string): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    credentials: "include",
    headers: { "X-Tenant-Slug": currentTenantSlug() },
  });
}

async function throwIfNotOk(res: Response): Promise<void> {
  if (res.ok) return;
  const body = (await res.json().catch(() => null)) as { detail?: string } | null;
  throw new AuthError(body?.detail ?? "Something went wrong.");
}

export async function listCatalogue(filters: CatalogueFilters): Promise<CompanyDetail[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const qs = params.toString();
  const res = await tenantFetch(`/api/v1/tenants/current/catalogue${qs ? `?${qs}` : ""}`);
  await throwIfNotOk(res);
  return (await res.json()) as CompanyDetail[];
}

export async function getCatalogueFacets(): Promise<CatalogueFacets> {
  const res = await tenantFetch("/api/v1/tenants/current/catalogue/facets");
  await throwIfNotOk(res);
  return (await res.json()) as CatalogueFacets;
}
