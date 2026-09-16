# ReScope — build plan

ReScope is a multi-tenant company-intelligence CRM. Each tenant lives on its own subdomain
(`acme.rescope.app`). A member pastes a company's website; a background pipeline profiles the
company — basics, overview, products, services, competencies, each with evidence — and embeds the
result into pgvector so the tenant can search its accounts semantically and find similar companies.

This document is the source of truth for *what* we're building and *why*. `ARCHITECTURE.md`
(written in Phase 5) will describe what was actually built.

## 1. Decisions

These were made up front and the rest of the plan depends on them.

- **Shared database, shared schema.** One Postgres, one schema, `tenant_id` on every tenant-scoped
  row. Isolation is enforced three times: tenant resolved from the `Host` header (never from the
  request body or path), composite foreign keys that make cross-tenant references impossible at the
  database, and row-level security as the backstop. See §3.
- **Per-tenant copies of scraped data.** When two tenants add `acme.com`, each gets its own profile
  rows from its own scrape job. The only tables without a `tenant_id` are `users`, `tenants`, and
  `plans`. A global scrape cache is a possible later optimization, not part of the design.
- **Platform-paid LLM, quotas per plan.** ReScope holds one Anthropic key (in the environment, never
  the database). Tenants get `N` profiles and `M` deep runs per calendar month by plan, enforced
  before a job is enqueued and metered per job into an append-only usage ledger.
- **Light CRM.** Companies (accounts), contacts, notes, tags, saved searches, CSV import. No deals
  or pipeline. The profiling pipeline is the product; the CRM layer makes it usable day to day.
- **New codebase, not a fork of ReCore.** Same stack and the same two conventions that kept ReCore
  maintainable — *routers contain no logic, services never import FastAPI* — but written fresh.
- **Tiered scraping.** A cheap text pass handles most sites; a visual browser agent
  (`browser-use`) runs only when the text pass is not enough or the user asks for a deep run.
- **Self-hosted embeddings.** `Qwen/Qwen3-Embedding-0.6B` served by Hugging Face
  text-embeddings-inference, 1024 dimensions, fixed in the schema. Switching models later is a
  re-embed job, not a migration.

## 2. Stack

| Layer | Choice |
|---|---|
| API | FastAPI, SQLAlchemy 2 (async, asyncpg), Alembic, Pydantic v2, structlog |
| Data | PostgreSQL 16 + pgvector, Redis 7 |
| Jobs | arq. Two worker processes off two images: `worker` (embeddings, scheduling, CSV import) and `scraper` (Playwright + Chromium + browser-use — heavy, isolated so a crash never takes the API worker with it) |
| Embeddings | text-embeddings-inference container serving `Qwen/Qwen3-Embedding-0.6B` |
| LLM | Anthropic SDK. `claude-opus-5` drives the visual agent; `claude-sonnet-5` does bulk structured extraction; `claude-haiku-4-5` does classification and dedupe |
| Web | Next.js 16 (App Router), React 19, Tailwind 4 |
| Infra | docker compose for everything; Caddy with a wildcard certificate in production |
| Tooling | uv, ruff, mypy, pytest (against a real `_test` database); pnpm, eslint, tsc, Playwright e2e; GitHub Actions |

## 3. Tenancy

**Resolution.** The web app's middleware reads the `Host` header, extracts the tenant slug, and
rewrites `acme.rescope.app/companies` to the internal route `/t/acme/companies`. Every API call the
web app makes carries `X-Tenant-Slug`; the API resolves it to a tenant, loads the caller's
membership, and returns **404** (not 403, which would confirm the tenant exists) if there is none.
The root domain (`rescope.app`) hosts signup, login, and the tenant switcher.

**Sessions.** Opaque session id in an `httpOnly; Secure; SameSite=Lax` cookie with
`Domain=.rescope.app`, so one login works across every tenant the user belongs to. Resolved
against Redis with a sliding TTL; revocation is a `DEL`. No JWTs.

**Schema rules.** Every tenant-scoped table has `tenant_id uuid NOT NULL`. Unique constraints are
always scoped by tenant: `UNIQUE (tenant_id, domain)`. Parent tables additionally carry
`UNIQUE (tenant_id, id)` so children can declare composite foreign keys:

```sql
FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id) ON DELETE CASCADE
```

A contact can therefore never point at another tenant's company, even if application code passes
the wrong id.

