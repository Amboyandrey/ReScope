"use client";

import { useEffect, useState } from "react";
import { FormError } from "@/components/form-error";
import { AuthError } from "@/lib/auth-client";
import {
  type ChatProvider,
  type Credential,
  type Provider,
  deleteCredential,
  getAvailableModels,
  getCurrentTenantSettings,
  listCredentials,
  setChatModel,
  setCredential,
  setScrapeProvider,
} from "@/lib/credentials-client";
import type { ScrapeProvider } from "@/lib/tenant-client";

const PROVIDER_LABELS: Record<Provider, string> = {
  anthropic: "Anthropic",
  browser_use: "Browser Use",
  openai: "OpenAI",
  gemini: "Gemini",
  nebius: "Nebius",
  custom: "Custom (OpenAI-compatible)",
};

const CHAT_PROVIDERS: ChatProvider[] = ["anthropic", "openai", "gemini", "nebius", "custom"];

export default function ApiKeysPage() {
  const [credentials, setCredentials] = useState<Credential[] | null>(null);
  const [provider, setProvider] = useState<Provider>("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const [scrapeProvider, setScrapeProviderState] = useState<ScrapeProvider | null>(null);
  const [scrapeProviderError, setScrapeProviderError] = useState<string | null>(null);

  const [chatProvider, setChatProviderState] = useState<ChatProvider | null>(null);
  const [chatModel, setChatModelState] = useState<string>("");
  const [chatModelInput, setChatModelInput] = useState<ChatProvider>("anthropic");
  const [chatModelError, setChatModelError] = useState<string | null>(null);
  const [chatModelPending, setChatModelPending] = useState(false);

  const [availableModels, setAvailableModels] = useState<string[] | null>(null);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsFetchError, setModelsFetchError] = useState<string | null>(null);
  const [manualModelEntry, setManualModelEntry] = useState(false);

  const refresh = async () => setCredentials(await listCredentials());

  useEffect(() => {
    listCredentials().then(setCredentials);
    getCurrentTenantSettings().then((t) => {
      setScrapeProviderState(t.scrape_provider);
      setChatProviderState(t.chat_provider);
      setChatModelState(t.chat_model);
      setChatModelInput(t.chat_provider);
    });
  }, []);

  useEffect(() => {
    if (chatProvider === null) return;
    let cancelled = false;
    Promise.resolve()
      .then(() => {
        if (cancelled) return;
        setModelsLoading(true);
        setModelsFetchError(null);
      })
      .then(() => getAvailableModels(chatModelInput))
      .then((models) => {
        if (cancelled) return;
        setAvailableModels(models);
        setManualModelEntry(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setAvailableModels(null);
        setManualModelEntry(true);
        setModelsFetchError(err instanceof AuthError ? err.message : "Could not load the model list.");
      })
      .finally(() => {
        if (!cancelled) setModelsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [chatProvider, chatModelInput]);

  async function onScrapeProviderChange(next: ScrapeProvider) {
    setScrapeProviderError(null);
    try {
      await setScrapeProvider(next);
      setScrapeProviderState(next);
    } catch (err) {
      setScrapeProviderError(err instanceof AuthError ? err.message : "Could not switch provider.");
    }
  }

  async function onChatModelSubmit(e: React.FormEvent) {
    e.preventDefault();
    setChatModelError(null);
    setChatModelPending(true);
    try {
      await setChatModel(chatModelInput, chatModel);
      setChatProviderState(chatModelInput);
    } catch (err) {
      setChatModelError(err instanceof AuthError ? err.message : "Could not save this chat model.");
    } finally {
      setChatModelPending(false);
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    try {
      await setCredential(provider, apiKey, provider === "custom" ? baseUrl : undefined);
      setApiKey("");
      setBaseUrl("");
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
        Register your own Anthropic, Browser Use, OpenAI, Gemini, or Nebius key — or point chat at
        your own OpenAI-compatible server — to run scraping, profiling, or chat on your own account
        instead of the platform&apos;s. A workspace with its own key isn&apos;t limited by its
        plan&apos;s monthly quota.
      </p>

      {credentials !== null && (
        <ul className="mt-6 flex flex-col gap-2">
          {(["anthropic", "browser_use", "openai", "gemini", "nebius", "custom"] as Provider[]).map((p) => {
            const credential = registered.get(p);
            const hasPlatformFallback = p === "anthropic" || p === "browser_use";
            return (
              <li
                key={p}
                className="flex items-center justify-between rounded-lg border border-zinc-200 bg-white px-4 py-3"
              >
                <div>
                  <div className="font-medium">{PROVIDER_LABELS[p]}</div>
                  {credential ? (
                    <div className="text-sm text-zinc-500">
                      Ending in {credential.last4}
                      {credential.base_url && <> · {credential.base_url}</>} · validated{" "}
                      {new Date(credential.validated_at).toLocaleDateString()}
                    </div>
                  ) : (
                    <div className="text-sm text-zinc-400">
                      {hasPlatformFallback ? "Not registered — using the platform key." : "Not registered."}
                    </div>
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
            <option value="openai">OpenAI</option>
            <option value="gemini">Gemini</option>
            <option value="nebius">Nebius</option>
            <option value="custom">Custom (OpenAI-compatible)</option>
          </select>
        </label>
        {provider === "custom" && (
          <input
            type="text"
            className="rounded-md border border-zinc-300 px-3 py-2"
            placeholder="Base URL, e.g. https://my-server.example.com/v1"
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            required
          />
        )}
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

      {chatProvider !== null && (
        <section className="mt-10 border-t border-zinc-200 pt-6">
          <h2 className="text-lg font-semibold">Chat model</h2>
          <p className="mt-1 text-sm text-zinc-600">
            Which provider and model answer your workspace&apos;s chat messages — Anthropic by
            default, or any other provider once you&apos;ve registered a key for it above.
          </p>
          <div className="mt-2 text-sm text-zinc-500">
            Currently: {PROVIDER_LABELS[chatProvider]} · {chatModel}
          </div>
          <form onSubmit={onChatModelSubmit} className="mt-3 flex flex-col gap-2">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium uppercase text-zinc-500">Provider</span>
              <select
                className="rounded-md border border-zinc-300 px-2 py-1.5"
                value={chatModelInput}
                onChange={(e) => setChatModelInput(e.target.value as ChatProvider)}
              >
                {CHAT_PROVIDERS.filter((p) => p === "anthropic" || registered.get(p)).map((p) => (
                  <option key={p} value={p}>
                    {PROVIDER_LABELS[p]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs font-medium uppercase text-zinc-500">Model</span>
              {modelsLoading ? (
                <div className="rounded-md border border-zinc-200 px-3 py-2 text-sm text-zinc-400">
                  Loading models…
                </div>
              ) : manualModelEntry || availableModels === null ? (
                <input
                  type="text"
                  className="rounded-md border border-zinc-300 px-3 py-2"
                  placeholder="e.g. claude-sonnet-5"
                  value={chatModel}
                  onChange={(e) => setChatModelState(e.target.value)}
                  required
                />
              ) : (
                <select
                  className="rounded-md border border-zinc-300 px-2 py-1.5"
                  value={chatModel}
                  onChange={(e) => setChatModelState(e.target.value)}
                >
                  <option value="" disabled>
                    Choose a model…
                  </option>
                  {chatModel && !availableModels.includes(chatModel) && (
                    <option value={chatModel}>{chatModel} (current)</option>
                  )}
                  {availableModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              )}
            </label>
            {modelsFetchError && (
              <div className="text-xs text-zinc-400">{modelsFetchError} — type a model id instead.</div>
            )}
            {!modelsLoading && availableModels !== null && (
              <button
                type="button"
                className="self-start text-xs text-zinc-500 underline"
                onClick={() => setManualModelEntry((v) => !v)}
              >
                {manualModelEntry ? "Choose from the list instead" : "Type a model id instead"}
              </button>
            )}
            <button
              type="submit"
              disabled={chatModelPending}
              className="self-start rounded-md bg-zinc-900 px-4 py-2 text-sm text-white disabled:opacity-50"
            >
              {chatModelPending ? "Validating…" : "Save chat model"}
            </button>
          </form>
          <FormError message={chatModelError} />
        </section>
      )}
    </main>
  );
}
