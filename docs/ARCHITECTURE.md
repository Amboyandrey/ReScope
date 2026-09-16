# ReScope — Architecture

This describes what was actually built, phase by phase, as a companion to `docs/PLAN.md` (written
up front, describing intent). Where the two disagree, this document — and the code — wins.

## 1. What it is

A multi-tenant CRM that profiles companies from their own website. A member pastes a domain; a
background pipeline reads the site, extracts an overview, products, services, and competencies —
each with a source URL, a quote, and a description — and embeds the result so the tenant can
search its accounts semantically, browse them in a filterable catalogue, or ask a retrieval-grounded
chat that cites the rows it drew from. A light CRM (contacts, notes, tags, saved searches) sits on
top, and a scheduler re-profiles a company periodically and surfaces what changed. Everything —
scraping's Tier 2 agent, and chat independently — runs on the platform's own Anthropic key by
default, but a workspace can bring its own for either: Anthropic and Browser Use for scraping, and
any of Anthropic, OpenAI, Gemini, Nebius, or its own OpenAI-compatible server for chat.

## 2. System shape

```
apps/
  api/    FastAPI + SQLAlchemy 2 (async) + Alembic + Pydantic v2 + structlog
  web/    Next.js 16 (App Router) + React 19 + Tailwind 4
infra/
  docker-compose.yml         dev stack
  docker-compose.prod.yml    production stack, fronted by Caddy
  Dockerfile.{api,scraper,web,caddy}
docs/
  PLAN.md            the up-front design
  ARCHITECTURE.md    this file
```

Inside `apps/api`: routers contain no logic and never touch SQLAlchemy directly; services take
plain arguments, return ORM objects or raise a typed `AppError`, and never import FastAPI. A
router's job is auth/role dependencies in, a Pydantic response model out.

Two background-worker images exist for one reason: Chromium is heavy and occasionally crashes, and
a crash there must never take down the queue that runs embeddings, CSV import work, and the
re-profile scheduler.

- `app/workers/main.py` — the light worker. No browser. Runs the hourly re-profile cron
  (`app.services.reprofile.enqueue_due_reprofiles`).
- `app/workers/scrape_company.py`, run by `app/workers/scraper.py` (its own queue, its own image,
  `max_jobs = 1`) — the only place Chromium is ever launched.

## 3. Tenancy

**Resolution.** `apps/web/proxy.ts` reads the `Host` header, extracts the subdomain, and rewrites
`acme.rescope.app/companies` to the internal route `/t/acme/companies`, stamping the tenant slug
into a header for server components. Every API call the web app makes carries `X-Tenant-Slug`; the
API's `get_tenant_ctx` dependency (`app/deps/tenant.py`) resolves it against the caller's own
membership and returns **404**, not 403, when there is none — a slug for a tenant you're not in
looks identical to a slug that doesn't exist. `api.<domain>` is a separate origin entirely (its own
port in dev, its own Caddy host-match block in production, §13) — it never goes through `proxy.ts`.

**Sessions.** An opaque id in an `httpOnly`, `SameSite=Lax` cookie, `Secure` in every environment
except `development` (`app/core/cookies.py`), scoped `Domain=.<root>` so one login carries across
every tenant subdomain. Resolved against Redis with a sliding TTL (`app/services/sessions.py`);
revocation is a `DEL`. A separate, JS-readable CSRF cookie is echoed back as `X-CSRF-Token` on
every mutating request (double-submit pattern, `app/core/csrf.py`) — no JWTs anywhere.

**Schema rules.** Every tenant-scoped table carries `tenant_id uuid NOT NULL`. A table other rows
hang off of additionally carries `UNIQUE (tenant_id, id)`, so a child can declare a composite
foreign key scoped by tenant:

```sql
FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id) ON DELETE CASCADE
```

A contact can't be pointed at another tenant's company even by a bug that passes the wrong id —
the database refuses the row, not just the application layer.