**Row-level security.** The API and workers connect as `rescope_app`, a role with CRUD and no DDL,
subject to RLS. Each request's transaction runs `SET LOCAL app.tenant_id = '<uuid>'`, and every
tenant table has one policy: `tenant_id = current_setting('app.tenant_id', true)::uuid`. Workers
re-set it after every commit because the setting is transaction-local. Migrations run as the owner
role. Unlike ReCore there are no excluded tables — everything except `users`, `tenants`, and
`plans` has a tenant.

**Roles.** `viewer < member < admin < owner`, ordered, so a permission check is one comparison.
A separate `users.is_superadmin` flag gates the platform-operator area (tenants, spend, quotas,
the scraping killswitch) and has nothing to do with tenant roles.

**Local development.** `rescope.localhost` is the root and `acme.rescope.localhost:3000` is a
tenant — browsers resolve every `*.localhost` name to loopback and accept cookies with
`Domain=.rescope.localhost`, so no hosts-file edits. The API is `localhost:8000`.

## 4. Data model

```
plans(id, name, profiles_per_month, deep_runs_per_month, max_companies, max_members)
tenants(id, slug UNIQUE, name, plan_id, status, settings jsonb, created_at)
users(id, email UNIQUE, password_hash, is_superadmin, created_at)
memberships(tenant_id, user_id, role, created_at)              PK (tenant_id, user_id)
invitations(id, tenant_id, email, role, token_hash, expires_at, accepted_at)

companies(id, tenant_id, domain, name, website_url, industry, hq_country, hq_city,
          employee_range, founded_year, socials jsonb, logo_url, overview text,
          profile_status, last_profiled_at, created_by, created_at, updated_at)
          UNIQUE (tenant_id, domain), UNIQUE (tenant_id, id)
offerings(id, tenant_id, company_id, kind product|service, name, description,
          category, url, evidence jsonb, created_at)
competencies(id, tenant_id, company_id,
          kind capability|technology|certification|industry_served|partnership,
          name, description, evidence jsonb, created_at)
embeddings(id, tenant_id, company_id, source_kind, source_id, content text,
          embedding vector(1024), model, created_at)
          UNIQUE (tenant_id, source_kind, source_id)

scrape_jobs(id, tenant_id, company_id, mode fast|deep, status, tier_reached,
          pages_fetched, tokens_in, tokens_out, cost_usd, error,
          queued_at, started_at, finished_at)
scrape_pages(id, tenant_id, job_id, url, status_code, content_hash,
          markdown text, screenshot_key, fetched_at)              -- raw artifacts, TTL'd
profile_changes(id, tenant_id, company_id, job_id, diff jsonb, created_at)

contacts(id, tenant_id, company_id, first_name, last_name, email, title,
          phone, linkedin_url, source, created_at, updated_at)
notes(id, tenant_id, company_id, author_id, body, created_at)
tags(id, tenant_id, name, color)                                UNIQUE (tenant_id, name)
company_tags(tenant_id, company_id, tag_id)
saved_searches(id, tenant_id, owner_id, name, query jsonb)
imports(id, tenant_id, kind, status, row_count, error_count, created_by, created_at)

usage_events(id, tenant_id, job_id, kind, model, tokens_in, tokens_out, cost_usd, created_at)
audit_logs(id, tenant_id, actor_id, action, target_type, target_id, metadata jsonb, created_at)
```

`evidence` is a list of `{url, quote}`. Every product, service and competency links back to the
page and sentence it was extracted from; that provenance is what makes an AI-written profile
trustworthy.

Quotas are computed on read from `usage_events` for the current calendar month. A rollup table is
the answer if that ever gets slow, and adding one changes nothing above the service.

## 5. The scraping pipeline

Each job moves through tiers and stops as soon as the profile is good enough.

**Tier 0 — discovery (no LLM).** Normalize the domain, run the SSRF guard, read `robots.txt` and
`sitemap.xml`, fetch the homepage with httpx. Rank candidate URLs by path and anchor text
(`/about`, `/products`, `/services`, `/solutions`, `/industries`, `/capabilities`,
`/case-studies`, `/contact`). Estimate whether the site is client-rendered from its
text-to-markup ratio.

**Tier 1 — text extraction.** Render up to ~25 pages with headless Playwright (no vision),
convert each to markdown, and make one structured-output call (`claude-sonnet-5`, low/medium
effort, `output_config.format` with the profile schema) that returns the profile with a confidence
per field and a source URL per item. This is expected to fully handle the majority of sites.

