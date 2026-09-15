"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { FormError } from "@/components/form-error";
import { StatusBadge } from "@/components/status-badge";
import { AuthError } from "@/lib/auth-client";
import { type Company, type SearchHit, createCompany, listCompanies, searchCompanies } from "@/lib/company-client";

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

function SearchResultRow({ hit }: { hit: SearchHit }) {
  return (
    <Link
      href={`/companies/${hit.company.id}`}
      className="flex flex-col gap-1 rounded-lg border border-zinc-200 bg-white px-4 py-3 hover:border-zinc-300"
    >
      <div className="flex items-center justify-between">
        <span className="font-medium">{hit.company.name}</span>
        <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs uppercase text-zinc-500">
          {hit.source_kind.replace("_", " ")}
        </span>
      </div>
      <p className="text-sm text-zinc-600">{hit.content}</p>
    </Link>
  );
}

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [domain, setDomain] = useState("");
  const [deepMode, setDeepMode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchHit[] | null>(null);
  const [searching, setSearching] = useState(false);

  const refresh = useCallback(async () => {
    setCompanies(await listCompanies());
  }, []);

  // A `.then()` chain, not `refresh()` called directly: the mount fetch is one-shot and doesn't
  // need `refresh`'s identity, and this shape is what react-hooks' set-state-in-effect rule
  // recognises as "subscribing to an external system" rather than an effect setting state itself.
  useEffect(() => {
    listCompanies().then(setCompanies);
  }, []);

  async function onAddSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      await createCompany(domain, deepMode ? "deep" : "fast");
      setDomain("");
      setDeepMode(false);
      await refresh();
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Something went wrong.");
    } finally {
      setPending(false);
    }
  }

  async function onSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) {
      setResults(null);
      return;
    }
    setSearching(true);
    try {
      setResults(await searchCompanies(query));
    } finally {
      setSearching(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <h1 className="text-2xl font-semibold">Companies</h1>
      <p className="mt-1 text-zinc-600">
        Add a company by its website. We&apos;ll read it and pull out its products, services and
        competencies.
      </p>

      <form onSubmit={onAddSubmit} className="mt-6 flex flex-col gap-2">
        <div className="flex gap-2">
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
        </div>
        <label className="flex items-center gap-2 text-sm text-zinc-600">
          <input type="checkbox" checked={deepMode} onChange={(e) => setDeepMode(e.target.checked)} />
          Deep scan — also visually explores tabs, menus, and hidden sections (slower, costs more,
          counts against a separate monthly quota)
        </label>
      </form>
      <FormError message={error} />

      <form onSubmit={onSearchSubmit} className="mt-8 flex gap-2">
        <input
          className="flex-1 rounded-md border border-zinc-300 px-3 py-2"
          placeholder="Search across every company's products, services and competencies…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!e.target.value.trim()) setResults(null);
          }}
        />
        <button
          type="submit"
          disabled={searching}
          className="rounded-md border border-zinc-300 px-4 py-2 disabled:opacity-50"
        >
          {searching ? "Searching…" : "Search"}
        </button>
      </form>

      {results !== null ? (
        <>
          <p className="mt-6 text-sm text-zinc-500">
            {results.length === 0 ? "No matches." : `${results.length} match${results.length === 1 ? "" : "es"}`}
          </p>
          <ul className="mt-3 flex flex-col gap-2">
            {results.map((hit, i) => (
              <li key={`${hit.company.id}-${i}`}>
                <SearchResultRow hit={hit} />
              </li>
            ))}
          </ul>
        </>
      ) : companies === null ? null : companies.length === 0 ? (
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