**Row-level security.** The API and workers connect as `rescope_app`, a role with CRUD and no DDL
(migrations run as the table owner, which Postgres exempts from RLS). Every request's transaction
runs `SET LOCAL app.tenant_id = '<uuid>'` (`set_tenant_scope`, `app/core/db.py`); every tenant
table has a SELECT policy checking exactly that. Writes are deliberately left ungated with their
own permissive policy — see `migrations/_rls.py`'s own docstring for why gating both would demand
every write path, background jobs included, set scope before its very first statement, and why
Postgres's `FORCE ROW LEVEL SECURITY` punishes a table with only a SELECT policy by denying writes
outright rather than leaving them unfiltered. Two tables are excluded from RLS entirely and stay
scoped by an explicit filter in application code instead: `tenants` (a signed-in user's own "list
my tenants" spans no single tenant, and previewing an invitation happens before the caller is a
member of anything) and `invitations` (reachable by token before membership exists). Everything
else — including every Phase 4 CRM table — gets the standard policy, no exceptions.

**Roles.** `viewer < member < admin < owner`; `require_role(minimum)` is one comparison
(`app/models/role.py`). `users.is_superadmin` is unrelated to tenant roles — it gates `/api/v1/admin/*`
(no tenant header at all) for platform-operator concerns: which tenants exist, the scraping
killswitch, and the audit trail of admin actions.

**Local development.** `rescope.localhost` is the root; `*.rescope.localhost` resolves to loopback
on any OS with a standards-conformant resolver (RFC 6761) — no `/etc/hosts` edits. The API listens
on its own port (`:8000`) rather than a subdomain, since a dev machine has no reverse proxy to
route `api.` anywhere.

## 4. Data model

```
plans(id, name, profiles_per_month, deep_runs_per_month, max_companies, max_members,
      reprofile_interval_days, chat_messages_per_month)
tenants(id, slug UNIQUE, name, plan_id, status, settings jsonb, created_at)          -- no RLS
users(id, email UNIQUE, password_hash, is_superadmin, created_at)                    -- no RLS
memberships(tenant_id, user_id, role, created_at)              PK (tenant_id, user_id)
invitations(id, tenant_id, email, role, token_hash, expires_at, accepted_at)         -- no RLS

companies(id, tenant_id, domain, name, website_url, industry, company_type, hq_country,
          hq_city, employee_range, founded_year, socials jsonb, logo_url, overview text,
          profile_status, last_profiled_at, created_by, created_at, updated_at)
          UNIQUE (tenant_id, domain), UNIQUE (tenant_id, id)
offerings(id, tenant_id, company_id, kind product|service, name, description NOT NULL,
          category, url, evidence jsonb, created_at)
competencies(id, tenant_id, company_id,
          kind capability|technology|certification|industry_served|partnership,
          name, description NOT NULL, evidence jsonb, created_at)
embeddings(id, tenant_id, company_id, source_kind, source_id, content text,
          embedding vector(1024), model, created_at)

scrape_jobs(id, tenant_id, company_id, mode fast|deep, status, tier_reached,
          pages_fetched, tokens_in, tokens_out, cost_usd, error,
          queued_at, started_at, finished_at)
scrape_pages(id, tenant_id, job_id, url, status_code, content_hash,
          markdown text, screenshot_key, fetched_at)
profile_changes(id, tenant_id, company_id, job_id, diff jsonb, created_at)

contacts(id, tenant_id, company_id, first_name, last_name, email, title,
          phone, linkedin_url, source, created_at, updated_at)
notes(id, tenant_id, company_id, author_id, body, created_at)
tags(id, tenant_id, name, color)               UNIQUE (tenant_id, name), UNIQUE (tenant_id, id)
company_tags(tenant_id, company_id, tag_id)    PK (tenant_id, company_id, tag_id)
saved_searches(id, tenant_id, owner_id, name, query jsonb)
imports(id, tenant_id, kind, status, row_count, error_count, errors jsonb, created_by, created_at)

tenant_credentials(id, tenant_id, provider anthropic|browser_use|openai|gemini|nebius|custom,
          ciphertext bytea, nonce bytea, wrapped_key bytea, base_url text NULL,
          last4, validated_at, created_by, created_at)          UNIQUE (tenant_id, provider)
conversations(id, tenant_id, owner_id, title, created_at, updated_at)
messages(id, tenant_id, conversation_id, role user|assistant, content text,
          citations jsonb, tokens_in, tokens_out, created_at)

usage_events(id, tenant_id, job_id NULL, kind, model, tokens_in, tokens_out, cost_usd,
          billed_to platform|tenant, created_at)
platform_settings(id, scraping_paused, updated_at)                                    -- singleton
audit_logs(id, tenant_id, actor_id, action, target_type, target_id, metadata jsonb, created_at)
```