**Tier 2 — visual agent.** Runs when Tier 1 confidence is low, the site is an SPA, offerings sit
behind tabs / accordions / infinite scroll / mega-menus, or the user chose *deep*. `browser-use`
drives Chromium with `claude-opus-5`, given the same output schema, bounded by max steps, max
minutes, max pages and a per-job token ceiling. Screenshots are stored as evidence.

**Merge, normalize, embed.** Deduplicate offerings by name similarity, map competencies onto a
small canonical taxonomy while keeping the free-text label, then embed one row per offering and
competency plus one company-summary row. The summary embedding powers similar-company search.

**Re-profile.** On a plan-dependent schedule (e.g. every 30 days) the job runs again; the diff
against the previous profile lands in `profile_changes` and surfaces as a per-account changes feed.

**Cost controls.** Quota check before enqueue; per-job token and time ceilings inside the worker;
tokens and USD written to `usage_events` for every model call; a platform-level killswitch flag
that pauses all scraping.

## 6. Search

- **Semantic:** embed the query with the same model, `WHERE tenant_id = :t ORDER BY embedding <=> :q`,
  group by company, rank by best chunk.
- **Similar companies:** cosine distance on the company-summary embedding, within the tenant.
- **Hybrid:** `tsvector` full-text combined with vector results by reciprocal rank fusion, for
  exact product names semantic search misses.
- **Filtered ANN:** an HNSW index post-filters, so a small tenant in a large table loses recall.
  pgvector ≥ 0.8 `hnsw.iterative_scan = relaxed_order` is the fix; set it per session.

## 7. Phases

| Phase | Deliverable | Est. |
|---|---|---|
| 0 | Repo, compose (postgres, redis, api, worker, scraper, tei, web), auth + sessions, tenants + subdomain routing, memberships and roles, invitations, RLS + composite FKs, audit, CI | 2 wk |
| 1 | Companies CRUD, Tier 0 + Tier 1 scrape, structured extraction, profile page with evidence, job status UI | 1–2 wk |
| 2 | TEI service, embeddings, semantic search, similar companies, hybrid search | 1 wk |
| 3 | browser-use deep mode, screenshot evidence, usage ledger, plans + quotas, killswitch, superadmin panel | 1–2 wk |
| 4 | Contacts, notes, tags, saved searches, CSV import, scheduled re-profile + changes feed | 1–2 wk |
| 5 | ARCHITECTURE.md, production deploy with wildcard domain, demo tenant, README with recordings | 1 wk |

Phase 1 is the first demoable cut; everything after it is additive.

## 8. Conventions

- Routers contain no logic; services take plain arguments and never import FastAPI.
- One Alembic revision per schema change, with a docstring explaining anything non-obvious.
- Secrets are never fields on a response schema.
- Every privileged action writes an audit row.
- Tests run against a real Postgres and Redis, on a `_test`-suffixed database and a separate Redis
  db index, so the suite can never touch a dev stack's data.
- Work happens on a branch per phase, committed and pushed one coherent feature at a time, and
  lands through a pull request the repository owner reviews and merges.

---

# Part 2 — richer profiles, a catalogue, bring-your-own keys, Browser Use Cloud, and chat

Phases 0–5 shipped everything above. Part 2 extends it in four phases, in dependency order: the
data has to get richer before a catalogue or a chat over it is worth building; per-workspace keys
have to exist before a second scraping provider or a chat can bill against them.

## 9. Decisions

- **Browser Use Cloud, not the library.** `browser-use` (0.13.x) hard-pins `anthropic==0.76.0`
  against the `>=1.5.0` Tier 1 needs — the same conflict that produced the custom agent in Phase
  3. Its hosted API (`https://api.browser-use.com/api/v2`) is plain HTTP, runs on Browser Use's own
  models, and bills to a Browser Use key, so it sits alongside the custom agent as a second Tier 2
  *provider* rather than replacing it. No new worker image.
- **Bring-your-own keys, Anthropic only.** A workspace can register its own Anthropic key (used for
  extraction, the custom visual agent, and chat) and its own Browser Use key. A workspace on its own
  Anthropic key is exempt from the plan's profile/deep-run/chat quotas; usage is still metered, with
  each event marked as billed to the platform or to the tenant. No OpenAI or other providers — one
  LLM code path stays one.
- **Chat is retrieval over the catalogue, with citations.** One chat surface per workspace, over
  every company it tracks. The model only ever sees what pgvector retrieved for the question and is
  told to cite it; every answer stores the companies and rows it drew from. Streamed, persisted, no
  tools.
