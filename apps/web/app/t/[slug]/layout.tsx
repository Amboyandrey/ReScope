import { redirect } from "next/navigation";
import { ROOT_URL } from "@/lib/config";
import { resolveTenant } from "@/lib/server-tenant";

// Everything under /t/[slug] is a tenant page — the proxy rewrites `slug.rescope.app/...` here
// and blocks direct access (see proxy.ts), so `slug` is always the host's own tenant. This layout
// is the actual membership check: a signed-out visitor or a non-member gets sent to the root
// domain rather than seeing so much as the tenant's name, matching the API's own 404-not-403 rule.
export default async function TenantLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const tenant = await resolveTenant(slug);
  if (!tenant) {
    redirect(`${ROOT_URL}/login`);
  }

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b border-zinc-200 bg-white px-6 py-3">
        <span className="font-semibold">{tenant.name}</span>
        <a
          href={ROOT_URL}
          className="text-sm text-zinc-500 hover:text-zinc-700"
        >
          Switch workspace
        </a>
      </header>
      {children}
    </div>
  );
}
