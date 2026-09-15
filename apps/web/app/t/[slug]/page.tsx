"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { FormError } from "@/components/form-error";
import { StatusBadge } from "@/components/status-badge";
import { AuthError } from "@/lib/auth-client";
import { type Company, createCompany, listCompanies } from "@/lib/company-client";

// A company mid-scrape polls its own row rather than the whole list re-fetching on a timer —
// keeps this page cheap even with a long list, and each row stops polling once it settles.
function useLiveCompany(initial: Company): Company {
  const [company, setCompany] = useState(initial);
  useEffect(() => {
    if (company.profile_status !== "pending" && company.profile_status !== "scraping") return;
    const id = setInterval(async () => {
      const fresh = await listCompanies();
      const match = fresh.find((c) => c.id === company.id);
      if (match) setCompany(match);
    }, 3000);
    return () => clearInterval(id);
  }, [company.id, company.profile_status]);
  return company;
}

function CompanyRow({ company: initial }: { company: Company }) {
  const company = useLiveCompany(initial);
  return (
    <Link
      href={`/companies/${company.id}`}
      className="flex items-center justify-between rounded-lg border border-zinc-200 bg-white px-4 py-3 hover:border-zinc-300"
    >
      <div>
        <div className="font-medium">{company.name}</div>
        <div className="text-sm text-zinc-500">{company.domain}</div>
      </div>
      <StatusBadge status={company.profile_status} />
    </Link>
  );
}

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [domain, setDomain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const refresh = useCallback(async () => {
    setCompanies(await listCompanies());
  }, []);

  // A `.then()` chain, not `refresh()` called directly: the mount fetch is one-shot and doesn't
  // need `refresh`'s identity, and this shape is what react-hooks' set-state-in-effect rule
  // recognises as "subscribing to an external system" rather than an effect setting state itself.
  useEffect(() => {
    listCompanies().then(setCompanies);
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      await createCompany(domain);
      setDomain("");
      await refresh();
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Something went wrong.");
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold">Companies</h1>
      <p className="mt-1 text-zinc-600">
        Add a company by its website. We&apos;ll read it and pull out its products, services and
        competencies.
      </p>

      <form onSubmit={onSubmit} className="mt-6 flex gap-2">
        <input
          className="flex-1 rounded-md border border-zinc-300 px-3 py-2"
          placeholder="acme.com or https://acme.com"
          value={domain}
          onChange={(e) => setDomain(e.target.value)}
          required
        />
        <button
          type="submit"
          disabled={pending}
          className="rounded-md bg-zinc-900 px-4 py-2 text-white disabled:opacity-50"
        >
          {pending ? "Adding…" : "Add"}
        </button>
      </form>
      <FormError message={error} />

      {companies === null ? null : companies.length === 0 ? (
        <p className="mt-8 text-zinc-500">No companies yet — add one above to get started.</p>
      ) : (
        <ul className="mt-8 flex flex-col gap-2">
          {companies.map((c) => (
            <li key={c.id}>
              <CompanyRow company={c} />
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
