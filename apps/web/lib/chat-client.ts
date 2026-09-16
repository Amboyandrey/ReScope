import { AuthError, readCsrfCookie } from "./auth-client";
import type { CatalogueFilters } from "./catalogue-client";
import { API_URL, ROOT_DOMAIN } from "./config";
import { tenantSlugFromHost } from "./tenant";

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type Citation = { company_id: string; source_kind: string; source_id: string };

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  created_at: string;
};

function currentTenantSlug(): string {
  const slug = tenantSlugFromHost(window.location.host, ROOT_DOMAIN);
  if (!slug) throw new AuthError("Not viewing a workspace.");
  return slug;
}

function authHeaders(): Record<string, string> {
  const csrf = readCsrfCookie();
  return {
    "Content-Type": "application/json",
    ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    "X-Tenant-Slug": currentTenantSlug(),
  };
}

async function throwIfNotOk(res: Response): Promise<void> {
  if (res.ok) return;
  const body = (await res.json().catch(() => null)) as { detail?: string } | null;
  throw new AuthError(body?.detail ?? "Something went wrong.");
}

export async function listConversations(): Promise<Conversation[]> {
  const res = await fetch(`${API_URL}/api/v1/tenants/current/conversations`, {
    credentials: "include",
    headers: authHeaders(),
  });
  await throwIfNotOk(res);
  return (await res.json()) as Conversation[];
}

export async function createConversation(title: string): Promise<Conversation> {
  const res = await fetch(`${API_URL}/api/v1/tenants/current/conversations`, {
    method: "POST",
    credentials: "include",
    headers: authHeaders(),
    body: JSON.stringify({ title }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as Conversation;
}

export async function deleteConversation(id: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/v1/tenants/current/conversations/${id}`, {
    method: "DELETE",
    credentials: "include",
    headers: authHeaders(),
  });
  await throwIfNotOk(res);
}

export async function listMessages(conversationId: string): Promise<Message[]> {
  const res = await fetch(`${API_URL}/api/v1/tenants/current/conversations/${conversationId}/messages`, {
    credentials: "include",
    headers: authHeaders(),
  });
  await throwIfNotOk(res);
  return (await res.json()) as Message[];
}

/** Parses one SSE frame (`event: x\ndata: y`) — `event` defaults to "message" per the spec, the
 * same default the server's own unlabeled `data:` frames rely on. */
function parseFrame(frame: string): { event: string; data: string } {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  return { event, data: dataLines.join("\n") };
}

/** Streams one assistant reply, calling `onToken` per chunk of text and `onCitations` once the
 * reply is complete and persisted. Throws `AuthError` on an `event: error` frame (a resolved-key
 * failure, a down provider, …) — the caller decides how to show that inline. */
export async function sendMessage(
  conversationId: string,
  content: string,
  filters: CatalogueFilters,
  onToken: (text: string) => void,
  onCitations: (citations: Citation[]) => void,
): Promise<void> {
  const res = await fetch(`${API_URL}/api/v1/tenants/current/conversations/${conversationId}/messages`, {
    method: "POST",
    credentials: "include",
    headers: authHeaders(),
    body: JSON.stringify({
      content,
      country: filters.country,
      company_type: filters.company_type,
      industry: filters.industry,
      competency_kind: filters.competency_kind,
      tag: filters.tag,
    }),
  });
  await throwIfNotOk(res);
  if (!res.body) return;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      if (!frame.trim()) continue;
      const { event, data } = parseFrame(frame);
      if (event === "message") onToken(JSON.parse(data) as string);
      else if (event === "citations") onCitations(JSON.parse(data) as Citation[]);
      else if (event === "error") throw new AuthError(JSON.parse(data) as string);
    }
  }
}