`evidence` is a list of `{url, quote}`. Every offering and competency links back to the page and
sentence it was extracted from, so an AI-written profile can be checked rather than trusted blind;
`description` is `NOT NULL` on both (backfilled `''` for pre-Phase-6 rows, filled by the next
re-profile) since it's what gets embedded — search and chat rank on substance, not a bare name.

`tenants.settings` is where two per-workspace choices live rather than as real columns, since both
are one option among what could grow into several free-form preferences: `scrape_provider`
(`custom` or `browser_use_cloud`, §5) and `chat` (`{provider, model}`, §12) — a `Tenant.chat_model`
property falls back to the platform's own Anthropic default when unset, the same shape
`scrape_provider` already had. `usage_events.job_id` is nullable because `CHAT` events (§11) have
no scrape job behind them; the table's own composite foreign key to `scrape_jobs` simply isn't
checked when it's null, Postgres's ordinary `MATCH SIMPLE` behavior.

Quotas are computed on read from `usage_events` for the current calendar month (`services/usage.py`,
`services/quotas.py`) — no rollup table exists yet; adding one changes nothing above the service
boundary if counting ever gets slow.

## 5. The scraping pipeline

Two tiers were built, not three — Tier 2 turned out to need a purpose-built agent loop rather than
the `browser-use` library the plan named (§8), but the tiering itself matches the plan.

**Tier 0 — discovery, no LLM** (`app/scraping/discovery.py`). Normalize the domain, run the SSRF
guard (rejects anything that doesn't resolve to a public address — `app/core/ssrf.py`), read
`robots.txt` and `sitemap.xml` best-effort, pull every same-host link off the homepage, and rank
the combined set by keyword match against the path and anchor text (`about`, `product`, `service`,
`solution`, `industr*`, `capabilit*`, `case-stud*`, `technology`, `platform`, `partner`,
`what-we-do`, …). The homepage itself is always included and ranked first.

**Tier 1 — text extraction** (`app/scraping/render.py`, `app/scraping/extraction.py`). Up to 12
candidate pages (`MAX_CANDIDATE_PAGES`) render with headless Playwright and convert to markdown,
then one structured-output call to `claude-sonnet-5` (`client.messages.parse`, the Pydantic
`ExtractedProfile` schema) returns overview, offerings, and competencies, each offering/competency
carrying its own evidence. This handles the large majority of sites.

**Tier 2 — visual agent, "deep mode"** (`app/scraping/visual_agent.py`). A custom-built loop, not
`browser-use`: that library hard-pins `anthropic==0.76.0`, incompatible with the `anthropic>=1.5.0`
Tier 1 needs for `client.messages.parse`. The loop screenshots the page, sends it to
`claude-opus-5` for one structured `VisualAction` (click / scroll_down / navigate / done), and
repeats up to `MAX_STEPS = 8` — enough to open tabs, accordions, and menus a static crawl would
never find. Whatever it reveals feeds into the same Tier 1 extraction call. Screenshots are
written to a storage volume shared between the `api` and `scraper` containers and served back as
evidence.

**A second Tier 2 provider: Browser Use Cloud** (`app/scraping/browser_use_cloud.py`, §10). A
workspace's `scrape_provider` setting (`custom` or `browser_use_cloud`, stored in
`tenants.settings`) picks which deep-mode agent runs — never a third tier, an alternate
implementation of the same one. `POST /tasks` on Browser Use's hosted API gets the profiling
instruction as `task`, the company's own domain as `startUrl`/`allowedDomains`, `maxSteps = 30`,
and `structuredOutput` set to `ExtractedProfile`'s own JSON schema; `GET /tasks/{id}` is polled on
a 5-second backoff up to a hard 10-minute ceiling (`MAX_WAIT_SECONDS = 600`) — a client timeout
never cancels the remote run, and this pipeline never retries one that hits it. Each step's
`screenshotUrl` downloads into the same shared storage volume the custom agent uses, so evidence
looks identical regardless of which provider ran. The two providers' offerings/competencies merge
by case-insensitive name — whichever copy has the longer description wins, evidence unions — with
company facts preferring the Tier 1 (rendered-page) result and falling back per field. It bills its
own usage kind, `BROWSER_USE_RUN`, counted against `deep_runs_per_month` exactly like a custom deep
run; the key resolves the workspace's own first, then the platform's `BROWSER_USE_API_KEY`, and the
option greys out in settings when neither exists.

