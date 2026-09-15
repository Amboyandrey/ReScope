"use client";

import { useEffect, useState } from "react";
import { type ProfileChange, listProfileChanges } from "@/lib/crm-client";

type AddedRemoved = { added: string[]; removed: string[] };
type OverviewDiff = { before: string | null; after: string | null };

function ListDiff({ label, diff }: { label: string; diff: AddedRemoved }) {
  if (diff.added.length === 0 && diff.removed.length === 0) return null;
  return (
    <div>
      <span className="text-xs uppercase text-zinc-400">{label}</span>
      {diff.added.map((name) => (
        <div key={`+${name}`} className="text-emerald-700">
          + {name}
        </div>
      ))}
      {diff.removed.map((name) => (
        <div key={`-${name}`} className="text-red-600 line-through">
          {name}
        </div>
      ))}
    </div>
  );
}

function ChangeCard({ change }: { change: ProfileChange }) {
  const overview = change.diff.overview as OverviewDiff | undefined;
  const offerings = change.diff.offerings as AddedRemoved | undefined;
  const competencies = change.diff.competencies as AddedRemoved | undefined;

  return (
    <li className="rounded-lg border border-zinc-200 bg-white p-4 text-sm">
      <p className="text-xs text-zinc-400">{new Date(change.created_at).toLocaleString()}</p>
      <div className="mt-2 flex flex-col gap-2">
        {overview && (
          <div>
            <span className="text-xs uppercase text-zinc-400">Overview</span>
            <p className="text-zinc-600">{overview.after ?? "(cleared)"}</p>
          </div>
        )}
        {offerings && <ListDiff label="Products & services" diff={offerings} />}
        {competencies && <ListDiff label="Competencies" diff={competencies} />}
      </div>
    </li>
  );
}

export function ChangesSection({ companyId }: { companyId: string }) {
  const [changes, setChanges] = useState<ProfileChange[] | null>(null);

  useEffect(() => {
    listProfileChanges(companyId).then(setChanges);
  }, [companyId]);

  if (!changes || changes.length === 0) return null;

  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold">Recent changes</h2>
      <ul className="mt-3 flex flex-col gap-3">
        {changes.map((c) => (
          <ChangeCard key={c.id} change={c} />
        ))}
      </ul>
    </section>
  );
}
