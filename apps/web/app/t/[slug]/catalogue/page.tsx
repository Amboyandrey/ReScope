"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { CatalogueFilterRail } from "@/components/catalogue-filters";
import { type CatalogueFilters, listCatalogue } from "@/lib/catalogue-client";
import type { CompanyDetail } from "@/lib/company-client";

const COMPANY_TYPE_LABELS: Record<string, string> = {
  manufacturer: "Manufacturer",
  distributor: "Distributor",
  service_provider: "Service provider",
  software: "Software",
  consultancy: "Consultancy",
  agency: "Agency",
  research: "Research",
  other: "Other",
};

function factsLine(company: CompanyDetail): string {
  const parts: string[] = [];
  if (company.company_type) parts.push(COMPANY_TYPE_LABELS[company.company_type] ?? company.company_type);
  const place = [company.hq_city, company.hq_country].filter(Boolean).join(", ");
  if (place) parts.push(place);
  if (company.industry) parts.push(company.industry);
  return parts.join(" · ");
}

function CompanyCard({ company }: { company: CompanyDetail }) {
  const line = factsLine(company);
  return (
    <Link
      href={`/companies/${company.id}`}
      className="flex flex-col gap-2 rounded-lg border border-zinc-200 bg-white p-4 hover:border-zinc-300"
    >
      <div>
        <div className="font-medium">{company.name}</div>
        {line && <div className="text-sm text-zinc-500">{line}</div>}
      </div>
      {company.overview && <p className="line-clamp-2 text-sm text-zinc-600">{company.overview}</p>}

      {company.offerings.length > 0 && (
        <ul className="flex flex-col gap-1">
          {company.offerings.slice(0, 3).map((o) => (
            <li key={o.id} className="text-xs text-zinc-600">
              <span className="font-medium">{o.name}</span>
              {o.description && <span> — {o.description}</span>}
            </li>
          ))}
        </ul>
      )}
      {company.competencies.length > 0 && (
        <ul className="flex flex-wrap gap-1">
          {company.competencies.slice(0, 3).map((c) => (
            <li
              key={c.id}
              className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-600"
              title={c.description}
            >
              {c.name}
            </li>
          ))}
        </ul>
      )}
    </Link>
  );
}

export default function CataloguePage() {
  const [filters, setFilters] = useState<CatalogueFilters>({});
  const [query, setQuery] = useState("");
  const [companies, setCompanies] = useState<CompanyDetail[] | null>(null);

  useEffect(() => {
    listCatalogue(filters).then(setCompanies);
  }, [filters]);

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <h1 className="text-2xl font-semibold">Catalogue</h1>
      <p className="mt-1 text-zinc-600">
        Every company you track, filterable by fact and searchable by what it does.
      </p>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          setFilters((prev) => ({ ...prev, q: query || undefined }));
        }}
        className="mt-6 flex gap-2"
      >
        <input
          className="flex-1 rounded-md border border-zinc-300 px-3 py-2"
          placeholder="Search products, services, competencies…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" className="rounded-md border border-zinc-300 px-4 py-2">
          Search
        </button>
      </form>

      <div className="mt-6 flex gap-8">
        <CatalogueFilterRail filters={filters} onChange={setFilters} />

        <div className="flex-1">
          {companies === null ? null : companies.length === 0 ? (
            <p className="text-zinc-500">No companies match these filters.</p>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {companies.map((c) => (
                <CompanyCard key={c.id} company={c} />
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
