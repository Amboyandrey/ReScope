"use client";

import { useEffect, useState } from "react";
import {
  type Tag,
  attachTag,
  createTag,
  detachTag,
  listCompanyTags,
  listTags,
} from "@/lib/crm-client";

export function TagsSection({ companyId }: { companyId: string }) {
  const [allTags, setAllTags] = useState<Tag[]>([]);
  const [companyTags, setCompanyTags] = useState<Tag[] | null>(null);
  const [newTagName, setNewTagName] = useState("");

  useEffect(() => {
    listTags().then(setAllTags);
    listCompanyTags(companyId).then(setCompanyTags);
  }, [companyId]);

  const attachedIds = new Set((companyTags ?? []).map((t) => t.id));
  const unattached = allTags.filter((t) => !attachedIds.has(t.id));

  async function onAttach(tagId: string) {
    await attachTag(companyId, tagId);
    setCompanyTags((prev) => [...(prev ?? []), allTags.find((t) => t.id === tagId)!]);
  }

  async function onDetach(tagId: string) {
    await detachTag(companyId, tagId);
    setCompanyTags((prev) => (prev ?? []).filter((t) => t.id !== tagId));
  }

  async function onCreateAndAttach(e: React.FormEvent) {
    e.preventDefault();
    if (!newTagName.trim()) return;
    const tag = await createTag(newTagName.trim());
    setAllTags((prev) => [...prev, tag]);
    await onAttach(tag.id);
    setNewTagName("");
  }

  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold">Tags</h2>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {(companyTags ?? []).map((tag) => (
          <button
            key={tag.id}
            onClick={() => onDetach(tag.id)}
            className="rounded-full px-2.5 py-1 text-xs font-medium text-white hover:opacity-80"
            style={{ backgroundColor: tag.color }}
            title="Remove tag"
          >
            {tag.name} ×
          </button>
        ))}
        {unattached.length > 0 && (
          <select
            className="rounded-md border border-zinc-300 px-2 py-1 text-sm text-zinc-600"
            value=""
            onChange={(e) => e.target.value && onAttach(e.target.value)}
          >
            <option value="">+ Add existing tag</option>
            {unattached.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        )}
      </div>
      <form onSubmit={onCreateAndAttach} className="mt-3 flex gap-2">
        <input
          className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm"
          placeholder="New tag name"
          value={newTagName}
          onChange={(e) => setNewTagName(e.target.value)}
        />
        <button type="submit" className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm">
          Create &amp; add
        </button>
      </form>
    </section>
  );
}
