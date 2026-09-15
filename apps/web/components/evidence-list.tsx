import type { Evidence } from "@/lib/company-client";

/** The source URL(s) and supporting quote(s) behind one extracted fact — click through to verify
 * it against the page it actually came from. */
export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return null;
  return (
    <ul className="mt-1 flex flex-col gap-0.5">
      {evidence.map((e, i) => (
        <li key={i} className="text-xs text-zinc-500">
          <span>&ldquo;{e.quote}&rdquo; — </span>
          <a href={e.url} target="_blank" rel="noreferrer" className="underline">
            {e.url}
          </a>
        </li>
      ))}
    </ul>
  );
}
