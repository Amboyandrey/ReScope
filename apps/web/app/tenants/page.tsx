"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getCurrentUser, tenantUrl } from "@/lib/auth-client";
import { listMyTenants, type MyTenant } from "@/lib/tenant-client";

// Root-domain page: every workspace the signed-in user belongs to, with a link into each one's
// own subdomain. Not reachable from inside a tenant — the proxy only rewrites to /t/[slug].
export default function TenantsPage() {
  const router = useRouter();
  const [tenants, setTenants] = useState<MyTenant[] | null>(null);

  useEffect(() => {
    (async () => {
      const user = await getCurrentUser();
      if (!user) {
        router.replace("/login");
        return;
      }
      setTenants(await listMyTenants());
    })();
  }, [router]);

  if (tenants === null) return null;

  return (
    <main className="mx-auto max-w-2xl px-6 py-16">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Your workspaces</h1>
        <Link href="/tenants/new" className="rounded-md bg-zinc-900 px-3 py-1.5 text-sm text-white">
          New workspace
        </Link>
      </div>
      {tenants.length === 0 ? (
        <p className="mt-6 text-zinc-600">You don&apos;t belong to a workspace yet.</p>
      ) : (
        <ul className="mt-6 flex flex-col gap-2">
          {tenants.map((t) => (
            <li key={t.id}>
              <a
                href={tenantUrl(t.slug)}
                className="flex items-center justify-between rounded-lg border border-zinc-200 bg-white px-4 py-3 hover:border-zinc-300"
              >
                <span className="font-medium">{t.name}</span>
                <span className="text-sm text-zinc-500">{t.role}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
