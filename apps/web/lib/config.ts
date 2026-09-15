// Runtime configuration the browser bundle needs. Both values are baked in at build time via
// NEXT_PUBLIC_* — there's nothing secret here, only where the API is and what the root domain is.

/** The API origin the browser calls directly, e.g. `http://api.rescope.localhost:8000`. */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://api.rescope.localhost:8000";

/** The domain tenants are subdomains of. `acme.` + this is a tenant; this alone is the root site. */
export const ROOT_DOMAIN = process.env.NEXT_PUBLIC_ROOT_DOMAIN ?? "rescope.localhost";
