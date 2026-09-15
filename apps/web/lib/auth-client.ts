import { API_URL, ROOT_DOMAIN } from "./config";

export type User = {
  id: string;
  email: string;
  display_name: string;
  is_superadmin: boolean;
  created_at: string;
};

export class AuthError extends Error {}

/** Reads the CSRF cookie the API sets alongside the session cookie — deliberately not httpOnly,
 * so the browser can echo it back as a header (the "double submit cookie" pattern). */
export function readCsrfCookie(): string | null {
  const match = document.cookie.match(/(?:^|; )rescope_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/** Every API call goes to the API's own subdomain with the domain-scoped session cookie attached. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const csrf = readCsrfCookie();
  return fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...init.headers,
    },
  });
}

/** Throws the API's own error message so callers can show it directly to the user. */
async function throwIfNotOk(res: Response): Promise<void> {
  if (res.ok) return;
  const body = (await res.json().catch(() => null)) as { detail?: string } | null;
  throw new AuthError(body?.detail ?? "Something went wrong.");
}

/** Creates an account and signs it in — the API sets the session and CSRF cookies. */
export async function signup(email: string, password: string, displayName: string): Promise<User> {
  const res = await apiFetch("/api/v1/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, display_name: displayName }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as User;
}

/** Authenticates and starts a session. */
export async function login(email: string, password: string): Promise<User> {
  const res = await apiFetch("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  await throwIfNotOk(res);
  return (await res.json()) as User;
}

/** Ends the current session. */
export async function logout(): Promise<void> {
  await apiFetch("/api/v1/auth/logout", { method: "POST" });
}

/** The signed-in user, or null if there's no valid session. */
export async function getCurrentUser(): Promise<User | null> {
  const res = await apiFetch("/api/v1/auth/me");
  if (res.status === 401) return null;
  await throwIfNotOk(res);
  return (await res.json()) as User;
}

/** Full URL for a tenant's own subdomain, in whatever protocol/port the browser is on. */
export function tenantUrl(slug: string): string {
  const { protocol, port } = window.location;
  return `${protocol}//${slug}.${ROOT_DOMAIN}${port ? `:${port}` : ""}`;
}
