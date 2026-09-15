# ReScope — Architecture

This describes what was actually built, phase by phase, as a companion to `docs/PLAN.md` (written
up front, describing intent). Where the two disagree, this document — and the code — wins.

## 1. What it is

A multi-tenant CRM that profiles companies from their own website. A member pastes a domain; a
background pipeline reads the site, extracts an overview, products, services, and competencies —
each with a source URL and quote — and embeds the result so the tenant can search its accounts
semantically. A light CRM (contacts, notes, tags, saved searches) sits on top, and a scheduler
re-profiles a company periodically and surfaces what changed.

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
port in dev, its own Caddy host-match block in production, §9) — it never goes through `proxy.ts`.

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
      reprofile_interval_days)
tenants(id, slug UNIQUE, name, plan_id, status, settings jsonb, created_at)          -- no RLS
users(id, email UNIQUE, password_hash, is_superadmin, created_at)                    -- no RLS
memberships(tenant_id, user_id, role, created_at)              PK (tenant_id, user_id)
invitations(id, tenant_id, email, role, token_hash, expires_at, accepted_at)         -- no RLS

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

usage_events(id, tenant_id, job_id, kind, model, tokens_in, tokens_out, cost_usd, created_at)
platform_settings(id, scraping_paused, updated_at)                                    -- singleton
audit_logs(id, tenant_id, actor_id, action, target_type, target_id, metadata jsonb, created_at)
```

`evidence` is a list of `{url, quote}`. Every offering and competency links back to the page and
sentence it was extracted from, so an AI-written profile can be checked rather than trusted blind.

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

**Cost controls.** One Anthropic key, read from the environment, funds every tenant's scraping —
no tenant ever supplies or sees its own key, so per-tenant quotas (not per-tenant billing) are what
keeps one tenant from exhausting the platform's spend. A quota check (`services/quotas.py`) runs
before a job is ever enqueued, keyed per plan and per usage kind (`PROFILE` vs `DEEP_PROFILE`,
separately limited). Every model call writes tokens and a computed USD cost to the `usage_events`
ledger (`services/usage.py`). A platform-wide killswitch (`platform_settings.scraping_paused`,
flipped only by a superadmin) is checked both before enqueue and again inside the worker, since
time passes between the two.

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

## 9. Deployment

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

## 10. Security posture

- Passwords: Argon2id (`app/core/security.py`).
- Sessions: opaque, Redis-backed, revocable by deletion — never a JWT that outlives a `DEL`.
- CSRF: double-submit cookie, checked on every mutating request.
- SSRF: every user-supplied URL (a company's domain) is resolved and checked against private/
  loopback/link-local ranges before anything fetches it — both at company-creation time and again
  inside Tier 0.
- Tenant isolation: three independent layers (header-only tenant resolution, composite foreign
  keys, row-level security) rather than any single one being load-bearing alone.
- Secrets: the platform's own Anthropic key lives in the environment, never a database row, and
  never appears on a response schema.
- Every privileged action (company deletion by someone other than its creator, an admin/owner
  membership change, the platform killswitch) writes an `audit_logs` row.

## 11. Testing

Tests run against a real Postgres and Redis — `tests/conftest.py` rewrites `DATABASE_URL` to a
`_test`-suffixed database and a separate Redis db index before the app ever loads settings, so the
suite structurally cannot touch a dev stack's data, and TRUNCATEs every table after each test
(except `plans` and `platform_settings`, migration-seeded reference/singleton data with no
migration left to reseed them once the schema is at head). LLM calls are mocked
(`unittest.mock.AsyncMock` against the pipeline module's own names); Playwright-dependent tests
launch a real headless Chromium with only the model call mocked, closer to what actually runs in
production than mocking the browser too.

## 12. Conventions

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
