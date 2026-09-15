"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { EvidenceList } from "@/components/evidence-list";
import { StatusBadge } from "@/components/status-badge";
import {
  type CompanyDetail,
  type ScrapeJob,
  deleteCompany,
  getCompany,
  listScrapeJobs,
} from "@/lib/company-client";

const ACTIVE_STATUSES = new Set(["pending", "scraping"]);

export default function CompanyProfilePage() {
  const router = useRouter();
  const { companyId } = useParams<{ companyId: string }>();
  const [company, setCompany] = useState<CompanyDetail | null>(null);
  const [jobs, setJobs] = useState<ScrapeJob[]>([]);

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
        <StatusBadge status={company.profile_status} />
      </div>

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
