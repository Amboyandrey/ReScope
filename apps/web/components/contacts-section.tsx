"use client";

import { useEffect, useRef, useState } from "react";
import { FormError } from "@/components/form-error";
import { AuthError } from "@/lib/auth-client";
import {
  type Contact,
  createContact,
  deleteContact,
  importContactsCsv,
  listContacts,
  updateContact,
} from "@/lib/crm-client";

function ContactRow({
  contact,
  onChange,
}: {
  contact: Contact;
  onChange: (updated: Contact | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(contact.title ?? "");

  async function saveTitle() {
    onChange(await updateContact(contact.company_id, contact.id, { title: title || undefined }));
    setEditing(false);
  }

  return (
    <li className="flex items-center justify-between rounded-lg border border-zinc-200 bg-white px-4 py-3">
      <div>
        <div className="font-medium">
          {contact.first_name} {contact.last_name}
        </div>
        <div className="text-sm text-zinc-500">
          {editing ? (
            <input
              autoFocus
              className="rounded border border-zinc-300 px-1 py-0.5 text-sm"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={saveTitle}
              onKeyDown={(e) => e.key === "Enter" && saveTitle()}
            />
          ) : (
            <button onClick={() => setEditing(true)} className="hover:underline">
              {contact.title ?? "Add title"}
            </button>
          )}
          {contact.email && <span> · {contact.email}</span>}
          {contact.phone && <span> · {contact.phone}</span>}
        </div>
      </div>
      <button
        onClick={async () => {
          await deleteContact(contact.company_id, contact.id);
          onChange(null);
        }}
        className="text-sm text-red-600 hover:underline"
      >
        Remove
      </button>
    </li>
  );
}

export function ContactsSection({ companyId }: { companyId: string }) {
  const [contacts, setContacts] = useState<Contact[] | null>(null);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<{ row_count: number; errors: string[] } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listContacts(companyId).then(setContacts);
  }, [companyId]);

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      const created = await createContact(companyId, { first_name: firstName, last_name: lastName });
      setContacts((prev) => [...(prev ?? []), created]);
      setFirstName("");
      setLastName("");
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not add contact.");
    }
  }

  async function onImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    try {
      const result = await importContactsCsv(companyId, file);
      setImportResult(result);
      setContacts(await listContacts(companyId));
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not import that file.");
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  return (
    <section className="mt-8">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Contacts</h2>
        <label className="cursor-pointer text-sm text-zinc-600 underline">
          Import CSV
          <input ref={fileInputRef} type="file" accept=".csv" onChange={onImport} className="hidden" />
        </label>
      </div>

      {importResult && (
        <p className="mt-2 text-sm text-zinc-500">
          Imported {importResult.row_count} contact{importResult.row_count === 1 ? "" : "s"}
          {importResult.errors.length > 0 && `, skipped ${importResult.errors.length} row(s)`}.
        </p>
      )}

      <form onSubmit={onAdd} className="mt-3 flex gap-2">
        <input
          className="w-1/3 rounded-md border border-zinc-300 px-3 py-2 text-sm"
          placeholder="First name"
          value={firstName}
          onChange={(e) => setFirstName(e.target.value)}
          required
        />
        <input
          className="w-1/3 rounded-md border border-zinc-300 px-3 py-2 text-sm"
          placeholder="Last name"
          value={lastName}
          onChange={(e) => setLastName(e.target.value)}
          required
        />
        <button type="submit" className="rounded-md bg-zinc-900 px-4 py-2 text-sm text-white">
          Add
        </button>
      </form>
      <FormError message={error} />

      {contacts === null ? null : contacts.length === 0 ? (
        <p className="mt-3 text-sm text-zinc-500">No contacts yet.</p>
      ) : (
        <ul className="mt-3 flex flex-col gap-2">
          {contacts.map((c) => (
            <ContactRow
              key={c.id}
              contact={c}
              onChange={(updated) =>
                setContacts((prev) =>
                  updated
                    ? (prev ?? []).map((p) => (p.id === updated.id ? updated : p))
                    : (prev ?? []).filter((p) => p.id !== c.id),
                )
              }
            />
          ))}
        </ul>
      )}
    </section>
  );
}