- **Descriptions are mandatory.** Every offering carries a description of what it is; every
  competency carries a description of *how the company evidently has it*. Extraction is told to
  omit an item it can't describe rather than emit a bare name. Descriptions are what gets embedded,
  so search and chat rank on substance, not labels.
- **Company facts come from the site.** Country, city, industry, company type, employee range,
  founded year, and socials are extracted from about/contact/footer pages into the columns that
  have existed since `0003` but were never populated. Country is ISO 3166-1 alpha-2; company type is
  a small fixed enum. Both are the catalogue's filters, so they're columns, not free text.

## 10. Data model changes

```
companies                 + company_type company_type NULL    (enum below)
                            hq_country now ISO-2, validated at write
offerings.description     NOT NULL (backfilled '' for legacy rows, re-profile fills them)
competencies.description  NOT NULL (same)

plans                     + chat_messages_per_month int

tenant_credentials(id, tenant_id, provider anthropic|browser_use, ciphertext bytea,
                   nonce bytea, wrapped_dek bytea, last4, validated_at,
                   created_by, created_at)                 UNIQUE (tenant_id, provider)
tenant_settings           (on tenants.settings jsonb)  scrape_provider: custom|browser_use_cloud

conversations(id, tenant_id, owner_id, title, created_at, updated_at)
messages(id, tenant_id, conversation_id, role user|assistant, content text,
         citations jsonb, tokens_in, tokens_out, created_at)

usage_events              + billed_to platform|tenant
                          + kind CHAT, kind BROWSER_USE_RUN
```

```
company_type: manufacturer | distributor | service_provider | software | consultancy
            | agency | research | other
```

Key encryption follows ReCore: AES-256-GCM, a random per-secret data key wrapped by a master key
from the environment (`MASTER_KEY`), plaintext never on a response schema, `last4` for display.

## 11. Phase 6 — richer profiles and the catalogue

**Extraction.** `ExtractedProfile` gains a `facts` block (name, hq_country, hq_city, industry,
company_type, employee_range, founded_year, socials) and `description` becomes required on every
offering and competency, with the prompt spelling out what a competency description is: the
evidence-backed reason the company has it (a certification held, a technology named on a product
page, a case study in that industry), not a restatement of its name. Facts write into `companies`
on every run. The company-summary embedding text becomes `"{name} — {company_type} in
{hq_city}, {hq_country}. {industry}. {overview}"` so a query like "robotics manufacturer in
Germany" lands on the summary row, not only on an offering.

**Catalogue API.** `GET /tenants/current/catalogue` with optional `country`, `company_type`,
`industry`, `competency_kind`, `tag`, and `q`. Filters are SQL; `q` runs the existing semantic
search first and intersects. `GET /tenants/current/catalogue/facets` returns the distinct values
and counts behind each filter so the UI never shows an option with zero results. Both viewer-role.

**Catalogue UI.** A `/catalogue` page per workspace: filter rail on the left (country, type,
industry, competency kind, tag), company cards on the right showing name, country/type/industry
line, overview excerpt, first few offerings and competencies each with its description. The
company profile header shows every fact, and offerings/competencies render their descriptions
under the name. A "Re-profile now" button on the profile (member role, quota-checked) so existing
companies pick up the new fields without waiting for the scheduler.

**Backfill.** A migration makes both `description` columns `NOT NULL DEFAULT ''`; nothing
rewrites history — the next re-profile (scheduled or manual) fills them.

## 12. Phase 7 — workspace API keys

**Storage and crypto.** `app/core/crypto.py` (envelope encryption as above), `tenant_credentials`
table, `services/credentials.py` with `set_credential`, `remove_credential`, `get_plaintext` (only
ever called by services that are about to make the call, never by a router). Adding or removing a
key is audited; the audit row carries `last4`, never the key.

**Validation on save.** An Anthropic key is checked with a minimal `messages.create` (a one-token
reply) before it's stored; a Browser Use key with `GET /api/v2/billing/account`, the cheapest
authenticated read the API exposes. A key that fails is rejected with the provider's own error,
not stored.

**Resolution.** `services/llm.py::anthropic_client_for(tenant)` returns a client on the tenant's
key when one exists, else the platform key, and reports which — every model call site (extraction,
visual agent, chat) goes through it. `assert_within_quota` short-circuits for a tenant on its own
key; `record_usage_event` writes `billed_to`.

**Settings UI.** `/settings/keys` (admin/owner): one row per provider — masked `last4`, when it was
validated, replace/remove. The scraping-provider choice (Phase 8) lives on the same page.

