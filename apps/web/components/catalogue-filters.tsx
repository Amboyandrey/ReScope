"use client";

import { useEffect, useState } from "react";
import { type CatalogueFacets, type CatalogueFilters, getCatalogueFacets } from "@/lib/catalogue-client";

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

function Select({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string; count: number }[];
}) {
  if (options.length === 0) return null;
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium uppercase text-zinc-500">{label}</span>
      <select
        className="rounded-md border border-zinc-300 px-2 py-1.5"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label} ({o.count})
          </option>
        ))}
      </select>
    </label>
  );
}

export function CatalogueFilterRail({
  filters,
  onChange,
}: {
  filters: CatalogueFilters;
  onChange: (filters: CatalogueFilters) => void;
}) {
  const [facets, setFacets] = useState<CatalogueFacets | null>(null);

  useEffect(() => {
    getCatalogueFacets().then(setFacets);
  }, []);

  if (!facets) return null;

  function set<K extends keyof CatalogueFilters>(key: K, value: string) {
    onChange({ ...filters, [key]: value || undefined });
  }

  const hasActiveFilters = Object.values(filters).some(Boolean);

  return (
    <aside className="flex w-56 shrink-0 flex-col gap-4">
      <Select
        label="Country"
        value={filters.country ?? ""}
        onChange={(v) => set("country", v)}
        options={facets.countries.map((f) => ({ value: f.value, label: f.value, count: f.count }))}
      />
      <Select
        label="Company type"
        value={filters.company_type ?? ""}
        onChange={(v) => set("company_type", v)}
        options={facets.company_types.map((f) => ({
          value: f.value,
          label: COMPANY_TYPE_LABELS[f.value] ?? f.value,
          count: f.count,
        }))}
      />
      <Select
        label="Industry"
        value={filters.industry ?? ""}
        onChange={(v) => set("industry", v)}
        options={facets.industries.map((f) => ({ value: f.value, label: f.value, count: f.count }))}
      />
      <Select
        label="Competency"
        value={filters.competency_kind ?? ""}
        onChange={(v) => set("competency_kind", v)}
        options={facets.competency_kinds.map((f) => ({
          value: f.value,
          label: f.value.replace("_", " "),
          count: f.count,
        }))}
      />
      <Select
        label="Tag"
        value={filters.tag ?? ""}
        onChange={(v) => set("tag", v)}
        options={facets.tags.map((f) => ({ value: f.id, label: f.name, count: f.count }))}
      />
      {hasActiveFilters && (
        <button onClick={() => onChange({ q: filters.q })} className="text-left text-sm text-zinc-500 underline">
          Clear filters
        </button>
      )}
    </aside>
  );
}
