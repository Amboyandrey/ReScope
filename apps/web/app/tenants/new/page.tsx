"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FormError } from "@/components/form-error";
import { AuthError, getCurrentUser, tenantUrl } from "@/lib/auth-client";
import { createTenant } from "@/lib/tenant-client";

export default function NewTenantPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    (async () => {
      if (!(await getCurrentUser())) router.replace("/login");
    })();
  }, [router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      const tenant = await createTenant(name);
      window.location.href = tenantUrl(tenant.slug);
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Something went wrong.");
      setPending(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center px-6">
      <h1 className="text-xl font-semibold">Name your workspace</h1>
      <p className="mt-1 text-sm text-zinc-600">This becomes your workspace&apos;s own address.</p>
      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4">
        <label className="flex flex-col gap-1 text-sm">
          Workspace name
          <input
            className="rounded-md border border-zinc-300 px-3 py-2"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Inc"
            required
          />
        </label>
        <FormError message={error} />
        <button
          type="submit"
          disabled={pending}
          className="rounded-md bg-zinc-900 px-3 py-2 text-white disabled:opacity-50"
        >
          {pending ? "Creating…" : "Create workspace"}
        </button>
      </form>
    </main>
  );
}