## 13. Phase 8 — Browser Use Cloud as a Tier 2 provider

**Client.** `app/scraping/browser_use_cloud.py`: `POST /tasks` with the profiling instruction as
`task`, `startUrl` = the company's website, `allowedDomains` = its domain, `maxSteps` = 30,
`structuredOutput` = `ExtractedProfile`'s JSON schema, `llm` = a fixed Browser Use-supported model
name held in one constant. Poll `GET /tasks/{id}` on a backoff until `finished` or `stopped`, with
a hard 10-minute ceiling; on ceiling, the run is failed locally (a client timeout does not cancel
the remote run, and this pipeline never retries it). `output` parses into `ExtractedProfile`;
each step's `screenshotUrl` is downloaded into the shared storage volume and recorded as a
`scrape_pages` row with its `url` and `screenshot_key`, so evidence works identically to the custom
agent.

**Dispatch and merge.** A deep-mode job reads the tenant's `scrape_provider`. `custom` runs today's
loop unchanged. `browser_use_cloud` runs Tier 0 + Tier 1 as usual (cheap, and it's what a site
with nothing hidden needs) and then the cloud task; the two profiles merge by case-insensitive
offering/competency name, keeping whichever copy has the longer description and the union of their
evidence. Facts prefer the Tier 1 result and fall back per field.

**Keys and metering.** The Browser Use key resolves tenant-first, then `BROWSER_USE_API_KEY` from
the environment; no key at all means the provider option is greyed out in settings. A run writes
one `usage_events` row of kind `BROWSER_USE_RUN` with `steps` in metadata and a per-step cost
constant, counted against `deep_runs_per_month` exactly like a custom deep run.

## 14. Phase 9 — chat

**Retrieval.** Embed the question, take the top 12 `embeddings` rows across the tenant (the same
`cosine_distance` query as search, without the per-company dedupe — an answer wants every relevant
row), group by company, and render a context block per company: name, facts line, overview, then
each retrieved offering/competency with its description. The optional catalogue filters from
Phase 6 apply to retrieval, so "which of my German accounts…" narrows before ranking rather than
hoping the model does it.

**Generation.** `claude-sonnet-5` on the resolved key, a system prompt that forbids answering from
anything outside the context and requires `[Company Name]` citations, streamed to the browser as
Server-Sent Events from a `StreamingResponse` — no Redis stream, no resume; a dropped connection
loses the in-flight reply and the client re-asks. Conversation history (last 10 turns) rides along
as prior messages; retrieval runs on the latest question only.

**Persistence and limits.** Every user and assistant message is a `messages` row; the assistant
row carries `citations` — `[{company_id, source_kind, source_id}]` resolved from the context the
model was given, so a citation is always a real row, never a hallucinated name. One user message
counts one `CHAT` usage event against `chat_messages_per_month`, skipped for a tenant on its own
key. Conversations are personal (owner-scoped, like saved searches).

**UI.** `/chat`: conversation list on the left, thread on the right, streamed tokens, citation
chips under each answer linking to the company's profile, and the Phase 6 filter rail collapsed
above the composer for scoping a question.

## 15. Phases

| Phase | Deliverable | Est. |
|---|---|---|
| 6 | Facts extraction, mandatory descriptions, company type/country, catalogue API + UI + facets, richer profile header, re-profile-now | 1–2 wk |
| 7 | Envelope crypto, tenant credentials (Anthropic + Browser Use), validation on save, key resolution, BYOK quota exemption, settings UI | 1 wk |
| 8 | Browser Use Cloud client, provider dispatch + merge, screenshot evidence, metering | 1 wk |
| 9 | Conversations/messages, retrieval + streamed generation with citations, chat quota, chat UI | 1–2 wk |

Each phase is its own branch and pull request, as before.

---

# Part 3 — a workspace's own chat model, on any of four providers

Phase 7 let a workspace bring its own Anthropic key; Phase 9 built chat on it. Part 3 opens chat
to a workspace's own choice of provider *and* model — Anthropic, OpenAI, Gemini, or Nebius — on its
own key. One phase: it's one cohesive change (a provider seam under chat, three more credential
kinds, one settings choice), about the size of Phase 7.

## 16. Decisions

- **Chat only.** Extraction and the visual agent stay on Anthropic: they depend on
  `client.messages.parse` structured output and on vision, neither of which is portable across
  these four providers without a per-provider rewrite. Chat is plain streamed text with a system
  prompt — the one model call in this app that genuinely is provider-agnostic. Phase 7's
  Anthropic key keeps funding scraping exactly as before; this only changes which key and model
  answer a chat message.
