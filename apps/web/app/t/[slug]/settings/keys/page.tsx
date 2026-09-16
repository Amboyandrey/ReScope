"use client";

import { useEffect, useState } from "react";
import { FormError } from "@/components/form-error";
import { AuthError } from "@/lib/auth-client";
import {
  type Credential,
  type Provider,
  deleteCredential,
  listCredentials,
  setCredential,
} from "@/lib/credentials-client";

const PROVIDER_LABELS: Record<Provider, string> = {
  anthropic: "Anthropic",
  browser_use: "Browser Use",
};

export default function ApiKeysPage() {
  const [credentials, setCredentials] = useState<Credential[] | null>(null);
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const refresh = async () => setCredentials(await listCredentials());

  useEffect(() => {
    listCredentials().then(setCredentials);
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      await setCredential(provider, apiKey);
      setApiKey("");
      await refresh();
    } catch (err) {
      setError(err instanceof AuthError ? err.message : "Could not save this key.");
    } finally {
      setPending(false);
    }
  }

  const registered = new Map((credentials ?? []).map((c) => [c.provider, c]));

  return (
    <main className="mx-auto max-w-2xl px-6 py-10">
      <h1 className="text-2xl font-semibold">API keys</h1>
      <p className="mt-1 text-zinc-600">
        Register your own Anthropic or Browser Use key to run scraping and profiling on your own
        account instead of the platform&apos;s — a workspace with its own key isn&apos;t limited by
        its plan&apos;s monthly quota.
      </p>

      {credentials !== null && (
        <ul className="mt-6 flex flex-col gap-2">
          {(["anthropic", "browser_use"] as Provider[]).map((p) => {
            const credential = registered.get(p);
            return (
              <li
                key={p}
                className="flex items-center justify-between rounded-lg border border-zinc-200 bg-white px-4 py-3"
              >
                <div>
                  <div className="font-medium">{PROVIDER_LABELS[p]}</div>
                  {credential ? (
                    <div className="text-sm text-zinc-500">
                      Ending in {credential.last4} · validated{" "}
                      {new Date(credential.validated_at).toLocaleDateString()}
                    </div>
                  ) : (
                    <div className="text-sm text-zinc-400">Not registered — using the platform key.</div>
                  )}
                </div>
                {credential && (
                  <button
                    onClick={async () => {
                      await deleteCredential(p);
                      await refresh();
                    }}
                    className="text-sm text-red-600 hover:underline"
                  >
                    Remove
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-2">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs font-medium uppercase text-zinc-500">Provider</span>
          <select
            className="rounded-md border border-zinc-300 px-2 py-1.5"
            value={provider}
            onChange={(e) => setProvider(e.target.value as Provider)}
          >
            <option value="anthropic">Anthropic</option>
            <option value="browser_use">Browser Use</option>
          </select>
        </label>
        <input
          type="password"
          className="rounded-md border border-zinc-300 px-3 py-2"
          placeholder="Paste your API key"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          required
        />
        <button
          type="submit"
          disabled={pending}
          className="self-start rounded-md bg-zinc-900 px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {pending ? "Validating…" : "Save key"}
        </button>
      </form>
      <FormError message={error} />
    </main>
  );
}
