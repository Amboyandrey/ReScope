import Link from "next/link";
import { ROOT_DOMAIN } from "@/lib/config";

// The root domain: marketing, signup, login and the tenant switcher live here. Tenants live on
// their own subdomains and never render this page.
export default function RootPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-6">
      <h1 className="text-4xl font-semibold tracking-tight">ReScope</h1>
      <p className="text-lg text-zinc-600">
        Paste a company&apos;s website. Get its products, services and competencies, with evidence —
        searchable across every account your team tracks.
      </p>
      <div className="flex gap-3">
        <Link href="/signup" className="rounded-md bg-zinc-900 px-4 py-2 text-white">
          Sign up
        </Link>
        <Link href="/login" className="rounded-md border border-zinc-300 px-4 py-2">
          Log in
        </Link>
      </div>
      <p className="text-sm text-zinc-500">
        Workspaces live at <code>{`{slug}.${ROOT_DOMAIN}`}</code>.
      </p>
    </main>
  );
}