- **Two adapters, not four.** Anthropic keeps its native SDK. OpenAI, Gemini, and Nebius all speak
  OpenAI's chat-completions protocol — OpenAI natively, Gemini through its OpenAI-compatible
  endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`), Nebius through
  `https://api.studio.nebius.com/v1/` — so one adapter on the `openai` SDK covers all three by
  `base_url`. Streamed token usage comes back via `stream_options={"include_usage": True}`; where a
  provider omits it on a streamed reply, usage is recorded as unknown (zeros), never guessed. If
  Gemini's compatibility endpoint ever proves too partial for what chat needs, the fallback is a
  native `google-genai` adapter behind the same protocol — a third adapter, not a redesign.
- **The model is the workspace's choice, validated on save.** A provider alone isn't enough: the
  workspace names the model id it wants (`gpt-5`, `gemini-2.5-pro`, a Nebius-hosted Llama, …).
  Saving that choice makes one minimal call *with that model* on the workspace's key, so a
  mistyped model id or a key without access to it fails at settings time, not on the next chat
  message. The UI suggests a short default list per provider but accepts free text — provider
  model catalogues change faster than this app will.
- **Own key means own bill.** A workspace chatting on its own key — any provider — is exempt from
  `chat_messages_per_month`, the same rule Phase 7 set for Anthropic. Usage is still metered
  (tokens, `billed_to = tenant`, the model id). Cost is recorded only where this app has a rate
  card — the platform's own Anthropic rate — and as `0` for a tenant-billed run on another
  provider: an unknown cost is recorded as unknown, not estimated from a made-up rate.
- **Anthropic on the platform key stays the default.** A workspace that registers nothing keeps
  chatting exactly as today, on `claude-sonnet-5` and the platform key, under quota. Nothing about
  this phase changes what an unconfigured workspace sees.

## 17. Data model changes

```
credential_provider (enum)  + OPENAI, GEMINI, NEBIUS
tenants.settings (jsonb)    + chat: {provider: anthropic|openai|gemini|nebius, model: str}
```

No new tables. `tenant_credentials` already stores one envelope-encrypted key per
`(tenant_id, provider)`; three more provider values is all the storage this needs. The chat
choice lives next to `scrape_provider` in `tenants.settings`, read through a `Tenant.chat_model`
property that falls back to `(anthropic, claude-sonnet-5)` when unset — the same shape Phase 8
gave `scrape_provider`.

## 18. Phase 10 — workspace chat model

**Provider seam.** `app/llm/` — a `ChatProvider` protocol with one method, `stream(system,
messages, model)`, yielding text chunks and finishing with `(tokens_in, tokens_out)`; two
implementations, `AnthropicChat` (the existing streaming code lifted out of the chat router
unchanged) and `OpenAICompatibleChat` (the `openai` SDK, `base_url` per provider, usage from the
final streamed chunk). `build_chat_provider(provider, api_key, model)` is the only place that
knows which class or base URL goes with which `Provider` value. The chat router calls the
protocol, never an SDK.

**Key resolution.** `services/llm.py::resolve_chat_model(db, tenant)` returns
`(provider, model, api_key, billed_to)`: the workspace's saved chat choice on its own key for that
provider, or the Anthropic default on the workspace's own Anthropic key if it has one, else the
Anthropic default on the platform key. `assert_within_chat_quota` short-circuits whenever the
resolved key is the tenant's own, whichever provider it belongs to — generalizing Phase 7's
Anthropic-only check.

**Credentials.** `Provider` gains `OPENAI`, `GEMINI`, `NEBIUS`. Validation on save for each is a
one-token chat completion on that provider's compatibility endpoint — the same "prove the key
authenticates, do no real work" rule Phase 7's Anthropic check follows. Existing
`PUT/GET/DELETE /tenants/current/credentials` need no new routes, only the enum.

**Settings.** `PUT /tenants/current/chat-model` with `{provider, model}` (admin/owner): refuses a
provider the workspace has no key for (Anthropic excepted — the platform key can carry it), then
validates the model with a one-token call on the resolved key before writing
`settings.chat.{provider,model}`. `TenantResponse` gains `chat_provider` and `chat_model`.
Audited, like the scrape-provider switch.

