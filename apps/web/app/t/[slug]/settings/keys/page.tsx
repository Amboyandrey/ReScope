"use client";

import { useEffect, useState } from "react";
import { FormError } from "@/components/form-error";
import { AuthError } from "@/lib/auth-client";
import {
  type Credential,
  type Provider,
  deleteCredential,
  getCurrentTenantSettings,
  listCredentials,
  setCredential,
  setScrapeProvider,
} from "@/lib/credentials-client";
import type { ScrapeProvider } from "@/lib/tenant-client";

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

  const [scrapeProvider, setScrapeProviderState] = useState<ScrapeProvider | null>(null);
  const [scrapeProviderError, setScrapeProviderError] = useState<string | null>(null);

  const refresh = async () => setCredentials(await listCredentials());

  useEffect(() => {
    listCredentials().then(setCredentials);
    getCurrentTenantSettings().then((t) => setScrapeProviderState(t.scrape_provider));
  }, []);

  async function onScrapeProviderChange(next: ScrapeProvider) {
    setScrapeProviderError(null);
    try {
      await setScrapeProvider(next);
      setScrapeProviderState(next);
    } catch (err) {
      setScrapeProviderError(err instanceof AuthError ? err.message : "Could not switch provider.");
    }
  }

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

      {scrapeProvider !== null && (
        <section className="mt-10 border-t border-zinc-200 pt-6">
          <h2 className="text-lg font-semibold">Deep-scan provider</h2>
          <p className="mt-1 text-sm text-zinc-600">
            Which agent a deep scan uses to explore a site — the built-in agent, or Browser Use
            Cloud once a Browser Use key is registered above.
          </p>
          <div className="mt-3 flex flex-col gap-2">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="scrape-provider"
                checked={scrapeProvider === "custom"}
                onChange={() => onScrapeProviderChange("custom")}
              />
              Built-in agent
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="scrape-provider"
                checked={scrapeProvider === "browser_use_cloud"}
                disabled={!registered.get("browser_use")}
                onChange={() => onScrapeProviderChange("browser_use_cloud")}
              />
              Browser Use Cloud
              {!registered.get("browser_use") && (
                <span className="text-zinc-400">— register a Browser Use key first</span>
              )}
            </label>
          </div>
          <FormError message={scrapeProviderError} />
        </section>
      )}
    </main>
  );
}
