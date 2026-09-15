export default async function TenantHome({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <h1 className="text-2xl font-semibold">Workspace: {slug}</h1>
      <p className="mt-2 text-zinc-600">Companies, search and profiles arrive in Phase 1.</p>
    </main>
  );
}