**Merge and embed** (`app/scraping/pipeline.py::run_scrape_job`). Tier 1's writes are committed
before extraction runs, so a failed extraction call never rolls back a successful render — a
job-status view sees exactly how far the run actually got. Offerings and competencies for the
company are replaced (deleted, then rewritten) each run, not merged with the previous set; the
company's overview, offering, and competency text is embedded (one row per offering/competency
plus one company-summary row) through the self-hosted embeddings service — best-effort, so a down
or slow embeddings service degrades a company to "profiled but not yet searchable" instead of
failing an otherwise-successful scrape.

**Re-profile** (`app/services/reprofile.py`, §7). An hourly cron job on the light worker
re-enqueues any company whose `last_profiled_at` is older than its plan's
`reprofile_interval_days`. A run past the company's first successful profile diffs the new
snapshot (overview, offering names, competency names) against the one taken right before the run
started, and — only if something actually changed — writes a `profile_changes` row, surfaced by
`GET /tenants/current/companies/{id}/changes`.

**Cost controls.** The platform's own Anthropic key, read from the environment, funds every
tenant's scraping by default — extraction and the visual agent stay Anthropic-only regardless of
what a workspace configures for chat (§12), since both depend on `client.messages.parse` structured
output and vision, neither portable across other providers. A workspace that registers its own
Anthropic key (§10) is exempt from the quota check below, but usage is still recorded, marked
`billed_to = tenant` rather than estimated away. The quota check itself (`services/quotas.py`) runs
before a job is ever enqueued, keyed per plan and per usage kind (`PROFILE` vs `DEEP_PROFILE`,
separately limited, `BROWSER_USE_RUN` sharing `DEEP_PROFILE`'s ceiling). Every model call writes
tokens and a computed USD cost to the `usage_events` ledger (`services/usage.py`). A platform-wide
killswitch (`platform_settings.scraping_paused`, flipped only by a superadmin) is checked both
before enqueue and again inside the worker, since time passes between the two.

## 6. Search

Built: semantic search and similar-companies, both `app/services/search.py`, both a
`cosine_distance` ordering over `embeddings` scoped by tenant, deduplicated to the single best
match per company so one company matching on three offerings doesn't crowd out the next-best
company that matched once. `MAX_DISTANCE = 0.6` keeps genuinely unrelated results out.

Not built: hybrid (`tsvector` + vector) search and an HNSW index were both in the original plan
(`docs/PLAN.md` §6) but cut — the brute-force `cosine_distance` scan is the right tool at the scale
a portfolio-sized deployment actually reaches, and adding either is a query-layer change with no
migration required to revisit later if a real tenant's company count ever warrants it.

## 7. Usage-based scheduling: the re-profile cron

`app/workers/main.py`'s `WorkerSettings.cron_jobs` runs `run_scheduled_reprofiles` once an hour
(arq's own `cron(..., minute=0)`). It calls `enqueue_due_reprofiles`, which — since a due company's
SELECT is RLS-gated and `companies` carries no cross-tenant escape hatch the way `tenants` does —
loops every tenant explicitly, setting `app.tenant_id` before querying that tenant's own due
companies, rather than attempting one cross-tenant query. A tenant already at its monthly quota is
skipped (not failed) for the rest of that tick; the next hourly run tries again once its month's
counters reset or its usage otherwise has room.

## 8. Light CRM

Contacts, notes, tags (with a company-tag join table), personal saved searches, and CSV import —
all under `app/{models,schemas,services,routers/v1}/{crm.py,contacts.py,notes.py,tags.py,
saved_searches.py,import_job.py}` and one migration (`0007_crm.py`) covering every table at once.
No deals, no pipeline stages — the profiling pipeline is the product; this layer only makes it
usable day to day. CSV import (`app/services/imports.py`) runs synchronously rather than as a
background job (files are small enough not to need one), matches header aliases case-insensitively
against a small known set, and tolerates a bad row by skipping and recording it rather than
aborting the whole file.

## 9. Catalogue

**API.** `GET /tenants/current/catalogue` (viewer) takes optional `country`, `company_type`,
`industry`, `competency_kind`, `tag`, and `q`; the structured filters run as SQL, and `q` runs the
existing semantic search (§6) first and intersects the result. `GET /tenants/current/catalogue/facets`
returns the distinct values and counts behind every filter, so the UI never offers an option with
zero matching companies.

**UI.** `/catalogue`: a filter rail (country, type, industry, competency kind, tag) on the left,
company cards on the right — name, country/type/industry line, overview excerpt, and the first few
offerings/competencies each showing its description. A company's own profile page shows every
extracted fact and renders every offering/competency's description under its name, plus a
"Re-profile now" button (member role, quota-checked) so an existing company can pick up newly
extracted fields without waiting for the scheduler.

## 10. Bring-your-own provider keys

**Storage and crypto.** `app/core/crypto.py`: AES-256-GCM envelope encryption — a random 256-bit
data key encrypts the secret, the data key itself is wrapped by a master key from the environment
(`MASTER_KEY`), so rotating the master key only means rewrapping data keys, never re-encrypting
every stored secret. `tenant_credentials` (§4) holds one row per `(tenant_id, provider)`;
`services/credentials.py`'s `set_credential` / `get_active_credential` / `remove_credential` /
`decrypt_credential_key` are the only code that ever touches plaintext, and only the last of those,
on the request that's about to make the actual model call. Registering or removing a key writes an
audit row carrying `last4`, never the key itself.

**Validation on save.** Before a key is stored, it's proven to authenticate against its own
provider — the cheapest real call each one exposes, never a paid or heavy one: Anthropic gets a
one-token `messages.create`; Browser Use gets `GET /api/v2/billing/account`; OpenAI, Gemini, and
Nebius (their shared adapter, §12) get `GET /models`; a workspace's own `custom` endpoint (§12) is
only proven *reachable* — any real HTTP response, not a connection failure — since a self-hosted
server doesn't reliably implement `/models` the way a hosted one does. A key that fails validation
is rejected with the provider's own error and never stored.

**Resolution and quota exemption.** `services/llm.py::resolve_anthropic_key` returns the tenant's
own key if registered, else the platform's, and which one it was; every Anthropic call site
(extraction, the visual agent, and chat's own default) goes through it. A tenant on its own key is
exempt from the corresponding quota (`assert_within_quota`, `assert_within_chat_quota`) — usage is
still recorded, `billed_to = tenant` rather than `platform`. Chat's own key resolution
(`resolve_chat_model`, §12) generalizes this same exemption to whichever of the four chat providers
a workspace has configured, not just Anthropic.

**Settings UI.** `/settings/keys` (admin/owner): one row per provider — Anthropic, Browser Use,
OpenAI, Gemini, Nebius, and Custom (with its own Base URL field) — showing a masked `last4` and
when it was last validated, with replace/remove actions. The scrape-provider choice (§5) and the
chat-provider/model choice (§12) both live on the same page, since both are simply "which of my
registered keys handles this."

## 11. Chat

**Retrieval.** The question is embedded and the top 12 `embeddings` rows across the tenant are
taken by `cosine_distance` — the same query search (§6) uses, but without the per-company dedupe,
since an answer wants every relevant row, not just the single best match per company. Results
group by company into a context block: name, a facts line, the overview, then every retrieved
offering/competency with its own description. The catalogue's own filters (§9) narrow retrieval
before ranking, so a scoped question ("which of my German accounts…") doesn't rely on the model
doing that narrowing itself.

**Generation and citations.** The resolved chat model (§12; `claude-sonnet-5` on the platform key
until a workspace configures otherwise) streams a reply as Server-Sent Events from a
`StreamingResponse` — no Redis stream, no resume; a dropped connection loses the in-flight reply
and the client just re-asks. The system prompt forbids answering from anything outside the given
context and requires a `[Company Name]` citation for any claim. After the stream finishes,
`resolve_citations` (`app/services/chat.py`) finds every `[Name]` in the finished answer that
actually names a company present in that turn's retrieved context, and cites that company's own
closest-matching retrieved row (`{company_id, source_kind, source_id}`) — a bracketed name that
doesn't match anything retrieved is silently dropped rather than cited, since it was never grounded
to begin with. The last 10 turns of conversation history ride along as prior messages; retrieval
itself only ever runs on the latest question.

**Persistence and limits.** Every user and assistant turn is a `messages` row; the assistant's
carries its resolved `citations`. One user message counts one `CHAT` usage event against
`chat_messages_per_month`, skipped for a tenant on its own key for whichever provider it's
configured to chat on (§10). Conversations are personal — owner-scoped, like saved searches, not
shared across a workspace.

**UI.** `/chat`: a conversation list on the left, the active thread on the right, streamed tokens,
and citation chips under each answer linking to the company's own profile.

## 12. The chat provider seam — any of four providers, or your own

Phase 9 built chat on Anthropic and the platform's key alone. Three phases later (Parts 3 and 4 of
`docs/PLAN.md`), a workspace can chat on Anthropic, OpenAI, Gemini, Nebius, or any OpenAI-compatible
server it runs itself — each on its own key, its own choice of model, browsable from a live model
list. Extraction and the visual agent (§5) never participate in any of this; they stay on Anthropic
for `client.messages.parse` structured output and vision, neither portable across the other
providers.

**The seam** (`app/llm/`). One `ChatProvider` protocol — `stream_text(system, messages, model,
max_tokens)` yielding text chunks, plus a `usage` property read once the stream is exhausted. Two
implementations: `AnthropicChat` (the native SDK) and `OpenAICompatibleChat` (the `openai` SDK,
parameterized by `base_url`), which alone covers OpenAI, Gemini (through its own OpenAI-compatible
endpoint), Nebius, and a workspace's own `CUSTOM` server — four `Provider` values, one adapter,
distinguished only by which URL it points at. `build_chat_provider(provider, api_key,
base_url=None)` is the only place that maps a `Provider` to a class and a URL; the chat router
calls the protocol and never imports an SDK directly. Streamed usage comes back on
`stream_options={"include_usage": True}`'s final chunk; a provider that never reports it leaves
`usage` as `None` rather than a guessed number.

**Resolution.** `resolve_chat_model(db, tenant)` (`app/services/llm.py`) returns the provider,
model, key, `base_url` (only ever set for `CUSTOM`), and `billed_to` a tenant's next chat message
would actually run on — the tenant's saved `(provider, model)` choice on its own key for that
provider, or the Anthropic default on the tenant's own Anthropic key, or the Anthropic default on
the platform key, in that order. `resolve_key_for_chat_provider` is the shared piece both this and
the settings endpoint below use, so key resolution has one implementation, not two.

**Bringing your own OpenAI-compatible endpoint.** `Provider.CUSTOM`'s credential carries a
`base_url` alongside its key (§4) — the only provider whose endpoint isn't a constant
`build_chat_provider` already knows. Since a self-hosted server (vLLM, Ollama, a company gateway)
doesn't reliably implement `GET /models`, its credential validates by reachability alone (§10): any
real HTTP response counts, even a 401 or 404, and only a connection failure is rejected. The actual
proof that key, endpoint, and model all work together is the same one-token `validate_chat_model`
call every provider goes through when the chat model itself is saved (below) — reachability was
never meant to be the real gate, even for the named providers.

**Choosing a model.** `PUT /tenants/current/chat-model` (admin/owner) with `{provider, model}`:
refuses a provider the workspace has no usable key for, then proves the specific model actually
answers with a one-token completion (`validate_chat_model`) before writing `tenants.settings.chat`.
A mistyped model id, or a key without access to the model asked for, fails here — at settings
time — rather than on the tenant's next real chat message. `GET
/tenants/current/chat-model/available-models?provider=X` (same role) backs a model picker: it
resolves the same key `set_chat_model` would, calls that provider's own `models.list()` — Anthropic
included, via its SDK's own Models API — and returns the ids, filtered by a small per-provider
denylist (`app/llm/models.py`) that drops known non-chat families (embeddings, audio, image,
moderation, legacy completions). Deliberately a denylist, not an allowlist, so a provider's new
chat model shows up without a code change. The list is an affordance for the settings UI, never a
gate — `validate_chat_model` remains the only thing that decides whether a model id is actually
accepted.

**Metering and quota.** `assert_within_chat_quota`'s BYOK exemption (§10) checks whichever provider
a tenant is currently configured to chat on, not just Anthropic — `has_own_chat_key` generalizes
Phase 7's Anthropic-only check the same way `resolve_chat_model` generalizes `resolve_anthropic_key`.
A chat run on any provider but Anthropic has no rate card, so its `usage_events` row records
`cost_usd = 0` rather than an invented number; tokens and `billed_to = tenant` are still recorded
exactly as they are for Anthropic.

**UI.** `/settings/keys` grows a "Chat model" section beneath the credentials list: a provider
dropdown limited to Anthropic plus whichever of the other four the workspace holds a key for, and a
Model field that fetches and shows a dropdown from the available-models endpoint above —
pre-selecting the currently-configured model — with a "type a model id instead" toggle, which is
also where the field automatically falls back (with the fetch error shown inline) whenever the list
can't be loaded at all.

## 13. Deployment

**Development** (`infra/docker-compose.yml`): seven services — `postgres` (pgvector image),
`redis`, `embeddings` (self-hosted text-embeddings-inference running `Qwen/Qwen3-Embedding-0.6B`,
1024 dimensions fixed in the schema), `api`, `worker`, `scraper`, `web` — each on a host port, no
reverse proxy. The web container needs `API_INTERNAL_URL` (the container-network address) as a
plain server-side env var distinct from the browser-facing, build-time-inlined
`NEXT_PUBLIC_API_URL`, since the latter doesn't resolve from inside the container's own network.

**Production** (`infra/docker-compose.prod.yml`, `infra/Caddyfile`, `infra/Dockerfile.caddy`): the
same services, plus `caddy`, the only service publishing a host port (`80`/`443`). Caddy
host-matches `api.<domain>` to the API container and `<domain>` / `*.<domain>` to the web
container — the split dev gets for free from two different ports collapses to one port in
production, so Caddy has to make that routing decision explicitly, before a tenant subdomain ever
reaches Next.js. A wildcard certificate needs the ACME DNS-01 challenge (HTTP-01 can't prove
ownership of a subdomain that doesn't exist yet), which needs a Caddy build carrying a DNS provider
plugin — `Dockerfile.caddy` builds one via `xcaddy` for Cloudflare; swapping providers means
swapping both that Dockerfile and the Caddyfile's `dns` directive together. See
`infra/.env.example` for every variable a deploy needs, including the one genuine manual step:
the `rescope_app` role's password is set once, by the first `alembic upgrade head` against a fresh
database (`migrations/_rls.py` reads it from `RESCOPE_APP_ROLE_PASSWORD`, falling back to a
dev-only default), and rotating it afterward needs a manual `ALTER ROLE` to match.

A `demo` tenant can be seeded on any deploy without a real Anthropic key or a completed scrape:
`app/scripts/seed_demo.py` writes two already-profiled fictional companies straight into the
database (bypassing the pipeline entirely), each with contacts, a note, and a tag, so there's
something to show immediately. It's idempotent — a second run is a no-op once the tenant exists.

## 14. Security posture

- Passwords: Argon2id (`app/core/security.py`).
- Sessions: opaque, Redis-backed, revocable by deletion — never a JWT that outlives a `DEL`.
- CSRF: double-submit cookie, checked on every mutating request.
- SSRF: every user-supplied URL (a company's domain) is resolved and checked against private/
  loopback/link-local ranges before anything fetches it — both at company-creation time and again
  inside Tier 0.
- Tenant isolation: three independent layers (header-only tenant resolution, composite foreign
  keys, row-level security) rather than any single one being load-bearing alone.
- Secrets: the platform's own Anthropic key lives in the environment, never a database row, and
  never appears on a response schema. A workspace's own key, for any of the six providers it can
  register (§10), is envelope-encrypted at rest and only ever decrypted on the request about to use
  it — never returned in a response, `last4` being the only trace of it a settings page ever shows.
- Every privileged action (company deletion by someone other than its creator, an admin/owner
  membership change, the platform killswitch) writes an `audit_logs` row.

## 15. Testing

Tests run against a real Postgres and Redis — `tests/conftest.py` rewrites `DATABASE_URL` to a
`_test`-suffixed database and a separate Redis db index before the app ever loads settings, so the
suite structurally cannot touch a dev stack's data, and TRUNCATEs every table after each test
(except `plans` and `platform_settings`, migration-seeded reference/singleton data with no
migration left to reseed them once the schema is at head). LLM calls are mocked
(`unittest.mock.AsyncMock` against the pipeline module's own names); Playwright-dependent tests
launch a real headless Chromium with only the model call mocked, closer to what actually runs in
production than mocking the browser too.

## 16. Conventions

- Routers contain no logic; services take plain arguments and never import FastAPI.
- One Alembic revision per schema change, with a docstring explaining anything non-obvious —
  particularly any RLS exception, since "no policy at all" and "an unfiltered policy" fail very
  differently under `FORCE ROW LEVEL SECURITY`.
- Secrets are never fields on a response schema.
- Every privileged action writes an audit row.
- A one-line explanation precedes any function whose purpose isn't obvious from its name and
  signature alone.
- Work happens on a branch per phase, committed and pushed incrementally, and lands through a pull
  request the repository owner reviews and merges.
