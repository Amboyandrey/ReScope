// Host → tenant resolution. Pure, so it can be unit-tested and shared by the proxy and the UI.

/** Characters a tenant slug may contain; anything else is treated as "not a tenant host". */
const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

/**
 * Extract the tenant slug from a request's Host header, or `null` when the host is the root
 * domain itself (or anything we don't recognise). Only a single label directly under the root
 * domain counts: `acme.rescope.app` is a tenant, `rescope.app` and `x.acme.rescope.app` are not.
 */
export function tenantSlugFromHost(host: string | null, rootDomain: string): string | null {
  if (!host) return null;
  const hostname = host.split(":")[0].toLowerCase();
  const root = rootDomain.toLowerCase();
  if (hostname === root || !hostname.endsWith(`.${root}`)) return null;
  const label = hostname.slice(0, -(root.length + 1));
  if (label === "www" || !SLUG_RE.test(label)) return null;
  return label;
}

/** Build the absolute origin for a tenant (or the root site when `slug` is null). */
export function originFor(slug: string | null, rootDomain: string, protocol: string, port: string): string {
  const hostname = slug ? `${slug}.${rootDomain}` : rootDomain;
  return `${protocol}//${hostname}${port ? `:${port}` : ""}`;
}