**UI.** `/settings/keys` grows three rows (OpenAI, Gemini, Nebius) in the existing keys list and
a "Chat model" section beneath the scrape-provider one: a provider dropdown listing only providers
the workspace holds a key for (plus Anthropic), a model input pre-filled with that provider's
suggested default, and a save that surfaces the validation error inline. The `/chat` page needs no
change — which model answers is a workspace setting, not a per-message choice.

**Metering.** `record_usage_event` already takes `model` and `billed_to`; a chat run on a
non-Anthropic provider passes the provider's model id, `cost_usd=0`, and its reported tokens.
The existing `CHAT` usage kind and `chat_messages_per_month` ceiling are unchanged.

**Tests.** The OpenAI-compatible adapter against a fake transport (streamed chunks, usage in the
final chunk, usage absent); provider construction picking the right base URL per `Provider`;
credential validation for the three new providers (success, rejection); `resolve_chat_model`'s
three-way fallback; the chat-model settings endpoint (key-required, model validation failure,
admin-only); and the chat router streaming through a non-Anthropic provider end to end with a
fake client, recording `billed_to = tenant` and `cost_usd = 0`.

## 19. Phases

| Phase | Deliverable | Est. |
|---|---|---|
| 10 | `ChatProvider` seam with Anthropic + OpenAI-compatible adapters, OpenAI/Gemini/Nebius credentials, per-workspace chat model choice validated on save, quota exemption generalized to any own key, settings UI | 1 wk |

One branch, one pull request, as before.

# Part 4 — any OpenAI-compatible endpoint, and picking a model from the provider's own list

Phase 10 opened chat to four named providers. Two things it left as free text or hardcoded are what
Part 4 fixes: a workspace that runs its own OpenAI-compatible server (vLLM, Ollama, Together,
Groq, a company gateway — anything speaking the chat-completions protocol) has no way to point
chat at it, and the model id is typed by hand against a catalogue the workspace has to look up
elsewhere. Two small phases, in this order — the model picker should work for the custom endpoint
too, so the endpoint comes first.

## 20. Decisions

- **A fifth chat provider: bring your own OpenAI-compatible endpoint.** `Provider` gains `CUSTOM`.
  It rides the same `OpenAICompatibleChat` adapter Phase 10 built for OpenAI, Gemini, and Nebius —
  the only difference is that its `base_url` comes from the workspace instead of a constant. One
  custom endpoint per workspace, the same one-row-per-provider shape every other credential has;
  a second custom slot is out of scope until a workspace actually asks for one.
- **The base URL lives on the credential, not on the chat choice.** A custom endpoint is a
  `(base_url, api_key)` pair the way an Anthropic credential is an `api_key` — registering one
  shouldn't require it to already be the active chat provider, and switching chat away from it
  and back shouldn't lose it. So `tenant_credentials` grows a nullable `base_url`, set only for
  `CUSTOM`; `tenants.settings.chat` stays `{provider, model}` exactly as Phase 10 left it.
- **A custom credential validates by reachability, not by `GET /models`.** Self-hosted servers
  implement `/chat/completions` reliably and `/models` only sometimes. Saving a custom credential
  proves the `base_url` points at a real server (any HTTP response, not a connection failure) and
  stops there; the definitive proof that key, endpoint, and model work together is the one-token
  `validate_chat_model` call every provider already goes through when the chat model is saved.
  Phase 10's "cheap authenticated read" was never the real gate — this just admits that for a
  server whose schema this app can't assume.
- **Fetch the model list, don't guess it.** Every provider here exposes `GET /models` — Anthropic
  through its own SDK's `models.list()`, the rest through the OpenAI protocol. A new endpoint
  returns the ids a workspace's key can actually see, filtered by a short per-provider denylist
  (embeddings, audio, image, moderation, legacy completion models) so the dropdown shows models a
  chat call could plausibly use. No caching — it's fetched when a human opens settings, not on a
  hot path, and a workspace's account can gain access to a new model at any moment.
- **Free text stays.** The list is an affordance, not a gate — `validate_chat_model` remains the
  only thing that decides whether a model id is accepted. A model that isn't in the list (brand
  new, a custom deployment name, a server with no `/models` at all) is still typed and saved
  exactly as in Phase 10. This keeps §16's promise that provider catalogues change faster than
  this app will.

## 21. Data model changes

```
credential_provider (enum)      + CUSTOM
tenant_credentials              + base_url text NULL   -- set only when provider = CUSTOM
```

No new tables, nothing new in `tenants.settings`. Phase 12 persists nothing — the model list is
a live read.

