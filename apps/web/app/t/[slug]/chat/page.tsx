"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { CatalogueFilterRail } from "@/components/catalogue-filters";
import { FormError } from "@/components/form-error";
import { MarkdownMessage } from "@/components/markdown-message";
import { AuthError } from "@/lib/auth-client";
import type { CatalogueFilters } from "@/lib/catalogue-client";
import {
  type Citation,
  type Conversation,
  type Message,
  createConversation,
  deleteConversation,
  listConversations,
  listMessages,
  sendMessage,
} from "@/lib/chat-client";

type DisplayMessage = Message | { id: string; role: "assistant"; content: string; citations: Citation[] };

function CitationChips({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  const unique = Array.from(new Map(citations.map((c) => [c.company_id, c])).values());
  return (
    <div className="mt-2 flex flex-wrap gap-1">
      {unique.map((c) => (
        <Link
          key={c.company_id}
          href={`/companies/${c.company_id}`}
          className="rounded-full border border-zinc-300 px-2 py-0.5 text-xs text-zinc-600 hover:border-zinc-400"
        >
          View source
        </Link>
      ))}
    </div>
  );
}

export default function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const [filters, setFilters] = useState<CatalogueFilters>({});
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listConversations().then((list) => {
      setConversations(list);
      if (list.length > 0) setActiveId(list[0].id);
    });
  }, []);

  useEffect(() => {
    if (!activeId) return;
    listMessages(activeId).then(setMessages);
  }, [activeId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function onNewConversation() {
    const conversation = await createConversation("New chat");
    setConversations((prev) => [conversation, ...(prev ?? [])]);
    setActiveId(conversation.id);
  }

  async function onDeleteConversation(id: string) {
    await deleteConversation(id);
    setConversations((prev) => (prev ?? []).filter((c) => c.id !== id));
    if (activeId === id) {
      setActiveId(null);
      setMessages([]);
    }
  }

  async function onSend(e: React.FormEvent) {
    e.preventDefault();
    if (!draft.trim() || sending) return;
    setError(null);

    let conversationId = activeId;
    if (!conversationId) {
      const conversation = await createConversation(draft.slice(0, 60));
      setConversations((prev) => [conversation, ...(prev ?? [])]);
      setActiveId(conversation.id);
      conversationId = conversation.id;
    }

    const question = draft;
    setDraft("");
    setMessages((prev) => [
      ...prev,
      { id: `pending-user-${Date.now()}`, role: "user", content: question, citations: [], created_at: "" },
    ]);
    setSending(true);
    const assistantId = `pending-assistant-${Date.now()}`;
    setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "", citations: [] }]);

    try {
      await sendMessage(
        conversationId,
        question,
        filters,
        (chunk) => {
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, content: m.content + chunk } : m)),
          );
        },
        (citations) => {
          setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, citations } : m)));
        },
      );
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Something went wrong.");
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="mx-auto flex h-[calc(100vh-57px)] max-w-5xl gap-6 px-6 py-6">
      <aside className="flex w-56 shrink-0 flex-col gap-2">
        <button
          onClick={onNewConversation}
          className="rounded-md border border-zinc-300 px-3 py-2 text-sm hover:border-zinc-400"
        >
          + New chat
        </button>
        <ul className="flex flex-col gap-1 overflow-y-auto">
          {(conversations ?? []).map((c) => (
            <li key={c.id} className="flex items-center gap-1">
              <button
                onClick={() => setActiveId(c.id)}
                className={`flex-1 truncate rounded-md px-2 py-1.5 text-left text-sm ${
                  c.id === activeId ? "bg-zinc-100 font-medium" : "hover:bg-zinc-50"
                }`}
              >
                {c.title}
              </button>
              <button
                onClick={() => onDeleteConversation(c.id)}
                className="px-1 text-xs text-zinc-400 hover:text-red-600"
                aria-label={`Delete ${c.title}`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <section className="flex flex-1 flex-col">
        <div className="flex-1 overflow-y-auto rounded-lg border border-zinc-200 bg-white p-4">
          {messages.length === 0 && (
            <p className="text-sm text-zinc-500">
              Ask anything about the companies in your catalogue — answers cite the company they
              came from.
            </p>
          )}
          <div className="flex flex-col gap-4">
            {messages.map((m) => (
              <div key={m.id} className={m.role === "user" ? "self-end text-right" : "self-start"}>
                <div
                  className={`inline-block rounded-lg px-3 py-2 text-sm ${
                    m.role === "user"
                      ? "max-w-md whitespace-pre-wrap bg-zinc-900 text-white"
                      : "max-w-2xl bg-zinc-100 text-zinc-800"
                  }`}
                >
                  {m.role === "user" || !m.content ? (
                    m.content || "…"
                  ) : (
                    <MarkdownMessage content={m.content} />
                  )}
                </div>
                {m.role === "assistant" && <CitationChips citations={m.citations} />}
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
        </div>

        <FormError message={error} />

        <button
          onClick={() => setShowFilters((v) => !v)}
          className="mt-3 self-start text-xs text-zinc-500 underline"
        >
          {showFilters ? "Hide filters" : "Scope this question to a filter…"}
        </button>
        {showFilters && (
          <div className="mt-2">
            <CatalogueFilterRail filters={filters} onChange={setFilters} />
          </div>
        )}

        <form onSubmit={onSend} className="mt-3 flex gap-2">
          <input
            className="flex-1 rounded-md border border-zinc-300 px-3 py-2"
            placeholder="Ask about your catalogue…"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={sending}
          />
          <button
            type="submit"
            disabled={sending || !draft.trim()}
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {sending ? "Sending…" : "Send"}
          </button>
        </form>
      </section>
    </main>
  );
}
