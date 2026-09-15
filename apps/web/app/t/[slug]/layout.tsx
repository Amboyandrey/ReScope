// Everything under /t/[slug] is a tenant page. The proxy rewrites `slug.rescope.app/...` here and
// blocks direct access, so `slug` is always the host's tenant — membership checks come with auth.
export default async function TenantLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return (
    <div className="min-h-screen">
      <header className="border-b border-zinc-200 bg-white px-6 py-3">
        <span className="font-semibold">ReScope</span>
        <span className="ml-3 rounded bg-zinc-100 px-2 py-0.5 font-mono text-xs text-zinc-600">{slug}</span>
      </header>
      {children}
    </div>
  );
}
