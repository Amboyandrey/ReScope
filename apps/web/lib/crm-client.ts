import { AuthError, readCsrfCookie } from "./auth-client";
import { API_URL, ROOT_DOMAIN } from "./config";
import { tenantSlugFromHost } from "./tenant";

export type Contact = {
  id: string;
  company_id: string;
  first_name: string;
  last_name: string;
  email: string | null;
  title: string | null;
  phone: string | null;
  linkedin_url: string | null;
  source: string;
  created_at: string;
  updated_at: string;
};

export type Note = {
  id: string;
  company_id: string;
  author_id: string;
  body: string;
  created_at: string;
};

export type Tag = { id: string; name: string; color: string };

export type SavedSearch = { id: string; name: string; q: string; created_at: string };

export type ImportResult = {
  id: string;
  kind: string;
  status: string;
  row_count: number;
  error_count: number;
  errors: string[];
  created_at: string;
};

export type ProfileChange = {
  id: string;
  job_id: string;
  diff: Record<string, unknown>;
  created_at: string;
};

/** The current tenant's slug, read from wherever the browser actually is — same rule every
 * tenant-scoped client module in this app follows (see lib/company-client.ts). */
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

// --- Contacts ---------------------------------------------------------------

export async function listContacts(companyId: string): Promise<Contact[]> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/contacts`);
  await throwIfNotOk(res);
  return (await res.json()) as Contact[];
}

export type ContactFields = {
  first_name: string;
  last_name: string;
  email?: string;
  title?: string;
  phone?: string;
  linkedin_url?: string;
};

export async function createContact(companyId: string, fields: ContactFields): Promise<Contact> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/contacts`, {
    method: "POST",
    body: JSON.stringify(fields),
  });
  await throwIfNotOk(res);
  return (await res.json()) as Contact;
}

export async function updateContact(
  companyId: string,
  contactId: string,
  fields: Partial<ContactFields>,
): Promise<Contact> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/contacts/${contactId}`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
  await throwIfNotOk(res);
  return (await res.json()) as Contact;
}

export async function deleteContact(companyId: string, contactId: string): Promise<void> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/contacts/${contactId}`, {
    method: "DELETE",
  });
  await throwIfNotOk(res);
}

export async function importContactsCsv(companyId: string, file: File): Promise<ImportResult> {
  const csrf = readCsrfCookie();
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(`${API_URL}/api/v1/tenants/current/companies/${companyId}/contacts/import`, {
    method: "POST",
    credentials: "include",
    headers: {
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      "X-Tenant-Slug": currentTenantSlug(),
    },
    body,
  });
  await throwIfNotOk(res);
  return (await res.json()) as ImportResult;
}

// --- Notes -------------------------------------------------------------------

export async function listNotes(companyId: string): Promise<Note[]> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/notes`);
  await throwIfNotOk(res);
  return (await res.json()) as Note[];
}

export async function createNote(companyId: string, body: string): Promise<Note> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/notes`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as Note;
}

export async function deleteNote(companyId: string, noteId: string): Promise<void> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/notes/${noteId}`, {
    method: "DELETE",
  });
  await throwIfNotOk(res);
}

// --- Tags ----------------------------------------------------------------------

export async function listTags(): Promise<Tag[]> {
  const res = await tenantFetch("/api/v1/tenants/current/tags");
  await throwIfNotOk(res);
  return (await res.json()) as Tag[];
}

export async function createTag(name: string, color?: string): Promise<Tag> {
  const res = await tenantFetch("/api/v1/tenants/current/tags", {
    method: "POST",
    body: JSON.stringify(color ? { name, color } : { name }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as Tag;
}

export async function deleteTag(tagId: string): Promise<void> {
  const res = await tenantFetch(`/api/v1/tenants/current/tags/${tagId}`, { method: "DELETE" });
  await throwIfNotOk(res);
}

export async function listCompanyTags(companyId: string): Promise<Tag[]> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/tags`);
  await throwIfNotOk(res);
  return (await res.json()) as Tag[];
}

export async function attachTag(companyId: string, tagId: string): Promise<void> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/tags/${tagId}`, {
    method: "PUT",
  });
  await throwIfNotOk(res);
}

export async function detachTag(companyId: string, tagId: string): Promise<void> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/tags/${tagId}`, {
    method: "DELETE",
  });
  await throwIfNotOk(res);
}

// --- Saved searches --------------------------------------------------------------

export async function listSavedSearches(): Promise<SavedSearch[]> {
  const res = await tenantFetch("/api/v1/tenants/current/saved-searches");
  await throwIfNotOk(res);
  return (await res.json()) as SavedSearch[];
}

export async function createSavedSearch(name: string, q: string): Promise<SavedSearch> {
  const res = await tenantFetch("/api/v1/tenants/current/saved-searches", {
    method: "POST",
    body: JSON.stringify({ name, q }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as SavedSearch;
}

export async function deleteSavedSearch(id: string): Promise<void> {
  const res = await tenantFetch(`/api/v1/tenants/current/saved-searches/${id}`, { method: "DELETE" });
  await throwIfNotOk(res);
}

// --- Profile changes --------------------------------------------------------------

export async function listProfileChanges(companyId: string): Promise<ProfileChange[]> {
  const res = await tenantFetch(`/api/v1/tenants/current/companies/${companyId}/changes`);
  await throwIfNotOk(res);
  return (await res.json()) as ProfileChange[];
}
