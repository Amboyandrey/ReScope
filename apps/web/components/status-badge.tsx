const STYLES: Record<string, string> = {
  pending: "bg-zinc-100 text-zinc-600",
  queued: "bg-zinc-100 text-zinc-600",
  scraping: "bg-amber-100 text-amber-700",
  running: "bg-amber-100 text-amber-700",
  done: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
};

/** A small pill for a company's or a scrape job's status — the same vocabulary either way. */
export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STYLES[status] ?? STYLES.pending}`}>
      {status}
    </span>
  );
}
