// Shared centered-card shell for the signup and login pages — both live on the root domain.
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-sm rounded-xl border border-zinc-200 bg-white p-8 shadow-sm">
        {children}
      </div>
    </main>
  );
}
