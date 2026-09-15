"use client";

import { useEffect, useState } from "react";
import { type SavedSearch, createSavedSearch, deleteSavedSearch, listSavedSearches } from "@/lib/crm-client";

export function SavedSearchesSection({
  currentQuery,
  onRun,
}: {
  currentQuery: string;
  onRun: (q: string) => void;
}) {
  const [saved, setSaved] = useState<SavedSearch[] | null>(null);
  const [name, setName] = useState("");

  useEffect(() => {
    listSavedSearches().then(setSaved);
  }, []);

  async function onSave(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !currentQuery.trim()) return;
    const created = await createSavedSearch(name.trim(), currentQuery);
    setSaved((prev) => [created, ...(prev ?? [])]);
    setName("");
  }

  if (saved === null) return null;

  return (
    <div className="mt-2">
      {currentQuery.trim() && (
        <form onSubmit={onSave} className="flex gap-2">
          <input
            className="rounded-md border border-zinc-300 px-2 py-1 text-sm"
            placeholder="Name this search…"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="text-sm text-zinc-600 underline">
            Save search
          </button>
        </form>
      )}
      {saved.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-2">
          {saved.map((s) => (
            <li
              key={s.id}
              className="flex items-center gap-1 rounded-full border border-zinc-300 px-2.5 py-1 text-xs"
            >
              <button onClick={() => onRun(s.q)} className="hover:underline">
                {s.name}
              </button>
              <button
                onClick={async () => {
                  await deleteSavedSearch(s.id);
                  setSaved((prev) => (prev ?? []).filter((p) => p.id !== s.id));
                }}
                className="text-zinc-400 hover:text-red-600"
                aria-label={`Delete saved search ${s.name}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
