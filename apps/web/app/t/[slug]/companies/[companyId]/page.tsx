"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ChangesSection } from "@/components/changes-section";
import { ContactsSection } from "@/components/contacts-section";
import { EvidenceList } from "@/components/evidence-list";
import { NotesSection } from "@/components/notes-section";
import { StatusBadge } from "@/components/status-badge";
import { TagsSection } from "@/components/tags-section";
import {
  type CompanyDetail,
  type ScrapeJob,
  type SimilarCompany,
  deleteCompany,
  getCompany,
  getSimilarCompanies,
  listScrapeJobs,
  reprofileCompany,
} from "@/lib/company-client";

const ACTIVE_STATUSES = new Set(["pending", "scraping"]);

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

function CompanyFacts({ company }: { company: CompanyDetail }) {
  const place = [company.hq_city, company.hq_country].filter(Boolean).join(", ");
  const facts: [string, string][] = [];
  if (company.company_type) facts.push(["Type", COMPANY_TYPE_LABELS[company.company_type] ?? company.company_type]);
  if (place) facts.push(["Location", place]);
  if (company.industry) facts.push(["Industry", company.industry]);
  if (company.employee_range) facts.push(["Employees", company.employee_range]);
  if (company.founded_year) facts.push(["Founded", String(company.founded_year)]);
  if (Object.keys(company.socials).length > 0) {
    facts.push(["Socials", Object.keys(company.socials).join(", ")]);
  }
  if (facts.length === 0) return null;

  return (
    <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
      {facts.map(([label, value]) => (
        <div key={label}>
          <dt className="text-xs text-zinc-400">{label}</dt>
          <dd className="text-zinc-700">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function CompanyProfilePage() {
  const router = useRouter();
  const { companyId } = useParams<{ companyId: string }>();
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [jobs, setJobs] = useState<ScrapeJob[]>([]);
  const [similar, setSimilar] = useState<SimilarCompany[]>([]);

  const refresh = useCallback(async () => {
    const [detail, jobList] = await Promise.all([getCompany(companyId), listScrapeJobs(companyId)]);
    setCompany(detail);
    setJobs(jobList);
  }, [companyId]);

  // `.then()`, not `refresh()` called directly — see the companies list page for why.
  useEffect(() => {
    Promise.all([getCompany(companyId), listScrapeJobs(companyId)]).then(([detail, jobList]) => {
      setCompany(detail);
      setJobs(jobList);
    });
    // Best-effort — a company with no summary embedding yet (still scraping, or scraping failed
    // before extraction) just gets an empty list, not an error.
    getSimilarCompanies(companyId)
      .then(setSimilar)
      .catch(() => setSimilar([]));
  }, [companyId]);

  useEffect(() => {
    if (!company || !ACTIVE_STATUSES.has(company.profile_status)) return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [company, refresh]);

  if (!company) return null;

  const latestJob = jobs[0];

  return (
    <main className="mx-auto max-w-3xl px-6 py-10">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{company.name}</h1>
          <a
            href={company.website_url}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-zinc-500 underline"
          >
            {company.domain}
          </a>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={async () => {
              await reprofileCompany(companyId);
              await refresh();
            }}
            disabled={ACTIVE_STATUSES.has(company.profile_status)}
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm disabled:opacity-50"
          >
            Re-profile now
          </button>
          <StatusBadge status={company.profile_status} />
        </div>
      </div>

      <CompanyFacts company={company} />

      {latestJob && (
        <div className="mt-4 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="font-medium">Latest scrape</span>
            <StatusBadge status={latestJob.status} />
          </div>
          <dl className="mt-2 grid grid-cols-2 gap-1 text-zinc-600 sm:grid-cols-4">
            <div>
              <dt className="text-xs text-zinc-400">Tier reached</dt>
              <dd>{latestJob.tier_reached}</dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-400">Pages read</dt>
              <dd>{latestJob.pages_fetched}</dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-400">Tokens</dt>
              <dd>
                {latestJob.tokens_in}/{latestJob.tokens_out}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-zinc-400">Cost</dt>
              <dd>${latestJob.cost_usd.toFixed(4)}</dd>
            </div>
          </dl>
          {latestJob.error && <p className="mt-2 text-red-600">{latestJob.error}</p>}
        </div>
      )}

      {company.overview && <p className="mt-6 text-zinc-700">{company.overview}</p>}

      <section className="mt-8">
        <h2 className="text-lg font-semibold">Products &amp; services</h2>
        {company.offerings.length === 0 ? (
          <p className="mt-2 text-sm text-zinc-500">Nothing extracted yet.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-4">
            {company.offerings.map((o) => (
              <li key={o.id} className="rounded-lg border border-zinc-200 bg-white p-4">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs uppercase text-zinc-500">
                    {o.kind}
                  </span>
                  <span className="font-medium">{o.name}</span>
                  {o.category && <span className="text-sm text-zinc-400">· {o.category}</span>}
                </div>
                {o.description && <p className="mt-1 text-sm text-zinc-600">{o.description}</p>}
                <EvidenceList evidence={o.evidence} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-8">
        <h2 className="text-lg font-semibold">Competencies</h2>
        {company.competencies.length === 0 ? (
          <p className="mt-2 text-sm text-zinc-500">Nothing extracted yet.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-4">
            {company.competencies.map((c) => (
              <li key={c.id} className="rounded-lg border border-zinc-200 bg-white p-4">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs uppercase text-zinc-500">
                    {c.kind.replace("_", " ")}
                  </span>
                  <span className="font-medium">{c.name}</span>
                </div>
                {c.description && <p className="mt-1 text-sm text-zinc-600">{c.description}</p>}
                <EvidenceList evidence={c.evidence} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <TagsSection companyId={companyId} />
      <ChangesSection companyId={companyId} />
      <ContactsSection companyId={companyId} />
      <NotesSection companyId={companyId} />

      {similar.length > 0 && (
        <section className="mt-8">
          <h2 className="text-lg font-semibold">Similar companies</h2>
          <ul className="mt-3 flex flex-col gap-2">
            {similar.map(({ company: c }) => (
              <li key={c.id}>
                <Link
                  href={`/companies/${c.id}`}
                  className="flex items-center justify-between rounded-lg border border-zinc-200 bg-white px-4 py-3 hover:border-zinc-300"
                >
                  <span className="font-medium">{c.name}</span>
                  <span className="text-sm text-zinc-500">{c.domain}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <button
        onClick={async () => {
          await deleteCompany(companyId);
          router.push("/");
        }}
        className="mt-10 text-sm text-red-600 underline"
      >
        Remove company
      </button>
    </main>
  );
}
