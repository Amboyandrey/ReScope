// Runtime configuration the browser bundle needs. Both values are baked in at build time via
// NEXT_PUBLIC_* — there's nothing secret here, only where the API is and what the root domain is.

/** The API origin the browser calls directly, e.g. `http://api.rescope.localhost:8000` — a
 * subdomain of the root, so the session cookie applies. Inlined into the client bundle. */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://api.rescope.localhost:8000";

/** Server-only address for the API — the container-network hostname inside Docker
 * (`http://api:8000`), plain `localhost` outside it. Never sent to the browser: reading it at
 * runtime (not `NEXT_PUBLIC_*`, so not build-time-inlined) is what lets one image serve both
 * a Docker Compose deployment and a bare `next start` without a rebuild. */
export const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/** The domain tenants are subdomains of. `acme.` + this is a tenant; this alone is the root site. */
export const ROOT_DOMAIN = process.env.NEXT_PUBLIC_ROOT_DOMAIN ?? "rescope.localhost";

/** Full origin of the root domain — where a non-member or signed-out visitor is sent back to. */
export const ROOT_URL = process.env.NEXT_PUBLIC_ROOT_URL ?? "http://rescope.localhost:3000";
