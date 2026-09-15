"use client";

import { useEffect, useState } from "react";
import { type Note, createNote, deleteNote, listNotes } from "@/lib/crm-client";

export function NotesSection({ companyId }: { companyId: string }) {
  const [notes, setNotes] = useState<Note[] | null>(null);
  const [body, setBody] = useState("");

  useEffect(() => {
    listNotes(companyId).then(setNotes);
  }, [companyId]);

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!body.trim()) return;
    const created = await createNote(companyId, body);
    setNotes((prev) => [created, ...(prev ?? [])]);
    setBody("");
  }

  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold">Notes</h2>
      <form onSubmit={onAdd} className="mt-3 flex flex-col gap-2">
        <textarea
          className="rounded-md border border-zinc-300 px-3 py-2 text-sm"
          placeholder="Leave a note for the rest of the team…"
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={2}
        />
        <button type="submit" className="self-end rounded-md bg-zinc-900 px-4 py-2 text-sm text-white">
          Add note
        </button>
      </form>

      {notes === null ? null : notes.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-500">No notes yet.</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {notes.map((n) => (
            <li key={n.id} className="rounded-lg border border-zinc-200 bg-white p-4">
              <div className="flex items-start justify-between gap-4">
                <p className="whitespace-pre-wrap text-sm text-zinc-700">{n.body}</p>
                <button
                  onClick={async () => {
                    await deleteNote(companyId, n.id);
                    setNotes((prev) => (prev ?? []).filter((p) => p.id !== n.id));
                  }}
                  className="shrink-0 text-sm text-red-600 hover:underline"
                >
                  Remove
                </button>
              </div>
              <p className="mt-1 text-xs text-zinc-400">{new Date(n.created_at).toLocaleString()}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