## 22. Phase 11 — a workspace's own OpenAI-compatible endpoint

**Credentials.** `Provider.CUSTOM`. `PUT /tenants/current/credentials` accepts an optional
`base_url`, required when `provider = custom` and rejected for any other provider (422 either
way). `set_credential` stores it on the row; `CredentialResponse` returns it, so the settings page
can show which endpoint a custom credential points at. Validation for `CUSTOM` is a single
`GET {base_url}/models` that accepts any HTTP status — 200, 401, 404 all mean "a server answered
there" — and fails only on a connection error or a malformed URL. `base_url` must be `http(s)`;
nothing else is checked about its shape.

**Provider seam.** `build_chat_provider(provider, api_key, *, base_url=None)`: `CUSTOM` requires
`base_url` and hands it to `OpenAICompatibleChat` as-is; every other provider ignores the argument
and keeps its constant. `CHAT_PROVIDERS` gains `CUSTOM`. `ResolvedChatModel` gains `base_url`,
read from the credential row; `resolve_chat_model` and `set_chat_model` need no other change —
the credential lookup they already do returns the whole row. The chat router passes
`resolved.base_url` through and otherwise doesn't know `CUSTOM` exists. `validate_chat_model`
takes the same optional `base_url` so the one-token proof runs against the workspace's own server.

**UI.** The credential form on `/settings/keys` grows a "Custom (OpenAI-compatible)" provider
option and, when it's selected, a Base URL input beneath the key input. The custom row in the
keys list shows its endpoint instead of Phase 10's "Not registered" copy. The chat-model provider
dropdown lists "Custom" once a custom credential exists — same rule as OpenAI/Gemini/Nebius, no
platform fallback.

**Tests.** `set_credential` for `CUSTOM` (missing `base_url` rejected, `base_url` on another
provider rejected, unreachable endpoint rejected, reachable-but-401 accepted); `build_chat_provider`
routing `CUSTOM` to the adapter with the given base URL and refusing it without one; `resolve_chat_model`
carrying `base_url` through for a custom-configured tenant; the chat-model endpoint switching to
`custom` and validating against a fake server at that URL; the chat router streaming through a
custom endpoint end to end.

## 23. Phase 12 — choosing a model from the provider's own list

**Endpoint.** `GET /tenants/current/chat-model/available-models?provider=X` (admin/owner, the
same role that can change the chat model). Resolves the workspace's key for `X` the way
`set_chat_model` does — its own key, or the platform key for Anthropic only — and 422s with
`ChatKeyRequired` when there is none. Calls that provider's `models.list()` on that key and
returns `{"models": [ids…]}`, sorted, after the denylist filter. A provider that rejects the call
or has no `/models` (a minimal custom server) returns 422 with the provider's own message; the UI
treats that as "type it manually", never as a broken page.

**Filtering.** `app/llm/models.py` holds one denylist of substrings per provider — OpenAI's
`embedding`, `whisper`, `tts`, `dall-e`, `moderation`, `davinci`, `babbage`, `audio`, `realtime`,
`transcribe`; Gemini's `embedding`, `aqa`, `imagen`, `veo`; Nebius's `embed`; Anthropic none
(its list is already only Claude models); `CUSTOM` none — this app can't assume anything about a
workspace's own server's naming. Substring matching on the id, lower-cased. Deliberately a
denylist, not an allowlist: a provider's new chat model should appear without a code change here.

**UI.** The chat-model section's Model field becomes a dropdown that loads from the endpoint when
the provider selection changes, pre-selecting the current model when it's in the list. A
"Type a model id instead" toggle swaps it for Phase 10's free-text input, and the free-text input
is what the section falls back to — with the fetch error shown inline — whenever the list can't
be loaded. Save behaves exactly as today: `PUT /tenants/current/chat-model` with whichever value
is in the field.

**Tests.** The denylist per provider against a fixed set of ids; the endpoint on a tenant with no
key for the provider (422); on Anthropic with no own key (platform key, succeeds); against a fake
`models.list()` (filtered, sorted); a provider whose list call fails (422 with its message);
admin-only.

## 24. Phases

| Phase | Deliverable | Est. |
|---|---|---|
| 11 | `Provider.CUSTOM` with a per-credential `base_url`, reachability validation, the seam and settings wired through it, settings UI | 3 days |
| 12 | Available-models endpoint per provider with a denylist filter, model dropdown with a manual-entry fallback in settings | 2 days |

One branch and one pull request per phase, as before.
